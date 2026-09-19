#pragma once

// UI-02 — map chrome painting (scale bar / north arrow / legend /
// facies-legend box), ported from the decoration helpers in
// paleo_workbench/ui/unified_map_canvas.py that the QGIS canvas chrome
// overlays consume (_paint_scale_bar_impl, _scale_bar_spec_impl,
// paint_map_decorations, legend_chrome_size, ensure_basic_map_chrome,
// _facies_pattern_pixmap).
//
// Domain semantics (unified_map_canvas docstring / decisions.md D10):
// chrome ink is relative to the MAP BODY (light body -> dark ink, dark
// body -> light ink), independent of the app theme; interaction colors
// use CANVAS_* tokens. All sizes are in device pixels; `scale` is
// dpi/96 for export targets.
//
// Decorations payload is the Python dict vocabulary carried as
// QVariantMap: {"elements": [..], "title": str,
//               "legend_items": [str | {"label"|"name"|"text","color"|"fill"}],
//               "facies_legend": {"title": str,
//                                 "items": [{"label","color","pattern"}]}}.

#include <QColor>
#include <QMap>
#include <QPainter>
#include <QPixmap>
#include <QRectF>
#include <QSize>
#include <QString>
#include <QStringList>
#include <QVariantMap>

#include <array>
#include <optional>

namespace pwb::ui_widgets {

// Chrome palette — RELATIVE TO THE MAP BODY, not the app theme (D10).
inline const QColor kChromeInkOnLightBody{QStringLiteral("#1f2937")};
inline const QColor kChromeInkOnDarkBody{QStringLiteral("#f8f9fa")};
inline const QColor kChromePanelBg{24, 28, 34, 210};
inline const QString kChromePanelBorder{QStringLiteral("#dfe6ee")};
inline const QString kSwatchFallback{QStringLiteral("#6c8ebf")};

// Cartographic basics always shown on a map face; can coexist with
// other decorations. Chinese labels match the frozen Python vocabulary.
inline const QStringList kBasicMapChrome{
    QStringLiteral("比例尺"), QStringLiteral("指北针")};

// Inject basic chrome (scale bar + north arrow) when the caller did
// not declare an explicit elements whitelist. A non-empty whitelist is
// respected as-is (export tests requesting only a title must not gain
// a north arrow — the dpi/96 font-scaling contract).
QVariantMap ensure_basic_map_chrome(const QVariantMap& decorations);

// Round a map-unit length down onto the 1/2/5 x 10^n ladder.
double nice_scale_units(double value);

// (nice unit length, matching pixel length) for a scale bar; nullopt
// when the extent span is degenerate or the bar would be < 16*scale px.
std::optional<std::pair<double, double>> scale_bar_spec(
    const std::array<double, 4>& extent, int canvas_width,
    double scale = 1.0);

// Paint the scale bar (label length matches the drawn bar exactly).
void paint_scale_bar(QPainter& painter,
                     const std::array<double, 4>& extent,
                     int canvas_width, int canvas_height, double scale,
                     const QColor& ink = kChromeInkOnDarkBody);

// Draw title / scale bar / north arrow / legend (+ facies-legend box).
// `extent` is the extent actually rendered into this target (exports
// letterbox the view extent); dark_chrome selects the dark ink palette
// for light map bodies.
void paint_map_decorations(QPainter& painter,
                           const QVariantMap& decorations,
                           int width, int height,
                           const std::array<double, 4>& extent,
                           double scale = 1.0,
                           bool dark_chrome = false);

// Native legend-widget size: must hold the work legend PLUS the
// facies-pattern box painted to its left (paint_map_decorations draws
// the facies box at rect.left - f_width - 8; a ~180px widget clips it
// into negative coordinates — the exact reason pattern fills were
// invisible on the native canvas). (0,0) when there is no legend
// content.
QSize legend_chrome_size(const QVariantMap& decorations, double scale = 1.0);

// 32x32 SVG tile pixmap for a facies pattern id (transparent black-line
// tile). Missing mapping / missing asset / load failure -> null pixmap
// (honest: Python's is_file check also yields None when the vendored
// geo-viz-engine pattern assets are absent).
QPixmap facies_pattern_pixmap(const QString& pattern_id);

}  // namespace pwb::ui_widgets
