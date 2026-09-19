#include <pwb/ui_pages_preview/qt/preview_settings_store.hpp>

#include <QVariant>

#include <pwb/platform_services/settings_service.hpp>

namespace pwb::ui_pages_preview {

const QString& PreviewSettingsStore::group_key() {
    static const QString key = QStringLiteral("preview/settings");
    return key;
}

PreviewSettingsStore::PreviewSettingsStore(QSettings* qsettings) {
    if (qsettings != nullptr) {
        settings_ = qsettings;
    } else {
        owned_ = std::make_unique<QSettings>(
            pwb::platform_services::settings_organization(),
            pwb::platform_services::settings_application());
        settings_ = owned_.get();
    }
}

PreviewSettings PreviewSettingsStore::load() const {
    const PreviewSettings defaults = PreviewSettings::defaults();
    domain::Json values = domain::Json::object();
    settings_->beginGroup(group_key());
    // Field-wise read: QVariant is typed, so QSettings.value(key, default)
    // coerces the same way the Python store does (bool/int/str fields).
    const domain::Json default_map = defaults.to_mapping();
    for (const std::string& name : preview_settings_fields()) {
        const QString key = QString::fromStdString(name);
        const domain::Json& def = default_map.at(name);
        QVariant raw;
        if (def.is_boolean()) {
            raw = settings_->value(key, def.get<bool>());
        } else if (def.is_number_integer() || def.is_number_unsigned()) {
            raw = settings_->value(key, static_cast<int>(def.get<long long>()));
        } else {
            raw = settings_->value(key,
                                   QString::fromStdString(def.get<std::string>()));
        }
        // QVariant -> Json for from_mapping coercion. QSettings may return
        // strings ("true", "42") from INI backends — Python's QSettings
        // typed-value semantics keep the declared default's type, and
        // from_mapping then validates strictly.
        if (def.is_boolean()) {
            values[name] = raw.toBool();
        } else if (def.is_number_integer() || def.is_number_unsigned()) {
            values[name] = raw.toInt();
        } else {
            values[name] = raw.toString().toStdString();
        }
    }
    settings_->endGroup();
    try {
        return PreviewSettings::from_mapping(values);
    } catch (const std::invalid_argument&) {
        return defaults;
    }
}

void PreviewSettingsStore::save(const PreviewSettings& settings) {
    settings_->beginGroup(group_key());
    const domain::Json map = settings.to_mapping();
    for (const std::string& name : preview_settings_fields()) {
        const QString key = QString::fromStdString(name);
        const domain::Json& v = map.at(name);
        if (v.is_boolean()) {
            settings_->setValue(key, v.get<bool>());
        } else if (v.is_number_integer() || v.is_number_unsigned()) {
            settings_->setValue(key, static_cast<int>(v.get<long long>()));
        } else {
            settings_->setValue(key,
                                QString::fromStdString(v.get<std::string>()));
        }
    }
    settings_->endGroup();
    settings_->sync();
}

PreviewSettings PreviewSettingsStore::reset() {
    settings_->remove(group_key());
    settings_->sync();
    return PreviewSettings::defaults();
}

}  // namespace pwb::ui_pages_preview
