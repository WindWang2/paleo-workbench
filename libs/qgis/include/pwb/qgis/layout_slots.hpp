#pragma once

// PWB layout slots — Paleo domain semantics attached to *native* QGIS layout
// items (qgis-native-layout-convergence docs/01 §"slot 语义").
//
// QGIS 4.2 has no per-item custom properties (custom properties live on
// QgsLayout), so slots are stored as a single layout-level custom property
// `pwb/item_slots` holding a JSON object keyed by item uuid. The payload
// round-trips through QgsPrintLayout::writeLayoutXml/readLayoutXml like any
// layout custom property, so slot semantics persist with the layout itself.
//
// A slot record never duplicates geometry/z/visibility/lock — those stay
// owned by QgsLayoutItem. It carries only what QGIS cannot express:
// the semantic role, the originating geological template, and the domain
// data binding.

#include <pwb/domain/json.hpp>

#include <QString>

#include <optional>
#include <string>
#include <vector>

class QgsLayout;
class QgsLayoutItem;

namespace pwb::qgis {

// Vocabulary of semantic slots used by the geological templates. Stable
// strings; persisted in documents — extend, never rename.
inline constexpr const char* kLayoutSlotsProperty = "pwb/item_slots";
inline constexpr const char* kSlotKey = "slot";
inline constexpr const char* kTemplateIdKey = "template_id";
inline constexpr const char* kDomainRoleKey = "domain_role";
inline constexpr const char* kBindingIdKey = "binding_id";
inline constexpr const char* kSlotPropertiesKey = "properties";
inline constexpr const char* kLayoutTemplateIdProperty = "pwb/template_id";
inline constexpr const char* kLayoutTemplateCategoryProperty = "pwb/template_category";
inline constexpr const char* kLayoutLegacyIdProperty = "pwb/legacy_composition_id";

struct ItemSlot {
    std::string slot;         // e.g. "main_map", "factor_legend", "title"
    std::string template_id;  // originating geological template
    std::string domain_role;  // e.g. "statistics_chart", "provenance_footer"
    std::string binding_id;   // data binding key (may be empty)
    domain::Json properties = domain::Json::object();  // QGIS-inexpressible extras
};

// Attaches (or replaces) the slot record for `item` on `layout`.
void attach_item_slot(QgsLayout* layout, const QgsLayoutItem* item,
                      const ItemSlot& slot);

// Removes the slot record for `item`; returns true when one existed.
bool detach_item_slot(QgsLayout* layout, const QgsLayoutItem* item);

// Returns the slot record for `item`, or nullopt when the item carries none.
std::optional<ItemSlot> item_slot(const QgsLayout* layout,
                                  const QgsLayoutItem* item);

// All slot records on the layout, keyed by item uuid.
std::vector<std::pair<QString, ItemSlot>> all_item_slots(const QgsLayout* layout);

// Convenience: the item holding `slot_name` (first match in scene order),
// or nullptr. Item-level lookup by uuid against `pwb/item_slots`.
QgsLayoutItem* item_for_slot(QgsLayout* layout, const std::string& slot_name);

// Template metadata carried by the whole layout (custom properties).
void set_layout_template_metadata(QgsLayout* layout, const std::string& template_id,
                                  const std::string& template_category);
std::string layout_template_id(const QgsLayout* layout);

}  // namespace pwb::qgis
