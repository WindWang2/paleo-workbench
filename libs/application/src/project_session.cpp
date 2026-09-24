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
    layout_ = std::make_unique<pwb::qgis::LayoutAuthority>(*map_);
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

namespace {
// B uses operation ids as journal file names ([A-Za-z0-9._-], no leading
// dot). QGIS layer ids carry user layer names — sanitize instead of
// letting a space or CJK character reject the whole commit.
std::string safe_segment(const std::string& raw) {
    std::string out;
    out.reserve(raw.size());
    for (const char c : raw) {
        const bool safe = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
            || (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-';
        out.push_back(safe ? c : '_');
    }
    while (!out.empty() && out.front() == '.') out.erase(out.begin());
    return out.empty() ? std::string("layer") : out;
}
}  // namespace

std::string ProjectSession::operation_id_for(
    const std::string& layer_id, const pwb::qgis::StagedAsset& staged) {
    const auto it = pending_operations_.find(layer_id);
    if (it != pending_operations_.end()
        && it->second.sha256 == staged.sha256
        && it->second.base_revision == staged.base_revision) {
        // Same staged round retried — B replays the recorded receipt for
        // this id (idempotency by design).
        return it->second.operation_id;
    }
    // New round: content hash + base revision make the id unique per edit
    // round and stable across process restarts.
    PendingOperation pending;
    pending.operation_id = "pwb-edit-" + safe_segment(layer_id)
        + "-r" + std::to_string(staged.base_revision)
        + "-" + staged.sha256.substr(0, 8);
    pending.sha256 = staged.sha256;
    pending.base_revision = staged.base_revision;
    const std::string id = pending.operation_id;
    pending_operations_[layer_id] = std::move(pending);
    return id;
}

std::string ProjectSession::frozen_base_version(
    const std::string& layer_id) const {
    if (store_ == nullptr) return "";
    // Freeze the bound version the user actually edited against (B's
    // optimistic lock); "" lets B resolve binding -> asset head.
    for (const LayerBindingV1& binding : store_->load_bindings()) {
        if (binding.layer_id == layer_id && !binding.version_id.empty()) {
            return binding.version_id;
        }
    }
    return "";
}

pwb::qgis::StagedAsset ProjectSession::stage_commit(
    const std::string& layer_id, const std::filesystem::path& staged_dir,
    std::string* error) {
    pwb::qgis::StagedAsset staged;

    // 1) Stage from the LIVE edit buffer: the user's source provider is
    //    not written yet; a failure here keeps the session retryable.
    const std::string stage_error =
        edit_->stage(layer_id, staged_dir, &staged);
    if (!stage_error.empty()) {
        if (error != nullptr) *error = stage_error;
        return staged;
    }

    if (store_ == nullptr) {
        // Module-only mode: the working file is the only persistence
        // available — finalize it, then report honestly instead of faking
        // a catalog receipt.
        const std::string finalize_error = edit_->finalize(layer_id);
        if (error != nullptr) {
            *error = finalize_error.empty()
                ? "no project store attached (module-only mode); committed "
                  "to the working file only, staged asset at "
                  + staged.geojson_path.string()
                : finalize_error;
        }
        return staged;
    }

    // 2) Catalog transaction first (stable operation id per staged round).
    CommitRequestV1 request;
    request.operation_id = operation_id_for(layer_id, staged);
    request.base_version = frozen_base_version(layer_id);
    request.staged = staged;
    const CommitReceiptV1 receipt = store_->commit(request);
    if (!receipt.ok) {
        // Buffer alive, staged file intact: repair + retry (same content
        // reuses the same operation id).
        if (error != nullptr) {
            *error = "store rejected commit: " + receipt.error;
        }
        return staged;
    }

    // 3) B accepted — now write the user's source provider and close the
    //    round. A failure here leaves the catalog version authoritative;
    //    the working copy can be reloaded from it.
    pwb::qgis::EditDeltaV1 delta;
    const std::string finalize_error = edit_->finalize(layer_id, &delta);
    if (error != nullptr && !finalize_error.empty()) {
        *error = "catalog version " + receipt.new_version
            + " committed, but the working file commit failed: "
            + finalize_error + " — reload the layer from the catalog "
              "version";
    }
    pending_operations_.erase(layer_id);
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
    // Detach, don't destroy: the session object stays reusable for the
    // rest of the window's life (edit() must never return a null
    // dereference, and a close-then-open switch needs a live
    // controller) — #1447.
    if (edit_ != nullptr) edit_->detach_all();
    active_facts_.reset();
    canvas_ = nullptr;
    map_->close();
}

}  // namespace pwb::application
