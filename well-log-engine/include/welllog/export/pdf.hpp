#pragma once

// Minimal hand-rolled PDF writer (ADR: PDF via hand-rolled writer, #185 spike,
// extended by #187 scene emission).
//
// This writer produces a byte-deterministic, Flate-compressed multi-page PDF
// with no third-party PDF library — only zlib for stream compression. It exposes
// the primitives the per-layer scene emission (#187's PdfSceneExporter) needs: a
// path operator stream built from the engine's backend-neutral OutlineCommand
// vocabulary, plus the graphics-state operators (clip, transform, alpha) those
// layers require, and page assembly. Output is deterministic by construction
// (no CreationDate/ModDate/ID).

#include <cstdint>
#include <memory>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include <welllog/core/result.hpp>
#include <welllog/export/pdf_export.hpp>
#include <welllog/scene/text_engine.hpp>

namespace welllog {

// One flattened PDF content-stream path, in PDF user-space units (points),
// built from the engine's OutlineCommand model. The mapping mirrors the SVG
// path-data emitter (src/export_vector/svg.cpp append_outline_path_data) but
// emits PDF operators and lifts quadratic curves to cubics (PDF has no
// quadratic).
class WELLLOG_EXPORT_PDF_API PdfPathStream {
public:
  PdfPathStream();
  ~PdfPathStream();
  PdfPathStream(const PdfPathStream &);
  PdfPathStream &operator=(const PdfPathStream &);
  PdfPathStream(PdfPathStream &&) noexcept;
  PdfPathStream &operator=(PdfPathStream &&) noexcept;

  // move-to (PDF `m`).
  PdfPathStream &move_to(double x, double y) noexcept;
  // line-to (PDF `l`).
  PdfPathStream &line_to(double x, double y) noexcept;
  // Append an OutlineCommand (em-space, y-up, glyph-local). Coordinates are
  // used verbatim; quadratic_to is lifted to a cubic. close → PDF `h`.
  PdfPathStream &append_outline(std::span<const OutlineCommand> commands,
                                double scale = 1.0,
                                double dx = 0.0, double dy = 0.0) noexcept;
  // Close the current subpath.
  PdfPathStream &close() noexcept;
  // Fill the current path (non-zero winding). PDF `f`.
  PdfPathStream &fill() noexcept;
  // Stroke the current path. PDF `S`.
  PdfPathStream &stroke() noexcept;
  // Set the non-stroking (fill) colour, sRGB 0–255.
  PdfPathStream &set_fill_color(std::uint8_t r, std::uint8_t g,
                                std::uint8_t b) noexcept;
  // Set the stroking colour, sRGB 0–255.
  PdfPathStream &set_stroke_color(std::uint8_t r, std::uint8_t g,
                                  std::uint8_t b) noexcept;
  // Set the line width in points.
  PdfPathStream &set_line_width(double width) noexcept;
  // Save/restore the graphics state (PDF `q`/`Q`). Used to scope per-track
  // clips and per-glyph transforms so they never leak across layers.
  PdfPathStream &save_state() noexcept;
  PdfPathStream &restore_state() noexcept;
  // Concatenate the current transformation matrix with the given 6-element
  // matrix (PDF `cm`). This is how the page maps scene millimetres into PDF
  // user-space points, and how per-glyph placement/rotation is applied.
  PdfPathStream &concat_matrix(double a, double b, double c, double d,
                               double e, double f) noexcept;
  // Append a rectangle subpath (PDF `re`). Equivalent to m/l/l/l/h but the
  // dedicated operator is the idiomatic, compact form for axis-aligned rects
  // (intervals, track clips, printable areas).
  PdfPathStream &rect(double x, double y, double width,
                      double height) noexcept;
  // Clip the current path (non-zero winding, PDF `W`) then discard it without
  // painting (PDF `n`). The `clip` + `end_path_no_paint` pair establishes the
  // clip region the following operators draw against; mirror SVG's clipPath.
  PdfPathStream &clip_nonzero() noexcept;
  PdfPathStream &end_path_no_paint() noexcept;
  // Set the non-stroking (fill) alpha to `alpha` in [0,1]. PDF has no inline
  // opacity, so this resolves to a named /ExtGState object (`/GSn`) emitted by
  // the writer; the alpha values a stream uses are recorded deterministically
  // (first-encountered order, deduplicated) and the writer names the objects
  // in that same order, so identical content always yields identical /GS names
  // and object layout. A `gs` operator is emitted referencing the assigned name.
  PdfPathStream &set_fill_alpha(double alpha) noexcept;

  // The raw (uncompressed) content-stream operators.
  [[nodiscard]] std::string_view operators() const noexcept;
  // The distinct fill-alpha values this stream emitted `gs /GSn` for, in
  // first-encountered order. The writer emits one /ExtGState object per value
  // and names them /GS0, /GS1, … by this same order. Empty when no alpha was
  // set (opaque only).
  [[nodiscard]] std::span<const double> fill_alphas() const noexcept;

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

// Physical page geometry in points (1 pt = 1/72 inch). The spike defaults match
// ISO A4 portrait. Depth (well-log) layouts use a tall custom size in later
// tickets; the spike only needs a valid fixed page.
struct PdfPageSpec {
  double width_points{595.275591};  // A4 width  (210 mm)
  double height_points{841.889764}; // A4 height (297 mm)
};

// One page's worth of content-stream operators. The spike emits simple geometry
// per page; later tickets replace this with the per-layer prepared-scene emit.
struct PdfPageContent {
  PdfPathStream stream;
};

class WELLLOG_EXPORT_PDF_API PdfDocument {
public:
  PdfDocument();
  ~PdfDocument();
  PdfDocument(const PdfDocument &);
  PdfDocument &operator=(const PdfDocument &);
  PdfDocument(PdfDocument &&) noexcept;
  PdfDocument &operator=(PdfDocument &&) noexcept;

  [[nodiscard]] std::string_view bytes() const noexcept;

private:
  struct Impl;
  explicit PdfDocument(std::shared_ptr<const Impl> impl);
  std::shared_ptr<const Impl> impl_;
  friend class PdfWriter;
};

// Assembles a byte-deterministic, Flate-compressed multi-page PDF from page
// content + page specs. No CreationDate/ModDate and no /ID are emitted, so two
// identical inputs always produce identical output.
class WELLLOG_EXPORT_PDF_API PdfWriter {
public:
  // Build a PDF with one page per content entry (page_specs defaults to A4 when
  // empty, sized to the content count). Returns a Result so allocation/path
  // failures surface as Errors like the other exporters.
  [[nodiscard]] static Result<PdfDocument>
  write(std::span<const PdfPageContent> pages,
        std::span<const PdfPageSpec> page_specs = {}) noexcept;
};

} // namespace welllog
