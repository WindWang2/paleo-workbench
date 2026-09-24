// layout_materializer — implementation. Item construction patterns follow
// the proven layout_spec_exec.cpp code (same vendored QGIS 4.2 SDK); the
// geographic-graticule block is adapted from its #1445-reviewed logic.

#include <pwb/qgis/layout_materializer.hpp>

#include <pwb/qgis/layout_slot_item.hpp>
#include <pwb/qgis/layout_slots.hpp>

#include <qgsapplication.h>
#include <qgscoordinatereferencesystem.h>
#include <qgscoordinatetransform.h>
#include <qgsexception.h>
#include <qgsfillsymbol.h>
#include <qgslayout.h>
#include <qgslayoutitemlabel.h>
#include <qgslayoutitemlegend.h>
#include <qgslayoutitemmap.h>
#include <qgslayoutitemmapgrid.h>
#include <qgslayoutitempage.h>
#include <qgslayoutitempicture.h>
#include <qgslayoutitemshape.h>
#include <qgslayoutitemscalebar.h>
#include <qgslayoutundostack.h>
#include <qgslinesymbol.h>
#include <qgsmaplayer.h>
#include <qgsprintlayout.h>
#include <qgsproject.h>
#include <qgstextformat.h>

#include <QFile>
#include <QFont>
#include <QString>
#include <QVariantMap>

#include <algorithm>
#include <cmath>
#include <map>

namespace pwb::qgis {

namespace {

using domain::Json;

#ifdef PALEO_QGIS_PREFIX_PATH
const std::string kQgisPrefix(PALEO_QGIS_PREFIX_PATH);
#else
const std::string kQgisPrefix;
#endif

QgsLayoutPoint mm_point(double x, double y) {
    return QgsLayoutPoint(x, y, Qgis::LayoutUnit::Millimeters);
}

QgsLayoutSize mm_size(double w, double h) {
    return QgsLayoutSize(w, h, Qgis::LayoutUnit::Millimeters);
}

const Json& prop(const Json& properties, const char* key) {
    static const Json kNull;
    if (!properties.is_object()) return kNull;
    const auto it = properties.find(key);
    return it == properties.end() ? kNull : *it;
}

std::string prop_str(const Json& properties, const char* key,
                     const std::string& fallback = {}) {
    const Json& v = prop(properties, key);
    return v.is_string() ? v.get<std::string>() : fallback;
}

double prop_num(const Json& properties, const char* key, double fallback) {
    const Json& v = prop(properties, key);
    if (v.is_number()) return v.get<double>();
    return fallback;
}

// data_binding.key → binding_id (composer bind_template vocabulary).
std::string binding_key(const Json& properties) {
    const Json& binding = prop(properties, "data_binding");
    if (binding.is_object()) {
        const auto key = binding.find("key");
        if (key != binding.end() && key->is_string()) return key->get<std::string>();
    }
    return {};
}

std::string north_arrow_svg_path() {
    const QString data_dir = QgsApplication::pkgDataPath();
    QStringList candidates{
        data_dir + QStringLiteral("/svg/arrows/NorthArrow_02.svg"),
        data_dir + QStringLiteral("/data/svg/arrows/NorthArrow_02.svg"),
    };
    if (!kQgisPrefix.empty()) {
        const QString vendor_prefix = QString::fromStdString(kQgisPrefix);
        candidates << vendor_prefix +
                          QStringLiteral("/data/svg/arrows/NorthArrow_02.svg")
                   << vendor_prefix +
                          QStringLiteral("/svg/arrows/NorthArrow_02.svg");
    }
    for (const QString& candidate : candidates) {
        if (QFile::exists(candidate)) return candidate.toStdString();
    }
    return {};
}

QgsTextFormat label_format(double size_mm, bool bold, const QColor& color) {
    QgsTextFormat format;
    QFont font;
    font.setFamilies({"SimSun", "Arial"});
    font.setBold(bold);
    format.setFont(font);
    format.setSize(std::max(2.0, size_mm));
    format.setSizeUnit(Qgis::RenderUnit::Millimeters);
    format.setColor(color);
    return format;
}

QColor prop_color(const Json& properties, const char* key,
                  const QColor& fallback) {
    const std::string raw = prop_str(properties, key);
    if (raw.empty()) return fallback;
    return QColor(raw.c_str());
}

// metadata/datasource/time_credits `fields` ([[key, value], ...]) → text.
std::string fields_text(const Json& properties, const char* text_key) {
    const std::string direct = prop_str(properties, text_key);
    if (!direct.empty()) return direct;
    const Json& fields = prop(properties, "fields");
    if (!fields.is_array()) return {};
    std::string out;
    for (const Json& field : fields) {
        if (!field.is_array() || field.empty() || !field[0].is_string()) continue;
        std::string line = field[0].get<std::string>();
        if (field.size() > 1 && field[1].is_string() && !field[1].get<std::string>().empty()) {
            line += ": " + field[1].get<std::string>();
        }
        if (!out.empty()) out += "\n";
        out += line;
    }
    return out;
}

std::unique_ptr<QgsFillSymbol> transparent_fill() {
    QVariantMap props;
    props.insert(QStringLiteral("outline_style"), QStringLiteral("no"));
    props.insert(QStringLiteral("color"), QStringLiteral("#00000000"));
    return QgsFillSymbol::createSimple(props);
}

class ScopedUndoBlock {
public:
    explicit ScopedUndoBlock(QgsPrintLayout& layout) : stack_(layout.undoStack()) {
        if (stack_ != nullptr) stack_->blockCommands(true);
    }
    ~ScopedUndoBlock() {
        if (stack_ != nullptr) stack_->blockCommands(false);
    }

private:
    QgsLayoutUndoStack* stack_;
};

// Stable per-layout unique item id: the element id when the document
// carries one, else the element type + occurrence counter (uniquified on
// collision). Ids travel in the item XML, so duplicates can rebuild the
// uuid-keyed slot map by id after QGIS clone() re-keys uuids.
std::string stable_item_id(const LayoutElementSpec& element,
                           std::map<std::string, int>& used) {
    std::string base = element.element_type;
    if (!element.element_id.empty()) base = element.element_id;
    const int seen = ++used[base];
    return seen == 1 ? base : base + "_" + std::to_string(seen);
}

void apply_common_state(QgsLayoutItem* item, const LayoutElementSpec& element,
                        std::map<std::string, int>& used_ids) {
    item->setZValue(static_cast<double>(element.z_index));
    item->setId(QString::fromStdString(stable_item_id(element, used_ids)));
    if (!element.visible) item->setVisibility(false);
    if (element.locked) item->setLocked(true);
}

void attach_slot(QgsPrintLayout& layout, const QgsLayoutItem* item,
                 const LayoutElementSpec& element, const char* slot_name,
                 const char* domain_role, const MaterializeContext& context) {
    ItemSlot slot;
    slot.slot = slot_name;
    slot.template_id = context.template_id;
    slot.domain_role = domain_role == nullptr ? std::string() : domain_role;
    slot.binding_id = binding_key(element.properties);
    slot.properties = element.properties;
    attach_item_slot(&layout, item, slot);
}

}  // namespace

MaterializeReport materialize_elements(QgsPrintLayout& layout,
                                       const std::vector<LayoutElementSpec>& elements,
                                       const MaterializeContext& context) {
    MaterializeReport report;
    PwbLayoutSlotItem::ensure_registered();
    ScopedUndoBlock undo_block(layout);

    QList<QgsMapLayer*> layers;
    if (context.layers_provider) layers = context.layers_provider();

    QgsLayoutItemMap* main_map = nullptr;
    QgsLayoutItemMap* inset_map = nullptr;
    // Grid elements fold into the main map (single-grid layout).
    const Json* grid_properties = nullptr;
    std::map<std::string, int> used_ids;

    for (const LayoutElementSpec& element : elements) {
        const std::string& t = element.element_type;
        const double x = element.x_mm;
        const double y = element.y_mm;
        const double w = std::max(1.0, element.width_mm);
        const double h = std::max(1.0, element.height_mm);

        if (t == "main_map" || t == "inset_map") {
            auto* map = new QgsLayoutItemMap(&layout);
            layout.addLayoutItem(map);
            map->attemptMove(mm_point(x, y));
            map->attemptResize(mm_size(w, h));
            if (!layers.isEmpty()) {
                // Top-first order passed through as-is (#1445 semantics).
                map->setLayers(layers);
            }
            if (t == "main_map") {
                main_map = map;
                attach_slot(layout, map, element, "main_map", "primary_map",
                            context);
            } else {
                inset_map = map;
                attach_slot(layout, map, element, "inset_map", "locator_map",
                            context);
            }
            map->setFrameEnabled(true);
            apply_common_state(map, element, used_ids);
            ++report.items_created;
            continue;
        }

        if (t == "grid") {
            // Folded into the main map once it exists (handled after loop).
            if (main_map == nullptr) {
                report.warnings.push_back(
                    "grid appears before main_map; it will attach to the "
                    "next main_map if one follows, otherwise it is dropped "
                    "(grid needs a map item)");
            }
            if (grid_properties != nullptr) {
                report.warnings.push_back(
                    "multiple grid elements: the last one wins");
            }
            grid_properties = &element.properties;
            continue;
        }

        if (t == "title" || t == "subtitle" || t == "text" ||
            t == "strat_labels" || t == "annotation" || t == "metadata" ||
            t == "datasource" || t == "time_credits") {
            auto* label = new QgsLayoutItemLabel(&layout);
            layout.addLayoutItem(label);
            std::string text = prop_str(element.properties, "text");
            if (text.empty()) text = fields_text(element.properties, "text");
            label->setText(QString::fromStdString(text));
            const double font_mm = prop_num(element.properties, "font_size",
                                            t == "title" || t == "subtitle" ? 9.0
                                                                            : 4.0);
            label->setTextFormat(label_format(
                font_mm,
                prop(element.properties, "bold").is_boolean()
                    ? prop(element.properties, "bold").get<bool>()
                    : false,
                prop_color(element.properties, "color", QColor(Qt::black))));
            const std::string align =
                prop_str(element.properties, "align",
                         t == "title" || t == "subtitle" ? "center" : "left");
            if (align == "center") {
                label->setHAlign(Qt::AlignHCenter);
            } else if (align == "right") {
                label->setHAlign(Qt::AlignRight);
            } else {
                label->setHAlign(Qt::AlignLeft);
            }
            label->setMargin(0.0);
            label->attemptMove(mm_point(x, y));
            label->attemptResize(mm_size(w, h));
            const char* slot_name = t == "title"          ? "title"
                                    : t == "subtitle"     ? "subtitle"
                                    : t == "strat_labels" ? "strat_labels"
                                    : t == "annotation"   ? "annotation"
                                    : t == "metadata"     ? "metadata_footer"
                                    : t == "datasource"   ? "datasource"
                                    : t == "text"         ? "text"
                                                          : "provenance_footer";
            const char* role = t == "time_credits" ? "provenance_footer" : nullptr;
            attach_slot(layout, label, element, slot_name, role, context);
            apply_common_state(label, element, used_ids);
            ++report.items_created;
            continue;
        }

        if (t == "north_arrow") {
            const std::string svg = north_arrow_svg_path();
            if (svg.empty()) {
                report.warnings.push_back(
                    "north arrow SVG not found in the vendored QGIS data dir; "
                    "materialized as placeholder");
                auto* slot_item = new PwbLayoutSlotItem(&layout);
                layout.addLayoutItem(slot_item);
                slot_item->set_kind(PwbLayoutSlotItem::Kind::Placeholder);
                slot_item->set_slot_name("north_arrow");
                slot_item->set_slot_properties(element.properties);
                slot_item->attemptMove(mm_point(x, y));
                slot_item->attemptResize(mm_size(w, h));
                attach_slot(layout, slot_item, element, "north_arrow", nullptr,
                            context);
                apply_common_state(slot_item, element, used_ids);
                ++report.items_created;
                continue;
            }
            auto* picture = new QgsLayoutItemPicture(&layout);
            layout.addLayoutItem(picture);
            picture->setPicturePath(QString::fromStdString(svg));
            picture->attemptMove(mm_point(x, y));
            picture->attemptResize(mm_size(w, h));
            attach_slot(layout, picture, element, "north_arrow", nullptr, context);
            apply_common_state(picture, element, used_ids);
            ++report.items_created;
            continue;
        }

        if (t == "image") {
            const std::string path = prop_str(element.properties, "path");
            const std::string embedded = prop_str(element.properties, "svg");
            if (!path.empty()) {
                auto* picture = new QgsLayoutItemPicture(&layout);
                layout.addLayoutItem(picture);
                picture->setPicturePath(QString::fromStdString(path));
                picture->attemptMove(mm_point(x, y));
                picture->attemptResize(mm_size(w, h));
                attach_slot(layout, picture, element, "image", nullptr, context);
                apply_common_state(picture, element, used_ids);
            } else {
                auto* slot_item = new PwbLayoutSlotItem(&layout);
                layout.addLayoutItem(slot_item);
                slot_item->set_kind(PwbLayoutSlotItem::Kind::Placeholder);
                slot_item->set_slot_name("image");
                Json properties = element.properties;
                if (!embedded.empty()) properties["embedded_svg"] = embedded;
                slot_item->set_slot_properties(properties);
                slot_item->attemptMove(mm_point(x, y));
                slot_item->attemptResize(mm_size(w, h));
                attach_slot(layout, slot_item, element, "image", nullptr, context);
                apply_common_state(slot_item, element, used_ids);
            }
            ++report.items_created;
            continue;
        }

        if (t == "scale_bar") {
            if (main_map == nullptr) {
                report.warnings.push_back("scale_bar before main_map; skipped");
                continue;
            }
            auto configure = [&](QgsLayoutItemScaleBar* bar, bool numeric) {
                bar->setLinkedMap(main_map);
                bar->applyDefaultSettings();
                if (numeric) {
                    bar->setStyle(QStringLiteral("Numeric"));
                } else {
                    bar->setUnits(Qgis::DistanceUnit::Kilometers);
                    const double length_km =
                        prop_num(element.properties, "length_km", 10.0);
                    bar->setNumberOfSegments(2);
                    bar->setNumberOfSegmentsLeft(0);
                    bar->setSegmentSizeMode(Qgis::ScaleBarSegmentSizeMode::Fixed);
                    bar->setUnitsPerSegment(std::max(0.5, length_km / 2.0));
                    bar->setHeight(2.0);
                }
                bar->attemptMove(mm_point(x, y));
                layout.addLayoutItem(bar);
                apply_common_state(bar, element, used_ids);
                ++report.items_created;
            };
            auto* scalebar = new QgsLayoutItemScaleBar(&layout);
            configure(scalebar, /*numeric=*/false);
            attach_slot(layout, scalebar, element, "scale_bar", nullptr, context);
            if (prop(element.properties, "numeric_scale").is_boolean() &&
                prop(element.properties, "numeric_scale").get<bool>()) {
                auto* numeric = new QgsLayoutItemScaleBar(&layout);
                configure(numeric, /*numeric=*/true);
                numeric->attemptMove(mm_point(x + w + 6.0, y));
                attach_slot(layout, numeric, element, "numeric_scale", nullptr,
                            context);
            }
            continue;
        }

        if (t == "legend" || t == "facies_legend" || t == "well_legend") {
            auto* legend = new QgsLayoutItemLegend(&layout);
            layout.addLayoutItem(legend);
            legend->setTitle(QString::fromStdString(
                prop_str(element.properties, "title", "图例")));
            if (main_map != nullptr) legend->setLinkedMap(main_map);
            legend->setResizeToContents(true);
            legend->attemptMove(mm_point(x, y));
            legend->attemptResize(mm_size(w, h));
            const char* slot_name = t == "legend" ? "legend" : t.c_str();
            const char* role = t == "facies_legend" ? "factor_legend"
                               : t == "well_legend" ? "well_legend"
                                                    : nullptr;
            attach_slot(layout, legend, element, slot_name, role, context);
            apply_common_state(legend, element, used_ids);
            ++report.items_created;
            continue;
        }

        if (t == "neatline") {
            auto* shape = new QgsLayoutItemShape(&layout);
            layout.addLayoutItem(shape);
            shape->setShapeType(QgsLayoutItemShape::Rectangle);
            shape->setSymbol(transparent_fill().release());
            shape->setFrameEnabled(true);
            shape->attemptMove(mm_point(x, y));
            shape->attemptResize(mm_size(w, h));
            apply_common_state(shape, element, used_ids);
            ++report.items_created;
            continue;
        }

        if (t == "stat_chart" || t == "colorbar" || t == "timescale" ||
            t == "profile" || t == "fault_symbols" || t == "lithology_legend") {
            auto* slot_item = new PwbLayoutSlotItem(&layout);
            layout.addLayoutItem(slot_item);
            slot_item->set_slot_name(t);
            slot_item->set_slot_properties(element.properties);
            if (t == "stat_chart") {
                slot_item->set_kind(PwbLayoutSlotItem::Kind::StatChart);
            } else if (t == "colorbar") {
                slot_item->set_kind(PwbLayoutSlotItem::Kind::Colorbar);
            } else if (t == "timescale") {
                slot_item->set_kind(PwbLayoutSlotItem::Kind::Timescale);
            } else if (t == "profile") {
                slot_item->set_kind(PwbLayoutSlotItem::Kind::Profile);
            } else if (t == "fault_symbols") {
                slot_item->set_kind(PwbLayoutSlotItem::Kind::FaultSymbols);
            } else {
                slot_item->set_kind(PwbLayoutSlotItem::Kind::LithologyLegend);
            }
            slot_item->attemptMove(mm_point(x, y));
            slot_item->attemptResize(mm_size(w, h));
            const char* role = t == "stat_chart" ? "statistics_chart" : nullptr;
            attach_slot(layout, slot_item, element, t.c_str(), role, context);
            apply_common_state(slot_item, element, used_ids);
            ++report.items_created;
            continue;
        }

        // Unknown legacy element: honest placeholder, never dropped and
        // never fabricated (audit D-V14 parity with the old SVG renderer).
        {
            report.unknown_types.push_back(t);
            auto* slot_item = new PwbLayoutSlotItem(&layout);
            layout.addLayoutItem(slot_item);
            slot_item->set_kind(PwbLayoutSlotItem::Kind::Placeholder);
            slot_item->set_slot_name(t);
            Json properties = element.properties;
            properties["_raw_element_type"] = t;
            slot_item->set_slot_properties(std::move(properties));
            slot_item->attemptMove(mm_point(x, y));
            slot_item->attemptResize(mm_size(w, h));
            attach_slot(layout, slot_item, element, t.c_str(),
                        "unknown_legacy", context);
            apply_common_state(slot_item, element, used_ids);
            ++report.items_created;
        }
    }

    // Map extent + CRS defaults (after all maps exist).
    QgsRectangle extent;
    if (context.map_extent.has_value()) {
        extent = QgsRectangle((*context.map_extent)[0], (*context.map_extent)[1],
                              (*context.map_extent)[2], (*context.map_extent)[3]);
    } else if (!layers.isEmpty()) {
        for (const QgsMapLayer* layer : layers) {
            if (layer == nullptr) continue;
            if (extent.isEmpty()) {
                extent = layer->extent();
            } else {
                extent.combineExtentWith(layer->extent());
            }
        }
    }
    QgsCoordinateReferenceSystem crs;
    if (!context.map_crs.empty()) {
        crs = QgsCoordinateReferenceSystem(QString::fromStdString(context.map_crs));
    } else if (QgsProject* project = layout.project()) {
        crs = project->crs();
    }
    for (QgsLayoutItemMap* map : {main_map, inset_map}) {
        if (map == nullptr) continue;
        if (extent.isEmpty()) continue;
        map->zoomToExtent(extent);
        if (crs.isValid()) map->setCrs(crs);
    }
    // Locator inset: shrink the extent by the template's locator scale.
    if (inset_map != nullptr && !extent.isEmpty()) {
        const auto slot = item_slot(&layout, inset_map);
        if (slot.has_value()) {
            const Json& props = slot->properties;
            if (const Json& scale_json = prop(props, "locator_scale");
                scale_json.is_number()) {
                const double scale = std::max(1.000001, scale_json.get<double>());
                const double dx = extent.width() * (scale - 1.0) / 2.0;
                const double dy = extent.height() * (scale - 1.0) / 2.0;
                inset_map->zoomToExtent(QgsRectangle(
                    extent.xMinimum() - dx, extent.yMinimum() - dy,
                    extent.xMaximum() + dx, extent.yMaximum() + dy));
                if (crs.isValid()) inset_map->setCrs(crs);
            }
        }
    }

    // Grid: fold into the main map (map grid, mm or geographic units).
    if (main_map == nullptr && grid_properties != nullptr) {
        report.warnings.push_back(
            "grid element had no main_map to attach to; dropped");
    }
    if (main_map != nullptr && grid_properties != nullptr) {
        const Json& grid = *grid_properties;
        QgsLayoutItemMapGrid* map_grid = main_map->grid();
        map_grid->setEnabled(true);
        if (prop(grid, "geographic").is_boolean() &&
            prop(grid, "geographic").get<bool>()) {
            QgsProject* project = layout.project();
            const QgsCoordinateReferenceSystem geographic(
                QStringLiteral("EPSG:4326"));
            if (!main_map->crs().isValid() || project == nullptr) {
                report.warnings.push_back(
                    "geographic graticule requires a valid map CRS and project; "
                    "grid left disabled");
            } else {
                QgsRectangle bounds;
                try {
                    QgsCoordinateTransform transform(main_map->crs(), geographic,
                                                     project);
                    bounds = transform.transformBoundingBox(main_map->extent());
                } catch (const QgsCsException&) {
                    // QgsCsException derives from QgsException, NOT
                    // std::exception — an unprojectable extent degrades
                    // the graticule, it never aborts the materialization.
                    bounds = QgsRectangle();
                } catch (...) {
                    bounds = QgsRectangle();
                }
                const double span = std::max(bounds.width(), bounds.height());
                double interval =
                    prop_num(grid, "interval_degrees",
                             prop_num(grid, "interval_x", 0.0));
                if (interval == 0.0 && std::isfinite(span) && span > 0.0) {
                    const double magnitude =
                        std::pow(10.0, std::floor(std::log10(span / 5.0)));
                    const double normalized = span / 5.0 / magnitude;
                    interval = magnitude * (normalized <= 1.0   ? 1.0
                                            : normalized <= 2.0 ? 2.0
                                            : normalized <= 5.0 ? 5.0
                                                                : 10.0);
                }
                if (std::isfinite(interval) && interval > 0.0 &&
                    span / interval <= 1000.0) {
                    map_grid->setCrs(geographic);
                    map_grid->setIntervalX(interval);
                    map_grid->setIntervalY(interval);
                    map_grid->setAnnotationEnabled(true);
                    map_grid->setAnnotationFormat(
                        Qgis::MapGridAnnotationFormat::DegreeMinuteSecond);
                    map_grid->setAnnotationPrecision(0);
                    map_grid->setAnnotationDirection(
                        Qgis::MapGridAnnotationDirection::Horizontal);
                    map_grid->setAnnotationFrameDistance(2.0);
                    for (const auto side :
                         {Qgis::MapGridBorderSide::Left, Qgis::MapGridBorderSide::Right,
                          Qgis::MapGridBorderSide::Top,
                          Qgis::MapGridBorderSide::Bottom}) {
                        map_grid->setAnnotationPosition(
                            Qgis::MapGridAnnotationPosition::OutsideMapFrame,
                            side);
                    }
                    QgsTextFormat text;
                    text.setSize(8.0);
                    text.setSizeUnit(Qgis::RenderUnit::Points);
                    text.setColor(Qt::black);
                    map_grid->setAnnotationTextFormat(text);
                    map_grid->setFrameStyle(Qgis::MapGridFrameStyle::Zebra);
                    map_grid->setFrameWidth(1.5);
                    map_grid->setFramePenSize(0.2);
                    map_grid->setFrameFillColor1(Qt::white);
                    map_grid->setFrameFillColor2(Qt::black);
                    const double line_width = prop_num(grid, "line_width_mm", 0.15);
                    auto line = QgsLineSymbol::createSimple(QVariantMap{
                        {QStringLiteral("line_color"),
                         QString::fromStdString(
                             prop_str(grid, "color", "#606060"))},
                        {QStringLiteral("line_width"),
                         QString::number(std::clamp(line_width, 0.01, 5.0))},
                        {QStringLiteral("line_style"), QStringLiteral("dot")}});
                    map_grid->setLineSymbol(line.release());
                } else {
                    map_grid->setEnabled(false);
                    report.warnings.push_back(
                        "geographic grid interval invalid; grid left disabled");
                }
            }
        } else {
            // Page-space grid: mm intervals (composer spacing_mm semantics).
            const double spacing =
                prop_num(grid, "spacing_mm",
                         prop_num(grid, "interval_x", 30.0));
            map_grid->setUnits(Qgis::MapGridUnit::Millimeters);
            map_grid->setIntervalX(spacing);
            map_grid->setIntervalY(spacing);
            map_grid->setAnnotationEnabled(false);
            auto line = QgsLineSymbol::createSimple(QVariantMap{
                {QStringLiteral("line_color"),
                 QString::fromStdString(prop_str(grid, "color", "#90a4ae"))},
                {QStringLiteral("line_width"), QStringLiteral("0.15")}});
            map_grid->setLineSymbol(line.release());
        }
    }

    if (auto* stack = layout.undoStack()->stack()) {
        stack->setClean();
    }
    return report;
}

}  // namespace pwb::qgis
