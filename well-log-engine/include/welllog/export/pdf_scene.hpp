#pragma once

// Single-page PDF scene emission (#187). Built on the hand-rolled writer from
// #185 (ADR: PDF via hand-rolled writer) and the Export Snapshot model from
// #186 (ADR 0048): a PreparedScene + ExportSnapshot are serialized to a PDF
// whose content stream is pure vector geometry — interval rects, marker lines,
// symbol paths, curve polylines, crossover-fill rings, and text rendered as
// glyph vector outlines (no font program embedded; text is graphical, not
// searchable, per the #185 decision). Mirrors src/export_vector/svg.cpp's
// append_layer_body 1:1, emitting PDF operators instead of SVG elements.
//
// Coordinate model: the engine's geometry is in scene millimetres (y-down);
// PDF user space is points (1 pt = 1/72 inch). Rather than converting every
// coordinate, one `cm` (concat-matrix) operator at the page top maps the
// scaled scene (mm) into PDF points, so the per-layer emission reads identically
// to the SVG emitter and depth proportions stay true (ADR 0039). Track clipping
// is honoured with a per-track `re ... W n` clip, mirroring SVG's clipPath.
//
// This ticket emits a SINGLE page (continuous-mode layout). Raster images,
// tiling patterns, multi-page pagination and custom-layer symbol geometry
// arrive in the next ticket (#188). Patterned intervals currently fall back to
// their solid fill_color (the spec always carries one); pattern fill is #188.
//
// Determinism is by construction (no CreationDate/ModDate/ID), matching the
// writer; identical scene + snapshot always produce byte-identical output.

#include <welllog/core/result.hpp>
#include <welllog/export/pdf.hpp>
#include <welllog/export/pdf_export.hpp>
#include <welllog/export/pagination.hpp>
#include <welllog/scene/scene.hpp>

namespace welllog {

// Serializes one PreparedScene + ExportSnapshot to a single-page PDF. Returns a
// Result so invalid scenes/snapshots surface as ErrorCode::invalid_presentation,
// consistent with SvgExporter / PaginatedSvgExporter. Continuous mode is the
// only mode this ticket supports (fixed-mode pagination is #188).
class WELLLOG_EXPORT_PDF_API PdfSceneExporter {
public:
  [[nodiscard]] static Result<PdfDocument>
  write(const PreparedScene &scene, const ExportSnapshot &snapshot) noexcept;
};

} // namespace welllog
