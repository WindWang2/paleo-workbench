#include <pwb/platform_services/settings_service.hpp>

#include <QByteArray>
#include <QRect>
#include <QScreen>
#include <QGuiApplication>

#include <algorithm>

namespace pwb::platform_services {
namespace {

// Resolves the live screen set and delegates (panel_float_controller.py
// clamp_geometry_to_screens contract).
QRect clamp_geometry_to_screens(const QRect& geometry) {
    const QList<QScreen*> screens = QGuiApplication::screens();
    if (screens.isEmpty()) return geometry;
    QList<QRect> available;
    for (const QScreen* screen : screens) {
        available.append(screen->availableGeometry());
    }
    const QScreen* primary = QGuiApplication::primaryScreen();
    const QRect primary_rect =
        primary != nullptr ? primary->availableGeometry()
                           : available.first();
    return clamp_to_desktop(geometry, available, primary_rect);
}

QStringList load_string_list(QSettings& settings, const QString& key,
                             int cap) {
    // QSettings value coercion: a single stored string must still yield a
    // one-element list (command_registry.py load_recent).
    const QVariant stored = settings.value(key);
    QStringList items;
    if (stored.typeId() == QMetaType::QStringList
        || stored.typeId() == QMetaType::QVariantList) {
        items = stored.toStringList();
    } else if (stored.isValid() && !stored.isNull()) {
        const QString single = stored.toString();
        if (!single.isEmpty()) items.append(single);
    }
    // DELIBERATE DIFFERENCE vs command_registry.py: stored empty strings
    // are dropped instead of kept (only reachable via a hand-edited store;
    // both push paths already reject empties).
    QStringList cleaned;
    for (const QString& item : items) {
        if (!item.isEmpty()) cleaned.append(item);
    }
    if (cleaned.size() > cap) {
        cleaned.erase(cleaned.begin() + cap, cleaned.end());
    }
    return cleaned;
}

void push_string_list(QSettings& settings, const QString& key, int cap,
                      const QString& value) {
    QStringList items = load_string_list(settings, key, cap);
    items.removeAll(value);
    items.prepend(value);
    while (items.size() > cap) items.removeLast();
    settings.setValue(key, items);
    settings.sync();
}

}  // namespace

QRect clamp_to_desktop(const QRect& geometry, const QList<QRect>& screens,
                       const QRect& primary) {
    if (screens.isEmpty()) return geometry;
    QRect visible = screens.first();
    for (const QRect& screen : screens) {
        visible = visible.united(screen);
    }
    if (!geometry.intersects(visible)) {
        const QSize size = geometry.size().boundedTo(primary.size());
        return QRect(primary.x() + 24, primary.y() + 24, size.width(),
                     size.height());
    }
    const int x = std::min(std::max(geometry.x(), visible.left()),
                           std::max(visible.left(), visible.right() - 60));
    const int y = std::min(std::max(geometry.y(), visible.top()),
                           std::max(visible.top(), visible.bottom() - 60));
    return QRect(x, y, geometry.width(), geometry.height());
}

QString settings_organization() { return QStringLiteral("PaleoWorkbench"); }
QString settings_application() { return QStringLiteral("Workstation"); }

const QString LayoutKeys::window_state = QStringLiteral("layout/window_state");
const QString LayoutKeys::window_geometry =
    QStringLiteral("layout/window_geometry");
const QString LayoutKeys::state_version =
    QStringLiteral("layout/state_version");
const QString LayoutKeys::inspector_hidden =
    QStringLiteral("layout/inspector_user_hidden");
const QString LayoutKeys::panel_group = QStringLiteral("panel_layout");
const QString LayoutKeys::recent_commands =
    QStringLiteral("ui/recent_commands");
const QString LayoutKeys::recent_projects = QStringLiteral("projects/recent");

bool migrate_legacy_layout_settings(QSettings& target) {
    bool migrated = false;

    // (PaleoWorkbench, WorkstationV3): window state v4 + inspector flag.
    {
        QSettings legacy_shell(settings_organization(),
                               QStringLiteral("WorkstationV3"));
        legacy_shell.sync();
        const QVariant state = legacy_shell.value(
            QStringLiteral("layout/windowState.v4"));
        if (state.isValid() && !state.isNull()) {
            if (!target.contains(LayoutKeys::window_state)) {
                target.setValue(LayoutKeys::window_state, state);
            }
            const QVariant inspector = legacy_shell.value(
                LayoutKeys::inspector_hidden);
            if (inspector.isValid() && !inspector.isNull()) {
                target.setValue(LayoutKeys::inspector_hidden, inspector);
            }
            target.setValue(LayoutKeys::state_version, kLayoutStateVersion);
            legacy_shell.remove(QStringLiteral("layout/windowState.v4"));
            legacy_shell.remove(LayoutKeys::inspector_hidden);
            migrated = true;
        }
    }

    // (PaleoWorkbench, paleo-workbench): the whole panel_layout group keeps
    // its key prefix under the new identity.
    {
        QSettings legacy_panels(settings_organization(),
                                QStringLiteral("paleo-workbench"));
        legacy_panels.sync();
        legacy_panels.beginGroup(LayoutKeys::panel_group);
        // allKeys() inside the group yields every leaf with its in-group
        // path ("panel_layout/a/b" -> "a/b"), so nested groups keep their
        // key prefix under the new identity.
        const QStringList keys = legacy_panels.allKeys();
        for (const QString& key : keys) {
            target.setValue(LayoutKeys::panel_group + QLatin1Char('/') + key,
                            legacy_panels.value(key));
        }
        legacy_panels.endGroup();
        if (!keys.isEmpty()) {
            legacy_panels.remove(LayoutKeys::panel_group);
            migrated = true;
        }
    }

    if (migrated) {
        target.sync();
    }
    return migrated;
}

void migrate_legacy_settings() {
    QSettings target(settings_organization(), settings_application());
    migrate_legacy_layout_settings(target);
}

void save_window_layout(QSettings& settings, QMainWindow& window,
                        bool force) {
    if (!window.isVisible() && !force) return;
    // NOTE: layout/inspector_user_hidden is intentionally NOT written —
    // the native shell has no inspector; a constant false would clobber a
    // Python-written true on the shared store (Python's restore self-heals
    // a missing flag, shell.py _restore_inspector_visibility).
    settings.setValue(LayoutKeys::state_version, kLayoutStateVersion);
    settings.setValue(LayoutKeys::window_state, window.saveState());
    if (window.isVisible()) {
        settings.setValue(LayoutKeys::window_geometry, window.saveGeometry());
    }
    settings.sync();
}

void restore_window_layout(QSettings& settings, QMainWindow& window) {
    const QVariant data = settings.value(LayoutKeys::window_state);
    if (!data.isValid() || data.isNull()) return;
    const QVariant version = settings.value(LayoutKeys::state_version, 0);
    bool version_ok = false;
    const int stored_version = version.toInt(&version_ok);
    // Unknown version (older, missing, or from a newer app): the restore
    // contract cannot be guaranteed — discard and keep the default layout.
    if (!version_ok || stored_version != kLayoutStateVersion) return;

    const QByteArray state = data.toByteArray();
    if (!state.isEmpty()) {
        window.restoreState(state);
    }
    const QVariant geometry = settings.value(LayoutKeys::window_geometry);
    if (geometry.isValid() && !geometry.isNull()) {
        window.restoreGeometry(geometry.toByteArray());
        if (window.isMaximized() || window.isFullScreen()) return;
        const QRect clamped = clamp_geometry_to_screens(window.geometry());
        if (clamped != window.geometry()) {
            window.setGeometry(clamped);
        }
    }
}

QStringList load_recent_commands(QSettings& settings) {
    return load_string_list(settings, LayoutKeys::recent_commands,
                            kRecentCommandsMax);
}

void push_recent_command(QSettings& settings, const QString& command_id) {
    if (command_id.isEmpty()) return;
    push_string_list(settings, LayoutKeys::recent_commands,
                     kRecentCommandsMax, command_id);
}

QStringList load_recent_projects(QSettings& settings) {
    return load_string_list(settings, LayoutKeys::recent_projects,
                            kRecentProjectsMax);
}

void push_recent_project(QSettings& settings, const QString& path) {
    if (path.isEmpty()) return;
    push_string_list(settings, LayoutKeys::recent_projects,
                     kRecentProjectsMax, path);
}

void clear_recent_projects(QSettings& settings) {
    settings.remove(LayoutKeys::recent_projects);
    settings.sync();
}

}  // namespace pwb::platform_services
