#include <pwb/ui_composite/composite_controller_qt.hpp>

#include <pwb/ui_composite/composite_controller.hpp>

#include <QVariantMap>

namespace pwb::ui_composite {

namespace {

QVariant json_to_variant(const Json& value) {
    if (value.is_null()) return {};
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_number_integer()) {
        return QVariant::fromValue<qlonglong>(value.get<long long>());
    }
    if (value.is_number_unsigned()) {
        return QVariant::fromValue<qulonglong>(value.get<unsigned long long>());
    }
    if (value.is_number_float()) return value.get<double>();
    if (value.is_string()) {
        return QString::fromStdString(value.get<std::string>());
    }
    if (value.is_array()) {
        QVariantList list;
        for (const Json& entry : value) list.append(json_to_variant(entry));
        return list;
    }
    if (value.is_object()) {
        QVariantMap map;
        for (auto it = value.begin(); it != value.end(); ++it) {
            map[QString::fromStdString(it.key())] = json_to_variant(it.value());
        }
        return map;
    }
    return {};
}

}  // namespace

CompositeEditControllerObject::CompositeEditControllerObject(
    CompositeEditController* core, QObject* parent)
    : QObject(parent), core_(core) {
    if (core_ == nullptr) return;
    core_->events.layers_changed = [this]() { emit layers_changed(); };
    core_->events.content_changed = [this](const std::string& layer_id) {
        emit content_changed(QString::fromStdString(layer_id));
    };
    core_->events.sessions_committed = [this]() {
        emit sessions_committed();
    };
    core_->events.native_join_refused = [this](const std::string& message) {
        emit native_join_refused(QString::fromStdString(message));
    };
    core_->events.geology_blocked = [this](const Json& violations) {
        emit geology_blocked(json_to_variant(violations).toList());
    };
    core_->events.feature_captured =
        [this](const std::string& layer_id,
               const std::string& feature_id) {
            emit feature_captured(QString::fromStdString(layer_id),
                                  QString::fromStdString(feature_id));
        };
    core_->events.state_changed = [this]() { emit state_changed(); };
}

}  // namespace pwb::ui_composite
