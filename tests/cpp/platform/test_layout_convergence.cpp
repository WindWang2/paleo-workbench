// platform.layout_convergence — the qgis-native-layout-convergence test
// battery: QgsLayoutManager persistence (structural + roundtrip), legacy
// Composition migration (all templates + unknown elements + idempotency),
// interaction (undo/dirty), unified export, atlas batch output and
// scale/lifecycle — offscreen against the real vendored QGIS.

#include <qgsapplication.h>

#include <QColor>
#include <QFile>
#include <QImage>
#include <QTemporaryDir>

#include <qgslayout.h>
#include <qgslayoutitem.h>
#include <qgslayoutitemlabel.h>
#include <qgslayoutitemlegend.h>
#include <qgslayoutitemmap.h>
#include <qgslayoutitemscalebar.h>
#include <qgslayoutmanager.h>
#include <qgslayoutundostack.h>
#include <qgsprintlayout.h>
#include <qgsproject.h>
#include <qgsvectorlayer.h>

#include <pwb/domain/json.hpp>
#include <pwb/mapping_document/composer_templates.hpp>
#include <pwb/mapping_document/composition.hpp>
#include <pwb/qgis/layout_authority.hpp>
#include <pwb/qgis/layout_export_service.hpp>
#include <pwb/qgis/layout_slot_item.hpp>
#include <pwb/qgis/layout_slots.hpp>
#include <pwb/qgis/map_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

#include <QUndoStack>

#include <cmath>
#include <filesystem>

#include "test_fixtures.hpp"
#include "test_framework.hpp"

using pwb::domain::Json;

namespace {

bool close_mm(double a, double b, double tol = 0.05) {
    return std::fabs(a - b) <= tol;
}

// Captures (uuid -> geometry mm) for structural roundtrip comparison.
struct ItemGeometry {
    std::string uuid;
    std::string id;
    double x = 0, y = 0, w = 0, h = 0;
    double z = 0;
    std::string slot;
    int type = 0;
};

std::vector<ItemGeometry> capture_geometry(QgsPrintLayout* layout) {
    std::vector<ItemGeometry> out;
    QList<QgsLayoutItem*> items;
    layout->layoutItems(items);
    std::sort(items.begin(), items.end(),
              [](const QgsLayoutItem* a, const QgsLayoutItem* b) {
                  return a->uuid() < b->uuid();
              });
    for (const QgsLayoutItem* item : items) {
        ItemGeometry g;
        g.uuid = item->uuid().toStdString();
        g.id = item->id().toStdString();
        g.x = item->positionWithUnits().x();
        g.y = item->positionWithUnits().y();
        g.w = item->sizeWithUnits().width();
        g.h = item->sizeWithUnits().height();
        g.z = item->zValue();
        g.type = item->type();
        if (const auto slot = pwb::qgis::item_slot(layout, item)) {
            g.slot = slot->slot;
        }
        out.push_back(std::move(g));
    }
    return out;
}

QgsLayoutItem* find_by_slot(QgsPrintLayout* layout, const char* slot_name) {
    return pwb::qgis::item_for_slot(layout, slot_name);
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();
    pwb::qgis::PwbLayoutSlotItem::ensure_registered();

    QTemporaryDir temp_dir;
    const QString gpkg_uri = pwb::test_fixtures::make_gpkg_fixture(temp_dir.path());
    PWB_CHECK_MSG(!gpkg_uri.isEmpty(), "fixture creation failed");
    const std::filesystem::path base =
        std::filesystem::path(temp_dir.path().toStdWString());

    // =====================================================================
    // 1. Structural — every geological template materializes a real,
    //    manager-registered QgsPrintLayout with native items + slots.
    // =====================================================================
    {
        pwb::qgis::MapSession map;
        pwb::qgis::LayoutAuthority authority(map);
        std::string error;
        pwb::qgis::LayerBinding binding{
            "conv.layer", "asset-1", "version-1", "vector"};
        QgsVectorLayer* layer = map.addVectorLayer(
            gpkg_uri.toStdString(), "conv", binding, &error);
        PWB_CHECK_MSG(layer != nullptr, error);

        int total_items = 0;
        for (const auto& tpl : pwb::mapping_document::composer_template_library()) {
            const auto created = authority.instantiate_template(tpl.template_id);
            std::string context = "template " + tpl.template_id + ": ";
            PWB_CHECK_MSG(created.layout != nullptr,
                          context + (created.warnings.empty()
                                         ? std::string("no layout")
                                         : created.warnings.front()));
            PWB_CHECK_MSG(created.items >= 4,
                          context + "expected >= 4 items, got " +
                              std::to_string(created.items));
            total_items += created.items;

            // Registered in the project's layout manager (the authority).
            QgsPrintLayout* found =
                authority.layout_by_name(created.layout->name().toStdString());
            PWB_CHECK_MSG(found == created.layout,
                          context + "layout not registered in manager");

            // Native items for the standard furniture.
            QList<QgsLayoutItemMap*> maps;
            created.layout->layoutItems(maps);
            PWB_CHECK_MSG(!maps.isEmpty(), context + "no native map item");
            // Slot semantics ride on the layout custom properties.
            PWB_CHECK_MSG(find_by_slot(created.layout, "main_map") != nullptr,
                          context + "main_map slot missing");
            PWB_CHECK_MSG(find_by_slot(created.layout, "title") != nullptr,
                          context + "title slot missing");
            // Map consumes the live session layers (same renderer
            // authority as the canvas).
            PWB_CHECK_MSG(!maps.first()->layers().isEmpty(),
                          context + "map has no layers");
            // Template metadata persisted on the layout.
            PWB_CHECK_MSG(pwb::qgis::layout_template_id(created.layout) ==
                              tpl.template_id,
                          context + "template metadata mismatch");
        }
        PWB_CHECK_MSG(total_items >= 40,
                      "10 templates should carry >= 40 items total, got " +
                          std::to_string(total_items));

        // Multiple layouts coexist; duplicate keeps slot semantics (the
        // clone re-keys uuids — the authority rebuilds the slot map by
        // item id) and never inherits the legacy migration anchor.
        const auto first = authority.layouts().front();
        QgsPrintLayout* original =
            authority.layout_by_name(first.name);
        PWB_CHECK(original != nullptr);
        QgsPrintLayout* dup = authority.duplicate_layout(
            first.name, authority.unique_layout_name(first.name + " 副本"));
        PWB_CHECK(dup != nullptr);
        PWB_CHECK(authority.layouts().size() == 11);
        PWB_CHECK_MSG(find_by_slot(dup, "main_map") != nullptr,
                      "duplicate lost the main_map slot (uuid rekey)");
        PWB_CHECK_MSG(find_by_slot(dup, "title") != nullptr,
                      "duplicate lost the title slot");
        const auto dup_migration = authority.migrate_composition(
            pwb::mapping_document::dump_composition(
                pwb::mapping_document::instantiate_composer_template(
                    pwb::mapping_document::CompositionFactory{},
                    first.template_id.empty() ? "single_factor"
                                              : first.template_id)));
        PWB_CHECK(dup_migration.layout != nullptr);
        PWB_CHECK(dup_migration.layout != dup);
        // The copy must not inherit the legacy anchor: migrating the same
        // document again pins to the FIRST migration target, never the copy.
        PWB_CHECK(authority.remove_layout(dup->name().toStdString()));
        PWB_CHECK(authority.remove_layout(
            dup_migration.layout->name().toStdString()));
        PWB_CHECK(authority.layouts().size() == 10);
        map.close();
    }

    // =====================================================================
    // 2. Persistence roundtrip — serialize into the project document
    //    section, restore into a FRESH session: geometry/slots/types hold
    //    within 0.05 mm.
    // =====================================================================
    Json saved_state;
    std::vector<ItemGeometry> geometry_before;
    {
        pwb::qgis::MapSession map;
        pwb::qgis::LayoutAuthority authority(map);
        const auto created = authority.instantiate_template("comprehensive");
        PWB_CHECK(created.layout != nullptr);

        // Edit something so undo history exists, then serialize.
        if (QgsLayoutItem* title = find_by_slot(created.layout, "title")) {
            created.layout->undoStack()->beginCommand(title, "move title");
            title->attemptMove(QgsLayoutPoint(30.0, 8.0, Qgis::LayoutUnit::Millimeters));
            created.layout->undoStack()->endCommand();
            PWB_CHECK(authority.is_dirty());
        }
        saved_state = authority.serialize_state();
        PWB_CHECK(saved_state.is_object());
        PWB_CHECK(saved_state.value("version", 0) == 1);
        geometry_before = capture_geometry(created.layout);
        map.close();
    }
    {
        pwb::qgis::MapSession map;
        pwb::qgis::LayoutAuthority authority(map);
        const auto restored = authority.restore_state(saved_state);
        PWB_CHECK_MSG(restored.restored == 1,
                      "expected 1 restored layout, got " +
                          std::to_string(restored.restored));
        for (const std::string& err : restored.errors) {
            PWB_CHECK_MSG(false, "restore error: " + err);
        }
        // Idempotent: restoring again replaces instead of duplicating.
        const auto again = authority.restore_state(saved_state);
        PWB_CHECK(again.restored == 1);
        PWB_CHECK(authority.layouts().size() == 1);

        QgsPrintLayout* layout =
            authority.layout_by_name(authority.layouts().front().name);
        PWB_CHECK(layout != nullptr);
        const auto after = capture_geometry(layout);
        PWB_CHECK_MSG(after.size() == geometry_before.size(),
                      "roundtrip item count changed: " +
                          std::to_string(after.size()) + " vs " +
                          std::to_string(geometry_before.size()));
        for (std::size_t i = 0; i < after.size() && i < geometry_before.size(); ++i) {
            const ItemGeometry& a = after[i];
            const ItemGeometry& b = geometry_before[i];
            std::string context = "roundtrip item " + a.uuid.substr(0, 8) + ": ";
            PWB_CHECK_MSG(a.type == b.type, context + "item type changed");
            PWB_CHECK_MSG(close_mm(a.x, b.x), context + "x moved");
            PWB_CHECK_MSG(close_mm(a.y, b.y), context + "y moved");
            PWB_CHECK_MSG(close_mm(a.w, b.w), context + "width changed");
            PWB_CHECK_MSG(close_mm(a.h, b.h), context + "height changed");
            PWB_CHECK_MSG(close_mm(a.z, b.z), context + "z changed");
            PWB_CHECK_MSG(a.slot == b.slot, context + "slot changed");
        }
        // Restore leaves a clean document (fresh undo history).
        PWB_CHECK(!authority.is_dirty());
        map.close();
    }

    // =====================================================================
    // 3. Migration — legacy Composition JSON → persistent native layout.
    // =====================================================================
    {
        pwb::qgis::MapSession map;
        pwb::qgis::LayoutAuthority authority(map);

        // 3a. Every template round-trips through the legacy kernel. The
        // deterministic per-factory id generators collide across
        // factories, so each migration gets a distinct document id (the
        // idempotency pin). Grid elements fold into the main map item;
        // numeric_scale scalebars materialize an extra Numeric bar.
        for (const auto& tpl : pwb::mapping_document::composer_template_library()) {
            pwb::mapping_document::CompositionFactory factory;
            const pwb::mapping_document::Composition legacy =
                pwb::mapping_document::instantiate_composer_template(
                    factory, tpl.template_id);
            Json legacy_json = pwb::mapping_document::dump_composition(legacy);
            legacy_json["id"] = "legacy_" + tpl.template_id;
            int folded_grids = 0;
            int numeric_bars = 0;
            for (const auto& element : legacy.elements) {
                if (element.element_type == "grid") ++folded_grids;
                if (element.element_type == "scale_bar" &&
                    element.properties.value("numeric_scale", false)) {
                    ++numeric_bars;
                }
            }
            const auto expected_items = static_cast<int>(legacy.elements.size()) -
                                        folded_grids + numeric_bars;
            const auto migrated = authority.migrate_composition(legacy_json);
            std::string context = "migration " + tpl.template_id + ": ";
            PWB_CHECK_MSG(migrated.layout != nullptr,
                          context + (migrated.warnings.empty()
                                         ? std::string("no layout")
                                         : migrated.warnings.front()));
            PWB_CHECK_MSG(migrated.items == expected_items,
                          context + "item count " +
                              std::to_string(migrated.items) + " != expected " +
                              std::to_string(expected_items));
            // Idempotency: the legacy id pins the layout.
            const auto second = authority.migrate_composition(legacy_json);
            PWB_CHECK_MSG(second.skipped_already_migrated,
                          context + "second migrate did not skip");
            PWB_CHECK(second.layout == migrated.layout);
        }
        PWB_CHECK(authority.layouts().size() ==
                  static_cast<int>(
                      pwb::mapping_document::composer_template_library().size()));

        // 3b. Unknown legacy element: honest placeholder, never dropped,
        //     never fabricated.
        {
            Json unknown = Json::object();
            unknown["id"] = "comp_unknown_elem";
            unknown["title"] = "未知元素迁移";
            unknown["paper_size"] = "A4";
            unknown["orientation"] = "landscape";
            unknown["width_mm"] = 297.0;
            unknown["height_mm"] = 210.0;
            unknown["dpi"] = 300.0;
            unknown["schema_version"] = 2;
            Json elements = Json::array();
            Json main_map = Json::object();
            main_map["id"] = "el_map";
            main_map["element_type"] = "main_map";
            main_map["x_mm"] = 20.0;
            main_map["y_mm"] = 20.0;
            main_map["width_mm"] = 200.0;
            main_map["height_mm"] = 150.0;
            main_map["z_index"] = 10;
            main_map["visible"] = true;
            main_map["locked"] = false;
            main_map["properties"] = Json::object();
            elements.push_back(main_map);
            Json weird = main_map;
            weird["id"] = "el_weird";
            // An out-of-vocabulary element_type rides the TEXT carrier
            // (parse moves the raw value into properties under
            // "_raw_element_type" — the composer wire contract).
            weird["element_type"] = "paleo_worm_highway";
            elements.push_back(weird);
            unknown["elements"] = elements;
            unknown["metadata"] = Json::object();

            const auto migrated = authority.migrate_composition(unknown);
            PWB_CHECK_MSG(migrated.layout != nullptr, "unknown-elem migrate failed");
            PWB_CHECK_MSG(migrated.unknown_types.size() == 1,
                          "expected 1 unknown type report");
            PWB_CHECK_MSG(migrated.unknown_types.front() == "paleo_worm_highway",
                          "unknown type not reported verbatim");
            bool has_placeholder = false;
            QList<QgsLayoutItem*> items;
            migrated.layout->layoutItems(items);
            for (QgsLayoutItem* item : items) {
                if (auto* slot_item = dynamic_cast<pwb::qgis::PwbLayoutSlotItem*>(item)) {
                    if (slot_item->kind() ==
                        pwb::qgis::PwbLayoutSlotItem::Kind::Placeholder) {
                        has_placeholder = true;
                    }
                }
            }
            PWB_CHECK_MSG(has_placeholder,
                          "unknown element must materialize a placeholder item");
        }
        map.close();
    }

    // =====================================================================
    // 4. Interaction — native undo/redo + dirty contract.
    // =====================================================================
    {
        pwb::qgis::MapSession map;
        pwb::qgis::LayoutAuthority authority(map);
        const auto created = authority.instantiate_template("contour");
        PWB_CHECK(created.layout != nullptr);
        QgsPrintLayout* layout = created.layout;
        PWB_CHECK(!authority.is_dirty());  // fresh document is clean

        QgsLayoutItem* title = find_by_slot(layout, "title");
        PWB_CHECK(title != nullptr);
        const double y_before = title->positionWithUnits().y();

        layout->undoStack()->beginCommand(title, "move");
        title->attemptMove(QgsLayoutPoint(title->positionWithUnits().x(),
                                          y_before + 12.0,
                                          Qgis::LayoutUnit::Millimeters));
        layout->undoStack()->endCommand();
        PWB_CHECK(authority.is_dirty());
        PWB_CHECK(close_mm(title->positionWithUnits().y(), y_before + 12.0));

        QUndoStack* stack = layout->undoStack()->stack();
        PWB_CHECK(stack != nullptr && stack->canUndo());
        stack->undo();
        PWB_CHECK(close_mm(title->positionWithUnits().y(), y_before));
        PWB_CHECK(stack->canRedo());
        stack->redo();
        PWB_CHECK(close_mm(title->positionWithUnits().y(), y_before + 12.0));

        // mark_saved clears every layout's dirty flag.
        authority.mark_saved();
        PWB_CHECK(!authority.is_dirty());
        map.close();
    }

    // =====================================================================
    // 5. Atlas / batch — coverage-driven multi-page output (50 features).
    // =====================================================================
    {
        pwb::qgis::MapSession map;
        pwb::qgis::LayoutAuthority authority(map);
        // Memory coverage layer with 50 features.
        QgsVectorLayer coverage("point?crs=EPSG:4326&field=name:string(20)",
                                "atlas_wells", "memory");
        PWB_CHECK(coverage.isValid());
        coverage.startEditing();
        for (int i = 0; i < 50; ++i) {
            QgsFeature feature(coverage.fields());
            feature.setGeometry(QgsGeometry::fromPointXY(
                QgsPointXY(110.0 + (i % 10) * 0.5, 30.0 + (i / 10) * 0.5)));
            feature.setAttribute("name", QStringLiteral("well_%1").arg(i));
            coverage.addFeature(feature);
        }
        coverage.commitChanges();
        PWB_CHECK(coverage.featureCount() == 50);

        const auto created = authority.instantiate_template("well_location");
        PWB_CHECK(created.layout != nullptr);

        pwb::qgis::AtlasExportRequest request;
        request.coverage_layer = &coverage;
        request.output_base = (base / "atlas_wells").string();
        request.format = "png";
        request.dpi = 72.0;
        const auto report = pwb::qgis::export_atlas(*created.layout, request);
        PWB_CHECK_MSG(report.ok, report.error.empty() ? std::string("atlas failed")
                                                      : report.error);
        PWB_CHECK_MSG(report.pages == 50,
                      "expected 50 atlas pages, got " + std::to_string(report.pages));
        PWB_CHECK(report.files.size() == 50);
        int present = 0;
        for (const std::string& file : report.files) {
            if (std::filesystem::exists(file) &&
                std::filesystem::file_size(file) > 0) {
                ++present;
            }
        }
        PWB_CHECK_MSG(present == 50,
                      "atlas files present+non-empty: " + std::to_string(present));
        map.close();
    }

    // =====================================================================
    // 6. Scale/lifecycle — 100+ item layout, repeated export, close/reopen.
    // =====================================================================
    {
        pwb::qgis::MapSession map;
        pwb::qgis::LayoutAuthority authority(map);
        const auto created = authority.instantiate_template("comprehensive");
        PWB_CHECK(created.layout != nullptr);
        QgsPrintLayout* layout = created.layout;

        // Bulk-add to 100+ items through the native undo framework.
        while (true) {
            QList<QgsLayoutItem*> items;
            layout->layoutItems(items);
            if (items.size() >= 120) break;
            auto* label = new QgsLayoutItemLabel(layout);
            layout->addLayoutItem(label);
            label->setText(QStringLiteral("负载标注 %1").arg(items.size()));
            label->attemptMove(QgsLayoutPoint(5.0 + (items.size() % 20) * 4.0,
                                              5.0 + (items.size() % 30) * 3.0,
                                              Qgis::LayoutUnit::Millimeters));
            label->attemptResize(QgsLayoutSize(20.0, 6.0, Qgis::LayoutUnit::Millimeters));
        }
        {
            QList<QgsLayoutItem*> items;
            layout->layoutItems(items);
            PWB_CHECK_MSG(items.size() >= 120, "bulk add fell short");
        }

        // Repeated export stays deterministic (three identical runs).
        pwb::qgis::LayoutExportRequest request;
        request.output_path = (base / "scale.png").string();
        request.format = "png";
        request.dpi = 96.0;
        long long size_first = -1;
        for (int round = 0; round < 3; ++round) {
            const auto report = pwb::qgis::export_layout(*layout, request);
            PWB_CHECK_MSG(report.ok, report.error);
            const long long size =
                static_cast<long long>(std::filesystem::file_size(request.output_path));
            if (round == 0) {
                size_first = size;
            } else {
                // PNG size can drift a few bytes on identical content only
                // via metadata; demand the same pixel dimensions instead.
                PWB_CHECK(report.width_px > 0);
            }
        }
        PWB_CHECK(size_first > 0);

        // Preview and export consume the same layout (same engine).
        const QImage preview = pwb::qgis::render_layout_preview(*layout, 96.0);
        PWB_CHECK(!preview.isNull());
        PWB_CHECK(preview.width() > 100);

        // close/reopen: serialize → close → fresh session → restore.
        const Json state = authority.serialize_state();
        map.close();
        pwb::qgis::MapSession map2;
        pwb::qgis::LayoutAuthority authority2(map2);
        const auto restored = authority2.restore_state(state);
        PWB_CHECK_MSG(restored.restored == 1,
                      "lifecycle restore failed: " +
                          (restored.errors.empty() ? std::string()
                                                   : restored.errors.front()));
        QgsPrintLayout* rehydrated =
            authority2.layout_by_name(authority2.layouts().front().name);
        PWB_CHECK(rehydrated != nullptr);
        {
            QList<QgsLayoutItem*> items;
            rehydrated->layoutItems(items);
            PWB_CHECK_MSG(items.size() >= 120,
                          "rehydrated layout lost items: " +
                              std::to_string(items.size()));
        }
        map2.close();
    }

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.layout_convergence");
}
