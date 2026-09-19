#include "pwb/ui_pages_mapedit/map_icons.hpp"

#include "pwb/ui_widgets/icon_factory.hpp"

namespace pwb::ui_pages_mapedit {
namespace {

PanelIconFn& provider() {
    static PanelIconFn fn = &default_panel_icon;
    return fn;
}

}  // namespace

QIcon default_panel_icon(const QString& name) {
    // tinted_map_icon parity — theme-aware tinting, DPR-aware pixmaps,
    // process cache; missing asset → empty icon.
    return ui_widgets::tinted_map_icon(name);
}

QIcon panel_icon(const QString& name) {
    const auto& fn = provider();
    return fn ? fn(name) : QIcon();
}

void set_panel_icon_provider(PanelIconFn new_provider) {
    provider() = new_provider ? std::move(new_provider)
                              : PanelIconFn(&default_panel_icon);
}

}  // namespace pwb::ui_pages_mapedit
