// UI-15 — map export worker (ui/map_export_worker.py port). One export
// task runs the frozen render_and_save_map_export semantics on the QGIS
// task bridge (a PwbTaskOwner owning one QgsTaskManager task):
//
//   * MapExportWorker  — the QObject surface (start/cancel/shutdown +
//     finished/failed/cancelled signals) mirroring Python's
//     MapExportWorker + OwnedWorkerJob pair; the PwbTaskOwner is internal
//     so ownership semantics stay identical (the worker QObject parents
//     the whole task).
//   * render_and_save_map_export — the synchronous task body (native QGIS
//     attempt → fallback renderer → QImage + decorations + PNG write),
//     throwing ExportCancelled at cancellation checkpoints and
//     std::runtime_error on failures.
//   * snapshot_map_export — capture a UnifiedMapCanvas into a spec
//     (backend snapshot + view extent + overlay decorations +
//     prefer_native_renderer when the live canvas runs QGIS).
//   * unified_map_canvas_from — the duck-walk helper: qobject_cast first,
//     then the first descendant UnifiedMapCanvas (Python's attribute-walk
//     equivalent for wrapper hosts).
//
// discard-on-failure semantics (#937-11 / #852): every non-success
// outcome removes the partial output file.
#pragma once

#include <functional>
#include <memory>
#include <optional>
#include <string>

#include <QObject>
#include <QString>

#include <pwb/qgis_processing/task_bridge.hpp>
#include <pwb/ui_canvas/export_core.hpp>

class QWidget;

namespace pwb::ui_canvas {

class UnifiedMapCanvas;

// render_and_save_map_export parity — the synchronous task body.
// `cancel` is a predicate (Python callable[[], bool]) checked at exactly
// three checkpoints: after the native render, after the fallback render,
// and after decorations before the PNG write — the renders themselves
// are non-interruptible. Throws ExportCancelled at a checkpoint and
// std::runtime_error on failures.
MapExportReport render_and_save_map_export(
    const MapExportSpec& spec,
    const std::function<bool()>& cancel = {});

// snapshot_map_export parity — capture the canvas into a frozen spec.
MapExportSpec snapshot_map_export(const UnifiedMapCanvas& canvas,
                                  std::string path, int width = 2400,
                                  std::optional<int> height = std::nullopt,
                                  double dpi = 300.0);

// Duck-walk parity: the widget itself, else its first descendant canvas.
UnifiedMapCanvas* unified_map_canvas_from(QWidget* widget);

// The worker/task pair: start() submits one export task on the QGIS
// task bridge owned by an internal PwbTaskOwner (the OwnedWorkerJob port
// keeps the same one-job-per-worker ownership). cancel() is cooperative
// (threading.Event.set parity); shutdown(wait_ms) reports whether native
// work joined — false means the task keeps running under QgsTaskManager
// (adoption, #1042 bounded-shutdown contract).
class MapExportWorker : public QObject {
    Q_OBJECT

public:
    explicit MapExportWorker(MapExportSpec spec, QObject* parent = nullptr);
    ~MapExportWorker() override;

    const MapExportSpec& spec() const { return spec_; }

    void start();
    void cancel();
    bool is_running() const;
    bool shutdown(int wait_ms = 3000);

    // The completed report (engine/degraded honesty record); std::nullopt
    // until a success — the worker-level counterpart of the Python
    // run() discarding the dict (kept here for hosts/tests).
    const std::optional<MapExportReport>& report() const { return report_; }

signals:
    void finished(const QString& path);
    void failed(const QString& message);
    void cancelled();

private:
    MapExportSpec spec_;
    std::optional<MapExportReport> report_;
    pwb::qgis_processing::PwbTaskOwner job_;  // one export task slot
    bool started_ = false;
};

}  // namespace pwb::ui_canvas
