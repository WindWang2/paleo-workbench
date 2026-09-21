#pragma once

// UI-10 Qt replay seam for the native composer export
// (V14-COMPILATION-PUBLISH).
//
// The composition page export kernel (pwb::mapping_document::
// export_composition_page) writes SVG itself but needs a paint device for
// PNG/PDF. This is the Qt implementation of that device — the faithful C++
// port of paleo_workbench/mapping/composer/export.py's
// export_composition_png / export_composition_pdf:
//   * PNG — the SVG replayed through QSvgRenderer onto a white
//     ARGB32_Premultiplied QImage sized by composition_page_pixels(dpi),
//     with dotsPerMeter set so the printed size matches the export DPI;
//   * PDF — a QPdfWriter whose page is the document's physical size, the
//     SVG replayed vectorially onto the writer's page rectangle.
//
// The replay is the host side of ComposerReplaySeams::replay; returning
// false with a message is an honest refusal (the caller removes any
// partial file), never a fabricated raster.

#include <pwb/mapping_document/composer_export.hpp>

#include <string>

namespace pwb::ui_seqviz::qt {

// Compose the ComposerReplaySeams bundle (bind once, pass to
// export_composition_page).
[[nodiscard]] pwb::mapping_document::ComposerReplaySeams
make_composition_replay_seams();

}  // namespace pwb::ui_seqviz::qt
