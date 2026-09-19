// UI-08 — _panel_icon seam: the pages' icon loader delegates to the shared
// theme-aware factory (paleo_workbench/ui/workstation/common.tinted_map_icon
// parity). Kept as a named seam so hosts can substitute their own provider.
#pragma once

#include <QIcon>
#include <QString>

#include <functional>

namespace pwb::ui_pages_mapedit {

using PanelIconFn = std::function<QIcon(const QString& name)>;

// Default provider — ui_widgets::tinted_map_icon (lazy-import parity: the
// lookup happens per call, never cached against a theme snapshot).
QIcon default_panel_icon(const QString& name);

// panel_icon(name): route through the current provider.
QIcon panel_icon(const QString& name);

// Host seam (tests / shells that re-tint differently).
void set_panel_icon_provider(PanelIconFn provider);

}  // namespace pwb::ui_pages_mapedit
