// LayoutAuthority — implementation (see header for the contract).

#include <pwb/qgis/layout_authority.hpp>

#include <pwb/mapping_document/composer_templates.hpp>
#include <pwb/mapping_document/composition.hpp>
#include <pwb/qgis/layout_materializer.hpp>
#include <pwb/qgis/layout_slots.hpp>
#include <pwb/qgis/layout_slot_item.hpp>

#include <qgslayout.h>
#include <qgslayoutitem.h>
#include <qgslayoutitemmap.h>
#include <qgslayoutitempage.h>
#include <qgslayoutmanager.h>
#include <qgslayoutpagecollection.h>
#include <qgslayoutundostack.h>
#include <qgsprintlayout.h>
#include <qgsproject.h>
#include <qgsreadwritecontext.h>
#include <qgsrectangle.h>

#include <QDomDocument>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSet>
#include <QString>
#include <QUndoStack>
#include <QVariant>

#include <algorithm>
#include <cmath>

namespace pwb::qgis {

namespace {

using domain::Json;

QgsLayoutManager* manager_for(const MapSession& session) {
    QgsProject* project = session.project();
    return project == nullptr ? nullptr : project->layoutManager();
}

void set_page(QgsPrintLayout& layout, double width_mm, double height_mm) {
    QgsLayoutItemPage* page = layout.pageCollection()->page(0);
    page->setPageSize(
        QgsLayoutSize(width_mm, height_mm, Qgis::LayoutUnit::Millimeters));
}

// Canvas-state seed: the live map view the exported map should match
// (Phase 8 — layout map and canvas consume the same layers/extent).
struct MapSeed {
    std::optional<std::array<double, 4>> extent;
    std::string crs;
};

MapSeed canvas_seed(const MapSession& session) {
    MapSeed seed;
    const std::string state_json = session.canvas_state_json();
    try {
        const Json state = Json::parse(state_json);
        if (const auto it = state.find("extent");
            it != state.end() && it->is_array() && it->size() == 4) {
            std::array<double, 4> extent{};
            bool finite = true;
            for (std::size_t i = 0; i < 4; ++i) {
                const Json& v = (*it)[i];
                if (!v.is_number() || !std::isfinite(v.get<double>())) {
                    finite = false;
                    break;
                }
                extent[i] = v.get<double>();
            }
            if (finite && extent[0] < extent[2] && extent[1] < extent[3]) {
                seed.extent = extent;
            }
        }
        if (const auto it = state.find("crs");
            it != state.end() && it->is_string()) {
            seed.crs = it->get<std::string>();
        }
    } catch (const std::exception&) {
        // Malformed canvas state — fall back to layer-union defaults.
    }
    return seed;
}

QJsonObject read_slot_map_public(const QgsLayout* layout) {
    const QVariant raw =
        layout->customProperty(kLayoutSlotsProperty, QVariant());
    const QString text = raw.toString();
    if (text.isEmpty()) return {};
    return QJsonDocument::fromJson(text.toUtf8()).object();
}

}  // namespace

LayoutAuthority::LayoutAuthority(MapSession& session) : session_(session) {}

std::string LayoutAuthority::unique_layout_name(const std::string& base) const {
    const QgsLayoutManager* manager = manager_for(session_);
    const std::string stem = base.empty() ? std::string("布局") : base;
    std::string candidate = stem;
    int suffix = 2;
    while (manager != nullptr &&
           manager->layoutByName(QString::fromStdString(candidate)) != nullptr) {
        candidate = stem + " " + std::to_string(suffix++);
    }
    return candidate;
}

QgsPrintLayout* LayoutAuthority::register_layout(
    std::unique_ptr<QgsPrintLayout> layout, const std::string& name) {
    QgsLayoutManager* manager = manager_for(session_);
    if (manager == nullptr || layout == nullptr) return nullptr;
    layout->setName(QString::fromStdString(name));
    QgsPrintLayout* raw = layout.get();
    if (!manager->addLayout(layout.release())) {
        return nullptr;
    }
    if (auto* stack = raw->undoStack()->stack()) stack->setClean();
    return raw;
}

QgsPrintLayout* LayoutAuthority::create_layout(const std::string& name) {
    auto layout = std::make_unique<QgsPrintLayout>(session_.project());
    layout->initializeDefaults();
    set_page(*layout, 297.0, 210.0);
    return register_layout(std::move(layout), unique_layout_name(name));
}

LayoutAuthority::InstantiateReport LayoutAuthority::instantiate_template(
    const std::string& template_id, const std::string& title) {
    InstantiateReport report;
    const mapping_document::CompositionTemplate* tpl =
        mapping_document::find_composer_template(template_id);
    if (tpl == nullptr) {
        report.warnings.push_back("unknown composition template '" +
                                  template_id + "'");
        return report;
    }

    std::string canonical;
    std::pair<double, double> short_long_mm{210.0, 297.0};
    double page_w = 297.0;
    double page_h = 210.0;
    if (mapping_document::known_paper_size(tpl->paper_size, canonical,
                                           short_long_mm)) {
        if (tpl->orientation == "portrait") {
            page_w = short_long_mm.first;   // short edge
            page_h = short_long_mm.second;  // long edge
        } else {
            page_w = short_long_mm.second;
            page_h = short_long_mm.first;
        }
    }

    auto layout = std::make_unique<QgsPrintLayout>(session_.project());
    layout->initializeDefaults();
    set_page(*layout, page_w, page_h);

    MaterializeContext context;
    context.template_id = tpl->template_id;
    context.template_category = tpl->category;
    context.layers_provider = [this]() {
        QList<QgsMapLayer*> ordered;
        for (const std::string& id : session_.layerIdsTopFirst()) {
            if (QgsMapLayer* layer = session_.layerById(id)) {
                ordered.append(layer);
            }
        }
        return ordered;
    };
    const MapSeed seed = canvas_seed(session_);
    context.map_extent = seed_extent_.has_value() ? seed_extent_ : seed.extent;
    context.map_crs = seed_crs_.empty() ? seed.crs : seed_crs_;

    std::vector<LayoutElementSpec> elements;
    elements.reserve(tpl->element_definitions.size());
    for (const auto& def : tpl->element_definitions) {
        LayoutElementSpec spec;
        spec.element_type = def.element_type;
        spec.x_mm = def.x_mm;
        spec.y_mm = def.y_mm;
        spec.width_mm = def.width_mm;
        spec.height_mm = def.height_mm;
        spec.z_index = def.z_index;
        spec.properties = def.properties;
        elements.push_back(std::move(spec));
    }
    std::stable_sort(elements.begin(), elements.end(),
                     [](const LayoutElementSpec& a, const LayoutElementSpec& b) {
                         return a.z_index < b.z_index;
                     });
    // Explicit title overrides the first TITLE element (composer parity).
    if (!title.empty()) {
        for (auto& element : elements) {
            if (element.element_type == "title") {
                element.properties["text"] = title;
                break;
            }
        }
    }

    const MaterializeReport materialized =
        materialize_elements(*layout, elements, context);
    report.items = materialized.items_created;
    report.warnings = materialized.warnings;

    const std::string layout_title =
        title.empty() ? tpl->label + " 1" : title;
    report.layout = register_layout(std::move(layout),
                                    unique_layout_name(layout_title));
    if (report.layout != nullptr) {
        set_layout_template_metadata(report.layout, tpl->template_id, tpl->category);
        if (auto* stack = report.layout->undoStack()->stack()) {
            stack->setClean();
        }
    }
    return report;
}

LayoutAuthority::MigrationResult LayoutAuthority::migrate_composition(
    const domain::Json& composition_json, const std::string& preferred_name) {
    MigrationResult result;
    mapping_document::Composition doc;
    try {
        doc = mapping_document::parse_composition(composition_json);
    } catch (const std::exception& error) {
        result.warnings.push_back(std::string("composition parse failed: ") +
                                  error.what());
        return result;
    }

    // Idempotency: the legacy composition id pins the target layout.
    std::string legacy_id = doc.id.empty() ? doc.title : doc.id;
    QgsLayoutManager* manager = manager_for(session_);
    if (manager != nullptr && !legacy_id.empty()) {
        for (QgsPrintLayout* existing : manager->printLayouts()) {
            if (existing->customProperty(kLayoutLegacyIdProperty, QVariant())
                    .toString()
                    .toStdString() == legacy_id) {
                result.skipped_already_migrated = true;
                result.layout = existing;
                result.layout_name = existing->name().toStdString();
                return result;
            }
        }
    }

    std::string canonical;
    std::pair<double, double> short_long_mm{210.0, 297.0};
    double page_w = doc.width_mm > 0.0 ? doc.width_mm : 297.0;
    double page_h = doc.height_mm > 0.0 ? doc.height_mm : 210.0;
    if (mapping_document::known_paper_size(doc.paper_size, canonical,
                                           short_long_mm)) {
        if (doc.orientation == "portrait") {
            page_w = short_long_mm.first;
            page_h = short_long_mm.second;
        } else {
            page_w = short_long_mm.second;
            page_h = short_long_mm.first;
        }
    }

    auto layout = std::make_unique<QgsPrintLayout>(session_.project());
    layout->initializeDefaults();
    set_page(*layout, page_w, page_h);

    MaterializeContext context;
    std::string template_id;
    std::string template_category;
    if (const auto it = doc.metadata.find("template_id");
        it != doc.metadata.end() && it->is_string()) {
        template_id = it->get<std::string>();
    }
    if (const auto it = doc.metadata.find("template_category");
        it != doc.metadata.end() && it->is_string()) {
        template_category = it->get<std::string>();
    }
    context.template_id = template_id;
    context.template_category = template_category;
    context.layers_provider = [this]() {
        QList<QgsMapLayer*> ordered;
        for (const std::string& id : session_.layerIdsTopFirst()) {
            if (QgsMapLayer* layer = session_.layerById(id)) {
                ordered.append(layer);
            }
        }
        return ordered;
    };
    const MapSeed seed = canvas_seed(session_);
    context.map_extent = seed_extent_.has_value() ? seed_extent_ : seed.extent;
    context.map_crs = seed_crs_.empty() ? seed.crs : seed_crs_;

    std::vector<LayoutElementSpec> elements;
    elements.reserve(doc.elements.size());
    for (const auto& element : doc.elements) {
        LayoutElementSpec spec;
        // Unknown element types ride a TEXT carrier with the raw value in
        // properties["_raw_element_type"] (composer parity).
        std::string effective_type = element.element_type;
        if (element.carried_raw_type) {
            const auto raw = element.properties.find("_raw_element_type");
            if (raw != element.properties.end() && raw->is_string()) {
                effective_type = raw->get<std::string>();
            }
        }
        spec.element_type = effective_type;
        spec.element_id = element.id;
        spec.x_mm = element.x_mm;
        spec.y_mm = element.y_mm;
        spec.width_mm = element.width_mm;
        spec.height_mm = element.height_mm;
        spec.z_index = element.z_index;
        spec.visible = element.visible;
        spec.locked = element.locked;
        spec.properties = element.properties;
        elements.push_back(std::move(spec));
    }

    const MaterializeReport materialized =
        materialize_elements(*layout, elements, context);
    result.items = materialized.items_created;
    result.unknown_types = materialized.unknown_types;
    result.warnings = materialized.warnings;

    const std::string name =
        preferred_name.empty() ? doc.title : preferred_name;
    result.layout_name = unique_layout_name(
        name.empty() ? std::string("迁移布局") : name);
    result.layout = register_layout(std::move(layout), result.layout_name);
    if (result.layout != nullptr) {
        if (!template_id.empty()) {
            set_layout_template_metadata(result.layout, template_id,
                                         template_category);
        }
        if (!legacy_id.empty()) {
            result.layout->setCustomProperty(kLayoutLegacyIdProperty,
                                             QString::fromStdString(legacy_id));
        }
        if (auto* stack = result.layout->undoStack()->stack()) {
            stack->setClean();
        }
    }
    return result;
}

std::vector<LayoutInfo> LayoutAuthority::layouts() const {
    std::vector<LayoutInfo> out;
    QgsLayoutManager* manager = manager_for(session_);
    if (manager == nullptr) return out;
    for (QgsPrintLayout* layout : manager->printLayouts()) {
        LayoutInfo info;
        info.name = layout->name().toStdString();
        info.template_id = layout_template_id(layout);
        info.template_category =
            layout->customProperty(kLayoutTemplateCategoryProperty, QVariant())
                .toString()
                .toStdString();
        info.legacy_composition_id =
            layout->customProperty(kLayoutLegacyIdProperty, QVariant())
                .toString()
                .toStdString();
        if (const QUndoStack* stack = layout->undoStack()->stack()) {
            info.dirty = !stack->isClean();
        }
        QList<QgsLayoutItem*> items;
        layout->layoutItems(items);
        info.item_count = items.size();
        out.push_back(std::move(info));
    }
    return out;
}

QgsPrintLayout* LayoutAuthority::layout_by_name(const std::string& name) const {
    QgsLayoutManager* manager = manager_for(session_);
    if (manager == nullptr) return nullptr;
    for (QgsPrintLayout* layout : manager->printLayouts()) {
        if (layout->name().toStdString() == name) return layout;
    }
    return nullptr;
}

bool LayoutAuthority::remove_layout(const std::string& name) {
    QgsLayoutManager* manager = manager_for(session_);
    if (manager == nullptr) return false;
    QgsPrintLayout* layout = layout_by_name(name);
    if (layout == nullptr) return false;
    return manager->removeLayout(layout);
}

QgsPrintLayout* LayoutAuthority::duplicate_layout(const std::string& name,
                                                  const std::string& new_name) {
    QgsLayoutManager* manager = manager_for(session_);
    if (manager == nullptr) return nullptr;
    QgsPrintLayout* layout = layout_by_name(name);
    if (layout == nullptr) return nullptr;
    QgsMasterLayoutInterface* duplicated = manager->duplicateLayout(
        layout, QString::fromStdString(new_name));
    auto* copy = dynamic_cast<QgsPrintLayout*>(duplicated);
    if (copy == nullptr) return nullptr;
    // QgsLayout::loadFromTemplate strips item uuids (no duplicate uuids),
    // so the uuid-keyed slot map hangs: rebuild it by item id (ids travel
    // in the item XML) and drop the legacy migration anchor — a copy is a
    // new document, not another face of the migrated one.
    const auto original_slots = all_item_slots(layout);
    QList<QgsLayoutItem*> copy_items;
    copy->layoutItems(copy_items);
    copy->setCustomProperty(kLayoutSlotsProperty, QVariant());
    for (QgsLayoutItem* item : copy_items) {
        const QgsLayoutItem* match = nullptr;
        QList<QgsLayoutItem*> original_items;
        layout->layoutItems(original_items);
        for (const QgsLayoutItem* candidate : original_items) {
            if (candidate->id() == item->id()) {
                match = candidate;
                break;
            }
        }
        if (match == nullptr) continue;
        for (const auto& [uuid, slot] : original_slots) {
            if (uuid == match->uuid()) {
                attach_item_slot(copy, item, slot);
                break;
            }
        }
    }
    copy->setCustomProperty(kLayoutLegacyIdProperty, QVariant());
    if (auto* stack = copy->undoStack()->stack()) stack->setClean();
    return copy;
}

void LayoutAuthority::clear() {
    QgsLayoutManager* manager = manager_for(session_);
    if (manager == nullptr) return;
    manager->clear();
}

void LayoutAuthority::sync_map_state(QgsPrintLayout* layout) {
    if (layout == nullptr) return;
    QList<QgsMapLayer*> ordered;
    for (const std::string& id : session_.layerIdsTopFirst()) {
        if (QgsMapLayer* layer = session_.layerById(id)) {
            ordered.append(layer);
        }
    }
    const MapSeed seed = canvas_seed(session_);
    QList<QgsLayoutItemMap*> maps;
    layout->layoutItems(maps);
    for (QgsLayoutItemMap* map : maps) {
        if (!ordered.isEmpty()) {
            map->setLayers(ordered);
        }
    }
    if (seed.extent.has_value() && !maps.isEmpty()) {
        const QgsRectangle extent((*seed.extent)[0], (*seed.extent)[1],
                                  (*seed.extent)[2], (*seed.extent)[3]);
        // Only the slot-tagged main map tracks the canvas view; insets
        // keep their locator extent (materializer semantics).
        QgsLayoutItemMap* main_map = maps.first();
        const auto slot_records = all_item_slots(layout);
        for (const auto& [uuid, slot] : slot_records) {
            if (slot.slot != "main_map") continue;
            QList<QgsLayoutItem*> items;
            layout->layoutItems(items);
            for (QgsLayoutItem* item : items) {
                if (item->uuid() == uuid) {
                    if (auto* as_map = dynamic_cast<QgsLayoutItemMap*>(item)) {
                        main_map = as_map;
                    }
                    break;
                }
            }
        }
        main_map->zoomToExtent(extent);
    }
}

void LayoutAuthority::set_map_seed(
    const std::optional<std::array<double, 4>>& extent, const std::string& crs) {
    seed_extent_ = extent;
    seed_crs_ = crs;
}

domain::Json LayoutAuthority::serialize_state() const {
    Json state = Json::object();
    state["version"] = 1;
    Json layouts = Json::array();
    QgsLayoutManager* manager = manager_for(session_);
    if (manager != nullptr) {
        for (QgsPrintLayout* layout : manager->printLayouts()) {
            // Slot GC: QGIS emits no itemRemoved signal, so deleted items'
            // slot records are dropped here (persisted state only carries
            // records with a live item).
            const auto records = all_item_slots(layout);
            QList<QgsLayoutItem*> live_items;
            layout->layoutItems(live_items);
            QSet<QString> live_uuids;
            for (const QgsLayoutItem* item : live_items) {
                live_uuids.insert(item->uuid());
            }
            QJsonObject pruned = read_slot_map_public(layout);
            bool changed = false;
            for (const auto& [uuid, slot] : records) {
                if (!live_uuids.contains(uuid)) {
                    pruned.remove(uuid);
                    changed = true;
                }
            }
            if (changed) {
                layout->setCustomProperty(
                    kLayoutSlotsProperty,
                    QString::fromUtf8(QJsonDocument(pruned).toJson(
                        QJsonDocument::Compact)));
            }
            QgsReadWriteContext context;
            QDomDocument document;
            const QDomElement element = layout->writeLayoutXml(document, context);
            document.appendChild(element.cloneNode(true));  // rooted document
            Json entry = Json::object();
            entry["name"] = layout->name().toStdString();
            entry["template_id"] = layout_template_id(layout);
            entry["template_category"] =
                layout->customProperty(kLayoutTemplateCategoryProperty, QVariant())
                    .toString()
                    .toStdString();
            entry["legacy_composition_id"] =
                layout->customProperty(kLayoutLegacyIdProperty, QVariant())
                    .toString()
                    .toStdString();
            entry["xml"] = document.toString().toStdString();
            layouts.push_back(std::move(entry));
        }
    }
    state["layouts"] = std::move(layouts);
    return state;
}

LayoutAuthority::RestoreReport LayoutAuthority::restore_state(
    const domain::Json& state) {
    RestoreReport report;
    // Custom item types must be registered BEFORE readLayoutXml, or the
    // XML loader silently skips them (createItem → null → continue).
    PwbLayoutSlotItem::ensure_registered();
    if (!state.is_object()) {
        report.errors.push_back("layouts section is not an object");
        return report;
    }
    const auto layouts_it = state.find("layouts");
    if (layouts_it == state.end() || !layouts_it->is_array()) {
        return report;  // empty section = nothing to restore
    }

    QgsLayoutManager* manager = manager_for(session_);
    if (manager == nullptr) {
        report.errors.push_back("project has no layout manager");
        return report;
    }
    // Idempotent restore: replace layouts by name, keep the rest.
    for (const Json& entry : *layouts_it) {
        if (!entry.is_object()) continue;
        const auto name_it = entry.find("name");
        const auto xml_it = entry.find("xml");
        if (name_it == entry.end() || !name_it->is_string() ||
            xml_it == entry.end() || !xml_it->is_string()) {
            report.errors.push_back("layouts entry missing name/xml");
            continue;
        }
        const std::string name = name_it->get<std::string>();
        const std::string xml = xml_it->get<std::string>();

        QDomDocument document;
        QString parse_error;
        if (!document.setContent(QString::fromStdString(xml), &parse_error)) {
            report.errors.push_back("layout '" + name +
                                    "' XML parse failed: " +
                                    parse_error.toStdString());
            continue;
        }
        auto layout = std::make_unique<QgsPrintLayout>(session_.project());
        QgsReadWriteContext context;
        const QDomElement element = document.documentElement();
        if (element.isNull() || !layout->readLayoutXml(element, document, context)) {
            report.errors.push_back("layout '" + name + "' readLayoutXml failed");
            continue;
        }
        // Replace a same-named layout, keep everything else.
        if (QgsPrintLayout* existing = layout_by_name(name)) {
            manager->removeLayout(existing);
        }
        if (register_layout(std::move(layout), name) == nullptr) {
            report.errors.push_back("layout '" + name + "' registration failed");
            continue;
        }
        // Custom properties (slots/template pin) ride on the XML element;
        // re-assert the ones the section carries redundantly.
        ++report.restored;
    }
    return report;
}

bool LayoutAuthority::is_dirty() const {
    QgsLayoutManager* manager = manager_for(session_);
    if (manager == nullptr) return false;
    for (QgsPrintLayout* layout : manager->printLayouts()) {
        if (const QUndoStack* stack = layout->undoStack()->stack()) {
            if (!stack->isClean()) return true;
        }
    }
    return false;
}

void LayoutAuthority::mark_saved() {
    QgsLayoutManager* manager = manager_for(session_);
    if (manager == nullptr) return;
    for (QgsPrintLayout* layout : manager->printLayouts()) {
        if (auto* stack = layout->undoStack()->stack()) {
            stack->setClean();
        }
    }
}

}  // namespace pwb::qgis
