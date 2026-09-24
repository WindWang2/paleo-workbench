// UI-15 — latest-revision asynchronous raster delivery
// (native_render_worker.py NativeRasterRequestController parity).

#include <pwb/ui_canvas/qt/native_raster_controller.hpp>

#include <pwb/qgis_processing/job_compat.hpp>
#include <pwb/ui_canvas/qt/qt_meta.hpp>

#include <algorithm>

namespace pwb::ui_canvas {

namespace {

std::string request_key(const NativeRasterRequest& request) {
    return "ui_canvas.raster." + request.layer_id;
}

}  // namespace

NativeRasterRequestController::NativeRasterRequestController(
    QObject* parent)
    : QObject(parent) {
    // One task slot — Python's single OwnedWorkerJob per controller.
    job_ = new pwb::qgis_processing::PwbTaskOwner(this);
    // released() fires only on shutdown() — the guard inside
    // dispatch_next makes that hop a no-op; normal completion dispatch
    // happens inside the finished callback (see start()).
    connect(job_, &pwb::qgis_processing::PwbTaskOwner::released, this,
            &NativeRasterRequestController::dispatch_next);
}

bool NativeRasterRequestController::same_request(
    const std::optional<NativeRasterRequest>& left,
    const NativeRasterRequest& right) {
    return left.has_value() && left->scene_epoch == right.scene_epoch &&
           left->layer_id == right.layer_id &&
           left->raster_key == right.raster_key &&
           left->scalar == right.scalar;
}

void NativeRasterRequestController::request(
    std::uint64_t scene_epoch, std::string layer_id, RasterKey raster_key,
    ScalarRasterSourcePtr scalar) {
    if (shutdown_) {
        return;
    }
    NativeRasterRequest next{scene_epoch, std::move(layer_id), raster_key,
                             std::move(scalar)};
    const auto desired_it = desired_.find(next.layer_id);
    if (desired_it != desired_.end() &&
        same_request(desired_it->second, next)) {
        return;
    }
    desired_[next.layer_id] = next;
    if (!active_.has_value()) {
        start(next);
        return;
    }
    if (active_->layer_id == next.layer_id) {
        // Native rasterization cannot be safely force-stopped. Cancellation
        // means suppressing delivery after its bounded current call returns.
        job_->cancel();
    }
    // Re-queue keeps the layer's ORIGINAL pending slot (OrderedDict parity).
    const auto pending_it =
        std::find_if(pending_order_.begin(), pending_order_.end(),
                     [&next](const NativeRasterRequest& entry) {
                         return entry.layer_id == next.layer_id;
                     });
    if (pending_it != pending_order_.end()) {
        *pending_it = next;
    } else {
        pending_order_.push_back(next);
    }
}

void NativeRasterRequestController::invalidate() {
    desired_.clear();
    pending_order_.clear();
    if (active_.has_value()) {
        job_->cancel();
    }
}

bool NativeRasterRequestController::shutdown(int wait_ms) {
    shutdown_ = true;
    invalidate();
    // The task keeps running under QgsTaskManager when it refuses the
    // bounded join (adoption) — the boolean stays the #1042 contract.
    return job_->shutdown(wait_ms);
}

bool NativeRasterRequestController::is_running() const {
    return job_->is_running();
}

void NativeRasterRequestController::start(
    const NativeRasterRequest& request) {
    active_ = request;
    const NativeRasterRequest captured = request;
    pwb::job::JobSpec spec;
    spec.kind = "cpu";
    spec.title = "native scalar raster";
    // task_key dedupes a re-queued same-layer request while the previous
    // one is still QUEUED — supersede semantics match OrderedDict
    // replacement exactly.
    spec.task_key = request_key(request);
    spec.run = [captured](pwb::job::JobContext& ctx) -> std::any {
        ctx.check_cancelled();
        RasterImage image;
        // The payload releases the GIL-equivalent: rasterize runs the
        // native grid→RGBA pipeline off the GUI thread.
        image.width = captured.scalar->raster_width();
        image.height = captured.scalar->raster_height();
        image.stride = captured.scalar->raster_stride();
        image.rgba = captured.scalar->rasterize();
        ctx.check_cancelled();
        return image;
    };
    pwb::qgis_processing::start_job_spec(
        *job_, std::move(spec),
        [this, captured](
            const pwb::qgis_processing::CompatJobOutcome& outcome) {
            if (!shutdown_) {
                if (outcome.state == pwb::job::JobState::done ||
                    outcome.state == pwb::job::JobState::degraded) {
                    if (same_request(desired_lookup(captured.layer_id),
                                     captured)) {
                        const auto* image =
                            std::any_cast<RasterImage>(&outcome.result);
                        if (image != nullptr) {
                            emit raster_ready(captured, *image);
                        }
                    }
                } else if (outcome.state == pwb::job::JobState::failed) {
                    if (same_request(desired_lookup(captured.layer_id),
                                     captured)) {
                        emit raster_failed(
                            captured,
                            QString::fromStdString(outcome.error));
                    }
                }
                // cancelled: Python's cancelled signal has no consumer —
                // the released hop still starts the next pending request
                // below.
            }
            // PwbTaskOwner emits released() only on shutdown(); the
            // finished-delivery hop is the terminal event that frees this
            // slot (the task is already terminal here, so re-start is
            // legal). Python's released → _on_released parity.
            dispatch_next();
        });
}

void NativeRasterRequestController::dispatch_next() {
    active_.reset();
    if (shutdown_ || pending_order_.empty()) {
        return;
    }
    NativeRasterRequest next = pending_order_.front();
    pending_order_.pop_front();
    if (same_request(desired_lookup(next.layer_id), next)) {
        start(next);
    } else {
        // A stale pending entry (desired replaced it after queueing):
        // skip and try the next one — Python recurses _on_released().
        if (!pending_order_.empty()) {
            dispatch_next();
        }
    }
}

std::optional<NativeRasterRequest>
NativeRasterRequestController::desired_lookup(
    const std::string& layer_id) const {
    const auto it = desired_.find(layer_id);
    if (it == desired_.end()) {
        return std::nullopt;
    }
    return it->second;
}

}  // namespace pwb::ui_canvas
