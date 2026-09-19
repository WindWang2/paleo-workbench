// UI-15 — Qt-free map-export spec (map_export_worker.py MapExportSpec
// parity). The worker/job plumbing lives in pwb_ui_canvas_qt; this header
// carries the frozen record and its validation so tests exercise it
// headless.
#pragma once

#include <optional>
#include <stdexcept>
#include <string>

#include <pwb/ui_canvas/map_render_backend.hpp>

namespace pwb::ui_canvas {

// One unified-map PNG export job's inputs (map_export_worker.MapExportSpec).
// `prefer_native_renderer` is True when the LIVE canvas backend is the QGIS
// renderer — the worker must interpret the same renderer payloads instead
// of the legacy painter vocabulary (which silently drops
// qgis_style.renderer_xml) (#923).
struct MapExportSpec {
    MapRenderSnapshot snapshot;
    Extent extent{0.0, 0.0, 1.0, 1.0};
    int width = 2400;
    int height = 1600;
    double dpi = 300.0;
    Json decorations = Json::object();
    std::string path;
    bool prefer_native_renderer = false;
};

// Honest engine report for one completed export — a fallback export is
// allowed but must never masquerade as a QGIS export (Python
// render_and_save_map_export return dict).
struct MapExportReport {
    std::string engine = "fallback";  // "qgis" | "fallback"
    bool degraded = false;
    std::string degraded_reason;      // "" when not degraded
};

// Internal: a cancel checkpoint fired between export phases
// (Python _ExportCancelled).
class ExportCancelled : public std::exception {
public:
    const char* what() const noexcept override {
        return "map export cancelled";
    }
};

// snapshot_map_export extent+size validation (Python parity):
//   * extent must contain four values — enforced by the Extent type;
//   * height nullopt → derived from the view extent aspect
//     (default_export_height); an explicit height must be >= 1;
//   * width/height must be >= 1 → std::invalid_argument.
MapExportSpec make_export_spec(MapRenderSnapshot snapshot,
                               const Extent& view_extent, std::string path,
                               int width, std::optional<int> height,
                               double dpi, Json decorations,
                               bool prefer_native_renderer);

// MapExportWorker._discard_partial parity: remove the target file written
// by a cancelled/failed render (best-effort, ignores all errors —
// #937-11 partial-file cleanup, #852 cancellation).
void discard_partial_export_file(const std::string& path);

}  // namespace pwb::ui_canvas
