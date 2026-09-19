#include "pwb/ui_shell/style_registry.hpp"

#include <QWidget>

#include <pwb/platform_services/theme_service.hpp>
#include <pwb/platform_services/theme_tokens.hpp>

namespace pwb::ui_shell {

namespace {

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

}  // namespace

StyleRegistry::StyleRegistry(QObject* parent) : QObject(parent) {}

void StyleRegistry::bind_theme_service(
    pwb::platform_services::ThemeService* service) {
    if (theme_conn_) {
        disconnect(theme_conn_);
        theme_conn_ = {};
    }
    if (density_conn_) {
        disconnect(density_conn_);
        density_conn_ = {};
    }
    theme_ = service;
    if (theme_ == nullptr) {
        return;
    }
    // ThemeService emits a single theme_changed(theme, density) for both
    // axes — repolish styles and re-apply tracked heights on either change.
    theme_conn_ =
        connect(theme_, &pwb::platform_services::ThemeService::theme_changed,
                this, [this](const QString&, const QString&) {
                    repolish_all();
                });
}

Palette StyleRegistry::palette() const {
    if (theme_ == nullptr) {
        return {};
    }
    return pwb::platform_services::palette_for(theme_->theme());
}

std::string StyleRegistry::current_density() const {
    if (theme_ == nullptr) {
        return "comfortable";
    }
    return pwb::platform_services::to_string(theme_->density());
}

void StyleRegistry::bind(QWidget* widget,
                         std::function<QString()> render) {
    if (widget == nullptr || !render) {
        return;
    }
    registry_[widget] = std::move(render);
    guards_[widget] = widget;
    connect(widget, &QObject::destroyed, this,
            [this, widget] { unregister(widget); });
    apply(widget);
}

void StyleRegistry::refresh(QWidget* widget) {
    apply(widget);
}

void StyleRegistry::bind_metrics(QWidget* widget,
                                 std::function<void()> apply_fn) {
    if (widget == nullptr || !apply_fn) {
        return;
    }
    auto fn = std::make_shared<std::function<void()>>(std::move(apply_fn));
    registry_[widget] = [fn]() -> QString {
        (*fn)();
        return QString();  // metrics-only: no stylesheet to apply
    };
    guards_[widget] = widget;
    connect(widget, &QObject::destroyed, this,
            [this, widget] { unregister(widget); });
    (*fn)();
}

void StyleRegistry::track_control_height(QWidget* widget) {
    if (widget == nullptr) {
        return;
    }
    const auto metrics =
        pwb::platform_services::density_for(current_density());
    widget->setMinimumHeight(metrics.btn_height);
    bind_metrics(widget, [this, widget] {
        const auto m = pwb::platform_services::density_for(current_density());
        if (widget != nullptr) {
            widget->setMinimumHeight(m.btn_height);
        }
    });
}

void StyleRegistry::on_theme_change(
    std::function<void(const QString&, const QString&)> callback) {
    if (theme_ == nullptr || !callback) {
        return;
    }
    connect(theme_, &pwb::platform_services::ThemeService::theme_changed,
            this, std::move(callback));
}

void StyleRegistry::repolish_all() {
    // Iterate a key snapshot — apply() may unregister dead entries.
    std::vector<QWidget*> keys;
    keys.reserve(registry_.size());
    for (const auto& [w, fn] : registry_) {
        keys.push_back(w);
    }
    for (QWidget* widget : keys) {
        try {
            apply(widget);
        } catch (...) {
            // One renderer's failure must not break the broadcast chain.
            unregister(widget);
        }
    }
}

void StyleRegistry::apply(QWidget* widget) {
    const auto it = registry_.find(widget);
    if (it == registry_.end()) {
        return;
    }
    // Liveness probe parity: a widget whose C++ side is gone unregisters
    // here and never enters render()/setStyleSheet (teardown safety).
    const auto guard = guards_.find(widget);
    if (guard == guards_.end() || guard->second.isNull()) {
        unregister(widget);
        return;
    }
    QString sheet;
    try {
        sheet = it->second();
    } catch (...) {
        unregister(widget);
        return;
    }
    if (sheet.isNull()) {
        return;  // metrics-only registration
    }
    widget->setStyleSheet(sheet);
}

void StyleRegistry::unregister(QWidget* widget) {
    registry_.erase(widget);
    guards_.erase(widget);
}

StyleRegistry& style_registry() {
    static StyleRegistry registry;
    return registry;
}

void style_bind(QWidget* widget, std::function<QString()> render) {
    style_registry().bind(widget, std::move(render));
}

void style_refresh(QWidget* widget) {
    style_registry().refresh(widget);
}

void style_bind_metrics(QWidget* widget, std::function<void()> apply_fn) {
    style_registry().bind_metrics(widget, std::move(apply_fn));
}

void style_track_control_height(QWidget* widget) {
    style_registry().track_control_height(widget);
}

Palette style_palette() {
    return style_registry().palette();
}

}  // namespace pwb::ui_shell
