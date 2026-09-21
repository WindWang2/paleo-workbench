// versioning.cpp — C++ port of paleo_workbench/workflow/versioning.py
// (CONV-33 route A2). See include/pwb/workflow_runtime/versioning.hpp.
//
// All project access goes through the Json seam (D4): the root is the
// `.paleo.json` document view; a missing section is the empty list, a
// missing/null scalar is the model default. Mutations (finalize) write
// back in place. Clock calls (make_id / now_iso) fire in EXACTLY the
// Python order — pydantic default factories fire in field-declaration
// order, and the oracle freezes that interleaving:
//   fresh VersionSet: id → created_at → updated_at, then
//   build_snapshot's VersionSnapshot: id → created_at, then
//   finalized_at → updated_at → draft.updated_at → run.updated_at.
//
// Content fingerprint byte format (L31-32) — NOT the compact-separator
// canonical hash of constraint_versions / workflow_spec:
//   json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
// with DEFAULT separators (indent=None → (", ", ": ")), i.e.
//   {"facies": [], "horizon": "H1", "id": "m1", "labels": [], ...}
// Keys are sorted at EVERY nesting level; floats use Python repr
// (shortest round-trip, via factor_host::python_repr_double); non-ASCII
// stays raw UTF-8. default=str never fires — payload values are already
// JSON-native in the document view (deviation-free seam).

#include <pwb/workflow_runtime/versioning.hpp>

#include <pwb/domain/sha256.hpp>
#include <pwb/domain/text.hpp>
#include <pwb/factor_host/canonical_json.hpp>

#include "python_compat.hpp"

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace pwb::workflow_runtime {

using pwb::domain::Json;  // .cpp-local alias (header spells domain::Json)

// Defined below (test-only byte-level seam, declared in
// versioning_test.cpp — not part of the frozen header).
[[nodiscard]] std::string versioning_fingerprint_raw_bytes(
    const domain::Json& map_doc);

namespace {

using pwb::domain::Sha256;
using pycompat::dict_get;

// ------------------------------------------------------ Json seam helpers --

const Json& empty_array() {
    static const Json kEmpty = Json::array();
    return kEmpty;
}

const Json& empty_object() {
    static const Json kEmpty = Json::object();
    return kEmpty;
}

// Section view: missing / null / wrong-type section ≙ empty list.
const Json& array_field(const Json& obj, const char* key) {
    if (!obj.is_object()) return empty_array();
    const auto it = obj.find(key);
    if (it == obj.end() || !it->is_array()) return empty_array();
    return *it;
}

// view_state or {} — a null view_state is {} (Python `or {}`).
const Json& object_field(const Json& obj, const char* key) {
    if (!obj.is_object()) return empty_object();
    const auto it = obj.find(key);
    if (it == obj.end() || !it->is_object()) return empty_object();
    return *it;
}

// Model str field (missing / null / wrong type → "", the seam default).
std::string string_field(const Json& obj, const char* key) {
    if (!obj.is_object()) return {};
    const auto it = obj.find(key);
    if (it == obj.end() || it->is_null() || !it->is_string()) return {};
    return it->get<std::string>();
}

// `str | None` field — null → nullopt; "" is a real value (kept for the
// snapshot's contour_draft_id, falsy for lookups).
std::optional<std::string> nullable_string_field(const Json& obj,
                                                 const char* key) {
    if (!obj.is_object()) return std::nullopt;
    const auto it = obj.find(key);
    if (it == obj.end() || it->is_null() || !it->is_string()) {
        return std::nullopt;
    }
    return it->get<std::string>();
}

std::string lower_ascii(std::string value) {
    return domain::lower_ascii(value);  // shared impl (#1392)
}

// _linked_qc_report (L44): last report (reversed scan) linked to the map.
const Json* linked_qc_report(const Json& project,
                             const std::string& map_document_id) {
    const Json& reports = array_field(project, "quality_reports");
    for (auto it = reports.rbegin(); it != reports.rend(); ++it) {
        if (it->is_object() &&
            string_field(*it, "linked_map_document_id") == map_document_id) {
            return &*it;
        }
    }
    return nullptr;
}

// _count_contour_segments (L35): segment count of the linked draft.
std::int64_t count_contour_segments(
    const Json& project, const std::optional<std::string>& draft_id) {
    if (!draft_id || draft_id->empty()) return 0;  // Python falsy draft_id
    for (const Json& draft : array_field(project, "contour_drafts")) {
        if (draft.is_object() && string_field(draft, "id") == *draft_id) {
            return static_cast<std::int64_t>(
                array_field(draft, "segments").size());
        }
    }
    return 0;
}

// ------------------------------------------------ fingerprint byte stream --

// json.dumps string escaping with ensure_ascii=False: ", \ and the C0
// escapes (short forms first), everything else raw UTF-8 bytes.
void append_escaped(std::string& out, const std::string& text) {
    out += '"';
    for (char raw : text) {
        const auto c = static_cast<unsigned char>(raw);
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\b': out += "\\b"; break;
            case '\f': out += "\\f"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    char buffer[8];
                    std::snprintf(buffer, sizeof buffer, "\\u%04x", c);
                    out += buffer;
                } else {
                    out += static_cast<char>(c);
                }
        }
    }
    out += '"';
}

// json.dumps(..., sort_keys=True, ensure_ascii=False, default=str) with
// the DEFAULT (spaced) separators (", ", ": ") and indent=None. Keys are
// sorted byte-wise (== Python str code-point order) at EVERY level.
void encode_python_dumps(std::string& out, const Json& value) {
    if (value.is_null()) {
        out += "null";
    } else if (value.is_boolean()) {
        out += value.get<bool>() ? "true" : "false";
    } else if (value.is_number_integer()) {
        out += std::to_string(value.get<std::int64_t>());
    } else if (value.is_number_float()) {
        out += pwb::factor_host::python_repr_double(value.get<double>());
    } else if (value.is_string()) {
        append_escaped(out, value.get_ref<const std::string&>());
    } else if (value.is_array()) {
        out += '[';
        bool first = true;
        for (const Json& item : value) {
            if (!first) out += ", ";
            first = false;
            encode_python_dumps(out, item);
        }
        out += ']';
    } else if (value.is_object()) {
        std::vector<const std::string*> keys;
        keys.reserve(value.size());
        for (auto it = value.begin(); it != value.end(); ++it) {
            keys.push_back(&it.key());
        }
        std::sort(keys.begin(), keys.end(),
                  [](const std::string* a, const std::string* b) {
                      return *a < *b;
                  });
        out += '{';
        bool first = true;
        for (const std::string* key : keys) {
            if (!first) out += ", ";
            first = false;
            append_escaped(out, *key);
            out += ": ";
            encode_python_dumps(out, value.at(*key));
        }
        out += '}';
    }
}

// _fingerprint_map (L22): sha256[:16] over the exact Python dumps bytes.
std::string fingerprint_map(const Json& map_doc) {
    return Sha256::of_bytes(versioning_fingerprint_raw_bytes(map_doc))
        .substr(0, 16);
}

}  // namespace

// Test-only seam (declared in versioning_test.cpp, NOT in the frozen
// header): the exact json.dumps byte stream _fingerprint_map hashes —
// frozen by the oracle for byte-level assertion.
std::string versioning_fingerprint_raw_bytes(const domain::Json& map_doc) {
    Json payload = Json::object();
    payload["facies"] = array_field(map_doc, "facies_polygons");
    payload["horizon"] = string_field(map_doc, "linked_target_horizon");
    payload["id"] = string_field(map_doc, "id");
    payload["labels"] = array_field(map_doc, "label_features");
    payload["lines"] = array_field(map_doc, "line_features");
    payload["wells"] = array_field(map_doc, "well_overlays");
    std::string raw;
    encode_python_dumps(raw, payload);
    return raw;
}

// ---------------------------------------------------------- build_snapshot --

project::VersionSnapshot build_snapshot(const domain::Json& project,
                                        const domain::Json& map_doc,
                                        const std::string& note,
                                        const std::string& created_by,
                                        const project::ModelClock& clock) {
    const std::string map_id = string_field(map_doc, "id");
    const auto draft_id =
        nullable_string_field(map_doc, "linked_contour_draft_id");
    const Json* qc = linked_qc_report(project, map_id);

    const std::string horizon =
        string_field(map_doc, "linked_target_horizon");
    // Factor tasks matching the horizon ("" horizon → all tasks, L84-89).
    std::vector<std::string> factor_ids;
    for (const Json& task : array_field(project, "factor_map_tasks")) {
        if (horizon.empty() ||
            string_field(task, "target_horizon") == horizon) {
            factor_ids.push_back(string_field(task, "id"));
        }
    }

    project::VersionSnapshot snap;
    snap.id = clock.make_id("vsnap");  // pydantic factory order: id, …
    snap.map_document_id = map_id;
    snap.contour_draft_id = draft_id;
    snap.quality_report_id =
        qc ? std::optional<std::string>(string_field(*qc, "id"))
           : std::nullopt;
    snap.factor_task_ids = std::move(factor_ids);
    snap.map_name = string_field(map_doc, "name");
    snap.target_horizon = horizon;
    snap.line_feature_count = static_cast<std::int64_t>(
        array_field(map_doc, "line_features").size());
    snap.facies_count = static_cast<std::int64_t>(
        array_field(map_doc, "facies_polygons").size());
    snap.contour_segment_count = count_contour_segments(project, draft_id);
    snap.qc_status =
        qc ? string_field(*qc, "status") : std::string("unchecked");
    snap.note = note;
    snap.content_fingerprint = fingerprint_map(map_doc);
    snap.created_at = clock.now_iso();  // … then created_at (declaration)
    snap.created_by = created_by;
    return snap;
}

// ---------------------------------------------------- finalize_map_version --

project::VersionSet finalize_map_version(domain::Json& project,
                                         const std::string& map_document_id,
                                         const FinalizeOptions& options,
                                         const FinalizeDeps& deps) {
    // Gate 0 — unknown map document (L121-126).
    const Json* map_doc = nullptr;
    for (const Json& doc : array_field(project, "paleomap_documents")) {
        if (doc.is_object() && string_field(doc, "id") == map_document_id) {
            map_doc = &doc;
            break;
        }
    }
    if (map_doc == nullptr) {
        throw std::invalid_argument(
            std::string(kErrUnknownMapDocumentPrefix) + map_document_id);
    }
    // Copy the doc view: the sections below mutate `project` in place and
    // the view must stay read-stable (Python holds the model object).
    const Json map_view = *map_doc;

    // Gates 1-3 — H3 trust ladder (L128-141). `production is False` is a
    // STRICT boolean identity check: 0 / "" / null do not trip it.
    const Json& vs_state = object_field(map_view, "view_state");
    if (pycompat::truthy(dict_get(vs_state, "is_demo_draft", Json(nullptr)))) {
        throw std::invalid_argument(std::string(kErrDemoDraftFinalize));
    }
    const auto production = vs_state.find("production");
    const bool production_is_false =
        production != vs_state.end() && production->is_boolean() &&
        !production->get<bool>();
    if (production_is_false) {
        if (string_field(vs_state, "lineage") == "untracked") {
            throw std::invalid_argument(std::string(kErrUntrackedLineage));
        }
        throw std::invalid_argument(std::string(kErrNonProduction));
    }

    // Gates 4-5 — optional QC pass requirement (L143-148). The message
    // interpolates the ORIGINAL status; only the membership test lowers.
    const Json* qc = linked_qc_report(project, map_document_id);
    if (options.require_qc_pass) {
        if (qc == nullptr) {
            throw std::invalid_argument(std::string(kErrQcNotRun));
        }
        const std::string status = string_field(*qc, "status");
        const std::string lowered = lower_ascii(status);
        if (lowered == "error" || lowered == "failed" ||
            lowered == "critical") {
            throw std::invalid_argument(std::string(kErrQcNotPassedPrefix) +
                                        status +
                                        std::string(kErrQcNotPassedSuffix));
        }
    }

    const std::string horizon = string_field(map_view, "linked_target_horizon");

    Json* sets = nullptr;
    if (project.is_object()) {
        const auto sets_it = project.find("version_sets");
        if (sets_it != project.end() && sets_it->is_array()) {
            sets = &*sets_it;
        }
    }

    // Supersede prior finals for this horizon (L151-155) — stamps first.
    if (sets != nullptr) {
        for (Json& vs : *sets) {
            if (vs.is_object() &&
                string_field(vs, "target_horizon") == horizon &&
                string_field(vs, "status") == "final") {
                vs["status"] = "superseded";
                vs["updated_at"] = deps.clock.now_iso();
            }
        }
    }

    // _version_set_for_horizon (L51-70): first non-superseded set for the
    // horizon, else create (id/created_at/updated_at factories in
    // declaration order) linked to the LAST compilation run.
    Json* vset = nullptr;
    if (sets != nullptr) {
        for (Json& vs : *sets) {
            if (vs.is_object() &&
                string_field(vs, "target_horizon") == horizon &&
                string_field(vs, "status") != "superseded") {
                vset = &vs;
                break;
            }
        }
    }
    if (vset == nullptr) {
        Json created = Json::object();
        created["id"] = deps.clock.make_id("vset");
        created["name"] =
            (horizon.empty() ? std::string("未指定层位") : horizon) +
            " 定稿版本集";
        created["target_horizon"] = horizon;
        created["status"] = "open";
        created["snapshots"] = Json::array();
        created["active_snapshot_id"] = nullptr;
        created["finalized_by"] = "";
        created["finalized_at"] = nullptr;
        const Json& runs = array_field(project, "compilation_runs");
        created["linked_compilation_run_id"] =
            runs.empty() ? Json(nullptr)
                         : Json(string_field(runs.back(), "id"));
        created["created_at"] = deps.clock.now_iso();
        created["updated_at"] = deps.clock.now_iso();
        if (sets == nullptr) {
            if (!project.is_object()) {
                project = Json::object();
            }
            sets = &project["version_sets"];
            *sets = Json::array();
        }
        sets->push_back(std::move(created));
        vset = &sets->back();
    }

    // Snapshot + final stamping (L157-165).
    project::VersionSnapshot snap = build_snapshot(
        project, map_view, options.note, options.operator_, deps.clock);
    Json* snapshots = &(*vset)["snapshots"];
    if (!snapshots->is_array()) {
        *snapshots = Json::array();
    }
    snapshots->push_back(snap.to_dict());
    (*vset)["active_snapshot_id"] = snap.id;
    (*vset)["status"] = "final";
    (*vset)["finalized_by"] = options.operator_;
    (*vset)["finalized_at"] = deps.clock.now_iso();
    (*vset)["updated_at"] = deps.clock.now_iso();

    // Linked ContourDraft → final (L167-173). Missing section → no draft
    // can match (Python list stays empty; no section is created).
    const auto draft_id =
        nullable_string_field(map_view, "linked_contour_draft_id");
    if (draft_id && !draft_id->empty() && project.is_object()) {
        const auto drafts_it = project.find("contour_drafts");
        if (drafts_it != project.end() && drafts_it->is_array()) {
            for (Json& draft : *drafts_it) {
                if (draft.is_object() &&
                    string_field(draft, "id") == *draft_id) {
                    draft["status"] = "final";
                    draft["updated_at"] = deps.clock.now_iso();
                    break;
                }
            }
        }
    }

    // Compilation run bookkeeping (L175-183): the LAST run unconditionally
    // gets the active map (+ active qc when linked), status bump from the
    // four in-flight states, always re-stamped.
    if (project.is_object()) {
        const auto runs_it = project.find("compilation_runs");
        if (runs_it != project.end() && runs_it->is_array() &&
            !runs_it->empty()) {
            Json& run = runs_it->back();
            run["active_paleomap_document_id"] = map_document_id;
            if (qc != nullptr) {
                run["active_quality_report_id"] = string_field(*qc, "id");
            }
            const std::string status = string_field(run, "status");
            if (status == "draft" || status == "running" ||
                status == "review_required" || status == "blocked") {
                run["status"] = "export_ready";
            }
            run["updated_at"] = deps.clock.now_iso();
        }
    }

    // Catalog provenance (L185-203): best-effort. A null sink ≙
    // get_catalog() → None (skip silently); a throwing sink must never
    // fail the finalize (Python broad-except, logged not re-raised).
    if (deps.finalize_sink != nullptr) {
        try {
            deps.finalize_sink->register_finalize_run(
                snap, options.operator_, options.note,
                string_field(*vset, "id"));
        } catch (...) {  // deliberate parity with `except Exception: _log.debug`
        }
    }

    return project::VersionSet::from_dict(*vset);
}

// --------------------------------------------------- active_final_snapshot --

std::optional<project::VersionSnapshot> active_final_snapshot(
    const domain::Json& project, const std::string& target_horizon) {
    const Json* last_final = nullptr;
    for (const Json& vs : array_field(project, "version_sets")) {
        if (!vs.is_object() || string_field(vs, "status") != "final") {
            continue;
        }
        if (!target_horizon.empty() &&
            string_field(vs, "target_horizon") != target_horizon) {
            continue;
        }
        last_final = &vs;
    }
    if (last_final == nullptr) return std::nullopt;

    const Json& snapshots = array_field(*last_final, "snapshots");
    if (snapshots.empty()) return std::nullopt;
    const auto active_id =
        nullable_string_field(*last_final, "active_snapshot_id");
    if (active_id && !active_id->empty()) {
        for (const Json& snap : snapshots) {
            if (snap.is_object() && string_field(snap, "id") == *active_id) {
                return project::VersionSnapshot::from_dict(snap);
            }
        }
    }
    // 末位 fallback: no/blank/dangling active_snapshot_id (L221-226).
    return project::VersionSnapshot::from_dict(snapshots.back());
}

// ----------------------------------------------------- version_set_summary --

domain::Json version_set_summary(const domain::Json& project) {
    std::int64_t total = 0;
    std::int64_t finals = 0;
    std::int64_t open = 0;
    const Json* last_final = nullptr;
    for (const Json& vs : array_field(project, "version_sets")) {
        ++total;
        if (!vs.is_object()) continue;
        const std::string status = string_field(vs, "status");
        if (status == "final") {
            ++finals;
            last_final = &vs;
        } else if (status == "open") {
            ++open;
        }
    }
    Json out = Json::object();
    out["version_set_count"] = total;
    out["final_count"] = finals;
    out["open_count"] = open;
    out["latest_final_horizon"] =
        last_final != nullptr
            ? string_field(*last_final, "target_horizon")
            : std::string("");
    if (last_final == nullptr) {
        out["latest_final_at"] = nullptr;
    } else if (const auto at =
                   nullable_string_field(*last_final, "finalized_at")) {
        out["latest_final_at"] = *at;
    } else {
        out["latest_final_at"] = nullptr;
    }
    return out;
}

}  // namespace pwb::workflow_runtime
