#pragma once

// Native composition page export (V14-COMPILATION-PUBLISH).
//
// Faithful port of paleo_workbench/mapping/composer/export.py — the
// physical-size page contract shared by SVG / PNG / PDF:
//   * SVG — the mm-authored vector scene, re-anchored to physical
//     millimetres (viewBox stays mm);
//   * PNG — the SVG replayed at `dpi` through the host's replay seam
//     (Qt QSvgRenderer on the Qt side), with the printed size persisted;
//   * PDF — the SVG replayed vectorially onto a physical-size page.
//
// The kernel writes SVG directly (atomically: temp → fsync → rename,
// stronger than Python's plain write; partial files are removed on
// failure). PNG/PDF rasterization needs a paint device, so they go
// through the injected ComposerReplaySeams — an absent seam is an honest
// refusal (ok=false), never a fabricated file. Unsupported formats fail
// closed with the Python message.
//
// Qt-free, Python-free.

#include <pwb/mapping_document/composition.hpp>
#include <pwb/mapping_document/composer_renderer.hpp>

#include <filesystem>
#include <functional>
#include <optional>
#include <string>

namespace pwb::mapping_document {

// Host paint-device seam for PNG/PDF (Qt implements it; see
// ui_seqviz_qt::composition_replay). Returns false with a message when the
// replay or the device write failed.
struct ComposerReplaySeams {
    // svg: the re-anchored composition SVG; format: "png" | "pdf".
    std::function<bool(const std::string& svg, const std::string& path,
                       const std::string& format, double dpi, double width_mm,
                       double height_mm, std::string& message)>
        replay;
};

// export_composition report slice (engine + path + failure reason).
struct CompositionExportReport {
    bool ok = false;
    std::string engine = "composer_svg";
    std::string path;
    std::string format;
    double dpi = 0.0;
    std::string message;
};

// The re-anchored physical-size SVG for this document (export.py
// _composition_svg).
[[nodiscard]] std::string composition_export_svg(const Composition& doc);

// Same, with the live-content render seams (the export path must render
// the same content the preview shows — decision D-V14-05).
[[nodiscard]] std::string composition_export_svg_with_seams(
    const Composition& doc, const ComposerRenderSeams& render_seams);

// export_composition dispatch: `format` empty ⇒ the path's extension
// (lower-cased) ⇒ "png". Throws std::invalid_argument with the Python
// message for unsupported formats. Never leaves a partial file behind.
[[nodiscard]] CompositionExportReport export_composition_page(
    const Composition& doc, const std::filesystem::path& path,
    const std::string& format = "", std::optional<double> dpi = std::nullopt,
    const ComposerRenderSeams& render_seams = {},
    const ComposerReplaySeams& replay = {});

}  // namespace pwb::mapping_document
