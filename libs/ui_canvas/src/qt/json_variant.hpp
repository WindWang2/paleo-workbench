#pragma once

// UI-15 internal — Json → QVariant conversion shared by the Qt TUs in
// this target (unified_map_canvas.cpp, map_export_worker.cpp). The map
// chrome helpers consume QVariantMap; the frozen decorations vocabulary
// is a Json dict — this is the single bridge.
//
// Not installed: private to pwb_ui_canvas_qt.

#include <QMetaType>
#include <QVariant>
#include <QVariantList>
#include <QVariantMap>

#include <pwb/domain/json.hpp>

namespace pwb::ui_canvas::qt::detail {

using Json = pwb::domain::Json;

inline QVariant json_to_variant(const Json& value) {
    if (value.is_null()) {
        return {};
    }
    if (value.is_boolean()) {
        return value.get<bool>();
    }
    if (value.is_number_integer()) {
        return static_cast<qlonglong>(value.get<long long>());
    }
    if (value.is_number_unsigned()) {
        return static_cast<qulonglong>(value.get<unsigned long long>());
    }
    if (value.is_number()) {
        return value.get<double>();
    }
    if (value.is_string()) {
        return QString::fromStdString(value.get<std::string>());
    }
    if (value.is_array()) {
        QVariantList list;
        list.reserve(static_cast<qsizetype>(value.size()));
        for (const Json& entry : value) {
            list.append(json_to_variant(entry));
        }
        return list;
    }
    if (value.is_object()) {
        QVariantMap map;
        for (auto it = value.begin(); it != value.end(); ++it) {
            map.insert(QString::fromStdString(it.key()),
                       json_to_variant(it.value()));
        }
        return map;
    }
    return {};
}

inline QVariantMap json_to_variant_map(const Json& value) {
    const QVariant variant = json_to_variant(value);
    return variant.metaType().id() == QMetaType::QVariantMap
               ? variant.toMap()
               : QVariantMap{};
}

}  // namespace pwb::ui_canvas::qt::detail
