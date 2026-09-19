// Model registry read/write group (conv-31b; service.py 2815-3124 — R7
// recon contract, frozen in 31b-findings). Free functions over
// CatalogDocument + the unified SaveHook: each writer computes its own
// DirtySet, calls the hook once, and on a non-ok return performs its
// Python-parity in-memory snapshot rollback (service.py raise paths).
//
// Behavior invariants (byte-identical error texts):
//   "register_model requires model_id and model_name"
//   "Unknown model: <id>"
//   "register_model_version cannot set status=production; "
//   "register as demo then call promote_model()"
//   "ModelVersion <id>@<v> already registered" / "... not registered"
//   "Unknown model version: <id>@<v>" / "Unknown model version: <row id>"
//   "Cannot promote to production: <gate reason>"
// Bounded deviations (findings B-11/B-28, R7 ⑤): ids/timestamps via
// domain::make_id / refs::utc_now_iso (same shapes as Python uuid4.hex[:12]
// / datetime.isoformat); register_model_version's duplicate check is
// re-run just before the append (Python checks once outside its TOCTOU
// window — the narrowing is deliberate and only ever stricter). The
// register_model_version artifact hash runs BEFORE the append+save window
// ("the lock never spans disk IO"); a missing/unreadable artifact leaves
// checksum nullopt (Python's silent OSError fallback).
// Pointer-scope contract (CONV-31b Wave4 fix for review V2-P1-4; the same
// family as the entity-node stability fixed in service_core.cpp): the
// Model*/ModelVersion* values returned by register_model /
// register_model_version / promote_model alias rows of the caller's
// CatalogDocument (a value type — Python hands out stable object
// references, C++ cannot without changing the frozen public surface:
// either the register_* return types or CatalogDocument's vector members
// in models.hpp). Their validity window is therefore:
//   - until the next append to the SAME list (vector reallocation), and
//   - until the document view is re-materialized (a CatalogServiceCore
//     caller: any node-side mutation — add_*/remove_*/reload — followed
//     by document(); pure find_* reads and saves do NOT re-materialize).
// Read the fields (or copy the row) inside that window, as every current
// consumer does; entity (asset/version/run) pointers from the core have
// the stronger "stable until removed" guarantee instead.
#include "pwb/catalog/model_registry.hpp"

#include "pwb/catalog/checksum.hpp"
#include "pwb/catalog/refs.hpp"

#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <utility>

namespace pwb::catalog {

namespace {

using pwb::domain::DataError;
using pwb::domain::ErrorCode;

namespace fs = std::filesystem;

// Python Path.expanduser() subset: a leading "~" / "~/..." resolves against
// $HOME (no "~other/" user expansion — registered artifact URIs never carry
// one). Unresolvable or non-tilde paths pass through verbatim like Python's
// expanduser (which only rewrites a leading "~" segment).
fs::path expand_user(const std::string& text) {
    if (text.empty() || text[0] != '~') return fs::path(text);
    if (text.size() == 1 || text[1] == '/') {
        const char* home = std::getenv("HOME");
        if (home != nullptr && *home != '\0') {
            const fs::path base(home);
            return text.size() == 1 ? base : base / text.substr(2);
        }
    }
    return fs::path(text);
}

// dict(x or {}) for the request's mapping fields: an object copies ({} is
// falsy in Python, so the copy and the fallback coincide); a non-object is
// defended to an empty object (Python would TypeError on dict(<scalar>) —
// unreachable through the typed request).
domain::Json object_or_empty(const domain::Json& value) {
    return value.is_object() ? value : domain::Json::object();
}

// service.py _discard_by_identity: pointer scan, never value equality
// (#1044 — a different-but-equal twin must not be evicted).
template <typename T>
void discard_by_identity(std::vector<T>& items, const T* target) {
    for (auto it = items.begin(); it != items.end(); ++it) {
        if (&*it == target) {
            items.erase(it);
            return;
        }
    }
}

// Null hook → Ok (TagStore::save_or_rollback precedent): the seam is
// optional, its absence is not a failure.
DataError run_save(const SaveHook& save, const DirtySet& dirty) {
    return save ? save(dirty) : DataError(ErrorCode::Ok, "");
}

}  // namespace

domain::Result<Model*> register_model(CatalogDocument& document,
                                      const SaveHook& save,
                                      const RegisterModelRequest& request) {
    if (request.model_id.empty() || request.model_name.empty()) {
        return DataError(ErrorCode::InvalidArgument,
                         "register_model requires model_id and model_name");
    }
    Model* existing = document.find_model_mut(request.model_id);
    if (existing != nullptr) {
        // Snapshot for the save-failure rollback (service.py 2868-2874).
        const std::string before_name = existing->model_name;
        const std::string before_type = existing->model_type;
        const std::string before_capability = existing->capability;
        const std::string before_provider = existing->provider;
        const std::string before_status = existing->status;
        const domain::Json before_metadata = existing->metadata;
        const domain::Json before_provenance = existing->provenance;
        bool changed = false;
        // model_name refreshes unconditionally (the caller validated it
        // non-empty); the identity fields only under their truthy gates so
        // an empty capability/provider never blanks a stored value
        // (find_production_model depends on capability surviving seeds).
        if (existing->model_name != request.model_name) {
            existing->model_name = request.model_name;
            changed = true;
        }
        if (!request.model_type.empty() && request.model_type != "unknown" &&
            existing->model_type != request.model_type) {
            existing->model_type = request.model_type;
            changed = true;
        }
        if (!request.capability.empty() &&
            existing->capability != request.capability) {
            existing->capability = request.capability;
            changed = true;
        }
        if (!request.provider.empty() &&
            existing->provider != request.provider) {
            existing->provider = request.provider;
            changed = true;
        }
        if (request.force_status) {
            // Whole-replace of status+metadata TOGETHER when either differs
            // (C2: without force_status a seed must never clobber a
            // promoted model's status or metadata).
            const domain::Json new_meta = object_or_empty(request.metadata);
            if (existing->status != request.status ||
                existing->metadata != new_meta) {
                existing->status = request.status;
                existing->metadata = new_meta;
                changed = true;
            }
        }
        if (request.provenance.is_object() && !request.provenance.empty()) {
            // dict.update: key-wise overlay, existing keys keep their
            // position, new keys append (ordered_json assignment order).
            for (auto it = request.provenance.begin();
                 it != request.provenance.end(); ++it) {
                existing->provenance[it.key()] = *it;
            }
            // Python marks changed=True right after update() — even when
            // the overlay is value-identical. Mirrored verbatim.
            changed = true;
        }
        if (changed) {
            DirtySet dirty;
            dirty.mark_model(existing->id);
            const DataError error = run_save(save, dirty);
            if (error.code != ErrorCode::Ok) {
                existing->model_name = before_name;
                existing->model_type = before_type;
                existing->capability = before_capability;
                existing->provider = before_provider;
                existing->status = before_status;
                existing->metadata = before_metadata;
                existing->provenance = before_provenance;
                return error;
            }
        }
        // changed == false: NO save (no revision churn, #1183).
        return existing;
    }
    Model model;
    model.id = domain::make_id("model_");  // callers carry the "_" (Python
                                           // _id adds it; C++ make_id does
                                           // not) → model_<12hex>
    model.model_id = request.model_id;
    model.model_name = request.model_name;
    model.model_type = request.model_type.empty() ? "unknown"
                                                  : request.model_type;
    model.capability = request.capability;
    model.provider = request.provider;
    model.status = request.status;  // verbatim (no "or" fallback in Python)
    model.metadata = object_or_empty(request.metadata);
    model.created_at = utc_now_iso();
    model.provenance = object_or_empty(request.provenance);
    document.models.push_back(std::move(model));
    // Pointer-scope contract above applies: valid until the next
    // models append or document re-materialization.
    Model* inserted = &document.models.back();
    DirtySet dirty;
    dirty.mark_model(inserted->id);
    const DataError error = run_save(save, dirty);
    if (error.code != ErrorCode::Ok) {
        discard_by_identity(document.models, inserted);
        return error;
    }
    return inserted;
}

domain::Result<ModelVersion*> register_model_version(
    CatalogDocument& document, const SaveHook& save,
    const RegisterModelVersionRequest& request) {
    // 1) model existence — checked at the Python timepoint (findings B-28:
    //    only the duplicate check is narrowed into the commit window).
    if (document.find_model(request.model_id) == nullptr) {
        return DataError(ErrorCode::NotFound,
                         "Unknown model: " + request.model_id);
    }
    // 2) Stage-13: production status only via promote_model.
    if (request.status == "production") {
        return DataError(
            ErrorCode::InvalidArgument,
            "register_model_version cannot set status=production; "
            "register as demo then call promote_model()");
    }
    const std::string key(request.model_version);
    const std::string duplicate_message =
        "ModelVersion " + request.model_id + "@" + request.model_version +
        " already registered";
    const auto is_duplicate = [&]() {
        for (const auto& version : document.model_versions) {
            if (version.model_id == request.model_id &&
                version.model_version == key) {
                return true;
            }
        }
        return false;
    };
    // 3) duplicate check at the Python position (error precedence: this
    //    fires before any artifact hashing could fail).
    if (is_duplicate()) {
        return DataError(ErrorCode::DuplicateOperation, duplicate_message);
    }
    // 4) checksum derivation — OUTSIDE the append+save window; OSError →
    //    stays nullopt (Python's silent fallback).
    std::optional<std::string> checksum = request.checksum;
    if (!checksum.has_value() && !request.artifact_uri.empty()) {
        const fs::path candidate = expand_user(request.artifact_uri);
        std::error_code ec;
        if (fs::is_regular_file(candidate, ec)) {
            checksum = sha256_file_or_none(candidate);
        }
    }
    // 5) assemble (status keeps its "demo" registration default — the DTO
    //    default stays "production" for old-row loads; the two must not
    //    collapse, R7 recon ⑥-2).
    ModelVersion version;
    version.id = domain::make_id("mver_");  // → mver_<12hex>
    version.model_id = request.model_id;
    version.model_version = key;
    version.artifact_uri = request.artifact_uri;
    version.checksum = checksum;
    version.input_schema = object_or_empty(request.input_schema);
    version.output_schema = object_or_empty(request.output_schema);
    version.preprocessing_version = request.preprocessing_version;
    version.runtime = request.runtime;
    version.deterministic = request.deterministic;
    version.demo_only = request.demo_only;
    version.status = request.status.empty() ? "demo" : request.status;
    version.metadata = object_or_empty(request.metadata);
    version.created_at = utc_now_iso();
    version.provenance = object_or_empty(request.provenance);
    // 6) duplicate re-check just before the append (B-28: Python's check
    //    sits outside its lock — the re-run narrows the TOCTOU window and
    //    is only ever stricter).
    if (is_duplicate()) {
        return DataError(ErrorCode::DuplicateOperation, duplicate_message);
    }
    document.model_versions.push_back(std::move(version));
    // Pointer-scope contract above applies (same-list append reallocates).
    ModelVersion* inserted = &document.model_versions.back();
    DirtySet dirty;
    dirty.mark_model_version(inserted->id);
    const DataError error = run_save(save, dirty);
    if (error.code != ErrorCode::Ok) {
        discard_by_identity(document.model_versions, inserted);
        return error;
    }
    return inserted;
}

// ---- reads -------------------------------------------------------------------

domain::Result<const Model*> get_model(const CatalogDocument& document,
                                       std::string_view model_id) {
    const Model* model = document.find_model(std::string(model_id));
    if (model == nullptr) {
        return DataError(ErrorCode::NotFound,
                         "Unknown model: " + std::string(model_id));
    }
    return model;
}

domain::Result<const ModelVersion*> get_model_version(
    const CatalogDocument& document, std::string_view model_id,
    std::string_view model_version) {
    const std::string key(model_version);
    const ModelVersion* version =
        document.find_model_version(std::string(model_id), key);
    if (version == nullptr) {
        return DataError(ErrorCode::NotFound,
                         "Unknown model version: " + std::string(model_id) +
                             "@" + std::string(model_version));
    }
    return version;
}

domain::Result<const ModelVersion*> get_model_version_by_id(
    const CatalogDocument& document, std::string_view model_version_id) {
    const ModelVersion* version =
        document.find_model_version_by_id(std::string(model_version_id));
    if (version == nullptr) {
        return DataError(
            ErrorCode::NotFound,
            "Unknown model version: " + std::string(model_version_id));
    }
    return version;
}

std::vector<const Model*> list_models(const CatalogDocument& document) {
    std::vector<const Model*> out;
    out.reserve(document.models.size());
    for (const auto& model : document.models) out.push_back(&model);
    return out;
}

std::vector<const ModelVersion*> list_model_versions(
    const CatalogDocument& document, const std::string* model_id) {
    std::vector<const ModelVersion*> out;
    out.reserve(document.model_versions.size());
    for (const auto& version : document.model_versions) {
        if (model_id == nullptr || version.model_id == *model_id) {
            out.push_back(&version);
        }
    }
    // sorted(key=created_at) — stable, so ties keep document (rowid) order.
    std::stable_sort(out.begin(), out.end(),
                     [](const ModelVersion* a, const ModelVersion* b) {
                         return a->created_at < b->created_at;
                     });
    return out;
}

// ---- promote / find ------------------------------------------------------------

domain::Result<ModelVersion*> promote_model(CatalogDocument& document,
                                            const SaveHook& save,
                                            std::string_view model_id,
                                            std::string_view model_version) {
    // Lookups BEFORE the gate (the oracle's unknown_model /
    // version_not_registered rows surface these texts without the
    // "Cannot promote" prefix).
    Model* model = document.find_model_mut(std::string(model_id));
    if (model == nullptr) {
        return DataError(ErrorCode::NotFound,
                         "Unknown model: " + std::string(model_id));
    }
    const std::string key(model_version);
    ModelVersion* version =
        document.find_model_version_mut(std::string(model_id), key);
    if (version == nullptr) {
        return DataError(ErrorCode::NotFound,
                         "ModelVersion " + std::string(model_id) + "@" +
                             std::string(model_version) + " not registered");
    }
    const auto facts =
        model_gate_facts(document, model_id, model_version);
    const auto gate = can_promote_to_production(
        std::get<0>(facts), std::get<1>(facts), std::get<2>(facts),
        /*require_input_schema=*/true);
    if (!gate.first) {
        return DataError(ErrorCode::InvalidArgument,
                         "Cannot promote to production: " + gate.second);
    }
    const std::string before_model_status = model->status;
    const std::string before_version_status = version->status;
    const bool before_demo_only = version->demo_only;
    model->status = "production";
    version->status = "production";
    version->demo_only = false;
    // ONE save carrying BOTH dirty ids = the caller's single transaction
    // (repository promote_model_transaction).
    DirtySet dirty;
    dirty.mark_model(model->id);
    dirty.mark_model_version(version->id);
    const DataError error = run_save(save, dirty);
    if (error.code != ErrorCode::Ok) {
        model->status = before_model_status;
        version->status = before_version_status;
        version->demo_only = before_demo_only;
        return error;
    }
    return version;
}

const ModelVersion* find_production_model(const CatalogDocument& document,
                                          std::string_view capability) {
    const ModelVersion* best = nullptr;
    for (const auto& version : document.model_versions) {
        if (version.demo_only || version.status != "production") continue;
        // Orphan model row → Python swallows the raise and skips.
        const Model* model = document.find_model(version.model_id);
        if (model == nullptr) continue;
        if (model->status != "production" || model->capability != capability) {
            continue;
        }
        const auto facts =
            model_gate_facts(document, model->model_id, version.model_version);
        const auto gate = can_promote_to_production(
            std::get<0>(facts), std::get<1>(facts), std::get<2>(facts),
            // Read-path exemption (Agent L P2): schema is enforced at
            // promote time; legacy pre-schema promotions must not vanish
            // from reads. Do NOT "fix" this to true.
            /*require_input_schema=*/false);
        if (!gate.first) continue;
        if (best == nullptr || version.created_at > best->created_at) {
            best = &version;  // strict > : ties keep the doc-order first
        }
    }
    return best;
}

std::tuple<std::optional<ModelGateFacts>,
           std::optional<ModelVersionGateFacts>,
           std::optional<std::string>>
model_gate_facts(const CatalogDocument& document, std::string_view model_id,
                 std::string_view model_version) {
    // Mirrors the gate's try block: get_model then get_model_version, their
    // raise texts forwarded verbatim as (false, str(exc)).
    const Model* model = document.find_model(std::string(model_id));
    if (model == nullptr) {
        return {std::nullopt, std::nullopt,
                std::optional<std::string>("Unknown model: " +
                                           std::string(model_id))};
    }
    const ModelVersion* version = document.find_model_version(
        std::string(model_id), std::string(model_version));
    if (version == nullptr) {
        return {std::nullopt, std::nullopt,
                std::optional<std::string>(
                    "Unknown model version: " + std::string(model_id) + "@" +
                    std::string(model_version))};
    }
    ModelGateFacts model_facts;
    model_facts.provider = model->provider;
    model_facts.model_type = model->model_type;
    model_facts.metadata = model->metadata;
    ModelVersionGateFacts version_facts;
    version_facts.demo_only = version->demo_only;
    version_facts.metadata = version->metadata;
    version_facts.input_schema = version->input_schema;
    return {model_facts, version_facts, std::nullopt};
}

}  // namespace pwb::catalog
