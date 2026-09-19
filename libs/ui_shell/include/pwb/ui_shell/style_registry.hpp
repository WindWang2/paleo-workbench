#pragma once

// Port of paleo_workbench/ui/style.py (UI-01).
// 动态 inline 样式注册表：palette_for 的暗色覆盖只进 QSS；大量调用点用
// 模块常量拼 inline stylesheet，主题切换后不刷新 —— 显式注册 + 主题变化
// 时重渲染。
//
// Qt side of the contract: render callbacks must re-read palette() inside
// the call (never capture a snapshot); widgets unregister automatically on
// destroyed (QPointer). Bound renderers that throw are dropped loudly is a
// Python concern — in C++ a throwing renderer is unregistered (the widget
// may be mid-teardown).

#include <QObject>
#include <QPointer>
#include <functional>
#include <map>
#include <string>

namespace pwb::platform_services {
class ThemeService;
}

namespace pwb::ui_shell {

// Current-theme semantic token vocabulary — re-fetched per call, never
// cached (Python tokens.palette_for(theme_manager.current_theme) parity).
// Returns {} when no ThemeService is bound.
using Palette = std::map<std::string, std::string>;

class StyleRegistry : public QObject {
    Q_OBJECT
public:
    explicit StyleRegistry(QObject* parent = nullptr);

    // Bind the platform ThemeService (Python module-global theme_manager
    // parity). Re-binding disconnects the previous service.
    void bind_theme_service(pwb::platform_services::ThemeService* service);

    // Current palette through the bound ThemeService; empty without one.
    Palette palette() const;
    std::string current_density() const;  // "comfortable" fallback

    // --- widget bindings ---------------------------------------------------
    // Register a stylesheet render callback and apply it immediately.
    // render() must re-read its inputs inside the call — same contract as
    // Python style.bind. A nullptr return from render() marks a metrics-only
    // registration (no setStyleSheet call — bind_metrics parity).
    void bind(QWidget* widget, std::function<QString()> render);
    // Re-render a bound widget now (data-state changed). Prefer this over
    // re-binding — rebinding accumulates destroyed connections (R1 P2-8).
    void refresh(QWidget* widget);
    // Register a metrics-apply callback (fixed heights etc.) run now and on
    // every theme/density change; the callback's QString return is unused.
    void bind_metrics(QWidget* widget, std::function<void()> apply_fn);
    // Track a widget's minimum height by current density (re-set on theme
    // change) — replaces compile-time setMinimumHeight(CONTROL_HEIGHT).
    void track_control_height(QWidget* widget);

    // Strong subscription to theme/density changes — the caller MUST
    // disconnect on receiver destruction (Python docstring parity); prefer
    // bind() for widget-level styling.
    void on_theme_change(std::function<void(const QString& theme,
                                            const QString& density)> callback);

    // Re-render every bound inline style (ThemeManager wiring calls this on
    // theme_changed). One renderer's failure must not break the broadcast
    // chain — failures unregister the widget and keep going.
    void repolish_all();

private:
    void apply(QWidget* widget);
    void unregister(QWidget* widget);
    void refresh_min_heights();

    pwb::platform_services::ThemeService* theme_ = nullptr;
    QMetaObject::Connection theme_conn_;
    QMetaObject::Connection density_conn_;
    std::map<QWidget*, std::function<QString()>> registry_;
    std::map<QWidget*, QPointer<QWidget>> guards_;
};

// Process-level registry (Python module-global parity). App code may also
// hold a per-shell instance; the global is for leaf widgets.
StyleRegistry& style_registry();

// Convenience free functions mirroring the Python module API.
void style_bind(QWidget* widget, std::function<QString()> render);
void style_refresh(QWidget* widget);
void style_bind_metrics(QWidget* widget, std::function<void()> apply_fn);
void style_track_control_height(QWidget* widget);
Palette style_palette();

}  // namespace pwb::ui_shell
