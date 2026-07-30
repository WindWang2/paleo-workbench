#pragma once

// Physical-scale, paginated SVG export (#186, ADR 0048). Builds on the
// single-scene SvgExporter (src/export_vector/svg.cpp): an ExportSnapshot
// captures the self-describing metadata that makes an export reproducible
// (table-and-export.md section 8.1), and PaginatedSvgExporter slices one
// prepared scene into either a single continuous long page or fixed pages with
// repeating header / legend / page-number / depth-range bands — all in physical
// millimetres, never window pixels (ADR 0039).
//
// Per-page curve envelopes: the input scene is prepared ONCE at aggregate page
// density by the host (see required_aggregate_pixel_height); each page then
// clips that scene to its depth window. The geometry is positionally stable
// across pages (the depth->y transform is a single global linear map, and
// prepare already clamps layer rects to the scene's depth range), so cross-page
// splits fall out of the per-page clip window. Per-page LOCAL-density curve
// re-query (for non-uniform sampling) is a documented refinement/deferral.

#include <cstdint>
#include <span>
#include <string>
#include <string_view>

#include <welllog/core/result.hpp>
#include <welllog/core/units.hpp>
#include <welllog/export/export.hpp>
#include <welllog/export/svg.hpp>
#include <welllog/scene/scene.hpp>

namespace welllog {

// The two pagination modes (table-and-export.md section 9).
enum class PaginationMode : std::uint8_t {
  // One continuous long page whose height preserves true depth->physical-length.
  continuous,
  // Fixed pages that auto-paginate the depth range, repeating header/legend/
  // page-number/depth-range on every page.
  fixed,
};

// Printable-area margins in physical millimetres (ADR 0039).
struct ExportPageMargins {
  Millimetres top{10.0};
  Millimetres right{10.0};
  Millimetres bottom{10.0};
  Millimetres left{10.0};
};

// Physical page geometry + pagination options. All sizes are millimetres and
// drive the layout; `dpi` is the export rasterization density used to compute
// the aggregate curve-envelope pixel height (criterion 4) and later raster
// backends — it never enters the page-millimetre math (ADR 0039).
struct ExportPageSpec {
  PaginationMode mode{PaginationMode::continuous};
  Millimetres page_width{210.0};  // ISO A4 portrait default.
  Millimetres page_height{297.0}; // Fixed mode; ignored (derived) in continuous.
  ExportPageMargins margins{};
  std::uint32_t dpi{300};
  // Depth overlap between consecutive fixed pages, as a fraction of the
  // printable depth height in [0, 1) (section 9 "page overlap"). 0 = butt.
  double page_overlap{0.0};
  std::string well_name;
  bool repeat_headers{true};
  bool repeat_legend{true};
  bool show_page_numbers{true};
  bool show_depth_range{true};
};

// The immutable, self-describing metadata an export captures so it is
// reproducible (criterion 1 / table-and-export.md section 8.1). A snapshot
// records the document revision, presentation version, the depth transform it
// was produced against (a version-tagged descriptor, not the full ADR-0013
// chain), the font asset fingerprint, the pattern versions, and the page spec.
struct ExportSnapshot {
  EntityId document_id{};
  DocumentRevision document_revision{};
  PresentationVersion presentation_version{};
  DepthTransformDescriptor depth_transform{};
  std::string font_asset_fingerprint;
  // Pattern versions, parallel to the prepared scene's patterns() order. Empty
  // when the scene has no patterns.
  std::span<const std::uint64_t> pattern_versions{};
  ExportPageSpec page{};
};

// Assembles paginated, physical-scale SVG from one prepared scene + snapshot.
// The existing single-scene SvgExporter::write is preserved unchanged; this is
// an additive exporter that reuses the same per-layer emission (ADR 0048).
class WELLLOG_EXPORT_VECTOR_API PaginatedSvgExporter {
public:
  // Continuous mode emits exactly one <svg>; fixed mode emits one <svg> per
  // page, concatenated. Returns a Result so invalid scenes/snapshots surface as
  // ErrorCode::invalid_presentation like SvgExporter::write.
  [[nodiscard]] static Result<SvgDocument>
  write(const PreparedScene &scene, const ExportSnapshot &snapshot) noexcept;

  // The aggregate curve-envelope pixel height the host should prepare the scene
  // at so every fixed page resolves to the correct per-page density. Equals the
  // printable depth height converted to export-DPI pixels, summed over pages.
  // Use this to build the CurveLodQuery before preparing the scene to export.
  [[nodiscard]] static std::uint32_t
  required_aggregate_pixel_height(const PreparedScene &scene,
                                  const ExportPageSpec &page) noexcept;
};

} // namespace welllog
