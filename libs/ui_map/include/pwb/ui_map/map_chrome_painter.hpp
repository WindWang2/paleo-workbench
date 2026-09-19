#pragma once

// UI-05 — Qt painter port of paleo_workbench/ui/unified_map_canvas.py's
// decoration layer (paint_map_decorations / _paint_decorations_impl /
// _paint_scale_bar_impl / ensure_basic_map_chrome / _nice_scale_units_impl /
// _scale_bar_spec_impl / legend_chrome_size / _facies_pattern_pixmap).
// The decoration Json shape is the Python one: {"title","elements",
// "legend_items",[ "facies_legend" ]}. Consumed by DisplayMapCanvas's
// overlay and by export code paths in later slices.

#include <QPixmap>
#include <QString>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/ui_map/map_chrome_core.hpp>

class QPainter;

namespace pwb::ui_map {

// Chrome ink vocabulary (unified_map_canvas.py literals).
inline constexpr const char* kChromeInkOnLightBody = "#1f2937";
inline constexpr const char* kChromeInkOnDarkBody = "#f8f9fa";
// Panel: QColor(24, 28, 34, 210) — alpha composited against the map body.
inline constexpr int kChromePanelBgR = 24;
inline constexpr int kChromePanelBgG = 28;
inline constexpr int kChromePanelBgB = 34;
inline constexpr int kChromePanelBgA = 210;
inline constexpr const char* kChromePanelBorder = "#dfe6ee";
inline constexpr const char* kChromeSwatchFallback = "#6c8ebf";

// ensure_basic_map_chrome: empty/absent elements -> {"比例尺","指北针"};
// an explicit non-empty whitelist passes through untouched.
Json ensure_basic_map_chrome(const Json& decorations);

// _nice_scale_units_impl: round a map-unit length down onto 1/2/5 x 10^n.
// Non-positive/non-finite input passes through unchanged (Python parity).
double nice_scale_units(double value);

// _scale_bar_spec_impl: (nice unit length, pixel length) or nullopt.
std::optional<std::pair<double, double>> scale_bar_spec(
    const Extent& extent, double canvas_width, double scale = 1.0);

// paint_map_decorations: title / scale bar / north arrow / legend (+ facies
// legend box) in device pixels. scale = dpi/96 for exports; dark_chrome
// selects the dark ink palette for light map bodies.
void paint_map_decorations(QPainter& painter, const Json& decorations,
                           double width, double height, const Extent& extent,
                           double dpi = 0.0, bool dark_chrome = false);

// legend_chrome_size: native legend control size (fits the work-area legend
// plus the facies texture box to its left); (0,0) without legend content.
std::pair<int, int> legend_chrome_size(const Json& decorations,
                                       double scale = 1.0);

// FACIES_PATTERN_DIR equivalent — the geo-viz-engine asset root. Resolved
// once from PWB_FACIES_PATTERN_DIR (empty when unset; tiles degrade to base
// swatches, matching Python's missing-file fallback).
const std::string& facies_pattern_dir();

// _facies_pattern_pixmap: 32x32 transparent SVG tile for a pattern id.
// `dir` is the FACIES_PATTERN_DIR equivalent (assets/patterns/facies);
// missing/invalid loads cache as null (Python _PATTERN_PIXMAP_CACHE parity).
QPixmap facies_pattern_pixmap(const std::string& pattern_id,
                              const std::string& pattern_dir);

}  // namespace pwb::ui_map
