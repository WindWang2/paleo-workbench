#pragma once

// ProjectSession — application-layer composition root (CPP-A contract).
// Owns the MapSession + EditController, tracks the active/edit layer
// agreement, collects the ToolContextSnapshot from live authorities, and is
// the single assembly point for the B/C adapters (libs/application/adapters).

#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <string>

#include <pwb/qgis/edit_controller.hpp>
#include <pwb/qgis/map_session.hpp>
#include <pwb/tool_policy/tool_context.hpp>

#include "adapters/project_store.hpp"

class QgsMapCanvas;

namespace pwb::application {

// Domain-side facts the platform cannot derive from QGIS alone (role,
// maturity, stage). First round: supplied by the host app / tests; later
// supplied by B's ProjectSnapshot.
struct DomainLayerFacts {
    std::string layer_id;
    std::string role;
    std::string role_label;
    bool is_facies = false;
    std::string artifact_maturity;   // raw/draft/reviewed/frozen/published
    bool frozen = false;
    bool raw_locked = false;
    bool stage_locked = false;
    bool write_granted = false;
    // BEGIN V14-QGIS-CONTROL
    // Layer presentation projection (pwb::ui_composite::layer_presentation):
    // stable flag vocabulary for the panel chips/tooltip + one-line
    // summary (binding/freshness/targets — see contracts 03 §9).
    std::vector<std::string> status_flags;
    std::string status_summary;
    // END V14-QGIS-CONTROL
};

class ProjectSession {
public:
    ProjectSession();
    ~ProjectSession();

    ProjectSession(const ProjectSession&) = delete;
    ProjectSession& operator=(const ProjectSession&) = delete;

    pwb::qgis::MapSession& map() { return *map_; }
    pwb::qgis::EditController& edit() { return *edit_; }

    void attachCanvas(QgsMapCanvas* canvas);
    QgsMapCanvas* canvas() const { return canvas_; }

    // Active/current/edit layer unification (invariant 10.3-1): one setter,
    // all three resolve to the same domain layer id.
    void set_active_layer(const DomainLayerFacts& facts);
    // Reset the active selection to the none-valid state (a close/switch
    // or a layer-removal path must let the next open's auto-activation
    // fire again) — #1453: assigning an empty DomainLayerFacts leaves
    // has_value() true forever.
    void clear_active_layer() { active_facts_.reset(); }
    const std::optional<DomainLayerFacts>& active_layer() const {
        return active_facts_;
    }
    std::string active_layer_error() const { return active_layer_error_; }

    // Workflow stage (tri-state like the contract: unset = no semantics).
    void set_mapping_stage(std::optional<std::string> stage) {
        mapping_stage_ = std::move(stage);
    }
    const std::optional<std::string>& mapping_stage() const {
        return mapping_stage_;
    }

    // Current map tool id (policy vocabulary: pan/zoom_in/vertex/...).
    // Drives the checked derivation; the canvas remains the QGIS authority
    // for which QgsMapTool is armed — this is the policy-side mirror.
    void set_current_tool(std::string tool_id) { current_tool_ = std::move(tool_id); }
    const std::string& current_tool() const { return current_tool_; }

    void set_store(std::shared_ptr<IProjectStore> store) { store_ = std::move(store); }
    IProjectStore* store() const { return store_.get(); }

    // Commit through the B adapter (staged asset protocol), ordered so the
    // user's source provider is written only after the catalog transaction
    // accepts the round:
    //   stage (live buffer, provider untouched) -> B commit -> finalize.
    // A rejected B commit keeps the edit buffer alive for repair + retry;
    // the retry reuses the same operation id for identical staged content
    // (B's idempotency) and gets a fresh id when the content changed.
    // Without a store (module-only mode) the working file is the only
    // persistence: it is finalized and an explicit error is returned, never
    // a fake receipt.
    pwb::qgis::StagedAsset stage_commit(const std::string& layer_id,
                                        const std::filesystem::path& staged_dir,
                                        std::string* error);

    // Snapshot derived from live authorities (QGIS layer/edit state +
    // domain facts). Pure derivation; the evaluator stays Qt-free.
    pwb::tool_policy::ToolContextSnapshot snapshot() const;

    void close();

private:
    // One staged round that has not been accepted by B yet: the operation
    // id must stay stable across retries of the SAME content (B replays
    // receipts by id) and change when the content changes (consecutive
    // edit rounds must never reuse an id — B would replay the old receipt
    // and silently drop the new edit).
    struct PendingOperation {
        std::string operation_id;
        std::string sha256;
        std::uint64_t base_revision = 0;
    };

    std::string operation_id_for(const std::string& layer_id,
                                 const pwb::qgis::StagedAsset& staged);
    std::string frozen_base_version(const std::string& layer_id) const;

    std::unique_ptr<pwb::qgis::MapSession> map_;
    std::unique_ptr<pwb::qgis::EditController> edit_;
    std::shared_ptr<IProjectStore> store_;
    QgsMapCanvas* canvas_ = nullptr;
    std::optional<DomainLayerFacts> active_facts_;
    std::string active_layer_error_;
    std::optional<std::string> mapping_stage_;
    std::string current_tool_ = "pan";
    std::map<std::string, PendingOperation> pending_operations_;
};

}  // namespace pwb::application
