// UI-15 — map export worker (map_export_worker.py parity).

#include <pwb/ui_canvas/qt/map_export_worker.hpp>

#include <pwb/ui_canvas/qt/fallback_map_backend.hpp>

#include <QImage>
#include <QMetaType>
#include <QPainter>
#include <QWidget>

#include <pwb/job_runtime/job_scheduler.hpp>
#include <pwb/job_runtime/qt/job_bridge.hpp>
#include <pwb/ui_canvas/qt/unified_map_canvas.hpp>
#include <pwb/ui_widgets/map_chrome.hpp>
#include <pwb/ui_widgets/ui_context.hpp>

#include "json_variant.hpp"

namespace pwb::ui_canvas {

namespace {

// RenderContext.device_px_per_logical_px(dpi): physical device px per
// logical px — dpi / 96 for exports (Python parity).
double device_px_per_logical_px(double dpi) {
    return dpi > 0.0 ? dpi / 96.0 : 1.0;
}

}  // namespace

MapExportReport render_and_save_map_export(
    const MapExportSpec& spec,
    const std::function<bool()>& cancel) {
    std::optional<RenderFrame> frame;
    MapExportReport report;
    if (spec.prefer_native_renderer) {
        // _render_frame_native parity: a throwaway native backend born and
        // torn down on this worker thread — render_sync needs no caller
        // event loop. Anything that fails degrades to the fallback
        // renderer, never loses the export (#923).
        try {
            std::shared_ptr<MapRenderBackend> backend =
                create_native_map_render_backend();
            if (!backend) {
                throw std::runtime_error("qgis renderer unavailable");
            }
            try {
                backend->set_layer_snapshot(spec.snapshot);
                backend->set_extent(spec.extent);
                backend->set_output_size(spec.width, spec.height);
                backend->set_dpi(spec.dpi);
                frame = backend->render_sync();
            } catch (...) {
                try {
                    backend->shutdown();
                } catch (...) {
                }
                throw;
            }
            try {
                backend->shutdown();
            } catch (...) {
            }
            if (frame.has_value()) {
                report.engine = "qgis";  // only once a frame exists
            }
        } catch (const std::exception& exc) {
            report.degraded = true;
            report.degraded_reason = exc.what();
            frame.reset();
        } catch (...) {
            report.degraded = true;
            report.degraded_reason = "unknown native renderer error";
            frame.reset();
        }
    } else {
        report.degraded = true;
        report.degraded_reason =
            "QGIS renderer not requested for this export";
    }
    if (cancel && cancel()) {
        throw ExportCancelled();
    }
    if (!frame.has_value()) {
        // The fallback path — create_map_render_backend(prefer_qgis=false)
        // picks the first registered non-QGIS factory. Installing here is
        // what makes the fallback concrete (Python has it built into the
        // selector; static-library TUs need an explicit pull).
        qt::install_fallback_backend_factory();
        std::shared_ptr<MapRenderBackend> backend =
            create_map_render_backend(/*prefer_qgis=*/false);
        backend->set_layer_snapshot(spec.snapshot);
        backend->set_extent(spec.extent);
        backend->set_output_size(spec.width, spec.height);
        backend->set_dpi(spec.dpi);
        frame = backend->render_sync();
    }
    if (cancel && cancel()) {
        // The (non-interruptible) frame render finished while the user
        // was cancelling: stop BEFORE decorations/save instead of
        // producing a half-product (#1224 honest cancellation).
        throw ExportCancelled();
    }
    QImage image =
        QImage(frame->rgba.data(), frame->width, frame->height,
               frame->stride, QImage::Format_RGBA8888)
            .copy();
    {
        QPainter painter(&image);
        painter.setRenderHint(QPainter::Antialiasing, true);
        pwb::ui_widgets::paint_map_decorations(
            painter, qt::detail::json_to_variant_map(spec.decorations),
            spec.width, spec.height, spec.extent,
            device_px_per_logical_px(spec.dpi),
            /*dark_chrome=*/true);
    }
    if (cancel && cancel()) {
        throw ExportCancelled();
    }
    if (!image.save(QString::fromStdString(spec.path), "PNG")) {
        throw std::runtime_error("could not save unified map PNG");
    }
    return report;
}

MapExportSpec snapshot_map_export(const UnifiedMapCanvas& canvas,
                                  std::string path, int width,
                                  std::optional<int> height, double dpi) {
    MapRenderBackend* backend = canvas.backend();
    if (backend == nullptr) {
        // Python reads canvas.backend._snapshot directly — a missing
        // backend surfaces the same loud failure.
        throw std::runtime_error(
            "cannot snapshot an export without a render backend");
    }
    const Extent extent = canvas.view_extent();
    Json decorations = Json::object();
    if (canvas.overlay_provider()) {
        const Json state = canvas.overlay_provider()();
        const auto it = state.find("decorations");
        if (it != state.end() && it->is_object()) {
            decorations = *it;
        }
    }
    return make_export_spec(backend->snapshot(), extent, std::move(path),
                            width, height, dpi, std::move(decorations),
                            backend->backend_name() == "qgis");
}

UnifiedMapCanvas* unified_map_canvas_from(QWidget* widget) {
    // Duck-walk parity: the widget itself, else its first descendant
    // canvas (the Python attribute names canvas/unified_canvas/widget
    // all resolve to a descendant lookup in Qt).
    if (auto* canvas = qobject_cast<UnifiedMapCanvas*>(widget)) {
        return canvas;
    }
    return widget ? widget->findChild<UnifiedMapCanvas*>() : nullptr;
}

// ---------------------------------------------------------------------------
// MapExportWorker
// ---------------------------------------------------------------------------

MapExportWorker::MapExportWorker(MapExportSpec spec, QObject* parent)
    : QObject(parent), spec_(std::move(spec)) {
    // One background lane — Python's dedicated OwnedWorkerJob thread.
    pwb::job::JobScheduler::Options options;
    options.max_workers = 1;
    options.interactive_workers = 0;
    scheduler_ = std::make_unique<pwb::job::JobScheduler>(options);
    job_ = new pwb::job::qtbridge::JobOwner(this);
}

MapExportWorker::~MapExportWorker() { shutdown(0); }

void MapExportWorker::start() {
    if (started_) {
        return;
    }
    started_ = true;
    const MapExportSpec spec = spec_;
    pwb::job::JobSpec job;
    job.kind = "io";
    job.title = "unified map export";
    job.run = [spec](pwb::job::JobContext& ctx) -> std::any {
        // Worker.run() parity:
        //   pre-start cancel check → cancelled
        //   failure while cancelled → cancelled; otherwise → failed
        //   success + cancel raced → discard partial + cancelled
        const auto cancelled = [&ctx]() {
            return ctx.token().is_cancelled();
        };
        if (cancelled()) {
            ctx.check_cancelled();  // → JobCancelled
        }
        try {
            MapExportReport report =
                render_and_save_map_export(spec, cancelled);
            if (cancelled()) {
                // The render completed and wrote its file while the user
                // was cancelling: drop the stale half-product (#852).
                discard_partial_export_file(spec.path);
                ctx.check_cancelled();
                throw pwb::job::JobCancelled(ctx.job_id());
            }
            return report;
        } catch (const ExportCancelled&) {
            discard_partial_export_file(spec.path);
            ctx.check_cancelled();
            throw pwb::job::JobCancelled(ctx.job_id());
        } catch (...) {
            // A render that raised mid-way may have left partial bytes on
            // disk; a cancelled or failed export must never keep them
            // (#852 / #937-11).
            discard_partial_export_file(spec.path);
            if (cancelled()) {
                ctx.check_cancelled();
                throw pwb::job::JobCancelled(ctx.job_id());
            }
            throw;
        }
    };
    job_->start(*scheduler_, std::move(job),
                [this](const pwb::job::qtbridge::JobOutcome& outcome) {
                    switch (outcome.state) {
                    case pwb::job::JobState::done:
                    case pwb::job::JobState::degraded: {
                        const auto* report =
                            std::any_cast<MapExportReport>(&outcome.result);
                        if (report != nullptr) {
                            report_ = *report;
                        }
                        emit finished(
                            QString::fromStdString(spec_.path));
                        break;
                    }
                    case pwb::job::JobState::failed:
                        emit failed(
                            QString::fromStdString(outcome.error));
                        break;
                    case pwb::job::JobState::cancelled:
                        emit cancelled();
                        break;
                    default:
                        break;
                    }
                });
}

void MapExportWorker::cancel() {
    job_->cancel();  // cooperative — threading.Event.set parity
}

bool MapExportWorker::is_running() const { return job_->is_running(); }

bool MapExportWorker::shutdown(int wait_ms) {
    const bool joined = job_->shutdown(wait_ms);
    scheduler_->shutdown(false, wait_ms / 1000.0);
    return joined;
}

}  // namespace pwb::ui_canvas
