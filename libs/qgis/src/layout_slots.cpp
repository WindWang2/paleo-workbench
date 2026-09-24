// layout_slots — implementation (see header for the storage contract:
// one layout-level custom property `pwb/item_slots`, JSON keyed by uuid).

#include <pwb/qgis/layout_slots.hpp>

#include <qgslayout.h>
#include <qgslayoutitem.h>

#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QString>
#include <QVariant>

#include <stdexcept>

namespace pwb::qgis {

namespace {

QJsonObject read_slot_map(const QgsLayout* layout) {
    const QVariant raw =
        layout->customProperty(kLayoutSlotsProperty, QVariant());
    const QString text = raw.toString();
    if (text.isEmpty()) return {};
    const QJsonDocument doc = QJsonDocument::fromJson(text.toUtf8());
    return doc.object();
}

QString write_slot_map(const QgsLayout* layout, const QJsonObject& map) {
    const QString text = QString::fromUtf8(
        QJsonDocument(map).toJson(QJsonDocument::Compact));
    const_cast<QgsLayout*>(layout)->setCustomProperty(kLayoutSlotsProperty, text);
    return text;
}

domain::Json to_domain_json(const QJsonObject& object) {
    return domain::Json::parse(
        QString::fromUtf8(QJsonDocument(object).toJson(QJsonDocument::Compact))
            .toStdString());
}

QJsonObject from_domain_json(const domain::Json& json) {
    return QJsonDocument::fromJson(
               QByteArray::fromStdString(json.dump()))
        .object();
}

QJsonObject slot_to_json(const ItemSlot& slot) {
    QJsonObject object;
    object.insert(QLatin1String(kSlotKey), QString::fromStdString(slot.slot));
    object.insert(QLatin1String(kTemplateIdKey),
                  QString::fromStdString(slot.template_id));
    object.insert(QLatin1String(kDomainRoleKey),
                  QString::fromStdString(slot.domain_role));
    object.insert(QLatin1String(kBindingIdKey),
                  QString::fromStdString(slot.binding_id));
    object.insert(QLatin1String(kSlotPropertiesKey),
                  from_domain_json(slot.properties));
    return object;
}

ItemSlot slot_from_json(const QJsonObject& object) {
    ItemSlot slot;
    slot.slot = object.value(QLatin1String(kSlotKey)).toString().toStdString();
    slot.template_id =
        object.value(QLatin1String(kTemplateIdKey)).toString().toStdString();
    slot.domain_role =
        object.value(QLatin1String(kDomainRoleKey)).toString().toStdString();
    slot.binding_id =
        object.value(QLatin1String(kBindingIdKey)).toString().toStdString();
    slot.properties = to_domain_json(
        object.value(QLatin1String(kSlotPropertiesKey)).toObject());
    return slot;
}

}  // namespace

void attach_item_slot(QgsLayout* layout, const QgsLayoutItem* item,
                      const ItemSlot& slot) {
    if (layout == nullptr || item == nullptr) return;
    QJsonObject map = read_slot_map(layout);
    map.insert(item->uuid(), slot_to_json(slot));
    write_slot_map(layout, map);
}

bool detach_item_slot(QgsLayout* layout, const QgsLayoutItem* item) {
    if (layout == nullptr || item == nullptr) return false;
    QJsonObject map = read_slot_map(layout);
    if (!map.contains(item->uuid())) return false;
    map.remove(item->uuid());
    write_slot_map(layout, map);
    return true;
}

std::optional<ItemSlot> item_slot(const QgsLayout* layout,
                                  const QgsLayoutItem* item) {
    if (layout == nullptr || item == nullptr) return std::nullopt;
    const QJsonObject map = read_slot_map(layout);
    const QJsonValue value = map.value(item->uuid());
    if (!value.isObject()) return std::nullopt;
    return slot_from_json(value.toObject());
}

std::vector<std::pair<QString, ItemSlot>> all_item_slots(const QgsLayout* layout) {
    std::vector<std::pair<QString, ItemSlot>> out;
    if (layout == nullptr) return out;
    const QJsonObject map = read_slot_map(layout);
    for (auto it = map.begin(); it != map.end(); ++it) {
        if (it.value().isObject()) {
            out.emplace_back(it.key(), slot_from_json(it.value().toObject()));
        }
    }
    return out;
}

QgsLayoutItem* item_for_slot(QgsLayout* layout, const std::string& slot_name) {
    if (layout == nullptr) return nullptr;
    const QJsonObject map = read_slot_map(layout);
    if (map.isEmpty()) return nullptr;
    QList<QgsLayoutItem*> items;
    layout->layoutItems(items);
    for (QgsLayoutItem* candidate : items) {
        const QJsonValue value = map.value(candidate->uuid());
        if (!value.isObject()) continue;
        if (slot_from_json(value.toObject()).slot == slot_name) return candidate;
    }
    return nullptr;
}

void set_layout_template_metadata(QgsLayout* layout,
                                  const std::string& template_id,
                                  const std::string& template_category) {
    if (layout == nullptr) return;
    layout->setCustomProperty(kLayoutTemplateIdProperty,
                              QString::fromStdString(template_id));
    layout->setCustomProperty(kLayoutTemplateCategoryProperty,
                              QString::fromStdString(template_category));
}

std::string layout_template_id(const QgsLayout* layout) {
    if (layout == nullptr) return {};
    return layout->customProperty(kLayoutTemplateIdProperty, QVariant())
        .toString()
        .toStdString();
}

}  // namespace pwb::qgis
