#include "style_codec.hpp"

#include <algorithm>
#include <stdexcept>

#include <QDomDocument>
#include <QString>
#include <QStringList>
#include <QVariantMap>

#include <qgscategorizedsymbolrenderer.h>
#include <qgscoordinatereferencesystem.h>
#include <qgsfield.h>
#include <qgsfillsymbol.h>
#include <qgsgraduatedsymbolrenderer.h>
#include <qgslabeling.h>
#include <qgslinesymbol.h>
#include <qgsmarkersymbol.h>
#include <qgsmarkersymbollayer.h>
#include <qgspallabeling.h>
#include <qgsproperty.h>
#include <qgspropertycollection.h>
#include <qgsreadwritecontext.h>
#include <qgsrendererrange.h>
#include <qgsrulebasedrenderer.h>
#include <qgssinglesymbolrenderer.h>
#include <qgssymbollayerutils.h>
#include <qgssymbol.h>
#include <qgstextbuffersettings.h>
#include <qgstextformat.h>
#include <qgsvectordataprovider.h>
#include <qgsvectorlayer.h>
#include <qgsvectorlayerlabeling.h>

#include <QColor>
#include <QDomElement>
#include <QFont>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>

#include "qgis_render_bridge.hpp"

// v7 §5 raster codec QGIS headers (top of TU — never inside a namespace).
// NOTE: no nlohmann/json here — the vendored copy's <valarray> include
// breaks MSVC's STL headers in this TU (C2065 align_val_t); Qt's own
// QJsonDocument parses the flat scalar spec instead.
#include <qgsapplication.h>
#include <qgscolorrampshader.h>
#include <qgsrasterinterface.h>
#include <qgsrasterlayer.h>
#include <qgsrasterrenderer.h>
#include <qgsrasterrendererregistry.h>
#include <qgsrastershader.h>
#include <qgssinglebandpseudocolorrenderer.h>

namespace pwb::qgis_render {
namespace {

Qgis::GeometryType geometry_type_from_name(const std::string& name) {
    if (name == "Point" || name == "MultiPoint") return Qgis::GeometryType::Point;
    if (name == "LineString" || name == "MultiLineString") return Qgis::GeometryType::Line;
    if (name == "Polygon" || name == "MultiPolygon") return Qgis::GeometryType::Polygon;
    return Qgis::GeometryType::Null;
}

/// Legacy compatibility symbol construction.  Professional authoring never
/// calls this: it exists so legacy VectorStyle payloads and minimal fallbacks
/// keep rendering while the authoritative model is the renderer XML payload.
///
/// Audit #922: legacy VectorStyle sizes are logical PIXELS at 96 dpi
/// (map_styles.py), while createSimple properties default to MILLIMETERS — so
/// every size carries an explicit ``*_unit = Pixel`` property, otherwise QGIS
/// inflates it by 96/25.4 ≈ 3.78×. *line_pattern* is applied as a custom dash
/// vector so both backends draw identical n × width pixel strokes: QGIS
/// built-in "dash"/"dot" use QGIS-internal lengths, and "fault" (the default
/// fault-trace pattern) has no built-in equivalent at all — it rendered solid.
std::unique_ptr<QgsSymbol> legacy_symbol_for(
    Qgis::GeometryType geometry_type, const QString& fill, const QString& stroke,
    double stroke_width, double marker_size, const std::string& line_pattern = "solid",
    const std::string& marker = "circle"
) {
    QVariantMap properties;
    const QString width = QString::number(std::max(0.0, stroke_width), 'g', 12);
    const char* dash_units = nullptr;
    if (line_pattern == "dash") dash_units = "4;2";
    else if (line_pattern == "dot") dash_units = "1;2";
    else if (line_pattern == "dash_dot") dash_units = "4;2;1;2";
    else if (line_pattern == "fault") dash_units = "6;2";
    switch (geometry_type) {
        case Qgis::GeometryType::Polygon:
            properties.insert(QStringLiteral("color"), fill);
            properties.insert(QStringLiteral("outline_color"), stroke);
            properties.insert(QStringLiteral("outline_width"), width);
            properties.insert(QStringLiteral("outline_width_unit"), QStringLiteral("Pixel"));
            return QgsFillSymbol::createSimple(properties);
        case Qgis::GeometryType::Line:
            properties.insert(QStringLiteral("line_color"), stroke);
            properties.insert(QStringLiteral("color"), stroke);
            properties.insert(QStringLiteral("line_width"), width);
            properties.insert(QStringLiteral("width"), width);
            properties.insert(QStringLiteral("line_width_unit"), QStringLiteral("Pixel"));
            if (dash_units != nullptr) {
                // The fallback QPen dashes are n × pen-width pixels; QGIS
                // rescales the customdash vector by dividing by the pen
                // width (qgslinesymbollayer.cpp), so pre-multiply here. The
                // fallback clamps its pen to >= 0.5 px — mirror that floor
                // so thin lines keep the same dash rhythm on both paths.
                const double dash_width = std::max(0.5, stroke_width);
                QStringList lengths;
                for (const QString& unit : QString::fromLatin1(dash_units).split(QLatin1Char(';'))) {
                    lengths << QString::number(unit.toDouble() * dash_width, 'g', 12);
                }
                properties.insert(QStringLiteral("use_custom_dash"), QStringLiteral("1"));
                properties.insert(QStringLiteral("customdash"), lengths.join(QLatin1Char(';')));
                properties.insert(QStringLiteral("customdash_unit"), QStringLiteral("Pixel"));
            }
            return QgsLineSymbol::createSimple(properties);
        case Qgis::GeometryType::Point:
            properties.insert(QStringLiteral("color"), fill);
            properties.insert(QStringLiteral("outline_color"), stroke);
            properties.insert(QStringLiteral("size"), QString::number(std::max(0.1, marker_size), 'g', 12));
            properties.insert(QStringLiteral("size_unit"), QStringLiteral("Pixel"));
            if (marker == "well") {
                // 井符号: filled ring + dark centre dot (the fallback draws
                // MarkerSymbol.WELL as an ellipse plus a centre point).
                QVariantMap dot_properties;
                dot_properties.insert(QStringLiteral("name"), QStringLiteral("circle"));
                dot_properties.insert(QStringLiteral("color"), stroke);
                dot_properties.insert(QStringLiteral("outline_color"), QStringLiteral("transparent"));
                dot_properties.insert(
                    QStringLiteral("size"),
                    QString::number(std::max(0.1, marker_size * 0.32), 'g', 12)
                );
                dot_properties.insert(QStringLiteral("size_unit"), QStringLiteral("Pixel"));
                QgsSymbolLayerList symbol_layers;
                symbol_layers << QgsSimpleMarkerSymbolLayer::create(properties)
                              << QgsSimpleMarkerSymbolLayer::create(dot_properties);
                return std::unique_ptr<QgsSymbol>(new QgsMarkerSymbol(symbol_layers));
            }
            return QgsMarkerSymbol::createSimple(properties);
        default:
            return {};
    }
}

}  // namespace

std::string renderer_to_xml(const QgsFeatureRenderer& renderer) {
    // QgsFeatureRenderer::save() is non-const in this QGIS version; serialize
    // through a clone so callers can pass const references safely.
    std::unique_ptr<QgsFeatureRenderer> writable(renderer.clone());
    QDomDocument document;
    QgsReadWriteContext context;
    const QDomElement element = writable->save(document, context);
    if (element.isNull()) {
        throw std::runtime_error("QGIS renderer could not be serialized");
    }
    document.appendChild(element);
    return document.toString().toStdString();
}

std::unique_ptr<QgsFeatureRenderer> renderer_from_xml(const std::string& xml) {
    QDomDocument document;
    if (!document.setContent(QString::fromStdString(xml))) {
        return nullptr;
    }
    QDomElement element = document.firstChildElement();
    if (element.isNull()) {
        return nullptr;
    }
    QgsReadWriteContext context;
    return std::unique_ptr<QgsFeatureRenderer>(QgsFeatureRenderer::load(element, context));
}

std::unique_ptr<QgsFeatureRenderer> build_renderer_from_spec(
    const Qgis::GeometryType geometry_type, const VectorLayerSpec& spec
) {
    if (geometry_type == Qgis::GeometryType::Null) return nullptr;

    const QString default_fill = QString::fromStdString(spec.fill);
    const QString default_stroke = QString::fromStdString(spec.stroke);

    if (spec.renderer_kind == "rule" && !spec.rules.empty()) {
        auto root = std::make_unique<QgsRuleBasedRenderer::Rule>(nullptr);
        for (const RuleSpec& rule : spec.rules) {
            auto symbol = legacy_symbol_for(
                geometry_type,
                rule.fill.empty() ? default_fill : QString::fromStdString(rule.fill),
                rule.stroke.empty() ? default_stroke : QString::fromStdString(rule.stroke),
                rule.stroke_width,
                rule.marker_size,
                spec.line_pattern,
                spec.marker
            );
            if (!symbol) continue;
            auto node = std::make_unique<QgsRuleBasedRenderer::Rule>(
                symbol.release(), 0, 0,
                QString::fromStdString(rule.expression),
                QString::fromStdString(!rule.label.empty() ? rule.label : rule.name)
            );
            root->appendChild(node.release());
        }
        if (root->children().isEmpty()) return nullptr;
        return std::make_unique<QgsRuleBasedRenderer>(root.release());
    }

    if (spec.renderer_kind == "categorized" && !spec.classification_field.empty()
        && !spec.categories.empty()) {
        QgsCategoryList categories;
        for (const CategorySpec& category : spec.categories) {
            auto symbol = legacy_symbol_for(
                geometry_type, QString::fromStdString(category.color), default_stroke,
                spec.stroke_width, spec.marker_size, spec.line_pattern, spec.marker
            );
            if (symbol) {
                categories.emplace_back(
                    QVariant(QString::fromStdString(category.value)), symbol.release(),
                    QString::fromStdString(category.label)
                );
            }
        }
        if (categories.empty()) return nullptr;
        return std::make_unique<QgsCategorizedSymbolRenderer>(
            QString::fromStdString(spec.classification_field), categories
        );
    }

    if (spec.renderer_kind == "graduated" && !spec.classification_field.empty()
        && !spec.ranges.empty()) {
        QgsRangeList ranges;
        for (const RangeSpec& range : spec.ranges) {
            auto symbol = legacy_symbol_for(
                geometry_type, QString::fromStdString(range.color), default_stroke,
                spec.stroke_width, spec.marker_size, spec.line_pattern, spec.marker
            );
            if (symbol) {
                ranges.emplace_back(
                    range.lower, range.upper, symbol.release(),
                    QString::fromStdString(range.label)
                );
            }
        }
        if (ranges.empty()) return nullptr;
        return std::make_unique<QgsGraduatedSymbolRenderer>(
            QString::fromStdString(spec.classification_field), ranges
        );
    }

    auto symbol = legacy_symbol_for(
        geometry_type, default_fill, default_stroke, spec.stroke_width,
        spec.marker_size, spec.line_pattern, spec.marker
    );
    if (!symbol) return nullptr;
    return std::make_unique<QgsSingleSymbolRenderer>(symbol.release());
}

std::unique_ptr<QgsVectorLayer> make_dialog_layer(
    const std::string& geometry_type, const std::string& crs,
    const std::vector<std::pair<std::string, std::string>>& fields
) {
    const QString uri = QStringLiteral("%1?crs=%2")
                            .arg(QString::fromStdString(geometry_type),
                                 QString::fromStdString(crs));
    auto layer = std::make_unique<QgsVectorLayer>(
        uri, QStringLiteral("paleo_authoring"), QStringLiteral("memory")
    );
    if (!layer->isValid()) {
        throw std::runtime_error("QGIS dialog layer could not be created");
    }
    QList<QgsField> qfields;
    for (const auto& entry : fields) {
        qfields.append(QgsField(
            QString::fromStdString(entry.first), QMetaType::Type::QString
        ));
    }
    if (!qfields.isEmpty() && !layer->dataProvider()->addAttributes(qfields)) {
        throw std::runtime_error("QGIS dialog layer fields could not be created");
    }
    layer->updateFields();
    return layer;
}

void validate_style_payloads(const VectorLayerSpec& spec) {
    if (!spec.renderer_xml.empty()) {
        auto renderer = renderer_from_xml(spec.renderer_xml);
        if (!renderer) {
            throw std::runtime_error("invalid QGIS renderer payload for layer " + spec.id);
        }
    }
    if (!spec.labeling_xml.empty()) {
        QDomDocument document;
        if (!document.setContent(QString::fromStdString(spec.labeling_xml))) {
            throw std::runtime_error("invalid QGIS labeling payload for layer " + spec.id);
        }
        const QDomElement element = document.firstChildElement();
        if (element.isNull()) {
            throw std::runtime_error("empty QGIS labeling payload for layer " + spec.id);
        }
        QgsReadWriteContext context;
        auto labeling = std::unique_ptr<QgsAbstractVectorLayerLabeling>(
            QgsAbstractVectorLayerLabeling::create(element, context)
        );
        if (!labeling) {
            throw std::runtime_error("QGIS labeling payload could not be parsed for layer " + spec.id);
        }
    }
}

void apply_renderer_style(QgsVectorLayer& layer, const VectorLayerSpec& spec) {
    const Qgis::GeometryType geometry_type = layer.geometryType();
    if (geometry_type == Qgis::GeometryType::Null) return;
    if (!spec.renderer_xml.empty()) {
        auto renderer = renderer_from_xml(spec.renderer_xml);
        if (!renderer) {
            throw std::runtime_error("invalid QGIS renderer payload for layer " + spec.id);
        }
        layer.setRenderer(renderer.release());
        return;
    }
    auto renderer = build_renderer_from_spec(geometry_type, spec);
    if (renderer) layer.setRenderer(renderer.release());
}

void apply_label_style(QgsVectorLayer& layer, const VectorLayerSpec& spec) {
    if (!spec.labeling_xml.empty()) {
        QDomDocument document;
        if (!document.setContent(QString::fromStdString(spec.labeling_xml))) {
            throw std::runtime_error("invalid QGIS labeling payload for layer " + spec.id);
        }
        QDomElement element = document.firstChildElement();
        if (element.isNull()) {
            throw std::runtime_error("empty QGIS labeling payload for layer " + spec.id);
        }
        QgsReadWriteContext context;
        auto labeling = std::unique_ptr<QgsAbstractVectorLayerLabeling>(
            QgsAbstractVectorLayerLabeling::create(element, context)
        );
        if (!labeling) {
            throw std::runtime_error("QGIS labeling payload could not be parsed for layer " + spec.id);
        }
        layer.setLabeling(labeling.release());
        layer.setLabelsEnabled(true);
        return;
    }
    if (!spec.labels_enabled || spec.label_field.empty()) {
        layer.setLabelsEnabled(false);
        return;
    }
    QgsPalLayerSettings settings;
    settings.fieldName = QString::fromStdString(spec.label_field);
    settings.isExpression = false;
    QgsTextFormat format;
    QFont font;
    if (!spec.label_font_family.empty()) font.setFamily(QString::fromStdString(spec.label_font_family));
    font.setBold(spec.label_bold);
    format.setFont(font);
    format.setSize(std::max(0.1, spec.label_size));
    format.setColor(QColor(QString::fromStdString(spec.label_color)));
    if (spec.label_buffer_size > 0.0) {
        QgsTextBufferSettings buffer;
        buffer.setEnabled(true);
        buffer.setSize(spec.label_buffer_size);
        // #1102: the buffer colour rides the wire (labels.buffer_color).
        // An absent or unparseable value keeps the historical white halo.
        const QColor buffer_color(QString::fromStdString(spec.label_buffer_color));
        buffer.setColor(buffer_color.isValid() ? buffer_color : QColor(Qt::white));
        format.setBuffer(buffer);
    }
    settings.setFormat(format);
    // #1052: per-feature data-defined label properties. Field-based
    // properties are evaluated per feature by QGIS PAL (rotation in degrees
    // clockwise, size in points, colour as a colour string) and override the
    // fixed format above; an empty field name leaves the fixed value.
    QgsPropertyCollection& data_defined = settings.dataDefinedProperties();
    if (!spec.label_rotation_field.empty()) {
        data_defined.setProperty(
            QgsPalLayerSettings::Property::LabelRotation,
            QgsProperty::fromField(QString::fromStdString(spec.label_rotation_field))
        );
    }
    if (!spec.label_size_field.empty()) {
        data_defined.setProperty(
            QgsPalLayerSettings::Property::Size,
            QgsProperty::fromField(QString::fromStdString(spec.label_size_field))
        );
    }
    if (!spec.label_color_field.empty()) {
        data_defined.setProperty(
            QgsPalLayerSettings::Property::Color,
            QgsProperty::fromField(QString::fromStdString(spec.label_color_field))
        );
    }
    layer.setLabeling(new QgsVectorLayerSimpleLabeling(settings));
    layer.setLabelsEnabled(true);
}

// ---------------------------------------------------------------------------
// Raster renderer codec (v7 §5): implementation below; includes live at
// the top of this file (never inside namespace pwb::qgis_render).

namespace {

/// Parse the payload into a rasterrenderer element; null element = invalid.
QDomElement raster_renderer_element(const std::string& xml) {
    QDomDocument doc;
    if (!doc.setContent(QString::fromStdString(xml), true)) return {};
    QDomElement elem = doc.documentElement();
    if (elem.tagName() != QStringLiteral("rasterrenderer")) {
        elem = doc.firstChildElement(QStringLiteral("rasterrenderer"));
    }
    if (elem.isNull() || elem.tagName() != QStringLiteral("rasterrenderer")) {
        return {};
    }
    return elem;
}

}  // namespace

std::string build_scalar_renderer_xml(const std::string& spec_json) {
    QJsonParseError parse_error{};
    const QJsonDocument document = QJsonDocument::fromJson(
        QByteArray::fromStdString(spec_json), &parse_error);
    if (parse_error.error != QJsonParseError::NoError || !document.isObject()) {
        throw std::runtime_error("scalar renderer spec must be a JSON object");
    }
    const QJsonObject payload = document.object();
    const double vmin = payload.value(QStringLiteral("min")).toDouble(0.0);
    double vmax = payload.value(QStringLiteral("max")).toDouble(1.0);
    if (!(vmax > vmin)) vmax = vmin + 1.0;
    const QString mode = payload.value(QStringLiteral("mode")).toString(
        QStringLiteral("continuous"));
    const QJsonArray items = payload.value(QStringLiteral("items")).toArray();
    if (items.isEmpty()) {
        throw std::runtime_error("scalar renderer spec needs a non-empty items list");
    }
    auto shader = std::make_unique<QgsColorRampShader>(vmin, vmax);
    shader->setColorRampType(mode == QStringLiteral("classified")
                                  ? Qgis::ShaderInterpolationMethod::Discrete
                                  : Qgis::ShaderInterpolationMethod::Linear);
    QList<QgsColorRampShader::ColorRampItem> ramp_items;
    ramp_items.reserve(items.size());
    for (const QJsonValue& value : items) {
        if (!value.isObject()) {
            throw std::runtime_error("scalar renderer item must be an object");
        }
        const QJsonObject item = value.toObject();
        ramp_items.append(QgsColorRampShader::ColorRampItem(
            item.value(QStringLiteral("value")).toDouble(0.0),
            QColor(item.value(QStringLiteral("color")).toString(
                QStringLiteral("#000000"))),
            item.value(QStringLiteral("label")).toString()));
    }
    std::sort(ramp_items.begin(), ramp_items.end(),
              [](const QgsColorRampShader::ColorRampItem& a,
                 const QgsColorRampShader::ColorRampItem& b) {
                  return a.value < b.value;
              });
    shader->setColorRampItemList(ramp_items);

    auto raster_shader = std::make_unique<QgsRasterShader>();
    raster_shader->setRasterShaderFunction(shader.release());
    // No live provider here: the XML is the deliverable.  Applying it to a
    // layer re-binds the provider as the renderer input (setRenderer/pipe).
    auto renderer = std::make_unique<QgsSingleBandPseudoColorRenderer>(
        /*input=*/nullptr, /*band=*/1, raster_shader.release());

    QDomDocument doc;
    QDomElement wrapper = doc.createElement(QStringLiteral("pwbwrapper"));
    doc.appendChild(wrapper);
    renderer->writeXml(doc, wrapper);
    QDomElement raster_elem = wrapper.firstChildElement(
        QStringLiteral("rasterrenderer"));
    if (raster_elem.isNull()) {
        throw std::runtime_error("QGIS raster renderer serialization failed");
    }
    QDomDocument out;
    out.appendChild(out.importNode(raster_elem, /*deep=*/true).toElement());
    return out.toString(-1).toStdString();
}

std::unique_ptr<QgsRasterRenderer> raster_renderer_from_xml(
    const std::string& xml, QgsRasterInterface* input) {
    QDomElement elem = raster_renderer_element(xml);
    if (elem.isNull()) return nullptr;
    const QString renderer_type = elem.attribute(QStringLiteral("type"));
    QgsRasterRendererRegistryEntry entry;
    if (QgsApplication::rasterRendererRegistry()->rendererData(
            renderer_type, entry)
        && entry.rendererCreateFunction) {
        return std::unique_ptr<QgsRasterRenderer>(
            entry.rendererCreateFunction(elem, input));
    }
    // Registry miss (exotic type): singlebandpseudocolor is this codec's own
    // format, so attempting it directly stays within known semantics.
    if (renderer_type == QStringLiteral("singlebandpseudocolor")) {
        return std::unique_ptr<QgsRasterRenderer>(
            QgsSingleBandPseudoColorRenderer::create(elem, input));
    }
    return nullptr;
}

bool apply_raster_renderer_xml(QgsRasterLayer& layer, const std::string& xml) {
    if (xml.empty()) return true;  // nothing to apply, not an error
    auto renderer = raster_renderer_from_xml(xml, layer.dataProvider());
    if (!renderer) return false;
    layer.setRenderer(renderer.release());
    layer.triggerRepaint();
    return true;
}

void validate_raster_renderer_xml(const std::string& xml) {
    QDomElement elem = raster_renderer_element(xml);
    if (elem.isNull()) {
        throw std::runtime_error("invalid raster renderer XML payload");
    }
}

}  // namespace pwb::qgis_render
