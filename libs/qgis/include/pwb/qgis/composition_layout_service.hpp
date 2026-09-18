// CompositionLayoutService — CONV-27 product wiring of the full native
// composition export chain:
//
//   Composition JSON (mapping_document kernel) → layout_export kernel spec
//   → layout_spec_exec (the ONE spec executor, shared with the pybind
//   bridge) → file + honest report.
//
// No Python anywhere on this path; the pybind bridge is the legacy runtime
// facing the same executor. Every service entry returns a JSON report and
// never fakes success (fail-closed policy, 27-decisions.md D-03).

#pragma once

#include <filesystem>
#include <string>

#include <pwb/domain/json.hpp>

namespace pwb::layout_spec_exec {
struct ExecContext;
}

namespace pwb::qgis {

class MapSession;

struct CompositionExportRequest {
    std::string format = "pdf";  // pdf|svg|png
    double dpi = 300.0;
    bool geo_pdf = false;
    bool force_vector = false;   // vector-preservation opt-in (pdf/svg)
    std::string background;      // page fill; "" = layout default (white)
    bool has_extent = false;
    double extent[4] = {0.0, 0.0, 0.0, 0.0};  // xmin,ymin,xmax,ymax
    std::string crs;             // "" → session project CRS
    pwb::domain::Json mirror_layers;  // legend honesty-gate description
};

struct MapBodyRequest {
    bool has_extent = false;
    double extent[4] = {0.0, 0.0, 0.0, 0.0};
    std::string crs;             // "" → session project CRS
    double dpi = 96.0;
    std::string format = "png";  // png|svg|pdf
    double width_mm = 200.0;     // map body page size (virtual page = body)
    double height_mm = 150.0;
    bool transparent = false;    // transparent page fill (PNG/SVG)
    bool force_vector = false;
};

class CompositionLayoutService {
public:
    explicit CompositionLayoutService(MapSession& session);

    // Composition → spec dry-run; no files touched. JSON report:
    // {ok, page_mm, items, warnings, hybrid_items, unmapped_elements,
    //  spec, failure}.
    pwb::domain::Json validate_layout(const std::string& composition_json,
                                      const CompositionExportRequest& request);

    // Full native chain. Returns the kernel LayoutExportReport::to_dict
    // shape (engine/path/format/dpi/ok/warnings/unmapped_elements/items/
    // hybrid_items + failure diagnostics, dimensions, filter_layers).
    pwb::domain::Json export_layout(const std::string& composition_json,
                                    const std::filesystem::path& output_path,
                                    const CompositionExportRequest& request);

    // Screen preview: the full chain at screen DPI into
    // preview_dir/pwb_preview.png (request format/dpi overridden).
    pwb::domain::Json preview(const std::string& composition_json,
                              const std::filesystem::path& preview_dir,
                              const CompositionExportRequest& request);

    // Map-body-only export: canvas-equivalent page — a single map item
    // without furniture (frame off, optional transparent background).
    pwb::domain::Json export_map_body(const std::filesystem::path& output_path,
                                      const MapBodyRequest& request);

    // Screen/export parity: canvas_state_json (MapSession::canvas_state_json
    // shape or equivalent) vs the export state derived from this session
    // and the request. Kernel ParityReport::to_dict shape + export_state.
    pwb::domain::Json parity_report(const std::string& canvas_state_json,
                                    const std::string& composition_json,
                                    const CompositionExportRequest& request);

private:
    pwb::layout_spec_exec::ExecContext exec_context() const;
    pwb::domain::Json build_export_state(
        const CompositionExportRequest& request,
        const pwb::domain::Json* spec) const;

    MapSession& session_;
};

}  // namespace pwb::qgis
