// UI-15 — latest-revision asynchronous raster delivery for native
// scalar-map layers (native_render_worker.py parity).
//
// The native scalar payload remains the only pixel cache. This coordinator
// owns in-flight work only: each completed raster snapshot is handed to the
// Qt canvas, which accepts it only when the scalar revision and canvas
// scene epoch still match. It never stores a second scientific grid or
// invokes interpolation.
//
// C++ ownership: one JobScheduler lane + one JobOwner (the OwnedWorkerJob
// port — CONV-30). Latest-request-per-layer tracking, cooperative cancel
// (delivery suppression, never a force-stop of native raster work), stale
// result suppression by request identity, and the boolean shutdown/join
// report are all preserved.
#pragma once

#include <deque>
#include <map>
#include <memory>
#include <optional>
#include <string>

#include <QObject>

#include <pwb/job_runtime/job_scheduler.hpp>
#include <pwb/job_runtime/qt/job_bridge.hpp>
#include <pwb/ui_canvas/layer_scene.hpp>

namespace pwb::ui_canvas {

// One rasterization unit (Python _Request parity). `scalar` identity
// matters: same_request compares shared_ptrs (Python `is`).
struct NativeRasterRequest {
    std::uint64_t scene_epoch = 0;
    std::string layer_id;
    RasterKey raster_key{0, 0};
    ScalarRasterSourcePtr scalar;
};

// Queue one worker at a time while retaining the latest revision per
// layer. Several scalar layers may be visible simultaneously, so a new
// request for one layer does not discard another layer's useful in-flight
// render; a changed revision for the SAME layer cooperatively cancels
// delivery and replaces the queued request.
class NativeRasterRequestController : public QObject {
    Q_OBJECT
public:
    explicit NativeRasterRequestController(QObject* parent = nullptr);

    // Queue (or replace) the raster work for one layer.
    void request(std::uint64_t scene_epoch, std::string layer_id,
                 RasterKey raster_key, ScalarRasterSourcePtr scalar);

    // Discard all queued/deliverable work after a canvas scene replacement.
    void invalidate();

    // Tear the raster worker down and report whether its lane joined.
    // false means the worker was detached while still running native
    // raster work (#1042) — callers gate catalog close / export success
    // on this instead of silently proceeding.
    bool shutdown(int wait_ms = 3000);

    bool is_running() const;

    // Test/self-check visibility into the queues (Python test parity —
    // tests assert on _desired/_pending sizes).
    std::size_t desired_count() const { return desired_.size(); }
    std::size_t pending_count() const { return pending_order_.size(); }
    bool has_active() const { return active_.has_value(); }

signals:
    void raster_ready(const pwb::ui_canvas::NativeRasterRequest& request,
                      const pwb::ui_canvas::RasterImage& image);
    void raster_failed(const pwb::ui_canvas::NativeRasterRequest& request,
                       const QString& message);

private:
    static bool same_request(
        const std::optional<NativeRasterRequest>& left,
        const NativeRasterRequest& right);

    void start(const NativeRasterRequest& request);
    // Free the active slot and start the oldest still-desired pending
    // request (Python _on_released parity — invoked from the finished
    // delivery hop, and harmlessly on JobOwner::released during shutdown).
    void dispatch_next();
    std::optional<NativeRasterRequest> desired_lookup(
        const std::string& layer_id) const;

    std::shared_ptr<pwb::job::JobScheduler> scheduler_;
    pwb::job::qtbridge::JobOwner* job_ = nullptr;  // child QObject
    std::optional<NativeRasterRequest> active_;
    // FIFO pending queue keyed by layer (Python OrderedDict parity —
    // re-queueing a layer keeps its ORIGINAL slot order).
    std::deque<NativeRasterRequest> pending_order_;
    std::map<std::string, NativeRasterRequest> desired_;
    bool shutdown_ = false;
};

}  // namespace pwb::ui_canvas

Q_DECLARE_METATYPE(pwb::ui_canvas::NativeRasterRequest)
