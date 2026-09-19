#include "pwb/closure_review/review_versioning.hpp"

#include "pwb/closure_review/review_qc_core.hpp"

#include <pwb/domain/sha256.hpp>
#include <pwb/ui_data_core/map_edit_geometry.hpp>

#include <cctype>
#include <cmath>
#include <optional>

namespace pwb::closure_review {

namespace {

using domain::Json;

const Json& empty_array() {
    static const Json value = Json::array();
    return value;
}

const Json& section_array(const Json& root, const char* key) {
    const auto it = root.find(key);
    if (it != root.end() && it->is_array()) {
        return *it;
    }
    return empty_array();
}

Json* mutable_section_array(Json& root, const char* key) {
    const auto it = root.find(key);
    if (it != root.end() && it->is_array()) {
        return &*it;
    }
    return nullptr;
}

std::string field_string(const Json& object, const char* key) {
    if (!object.is_object()) {
        return {};
    }
    const auto it = object.find(key);
    return it != object.end() && it->is_string() ? it->get<std::string>()
                                                 : std::string();
}

// getattr(obj, key, default) parity: missing/null → the fallback.
Json field_or(const Json& object, const char* key, Json fallback) {
    if (object.is_object()) {
        const auto it = object.find(key);
        if (it != object.end() && !it->is_null()) {
            return *it;
        }
    }
    return fallback;
}

// _fingerprint_map parity: sha256 over a canonical (recursively key-sorted)
// JSON dump of the map's content payload, truncated to 16 hex chars. The
// ordered_json → json conversion performs the recursive sort (nlohmann
// json objects are ordered by key), matching Python json.dumps(sort_keys).
nlohmann::json json_sort(const Json& value) {
    return nlohmann::json(value);
}

std::string fingerprint_map(const Json& document) {
    nlohmann::json payload;
    payload["id"] = json_sort(field_or(document, "id", Json()));
    payload["horizon"] =
        json_sort(field_or(document, "linked_target_horizon", Json()));
    payload["facies"] =
        json_sort(field_or(document, "facies_polygons", Json::array()));
    payload["lines"] =
        json_sort(field_or(document, "line_features", Json::array()));
    payload["wells"] =
        json_sort(field_or(document, "well_overlays", Json::array()));
    payload["labels"] =
        json_sort(field_or(document, "label_features", Json::array()));
    // default=str parity: non-representable leaves stringify; nlohmann
    // serializes every JSON value it can hold, and the document payload is
    // JSON already, so no extra conversion applies.
    return domain::Sha256::of_bytes(payload.dump()).substr(0, 16);
}

int count_contour_segments(const Json& root, const std::string& draft_id) {
    if (draft_id.empty()) {
        return 0;
    }
    for (const auto& draft : section_array(root, "contour_drafts")) {
        if (field_string(draft, "id") == draft_id) {
            return static_cast<int>(
                section_array(draft, "segments").size());
        }
    }
    return 0;
}

// _linked_qc_report parity: the LATEST report linked to this map.
const Json* linked_qc_report(const Json& root, const std::string& doc_id) {
    const Json& reports = section_array(root, "quality_reports");
    for (auto it = reports.rbegin(); it != reports.rend(); ++it) {
        if (it->is_object() &&
            field_string(*it, "linked_map_document_id") == doc_id) {
            return &*it;
        }
    }
    return nullptr;
}

// _version_set_for_horizon parity: the first non-superseded set for the
// horizon, else a fresh open one (appended, linked to the active run).
Json* version_set_for_horizon(Json& root, const std::string& horizon,
                              const std::string& iso_now) {
    Json* sets = mutable_section_array(root, "version_sets");
    if (sets == nullptr) {
        root["version_sets"] = Json::array();
        sets = &root["version_sets"];
    }
    for (auto& vs : *sets) {
        if (field_string(vs, "target_horizon") == horizon &&
            field_string(vs, "status") != "superseded") {
            return &vs;
        }
    }
    Json vs = Json::object();
    vs["id"] = ui_data_core::new_feature_id("vset");
    vs["name"] = (horizon.empty() ? std::string("未指定层位") : horizon) +
                 " 定稿版本集";
    vs["target_horizon"] = horizon;
    vs["status"] = "open";
    vs["snapshots"] = Json::array();
    vs["active_snapshot_id"] = Json();
    vs["finalized_by"] = "";
    vs["finalized_at"] = Json();
    vs["linked_compilation_run_id"] = Json();
    const Json& runs = section_array(root, "compilation_runs");
    if (!runs.empty()) {
        const auto id_it = runs.back().find("id");
        if (id_it != runs.back().end()) {
            vs["linked_compilation_run_id"] = *id_it;
        }
    }
    vs["created_at"] = iso_now;
    vs["updated_at"] = iso_now;
    sets->push_back(vs);
    return &sets->back();
}

}  // namespace

domain::Json build_snapshot(const Json& root, const Json& map_document,
                            const std::string& note,
                            const std::string& created_by,
                            const std::string& iso_now) {
    const std::string doc_id = field_string(map_document, "id");
    const std::string draft_id =
        field_string(map_document, "linked_contour_draft_id");
    const Json* qc = linked_qc_report(root, doc_id);

    // Factor tasks matching the horizon (no horizon → all factor tasks).
    Json factor_ids = Json::array();
    const std::string horizon =
        field_string(map_document, "linked_target_horizon");
    for (const auto& task : section_array(root, "factor_map_tasks")) {
        if (!task.is_object()) {
            continue;
        }
        if (horizon.empty() ||
            field_string(task, "target_horizon") == horizon) {
            const auto id_it = task.find("id");
            if (id_it != task.end()) {
                factor_ids.push_back(*id_it);
            }
        }
    }

    Json snapshot = Json::object();
    snapshot["id"] = ui_data_core::new_feature_id("vsnap");
    snapshot["map_document_id"] = doc_id;
    snapshot["contour_draft_id"] = draft_id.empty() ? Json() : Json(draft_id);
    snapshot["quality_report_id"] =
        qc != nullptr ? Json(field_string(*qc, "id")) : Json();
    snapshot["factor_task_ids"] = factor_ids;
    snapshot["map_name"] = field_string(map_document, "name");
    snapshot["target_horizon"] = horizon;
    snapshot["line_feature_count"] =
        section_array(map_document, "line_features").size();
    snapshot["facies_count"] =
        section_array(map_document, "facies_polygons").size();
    snapshot["contour_segment_count"] =
        count_contour_segments(root, draft_id);
    snapshot["qc_status"] =
        qc != nullptr ? field_string(*qc, "status") : std::string("unchecked");
    snapshot["note"] = note;
    snapshot["content_fingerprint"] = fingerprint_map(map_document);
    snapshot["created_at"] = iso_now;
    snapshot["created_by"] = created_by;
    return snapshot;
}

domain::Result<domain::Json> finalize_map_version_on_document(
    Json& root, const std::string& doc_id, const std::string& note,
    const std::string& finalized_by, bool require_qc_pass,
    const std::string& iso_now) {
    // The document pointer is re-resolved after every root mutation: root
    // object growth can reallocate the section vector storage.
    auto resolve_document = [&root, &doc_id]() -> Json* {
        Json* docs = mutable_section_array(root, "paleomap_documents");
        if (docs == nullptr) {
            return nullptr;
        }
        for (auto& doc : *docs) {
            if (doc.is_object() && field_string(doc, "id") == doc_id) {
                return &doc;
            }
        }
        return nullptr;
    };
    Json* map_doc = resolve_document();
    if (map_doc == nullptr) {
        return domain::DataError(domain::ErrorCode::NotFound,
                                 "unknown map document: " + doc_id);
    }

    // H3 guards: demo drafts must never be expert-finalized as production —
    // the highest-trust step cannot launder heuristic geometry. A no-catalog
    // compile (untracked lineage) is not a demo draft — say so explicitly.
    const auto state_it = map_doc->find("view_state");
    const Json view_state =
        state_it != map_doc->end() && state_it->is_object()
            ? *state_it
            : Json::object();
    auto state_value = [&view_state](const char* key) -> Json {
        const auto it = view_state.find(key);
        return it != view_state.end() ? *it : Json();
    };
    // Python truthiness on the raw marker: any truthy is_demo_draft
    // (true/1/"true") refuses — not just boolean true.
    const Json demo_marker = state_value("is_demo_draft");
    if (!demo_marker.is_null() && json_truthy(demo_marker)) {
        return domain::DataError(
            domain::ErrorCode::InvalidArgument,
            "演示草稿图不能专家定稿为生产成果；请先通过生产编图路径生成正式图件");
    }
    // Python `vs_state.get("production") is False` — strict identity, so
    // only a literal boolean false enters this branch.
    const auto production_it = view_state.find("production");
    if (production_it != view_state.end() && production_it->is_boolean() &&
        !production_it->get<bool>()) {
        const Json lineage = state_value("lineage");
        if (lineage.is_string() && lineage.get<std::string>() == "untracked") {
            return domain::DataError(
                domain::ErrorCode::InvalidArgument,
                "该成果的 lineage 未登记（无目录），不能专家定稿；请重新打开目录后通过生产编图生成");
        }
        return domain::DataError(domain::ErrorCode::InvalidArgument,
                                 "非生产成果不能专家定稿为正式图件");
    }

    const Json* qc = linked_qc_report(root, doc_id);
    if (require_qc_pass) {
        if (qc == nullptr) {
            return domain::DataError(domain::ErrorCode::InvalidArgument,
                                     "定稿前需先运行质检");
        }
        std::string status = field_string(*qc, "status");
        for (auto& c : status) {
            c = static_cast<char>(
                std::tolower(static_cast<unsigned char>(c)));
        }
        if (status == "error" || status == "failed" || status == "critical") {
            return domain::DataError(
                domain::ErrorCode::InvalidArgument,
                "质检未通过（status=" + field_string(*qc, "status") +
                    "），不能定稿");
        }
    }

    const std::string horizon =
        field_string(*map_doc, "linked_target_horizon");

    // Supersede prior finals for this horizon (history is kept). Do this
    // BEFORE creating/appending any new set: vector growth invalidates
    // into-vector pointers.
    {
        Json* sets = mutable_section_array(root, "version_sets");
        if (sets != nullptr) {
            for (auto& vs : *sets) {
                if (field_string(vs, "target_horizon") == horizon &&
                    field_string(vs, "status") == "final") {
                    vs["status"] = "superseded";
                    vs["updated_at"] = iso_now;
                }
            }
        }
    }

    Json* vset = version_set_for_horizon(root, horizon, iso_now);
    // Re-resolve the document (root mutations above may have reallocated
    // the paleomap_documents section header storage path).
    map_doc = resolve_document();
    if (vset == nullptr || map_doc == nullptr) {
        return domain::DataError(domain::ErrorCode::Unknown,
                                 "version set allocation failed");
    }

    Json snapshot =
        build_snapshot(root, *map_doc, note, finalized_by, iso_now);
    if (!vset->contains("snapshots") || !(*vset)["snapshots"].is_array()) {
        (*vset)["snapshots"] = Json::array();
    }
    (*vset)["snapshots"].push_back(snapshot);
    (*vset)["active_snapshot_id"] = snapshot["id"];
    (*vset)["status"] = "final";
    (*vset)["finalized_by"] = finalized_by;
    (*vset)["finalized_at"] = iso_now;
    (*vset)["updated_at"] = iso_now;

    // Linked contour draft → final.
    const std::string draft_id =
        field_string(*map_doc, "linked_contour_draft_id");
    if (!draft_id.empty()) {
        Json* drafts = mutable_section_array(root, "contour_drafts");
        if (drafts != nullptr) {
            for (auto& draft : *drafts) {
                if (field_string(draft, "id") == draft_id) {
                    draft["status"] = "final";
                    draft["updated_at"] = iso_now;
                    break;
                }
            }
        }
    }

    // Compilation run bookkeeping: the run advances toward export_ready.
    Json* runs = mutable_section_array(root, "compilation_runs");
    if (runs != nullptr && !runs->empty()) {
        Json& run = runs->back();
        run["active_paleomap_document_id"] = doc_id;
        if (qc != nullptr) {
            run["active_quality_report_id"] = field_string(*qc, "id");
        }
        const std::string run_status = field_string(run, "status");
        if (run_status == "draft" || run_status == "running" ||
            run_status == "review_required" || run_status == "blocked") {
            run["status"] = "export_ready";
        }
        run["updated_at"] = iso_now;
    }

    // Catalog provenance (version_finalize DataRun) is the catalog line's
    // registration surface — a missing catalog never fails the finalize
    // itself (versioning.py best-effort contract).

    return *vset;
}

}  // namespace pwb::closure_review
