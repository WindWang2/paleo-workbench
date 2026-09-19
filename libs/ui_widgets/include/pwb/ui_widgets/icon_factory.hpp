#pragma once

// UI-02 — repository-SVG icon factory, ported from
// paleo_workbench/ui/workstation/common.py (workstation_icon /
// tinted_map_icon): theme-aware tinting, DPR-aware pixmaps, process cache.
//
// Assets resolve through pwb::platform_services::resource_file (the same
// locator as the rest of the native stack — PALEO_RESOURCES_DIR override,
// source tree, install-relative); the Python assets dir is
// paleo_workbench/ui/assets/icons.

#include <QIcon>
#include <QPixmap>
#include <QSize>
#include <QString>

namespace pwb::ui_widgets {

// Repo icon tinted with a semantic color. Empty `color` uses the CURRENT
// theme's TEXT_SECONDARY (paint-time token read, never cached); missing
// assets return an empty QIcon (honest miss, caller's no-asset fallback
// is unchanged).
QIcon workstation_icon(const QString& name, const QString& color = QString());

// Map-workspace icon from assets/icons/map (root dir fallback), same
// tinting mechanism — except achromatic detection: SVGs carrying semantic
// (non-gray) baked colors are returned untinted, since a flat recolor
// would destroy map symbology meaning.
QIcon tinted_map_icon(const QString& name, const QString& color = QString());

// The states.py _tinted_pixmap helper: theme-tinted pixmap at `size` for
// the target's devicePixelRatioF (explicit DPR overload keeps the logical
// size constant on HiDPI — audit G-P1-6).
QPixmap tinted_pixmap(const QString& icon_name, const QString& color_token,
                      int size, double dpr = 1.0);

// Current-theme TEXT_SECONDARY (paint-time read).
QString default_icon_color();

}  // namespace pwb::ui_widgets
