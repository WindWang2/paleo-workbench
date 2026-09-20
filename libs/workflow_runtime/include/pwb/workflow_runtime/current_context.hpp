#pragma once

// C++ port of paleo_workbench/workflow/current_context.py (CONV-26) —
// deterministic current-project version selection (Stage 9). Freshness is
// DERIVED from asset current pointers + project product refs + explicit
// overrides; immutable historical DataVersions are never stamped stale.
//
// Ported surface: the CurrentProjectVersionContext dataclass (select /
// mark_domain_product_current / current_for_asset / is_current_version /
// set_expected_identity with display-only key stripping). The
// resolve_current_project_version_context() project glue (horizon /
// correlation / fault interpretation refs, factor & prediction task
// pointers) becomes the Json-driven build_context_from_project() over a
// CatalogRepository seam — see catalog_seam.hpp and runtime_service.hpp.
//
// Divergence (documented): Python stores selected_version_ids as a set
// (per-process hash order); C++ keeps insertion order — deterministic.
// Only observable when several selected tips share a domain-task/parent
// supersession key (freshness rules 3/4); the oracle avoids that ambiguity.
//
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>

#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

namespace pwb::workflow_runtime {

using pwb::domain::Json;

class CurrentProjectVersionContext {
public:
    CurrentProjectVersionContext();

    // Record that *asset_id* currently points at *version_id*. Replacing an
    // asset's selection removes the previous tip from selected ids.
    void select(const std::string& asset_id, const std::string& version_id,
                const std::string& label = "");

    // Record which product version is current for a domain task
    // (recompute outputs often create new assets that are not the tip).
    void mark_domain_product_current(const std::string& domain_task_id,
                                     const std::string& version_id);

    // resolve_current_project_version_context support (issue #373 / C15):
    // Python mutates ctx.selected_version_ids directly — a superseded
    // domain tip leaves the selection without touching its asset pointer.
    void deselect_version(const std::string& version_id);

    // Python `ctx.selected_version_ids.add(vid)` + `ctx.labels[vid] = ...`
    // for versions unknown to the catalog (no asset to point at).
    void select_version_only(const std::string& version_id,
                             const std::string& label);

    [[nodiscard]] std::optional<std::string> current_for_asset(
        const std::optional<std::string>& asset_id) const;
    [[nodiscard]] bool is_current_version(const std::string& version_id) const;

    // Expected computation identity (generator / snapshot / parameters /
    // model_ref). Display-only keys and "_display*" keys are stripped so
    // style changes never stale science.
    void set_expected_identity(
        const std::string& key,
        const std::optional<std::string>& generator_version = std::nullopt,
        const std::optional<std::string>& input_snapshot_hash = std::nullopt,
        const Json& parameters = Json(nullptr),
        const Json& model_ref = Json(nullptr));

    // ---- read views (Python dataclass fields) ----
    [[nodiscard]] const std::map<std::string, std::string>& current_by_asset()
        const {
        return current_by_asset_;
    }
    [[nodiscard]] const std::vector<std::string>& selected_version_ids() const {
        return selected_order_;
    }
    [[nodiscard]] const std::map<std::string, std::string>& labels() const {
        return labels_;
    }
    [[nodiscard]] const std::map<std::string, Json>& expected_identity() const {
        return expected_identity_;
    }
    [[nodiscard]] const std::set<std::string>& display_only_keys() const {
        return display_only_keys_;
    }
    [[nodiscard]] const std::map<std::string, std::string>&
    current_by_domain_task() const {
        return current_by_domain_task_;
    }

private:
    std::map<std::string, std::string> current_by_asset_;
    std::vector<std::string> selected_order_;      // insertion order
    std::set<std::string> selected_set_;
    std::map<std::string, std::string> labels_;
    std::map<std::string, Json> expected_identity_;
    std::set<std::string> display_only_keys_;
    std::map<std::string, std::string> current_by_domain_task_;

    void discard_selected(const std::string& version_id);
};

}  // namespace pwb::workflow_runtime
