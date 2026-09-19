#pragma once

// UI-02 — shared theme/density access for the component layer, ported
// from paleo_workbench/ui/style.py accessors + theme.py's theme_manager
// singleton semantics.
//
// The Python components read a process-global theme_manager. The C++
// port injects the host's pwb::platform_services::ThemeService once
// (set_theme_service); when the host has not installed one, a lazily
// created process-lifetime fallback mirrors the Python singleton (so
// component construction never touches a null service — the fallback
// reads the same persisted (theme, density) pair).

#include <pwb/platform_services/theme_service.hpp>
#include <pwb/platform_services/theme_tokens.hpp>

#include <QString>
#include <map>
#include <string>

class QWidget;

namespace pwb::ui_widgets {

// The active theme service (host-installed, else a lazily created
// process-lifetime fallback — the Python theme_manager equivalent).
pwb::platform_services::ThemeService* theme_service();

// Host installs its service (AppContext wiring — out of this slice's
// scope, but the seam must exist for it). nullptr resets to fallback.
void set_theme_service(pwb::platform_services::ThemeService* service);

// Current values (paint-time reads — never cache, style.py contract).
pwb::platform_services::ThemeMode current_theme();
pwb::platform_services::Density current_density();
std::map<std::string, std::string> current_palette();

// palette token value for the current theme ("" when absent).
QString palette_token(const char* name);

// Density metrics for the CURRENT density (tokens.* accessors).
int row_height();
int toolbar_height();
int combo_item_height();
QString item_padding();
QString menu_padding();
QString tab_padding();

// Layout spacing tokens (tokens.py SPACE_* — frozen integers, not colors).
inline constexpr int kSpaceXs = 2;
inline constexpr int kSpaceS = 4;
inline constexpr int kSpaceM = 8;
inline constexpr int kSpaceL = 12;
inline constexpr int kSpaceXl = 16;
inline constexpr int kSpace2Xl = 24;

// unpolish/polish one widget (dynamic property changes need a repolish —
// the Python components' shared _repolish helper).
void repolish(QWidget* widget);
// repolish every child widget (buttons.repolish_tree parity).
void repolish_tree(QWidget* widget);

}  // namespace pwb::ui_widgets
