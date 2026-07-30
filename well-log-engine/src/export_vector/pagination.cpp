#include <welllog/export/pagination.hpp>

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <limits>
#include <string>

#include "export_vector/svg_internal.hpp"

namespace welllog {
namespace {

using svg_internal::append_color;
using svg_internal::append_defs;
using svg_internal::append_integer;
using svg_internal::append_layer_body;
using svg_internal::append_number;
using svg_internal::append_xml_attribute;

// 1 inch = 25.4 mm (ADR 0039 unit conversion; never uses screen DPI).
constexpr double millimetres_per_inch = 25.4;

[[nodiscard]] Error
pagination_error(ErrorCode code, MessageKey message) noexcept {
  return Error{
      .code = code,
      .severity = Severity::error,
      .entity_id = std::nullopt,
      .message = message,
      .arguments = {},
  };
}

[[nodiscard]] bool snapshot_is_valid(const PreparedScene &scene,
                                     const ExportSnapshot &snapshot) noexcept {
  if (scene.document_id().is_nil() || scene.document_revision().value == 0 ||
      !std::isfinite(scene.physical_width().value) ||
      scene.physical_width().value <= 0.0 ||
      !std::isfinite(scene.physical_height().value) ||
      scene.physical_height().value <= 0.0 || scene.tracks().empty()) {
    return false;
  }
  const auto &page = snapshot.page;
  if (!std::isfinite(page.page_width.value) || page.page_width.value <= 0.0 ||
      !std::isfinite(page.page_height.value) || page.page_height.value <= 0.0) {
    return false;
  }
  const auto finite_margin = [](Millimetres m) {
    return std::isfinite(m.value) && m.value >= 0.0;
  };
  if (!finite_margin(page.margins.top) || !finite_margin(page.margins.right) ||
      !finite_margin(page.margins.bottom) ||
      !finite_margin(page.margins.left)) {
    return false;
  }
  // The printable area must be strictly positive.
  if (page.margins.left.value + page.margins.right.value >=
          page.page_width.value ||
      page.margins.top.value + page.margins.bottom.value >=
          page.page_height.value) {
    return false;
  }
  if (page.dpi == 0 ||
      !std::isfinite(page.page_overlap) || page.page_overlap < 0.0 ||
      page.page_overlap >= 1.0) {
    return false;
  }
  return true;
}

[[nodiscard]] double
printable_depth_height_mm(const PreparedScene &scene,
                          const ExportPageSpec &page) noexcept {
  // The scene maps onto the page width: scale the scene so its physical width
  // matches the printable width, then the printable depth height is the page's
  // printable height. (Continuous mode derives its own height separately.)
  const auto printable_width =
      page.page_width.value - page.margins.left.value - page.margins.right.value;
  const auto scale = printable_width / scene.physical_width().value;
  const auto printable_page_height = page.page_height.value -
                                     page.margins.top.value -
                                     page.margins.bottom.value;
  return printable_page_height / scale;
}

// Formats a depth value with the engine's deterministic shortest-round-trip
// representation (matches the rest of the SVG emitters).
void append_depth(std::string &output, double depth) noexcept {
  append_number(output, depth);
}

// Computes the reference depth at a scene-y position, using the scene's linear
// depth transform (depth_top + (y / physical_height) * (bottom - top)).
[[nodiscard]] double scene_y_to_depth(const PreparedScene &scene,
                                      double y_mm) noexcept {
  const auto range = scene.reference_depth_range();
  const auto span = range.bottom - range.top;
  return range.top + (y_mm / scene.physical_height().value) * span;
}

// Appends one plain <text> element tagged with a data-export-role, used for the
// synthesized page header/footer/legend strings (well name, page number, depth
// range, curve legend) — plain ASCII SVG text, not the scene's glyph runs.
void append_text_element(std::string &output, std::string_view role,
                         double x_mm, double y_mm, std::string_view body,
                         double font_size_mm = 3.0) {
  output += "<text data-export-role=\"";
  output += role;
  output += "\" x=\"";
  append_number(output, x_mm);
  output += "\" y=\"";
  append_number(output, y_mm);
  output += "\" font-size=\"";
  append_number(output, font_size_mm);
  output += "\">";
  append_xml_attribute(output, body);
  output += "</text>";
}

// Appends the self-describing snapshot metadata as data-* attributes on the
// page root <svg>, so every page records the document revision, presentation
// version, font fingerprint and depth-transform version the export was produced
// against (criterion 1 "self-describing"; table-and-export.md section 9
// "Revision 元数据"). Mirrors the single-scene exporter's document/font tags.
void append_snapshot_metadata(std::string &output,
                              const ExportSnapshot &snapshot) noexcept {
  output += "\" data-document-id=\"";
  append_xml_attribute(output, snapshot.document_id.to_string());
  output += "\" data-document-revision=\"";
  append_integer(output, snapshot.document_revision.value);
  output += "\" data-presentation-version=\"";
  append_integer(output, snapshot.presentation_version.value);
  output += "\" data-depth-transform-version=\"";
  append_integer(output, snapshot.depth_transform.version);
  output += "\" data-font-asset=\"";
  append_xml_attribute(output, snapshot.font_asset_fingerprint);
  output += "\">";
}

// Emits one fixed page: page-sized <svg>, header/footer/legend bands, and the
// scene body clipped to this page's depth window and translated into place.
void append_fixed_page(std::string &output, const PreparedScene &scene,
                       const ExportSnapshot &snapshot, std::uint32_t page_index,
                       std::uint32_t page_count, double window_top_mm,
                       double window_bottom_mm) noexcept {
  const auto &page = snapshot.page;
  output += "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"";
  append_number(output, page.page_width.value);
  output += "mm\" height=\"";
  append_number(output, page.page_height.value);
  output += "mm\" viewBox=\"0 0 ";
  append_number(output, page.page_width.value);
  output.push_back(' ');
  append_number(output, page.page_height.value);
  output += "\" data-export-page=\"";
  append_integer(output, page_index + 1);
  output += "\" data-export-page-count=\"";
  append_integer(output, page_count);
  append_snapshot_metadata(output, snapshot);

  // Patterns/glyph defs are emitted once per page (each page is a standalone
  // SVG document). Track clipPaths/patterns/glyphs live in the shared helper.
  append_defs(output, scene);

  // Page header band: well name + page number (synthesized plain text, distinct
  // from the per-track curve headers emitted in the body below).
  const auto content_left = page.margins.left.value;
  const auto content_top = page.margins.top.value;
  const auto printable_page_height = page.page_height.value -
                                     page.margins.top.value -
                                     page.margins.bottom.value;
  if (page.repeat_headers) {
    if (!page.well_name.empty()) {
      append_text_element(output, "header", content_left,
                          content_top + 3.0, page.well_name);
    }
    if (page.show_page_numbers) {
      std::string page_label = "page ";
      append_integer(page_label, page_index + 1);
      page_label += " of ";
      append_integer(page_label, page_count);
      const auto page_label_x =
          page.page_width.value - page.margins.right.value;
      append_text_element(output, "header", page_label_x, content_top + 3.0,
                          page_label);
    }
  }

  // Per-page depth range (footer band). data-page-depth-top/-bottom carry the
  // depth window for cross-page continuity assertions (criterion 3/8).
  if (page.show_depth_range) {
    const auto depth_top = scene_y_to_depth(scene, window_top_mm);
    const auto depth_bottom = scene_y_to_depth(scene, window_bottom_mm);
    const auto footer_y =
        page.page_height.value - page.margins.bottom.value + 3.0;
    output += "<text data-export-role=\"footer\" x=\"";
    append_number(output, content_left);
    output += "\" y=\"";
    append_number(output, footer_y);
    output += "\" data-page-depth-top=\"";
    append_depth(output, depth_top);
    output += "\" data-page-depth-bottom=\"";
    append_depth(output, depth_bottom);
    output += "\" font-size=\"3\">depth ";
    append_depth(output, depth_top);
    output += " .. ";
    append_depth(output, depth_bottom);
    output += "</text>";
  }

  // Legend band: one line per visible curve layer (mnemonic + colour swatch +
  // scale range), from the prepared track-header entries. Repeated per page.
  if (page.repeat_legend) {
    const auto headers = scene.track_header_entries();
    double legend_y = content_top + printable_page_height - 3.0;
    for (const auto &entry : headers) {
      output += "<rect data-export-role=\"legend\" x=\"";
      append_number(output, content_left);
      output += "\" y=\"";
      append_number(output, legend_y - 2.0);
      output += "\" width=\"3\" height=\"2\" fill=\"";
      append_color(output, entry.color);
      output += "\"/>";
      std::string legend = entry.curve_name;
      legend += " ";
      append_number(legend, entry.scale_minimum);
      legend += "..";
      append_number(legend, entry.scale_maximum);
      legend += " ";
      legend += entry.unit;
      append_text_element(output, "legend", content_left + 4.0, legend_y,
                          legend);
      legend_y -= 4.0;
    }
  }

  // The scene body, mapped onto the printable area and clipped to this page's
  // depth window. The scene is scaled the same way as continuous mode
  // (scale = printable_width / scene_width) so it fills the printable width and
  // depth proportions stay true; a translate positions scene-y=window_top at the
  // page content top, so only [window_top, window_bottom] of the scaled scene
  // shows on this page. The clipPath is in PAGE millimetres (the printable
  // rect) so it clips the scaled body to the content area; the scene's own track
  // clips are preserved inside append_layer_body.
  const auto printable_width =
      page.page_width.value - page.margins.left.value - page.margins.right.value;
  const auto scale = printable_width / scene.physical_width().value;
  output += "<clipPath id=\"page-window-";
  append_integer(output, page_index);
  output += "\"><rect x=\"";
  append_number(output, content_left);
  output += "\" y=\"";
  append_number(output, content_top);
  output += "\" width=\"";
  append_number(output, printable_width);
  output += "\" height=\"";
  append_number(output, printable_page_height);
  output += "\"/></clipPath>";
  output += "<g clip-path=\"url(#page-window-";
  append_integer(output, page_index);
  output += ")\" transform=\"translate(";
  append_number(output, content_left);
  output.push_back(' ');
  // Scene point (x, window_top) must land at content_top: after scale, y is
  // window_top*scale, so translate by content_top - window_top*scale.
  append_number(output, content_top - window_top_mm * scale);
  output += ") scale(";
  append_number(output, scale);
  output.push_back(' ');
  append_number(output, scale);
  output += ")\" data-export-role=\"body\">";
  append_layer_body(output, scene);
  output += "</g>";

  output += "</svg>";
}

} // namespace

std::uint32_t PaginatedSvgExporter::required_aggregate_pixel_height(
    const PreparedScene &scene, const ExportPageSpec &page) noexcept {
  if (scene.physical_height().value <= 0.0 ||
      !std::isfinite(scene.physical_height().value) || page.dpi == 0) {
    return 0;
  }
  const auto printable_depth_mm = printable_depth_height_mm(scene, page);
  // Pixels per millimetre at the export DPI.
  const auto pixels_per_mm =
      static_cast<double>(page.dpi) / millimetres_per_inch;
  // Per-page depth pixels; the aggregate over the whole scene depth is the
  // sum across pages (uniform density assumption, ADR 0048).
  const auto page_depth_px = printable_depth_mm * pixels_per_mm;
  const auto effective_step = printable_depth_mm * (1.0 - page.page_overlap);
  if (effective_step <= 0.0) {
    return 0;
  }
  const auto page_count_d = std::ceil(scene.physical_height().value /
                                      effective_step);
  const auto page_count =
      page_count_d < 1.0 ? 1.0 : page_count_d;
  const auto aggregate =
      static_cast<double>(page_count) * page_depth_px;
  if (aggregate <= 0.0 || !std::isfinite(aggregate)) {
    return 0;
  }
  if (aggregate > static_cast<double>(std::numeric_limits<std::uint32_t>::max())) {
    return std::numeric_limits<std::uint32_t>::max();
  }
  return static_cast<std::uint32_t>(aggregate);
}

Result<SvgDocument>
PaginatedSvgExporter::write(const PreparedScene &scene,
                            const ExportSnapshot &snapshot) noexcept {
  try {
    if (!snapshot_is_valid(scene, snapshot)) {
      return pagination_error(ErrorCode::invalid_presentation,
                              MessageKey::presentation_invalid);
    }
    const auto &page = snapshot.page;

    std::string output;
    output.reserve(1024 + scene.curve_points().size() * 32);

    if (page.mode == PaginationMode::continuous) {
      // One continuous page: the printable width maps the scene width, and the
      // page height preserves true depth->physical-length (scene physical height
      // scaled by the same width factor), so depth proportions stay correct.
      const auto printable_width = page.page_width.value -
                                   page.margins.left.value -
                                   page.margins.right.value;
      const auto scale = printable_width / scene.physical_width().value;
      const auto page_height_mm =
          scene.physical_height().value * scale +
          page.margins.top.value + page.margins.bottom.value;

      output += "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"";
      append_number(output, page.page_width.value);
      output += "mm\" height=\"";
      append_number(output, page_height_mm);
      output += "mm\" viewBox=\"0 0 ";
      append_number(output, page.page_width.value);
      output.push_back(' ');
      append_number(output, page_height_mm);
      output += "\" data-export-page=\"1\" data-export-page-count=\"1\"";
      append_snapshot_metadata(output, snapshot);
      append_defs(output, scene);

      if (page.repeat_headers && !page.well_name.empty()) {
        append_text_element(output, "header", page.margins.left.value,
                            page.margins.top.value + 3.0, page.well_name);
      }
      if (page.show_depth_range) {
        const auto depth_top =
            scene_y_to_depth(scene, 0.0);
        const auto depth_bottom = scene_y_to_depth(
            scene, scene.physical_height().value);
        const auto footer_y = page_height_mm - page.margins.bottom.value + 3.0;
        output += "<text data-export-role=\"footer\" x=\"";
        append_number(output, page.margins.left.value);
        output += "\" y=\"";
        append_number(output, footer_y);
        output += "\" data-page-depth-top=\"";
        append_depth(output, depth_top);
        output += "\" data-page-depth-bottom=\"";
        append_depth(output, depth_bottom);
        output += "\" font-size=\"3\">depth ";
        append_depth(output, depth_top);
        output += " .. ";
        append_depth(output, depth_bottom);
        output += "</text>";
      }

      // Body translated to (margin-left, margin-top) and scaled to fit the
      // printable width; vertical scale keeps depth proportions true.
      output += "<g transform=\"translate(";
      append_number(output, page.margins.left.value);
      output.push_back(' ');
      append_number(output, page.margins.top.value);
      output += ") scale(";
      append_number(output, scale);
      output.push_back(' ');
      append_number(output, scale);
      output += ")\" data-export-role=\"body\">";
      append_layer_body(output, scene);
      output += "</g></svg>";
      return SvgDocument{std::move(output)};
    }

    // Fixed mode: slice the scene depth range into pages.
    const auto printable_depth_mm = printable_depth_height_mm(scene, page);
    const auto effective_step = printable_depth_mm * (1.0 - page.page_overlap);
    const auto scene_height = scene.physical_height().value;
    auto page_count =
        static_cast<std::uint32_t>(std::ceil(scene_height / effective_step));
    if (page_count == 0) {
      page_count = 1;
    }
    for (std::uint32_t index = 0; index < page_count; ++index) {
      const auto window_top =
          static_cast<double>(index) * effective_step;
      auto window_bottom = window_top + printable_depth_mm;
      // The final page bottoms out at the scene height (no overshoot).
      if (window_bottom > scene_height || index + 1 == page_count) {
        window_bottom = scene_height;
      }
      append_fixed_page(output, scene, snapshot, index, page_count, window_top,
                        window_bottom);
    }
    return SvgDocument{std::move(output)};
  } catch (const std::bad_alloc &) {
    return pagination_error(ErrorCode::resource_exhausted,
                            MessageKey::resource_exhausted);
  } catch (...) {
    return pagination_error(ErrorCode::internal_error,
                            MessageKey::internal_error);
  }
}

} // namespace welllog
