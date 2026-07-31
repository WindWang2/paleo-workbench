// PDF scene emission (#187 vector primitives + text-as-outlines; #188 raster
// images, tiling patterns, pagination, custom layer). Serializes a
// PreparedScene + ExportSnapshot to one or more PDF pages via the #185 writer.
// The geometry emission mirrors src/export_vector/svg.cpp's append_layer_body /
// append_pattern_definition 1:1 — same per-track structure, same per-layer order
// (intervals, markers, symbols, curves, crossover fills, images, custom,
// text), same scene-millimetre coordinates — but emits PDF path operators
// (`m/l/c/h/re/f/S`) instead of SVG elements.
//
// One `cm` (concat-matrix) operator per page maps the scaled scene (mm) into
// PDF user-space points, so the per-layer code operates in millimetres exactly
// like the SVG emitter. Track clipping uses `re ... W n` per track (mirroring
// SVG's clipPath); each fixed page adds a depth-window clip (mirroring
// pagination.cpp's page-window clipPath). Text is rendered as glyph vector
// outlines under a per-glyph `cm` (translate/rotate/scale), no font embedded
// (ADR 0047). Raster images embed as image XObjects (pixels fetched via the
// host image_tile resolver — the engine never decodes), and PatternDefinition
// maps to PDF tiling patterns, phase-consistent with the SVG backend.
//
// Determinism is by construction (no CreationDate/ModDate/ID); identical input
// always yields byte-identical output.

#include <welllog/export/pdf_scene.hpp>

#include <welllog/core/document.hpp>
#include <welllog/core/entity_id.hpp>
#include <welllog/io/manifest.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <functional>
#include <optional>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace welllog {
namespace {

// 1 inch = 25.4 mm (ADR 0039 unit conversion; never uses screen DPI).
constexpr double millimetres_per_inch = 25.4;
// 1 mm = 72/25.4 PDF user-space points.
constexpr double points_per_millimetre = 72.0 / millimetres_per_inch;
// Cubic-Bezier circle-approximation kappa (4 segments → a near-perfect circle).
constexpr double circle_kappa = 0.5522847498307936;

[[nodiscard]] Error
pdf_scene_error(ErrorCode code, MessageKey message) noexcept {
  return Error{
      .code = code,
      .severity = Severity::error,
      .entity_id = std::nullopt,
      .message = message,
      .arguments = {},
  };
}

// Mirrors pagination.cpp::snapshot_is_valid: rejects empty/invalid scenes and
// pages whose printable area is not strictly positive. Kept local (not shared)
// because the PDF exporter links the PDF library, not the SVG/vector library.
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

[[nodiscard]] double printable_width(const ExportPageSpec &page) noexcept {
  return page.page_width.value - page.margins.left.value -
         page.margins.right.value;
}
[[nodiscard]] double printable_height(const ExportPageSpec &page) noexcept {
  return page.page_height.value - page.margins.top.value -
         page.margins.bottom.value;
}

// The printable depth height in scene millimetres, mirroring pagination.cpp.
[[nodiscard]] double
printable_depth_height_mm(const PreparedScene &scene,
                          const ExportPageSpec &page) noexcept {
  const auto scale = printable_width(page) / scene.physical_width().value;
  return printable_height(page) / scale;
}

// Emits a circle as four cubic Bezier segments approximating a full circle of
// the given radius centred at (cx, cy). Mirrors the SVG emitter's two-arc
// circle but in PDF's cubic-only vocabulary. Built as OutlineCommands with
// cubic_to (so no quadratic→cubic lift occurs) and appended in one call.
void emit_circle_path(PdfPathStream &stream, double cx, double cy,
                      double radius) noexcept {
  const auto k = radius * circle_kappa;
  // Start at (cx+r, cy) and walk the four quadrant control points clockwise
  // (scene y-down). Each quadrant contributes one cubic `c`; a close makes the
  // fill a clean loop.
  const std::array<OutlineCommand, 5> commands{{
      // (cx+r,cy) → (cx,cy+r): control points (cx+r, cy+k), (cx+k, cy+r).
      {OutlineVerb::cubic_to, {cx + radius, cy + k, cx + k, cy + radius,
                               cx, cy + radius}},
      // (cx,cy+r) → (cx-r,cy): (cx-k, cy+r), (cx-r, cy+k).
      {OutlineVerb::cubic_to, {cx - k, cy + radius, cx - radius, cy + k,
                               cx - radius, cy}},
      // (cx-r,cy) → (cx,cy-r): (cx-r, cy-k), (cx-k, cy-r).
      {OutlineVerb::cubic_to, {cx - radius, cy - k, cx - k, cy - radius,
                               cx, cy - radius}},
      // (cx,cy-r) → (cx+r,cy): (cx+k, cy-r), (cx+r, cy-k).
      {OutlineVerb::cubic_to, {cx + k, cy - radius, cx + radius, cy - k,
                               cx + radius, cy}},
      {OutlineVerb::close, {}},
  }};
  stream.move_to(cx + radius, cy);
  stream.append_outline(commands);
}

// Clips a tile-local segment to the pattern tile rect (Liang-Barsky). Carried
// over verbatim from svg.cpp::clip_line_to_tile — tile-local clipping is pure
// geometry, backend-neutral, so SVG and PDF share the exact same result.
[[nodiscard]] std::optional<std::pair<PhysicalPoint, PhysicalPoint>>
clip_line_to_tile(PhysicalPoint from, PhysicalPoint to, double width,
                  double height) noexcept {
  const auto delta_x = to.left.value - from.left.value;
  const auto delta_y = to.top.value - from.top.value;
  double enter = 0.0;
  double leave = 1.0;
  const auto clip_side = [&](double p, double q) {
    if (p == 0.0) {
      return q >= 0.0;
    }
    const auto ratio = q / p;
    if (p < 0.0) {
      if (ratio > leave) {
        return false;
      }
      enter = std::max(enter, ratio);
    } else {
      if (ratio < enter) {
        return false;
      }
      leave = std::min(leave, ratio);
    }
    return true;
  };
  if (!clip_side(-delta_x, from.left.value) ||
      !clip_side(delta_x, width - from.left.value) ||
      !clip_side(-delta_y, from.top.value) ||
      !clip_side(delta_y, height - from.top.value)) {
    return std::nullopt;
  }
  return std::pair{
      PhysicalPoint{.left = Millimetres{from.left.value + enter * delta_x},
                    .top = Millimetres{from.top.value + enter * delta_y}},
      PhysicalPoint{.left = Millimetres{from.left.value + leave * delta_x},
                    .top = Millimetres{from.top.value + leave * delta_y}},
  };
}

// A per-page registry of the indirect objects (image XObjects + tiling
// patterns) the page's content stream references. Patterns are keyed by their
// PatternDefinition id so the same pattern referenced by many intervals shares
// one object; images are keyed by (image_source_id, level, row, col). Names are
// assigned in first-encountered order (P0, P1, … / Im0, Im1, …) which is
// deterministic given deterministic scene traversal.
struct PageResources {
  // id → (local_name, pattern definition index in scene.patterns()).
  std::unordered_map<EntityId, std::string, EntityIdHash> pattern_names;
  std::vector<EntityId> pattern_order; // first-encountered order
  // tile-key → local_name.
  struct ImageKey {
    EntityId source_id;
    std::uint32_t level;
    std::uint32_t row;
    std::uint32_t col;
    bool operator==(const ImageKey &) const = default;
  };
  struct ImageKeyHash {
    std::size_t operator()(const ImageKey &k) const noexcept {
      const EntityIdHash id_hash;
      return id_hash(k.source_id) ^
             (static_cast<std::size_t>(k.level) << 5) ^
             (static_cast<std::size_t>(k.row) << 11) ^
             (static_cast<std::size_t>(k.col) << 17);
    }
  };
  std::unordered_map<ImageKey, std::string, ImageKeyHash> image_names;
  std::vector<ImageKey> image_order;
  // Resolved pixel data for each image, keyed by local name. SharedOwner keeps
  // the decoded bytes alive until the PDF is assembled.
  struct ImageRecord {
    std::uint32_t width_px{};
    std::uint32_t height_px{};
    PixelFormat pixel_format{PixelFormat::rgba8};
    const std::uint8_t *data{nullptr};
    SharedOwner owner;
  };
  std::unordered_map<std::string, ImageRecord> image_records;

  // Resolves (or creates) the local name for a pattern id, returning "P<n>".
  std::string name_for_pattern(EntityId pattern_id) {
    const auto it = pattern_names.find(pattern_id);
    if (it != pattern_names.end()) {
      return it->second;
    }
    std::string name = "P";
    name += std::to_string(pattern_order.size());
    pattern_names.emplace(pattern_id, name);
    pattern_order.push_back(pattern_id);
    return name;
  }
  // Resolves (or creates) the local name for an image tile, returning "Im<n>".
  std::string name_for_image(EntityId source_id, std::uint32_t level,
                             std::uint32_t row, std::uint32_t col) {
    const ImageKey key{source_id, level, row, col};
    const auto it = image_names.find(key);
    if (it != image_names.end()) {
      return it->second;
    }
    std::string name = "Im";
    name += std::to_string(image_order.size());
    image_names.emplace(key, name);
    image_order.push_back(key);
    return name;
  }
  // Records the resolved pixels for a named tile (idempotent on the name).
  void record_image(const std::string &name, const RasterTile &raster) {
    if (image_records.find(name) != image_records.end()) {
      return;
    }
    image_records.emplace(
        name, ImageRecord{.width_px = raster.width_px,
                          .height_px = raster.height_px,
                          .pixel_format = raster.pixel_format,
                          .data = raster.data,
                          .owner = raster.owner});
  }
};

// Appends a tile-local line to a pattern's content stream, clipped to the tile
// rect (Liang-Barsky) and stroked with the pattern foreground — the PDF
// equivalent of svg.cpp::append_tile_line.
void append_tile_line(PdfPathStream &stream, PhysicalPoint from,
                      PhysicalPoint to,
                      const PatternDefinition &pattern) noexcept {
  const auto clipped = clip_line_to_tile(from, to, pattern.tile_width.value,
                                         pattern.tile_height.value);
  if (!clipped.has_value()) {
    return;
  }
  stream.set_stroke_color(pattern.foreground.red, pattern.foreground.green,
                          pattern.foreground.blue);
  if (pattern.foreground.alpha < 255) {
    stream.set_fill_alpha(static_cast<double>(pattern.foreground.alpha) / 255.0);
  }
  stream.set_line_width(pattern.stroke_width.value);
  stream.move_to(clipped->first.left.value, clipped->first.top.value)
      .line_to(clipped->second.left.value, clipped->second.top.value)
      .stroke();
}

// Builds the content-stream body of one tiling pattern, mirroring svg.cpp's
// append_pattern_definition: the tile background rect (if opaque) + each
// primitive (lines/polylines clipped to the tile, circles). The pattern is
// authored in tile-local millimetres; the Pattern /Matrix carries the
// scene_anchor + rotation so adjacent tiles share phase (ADR 0020), exactly
// like SVG's patternUnits="userSpaceOnUse" x/y + patternTransform.
void emit_pattern_tile_body(PdfPathStream &stream,
                            const PatternDefinition &pattern) noexcept {
  if (pattern.background.alpha > 0) {
    stream.set_fill_color(pattern.background.red, pattern.background.green,
                          pattern.background.blue);
    if (pattern.background.alpha < 255) {
      stream.set_fill_alpha(
          static_cast<double>(pattern.background.alpha) / 255.0);
    }
    stream.rect(0.0, 0.0, pattern.tile_width.value, pattern.tile_height.value)
        .fill();
  }
  for (const auto &primitive : pattern.primitives) {
    if (const auto *line = std::get_if<PatternLine>(&primitive)) {
      append_tile_line(stream, line->from, line->to, pattern);
    } else if (const auto *polyline =
                   std::get_if<PatternPolyline>(&primitive)) {
      for (std::size_t index = 0; index + 1 < polyline->points.size(); ++index) {
        append_tile_line(stream, polyline->points[index],
                         polyline->points[index + 1], pattern);
      }
      if (polyline->closed && polyline->points.size() > 2) {
        append_tile_line(stream, polyline->points.back(),
                         polyline->points.front(), pattern);
      }
    } else {
      const auto &circle = std::get<PatternCircle>(primitive);
      stream.set_fill_color(pattern.foreground.red, pattern.foreground.green,
                            pattern.foreground.blue);
      if (circle.filled) {
        if (pattern.foreground.alpha < 255) {
          stream.set_fill_alpha(
              static_cast<double>(pattern.foreground.alpha) / 255.0);
        }
        emit_circle_path(stream, circle.center.left.value,
                         circle.center.top.value, circle.radius.value);
        stream.fill();
      } else {
        stream.set_stroke_color(pattern.foreground.red,
                                pattern.foreground.green, pattern.foreground.blue);
        if (pattern.foreground.alpha < 255) {
          stream.set_fill_alpha(
              static_cast<double>(pattern.foreground.alpha) / 255.0);
        }
        stream.set_line_width(pattern.stroke_width.value);
        emit_circle_path(stream, circle.center.left.value,
                         circle.center.top.value, circle.radius.value);
        stream.stroke();
      }
    }
  }
}

// Builds the full object body for a tiling pattern: dictionary + compressed
// content stream. The /Matrix composes translate(scene_anchor) · rotate(θ):
// scene_anchor pins the tile phase to scene coordinates (matching SVG's x/y),
// rotation_degrees matches SVG's patternTransform rotate. Returns the body the
// writer wraps in "N 0 obj\n…\nendobj".
// Returns nullopt on a Flate failure so the caller can surface an error
// rather than emit a malformed (dict-less) object body. NOT noexcept: it
// allocates (string building, Flate), so a bad_alloc must propagate to
// write()'s catch (→ resource_exhausted) rather than terminate.
std::optional<std::string>
build_pattern_body(const PatternDefinition &pattern) {
  PdfPathStream tile;
  emit_pattern_tile_body(tile, pattern);
  const auto ops = std::string(tile.operators());
  std::string compressed;
  if (!flate_compress_buffer(ops, compressed)) {
    return std::nullopt;
  }
  std::string body;
  body += "<< /Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1 ";
  body += "/BBox [0 0 ";
  body += std::to_string(pattern.tile_width.value);
  body += " ";
  body += std::to_string(pattern.tile_height.value);
  body += "] /XStep ";
  body += std::to_string(pattern.tile_width.value);
  body += " /YStep ";
  body += std::to_string(pattern.tile_height.value);
  // Pattern matrix: translate(scene_anchor) · rotate(θ), in millimetres (the
  // pattern cell is in mm; the page cm maps mm→points). SVG applies the same
  // translate (x/y) + rotate (patternTransform).
  const auto theta = pattern.rotation_degrees * (M_PI / 180.0);
  const auto cos_t = std::cos(theta);
  const auto sin_t = std::sin(theta);
  body += " /Matrix [";
  body += std::to_string(cos_t);
  body += " ";
  body += std::to_string(sin_t);
  body += " ";
  body += std::to_string(-sin_t);
  body += " ";
  body += std::to_string(cos_t);
  body += " ";
  body += std::to_string(pattern.scene_anchor.left.value);
  body += " ";
  body += std::to_string(pattern.scene_anchor.top.value);
  body += "] /Resources << >> /Length ";
  body += std::to_string(compressed.size());
  body += " /Filter /FlateDecode >>\nstream\n";
  body.append(compressed.data(), compressed.size());
  body += "\nendstream";
  return body;
}

// Builds the full object body for an image XObject: dictionary + the pixel
// stream (Flate-compressed). Colourspace maps PixelFormat → DeviceRGB/DeviceGray
// (#188 drops the RGBA alpha channel — a separate /SMask soft-mask is a later
// refinement). DPI is encoded by the placement `cm` (physical rect vs pixel
// count), not in the object — consistent with SVG's width/height. Returns
// nullopt on a Flate failure so the caller surfaces an error. NOT noexcept: it
// allocates (string + Flate), so bad_alloc propagates to write()'s catch.
std::optional<std::string>
build_image_body(const PageResources::ImageRecord &rec) {
  const std::uint32_t channels = rec.pixel_format == PixelFormat::rgba8 ? 3
                              : rec.pixel_format == PixelFormat::rgb8 ? 3 : 1;
  // Re-pack RGBA → RGB if needed (drop alpha).
  std::string pixels;
  const auto pixels_in =
      static_cast<std::uint64_t>(rec.width_px) *
      static_cast<std::uint64_t>(rec.height_px);
  const std::uint32_t in_channels =
      rec.pixel_format == PixelFormat::rgba8 ? 4
      : rec.pixel_format == PixelFormat::rgb8 ? 3 : 1;
  pixels.reserve(pixels_in * channels);
  for (std::uint64_t i = 0; i < pixels_in; ++i) {
    const auto base = i * in_channels;
    for (std::uint32_t c = 0; c < channels; ++c) {
      pixels.push_back(static_cast<char>(rec.data[base + c]));
    }
  }
  std::string compressed;
  if (!flate_compress_buffer(pixels, compressed)) {
    return std::nullopt;
  }
  std::string body;
  body += "<< /Type /XObject /Subtype /Image /Width ";
  body += std::to_string(rec.width_px);
  body += " /Height ";
  body += std::to_string(rec.height_px);
  body += " /ColorSpace /";
  body += channels == 1 ? "DeviceGray" : "DeviceRGB";
  body += " /BitsPerComponent 8 /Length ";
  body += std::to_string(compressed.size());
  body += " /Filter /FlateDecode >>\nstream\n";
  body.append(compressed.data(), compressed.size());
  body += "\nendstream";
  return body;
}

// Emits one prepared symbol as PDF path operators, mirroring svg.cpp's
// append_symbol geometry (circle/diamond/square/triangle/cross).
void emit_symbol(PdfPathStream &stream, const PreparedSymbol &symbol,
                 const PreparedSymbolLayer &layer) noexcept {
  const auto half = layer.symbol_size.value / 2.0;
  const auto cx = symbol.center.left.value;
  const auto cy = symbol.center.top.value;
  stream.set_fill_color(layer.color.red, layer.color.green, layer.color.blue);
  stream.set_stroke_color(layer.color.red, layer.color.green, layer.color.blue);
  if (layer.color.alpha < 255) {
    stream.set_fill_alpha(static_cast<double>(layer.color.alpha) / 255.0);
  }
  switch (symbol.kind) {
  case SymbolKind::circle: {
    emit_circle_path(stream, cx, cy, half);
    stream.fill();
    return;
  }
  case SymbolKind::cross: {
    // Two diagonal strokes, no fill (stroke-only).
    stream.set_line_width(layer.symbol_size.value / 6.0);
    stream.move_to(cx - half, cy - half)
        .line_to(cx + half, cy + half)
        .move_to(cx + half, cy - half)
        .line_to(cx - half, cy + half)
        .stroke();
    return;
  }
  case SymbolKind::square:
    stream.move_to(cx - half, cy - half)
        .line_to(cx + half, cy - half)
        .line_to(cx + half, cy + half)
        .line_to(cx - half, cy + half)
        .close()
        .fill();
    return;
  case SymbolKind::triangle_up:
    stream.move_to(cx, cy - half)
        .line_to(cx + half, cy + half)
        .line_to(cx - half, cy + half)
        .close()
        .fill();
    return;
  case SymbolKind::diamond:
    stream.move_to(cx, cy - half)
        .line_to(cx + half, cy)
        .line_to(cx, cy + half)
        .line_to(cx - half, cy)
        .close()
        .fill();
    return;
  }
}

// Emits one curve layer's polyline(s) as `m`/`l` segments + a single stroke,
// mirroring svg.cpp::append_path_data. The polyline may have multiple segments
// (log-scale gaps, nulls); each segment is a separate subpath so the gaps do
// not connect.
void emit_curve_layer(PdfPathStream &stream, const PreparedScene &scene,
                      const PreparedCurveLayer &layer) noexcept {
  if (!layer.visible || layer.segment_count == 0) {
    return;
  }
  stream.set_stroke_color(layer.color.red, layer.color.green, layer.color.blue);
  stream.set_line_width(layer.line_width.value);
  const auto segments = scene.curve_segments();
  const auto points = scene.curve_points();
  for (std::uint64_t offset = 0; offset < layer.segment_count; ++offset) {
    const auto &segment = segments[static_cast<std::size_t>(
        layer.first_segment + offset)];
    for (std::uint64_t point_offset = 0; point_offset < segment.point_count;
         ++point_offset) {
      const auto &point = points[static_cast<std::size_t>(
          segment.first_point + point_offset)];
      if (point_offset == 0) {
        stream.move_to(point.position.left.value, point.position.top.value);
      } else {
        stream.line_to(point.position.left.value, point.position.top.value);
      }
    }
  }
  stream.stroke();
}

// Walks a region's closed boundary ring into the stream (m/l), shared by the
// solid and patterned fill paths. The caller closes + paints.
void append_fill_ring(PdfPathStream &stream, const PreparedScene &scene,
                      const PreparedFillRegion &region) noexcept {
  const auto vertices = scene.fill_vertices();
  for (std::uint64_t offset = 0; offset < region.vertex_count; ++offset) {
    const auto &vertex = vertices[static_cast<std::size_t>(
        region.first_vertex + offset)];
    if (offset == 0) {
      stream.move_to(vertex.position.left.value, vertex.position.top.value);
    } else {
      stream.line_to(vertex.position.left.value, vertex.position.top.value);
    }
  }
}

// Emits the closed boundary ring of one crossover-fill region, mirroring
// svg.cpp's solid-vs-pattern decision: solid fill when pattern_id is nil, else
// a tiling-pattern fill (registering the pattern in `resources`).
void emit_fill_region(PdfPathStream &stream, const PreparedScene &scene,
                      const PreparedFillRegion &region,
                      PageResources &resources) noexcept {
  append_fill_ring(stream, scene, region);
  if (region.pattern_id.is_nil()) {
    stream.set_fill_color(region.fill_color.red, region.fill_color.green,
                          region.fill_color.blue);
    if (region.fill_color.alpha < 255) {
      stream.set_fill_alpha(
          static_cast<double>(region.fill_color.alpha) / 255.0);
    }
    stream.close().fill();
  } else {
    // Pattern fill: switch the non-stroking colour space to /Pattern and paint
    // with the tiling pattern. The page Resources names it.
    const auto name = resources.name_for_pattern(region.pattern_id);
    stream.close();
    stream.set_pattern_fill(name);
  }
}

// Emits one text run as glyph vector outlines: each glyph is drawn under a
// per-glyph `cm` that composes translate(origin)·rotate(rotation)·scale(fs,-fs)
// — the same transform the SVG `<use>` applies. The glyph's OutlineCommand
// stream (em fractions, y-up) is emitted verbatim; the negative-d scale flips
// it to scene y-down and sizes it in millimetres. No font program is embedded.
void emit_text_run(PdfPathStream &stream, const PreparedScene &scene,
                   const PreparedTextRun &run) noexcept {
  const auto glyphs = scene.glyphs();
  const auto outlines = scene.glyph_outlines();
  const auto outline_commands = scene.outline_commands();
  stream.save_state();
  stream.set_fill_color(run.color.red, run.color.green, run.color.blue);
  if (run.color.alpha < 255) {
    stream.set_fill_alpha(static_cast<double>(run.color.alpha) / 255.0);
  }
  const auto fs = run.font_size.value;
  for (std::uint64_t offset = 0; offset < run.glyph_count; ++offset) {
    const auto &glyph = glyphs[static_cast<std::size_t>(run.first_glyph +
                                                         offset)];
    // Locate this glyph's outline by matching font_index + glyph_id. The
    // outlines span is the single source of truth shared with the SVG backend.
    const PreparedGlyphOutline *outline = nullptr;
    for (const auto &candidate : outlines) {
      if (candidate.font_index == glyph.font_index &&
          candidate.glyph_id == glyph.glyph_id) {
        outline = &candidate;
        break;
      }
    }
    if (outline == nullptr || outline->command_count == 0) {
      continue;
    }
    // Per-GLYPH rotation, not per-run: in vertical typesetting rotated glyphs
    // carry their own 90° glyph rotation while upright ones carry 0°, so this
    // must read glyph.rotation_degrees (matching SVG's `rotate(glyph.rotation)`)
    // rather than run.rotation_degrees.
    const auto theta = glyph.rotation_degrees * (M_PI / 180.0);
    const auto cos_t = std::cos(theta);
    const auto sin_t = std::sin(theta);
    // M = translate(ox,oy) · rotate(θ) · scale(fs,-fs) as an affine [a b c d e f]
    // (derived in the header comment): a=cos·fs, b=sin·fs, c=sin·fs, d=-cos·fs.
    stream.save_state();
    stream.concat_matrix(cos_t * fs, sin_t * fs, sin_t * fs, -cos_t * fs,
                         glyph.origin.left.value, glyph.origin.top.value);
    stream.append_outline(outline_commands.subspan(
        static_cast<std::size_t>(outline->first_command),
        static_cast<std::size_t>(outline->command_count)));
    stream.fill();
    stream.restore_state();
  }
  stream.restore_state();
}

// Emits the custom-layer primitives of one track, mirroring svg.cpp's custom
// loop. Polylines → stroked path; triangles/quads → filled closed sub-paths
// (triangulated, vertex_count/3 triangles); symbols → filled shape. No
// per-backend clip: the geometry is pre-clipped to the source's clip ring at
// prepare time (the same data GL/SVG draw).
void emit_custom_layer(PdfPathStream &stream, const PreparedScene &scene,
                       const PreparedCustomLayer &layer) noexcept {
  if (!layer.visible) {
    return;
  }
  const auto custom_vertices = scene.custom_vertices();
  for (std::uint64_t offset = 0; offset < layer.primitive_count; ++offset) {
    const auto &primitive = scene.custom_primitives()[static_cast<std::size_t>(
        layer.first_primitive + offset)];
    if (primitive.kind == CustomPrimitiveKind::polyline) {
      stream.set_stroke_color(primitive.color.red, primitive.color.green,
                              primitive.color.blue);
      stream.set_line_width(primitive.stroke_width.value);
      for (std::uint64_t point_offset = 0;
           point_offset < primitive.vertex_count; ++point_offset) {
        const auto &point = custom_vertices[static_cast<std::size_t>(
            primitive.first_vertex + point_offset)];
        if (point_offset == 0) {
          stream.move_to(point.left.value, point.top.value);
        } else {
          stream.line_to(point.left.value, point.top.value);
        }
      }
      if (primitive.closed) {
        stream.close();
      }
      stream.stroke();
    } else if (primitive.kind == CustomPrimitiveKind::triangle ||
               primitive.kind == CustomPrimitiveKind::quad) {
      stream.set_fill_color(primitive.color.red, primitive.color.green,
                            primitive.color.blue);
      if (primitive.color.alpha < 255) {
        stream.set_fill_alpha(
            static_cast<double>(primitive.color.alpha) / 255.0);
      }
      const auto triangle_count = primitive.vertex_count / 3;
      for (std::uint64_t tri = 0; tri < triangle_count; ++tri) {
        for (std::uint64_t point_offset = 0; point_offset < 3; ++point_offset) {
          const auto &point = custom_vertices[static_cast<std::size_t>(
              primitive.first_vertex + tri * 3 + point_offset)];
          if (point_offset == 0) {
            stream.move_to(point.left.value, point.top.value);
          } else {
            stream.line_to(point.left.value, point.top.value);
          }
        }
        stream.close();
      }
      stream.fill();
    } else {
      // Symbol: emit the symbol's true geometry. SVG defers non-circle kinds to
      // a circle; PDF emits each SymbolKind correctly via emit_symbol (size from
      // the primitive bounds, color from the primitive).
      PreparedSymbol sym;
      PreparedSymbolLayer slyr;
      const auto &center = custom_vertices[static_cast<std::size_t>(
          primitive.first_vertex)];
      sym.center = center;
      sym.kind = primitive.symbol_kind;
      slyr.color = primitive.color;
      slyr.symbol_size = Millimetres{primitive.bounds.width.value};
      emit_symbol(stream, sym, slyr);
    }
  }
}

// Emits the per-track, per-layer body — the single geometric emitter for one
// track, mirroring svg.cpp::append_layer_body's per-track `<g>`. Called inside
// the track's saved clip state. `resources` collects the patterns/images the
// page will need to name in its Resources dict.
void emit_track_body(PdfPathStream &stream, const PreparedScene &scene,
                     const PreparedTrack &track, PageResources &resources,
                     const std::function<Result<RasterTile>(
                         const ImageTileRequest &)> &image_tile) noexcept {
  // Interval rects (solid or patterned fill — mirrors SVG's pattern_id branch).
  for (const auto &layer : scene.interval_layers()) {
    if (layer.track_id != track.id) {
      continue;
    }
    for (std::uint64_t offset = 0; offset < layer.interval_count; ++offset) {
      const auto &interval = scene.intervals()[static_cast<std::size_t>(
          layer.first_interval + offset)];
      stream.rect(interval.rect.left.value, interval.rect.top.value,
                  interval.rect.width.value, interval.rect.height.value);
      if (interval.pattern_id.is_nil()) {
        stream.set_fill_color(interval.fill_color.red,
                              interval.fill_color.green,
                              interval.fill_color.blue);
        if (interval.fill_color.alpha < 255) {
          stream.set_fill_alpha(
              static_cast<double>(interval.fill_color.alpha) / 255.0);
        }
        stream.fill();
      } else {
        stream.set_pattern_fill(resources.name_for_pattern(interval.pattern_id));
      }
    }
  }
  // Marker lines across the full track width.
  for (const auto &layer : scene.marker_layers()) {
    if (layer.track_id != track.id) {
      continue;
    }
    stream.set_stroke_color(layer.line_color.red, layer.line_color.green,
                            layer.line_color.blue);
    stream.set_line_width(layer.line_width.value);
    const auto left = track.clip.left.value;
    const auto right = track.clip.left.value + track.clip.width.value;
    for (std::uint64_t offset = 0; offset < layer.marker_count; ++offset) {
      const auto &marker = scene.markers()[static_cast<std::size_t>(
          layer.first_marker + offset)];
      stream.move_to(left, marker.display_top.value)
          .line_to(right, marker.display_top.value);
    }
    stream.stroke();
  }
  // Symbols.
  for (const auto &layer : scene.symbol_layers()) {
    if (layer.track_id != track.id) {
      continue;
    }
    for (std::uint64_t offset = 0; offset < layer.symbol_count; ++offset) {
      const auto &symbol = scene.symbols()[static_cast<std::size_t>(
          layer.first_symbol + offset)];
      emit_symbol(stream, symbol, layer);
    }
  }
  // Curve polylines.
  for (const auto &layer : scene.curve_layers()) {
    if (layer.track_id == track.id) {
      emit_curve_layer(stream, scene, layer);
    }
  }
  // Crossover fill regions.
  for (const auto &fill_layer : scene.fill_layers()) {
    if (fill_layer.track_id != track.id) {
      continue;
    }
    for (std::uint64_t offset = 0; offset < fill_layer.region_count; ++offset) {
      const auto &region = scene.fill_regions()[static_cast<std::size_t>(
          fill_layer.first_region + offset)];
      emit_fill_region(stream, scene, region, resources);
    }
  }
  // Image layer tiles: place each resolved tile as an image XObject. Pixels are
  // fetched via the host resolver (the engine never decodes); a missing
  // resolver or failed resolution skips the tile (best-effort, like the SVG
  // backend which only emits a placeholder href).
  if (image_tile) {
    for (const auto &image_layer : scene.image_layers()) {
      if (image_layer.track_id != track.id) {
        continue;
      }
      for (std::uint64_t offset = 0; offset < image_layer.tile_count; ++offset) {
        const auto &tile = scene.image_tiles()[static_cast<std::size_t>(
            image_layer.first_tile + offset)];
        const auto resolved = image_tile(ImageTileRequest{
            .image_source_id = tile.image_source_id,
            .level = tile.level,
            .row = tile.row,
            .col = tile.col,
        });
        if (!resolved.has_value()) {
          continue;
        }
        const auto &raster = resolved.value();
        if (raster.data == nullptr || raster.width_px == 0 ||
            raster.height_px == 0) {
          continue;
        }
        // Register the tile (dedup by source/level/row/col) and place it: a `cm`
        // mapping the image's 1×1 unit space onto the tile's physical rect (in
        // mm, under the page cm), then `Do`. The object body is built later when
        // the page's resources are materialized.
        const auto name = resources.name_for_image(
            tile.image_source_id, tile.level, tile.row, tile.col);
        resources.record_image(name, raster);
        stream.save_state();
        // Map the image's unit square [0,1]×[0,1] (PDF image space is y-UP, row 0
        // at v=1) onto the tile's physical rect in scene mm (y-DOWN), so source
        // row 0 lands at rect.top (the shallow end): a=width, d=−height (flip),
        // e=left, f=top+height. The page cm then maps this scene rect into the
        // flipped page space; the net result is an upright image in the placed
        // rect (mirroring SVG's <image y=top> which puts row 0 at top).
        stream.concat_matrix(tile.rect.width.value, 0.0, 0.0,
                             -tile.rect.height.value, tile.rect.left.value,
                             tile.rect.top.value + tile.rect.height.value);
        stream.invoke_xobject(name);
        stream.restore_state();
      }
    }
  }
  // Custom layer primitives.
  for (const auto &custom_layer : scene.custom_layers()) {
    if (custom_layer.track_id == track.id) {
      emit_custom_layer(stream, scene, custom_layer);
    }
  }
  // Text runs (vector outlines).
  for (const auto &run : scene.text_runs()) {
    const auto run_track = scene.track_id_for_layer(run.layer_id);
    if (run_track.has_value() && *run_track == track.id) {
      emit_text_run(stream, scene, run);
    }
  }
}

// Materializes one page's collected resources into the PdfIndirectObject list
// the writer appends. Patterns first (P0..), then images (Im0..) — deterministic
// order. Pattern definitions are looked up by id in the scene; image pixel
// records are carried in PageResources. Returns nullopt if any object body
// failed to build (e.g. a Flate error), so write() surfaces an Error rather than
// emit a malformed (dict-less) object that a `Do`/`scn` would dangle-reference.
std::optional<std::vector<PdfIndirectObject>>
materialize_objects(const PreparedScene &scene,
                    const PageResources &resources) {
  std::vector<PdfIndirectObject> objects;
  for (const auto &pattern_id : resources.pattern_order) {
    const PatternDefinition *pattern = nullptr;
    for (const auto &candidate : scene.patterns()) {
      if (candidate.id == pattern_id) {
        pattern = &candidate;
        break;
      }
    }
    if (pattern == nullptr) {
      continue;
    }
    auto body = build_pattern_body(*pattern);
    if (!body.has_value()) {
      return std::nullopt;
    }
    objects.push_back(PdfIndirectObject{
        .body = std::move(*body),
        .kind = PdfObjectKind::pattern,
        .local_name = resources.pattern_names.at(pattern_id),
    });
  }
  for (const auto &key : resources.image_order) {
    const auto name = resources.image_names.at(key);
    const auto rec_it = resources.image_records.find(name);
    if (rec_it == resources.image_records.end()) {
      continue;
    }
    auto body = build_image_body(rec_it->second);
    if (!body.has_value()) {
      return std::nullopt;
    }
    objects.push_back(PdfIndirectObject{
        .body = std::move(*body),
        .kind = PdfObjectKind::image,
        .local_name = name,
    });
  }
  return objects;
}

} // namespace

Result<PdfDocument>
PdfSceneExporter::write(const PreparedScene &scene,
                        const ExportSnapshot &snapshot,
                        std::function<Result<RasterTile>(const ImageTileRequest &)>
                            image_tile) noexcept {
  try {
    if (!snapshot_is_valid(scene, snapshot)) {
      return pdf_scene_error(ErrorCode::invalid_presentation,
                             MessageKey::presentation_invalid);
    }
    const auto &page = snapshot.page;
    const auto scale = printable_width(page) / scene.physical_width().value;
    const auto s_pt = scale * points_per_millimetre;
    const auto margin_left_pt =
        page.margins.left.value * points_per_millimetre;

    // Determine the pages: continuous (one page, true depth length) or fixed
    // (depth-window slicing), mirroring pagination.cpp.
    struct PageWindow {
      double window_top_mm;
      double window_bottom_mm;
      bool clip;          // false for continuous (whole scene), true for fixed
      double height_mm;   // page height in mm (MediaBox derived)
    };
    std::vector<PageWindow> windows;
    if (page.mode == PaginationMode::continuous) {
      const auto page_height_mm = scene.physical_height().value * scale +
                                  page.margins.top.value +
                                  page.margins.bottom.value;
      windows.push_back({0.0, scene.physical_height().value, false,
                         page_height_mm});
    } else {
      const auto printable_depth_mm = printable_depth_height_mm(scene, page);
      const auto effective_step =
          printable_depth_mm * (1.0 - page.page_overlap);
      const auto scene_height = scene.physical_height().value;
      auto page_count =
          static_cast<std::uint32_t>(std::ceil(scene_height / effective_step));
      if (page_count == 0) {
        page_count = 1;
      }
      for (std::uint32_t index = 0; index < page_count; ++index) {
        const auto window_top = static_cast<double>(index) * effective_step;
        auto window_bottom = window_top + printable_depth_mm;
        if (window_bottom > scene_height || index + 1 == page_count) {
          window_bottom = scene_height;
        }
        windows.push_back({window_top, window_bottom, true, page.page_height.value});
      }
    }

    std::vector<PdfPageContent> contents;
    std::vector<PdfPageSpec> specs;
    std::vector<std::vector<PdfIndirectObject>> object_storage;
    contents.reserve(windows.size());
    specs.reserve(windows.size());
    object_storage.reserve(windows.size());

    for (const auto &window : windows) {
      PdfPathStream stream;
      // Page cm: map scene-millimetres (sx, sy), y-DOWN with depth increasing
      // downward, into PDF user-space points (x, y), y-UP — so the scene renders
      // top-down (shallow depth at the page top, deep at the bottom), matching
      // the SVG backend and well-log convention. The y-flip is d=−s_pt. The
      // vertical translation pins scene-y=window_top at the printable TOP:
      // f = (window.height_mm − margins.top)·pmm + window_top·s_pt, correct for
      // BOTH symmetric and asymmetric margins (a prior f = mt_pt +
      // window_bottom·s_pt form was wrong for asymmetric margins — hidden by
      // tests using 10/10 all round). e = margin_left_pt.
      stream.concat_matrix(s_pt, 0.0, 0.0, -s_pt, margin_left_pt,
                           (window.height_mm - page.margins.top.value) *
                                   points_per_millimetre +
                               window.window_top_mm * s_pt);

      PageResources resources;
      if (window.clip) {
        // Page depth-window clip in scene mm: the [window_top, window_bottom]
        // band, which the flipped page cm maps onto the printable area.
        stream.save_state();
        stream.rect(0.0, window.window_top_mm, scene.physical_width().value,
                    window.window_bottom_mm - window.window_top_mm)
            .clip_nonzero()
            .end_path_no_paint();
      }
      for (const auto &track : scene.tracks()) {
        stream.save_state();
        stream.rect(track.clip.left.value, track.clip.top.value,
                    track.clip.width.value, track.clip.height.value)
            .clip_nonzero()
            .end_path_no_paint();
        emit_track_body(stream, scene, track, resources, image_tile);
        stream.restore_state();
      }
      if (window.clip) {
        stream.restore_state();
      }

      auto objects_opt = materialize_objects(scene, resources);
      if (!objects_opt.has_value()) {
        return pdf_scene_error(ErrorCode::internal_error,
                               MessageKey::internal_error);
      }
      PdfPageContent content{.stream = std::move(stream)};
      object_storage.push_back(std::move(*objects_opt));
      content.objects = object_storage.back();
      contents.push_back(std::move(content));
      specs.push_back(PdfPageSpec{
          .width_points = page.page_width.value * points_per_millimetre,
          .height_points = window.height_mm * points_per_millimetre,
      });
    }

    return PdfWriter::write(contents, specs);
  } catch (const std::bad_alloc &) {
    return pdf_scene_error(ErrorCode::resource_exhausted,
                           MessageKey::resource_exhausted);
  } catch (...) {
    return pdf_scene_error(ErrorCode::internal_error,
                           MessageKey::internal_error);
  }
}

} // namespace welllog
