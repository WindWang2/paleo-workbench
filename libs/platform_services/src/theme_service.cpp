#include <pwb/platform_services/theme_service.hpp>

#include <QApplication>
#include <QWidget>

#include <memory>

namespace pwb::platform_services {

const QString ThemeService::organization() {
    return QStringLiteral("PaleoWorkbench");
}

const QString ThemeService::application() {
    return QStringLiteral("Workstation");
}

const QString ThemeService::theme_key() {
    return QStringLiteral("ui/theme");
}

const QString ThemeService::density_key() {
    return QStringLiteral("ui/density");
}

ThemeService::ThemeService(QObject* parent) : QObject(parent) {}

void ThemeService::set_store(QSettings* store) { store_ = store; }

void ThemeService::set_theme(ThemeMode mode) {
    if (mode == theme_) return;  // Python manager: unchanged value -> no emit
    theme_ = mode;
    emit_and_persist();
}

void ThemeService::set_density(Density density) {
    if (density == density_) return;
    density_ = density;
    emit_and_persist();
}

void ThemeService::toggle_density() {
    density_ = density_ == Density::Compact ? Density::Comfortable
                                            : Density::Compact;
    emit_and_persist();
}

void ThemeService::load_persisted(QSettings& settings) {
    const QString theme = settings.value(theme_key()).toString();
    if (!theme.isEmpty()) {
        theme_ = theme_from_string(theme.toStdString());
    }
    const QString density = settings.value(density_key()).toString();
    if (!density.isEmpty()) {
        density_ = density_from_string(density.toStdString());
    }
}

QString ThemeService::stylesheet() const {
    return QString::fromStdString(build_platform_qss(theme_, density_));
}

void ThemeService::apply(QWidget& shell) {
    shell.setStyleSheet(stylesheet());
}

void ThemeService::emit_and_persist() {
    emit theme_changed(QString::fromStdString(to_string(theme_)),
                       QString::fromStdString(to_string(density_)));
    // Best-effort persistence: an unbound/unwritable store must never take
    // the shell down at startup or on a theme click.
    QSettings* settings = store_;
    std::unique_ptr<QSettings> default_store;
    if (settings == nullptr) {
        if (QCoreApplication::instance() == nullptr) return;
        default_store = std::make_unique<QSettings>(organization(),
                                                    application());
        settings = default_store.get();
    }
    settings->setValue(theme_key(), QString::fromStdString(to_string(theme_)));
    settings->setValue(density_key(),
                       QString::fromStdString(to_string(density_)));
    settings->sync();
}

}  // namespace pwb::platform_services
