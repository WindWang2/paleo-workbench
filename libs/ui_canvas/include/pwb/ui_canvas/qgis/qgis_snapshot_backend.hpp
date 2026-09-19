// UI-15 — QgisSnapshotRenderBackend: the QgisMapRenderBackend port
// (mapping/map_render_backend.py frozen semantics). Wraps the vendored
// QgisRenderBridge behind the Qt-free MapRenderBackend contract:
//
//   * initialize() creates + initializes the process-global QGIS runtime
//   * set_layer_snapshot pushes the encoded wire payload eagerly when the
//     bridge exists; otherwise marks pending for the next render request
//   * request_render coalesces through the native parallel job;
//     take_completed_frame guards the newest generation
//   * render_sync / export_map_body run the same renderer synchronously
//   * the #932 stale-delta rejection anywhere in the stack triggers a
//     full reship + retry once
//   * shutdown() tears down the bridge + clears the encoder caches
//
// install_qgis_backend_factory() registers this backend with the core
// factory registry behind a cached runtime probe (qgis_backend_probe
// parity) — a broken QGIS prefix degrades to the next registered
// backend instead of killing canvas construction.
#pragma once

#include <memory>
#include <optional>
#include <string>
#include <utility>

#include <pwb/ui_canvas/map_render_backend.hpp>
#include <pwb/ui_canvas/snapshot_encoder.hpp>

namespace pwb::qgis_render {
class QgisRenderBridge;
}

namespace pwb::ui_canvas::qgis {

class QgisSnapshotRenderBackend final : public MapRenderBackend {
public:
    QgisSnapshotRenderBackend() = default;
    ~QgisSnapshotRenderBackend() override;

    std::string backend_name() const override { return "qgis"; }
    bool light_frame_background() const override { return true; }

    // The native bridge is compiled into this target — always "available";
    // initialize() is the real usability check (Python parity: the
    // pybind-ImportError branch has no C++ equivalent).
    bool is_available() const override { return true; }

    // "available" before init, "ready (version)" after — Python status.
    std::string status() const override;

    void initialize() override;
    void set_layer_snapshot(const MapRenderSnapshot& snapshot) override;
    std::uint64_t request_render() override;
    std::optional<RenderFrame> take_completed_frame() override;
    bool render_active() const override;
    void cancel_render() override;
    RenderFrame render_sync() override;
    bool export_map_body(const std::string& path, const std::string& format,
                         int width, int height, double dpi) override;
    void shutdown() override;

    // Diagnostics for tests/ledger (encoding_stats parity).
    const SnapshotEncoderState& encoder_state() const { return encoder_state_; }

private:
    // Encode + push the current snapshot; updates shipped_revisions on
    // success. May throw (stale-delta included — callers recover).
    void push_native_snapshot();
    // _reship_full_snapshot parity: force every vector layer to a full
    // payload, push, restore shipped_revisions.
    void reship_full_snapshot();

    std::unique_ptr<pwb::qgis_render::QgisRenderBridge> bridge_;
    bool native_snapshot_pending_ = false;
    SnapshotEncoderState encoder_state_;
};

// Register this backend with the core factory registry (is_qgis=true).
// The factory consults the cached probe first — a QGIS runtime that fails
// to initialize produces nullptr so the selector moves on (Python's
// create_map_render_backend probe + degrade parity).
void install_qgis_backend_factory();

// One-shot guarded QGIS runtime probe (qgis_backend_probe parity): the
// result is cached process-wide; the returned reason is actionable and
// empty on success.
std::pair<bool, std::string> qgis_backend_probe();

}  // namespace pwb::ui_canvas::qgis
