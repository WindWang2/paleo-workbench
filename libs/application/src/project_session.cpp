#include <pwb/application/project_session.hpp>

#include <qgsmapcanvas.h>
#include <qgsmaptool.h>
#include <qgsproject.h>
#include <qgsvectorlayer.h>
#include <qgsvectordataprovider.h>

#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/tool_policy/tool_availability.hpp>

namespace pwb::application {

ProjectSession::ProjectSession() {
    if (!pwb::qgis::QgisRuntime::initialized()) {
        throw std::logic_error("ProjectSession requires QgisRuntime::acquire() first");
    }
    map_ = std::make_unique<pwb::qgis::MapSession>();
    edit_ = std::make_unique<pwb::qgis::EditController>(*map_);
}

ProjectSession::~ProjectSession() { close(); }

void ProjectSession::attachCanvas(QgsMapCanvas* canvas) { canvas_ = canvas; }

void ProjectSession::set_active_layer(const DomainLayerFacts& facts) {
    // Invariant: active == canvas current == edit target. Setting the
    // domain layer here also pushes it as the canvas current layer; the
    // edit controller resolves layers by the same domain id.
    active_facts_ = facts;
    active_layer_error_.clear();
    if (canvas_ != nullptr) {
        QgsMapLayer* layer = map_->layerById(facts.layer_id);
        if (layer == nullptr) {
            active_layer_error_ = "active layer not registered: " + facts.layer_id;
            canvas_->setCurrentLayer(nullptr);
        } else {
            canvas_->setCurrentLayer(layer);
        }
    }
}

pwb::qgis::StagedAsset ProjectSession::stage_commit(
    const std::string& layer_id, const std::filesystem::path& staged_dir,
    std::string* error) {
    pwb::qgis::StagedAsset staged;
    pwb::qgis::EditDeltaV1 delta;
    const std::string commit_error =
        edit_->commit(layer_id, staged_dir, &staged, &delta);
    if (!commit_error.empty()) {
        if (error != nullptr) *error = commit_error;
        return staged;
    }
    if (store_ == nullptr) {
        // Module-only mode: the staged asset exists, but no B store is
        // attached — report honestly instead of faking a receipt.
        if (error != nullptr)
            *error = "no project store attached (module-only mode); staged asset at "
                + staged.geojson_path.string();
        return staged;
    }
    CommitRequestV1 request;
    request.operation_id = "pwb-edit-" + layer_id + "-"
        + std::to_string(staged.base_revision);
    // Base version comes from B's binding; without a store it stays empty
    // (honest unknown) rather than a fabricated id.
    request.base_version = std::string();
    request.staged = staged;
    const CommitReceiptV1 receipt = store_->commit(request);
    if (!receipt.ok && error != nullptr) {
        *error = "store rejected commit: " + receipt.error;
    }
    return staged;
}

pwb::tool_policy::ToolContextSnapshot ProjectSession::snapshot() const {
    pwb::tool_policy::ToolContextSnapshot ctx;
    ctx.project_open = map_ != nullptr && map_->project() != nullptr;
    ctx.qgis_available = pwb::qgis::QgisRuntime::initialized();
    ctx.native_canvas_available = ctx.qgis_available && canvas_ != nullptr;
    ctx.backend_mode = ctx.native_canvas_available ? "native" : "unknown";
    ctx.mapping_stage = mapping_stage_;

    if (active_facts_.has_value()) {
        const DomainLayerFacts& facts = *active_facts_;
        ctx.active_layer_id = facts.layer_id;
        ctx.layer_role = facts.role;
        ctx.layer_role_label = facts.role_label;
        ctx.layer_is_facies = facts.is_facies;
        ctx.artifact_maturity = facts.artifact_maturity;
        ctx.layer_frozen = facts.frozen;
        ctx.raw_locked = facts.raw_locked;
        ctx.stage_locked = facts.stage_locked;
        ctx.write_granted = facts.write_granted;
        // Honest fail-closed: without a B store, the domain gate verdict is
        // unknown; writable facts come from QGIS provider state below.
        if (facts.frozen || facts.raw_locked || facts.stage_locked) {
            ctx.edit_gate_open = false;
            if (facts.raw_locked)
                ctx.edit_gate_reason = pwb::tool_policy::raw_layer_gate_reason();
            else if (facts.frozen)
                ctx.edit_gate_reason = pwb::tool_policy::frozen_layer_gate_reason();
            else
                ctx.edit_gate_reason = "当前阶段的证据组已锁定，禁止编辑";
        } else if (facts.write_granted) {
            ctx.edit_gate_open = true;
        } else {
            ctx.edit_gate_open = std::nullopt;
        }

        QgsVectorLayer* layer = map_->vectorLayerById(facts.layer_id);
        if (layer != nullptr) {
            ctx.qgis_layer_type = "vector";
            switch (layer->geometryType()) {
                case Qgis::GeometryType::Point: ctx.active_layer_kind = "point"; break;
                case Qgis::GeometryType::Line: ctx.active_layer_kind = "line"; break;
                case Qgis::GeometryType::Polygon: ctx.active_layer_kind = "polygon"; break;
                default: ctx.active_layer_kind.clear(); break;
            }
            ctx.layer_name = layer->name().toStdString();
            ctx.vector_writable = true;
            const QgsVectorDataProvider* provider = layer->dataProvider();
            if (provider != nullptr) {
                ctx.provider_name = provider->name().toStdString();
                const Qgis::VectorProviderCapabilities caps =
                    provider->capabilities();
                ctx.provider_writable =
                    caps.testFlag(Qgis::VectorProviderCapability::AddFeatures)
                    && caps.testFlag(Qgis::VectorProviderCapability::ChangeGeometries)
                    && caps.testFlag(Qgis::VectorProviderCapability::ChangeAttributeValues);
            }
            ctx.selection_count = static_cast<int>(layer->selectedFeatureCount());
        } else {
            // Registered facts but the QGIS layer is missing: missing-layer
            // honest fact.
            ctx.layer_missing = true;
        }
    }

    if (active_facts_.has_value()) {
        const std::string& id = active_facts_->layer_id;
        ctx.editing = edit_->editing(id);
        ctx.dirty = edit_->dirty(id);
        ctx.can_undo = edit_->can_undo(id);
        ctx.can_redo = edit_->can_redo(id);
    }

    if (map_ != nullptr && map_->project() != nullptr) {
        ctx.queryable_layer_count = static_cast<int>(
            map_->layerIdsTopFirst().size());
    }
    ctx.snapping_available = true;
    ctx.topology_available = true;
    ctx.current_tool = current_tool_;
    // Native-path capability manifest: the platform's compiled-in tools.
    ctx.capability_flags = {
        "qgis.native_tool.identify", "qgis.native_tool.select",
        "qgis.native_tool.addPoint", "qgis.native_tool.addLine",
        "qgis.native_tool.addPolygon", "qgis.native_tool.move",
        "qgis.native_tool.vertex", "qgis.native_tool.faultCut",
        "qgis.native_tool.boundaryReshape",
        "qgis.geometry_op.validate", "qgis.geometry_op.reshape",
        "qgis.geometry_op.add_part", "qgis.snapping_push",
    };
    return ctx;
}

void ProjectSession::close() {
    if (map_ == nullptr) return;
    edit_.reset();
    active_facts_.reset();
    canvas_ = nullptr;
    map_->close();
}

}  // namespace pwb::application
