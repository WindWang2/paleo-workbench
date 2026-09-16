#pragma once

// ProjectSession — application-layer composition root (CPP-A contract).
// Owns the MapSession + EditController, tracks the active/edit layer
// agreement, collects the ToolContextSnapshot from live authorities, and is
// the single assembly point for the B/C adapters (libs/application/adapters).

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

    void set_store(std::shared_ptr<IProjectStore> store) { store_ = std::move(store); }
    IProjectStore* store() const { return store_.get(); }

    // Commit through the B adapter (staged asset protocol). Without a store
    // (module-only mode) returns an explicit error, never a fake receipt.
    pwb::qgis::StagedAsset stage_commit(const std::string& layer_id,
                                        const std::filesystem::path& staged_dir,
                                        std::string* error);

    // Snapshot derived from live authorities (QGIS layer/edit state +
    // domain facts). Pure derivation; the evaluator stays Qt-free.
    pwb::tool_policy::ToolContextSnapshot snapshot() const;

    void close();

private:
    std::unique_ptr<pwb::qgis::MapSession> map_;
    std::unique_ptr<pwb::qgis::EditController> edit_;
    std::shared_ptr<IProjectStore> store_;
    QgsMapCanvas* canvas_ = nullptr;
    std::optional<DomainLayerFacts> active_facts_;
    std::string active_layer_error_;
    std::optional<std::string> mapping_stage_;
    std::string current_tool_ = "pan";
};

}  // namespace pwb::application
