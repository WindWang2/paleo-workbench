#include "pwb/ui_shell/layout_persistence.hpp"

#include <QLoggingCategory>
#include <QStringList>

namespace pwb::ui_shell {

namespace {
Q_LOGGING_CATEGORY(lcLayout, "pwb.ui_shell.layout")

constexpr const char* kWindowStateKey = "layout/window_state";
constexpr const char* kStateVersionKey = "layout/state_version";
constexpr const char* kInspectorFlagKey = "layout/inspector_user_hidden";
// Legacy shell identity (WorkstationV3) window-state key.
constexpr const char* kLegacyShellApp = "WorkstationV3";
constexpr const char* kLegacyWindowStateKey = "layout/windowState.v4";
// Legacy panel-floating persistence identity.
constexpr const char* kLegacyPanelsApp = "paleo-workbench";

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}
}  // namespace

bool migrate_legacy_layout_settings() {
    bool migrated = false;
    QSettings target(QString::fromLatin1(kSettingsOrg),
                     QString::fromLatin1(kSettingsApp));

    // (PaleoWorkbench, WorkstationV3) window state + inspector flag.
    QSettings legacy_shell(QString::fromLatin1(kSettingsOrg),
                           QString::fromLatin1(kLegacyShellApp));
    legacy_shell.sync();
    const QVariant state = legacy_shell.value(QLatin1String(kLegacyWindowStateKey));
    if (state.isValid()) {
        if (!target.contains(QLatin1String(kWindowStateKey))) {
            target.setValue(QLatin1String(kWindowStateKey), state);
        }
        const QVariant inspector_hidden =
            legacy_shell.value(QLatin1String(kInspectorFlagKey));
        if (inspector_hidden.isValid()) {
            target.setValue(QLatin1String(kInspectorFlagKey), inspector_hidden);
        }
        target.setValue(QLatin1String(kStateVersionKey), kLayoutStateVersion);
        legacy_shell.remove(QLatin1String(kLegacyWindowStateKey));
        legacy_shell.remove(QLatin1String(kInspectorFlagKey));
        migrated = true;
    }

    // (PaleoWorkbench, paleo-workbench) panel_layout group.
    QSettings legacy_panels(QString::fromLatin1(kSettingsOrg),
                            QString::fromLatin1(kLegacyPanelsApp));
    legacy_panels.sync();
    legacy_panels.beginGroup(QStringLiteral("panel_layout"));
    const QStringList keys = legacy_panels.allKeys();
    for (const QString& key : keys) {
        // Read inside the group, write outside: new keys keep the
        // panel_layout/… prefix unchanged.
        target.setValue(QStringLiteral("panel_layout/") + key,
                        legacy_panels.value(key));
    }
    legacy_panels.endGroup();
    if (!keys.isEmpty()) {
        legacy_panels.remove(QStringLiteral("panel_layout"));
        migrated = true;
    }

    if (migrated) {
        target.sync();
        qCInfo(lcLayout,
               "migrated legacy layout settings into (%s, %s)", kSettingsOrg,
               kSettingsApp);
    }
    return migrated;
}

LayoutPersistence::LayoutPersistence(QSettings* settings)
    : settings_(settings) {}

void LayoutPersistence::save_float(const std::string& key,
                                   const QRect& geometry) {
    QSettings& settings = bind();
    settings.beginGroup(group_for(key));
    settings.setValue(QStringLiteral("floating"), true);
    settings.setValue(QStringLiteral("visible"), true);
    settings.setValue(QStringLiteral("geometry"),
                      QStringLiteral("%1,%2,%3,%4")
                          .arg(geometry.x())
                          .arg(geometry.y())
                          .arg(geometry.width())
                          .arg(geometry.height()));
    settings.endGroup();
    settings.sync();
}

void LayoutPersistence::save_dock(const std::string& key,
                                  const std::vector<int>& sizes) {
    QSettings& settings = bind();
    settings.beginGroup(group_for(key));
    settings.setValue(QStringLiteral("floating"), false);
    settings.setValue(QStringLiteral("visible"), true);
    settings.setValue(QStringLiteral("docked_sizes"), encode_sizes(sizes));
    settings.endGroup();
    settings.sync();
}

void LayoutPersistence::save_docked_sizes(const std::string& key,
                                          const std::vector<int>& sizes) {
    QSettings& settings = bind();
    settings.setValue(group_for(key) + QStringLiteral("/docked_sizes"),
                      encode_sizes(sizes));
    settings.sync();
}

void LayoutPersistence::save_visibility(const std::string& key,
                                        bool visible) {
    QSettings& settings = bind();
    settings.setValue(group_for(key) + QStringLiteral("/visible"), visible);
    settings.sync();
}

void LayoutPersistence::clear(const std::string& key) {
    QSettings& settings = bind();
    settings.remove(group_for(key));
    settings.sync();
}

PanelLayoutRecord LayoutPersistence::load(const std::string& key) const {
    // QSettings::beginGroup/endGroup are non-const even for reads — bind
    // non-const (the store is logically mutable state anyway).
    QSettings& settings =
        const_cast<LayoutPersistence*>(this)->bind();
    settings.beginGroup(group_for(key));
    PanelLayoutRecord record;
    record.floating = settings.value(QStringLiteral("floating"), false).toBool();
    record.visible = settings.value(QStringLiteral("visible"), true).toBool();
    record.geometry =
        parse_geometry(settings.value(QStringLiteral("geometry")).toString());
    record.docked_sizes =
        parse_sizes(settings.value(QStringLiteral("docked_sizes")).toString());
    settings.endGroup();
    return record;
}

QSettings& LayoutPersistence::bind() {
    if (settings_ != nullptr) {
        return *settings_;
    }
    if (owned_ == nullptr) {
        // One-shot legacy migration before the default backend binds — an
        // isolated LayoutPersistence (no workstation shell) still reads the
        // old panel layout.
        migrate_legacy_layout_settings();
        owned_ = std::make_unique<QSettings>(
            QString::fromLatin1(kSettingsOrg),
            QString::fromLatin1(kSettingsApp));
    }
    return *owned_;
}

const QSettings& LayoutPersistence::bind() const {
    return const_cast<LayoutPersistence*>(this)->bind();
}

QString LayoutPersistence::group_for(const std::string& key) {
    return QStringLiteral("panel_layout/") + qstr(key);
}

QString LayoutPersistence::encode_sizes(const std::vector<int>& sizes) {
    QStringList parts;
    parts.reserve(static_cast<qsizetype>(sizes.size()));
    for (const int size : sizes) {
        parts.push_back(QString::number(size));
    }
    return parts.join(QLatin1Char(','));
}

std::optional<QRect> LayoutPersistence::parse_geometry(const QString& raw) {
    const QStringList parts = raw.split(QLatin1Char(','), Qt::SkipEmptyParts);
    if (parts.size() != 4) {
        return std::nullopt;
    }
    bool ok = false;
    const int x = parts[0].toInt(&ok);
    if (!ok) return std::nullopt;
    const int y = parts[1].toInt(&ok);
    if (!ok) return std::nullopt;
    const int w = parts[2].toInt(&ok);
    if (!ok) return std::nullopt;
    const int h = parts[3].toInt(&ok);
    if (!ok) return std::nullopt;
    return QRect(x, y, w, h);
}

std::optional<std::vector<int>> LayoutPersistence::parse_sizes(
    const QString& raw) {
    const QStringList parts = raw.split(QLatin1Char(','), Qt::SkipEmptyParts);
    if (parts.isEmpty()) {
        return std::nullopt;
    }
    std::vector<int> out;
    out.reserve(parts.size());
    for (const QString& part : parts) {
        bool ok = false;
        const int value = part.toInt(&ok);
        if (!ok) {
            return std::nullopt;
        }
        out.push_back(value);
    }
    return out;
}

}  // namespace pwb::ui_shell
