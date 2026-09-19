#include "pwb/ui_widgets/ui_context.hpp"

#include <QCoreApplication>
#include <QStyle>
#include <QWidget>

namespace pwb::ui_widgets {

namespace {

pwb::platform_services::ThemeService* g_host_service = nullptr;
pwb::platform_services::ThemeService* g_fallback = nullptr;

}  // namespace

pwb::platform_services::ThemeService* theme_service() {
    if (g_host_service != nullptr) return g_host_service;
    if (g_fallback == nullptr) {
        // Process-lifetime fallback (the Python theme_manager singleton
        // equivalent): created once, parented to the application so it
        // dies with it rather than mid-teardown.
        g_fallback = new pwb::platform_services::ThemeService(
            QCoreApplication::instance());
    }
    return g_fallback;
}

void set_theme_service(pwb::platform_services::ThemeService* service) {
    g_host_service = service;  // not owned — the host owns its service
}

pwb::platform_services::ThemeMode current_theme() {
    return theme_service()->theme();
}

pwb::platform_services::Density current_density() {
    return theme_service()->density();
}

std::map<std::string, std::string> current_palette() {
    return pwb::platform_services::palette_for(current_theme());
}

QString palette_token(const char* name) {
    const auto palette = current_palette();
    const auto it = palette.find(name);
    return it == palette.end() ? QString()
                               : QString::fromStdString(it->second);
}

int row_height() {
    return pwb::platform_services::density_for(current_density()).row_height;
}

int toolbar_height() {
    return pwb::platform_services::density_for(current_density())
        .toolbar_height;
}

int combo_item_height() {
    return pwb::platform_services::density_for(current_density())
        .combo_item_height;
}

QString item_padding() {
    return QString::fromStdString(
        pwb::platform_services::density_for(current_density()).item_padding);
}

QString menu_padding() {
    return QString::fromStdString(
        pwb::platform_services::density_for(current_density()).menu_padding);
}

QString tab_padding() {
    return QString::fromStdString(
        pwb::platform_services::density_for(current_density()).tab_padding);
}

void repolish(QWidget* widget) {
    if (widget == nullptr) return;
    QStyle* style = widget->style();
    style->unpolish(widget);
    style->polish(widget);
}

void repolish_tree(QWidget* widget) {
    if (widget == nullptr) return;
    const auto children = widget->findChildren<QWidget*>();
    for (QWidget* child : children) repolish(child);
}

}  // namespace pwb::ui_widgets
