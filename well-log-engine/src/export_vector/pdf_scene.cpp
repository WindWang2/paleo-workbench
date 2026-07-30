// Single-page PDF scene emission (#187). Serializes a PreparedScene +
// ExportSnapshot to PDF content-stream operators via the #185 writer. The
// geometry emission mirrors src/export_vector/svg.cpp's append_layer_body 1:1
// — same per-track structure, same per-layer order (intervals, markers,
// symbols, curves, crossover fills, text), same scene-millimetre coordinates —
// but emits PDF path operators (`m/l/c/h/re/f/S`) instead of SVG elements.
//
// One `cm` (concat-matrix) operator at the page top maps the scaled scene (mm)
// into PDF user-space points, so the per-layer code operates in millimetres
// exactly like the SVG emitter. Track clipping uses `re ... W n` per track
// (mirroring SVG's clipPath). Text is rendered as glyph vector outlines: each
// glyph's OutlineCommand stream is emitted under a per-glyph `cm` that applies
// the same translate/rotate/scale(fs,-fs) the SVG `<use>` does — no font
// program is embedded (ADR: PDF via hand-rolled writer, #185).
//
// Determinism is by construction (no CreationDate/ModDate/ID); identical input
// always yields byte-identical output.

#include <welllog/export/pdf_scene.hpp>

#include <array>
#include <cmath>
#include <cstdint>
#include <string>
#include <utility>

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

// Emits the closed boundary ring of one crossover-fill region as a path + fill,
// mirroring svg.cpp::append_fill_ring_path.
void emit_fill_region(PdfPathStream &stream, const PreparedScene &scene,
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
  stream.set_fill_color(region.fill_color.red, region.fill_color.green,
                        region.fill_color.blue);
  if (region.fill_color.alpha < 255) {
    stream.set_fill_alpha(static_cast<double>(region.fill_color.alpha) / 255.0);
  }
  // Patterned fills are #188; fall back to the region's solid fill_color (the
  // spec always carries one) so the geometry is still drawn, not dropped.
  stream.close().fill();
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

// Emits the per-track, per-layer body — the single geometric emitter for one
// track, mirroring svg.cpp::append_layer_body's per-track `<g>`. Called inside
// the track's saved clip state.
void emit_track_body(PdfPathStream &stream, const PreparedScene &scene,
                     const PreparedTrack &track) noexcept {
  // Interval rects (solid fills only this ticket; pattern fill is #188).
  for (const auto &layer : scene.interval_layers()) {
    if (layer.track_id != track.id) {
      continue;
    }
    for (std::uint64_t offset = 0; offset < layer.interval_count; ++offset) {
      const auto &interval = scene.intervals()[static_cast<std::size_t>(
          layer.first_interval + offset)];
      stream.set_fill_color(interval.fill_color.red,
                            interval.fill_color.green,
                            interval.fill_color.blue);
      if (interval.fill_color.alpha < 255) {
        stream.set_fill_alpha(
            static_cast<double>(interval.fill_color.alpha) / 255.0);
      }
      stream.rect(interval.rect.left.value, interval.rect.top.value,
                  interval.rect.width.value, interval.rect.height.value)
          .fill();
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
      emit_fill_region(stream, scene, region);
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

} // namespace

Result<PdfDocument>
PdfSceneExporter::write(const PreparedScene &scene,
                        const ExportSnapshot &snapshot) noexcept {
  try {
    if (!snapshot_is_valid(scene, snapshot)) {
      return pdf_scene_error(ErrorCode::invalid_presentation,
                             MessageKey::presentation_invalid);
    }
    const auto &page = snapshot.page;

    // Continuous mode: the printable width maps the scene width, and the page
    // height preserves true depth→physical-length (scene physical height scaled
    // by the same width factor), exactly like PaginatedSvgExporter's continuous
    // branch. Fixed-mode pagination arrives in #188.
    const auto scale = printable_width(page) / scene.physical_width().value;
    const auto page_height_mm = scene.physical_height().value * scale +
                                page.margins.top.value +
                                page.margins.bottom.value;

    // Build the single page's content stream. One `cm` maps a scene-millimetre
    // point (sx, sy) to PDF user-space points:
    //   (marginL_mm·pmm + sx·scale·pmm, marginT_mm·pmm + sy·scale·pmm)
    // As an affine [a b c d e f] that is a=d=scale·pmm, e=marginL_mm·pmm,
    // f=marginT_mm·pmm (b=c=0). pmm = points per millimetre.
    PdfPageContent content;
    const auto s_pt = scale * points_per_millimetre;
    const auto margin_left_pt = page.margins.left.value * points_per_millimetre;
    const auto margin_top_pt = page.margins.top.value * points_per_millimetre;
    content.stream.concat_matrix(s_pt, 0.0, 0.0, s_pt, margin_left_pt,
                                 margin_top_pt);

    // Per track: save state, establish the track clip (re ... W n), emit the
    // body, restore state — mirroring SVG's per-track clipPath'd `<g>`.
    for (const auto &track : scene.tracks()) {
      content.stream.save_state();
      content.stream
          .rect(track.clip.left.value, track.clip.top.value,
                track.clip.width.value, track.clip.height.value)
          .clip_nonzero()
          .end_path_no_paint();
      emit_track_body(content.stream, scene, track);
      content.stream.restore_state();
    }

    const std::array<PdfPageContent, 1> pages{content};
    // MediaBox is in PDF points; page size derived in millimetres (margin +
    // scaled scene) like the continuous SVG page.
    const PdfPageSpec spec{
        .width_points = page.page_width.value * points_per_millimetre,
        .height_points = page_height_mm * points_per_millimetre,
    };
    const std::array<PdfPageSpec, 1> specs{spec};
    return PdfWriter::write(pages, specs);
  } catch (const std::bad_alloc &) {
    return pdf_scene_error(ErrorCode::resource_exhausted,
                           MessageKey::resource_exhausted);
  } catch (...) {
    return pdf_scene_error(ErrorCode::internal_error,
                           MessageKey::internal_error);
  }
}

} // namespace welllog
