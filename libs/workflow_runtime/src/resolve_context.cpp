// resolve_context.cpp — see include/pwb/workflow_runtime/resolve_context.hpp.
// Line anchors below cite paleo_workbench/workflow/current_context.py.

#include <pwb/workflow_runtime/resolve_context.hpp>

#include <algorithm>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::workflow_runtime {

namespace {

using pwb::domain::Json;

// `or []` section view: missing / null / typed-wrong ≙ empty array.
const Json kEmptyArray = Json::array();
const Json& array_field(const Json& obj, const char* key) {
    if (!obj.is_object()) return kEmptyArray;
    const auto it = obj.find(key);
    if (it == obj.end() || !it->is_array()) return kEmptyArray;
    return *it;
}

// getattr(obj, "attr", "") or "" — missing / null / non-string ≙ "".
std::string string_field(const Json& obj, const char* key) {
    if (!obj.is_object()) return {};
    const auto it = obj.find(key);
    if (it == obj.end() || it->is_null() || !it->is_string()) return {};
    return it->get<std::string>();
}

// getattr(obj, "attr", None) — missing / null ≙ nullopt.
std::optional<std::string> nullable_string_field(const Json& obj,
                                                 const char* key) {
    if (!obj.is_object()) return std::nullopt;
    const auto it = obj.find(key);
    if (it == obj.end() || it->is_null() || !it->is_string()) {
        return std::nullopt;
    }
    return it->get<std::string>();
}

const Json kNullJson = Json(nullptr);

// getattr(obj, "attr", None) for arbitrary Json values.
const Json& value_field(const Json& obj, const char* key) {
    if (!obj.is_object()) return kNullJson;
    const auto it = obj.find(key);
    if (it == obj.end() || it->is_null()) return kNullJson;
    return *it;
}

std::string id_or(const Json& ref, const std::string& fallback) {
    std::string id = string_field(ref, "id");
    return id.empty() ? fallback : id;
}

// L383 _deselect_superseded_domain_tips — keep only the project-selected
// tip of a domain task selected. Legacy asset-per-run catalogs leave
// superseded per-run asset tips selected through their catalog
// current_version_id; those tips must not keep poisoning freshness rule 3.
// Best-effort: versions the catalog cannot resolve leave the selection
// untouched. Explicit selections applied later (extra_selected) still win.
void deselect_superseded_domain_tips(
    CurrentProjectVersionContext& ctx, CatalogRepository& catalog,
    const std::string& domain_task_id, const std::string& keep_version_id,
    const std::map<std::string, const RunRecord*>& run_by_id) {
    if (domain_task_id.empty() || keep_version_id.empty()) return;
    // Python iterates `list(ctx.selected_version_ids)` — a SNAPSHOT:
    // discarding while iterating the live vector would skip the element
    // after each erase. Insertion order is the C++ stand-in for Python's
    // set (documented divergence — only observable with several selected
    // tips sharing one supersession key, which the oracle avoids).
    const std::vector<std::string> selected = ctx.selected_version_ids();
    for (const std::string& vid : selected) {
        if (vid == keep_version_id) continue;
        const std::optional<VersionRecord> ver = catalog.resolve_version(vid);
        if (!ver.has_value() || !ver->producing_run_id.has_value()) continue;
        const auto run_it = run_by_id.find(*ver->producing_run_id);
        if (run_it == run_by_id.end()) continue;
        if (run_it->second->domain_task_id.has_value() &&
            *run_it->second->domain_task_id == domain_task_id) {
            ctx.deselect_version(vid);
        }
    }
}


}  // namespace

CurrentProjectVersionContext resolve_current_project_version_context(
    CatalogRepository* catalog, const Json* project,
    const std::map<std::string, std::string>& extra_selected) {
    CurrentProjectVersionContext ctx;

    // Precomputed run index (#538): one listing shared by every domain
    // task's superseded-tip deselection; the storage outlives all the
    // pointers taken into it.
    std::vector<RunRecord> run_storage;
    std::map<std::string, const RunRecord*> run_by_id;
    if (catalog != nullptr) {
        run_storage = catalog->list_runs();
        for (const RunRecord& run : run_storage) {
            run_by_id[run.run_id] = &run;
        }
    }

    // ---- 1. catalog current pointers (L152-160) ----
    if (catalog != nullptr) {
        for (const AssetRecord& asset : catalog->list_assets()) {
            if (asset.current_version_id.has_value() &&
                !asset.current_version_id->empty()) {
                ctx.select(asset.id, *asset.current_version_id, asset.name);
            }
        }
    }

    if (project == nullptr || !project->is_object()) {
        for (const auto& [asset_id, vid] : extra_selected) {
            ctx.select(asset_id, vid);
        }
        return ctx;
    }

    // ---- 2. horizon interpretation refs (L202-224) ----
    for (const Json& ref : array_field(*project, "horizon_interpretations")) {
        const std::string vid = string_field(ref, "current_version_id");
        if (vid.empty() || catalog == nullptr) continue;
        const std::optional<VersionRecord> ver = catalog->resolve_version(vid);
        if (ver.has_value()) {
            ctx.select(ver->asset_id, vid, string_field(ref, "name"));
        } else {
            // Unknown to catalog — still treat as selected version id.
            ctx.select_version_only(vid,
                                    string_field(ref, "name").empty()
                                        ? vid
                                        : string_field(ref, "name"));
        }
        const std::string fp = string_field(ref, "scientific_fingerprint");
        if (!fp.empty()) {
            // Key must match DataRun.domain_task_id (interpretation_id).
            ctx.set_expected_identity(
                id_or(ref, vid), std::string("horizon-interp-v1"), fp);
        }
    }

    // ---- 2b. multi-well correlation interpretation refs (L227-255) ----
    for (const Json& ref : array_field(*project,
                                       "correlation_interpretations")) {
        const std::string vid = string_field(ref, "current_version_id");
        if (vid.empty()) continue;
        if (catalog != nullptr) {
            const std::optional<VersionRecord> ver =
                catalog->resolve_version(vid);
            if (ver.has_value()) {
                ctx.select(ver->asset_id, vid, string_field(ref, "name"));
                const std::string task_id = id_or(ref, "");
                ctx.mark_domain_product_current(task_id, vid);
                deselect_superseded_domain_tips(ctx, *catalog, task_id, vid,
                                                run_by_id);
            } else {
                const std::string label = string_field(ref, "name");
                ctx.select_version_only(vid, label.empty() ? vid : label);
            }
        } else {
            ctx.select_version_only(vid, "");
        }
        const std::string fp = string_field(ref, "scientific_fingerprint");
        if (!fp.empty()) {
            ctx.set_expected_identity(id_or(ref, vid),
                                      std::string("strat-corr-v1"), fp);
        }
    }

    // ---- 2c. fault interpretation refs (L257-286) ----
    for (const Json& ref : array_field(*project, "fault_interpretations")) {
        const std::string vid = string_field(ref, "current_version_id");
        if (vid.empty()) continue;
        if (catalog != nullptr) {
            const std::optional<VersionRecord> ver =
                catalog->resolve_version(vid);
            if (ver.has_value()) {
                ctx.select(ver->asset_id, vid, string_field(ref, "name"));
                const std::string task_id = id_or(ref, "");
                ctx.mark_domain_product_current(task_id, vid);
                deselect_superseded_domain_tips(ctx, *catalog, task_id, vid,
                                                run_by_id);
            } else {
                const std::string label = string_field(ref, "name");
                ctx.select_version_only(vid, label.empty() ? vid : label);
            }
        } else {
            ctx.select_version_only(vid, "");
        }
        const std::string fp = string_field(ref, "scientific_fingerprint");
        if (!fp.empty()) {
            ctx.set_expected_identity(id_or(ref, vid),
                                      std::string("fault-interp-v1"), fp);
        }
    }

    // ---- 3. factor map product pointers + expected identity (L289-354) --
    for (const Json& task : array_field(*project, "factor_map_tasks")) {
        const std::string grid_vid =
            string_field(task, "grid_artifact_version_id");
        if (!grid_vid.empty() && catalog != nullptr) {
            const std::optional<VersionRecord> ver =
                catalog->resolve_version(grid_vid);
            if (ver.has_value()) {
                ctx.select(ver->asset_id, grid_vid,
                           string_field(task, "name"));
                const std::string task_id = id_or(task, "");
                ctx.mark_domain_product_current(task_id, grid_vid);
                deselect_superseded_domain_tips(ctx, *catalog, task_id,
                                                grid_vid, run_by_id);
            }
        }
        const std::string snap = string_field(task, "input_snapshot_hash");
        const std::optional<std::string> gen =
            nullable_string_field(task, "generator_version");
        const Json& params = value_field(task, "parameters");
        // Scientific params only (method/power/radius etc.); display keys
        // are stripped later by set_expected_identity.
        Json sci_params = Json::object();
        sci_params["factor_type"] = value_field(task, "factor_type");
        sci_params["target_horizon"] = value_field(task, "target_horizon");
        sci_params["method"] = value_field(task, "method");
        for (const char* key : {"power", "search_radius", "grid_n", "backend",
                                "anisotropy", "result_fingerprint",
                                "algorithm_fingerprint"}) {
            // Python `if key in params` — explicit null rides along.
            if (params.is_object() && params.find(key) != params.end()) {
                sci_params[key] = params.at(key);
            }
        }
        ctx.set_expected_identity(
            id_or(task, "factor:" + string_field(task, "name")), gen,
            snap.empty() ? std::nullopt : std::optional<std::string>(snap),
            sci_params);
    }

    // ---- 4. prediction tasks (L356-393) ----
    for (const Json& task : array_field(*project, "prediction_tasks")) {
        const std::string snap = string_field(task, "input_snapshot_hash");
        const std::optional<std::string> gen =
            nullable_string_field(task, "generator_version");
        const Json& model_meta = value_field(task, "model_metadata");
        Json model_ref = Json(nullptr);
        if (model_meta.is_object() && !model_meta.empty()) {
            Json subset = Json::object();
            for (const char* key :
                 {"model_id", "model_version", "model_version_id",
                  "preprocessing_version"}) {
                const auto it = model_meta.find(key);
                if (it != model_meta.end()) subset[key] = *it;
            }
            model_ref = subset.empty() ? model_meta : Json(subset);
        }
        Json sci_params = Json::object();
        const std::optional<std::string> adapter_kind =
            nullable_string_field(task, "adapter_kind");
        if (adapter_kind.has_value()) sci_params["adapter_kind"] = *adapter_kind;
        // Python `... .get("threshold") if hasattr(task, "parameters")
        // else model_meta.get("threshold")` — presence of the parameters
        // KEY (even null) routes the lookup; a null/absent threshold then
        // filters out below.
        const bool has_params =
            task.is_object() && task.find("parameters") != task.end();
        const Json& params = value_field(task, "parameters");
        Json threshold = kNullJson;
        if (has_params) {
            if (params.is_object()) {
                const auto it = params.find("threshold");
                if (it != params.end()) threshold = *it;
            }
        } else if (model_meta.is_object()) {
            const auto it = model_meta.find("threshold");
            if (it != model_meta.end()) threshold = *it;
        }
        if (!threshold.is_null()) sci_params["threshold"] = threshold;
        ctx.set_expected_identity(
            id_or(task, "pred:" + string_field(task, "name")), gen,
            snap.empty() ? std::nullopt : std::optional<std::string>(snap),
            sci_params, model_ref);
    }

    // ---- 5. explicit overrides (L396-399) ----
    for (const auto& [asset_id, vid] : extra_selected) {
        ctx.select(asset_id, vid);
    }

    return ctx;
}

}  // namespace pwb::workflow_runtime
