// UI-15 — QgisSnapshotRenderBackend (QgisMapRenderBackend parity).

#include <pwb/ui_canvas/qgis/qgis_snapshot_backend.hpp>

#include <pwb/ui_canvas/qgis/snapshot_codec.hpp>

#include "qgis_render_bridge.hpp"

namespace pwb::ui_canvas::qgis {

QgisSnapshotRenderBackend::~QgisSnapshotRenderBackend() { shutdown(); }

std::string QgisSnapshotRenderBackend::status() const {
    // Python: native None -> unavailable (no C++ equivalent); bridge None
    // -> "available"; else "ready (version)".
    if (!bridge_) {
        return "available";
    }
    return "ready (" + bridge_->version() + ")";
}

void QgisSnapshotRenderBackend::initialize() {
    if (initialized()) {
        return;
    }
    bridge_ = std::make_unique<pwb::qgis_render::QgisRenderBridge>();
    bridge_->initialize();
    mark_initialized(true);
}

void QgisSnapshotRenderBackend::set_layer_snapshot(
    const MapRenderSnapshot& snapshot) {
    MapRenderBackend::set_layer_snapshot(snapshot);
    if (bridge_) {
        push_native_snapshot();
    } else {
        // Bridge not created yet (or shut down): deliver on the next
        // render request, which initializes the bridge on the async
        // path too.
        native_snapshot_pending_ = true;
    }
}

void QgisSnapshotRenderBackend::push_native_snapshot() {
    bool shipped = false;
    try {
        bridge_->set_layer_snapshot(
            layer_specs_from_json(
                encode_qgis_snapshot(snapshot(), encoder_state_)),
            snapshot().project_crs);
        shipped = true;
    } catch (const std::runtime_error& exc) {
        if (!is_stale_delta_error(exc)) {
            throw;
        }
        reship_full_snapshot();
        shipped = true;
    }
    // Python `finally` parity: shipped_revisions only advance when a
    // snapshot (or its full reship) actually reached the bridge.
    if (shipped) {
        for (const MapLayerSnapshot& layer : snapshot().layers) {
            encoder_state_.shipped_revisions[layer.id] =
                layer.data_revision;
        }
    }
    // _native_snapshot parity: prune caches for layers no longer present
    // as vectors so removed layers do not pin stale feature payloads.
    prune_encoder_state(encoder_state_, snapshot());
}

void QgisSnapshotRenderBackend::reship_full_snapshot() {
    // Force a full reship after the bridge rejected a stale feature
    // delta: the delta's base revision no longer matches the bridge
    // mirror (e.g. the runtime restarted under us, or the snapshot was
    // stashed behind an active render). The bridge validates deltas
    // before mutating mirrors, so half-applied state is impossible;
    // recovery is reshipping every vector layer in full (#932).
    encoder_state_.force_full_ids.clear();
    for (const MapLayerSnapshot& layer : snapshot().layers) {
        if (layer.layer_type != "scalar_grid" &&
            layer.layer_type != "grid" &&
            layer.layer_type != "raster_source") {
            encoder_state_.force_full_ids.insert(layer.id);
        }
    }
    try {
        bridge_->set_layer_snapshot(
            layer_specs_from_json(
                encode_qgis_snapshot(snapshot(), encoder_state_)),
            snapshot().project_crs);
    } catch (...) {
        encoder_state_.force_full_ids.clear();
        throw;
    }
    encoder_state_.force_full_ids.clear();
    for (const MapLayerSnapshot& layer : snapshot().layers) {
        encoder_state_.shipped_revisions[layer.id] = layer.data_revision;
    }
}

std::uint64_t QgisSnapshotRenderBackend::request_render() {
    if (!initialized()) {
        initialize();
    }
    if (native_snapshot_pending_) {
        // A snapshot arrived before the bridge existed; push it now so
        // the first async render composes current layers instead of a
        // blank frame.
        native_snapshot_pending_ = false;
        push_native_snapshot();
    }
    const std::uint64_t generation = next_generation();
    // Python `self._completed = None` — clears only the host-side cached
    // frame; the bridge coalesces the in-flight job itself (calling
    // bridge_->cancel_render() here would kill the running render).
    MapRenderBackend::cancel_render();
    try {
        bridge_->request_render(extent(), output_size().first,
                                output_size().second, dpi(), generation);
    } catch (const std::runtime_error& exc) {
        if (!is_stale_delta_error(exc)) {
            throw;
        }
        // A snapshot stashed behind the previous render only failed
        // delta validation when the job finished inside this call;
        // recover with a full reship and re-issue the same request.
        reship_full_snapshot();
        bridge_->request_render(extent(), output_size().first,
                                output_size().second, dpi(), generation);
    }
    return generation;
}

std::optional<RenderFrame> QgisSnapshotRenderBackend::take_completed_frame() {
    if (!bridge_) {
        return std::nullopt;
    }
    std::optional<pwb::qgis_render::RenderResult> payload;
    try {
        payload = bridge_->take_completed_frame();
    } catch (const std::runtime_error& exc) {
        if (!is_stale_delta_error(exc)) {
            throw;
        }
        // Same deferred-delta rejection, surfacing when the finished job
        // applied a stashed snapshot. Reship fully and re-render so the
        // canvas still receives a frame for its current state.
        reship_full_snapshot();
        request_render();
        return std::nullopt;
    }
    if (!payload) {
        return std::nullopt;
    }
    // The native bridge normally rejects stale output itself. Keep the
    // host guard too: a delayed result can never paint over a newer
    // viewport.
    if (payload->generation != generation()) {
        return std::nullopt;
    }
    return RenderFrame{payload->generation, payload->width, payload->height,
                       payload->stride, std::move(payload->rgba),
                       payload->render_ms};
}

bool QgisSnapshotRenderBackend::render_active() const {
    return bridge_ && bridge_->render_active();
}

void QgisSnapshotRenderBackend::cancel_render() {
    MapRenderBackend::cancel_render();
    if (bridge_) {
        bridge_->cancel_render();
    }
}

RenderFrame QgisSnapshotRenderBackend::render_sync() {
    if (!initialized()) {
        initialize();
    }
    // #941-6: only push when a snapshot arrived before the bridge existed
    // (set_layer_snapshot already pushes eagerly otherwise) — re-pushing
    // every sync frame re-parsed the full payload (~100 ms @ 100k).
    if (native_snapshot_pending_) {
        native_snapshot_pending_ = false;
        push_native_snapshot();
    }
    const std::uint64_t generation = next_generation();
    pwb::qgis_render::RenderResult payload;
    try {
        payload = bridge_->render_sync(extent(), output_size().first,
                                       output_size().second, dpi());
    } catch (const std::runtime_error& exc) {
        if (!is_stale_delta_error(exc)) {
            throw;
        }
        // Deferred delta rejection can surface here too (the sync path
        // also applies stashed snapshots); reship fully and retry once.
        reship_full_snapshot();
        payload = bridge_->render_sync(extent(), output_size().first,
                                       output_size().second, dpi());
    }
    return RenderFrame{generation, payload.width, payload.height,
                       payload.stride, std::move(payload.rgba),
                       payload.render_ms};
}

bool QgisSnapshotRenderBackend::export_map_body(const std::string& path,
                                                const std::string& format,
                                                int width, int height,
                                                double dpi) {
    if (!initialized()) {
        initialize();
    }
    if (format != "svg" && format != "pdf") {
        return false;
    }
    native_snapshot_pending_ = false;
    push_native_snapshot();
    const std::size_t written = bridge_->export_vector(
        path, format, extent(), width, height, dpi);
    return written > 0;
}

void QgisSnapshotRenderBackend::shutdown() {
    if (bridge_) {
        bridge_->shutdown();
        bridge_.reset();
    }
    encoder_state_ = SnapshotEncoderState{};
    native_snapshot_pending_ = false;
    MapRenderBackend::shutdown();
}

// ---------------------------------------------------------------------------
// Probe + factory
// ---------------------------------------------------------------------------

std::pair<bool, std::string> qgis_backend_probe() {
    // One-shot guarded probe — the result is cached process-wide
    // (qgis_backend_probe parity; the pybind-ImportError branch has no
    // C++ equivalent since the bridge is compiled in).
    static const std::pair<bool, std::string> cached = [] {
        try {
            QgisSnapshotRenderBackend backend;
            backend.initialize();
            backend.shutdown();
        } catch (const std::exception& exc) {
            return std::make_pair(
                false,
                std::string(
                    "QGIS 运行时初始化失败：") +
                    exc.what());
        } catch (...) {
            return std::make_pair(
                false,
                std::string("QGIS 运行时初始化失败：unknown error"));
        }
        return std::make_pair(true, std::string{});
    }();
    return cached;
}

void install_qgis_backend_factory() {
    register_backend_factory(
        []() -> std::shared_ptr<MapRenderBackend> {
            if (!qgis_backend_probe().first) {
                return nullptr;
            }
            return std::make_shared<QgisSnapshotRenderBackend>();
        },
        /*is_qgis=*/true);
}

}  // namespace pwb::ui_canvas::qgis
