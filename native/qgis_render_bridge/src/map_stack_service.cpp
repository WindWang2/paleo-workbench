// pybind11 (and therefore Python.h) must be included BEFORE any Qt/QGIS
// header: Qt redefines `slots`, which corrupts PyType_Spec in object.h.
#include <pybind11/pybind11.h>

#include "map_stack_service.hpp"

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <functional>
#include <mutex>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

#include <QApplication>
#include <QColor>
#include <QCoreApplication>
#include <QDialog>
#include <QDomDocument>
#include <QFile>
#include <QIODevice>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QMap>
#include <QMenu>
#include <QObject>
#include <QPainter>
#include <QPointer>
#include <QSet>
#include <QString>
#include <QTemporaryDir>
#include <QTimer>
#include <QUuid>
#include <QWidget>

#include <qgsapplication.h>
#include <qgstextformat.h>
#include <qgsadvanceddigitizingdockwidget.h>
#include <qgscoordinatereferencesystem.h>
#include <qgscoordinatetransform.h>
#include <qgscompoundcurve.h>
#include <qgsdefaultvalue.h>
#include <qgseditorwidgetsetup.h>
#include <qgsfeature.h>
#include <qgsfield.h>
#include <qgsfieldconstraints.h>
#include <qgsfillsymbol.h>
#include <qgsjsonutils.h>
#include <qgslayertree.h>
#include <qgslayertreelayer.h>
#include <qgslayertreemapcanvasbridge.h>
#include <qgslayertreemodel.h>
#include <qgslayertreeregistrybridge.h>
#include <qgslayertreeview.h>
#include <qgslayertreeviewdefaultactions.h>
#include <qgslayertreeviewindicator.h>
#include <qgslayout.h>
#include <qgslayoutexporter.h>
#include <qgslayoutitemlabel.h>
#include <qgslayoutitemlegend.h>
#include <qgslayoutitemmap.h>
#include <qgslayoutitemmapgrid.h>
#include <qgslayoutitempage.h>
#include <qgslayoutpagecollection.h>
#include <qgslayoutitempicture.h>
#include <qgslayoutitemshape.h>
#include <qgslayoutitemscalebar.h>
#include <qgslayoutpoint.h>
#include <qgslayoutsize.h>
#include <qgsmapcanvas.h>
#include <qgsmaplayer.h>
#include <qgsmaptool.h>
#include <qgsmaptoolcapture.h>
#include <qgsmaptooldigitizefeature.h>
#include <qgsmaptoolidentifyfeature.h>
#include <qgsmaptoolpan.h>
#include <qgsmaptoolzoom.h>
#include <qgsmaptopixel.h>
#include <qgspointxy.h>
#include <qgspointlocator.h>
#include <qgsprintlayout.h>
#include <qgsproject.h>
#include <qgsreadwritecontext.h>
#include <qgsrectangle.h>
#include <qgsrubberband.h>
#include <qgshighlight.h>
#include <qgssnappingconfig.h>
#include <qgssnappingutils.h>
#include <qgssymbol.h>
#include <qgsunittypes.h>
#include <qgsvectorlayer.h>
#include <qgswkbtypes.h>
#include <qgsvectorlayerlabeling.h>
#include <qgsvectorlayerproperties.h>

#include "qgis_render_bridge.hpp"
#include "style_codec.hpp"
#include <qgsrasterlayer.h>
#include <qgsrasterrenderer.h>
#include "edit_tools.hpp"

namespace pwb::qgis_render {

#ifdef PALEO_QGIS_PREFIX_PATH
#undef PALEO_QGIS_PREFIX_PATH
#endif
extern const std::string PALEO_QGIS_PREFIX_PATH;
extern std::mutex g_qgis_lifecycle_mutex;
// #1155: process-level "initQgis ran exactly once" flag owned by
// qgis_render_bridge.cpp; QGIS 4.2 is not safely re-initializable, so every
// initialization path must share this guard.
extern bool g_qgis_initialized;

namespace {

std::string qjsonValueToString(const QJsonValue& v) {
    if (v.isString()) return v.toString().toStdString();
    if (v.isDouble()) {
        double d = v.toDouble();
        if (std::floor(d) == d) return std::to_string(static_cast<long long>(d));
        return QString::number(d, 'g', 12).toStdString();
    }
    if (v.isBool()) return v.toBool() ? "true" : "false";
    return {};
}
// 镜像 fid 映射：从 geojson 原文提取有序 __pwb_fid，与 addFeatures 就地
// 分配的 QgsFeatureId 顺序配对（M3 Task 3；memory provider 不落属性字段）。
void recordMirrorFeatureFids(std::unordered_map<long long, std::string>& table,
                             const QgsFeatureList& flist,
                             const QByteArray& geoBytes) {
    table.clear();
    QStringList ids;
    const QJsonDocument d = QJsonDocument::fromJson(geoBytes);
    if (d.isObject()) {
        const QJsonArray feats =
            d.object().value(QStringLiteral("features")).toArray();
        for (const QJsonValue& fv : feats) {
            ids << fv.toObject()
                      .value(QStringLiteral("properties"))
                      .toObject()
                      .value(QStringLiteral("__pwb_fid"))
                      .toString();
        }
    }
    // 终局审查 M1：OGR 解析会静默丢弃无效要素（下标平移风险）——
    // 数量失配时整表弃用，退化为数值 fid 回落，而不是错位映射。
    if (ids.size() != static_cast<int>(flist.size())) {
        return;
    }
    int i = 0;
    for (const QgsFeature& f : flist) {
        if (i < ids.size() && !ids[i].isEmpty())
            table[static_cast<long long>(f.id())] = ids[i].toStdString();
        ++i;
    }
}

// ---------------------------------------------------------------------------
// V8 M1: fields_json（qgis_layer_schema wire，GeologicalLayerSpec 单一字段
// 权威）→ memory provider 的真实 QgsFields + 约束 + 默认值 + 编辑器控件。
// 桥只应用 schema、绝不发明字段；wire 畸形时抛错（fail-closed），因为
// Python 侧 spec 已验证——能到这里的坏 JSON 只能是编程错误。
// ---------------------------------------------------------------------------
struct FieldSchemaEntry {
    QgsField field;            // 类型/长度/精度 + 字段级约束（provider origin）
    QString alias;
    QString editor_widget;     // 空 = 不设置（沿用 QGIS 默认）
    QVariantMap editor_config;
    QString default_expression;  // 字面量已转 QGIS 表达式
};

QMetaType::Type metaTypeForWireName(const QString& name) {
    if (name == QLatin1String("QString")) return QMetaType::Type::QString;
    if (name == QLatin1String("qlonglong")) return QMetaType::Type::LongLong;
    if (name == QLatin1String("double")) return QMetaType::Type::Double;
    if (name == QLatin1String("bool")) return QMetaType::Type::Bool;
    if (name == QLatin1String("QDateTime")) return QMetaType::Type::QDateTime;
    throw std::invalid_argument(
        "fields_json: unknown field type '" + name.toStdString() + "'");
}

QVariant jsonValueToVariant(const QJsonValue& v) {
    if (v.isString()) return QVariant(v.toString());
    if (v.isDouble()) return QVariant(v.toDouble());
    if (v.isBool()) return QVariant(v.toBool());
    return QVariant();
}

QString defaultLiteralToExpression(const QJsonValue& v) {
    if (v.isBool()) return v.toBool() ? QStringLiteral("true") : QStringLiteral("false");
    if (v.isDouble()) return QString::number(v.toDouble(), 'g', 15);
    // 字符串字面量 → 单引号表达式（内部引号按 QGIS 表达式转义）。
    const QString raw = v.toString();
    QString escaped;
    escaped.reserve(raw.size());
    for (const QChar ch : raw) {
        if (ch == QLatin1Char('\'')) escaped += QStringLiteral("''");
        else escaped += ch;
    }
    return QStringLiteral("'%1'").arg(escaped);
}

QList<FieldSchemaEntry> parseFieldSchema(const std::string& fields_json) {
    QJsonParseError err;
    const QJsonDocument doc = QJsonDocument::fromJson(
        QByteArray::fromStdString(fields_json).trimmed(), &err);
    if (err.error != QJsonParseError::NoError || !doc.isArray()) {
        throw std::invalid_argument(
            "fields_json: malformed wire payload for mirror layer: "
            + err.errorString().toStdString());
    }
    QList<FieldSchemaEntry> entries;
    const QJsonArray array = doc.array();
    for (const QJsonValue& value : array) {
        const QJsonObject obj = value.toObject();
        const QString name = obj.value(QStringLiteral("name")).toString();
        if (name.isEmpty()) {
            throw std::invalid_argument("fields_json: field entry without name");
        }
        FieldSchemaEntry entry;
        entry.field = QgsField(
            name, metaTypeForWireName(obj.value(QStringLiteral("type")).toString()));
        if (obj.contains(QStringLiteral("length"))) {
            entry.field.setLength(obj.value(QStringLiteral("length")).toInt());
        }
        if (obj.contains(QStringLiteral("precision"))) {
            entry.field.setPrecision(obj.value(QStringLiteral("precision")).toInt());
        }
        entry.alias = obj.value(QStringLiteral("alias")).toString();
        if (entry.alias.isEmpty()) entry.alias = name;
        // 字段级约束：随 QgsField 进 provider（ConstraintOriginProvider），
        // QGIS 属性表单按 field.constraints() 强制，与 origin 无关。
        const QJsonObject constraints =
            obj.value(QStringLiteral("constraints")).toObject();
        if (constraints.value(QStringLiteral("not_null")).toBool()) {
            QgsFieldConstraints fc = entry.field.constraints();
            fc.setConstraint(QgsFieldConstraints::ConstraintNotNull,
                             QgsFieldConstraints::ConstraintOriginProvider);
            entry.field.setConstraints(fc);
        }
        if (constraints.value(QStringLiteral("unique")).toBool()) {
            QgsFieldConstraints fc = entry.field.constraints();
            fc.setConstraint(QgsFieldConstraints::ConstraintUnique,
                             QgsFieldConstraints::ConstraintOriginProvider);
            entry.field.setConstraints(fc);
        }
        const QString expr = constraints.value(QStringLiteral("expression")).toString();
        if (!expr.isEmpty()) {
            QgsFieldConstraints fc = entry.field.constraints();
            fc.setConstraintExpression(expr);
            entry.field.setConstraints(fc);
        }
        // 编辑器控件 + 值域配置（ValueMap/Range 的 config 形状与 QGIS 桌面
        // 同名控件一致——style_codec/桌面对话框序列化的形状不漂移）。
        entry.editor_widget = obj.value(QStringLiteral("editor_widget")).toString();
        const QJsonObject domain = obj.value(QStringLiteral("domain")).toObject();
        QVariantMap config;
        if (entry.editor_widget == QLatin1String("ValueMap")) {
            QVariantMap map_config;
            const QJsonObject map = domain.value(QStringLiteral("map")).toObject();
            for (auto it = map.begin(); it != map.end(); ++it) {
                // wire 的 map 是 {值: 值}（identity）——显示文本取键、存储值取值。
                map_config.insert(it.key(), jsonValueToVariant(it.value()));
            }
            config.insert(QStringLiteral("map"), map_config);
        } else if (entry.editor_widget == QLatin1String("Range")) {
            const QJsonArray range = domain.value(QStringLiteral("range")).toArray();
            if (range.size() == 2) {
                config.insert(QStringLiteral("Min"), range.at(0).toDouble());
                config.insert(QStringLiteral("Max"), range.at(1).toDouble());
                config.insert(QStringLiteral("Step"), 1.0);
                config.insert(QStringLiteral("Style"), QStringLiteral("SpinBox"));
            }
        }
        entry.editor_config = config;
        if (obj.contains(QStringLiteral("default"))) {
            entry.default_expression =
                defaultLiteralToExpression(obj.value(QStringLiteral("default")));
        }
        entries.append(entry);
    }
    return entries;
}

QString fieldSchemaSignature(const QList<FieldSchemaEntry>& entries) {
    // 稳定签名（name:type:len:prec|constraints…）——与 pwb/fields_json 属性
    // 一起持久化，重复发布同 schema 时零 provider 抖动。
    QStringList parts;
    for (const FieldSchemaEntry& e : entries) {
        QStringList part;
        part << e.field.name()
             << QString::number(static_cast<int>(e.field.type()))
             << QString::number(e.field.length())
             << QString::number(e.field.precision())
             << e.alias << e.editor_widget << e.default_expression;
        parts << part.join(QStringLiteral(":"));
    }
    return parts.join(QStringLiteral("|"));
}

// 把 schema 应用到镜像层。返回 provider 字段是否发生变化（变化即要求
// 调用方跳过 delta 通道——属性被整体重建，改走全量重发）。
bool applyFieldSchema(QgsVectorLayer& layer,
                      const QList<FieldSchemaEntry>& entries) {
    QgsVectorDataProvider* provider = layer.dataProvider();
    if (provider == nullptr) return false;
    const QgsFields current = layer.fields();
    bool equivalent = current.count() == entries.count();
    if (equivalent) {
        for (int i = 0; i < entries.count(); ++i) {
            if (current.at(i).name() != entries.at(i).field.name()
                || current.at(i).type() != entries.at(i).field.type()) {
                equivalent = false;
                break;
            }
        }
    }
    if (!equivalent) {
        // 镜像层由 host 全量权威重发——字段漂移时整体重建（delete + re-add）
        // 比 per-field changeAttributeType 简单且不会留下半迁移状态。
        QgsAttributeIds drop;
        for (int i = 0; i < current.count(); ++i) drop << i;
        if (!drop.isEmpty()) provider->deleteAttributes(drop);
        layer.updateFields();
        QList<QgsField> fresh;
        for (const FieldSchemaEntry& e : entries) fresh << e.field;
        if (!fresh.isEmpty()) {
            if (!provider->addAttributes(fresh)) {
                throw std::runtime_error(
                    "mirror addAttributes failed for doc_id: "
                    + layer.customProperty(QStringLiteral("pwb/doc_id"))
                          .toString().toStdString());
            }
            layer.updateFields();
        }
    }
    // 图层级配置（alias/widget/default）幂等覆盖——cheap，不做签名短路。
    const QgsFields applied = layer.fields();
    for (const FieldSchemaEntry& e : entries) {
        const int idx = applied.indexOf(e.field.name());
        if (idx < 0) continue;
        layer.setFieldAlias(idx, e.alias);
        if (!e.editor_widget.isEmpty()) {
            layer.setEditorWidgetSetup(
                idx, QgsEditorWidgetSetup(e.editor_widget, e.editor_config));
        }
        if (!e.default_expression.isEmpty()) {
            layer.setDefaultValueDefinition(
                idx, QgsDefaultValue(e.default_expression, false));
        }
    }
    return !equivalent;
}

QgsFeatureList parseGeoJsonFeatures(const QString& text, const QgsFields& fields) {
    // V8 M1：带 schema 解析。不使用 stringToFeatureList(text, fields)——
    // 该 vendored 构建对额外属性按"位置"映射（__pwb_fid 首键错位实测），
    // 因此手工构建要素：几何走 geometryFromGeoJson，属性按名 setAttribute
    // （__pwb_* 侧信道键天然忽略）。无 schema 时保持 QGIS 默认（V7 行为）。
    if (fields.isEmpty()) {
        return QgsJsonUtils::stringToFeatureList(text);
    }
    QJsonParseError json_err{};
    const QJsonDocument doc = QJsonDocument::fromJson(text.toUtf8(), &json_err);
    if (json_err.error != QJsonParseError::NoError || !doc.isObject()) {
        return QgsJsonUtils::stringToFeatureList(text);
    }
    QgsFeatureList out;
    const QJsonArray features =
        doc.object().value(QStringLiteral("features")).toArray();
    for (const QJsonValue& value : features) {
        const QJsonObject feature = value.toObject();
        QgsFeature record(fields);
        const QJsonObject geometry_json =
            feature.value(QStringLiteral("geometry")).toObject();
        if (!geometry_json.isEmpty()) {
            const QgsGeometry geometry = QgsJsonUtils::geometryFromGeoJson(
                QString::fromUtf8(
                    QJsonDocument(geometry_json).toJson(QJsonDocument::Compact)));
            if (!geometry.isNull()) record.setGeometry(geometry);
        }
        const QJsonObject properties =
            feature.value(QStringLiteral("properties")).toObject();
        for (int index = 0; index < fields.count(); ++index) {
            const QString name = fields.at(index).name();
            const QJsonValue property = properties.value(name);
            if (property.isUndefined()) continue;  // 缺省属性 = NULL（诚实）
            QVariant variant;
            switch (fields.at(index).type()) {
              case QMetaType::Type::Double:
                variant = property.toDouble();
                break;
              case QMetaType::Type::LongLong:
              case QMetaType::Type::Int:
                variant = property.isDouble()
                              ? QVariant(static_cast<qint64>(property.toDouble()))
                              : property.toVariant();
                break;
              case QMetaType::Type::Bool:
                variant = property.toBool();
                break;
              case QMetaType::Type::QDateTime:
                variant = QDateTime::fromString(property.toString(), Qt::ISODate);
                break;
              default:
                variant = property.toVariant().toString();
                break;
            }
            record.setAttribute(index, variant);
        }
        if (record.hasGeometry() || !properties.isEmpty()) {
            out.append(record);
        }
    }
    return out;
}

Qgis::SnappingTypes parseSnappingTypes(const QJsonArray& arr) {

    Qgis::SnappingTypes types;
    for (const QJsonValue& v : arr) {
        const QString s = v.toString();
        if (s == QLatin1String("vertex")) types |= Qgis::SnappingType::Vertex;
        else if (s == QLatin1String("segment")) types |= Qgis::SnappingType::Segment;
        else if (s == QLatin1String("midpoint")) types |= Qgis::SnappingType::MiddleOfSegment;
        else if (s == QLatin1String("centroid")) types |= Qgis::SnappingType::Centroid;
        else if (s == QLatin1String("area")) types |= Qgis::SnappingType::Area;
        // V7：线端点（SnappingType::LineEndpoint，QGIS 3.20+）——Python
        // SnappingService 的 endpoint 模式原生投影。
        else if (s == QLatin1String("endpoint")) types |= Qgis::SnappingType::LineEndpoint;
    }
    if (types == Qgis::SnappingTypes()) types = Qgis::SnappingType::Vertex;
    return types;
}

static bool legacy_style_empty(const std::string& s) {
    if (s.empty()) return true;
    QByteArray bytes = QByteArray::fromStdString(s).trimmed();
    if (bytes.isEmpty()) return true;
    if (bytes == "null" || bytes == "{}" || bytes == "[]") return true;
    QJsonParseError err;
    QJsonDocument doc = QJsonDocument::fromJson(bytes, &err);
    if (err.error != QJsonParseError::NoError) return true;
    if (doc.isNull()) return true;
    if (doc.isObject() && doc.object().isEmpty()) return true;
    if (doc.isArray() && doc.array().isEmpty()) return true;
    return false;
}

VectorLayerSpec buildSpecFromLegacyJson(const std::string& rendererXml,
                                        const std::string& labelingXml,
                                        const std::string& legacyJson,
                                        const std::string& layerId) {
    VectorLayerSpec spec;
    spec.id = layerId;
    spec.renderer_xml = rendererXml;
    spec.labeling_xml = labelingXml;
    if (legacyJson.empty()) return spec;
    QJsonDocument doc = QJsonDocument::fromJson(QByteArray::fromStdString(legacyJson));
    if (!doc.isObject()) return spec;
    QJsonObject obj = doc.object();
    if (obj.isEmpty()) return spec;
    if (obj.contains("fill") && obj["fill"].isString())
        spec.fill = obj["fill"].toString().toStdString();
    if (obj.contains("stroke") && obj["stroke"].isString())
        spec.stroke = obj["stroke"].toString().toStdString();
    if (obj.contains("stroke_width")) {
        QJsonValue v = obj["stroke_width"];
        if (v.isDouble()) spec.stroke_width = v.toDouble();
        else if (v.isString()) spec.stroke_width = v.toString().toDouble();
    }
    if (obj.contains("marker_size")) {
        QJsonValue v = obj["marker_size"];
        if (v.isDouble()) spec.marker_size = v.toDouble();
        else if (v.isString()) spec.marker_size = v.toString().toDouble();
    }
    if (obj.contains("marker") && obj["marker"].isString())
        spec.marker = obj["marker"].toString().toStdString();
    if (obj.contains("line_pattern") && obj["line_pattern"].isString())
        spec.line_pattern = obj["line_pattern"].toString().toStdString();
    if (obj.contains("renderer") && obj["renderer"].isString())
        spec.renderer_kind = obj["renderer"].toString().toStdString();
    if (obj.contains("field") && obj["field"].isString())
        spec.classification_field = obj["field"].toString().toStdString();
    if (obj.contains("renderer_xml") && obj["renderer_xml"].isString() && spec.renderer_xml.empty())
        spec.renderer_xml = obj["renderer_xml"].toString().toStdString();
    if (obj.contains("labeling_xml") && obj["labeling_xml"].isString() && spec.labeling_xml.empty())
        spec.labeling_xml = obj["labeling_xml"].toString().toStdString();
    if (obj.contains("categories")) {
        QJsonValue cv = obj["categories"];
        if (cv.isObject()) {
            QJsonObject catObj = cv.toObject();
            for (auto it = catObj.begin(); it != catObj.end(); ++it) {
                std::string value = it.key().toStdString();
                std::string color = it.value().toString().toStdString();
                spec.categories.push_back({value, color, value});
            }
        } else if (cv.isArray()) {
            QJsonArray arr = cv.toArray();
            for (const QJsonValue& entryVal : arr) {
                if (entryVal.isArray()) {
                    QJsonArray entry = entryVal.toArray();
                    if (entry.size() >= 2) {
                        std::string v = qjsonValueToString(entry[0]);
                        std::string c = qjsonValueToString(entry[1]);
                        std::string lbl = entry.size() > 2 ? qjsonValueToString(entry[2]) : v;
                        spec.categories.push_back({v, c, lbl});
                    }
                } else if (entryVal.isObject()) {
                    QJsonObject entry = entryVal.toObject();
                    std::string v = entry.contains("value") ? qjsonValueToString(entry["value"]) : "";
                    std::string c = entry.contains("color") ? qjsonValueToString(entry["color"])
                                  : entry.contains("fill") ? qjsonValueToString(entry["fill"]) : "";
                    std::string lbl = entry.contains("label") ? qjsonValueToString(entry["label"]) : v;
                    if (!v.empty() || !c.empty()) spec.categories.push_back({v, c, lbl});
                }
            }
        }
    }
    if (obj.contains("ranges")) {
        QJsonValue rv = obj["ranges"];
        if (rv.isArray()) {
            QJsonArray arr = rv.toArray();
            for (const QJsonValue& entryVal : arr) {
                if (entryVal.isArray()) {
                    QJsonArray entry = entryVal.toArray();
                    if (entry.size() >= 3) {
                        double lo = entry[0].toDouble();
                        double hi = entry[1].toDouble();
                        std::string color = qjsonValueToString(entry[2]);
                        std::string label = entry.size() > 3 ? qjsonValueToString(entry[3]) : "";
                        spec.ranges.push_back({lo, hi, color, label});
                    }
                } else if (entryVal.isObject()) {
                    QJsonObject entry = entryVal.toObject();
                    double lo = 0, hi = 0;
                    if (entry.contains("lower")) lo = entry["lower"].toDouble();
                    else if (entry.contains("lo")) lo = entry["lo"].toDouble();
                    else if (entry.contains("min")) lo = entry["min"].toDouble();
                    if (entry.contains("upper")) hi = entry["upper"].toDouble();
                    else if (entry.contains("hi")) hi = entry["hi"].toDouble();
                    else if (entry.contains("max")) hi = entry["max"].toDouble();
                    std::string color;
                    if (entry.contains("color")) color = qjsonValueToString(entry["color"]);
                    else if (entry.contains("fill")) color = qjsonValueToString(entry["fill"]);
                    std::string label = entry.contains("label") ? qjsonValueToString(entry["label"]) : "";
                    spec.ranges.push_back({lo, hi, color, label});
                }
            }
        }
    }
    if (obj.contains("rules") && obj["rules"].isArray()) {
        QJsonArray arr = obj["rules"].toArray();
        for (const QJsonValue& entryVal : arr) {
            if (!entryVal.isObject()) continue;
            QJsonObject entry = entryVal.toObject();
            RuleSpec rule;
            if (entry.contains("name")) rule.name = qjsonValueToString(entry["name"]);
            if (entry.contains("expression")) rule.expression = qjsonValueToString(entry["expression"]);
            if (entry.contains("label")) rule.label = qjsonValueToString(entry["label"]);
            else if (entry.contains("name") && rule.label.empty()) rule.label = rule.name;
            if (entry.contains("fill")) rule.fill = qjsonValueToString(entry["fill"]);
            if (entry.contains("stroke")) rule.stroke = qjsonValueToString(entry["stroke"]);
            if (entry.contains("stroke_width")) {
                QJsonValue v = entry["stroke_width"];
                if (v.isDouble()) rule.stroke_width = v.toDouble();
                else if (v.isString()) rule.stroke_width = v.toString().toDouble();
            }
            if (entry.contains("marker_size")) {
                QJsonValue v = entry["marker_size"];
                if (v.isDouble()) rule.marker_size = v.toDouble();
                else if (v.isString()) rule.marker_size = v.toString().toDouble();
            }
            spec.rules.push_back(std::move(rule));
        }
    }
    if (obj.contains("labels") && obj["labels"].isObject()) {
        QJsonObject labels = obj["labels"].toObject();
        bool visible = true;
        if (labels.contains("visible")) {
            QJsonValue vv = labels["visible"];
            if (vv.isBool()) visible = vv.toBool();
            else if (vv.isString()) visible = vv.toString().toLower() != "false" && vv.toString() != "0";
        }
        std::string field;
        if (labels.contains("field") && labels["field"].isString())
            field = labels["field"].toString().toStdString();
        spec.labels_enabled = visible && !field.empty();
        if (labels.contains("field") && labels["field"].isString())
            spec.label_field = field;
        if (labels.contains("font_family") && labels["font_family"].isString())
            spec.label_font_family = labels["font_family"].toString().toStdString();
        if (labels.contains("size")) {
            QJsonValue v = labels["size"];
            if (v.isDouble()) spec.label_size = v.toDouble();
            else if (v.isString()) spec.label_size = v.toString().toDouble();
        }
        if (labels.contains("bold")) {
            QJsonValue v = labels["bold"];
            if (v.isBool()) spec.label_bold = v.toBool();
            else if (v.isString()) spec.label_bold = v.toString().toLower() == "true" || v.toString() == "1";
        }
        if (labels.contains("color") && labels["color"].isString())
            spec.label_color = labels["color"].toString().toStdString();
        if (labels.contains("buffer")) {
            QJsonValue v = labels["buffer"];
            if (v.isDouble()) spec.label_buffer_size = v.toDouble();
            else if (v.isString()) spec.label_buffer_size = v.toString().toDouble();
        } else if (labels.contains("halo_width")) {
            QJsonValue v = labels["halo_width"];
            if (v.isDouble()) spec.label_buffer_size = v.toDouble();
            else if (v.isString()) spec.label_buffer_size = v.toString().toDouble();
        }
        if (labels.contains("buffer_color") && labels["buffer_color"].isString())
            spec.label_buffer_color = labels["buffer_color"].toString().toStdString();
        else if (labels.contains("halo_color") && labels["halo_color"].isString())
            spec.label_buffer_color = labels["halo_color"].toString().toStdString();
        if (labels.contains("rotation_field") && labels["rotation_field"].isString())
            spec.label_rotation_field = labels["rotation_field"].toString().toStdString();
        if (labels.contains("size_field") && labels["size_field"].isString())
            spec.label_size_field = labels["size_field"].toString().toStdString();
        if (labels.contains("color_field") && labels["color_field"].isString())
            spec.label_color_field = labels["color_field"].toString().toStdString();
    }
    return spec;
}

void applyStyleToLayer(QgsVectorLayer& layer, const VectorLayerSpec& spec) {
    validate_style_payloads(spec);
    apply_renderer_style(layer, spec);
    apply_label_style(layer, spec);
}

static std::string makeStyleSig(const std::string& renderer_xml,
                                const std::string& labeling_xml,
                                const std::string& legacy_json) {
    std::string sig;
    sig.reserve(renderer_xml.size() + labeling_xml.size() + legacy_json.size() + 2);
    sig.append(renderer_xml);
    sig.push_back('\x1e');
    sig.append(labeling_xml);
    sig.push_back('\x1e');
    sig.append(legacy_json);
    return sig;
}

}  // namespace

static QgsMapLayer* findMapMirrorByDocId(QgsProject* project, const std::string& doc_id) {
    if (!project || doc_id.empty()) return nullptr;
    const QString key = QStringLiteral("pwb/doc_id");
    const QString target = QString::fromStdString(doc_id);
    for (auto* layer : project->mapLayers().values()) {
        if (layer->customProperty(key).toString() == target) return layer;
    }
    return nullptr;
}

static QgsVectorLayer* findMirrorByDocId(QgsProject* project, const std::string& doc_id) {
    return qobject_cast<QgsVectorLayer*>(findMapMirrorByDocId(project, doc_id));
}

// ------------------------------------------------------------------ V5 groups

namespace {

const char kGroupIdProp[] = "pwb/group_id";


// M2T3 经验：qobject_cast 在 QgsLayerTree* 节点类上不可靠（meta-object 链
// 在 vendored 构建下有缺口）；类型分派一律走 nodeType() 枚举 + static_cast。
inline QgsLayerTreeGroup* treeGroupCast(QgsLayerTreeNode* node) {
    return node != nullptr && node->nodeType() == QgsLayerTreeNode::NodeGroup
        ? static_cast<QgsLayerTreeGroup*>(node)
        : nullptr;
}

inline QgsLayerTreeLayer* treeLayerCast(QgsLayerTreeNode* node) {
    return node != nullptr && node->nodeType() == QgsLayerTreeNode::NodeLayer
        ? static_cast<QgsLayerTreeLayer*>(node)
        : nullptr;
}

// takeChild 的隐藏语义：removeChildrenPrivate 会先递归卸下被移动节点的
// 全部后代（makeOrphan）——直接对带子组的组调用会摧毁子树。此处的
// 后序卸载保证每次 takeChild 时目标节点已无子节点。
struct SubtreeDetachEntry {
    QgsLayerTreeNode* node;
    QList<QgsLayerTreeNode*> children;
};

void detachGroupSubtree(QgsLayerTreeNode* node, QList<SubtreeDetachEntry*>* log) {
    const QList<QgsLayerTreeNode*> children = node->children();
    if (children.isEmpty()) return;
    for (QgsLayerTreeNode* child : children) {
        detachGroupSubtree(child, log);
    }
    for (QgsLayerTreeNode* child : children) {
        node->takeChild(child);  // child 此刻必为叶（无树子节点）
    }
    log->append(new SubtreeDetachEntry{node, children});
}

void restoreGroupSubtree(const QList<SubtreeDetachEntry*>& log) {
    for (const auto* entry : log) {
        auto* group = treeGroupCast(const_cast<QgsLayerTreeNode*>(entry->node));
        if (group == nullptr) continue;
        for (int i = 0; i < entry->children.size(); ++i) {
            group->insertChildNode(i, entry->children.at(i));
        }
    }
}

// #1154 舞步：registry bridge 的移除计数不受 setEnabled 开关控制
//（groupWillRemoveChildren 无条件收集图层 id），takeChild/insertChildNode
// 期间必须把 root 上那两个连接整体断开，析构时原样接回。
struct RegistryBridgeDetach {
    QgsLayerTreeGroup* root = nullptr;
    QgsLayerTreeRegistryBridge* bridge = nullptr;
    bool detached = false;
    bool wasEnabled = false;

    explicit RegistryBridgeDetach(QgsProject* project, QgsLayerTreeGroup* treeRoot)
        : root(treeRoot), bridge(project ? project->layerTreeRegistryBridge() : nullptr) {
        if (bridge == nullptr || root == nullptr) return;
        wasEnabled = bridge->isEnabled();
        if (wasEnabled) bridge->setEnabled(false);
        detached = QObject::disconnect(root, nullptr, bridge, nullptr);
    }

    ~RegistryBridgeDetach() {
        if (bridge == nullptr) return;
        if (detached) {
            QObject::connect(
                root, SIGNAL(willRemoveChildren(QgsLayerTreeNode*,int,int)), bridge,
                SLOT(groupWillRemoveChildren(QgsLayerTreeNode*,int,int)));
            QObject::connect(
                root, SIGNAL(removedChildren(QgsLayerTreeNode*,int,int)), bridge,
                SLOT(groupRemovedChildren()));
        }
        if (wasEnabled) bridge->setEnabled(true);
    }
};

// 递归按稳定 group_id 寻址组节点（custom property，与显示名解耦）。
QgsLayerTreeGroup* findGroupByGroupIdIn(QgsLayerTreeGroup* parent,
                                        const std::string& group_id) {
    if (parent == nullptr || group_id.empty()) return nullptr;
    for (QgsLayerTreeNode* child : parent->children()) {
        auto* group = treeGroupCast(child);
        if (group == nullptr) continue;
        if (group->customProperty(kGroupIdProp).toString().toStdString() == group_id) {
            return group;
        }
        QgsLayerTreeGroup* found = findGroupByGroupIdIn(group, group_id);
        if (found != nullptr) return found;
    }
    return nullptr;
}

// 组节点没有稳定 id 时分配一个（用户在 QGIS 树里新建的组）并返回。
std::string ensureGroupNodeId(QgsLayerTreeGroup* group) {
    if (group == nullptr) return std::string();
    QVariant existing = group->customProperty(kGroupIdProp);
    if (existing.isValid() && !existing.toString().isEmpty()) {
        return existing.toString().toStdString();
    }
    const std::string assigned =
        "user_" + QUuid::createUuid().toString(QUuid::WithoutBraces).toStdString();
    group->setCustomProperty(kGroupIdProp, QString::fromStdString(assigned));
    return assigned;
}

bool isDescendantOf(QgsLayerTreeNode* node, QgsLayerTreeNode* candidate) {
    for (QgsLayerTreeNode* p = node; p != nullptr; p = p->parent()) {
        if (p == candidate) return true;
    }
    return false;
}

void appendNodeToJson(QgsLayerTreeNode* node, QJsonArray* out) {
    if (auto* group = treeGroupCast(node)) {
        QJsonObject obj;
        obj.insert(QStringLiteral("type"), QStringLiteral("group"));
        obj.insert(QStringLiteral("id"), QString::fromStdString(ensureGroupNodeId(group)));
        obj.insert(QStringLiteral("name"), group->name());
        obj.insert(QStringLiteral("visible"), group->itemVisibilityChecked());
        QJsonArray children;
        for (QgsLayerTreeNode* child : group->children()) {
            appendNodeToJson(child, &children);
        }
        obj.insert(QStringLiteral("children"), children);
        out->append(obj);
        return;
    }
    if (auto* layerNode = treeLayerCast(node)) {
        QgsMapLayer* layer = layerNode->layer();
        if (layer == nullptr) return;
        const QString doc = layer->customProperty(QStringLiteral("pwb/doc_id")).toString();
        if (doc.isEmpty()) return;
        QJsonObject obj;
        obj.insert(QStringLiteral("type"), QStringLiteral("layer"));
        obj.insert(QStringLiteral("id"), doc);
        obj.insert(QStringLiteral("name"), layer->name());
        obj.insert(QStringLiteral("visible"), layerNode->itemVisibilityChecked());
        out->append(obj);
    }
}

// V5 typed 树事件（schema 2 events 数组元素）。
void appendTreeEvent(QJsonArray* events, const QString& type, const QString& node_type,
                     const std::string& node_id, bool value) {
    QJsonObject event;
    event.insert(QStringLiteral("type"), type);
    event.insert(QStringLiteral("node_type"), node_type);
    event.insert(QStringLiteral("node_id"), QString::fromStdString(node_id));
    event.insert(QStringLiteral("value"), value);
    events->append(event);
}

void appendTreeEvent(QJsonArray* events, const QString& type, const QString& node_type,
                     const std::string& node_id, const std::string& value) {
    QJsonObject event;
    event.insert(QStringLiteral("type"), type);
    event.insert(QStringLiteral("node_type"), node_type);
    event.insert(QStringLiteral("node_id"), QString::fromStdString(node_id));
    event.insert(QStringLiteral("value"), QString::fromStdString(value));
    events->append(event);
}

}  // namespace

struct QgisMapStack::Impl {
  bool initialized = false;
  bool display_mode = false;
  std::unique_ptr<QgsProject> owned_project;
  std::unordered_map<std::uintptr_t, std::unique_ptr<QgsLayerTreeMapCanvasBridge>>
      tree_bridges;
  std::unordered_set<std::string> owned_layers;
  std::unordered_map<std::uintptr_t, std::unique_ptr<QgsMapTool>> tools;
  std::unordered_map<std::uintptr_t, ExtentCallback> extent_callbacks;
  std::unordered_map<std::uintptr_t, PointCallback> xy_callbacks;
  std::unordered_map<std::uintptr_t, QPointer<QgsMapCanvas>> canvas_refs;
  // 隐藏高级数字化 dock：QgsMapToolCapture 派生链构造有 Q_ASSERT(cadDockWidget)，
  // 每画布一个，永不 show；parent 挂画布随其销毁（M3 Task 1）。
  std::unordered_map<std::uintptr_t, QPointer<QgsAdvancedDigitizingDockWidget>> cad_docks;
  // 采点工具包（M3 Task 2）：每画布 point/line/polygon 三槽，惰性创建。
  // scratch 为桥内私有 memory 层（不进 QgsProject、不落持久化），仅向
  // QgsMapToolDigitizeFeature 提供几何类型/CRS/editable 前置；捕获几何经
  // digitizingCompleted 回调交 Python 权威会话。
  struct CaptureKit {
    std::unique_ptr<QgsVectorLayer> scratch[3];
    QgsMapToolDigitizeFeature* tools[3] = {nullptr, nullptr, nullptr};  // Qt parent 持有
    QgsCoordinateReferenceSystem scratch_crs;
  };
  std::unordered_map<std::uintptr_t, CaptureKit> capture_kits;
  std::unordered_map<std::uintptr_t,
                     std::function<void(const std::string&, const std::string&)>>
      digitize_callbacks;
  // 顶点/移动编辑工具（M3 Task 3；Qt parent=画布持有，指针仅作惰性缓存）
  std::unordered_map<std::uintptr_t, PwbVertexTool*> vertex_tools;
  std::unordered_map<std::uintptr_t, PwbMoveTool*> move_tools;
  std::unordered_map<std::uintptr_t,
                     std::function<void(const std::string&, const std::string&)>>
      edit_pick_callbacks;
  // 选择/identify（M3 Task 4；Qt parent=画布持有）与选中高亮投影
  std::unordered_map<std::uintptr_t, PwbSelectTool*> select_tools;
  std::unordered_map<std::uintptr_t, QgsMapToolIdentifyFeature*> identify_tools;
  std::unordered_map<std::uintptr_t,
                     std::function<void(const std::string&, const std::string&)>>
      selection_callbacks;
  // 测距（V7；Qt parent=画布持有）
  std::unordered_map<std::uintptr_t, PwbMeasureTool*> measure_tools;
  std::unordered_map<std::uintptr_t,
                     std::function<void(const std::string&, const std::string&)>>
      measure_callbacks;
  std::unordered_map<std::uintptr_t, std::vector<std::unique_ptr<QgsHighlight>>>
      highlights;
  std::unordered_map<std::uintptr_t, QMetaObject::Connection> extent_connections;
  std::unordered_map<std::uintptr_t, QMetaObject::Connection> xy_connections;
  // I1: retain rejection after erasing the QPointer tombstone — otherwise the
  // next call would miss in canvas_refs and canvasOrThrow would reinterpret a
  // freed pointer (UAF). The set is bounded by the number of distinct dead
  // addresses not yet reused (cleared on createCanvas reuse and shutdown).
  std::unordered_set<std::uintptr_t> dead_canvas_addrs;
  std::unordered_map<std::uintptr_t, QPointer<QgsLayerTreeView>> tree_views;
  // 树视图创建时的 model 直存（qobject_cast 在该类上不可靠，见 M2T3 调试记录）
  std::unordered_map<std::uintptr_t, QPointer<QgsLayerTreeModel>> tree_models;
  std::unordered_map<std::uintptr_t, std::function<void(const std::string&)>> tree_sel_callbacks;
  std::unordered_map<std::uintptr_t, QMetaObject::Connection> tree_sel_connections;
  // 树变更批次：同 tick 合并，QTimer::singleShot(0) 发批（JSON）
  struct TreeChangeBatch {
    QMap<QString, bool> visibility;
    QStringList order;
    QMap<QString, QString> renames;
    // V5 分组扩展：typed 事件（含组）与结构快照脏标记。
    QJsonArray events;
    bool tree_dirty = false;
    bool empty() const {
      return visibility.isEmpty() && order.isEmpty() && renames.isEmpty()
          && events.isEmpty() && !tree_dirty;
    }
  };
  std::unordered_map<std::uintptr_t, std::function<void(const std::string&)>> tree_change_callbacks;
  std::unordered_map<std::uintptr_t, std::vector<QMetaObject::Connection>> tree_change_connections;
  std::unordered_map<std::uintptr_t, TreeChangeBatch> tree_pending;
  std::unordered_set<std::uintptr_t> tree_flush_scheduled;
  // 组节点展开态回调（V5 StageViewState）。expandedChanged 是节点级信号，
  // 经 wireNodeExpandSignal 接线；去重标记走节点 custom property（随节点
  // 生灭，无悬挂指针），连接随节点析构自灭，shutdown 兜底断开。
  std::unordered_map<std::uintptr_t,
                     std::function<void(const std::string&, bool)>> tree_expand_callbacks;
  std::vector<QMetaObject::Connection> node_expand_connections;
  // 重命名影子表：doc_id -> 最近一次已知图层名；程序化 setName 同步更新，
  // 回调侧据此区分真实重命名与样式刷新等无关 dataChanged。
  std::unordered_map<std::string, std::string> known_layer_names;
  // 可见性影子表：doc_id -> 最近一次已知勾选态；QGIS 用户勾选与刷新都发
  // 空 roles 的 dataChanged，只能靠影子比对区分。
  std::unordered_map<std::string, bool> known_layer_visibility;
  // V5 组影子表：group_id -> 最近一次已知名称/勾选态（与图层表分开，
  // 组 id 与 doc_id 命名空间不同但语义独立更稳）。
  std::unordered_map<std::string, std::string> known_group_names;
  std::unordered_map<std::string, bool> known_group_visibility;
  // 树视图的创建画布（菜单 zoom 动作用）与菜单回调
  std::unordered_map<std::uintptr_t, QPointer<QgsMapCanvas>> tree_canvas;
  std::unordered_map<std::uintptr_t, std::function<void(const std::string&, const std::string&)>>
      tree_menu_callbacks;
  // 孤儿回调坟场：view 的 destroyed 信号里不能销毁含 py::function 的
  // std::function（shiboken 延迟删除链上解释器态不稳，实测 GC_Del segfault），
  // 挪到这里由 shutdown/dtor（绑定层持 GIL 的正常路径）统一销毁。
  std::vector<std::function<void(const std::string&)>> orphan_tree_callbacks;
  std::vector<std::function<void(const std::string&, const std::string&)>>
      orphan_tree_menu_callbacks;
  std::vector<std::function<void(const std::string&, bool)>>
      orphan_tree_expand_callbacks;
  // 画布侧回调坟场（同上理由）：canvas destroyed 链上的 reapCanvasTables
  // 把含 py::function 的回调表 move 进这里，由 shutdown/dtor 统一销毁。
  std::vector<std::function<void(const std::string&, const std::string&)>>
      orphan_digitize_callbacks;
  std::vector<std::function<void(const std::string&, const std::string&)>>
      orphan_edit_pick_callbacks;
  std::vector<std::function<void(const std::string&, const std::string&)>>
      orphan_selection_callbacks;
  std::vector<std::function<void(const std::string&, const std::string&)>>
      orphan_measure_callbacks;
  std::unordered_map<std::string, std::string> mirror_by_doc;
  // 镜像层 QgsFeatureId → 文档 feature_id（M3 Task 3）：memory provider 不落
  // 属性字段，__pwb_fid 由 upsert 时从 geojson 原文与 addFeatures 后的
  // fid 顺序配对重建；reconcile 每次 truncate+add 后整表替换。
  std::unordered_map<std::string, std::unordered_map<long long, std::string>>
      mirror_feature_fids;
      // v7 §9: last-applied host data revision per doc_id (delta channel).
      std::unordered_map<std::string, std::uint64_t> mirror_data_revisions;
  std::unordered_map<std::string, std::string> mirror_style_sig;
  int suppress_tree_callbacks = 0;

  void eraseMirrorByQgisId(const std::string& qgis_id) {
    for (auto it = mirror_by_doc.begin(); it != mirror_by_doc.end(); ) {
      if (it->second == qgis_id) {
        auto sit = mirror_style_sig.find(it->first);
        if (sit != mirror_style_sig.end()) mirror_style_sig.erase(sit);
        known_layer_names.erase(it->first);
        known_layer_visibility.erase(it->first);
        mirror_feature_fids.erase(it->first);
        mirror_data_revisions.erase(it->first);
        it = mirror_by_doc.erase(it);
      } else {
        ++it;
      }
    }
  }

  void eraseMirrorByDocId(const std::string& doc_id) {
    auto dit = mirror_by_doc.find(doc_id);
    if (dit != mirror_by_doc.end()) mirror_by_doc.erase(dit);
    auto sit = mirror_style_sig.find(doc_id);
    if (sit != mirror_style_sig.end()) mirror_style_sig.erase(sit);
    known_layer_names.erase(doc_id);
    known_layer_visibility.erase(doc_id);
    mirror_feature_fids.erase(doc_id);
    mirror_data_revisions.erase(doc_id);
  }

  void eraseMirrorByDocIdIfQgisMatches(const std::string& doc_id,
                                       const std::string& qgis_id) {
    auto dit = mirror_by_doc.find(doc_id);
    if (dit != mirror_by_doc.end() && dit->second == qgis_id) {
      mirror_by_doc.erase(dit);
      auto sit = mirror_style_sig.find(doc_id);
      if (sit != mirror_style_sig.end()) mirror_style_sig.erase(sit);
      known_layer_names.erase(doc_id);
      known_layer_visibility.erase(doc_id);
      mirror_feature_fids.erase(doc_id);
    mirror_data_revisions.erase(doc_id);
    }
  }
};

namespace {
struct SuppressGuard {
    int* counter = nullptr;
    explicit SuppressGuard(int* c) : counter(c) { if (counter) ++(*counter); }
    ~SuppressGuard() { if (counter) --(*counter); }
    SuppressGuard(const SuppressGuard&) = delete;
    SuppressGuard& operator=(const SuppressGuard&) = delete;
};

// 图层树右键菜单 provider：QGIS 默认动作（缩放/要素计数/内联重命名）+
// 自定义动作键经回调上报 Python（删除不走 QGIS 默认 remove——那会绕过文档
// 模型直接删 project 图层，必须经 remove_layer 请求信号走宿主落地）。
class PwbLayerTreeMenuProvider : public QgsLayerTreeViewMenuProvider {
 public:
  PwbLayerTreeMenuProvider(
      QgsLayerTreeView* view, QPointer<QgsMapCanvas> canvas,
      std::function<void(const std::string&, const std::string&)> cb)
      : view_(view), canvas_(std::move(canvas)), cb_(std::move(cb)) {}

  QMenu* createContextMenu() override {
    auto* menu = new QMenu();
    auto* actions = view_->defaultActions();
    // V5：组节点上下文（currentLayer 对组返回 nullptr，先看 currentNode）。
    QgsLayerTreeNode* node = view_->currentNode();
    if (auto* group = treeGroupCast(node)) {
      if (group != view_->layerTreeModel()->rootGroup()) {
        const QString gid = group->customProperty(QStringLiteral("pwb/group_id")).toString();
        if (!canvas_.isNull()) {
          menu->addAction(actions->actionZoomToLayers(canvas_.data(), menu));
        }
        menu->addAction(actions->actionRenameGroupOrLayer(menu));
        const bool isSystemGroup = gid.startsWith(QLatin1String("phase"))
            || gid.startsWith(QLatin1String("factor."))
            || gid.startsWith(QLatin1String("base."))
            || gid.startsWith(QLatin1String("legacy."));
        if (!isSystemGroup) {
          addCustom(menu, QStringLiteral("删除组（保留图层）"), "remove_group",
                    gid.toStdString());
        }
        return menu;
      }
    }
    QgsMapLayer* layer = view_->currentLayer();
    if (layer == nullptr) {
      addCustom(menu, QStringLiteral("新建矢量图层"), "create_layer", nullptr);
      addCustom(menu, QStringLiteral("导入参考图层"), "import_reference", nullptr);
      menu->addSeparator();
      addCustom(menu, QStringLiteral("新建图层组"), "create_group", nullptr);
      return menu;
    }
    const bool isReference =
        layer->customProperty(QStringLiteral("pwb/reference")).toString() == QLatin1String("true");
    const bool isEditable =
        layer->customProperty(QStringLiteral("pwb/editable")).toString() == QLatin1String("true");
    if (!canvas_.isNull()) {
      menu->addAction(actions->actionZoomToLayers(canvas_.data(), menu));
    }
    menu->addAction(actions->actionShowFeatureCount(menu));
    if (isReference) {
      menu->addSeparator();
      addCustom(menu, QStringLiteral("刷新引用（重读源文件）"), "refresh_reference", layer);
      // 勾选态以镜像层属性投影 Python 权威（participates_in_snap →
      // pwb/reference_snap，upsert 时写入），M2 移交项。
      QAction* snap = addCustom(menu, QStringLiteral("参与捕捉"), "toggle_reference_snap", layer);
      snap->setCheckable(true);
      snap->setChecked(
          layer->customProperty(QStringLiteral("pwb/reference_snap")).toString() ==
          QLatin1String("true"));
      addCustom(menu, QStringLiteral("移除引用…"), "remove_reference", layer);
      // QGIS 桌面语义：属性对话框适用于一切图层。引用层的符号 / 标注 /
      // 透明度经镜像层生效并持久化到工程呈现态信封（map_qgis_project_xml）。
      menu->addSeparator();
      addCustom(menu, QStringLiteral("图层属性…"), "properties", layer);
    } else if (isEditable) {
      menu->addSeparator();
      addCustom(menu, QStringLiteral("打开属性表"), "attribute_table", layer);
      addCustom(menu, QStringLiteral("开始/停止编辑"), "toggle_editing", layer);
      menu->addSeparator();
      addCustom(menu, QStringLiteral("图层属性…"), "properties", layer);
      addCustom(menu, QStringLiteral("符号系统…"), "symbology", layer);
      addCustom(menu, QStringLiteral("标注…"), "labeling", layer);
      menu->addSeparator();
      menu->addAction(actions->actionRenameGroupOrLayer(menu));
      addCustom(menu, QStringLiteral("复制图层"), "duplicate", layer);
      addCustom(menu, QStringLiteral("删除图层"), "remove_layer", layer);
      menu->addSeparator();
      addCustom(menu, QStringLiteral("修复无效几何…"), "repair", layer);
      addCustom(menu, QStringLiteral("导出图层…"), "export", layer);
    } else {
      menu->addSeparator();
      menu->addAction(actions->actionRenameGroupOrLayer(menu));
      // 基础工区图层（井位 / 地震工区等）：QGIS 桌面语义同样提供属性
      // 对话框——符号 / 标注 / 透明度经镜像层生效并持久化到呈现态信封。
      menu->addSeparator();
      addCustom(menu, QStringLiteral("图层属性…"), "properties", layer);
    }
    return menu;
  }

 private:
  QAction* addCustom(QMenu* menu, const QString& text, const char* key, QgsMapLayer* layer) {
    std::string doc;
    if (layer != nullptr) {
      doc = layer->customProperty(QStringLiteral("pwb/doc_id")).toString().toStdString();
    }
    return addCustom(menu, text, key, doc);
  }

  QAction* addCustom(QMenu* menu, const QString& text, const char* key,
                     std::string node_id) {
    QAction* action = menu->addAction(text, menu, [this, key = std::string(key),
                                 node_id = std::move(node_id)]() {
      if (!cb_) return;
      cb_(key, node_id);
    });
    return action;
  }

  QgsLayerTreeView* view_;  // provider 由 view 持有（view 析构即销毁），不会悬垂
  QPointer<QgsMapCanvas> canvas_;
  std::function<void(const std::string&, const std::string&)> cb_;
};
}  // namespace

void QgisMapStack::eraseMirrorByQgisId(const std::string& qgis_id) {
  if (impl_) impl_->eraseMirrorByQgisId(qgis_id);
}

void QgisMapStack::eraseMirrorByDocId(const std::string& doc_id) {
  if (impl_) impl_->eraseMirrorByDocId(doc_id);
}

QgisMapStack::QgisMapStack() : impl_(std::make_unique<Impl>()) {}
QgisMapStack::~QgisMapStack() {
  if (!impl_) return;
  // Idempotent. Display path detaches canvases then drops owned_project so
  // QgsMapCanvas::mProject cannot dangle; never instance()->removeAllMapLayers().
  shutdown();
}

QgsProject* QgisMapStack::project() const {
  if (impl_->owned_project) return impl_->owned_project.get();
  return QgsProject::instance();
}

bool QgisMapStack::isDisplay() const noexcept {
  return impl_ && impl_->display_mode;
}

void QgisMapStack::initialize(bool display) {
  if (impl_->initialized) return;
  if (QCoreApplication::instance() == nullptr) {
    throw std::runtime_error("QgisMapStack requires an existing Qt application");
  }
  if (PALEO_QGIS_PREFIX_PATH.empty()) {
    throw std::runtime_error("vendored QGIS prefix is not configured");
  }
  std::lock_guard<std::mutex> lock(g_qgis_lifecycle_mutex);
  // #1155: only QgisRenderBridge::initialize carried the process-level guard;
  // per-instance unconditional init()/initQgis() re-entered QGIS when a
  // QgisRenderBridge (unified canvas) already initialized it.
  if (!g_qgis_initialized) {
    QgsApplication::setPrefixPath(
        QString::fromStdString(PALEO_QGIS_PREFIX_PATH), true);
    QgsApplication::init();
    QgsApplication::initQgis();
    g_qgis_initialized = true;
  }
  if (display) {
    impl_->owned_project = std::make_unique<QgsProject>();
    impl_->display_mode = true;
  }
  impl_->initialized = true;
}

bool QgisMapStack::initialized() const noexcept { return impl_->initialized; }

int QgisMapStack::projectLayerCount() const {
  return static_cast<int>(project()->count());
}

void QgisMapStack::syncCanvasLayers(std::uintptr_t canvas_addr) {
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  auto bit = impl_->tree_bridges.find(canvas_addr);
  if (bit != impl_->tree_bridges.end() && bit->second) {
    bit->second->setCanvasLayers();
    return;
  }
  QList<QgsMapLayer*> layers;
  QgsProject* prj = project();
  if (prj != nullptr) {
    QgsLayerTree* root = prj->layerTreeRoot();
    const QList<QgsMapLayer*> order = root->layerOrder();
    for (QgsMapLayer* layer : order) {
      if (layer == nullptr || !layer->isSpatial()) continue;
      QgsLayerTreeLayer* node = root->findLayer(layer);
      if (node == nullptr || !node->isVisible()) continue;
      layers.append(layer);
    }
  }
  canvas->setLayers(layers);
}

int QgisMapStack::canvasLayerCount(std::uintptr_t canvas_addr) const {
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  return static_cast<int>(canvas->layers().size());
}

void QgisMapStack::shutdown() {
  for (auto& kv : impl_->extent_connections) {
    QObject::disconnect(kv.second);
  }
  impl_->extent_connections.clear();
  for (auto& kv : impl_->xy_connections) {
    QObject::disconnect(kv.second);
  }
  impl_->xy_connections.clear();
  for (auto& kv : impl_->tree_sel_connections) {
    QObject::disconnect(kv.second);
  }
  impl_->tree_sel_connections.clear();
  impl_->tree_sel_callbacks.clear();
  for (auto& kv : impl_->tree_change_connections) {
    for (const auto& conn : kv.second) QObject::disconnect(conn);
  }
  impl_->tree_change_connections.clear();
  impl_->tree_change_callbacks.clear();
  for (const auto& conn : impl_->node_expand_connections) {
    QObject::disconnect(conn);
  }
  impl_->node_expand_connections.clear();
  impl_->tree_expand_callbacks.clear();
  impl_->orphan_tree_expand_callbacks.clear();
  impl_->tree_pending.clear();
  impl_->tree_flush_scheduled.clear();
  impl_->known_layer_names.clear();
  impl_->known_layer_visibility.clear();
  impl_->known_group_names.clear();
  impl_->known_group_visibility.clear();
  impl_->tree_views.clear();
  impl_->tree_models.clear();
  impl_->tree_canvas.clear();
  impl_->tree_menu_callbacks.clear();
  impl_->orphan_tree_callbacks.clear();
  impl_->orphan_tree_menu_callbacks.clear();
  impl_->orphan_digitize_callbacks.clear();
  impl_->orphan_edit_pick_callbacks.clear();
  impl_->orphan_selection_callbacks.clear();
  impl_->orphan_measure_callbacks.clear();
  if (impl_->owned_project) {
    for (auto& kv : impl_->canvas_refs) {
      if (kv.second.isNull()) continue;
      QgsMapCanvas* c = kv.second;
      c->setLayers(QList<QgsMapLayer*>());
      c->setProject(nullptr);
      if (QgsMapTool* tool = c->mapTool()) c->unsetMapTool(tool);
    }
  }
  {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    for (const auto& id : impl_->owned_layers) {
      QgsMapLayer* layer = project()->mapLayer(QString::fromStdString(id));
      if (layer != nullptr) {
        project()->removeMapLayer(layer);
      }
    }
  }
  impl_->owned_layers.clear();
  impl_->mirror_by_doc.clear();
  impl_->mirror_style_sig.clear();
  impl_->suppress_tree_callbacks = 0;
  if (impl_->owned_project) {
    impl_->owned_project->removeAllMapLayers();
    impl_->owned_project.reset();
  }
  impl_->display_mode = false;
  impl_->tree_bridges.clear();
  for (auto& kv : impl_->tools) {
    auto it = impl_->canvas_refs.find(kv.first);
    bool canvasAlive = (it != impl_->canvas_refs.end() && !it->second.isNull());
    if (canvasAlive && kv.second) {
      QgsMapCanvas* c = it->second;
      if (c && c->mapTool() == kv.second.get()) {
        c->unsetMapTool(kv.second.get());
      }
    }
    if (kv.second) kv.second.release();
  }
  impl_->tools.clear();
  impl_->cad_docks.clear();
  // 终局审查 C1：清工具表前解除各画布上激活的桥内编辑/采点工具，
  // 否则 scratch 层随 kit 析构而激活工具的 mLayer 悬垂（UAF）。
  for (auto& kv : impl_->canvas_refs) {
    if (kv.second.isNull()) continue;
    QgsMapCanvas* c = kv.second;
    QgsMapTool* active = c ? c->mapTool() : nullptr;
    if (active == nullptr) continue;
    bool ours = false;
    for (auto& kitKv : impl_->capture_kits) {
      for (QgsMapToolDigitizeFeature* t : kitKv.second.tools)
        ours = ours || t == active;
    }
    auto inTables = [&](const auto& table) {
      for (auto& t : table) ours = ours || t.second == active;
    };
    inTables(impl_->vertex_tools);
    inTables(impl_->move_tools);
    inTables(impl_->select_tools);
    inTables(impl_->identify_tools);
    inTables(impl_->measure_tools);
    if (ours) c->unsetMapTool(active);
  }
  impl_->capture_kits.clear();
  impl_->digitize_callbacks.clear();
  impl_->vertex_tools.clear();
  impl_->move_tools.clear();
  impl_->edit_pick_callbacks.clear();
  impl_->select_tools.clear();
  impl_->identify_tools.clear();
  impl_->selection_callbacks.clear();
  impl_->measure_tools.clear();
  impl_->measure_callbacks.clear();
  impl_->highlights.clear();
  impl_->canvas_refs.clear();
  impl_->dead_canvas_addrs.clear();
  impl_->extent_callbacks.clear();
  impl_->xy_callbacks.clear();
  impl_->initialized = false;
}

QgsMapCanvas* QgisMapStack::canvasOrThrow(std::uintptr_t address) const {
  if (address == 0) throw std::invalid_argument("null canvas address");
  if (impl_->dead_canvas_addrs.find(address) != impl_->dead_canvas_addrs.end()) {
    throw std::invalid_argument("canvas address no longer valid");
  }
  auto it = impl_->canvas_refs.find(address);
  if (it != impl_->canvas_refs.end() && it->second.isNull()) {
    throw std::invalid_argument("canvas address no longer valid");
  }
  auto* canvas = reinterpret_cast<QgsMapCanvas*>(address);
  if (canvas == nullptr) throw std::invalid_argument("null canvas address");
  return canvas;
}

void QgisMapStack::ensureNotStale(std::uintptr_t canvas_addr) {
  if (impl_->dead_canvas_addrs.find(canvas_addr) != impl_->dead_canvas_addrs.end()) {
    throw std::invalid_argument("canvas address no longer valid");
  }
  auto it = impl_->canvas_refs.find(canvas_addr);
  if (it != impl_->canvas_refs.end() && it->second.isNull()) {
    auto toolIt = impl_->tools.find(canvas_addr);
    if (toolIt != impl_->tools.end() && toolIt->second) {
      toolIt->second.release();
    }
    impl_->tools.erase(canvas_addr);
    auto ecIt = impl_->extent_connections.find(canvas_addr);
    if (ecIt != impl_->extent_connections.end()) {
      QObject::disconnect(ecIt->second);
      impl_->extent_connections.erase(ecIt);
    }
    auto xcIt = impl_->xy_connections.find(canvas_addr);
    if (xcIt != impl_->xy_connections.end()) {
      QObject::disconnect(xcIt->second);
      impl_->xy_connections.erase(xcIt);
    }
    impl_->extent_callbacks.erase(canvas_addr);
    impl_->xy_callbacks.erase(canvas_addr);
    impl_->tree_bridges.erase(canvas_addr);
    // I1: erase the QPointer tombstone to prevent unbounded growth; retain
    // rejection via dead_canvas_addrs so a subsequent call with the same
    // freed address cannot be reinterpreted (UAF). The alternative of simply
    // erasing without dead-set would make the next canvasOrThrow miss and
    // reinterpret a dangling pointer.
    impl_->canvas_refs.erase(it);
    impl_->dead_canvas_addrs.insert(canvas_addr);
    throw std::invalid_argument("canvas address no longer valid");
  }
}

std::uintptr_t QgisMapStack::createCanvas() {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  auto* canvas = new QgsMapCanvas();
  const std::uintptr_t addr = reinterpret_cast<std::uintptr_t>(canvas);
  // Qt 树析构直接销毁画布（无 orderly destroyCanvas）时只回收桥表：
  // 半析构的 QgsMapCanvas 上调用 unsetMapTool 等会踩悬空子对象（UAF），
  // 因此这条路径绝不触碰画布本身；工具由 Qt 父子树销毁，release() 防双删。
  std::weak_ptr<char> alive = alive_token_;
  QObject::connect(canvas, &QObject::destroyed,
                   [this, alive, addr]() {
                     if (alive.expired()) return;  // 栈先亡：impl_ 不可达
                     // 回调表里的 std::function 持有 Python 对象；destroyed
                     // 可能从无 GIL 的线程发出，先取 GIL 再擦表。
                     pybind11::gil_scoped_acquire gil;
                     reapCanvasTables(addr);
                   });
  canvas->setCanvasColor(Qt::white);
  canvas->enableAntiAliasing(true);
  if (impl_->display_mode) {
    canvas->setProject(project());
  } else {
    auto tree_bridge = std::make_unique<QgsLayerTreeMapCanvasBridge>(
        project()->layerTreeRoot(), canvas);
    tree_bridge->setCanvasLayers();
    impl_->tree_bridges.emplace(addr, std::move(tree_bridge));
    impl_->canvas_refs[addr] = canvas;
    // 永不显示（真机回归：QDockWidget 非浮动子控件会随父画布 show 一起被
    // Qt 递归显示）；enable()/activateCad 的 mSessionActive 门仍可绕过，
    // 但我们从不开启 CAD 会话。
    auto* cadDock = new QgsAdvancedDigitizingDockWidget(canvas, canvas);
    cadDock->hide();
    impl_->cad_docks[addr] = cadDock;
    impl_->dead_canvas_addrs.erase(addr);
    return addr;
  }
  impl_->canvas_refs[addr] = canvas;
  impl_->dead_canvas_addrs.erase(addr);
  canvas->setMapTool(new QgsMapToolPan(canvas));
  return addr;
}

void QgisMapStack::destroyCanvas(std::uintptr_t canvas_addr) {
  auto it = impl_->canvas_refs.find(canvas_addr);
  if (it == impl_->canvas_refs.end()) return;
  // Disconnect callbacks
  auto ecIt = impl_->extent_connections.find(canvas_addr);
  if (ecIt != impl_->extent_connections.end()) {
    QObject::disconnect(ecIt->second);
    impl_->extent_connections.erase(ecIt);
  }
  auto xcIt = impl_->xy_connections.find(canvas_addr);
  if (xcIt != impl_->xy_connections.end()) {
    QObject::disconnect(xcIt->second);
    impl_->xy_connections.erase(xcIt);
  }
  impl_->extent_callbacks.erase(canvas_addr);
  impl_->xy_callbacks.erase(canvas_addr);
  // 只有画布仍活着（orderly 关闭）才允许解除激活工具；Qt 析构期间的
  // 销毁路径进不来这里——Python 侧 destroyed 钩子只做状态记账，桥内
  // destroyed 连接走 reapCanvasTables（无解引用）。
  if (!it->second.isNull()) {
    QgsMapCanvas* c = it->second;
    // Remove tool (Qt parent owns it — always release, never delete via unique_ptr)
    auto toolIt = impl_->tools.find(canvas_addr);
    if (toolIt != impl_->tools.end() && toolIt->second &&
        c && c->mapTool() == toolIt->second.get()) {
      c->unsetMapTool(toolIt->second.get());
    }
    // 终局审查 C1：桥内编辑/采点工具 parent=画布，清表前先解除激活——
    // 否则 scratch 层随 kit 析构而激活工具的 mLayer 悬垂（UAF）。
    QgsMapTool* active = c ? c->mapTool() : nullptr;
    if (active != nullptr) {
      bool ours = false;
      auto kitIt = impl_->capture_kits.find(canvas_addr);
      if (kitIt != impl_->capture_kits.end()) {
        for (QgsMapToolDigitizeFeature* t : kitIt->second.tools)
          ours = ours || t == active;
      }
      auto inTable = [&](const auto& table) {
        auto tIt = table.find(canvas_addr);
        return tIt != table.end() && tIt->second == active;
      };
      ours = ours || inTable(impl_->vertex_tools) || inTable(impl_->move_tools) ||
             inTable(impl_->select_tools) || inTable(impl_->identify_tools) ||
             inTable(impl_->measure_tools);
      if (ours) c->unsetMapTool(active);
    }
  }
  reapCanvasTables(canvas_addr);
}

void QgisMapStack::reapCanvasTables(std::uintptr_t canvas_addr) {
  // 纯表清理，绝不解引用画布：canvas 可能已亡或正析构。工具由 Qt 父子树
  // 负责销毁，unique_ptr 一律 release() 防双删。
  auto toolIt = impl_->tools.find(canvas_addr);
  if (toolIt != impl_->tools.end()) {
    if (toolIt->second) toolIt->second.release();
    impl_->tools.erase(toolIt);
  }
  // Remove bridge; canvas lifetime is owned by Qt parent hierarchy,
  // so we do not delete the QWidget here (avoids double-free with
  // QgisCanvasHost layout).
  impl_->tree_bridges.erase(canvas_addr);
  impl_->cad_docks.erase(canvas_addr);  // Qt 父子关系负责销毁（parent=canvas）
  impl_->capture_kits.erase(canvas_addr);
  {
    // 含 py::function 的回调表不在这里销毁：canvas destroyed 链上解释器
    // 态不稳（与 orphan_tree 坟场同理由），move 进坟场由 shutdown/dtor
    // 统一释放（绑定层持 GIL 的正常路径）。
    if (auto it = impl_->digitize_callbacks.find(canvas_addr);
        it != impl_->digitize_callbacks.end()) {
      impl_->orphan_digitize_callbacks.push_back(std::move(it->second));
      impl_->digitize_callbacks.erase(it);
    }
    if (auto it = impl_->edit_pick_callbacks.find(canvas_addr);
        it != impl_->edit_pick_callbacks.end()) {
      impl_->orphan_edit_pick_callbacks.push_back(std::move(it->second));
      impl_->edit_pick_callbacks.erase(it);
    }
    if (auto it = impl_->selection_callbacks.find(canvas_addr);
        it != impl_->selection_callbacks.end()) {
      impl_->orphan_selection_callbacks.push_back(std::move(it->second));
      impl_->selection_callbacks.erase(it);
    }
    if (auto it = impl_->measure_callbacks.find(canvas_addr);
        it != impl_->measure_callbacks.end()) {
      impl_->orphan_measure_callbacks.push_back(std::move(it->second));
      impl_->measure_callbacks.erase(it);
    }
  }
  impl_->vertex_tools.erase(canvas_addr);
  impl_->move_tools.erase(canvas_addr);
  impl_->select_tools.erase(canvas_addr);
  impl_->identify_tools.erase(canvas_addr);
  impl_->measure_tools.erase(canvas_addr);
  impl_->highlights.erase(canvas_addr);
  impl_->canvas_refs.erase(canvas_addr);
  // 终局审查 M5：销毁后的地址必须留在 dead-set（拒绝后续同地址调用把
  // 已亡指针 reinterpret 成活画布）；新画布复用地址时 createCanvas 自清。
  impl_->dead_canvas_addrs.insert(canvas_addr);
}

void QgisMapStack::setCanvasWhiteBackground(std::uintptr_t canvas) {
  canvasOrThrow(canvas)->setCanvasColor(Qt::white);
}

void QgisMapStack::setDestinationCrs(std::uintptr_t canvas, const std::string& crs) {
  canvasOrThrow(canvas)->setDestinationCrs(
      QgsCoordinateReferenceSystem(QString::fromStdString(crs)));
}

void QgisMapStack::setCanvasExtent(std::uintptr_t canvas, double xmin, double ymin,
                                   double xmax, double ymax) {
  // #1165: NaN/inf extents (e.g. zoom_by(inf) on the Python side) went
  // straight into QgsRectangle and poisoned every derived transform; reject
  // them like the render-bridge path does with normalized_extent.
  const bool finite = std::isfinite(xmin) && std::isfinite(ymin)
      && std::isfinite(xmax) && std::isfinite(ymax);
  if (!finite || xmax < xmin || ymax < ymin) {
    throw std::invalid_argument("canvas extent must be finite and ordered");
  }
  canvasOrThrow(canvas)->setExtent(QgsRectangle(xmin, ymin, xmax, ymax));
}

std::vector<double> QgisMapStack::canvasExtent(std::uintptr_t canvas) const {
  const QgsRectangle r = canvasOrThrow(canvas)->extent();
  return {r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum()};
}

void QgisMapStack::zoomToFullExtent(std::uintptr_t canvas) {
  canvasOrThrow(canvas)->zoomToFullExtent();
}
void QgisMapStack::zoomToPreviousExtent(std::uintptr_t canvas) {
  canvasOrThrow(canvas)->zoomToPreviousExtent();
}
void QgisMapStack::zoomToNextExtent(std::uintptr_t canvas) {
  canvasOrThrow(canvas)->zoomToNextExtent();
}
void QgisMapStack::refreshCanvas(std::uintptr_t canvas) {
  // #1156: refresh() starts the canvas's normal asynchronous render. The
  // previous waitWhileRendering()+processEvents() pair ran a nested event
  // pump deep inside the C++ call stack: extentsChanged re-entered Python
  // callbacks, and window destruction re-entered shutdown()/destroy_canvas()
  // on the same QgisMapStack mid-refresh. Callers that need a finished frame
  // pump the (outer) event loop or poll isCanvasRendering.
  QgsMapCanvas* c = canvasOrThrow(canvas);
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
  c->refresh();
}

bool QgisMapStack::isCanvasRendering(std::uintptr_t canvas) const {
  return canvasOrThrow(canvas)->isDrawing();
}

std::vector<double> QgisMapStack::screenToMap(std::uintptr_t canvas, double x, double y) const {
  // #1165：NaN/inf 与 extent 同样禁止进入坐标换算。
  if (!std::isfinite(x) || !std::isfinite(y)) {
    throw std::invalid_argument("screen coordinates must be finite");
  }
  // double 重载不截断亚像素坐标（M2 移交项：int 截断会吃掉 <1px 精度）。
  const QgsPointXY p = canvasOrThrow(canvas)->getCoordinateTransform()->toMapCoordinates(x, y);
  return {p.x(), p.y()};
}

std::vector<double> QgisMapStack::mapToScreen(std::uintptr_t canvas, double x, double y) const {
  if (!std::isfinite(x) || !std::isfinite(y)) {
    throw std::invalid_argument("map coordinates must be finite");
  }
  const QgsPointXY p = canvasOrThrow(canvas)->getCoordinateTransform()->transform(
      QgsPointXY(x, y));
  return {p.x(), p.y()};
}

std::string QgisMapStack::addVectorLayerGeoJson(
    const std::string& name, const std::string& geometry_type,
    const std::string& crs_auth_id, const std::string& geojson,
    const std::string& renderer_xml, const std::string& labeling_xml,
    const std::string& legacy_style_json) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  const QString uri = QStringLiteral("%1?crs=%2")
      .arg(QString::fromStdString(geometry_type), QString::fromStdString(crs_auth_id));
  auto layer = std::make_unique<QgsVectorLayer>(
      uri, QString::fromStdString(name), QStringLiteral("memory"));
  if (!layer->isValid()) throw std::runtime_error("memory layer creation failed: " + name);

  QgsFeatureList features = QgsJsonUtils::stringToFeatureList(
      QString::fromStdString(geojson));
  if (!features.isEmpty()) {
    layer->dataProvider()->addFeatures(features);
    layer->updateExtents();
  }
  bool hasStyle = !renderer_xml.empty() || !labeling_xml.empty() || !legacy_style_json.empty();
  const bool legacyIsEmpty = legacy_style_empty(legacy_style_json);
  if (hasStyle && (!renderer_xml.empty() || !labeling_xml.empty() || !legacyIsEmpty)) {
    VectorLayerSpec spec = buildSpecFromLegacyJson(renderer_xml, labeling_xml, legacy_style_json, name);
    spec.id = layer->id().toStdString();
    if (spec.id.empty()) spec.id = name;
    applyStyleToLayer(*layer, spec);
  }
  const std::string id = layer->id().toStdString();
  project()->addMapLayer(layer.release());
  impl_->owned_layers.insert(id);
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
  return id;
}

void QgisMapStack::setLayerStyle(const std::string& layer_id,
                                 const std::string& renderer_xml,
                                 const std::string& labeling_xml,
                                 const std::string& legacy_style_json) {
  QgsMapLayer* base = project()->mapLayer(QString::fromStdString(layer_id));
  if (base == nullptr) throw std::invalid_argument("unknown layer: " + layer_id);
  auto* layer = dynamic_cast<QgsVectorLayer*>(base);
  if (layer == nullptr) throw std::invalid_argument("layer is not a vector layer: " + layer_id);
  bool hasStyle = !renderer_xml.empty() || !labeling_xml.empty() || !legacy_style_json.empty();
  const bool legacyIsEmpty = legacy_style_empty(legacy_style_json);
  if (!hasStyle || (renderer_xml.empty() && labeling_xml.empty() && legacyIsEmpty)) {
    return;
  }
  VectorLayerSpec spec = buildSpecFromLegacyJson(renderer_xml, labeling_xml, legacy_style_json, layer_id);
  spec.id = layer_id;
  applyStyleToLayer(*layer, spec);
  layer->triggerRepaint();
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
}

bool QgisMapStack::removeLayer(const std::string& layer_id) {
  auto it = impl_->owned_layers.find(layer_id);
  if (it == impl_->owned_layers.end()) return false;
  QgsMapLayer* layer = project()->mapLayer(
      QString::fromStdString(layer_id));
  if (layer == nullptr) {
    impl_->owned_layers.erase(it);
    eraseMirrorByQgisId(layer_id);
    return false;
  }
  QVariant docVar = layer->customProperty(QStringLiteral("pwb/doc_id"));
  std::string doc_id = docVar.isValid() ? docVar.toString().toStdString() : "";
  {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    project()->removeMapLayer(layer);
  }
  impl_->owned_layers.erase(it);
  if (!doc_id.empty()) {
    impl_->eraseMirrorByDocIdIfQgisMatches(doc_id, layer_id);
  } else {
    eraseMirrorByQgisId(layer_id);
  }
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
  return true;
}

void QgisMapStack::setLayerVisibility(const std::string& layer_id, bool visible) {
  QgsMapLayer* layer = project()->mapLayer(QString::fromStdString(layer_id));
  if (layer == nullptr) throw std::invalid_argument("unknown layer: " + layer_id);
  QgsLayerTreeLayer* node = project()->layerTreeRoot()->findLayer(layer);
  if (node != nullptr) {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    node->setItemVisibilityChecked(visible);
  }
  const QVariant docVar = layer->customProperty(QStringLiteral("pwb/doc_id"));
  if (docVar.isValid() && !docVar.toString().isEmpty()) {
    impl_->known_layer_visibility[docVar.toString().toStdString()] = visible;
  }
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
}

void QgisMapStack::setLayerOpacity(const std::string& layer_id, double opacity) {
  QgsMapLayer* layer = project()->mapLayer(QString::fromStdString(layer_id));
  if (layer == nullptr) throw std::invalid_argument("unknown layer: " + layer_id);
  layer->setOpacity(std::clamp(opacity, 0.0, 1.0));
}

void QgisMapStack::clearProjectLayers() {
  std::vector<std::string> empty;
  removeMirrorLayersExcept(empty);
}

bool QgisMapStack::applyMirrorFeatureDelta(QgsVectorLayer& layer,
                                           const std::string& doc_id,
                                           const std::string& delta_json,
                                           std::uint64_t new_revision) {
  QJsonParseError err{};
  const QJsonDocument doc = QJsonDocument::fromJson(
      QByteArray::fromStdString(delta_json), &err);
  if (err.error != QJsonParseError::NoError || !doc.isObject()) return false;
  const QJsonObject payload = doc.object();
  bool ok = false;
  const std::uint64_t base = static_cast<std::uint64_t>(
      payload.value(QStringLiteral("base_revision")).toVariant().toULongLong(&ok));
  if (!ok) return false;
  const auto revIt = impl_->mirror_data_revisions.find(doc_id);
  if (revIt == impl_->mirror_data_revisions.end() || revIt->second != base) {
    return false;  // concurrent reset — caller ships the full collection
  }
  QgsVectorDataProvider* provider = layer.dataProvider();
  if (provider == nullptr) return false;

  // host id → qgis fid from the recorded table (fid → host id)
  std::unordered_map<std::string, long long> host_to_fid;
  for (const auto& [fid, host] : impl_->mirror_feature_fids[doc_id]) {
    host_to_fid.emplace(host, fid);
  }
  QgsFeatureIds remove_ids;
  for (const QJsonValue& removed :
       payload.value(QStringLiteral("removed_ids")).toArray()) {
    const auto it = host_to_fid.find(removed.toString().toStdString());
    if (it != host_to_fid.end()) remove_ids << it->second;
  }
  const QJsonArray changed = payload.value(QStringLiteral("changed")).toArray();
  // #1153 discipline: any kind drift forces the full path (the memory
  // provider's geometry type is fixed at creation).
  for (const QJsonValue& value : changed) {
    const QString type = value.toObject()
                             .value(QStringLiteral("geometry"))
                             .toObject()
                             .value(QStringLiteral("type"))
                             .toString();
    if (!type.isEmpty()) {
      const Qgis::GeometryType kind =
          QgsWkbTypes::geometryType(QgsWkbTypes::flatType(
              QgsWkbTypes::parseType(type)));
      if (kind != layer.geometryType() && kind != Qgis::GeometryType::Unknown) {
        return false;
      }
    }
  }
  for (const QJsonValue& value : changed) {
    const auto it = host_to_fid.find(
        value.toObject()
            .value(QStringLiteral("properties"))
            .toObject()
            .value(QStringLiteral("__pwb_fid"))
            .toString()
            .toStdString());
    if (it != host_to_fid.end()) remove_ids << it->second;
  }
  if (!remove_ids.isEmpty()) {
    if (!provider->deleteFeatures(remove_ids)) return false;
  }
  QgsFeatureList add_list;
  QStringList changed_ids;
  for (const QJsonValue& value : changed) {
    changed_ids << value.toObject()
                    .value(QStringLiteral("properties"))
                    .toObject()
                    .value(QStringLiteral("__pwb_fid"))
                    .toString();
    QJsonObject single;
    single.insert(QStringLiteral("type"), QStringLiteral("FeatureCollection"));
    QJsonArray single_features;
    single_features.append(value);
    single.insert(QStringLiteral("features"), single_features);
    // V8 M1: delta 重加的要素也按层内 typed 字段解析（调用前 schema 已应用）。
    const QgsFeatureList one = parseGeoJsonFeatures(
        QString::fromUtf8(QJsonDocument(single).toJson()), layer.fields());
    if (!one.isEmpty()) add_list.append(one);
  }
  if (!add_list.isEmpty()) {
    if (!provider->addFeatures(add_list)) return false;
  }
  // Maintain the fid table exactly like recordMirrorFeatureFids would after
  // a full ship: drop removed entries, append addFeatures-assigned fids in
  // order paired with the JSON __pwb_fid sequence.
  auto& table = impl_->mirror_feature_fids[doc_id];
  for (const QgsFeatureId fid : remove_ids) table.erase(static_cast<long long>(fid));
  if (changed_ids.size() == static_cast<int>(add_list.size())) {
    for (int index = 0; index < changed_ids.size(); ++index) {
      if (!changed_ids.at(index).isEmpty()) {
        table[static_cast<long long>(add_list.at(index).id())] =
            changed_ids.at(index).toStdString();
      }
    }
  } else {
    // count mismatch (OGR dropped a malformed feature): drop the whole
    // table — numeric fid fallback beats a shifted mapping (M1 discipline).
    // v7 R2-F6: also drop the recorded revision so the next publish takes
    // the full path; otherwise later deltas would resolve zero deletes and
    // re-add — accumulating duplicates until a coincidental full ship.
    table.clear();
    impl_->mirror_data_revisions.erase(doc_id);
  }
  layer.updateExtents();
  impl_->mirror_data_revisions[doc_id] = new_revision;
  return true;
}

std::string QgisMapStack::upsertMirrorLayer(const std::string& doc_id,
                                            const std::string& name,
                                            const std::string& geometry_type,
                                            const std::string& crs_auth_id,
                                            const std::string& geojson_feature_collection,
                                            const std::string& renderer_xml,
                                            const std::string& labeling_xml,
                                            const std::string& legacy_style_json,
                                            bool visible,
                                            double opacity,
                                            bool is_reference,
                                            bool is_editable,
                                            bool reference_snap,
                                            std::uint64_t data_revision,
                                            const std::string& delta_json,
                                            const std::string& fields_json) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  if (doc_id.empty()) throw std::invalid_argument("doc_id must not be empty");
  const QByteArray geoBytes = QByteArray::fromStdString(geojson_feature_collection).trimmed();
  if (geoBytes.isEmpty()) throw std::invalid_argument("geojson must not be empty for doc_id: " + doc_id);
  QgsProject* project = this->project();
  QgsVectorLayer* existing = nullptr;
  std::string existing_id;
  auto mapIt = impl_->mirror_by_doc.find(doc_id);
  if (mapIt != impl_->mirror_by_doc.end()) {
    QgsMapLayer* base = project->mapLayer(QString::fromStdString(mapIt->second));
    if (base) {
      existing = qobject_cast<QgsVectorLayer*>(base);
      if (existing) {
        existing_id = mapIt->second;
      } else {
        impl_->eraseMirrorByDocId(doc_id);
      }
    } else {
      impl_->eraseMirrorByDocId(doc_id);
    }
  }
  if (!existing) {
    existing = findMirrorByDocId(project, doc_id);
    if (existing) {
      existing_id = existing->id().toStdString();
      impl_->mirror_by_doc[doc_id] = existing_id;
      impl_->owned_layers.insert(existing_id);
    }
  }
  if (existing) {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    QgsFeatureList features = QgsJsonUtils::stringToFeatureList(
        QString::fromStdString(geojson_feature_collection));
    // #1153: a memory layer's provider geometry type is fixed at creation;
    // if the payload drifted (doc_id unchanged but geometries changed kind),
    // reusing the layer would truncate it and then reject every mismatched
    // feature — silently emptying the mirror. Rebuild instead.
    for (const QgsFeature& feature : features) {
      if (feature.hasGeometry()
          && QgsWkbTypes::geometryType(feature.geometry().wkbType())
                 != existing->geometryType()) {
        impl_->eraseMirrorByDocId(doc_id);
        existing = nullptr;
        break;
      }
    }
  }
  if (existing) {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    // V8 M1: 先应用 spec 字段 schema——delta 通道与全量重发都必须在 typed
    // provider 字段上解析 features，GeoJSON properties 才真正落为属性。
    bool schema_changed = false;
    if (!fields_json.empty()) {
      const QList<FieldSchemaEntry> schema = parseFieldSchema(fields_json);
      schema_changed = applyFieldSchema(*existing, schema);
      existing->setCustomProperty(QStringLiteral("pwb/fields_json"),
                                  QString::fromStdString(fields_json));
      existing->setCustomProperty(QStringLiteral("pwb/fields_sig"),
                                  fieldSchemaSignature(schema));
    } else if (!existing->customProperty(QStringLiteral("pwb/fields_json"))
                    .toString().isEmpty()) {
      // 角色回退（legacy 无 schema 路径）且此前 schema 化过：这是 schema
      // 漂移到"无"——provider 字段一并重建（否则残留列全部变 NULL 的假象），
      // 并清掉过期声明属性。
      QgsAttributeIds drop;
      const QgsFields current = existing->fields();
      for (int i = 0; i < current.count(); ++i) drop << i;
      if (!drop.isEmpty() && existing->dataProvider() != nullptr) {
        existing->dataProvider()->deleteAttributes(drop);
        existing->updateFields();
      }
      existing->removeCustomProperty(QStringLiteral("pwb/fields_json"));
      existing->removeCustomProperty(QStringLiteral("pwb/fields_sig"));
      schema_changed = true;  // 全量重发（typed → legacy 的属性丢弃语义）
    }
    // v7 §9: delta channel — delete+re-add only the changed features when
    // the mirror provably holds base_revision (offscreen #932 semantics).
    // V8 M1: schema 重建后属性列已整体换血，delta 的 delete+re-add 会丢未
    // 变更要素的属性——强制走全量路径。
    bool delta_applied = false;
    if (!delta_json.empty() && data_revision != 0 && !schema_changed) {
      delta_applied = applyMirrorFeatureDelta(*existing, doc_id, delta_json,
                                              data_revision);
    }
    QgsFeatureList features;
    if (!delta_applied) {
      features = parseGeoJsonFeatures(
          QString::fromStdString(geojson_feature_collection), existing->fields());
      if (existing->dataProvider()) {
        if (!existing->dataProvider()->truncate()) {
          throw std::runtime_error("mirror truncate failed for doc_id: " + doc_id);
        }
      }
      if (!features.isEmpty()) {
        if (existing->dataProvider() == nullptr
            || !existing->dataProvider()->addFeatures(features)) {
          throw std::runtime_error("mirror addFeatures failed for doc_id: " + doc_id);
        }
      }
      recordMirrorFeatureFids(impl_->mirror_feature_fids[doc_id], features, geoBytes);
      if (data_revision != 0) {
        impl_->mirror_data_revisions[doc_id] = data_revision;
      } else {
        impl_->mirror_data_revisions.erase(doc_id);
      }
    }
    existing->updateExtents();
    std::string new_sig = makeStyleSig(renderer_xml, labeling_xml, legacy_style_json);
    auto sigIt = impl_->mirror_style_sig.find(doc_id);
    bool sig_changed = (sigIt == impl_->mirror_style_sig.end() || sigIt->second != new_sig);
    if (sig_changed) {
      bool hasStyle = !renderer_xml.empty() || !labeling_xml.empty() || !legacy_style_json.empty();
      const bool legacyIsEmpty = legacy_style_empty(legacy_style_json);
      if (hasStyle && (!renderer_xml.empty() || !labeling_xml.empty() || !legacyIsEmpty)) {
        VectorLayerSpec spec = buildSpecFromLegacyJson(renderer_xml, labeling_xml, legacy_style_json, existing_id);
        spec.id = existing_id;
        if (spec.id.empty()) spec.id = doc_id;
        applyStyleToLayer(*existing, spec);
      }
      impl_->mirror_style_sig[doc_id] = new_sig;
      // sig 双存：Impl::mirror_style_sig 是快速比对主源；customProperty
      // pwb/style_sig 供跨边界检视/调试，两者由本函数统一写入保持一致。
      existing->setCustomProperty(QStringLiteral("pwb/style_sig"), QString::fromStdString(new_sig));
    }
    existing->setName(QString::fromStdString(name));
    impl_->known_layer_names[doc_id] = name;  // 程序化改名：同步影子表防误报
    existing->setOpacity(std::clamp(opacity, 0.0, 1.0));
    existing->setCustomProperty(QStringLiteral("pwb/reference"),
                                is_reference ? QStringLiteral("true") : QString());
    existing->setCustomProperty(QStringLiteral("pwb/editable"),
                                is_editable ? QStringLiteral("true") : QString());
    existing->setCustomProperty(QStringLiteral("pwb/reference_snap"),
                                reference_snap ? QStringLiteral("true") : QString());
    QgsLayerTreeLayer* node = project->layerTreeRoot()->findLayer(existing);
    if (node) node->setItemVisibilityChecked(visible);
    impl_->known_layer_visibility[doc_id] = visible;
    impl_->owned_layers.insert(existing_id);
    for (auto& kv : impl_->canvas_refs) {
      if (!kv.second.isNull()) syncCanvasLayers(kv.first);
    }
    return existing_id;
  }
  const QString uri = QStringLiteral("%1?crs=%2")
      .arg(QString::fromStdString(geometry_type), QString::fromStdString(crs_auth_id));
  auto layer = std::make_unique<QgsVectorLayer>(
      uri, QString::fromStdString(name), QStringLiteral("memory"));
  if (!layer->isValid()) throw std::runtime_error("memory layer creation failed: " + name);
  // V8 M1: schema 先行——provider 落字段，features 带 schema 解析为 typed
  // 属性（无 schema 时保持 V7 legacy 行为：属性被丢弃，几何仍在）。
  if (!fields_json.empty()) {
    const QList<FieldSchemaEntry> schema = parseFieldSchema(fields_json);
    applyFieldSchema(*layer, schema);
    layer->setCustomProperty(QStringLiteral("pwb/fields_json"),
                             QString::fromStdString(fields_json));
    layer->setCustomProperty(QStringLiteral("pwb/fields_sig"),
                             fieldSchemaSignature(schema));
  }
  QgsFeatureList features = parseGeoJsonFeatures(
      QString::fromStdString(geojson_feature_collection), layer->fields());
  if (!features.isEmpty()) {
    if (!layer->dataProvider()->addFeatures(features)) {
      throw std::runtime_error("addFeatures failed for new mirror layer: " + name);
    }
    layer->updateExtents();
  }
  recordMirrorFeatureFids(impl_->mirror_feature_fids[doc_id], features, geoBytes);
  if (data_revision != 0) {
    impl_->mirror_data_revisions[doc_id] = data_revision;
  } else {
    impl_->mirror_data_revisions.erase(doc_id);
  }
  bool hasStyle = !renderer_xml.empty() || !labeling_xml.empty() || !legacy_style_json.empty();
  const bool legacyIsEmpty = legacy_style_empty(legacy_style_json);
  if (hasStyle && (!renderer_xml.empty() || !labeling_xml.empty() || !legacyIsEmpty)) {
    VectorLayerSpec spec = buildSpecFromLegacyJson(renderer_xml, labeling_xml, legacy_style_json, name);
    spec.id = layer->id().toStdString();
    if (spec.id.empty()) spec.id = name;
    applyStyleToLayer(*layer, spec);
  }
  std::string new_sig = makeStyleSig(renderer_xml, labeling_xml, legacy_style_json);
  layer->setCustomProperty(QStringLiteral("pwb/doc_id"), QString::fromStdString(doc_id));
  layer->setCustomProperty(QStringLiteral("pwb/style_sig"), QString::fromStdString(new_sig));
  layer->setCustomProperty(QStringLiteral("pwb/reference"),
                           is_reference ? QStringLiteral("true") : QString());
  layer->setCustomProperty(QStringLiteral("pwb/editable"),
                           is_editable ? QStringLiteral("true") : QString());
  layer->setCustomProperty(QStringLiteral("pwb/reference_snap"),
                           reference_snap ? QStringLiteral("true") : QString());
  layer->setOpacity(std::clamp(opacity, 0.0, 1.0));
  const std::string id = layer->id().toStdString();
  {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    project->addMapLayer(layer.release());
    QgsMapLayer* added = project->mapLayer(QString::fromStdString(id));
    if (added) {
      QgsLayerTreeLayer* node = project->layerTreeRoot()->findLayer(added);
      if (node) node->setItemVisibilityChecked(visible);
    }
    impl_->known_layer_visibility[doc_id] = visible;
  }
  impl_->owned_layers.insert(id);
  impl_->mirror_by_doc[doc_id] = id;
  impl_->mirror_style_sig[doc_id] = new_sig;
  impl_->known_layer_names[doc_id] = name;
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
  return id;
}

std::string QgisMapStack::upsertRasterMirrorLayer(
    const std::string& doc_id, const std::string& name,
    const std::string& source_path, const std::string& crs_auth_id,
    const std::string& renderer_xml, bool visible, double opacity,
    bool is_reference) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  if (doc_id.empty()) throw std::invalid_argument("doc_id must not be empty");
  if (source_path.empty())
    throw std::invalid_argument("raster source_path must not be empty for doc_id: " + doc_id);
  // Up-front payload validation: a malformed renderer must not leave the
  // live mirror half-styled (#519 discipline).
  if (!renderer_xml.empty()) validate_raster_renderer_xml(renderer_xml);

  QgsProject* project = this->project();
  QgsRasterLayer* existing = nullptr;
  std::string existing_id;
  std::string existing_source;
  auto mapIt = impl_->mirror_by_doc.find(doc_id);
  if (mapIt != impl_->mirror_by_doc.end()) {
    if (auto* base = project->mapLayer(QString::fromStdString(mapIt->second))) {
      existing = qobject_cast<QgsRasterLayer*>(base);
      if (existing) {
        existing_id = mapIt->second;
        existing_source = existing->source().toStdString();
      } else {
        // doc_id currently owns a non-raster mirror: drop the registry
        // binding (the vector layer itself stays until replaced).
        impl_->eraseMirrorByDocId(doc_id);
      }
    } else {
      impl_->eraseMirrorByDocId(doc_id);
    }
  }
  if (!existing) {
    existing = qobject_cast<QgsRasterLayer*>(
        findMapMirrorByDocId(project, doc_id));
    if (existing) {
      existing_id = existing->id().toStdString();
      existing_source = existing->source().toStdString();
      impl_->mirror_by_doc[doc_id] = existing_id;
      impl_->owned_layers.insert(existing_id);
    }
  }

  const bool style_only_change = existing != nullptr
      && existing_source == source_path;
  if (existing && style_only_change) {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    std::string new_sig = makeStyleSig(renderer_xml, std::string(), std::string());
    auto sigIt = impl_->mirror_style_sig.find(doc_id);
    const bool sig_changed = sigIt == impl_->mirror_style_sig.end()
        || sigIt->second != new_sig;
    if (sig_changed) {
      if (!renderer_xml.empty()
          && !apply_raster_renderer_xml(*existing, renderer_xml)) {
        throw std::runtime_error(
            "raster renderer application failed for doc_id: " + doc_id);
      }
      impl_->mirror_style_sig[doc_id] = new_sig;
      existing->setCustomProperty(QStringLiteral("pwb/style_sig"),
                                  QString::fromStdString(new_sig));
    }
    existing->setName(QString::fromStdString(name));
    impl_->known_layer_names[doc_id] = name;
    existing->setOpacity(std::clamp(opacity, 0.0, 1.0));
    existing->setCustomProperty(QStringLiteral("pwb/reference"),
                                is_reference ? QStringLiteral("true") : QString());
    if (!crs_auth_id.empty()) {
      existing->setCustomProperty(QStringLiteral("pwb/crs_hint"),
                                  QString::fromStdString(crs_auth_id));
    }
    if (QgsLayerTreeLayer* node = project->layerTreeRoot()->findLayer(existing)) {
      node->setItemVisibilityChecked(visible);
    }
    impl_->known_layer_visibility[doc_id] = visible;
    for (auto& kv : impl_->canvas_refs) {
      if (!kv.second.isNull()) syncCanvasLayers(kv.first);
    }
    return existing_id;
  }

  // Source changed (or first publish): rebuild the mirror layer.
  if (existing) {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    impl_->eraseMirrorByDocId(doc_id);
    if (impl_->owned_layers.erase(existing_id) > 0) {
      project->removeMapLayer(QString::fromStdString(existing_id));
    }
    existing = nullptr;
  }
  auto layer = std::make_unique<QgsRasterLayer>(
      QString::fromStdString(source_path), QString::fromStdString(name),
      QStringLiteral("gdal"));
  if (!layer->isValid())
    throw std::runtime_error("QGIS could not open raster layer " + doc_id);
  if (!renderer_xml.empty()
      && !apply_raster_renderer_xml(*layer, renderer_xml)) {
    throw std::runtime_error("raster renderer application failed for doc_id: " + doc_id);
  }
  const std::string new_sig = makeStyleSig(renderer_xml, std::string(), std::string());
  layer->setCustomProperty(QStringLiteral("pwb/doc_id"), QString::fromStdString(doc_id));
  layer->setCustomProperty(QStringLiteral("pwb/style_sig"), QString::fromStdString(new_sig));
  layer->setCustomProperty(QStringLiteral("pwb/reference"),
                           is_reference ? QStringLiteral("true") : QString());
  if (!crs_auth_id.empty()) {
    layer->setCustomProperty(QStringLiteral("pwb/crs_hint"),
                             QString::fromStdString(crs_auth_id));
  }
  layer->setOpacity(std::clamp(opacity, 0.0, 1.0));
  const std::string id = layer->id().toStdString();
  {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    project->addMapLayer(layer.release());
    if (QgsMapLayer* added = project->mapLayer(QString::fromStdString(id))) {
      if (QgsLayerTreeLayer* node = project->layerTreeRoot()->findLayer(added)) {
        node->setItemVisibilityChecked(visible);
      }
    }
    impl_->known_layer_visibility[doc_id] = visible;
  }
  impl_->owned_layers.insert(id);
  impl_->mirror_by_doc[doc_id] = id;
  impl_->mirror_style_sig[doc_id] = new_sig;
  impl_->known_layer_names[doc_id] = name;
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
  return id;
}

void QgisMapStack::removeMirrorLayersExcept(const std::vector<std::string>& doc_ids) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  std::unordered_set<std::string> keep(doc_ids.begin(), doc_ids.end());
  SuppressGuard guard(&impl_->suppress_tree_callbacks);
  auto owned_copy = impl_->owned_layers;
  for (const auto& qgis_id : owned_copy) {
    QgsMapLayer* layer = project()->mapLayer(QString::fromStdString(qgis_id));
    if (layer == nullptr) {
      impl_->owned_layers.erase(qgis_id);
      impl_->eraseMirrorByQgisId(qgis_id);
      continue;
    }
    QVariant docVar = layer->customProperty(QStringLiteral("pwb/doc_id"));
    std::string doc_id = docVar.isValid() ? docVar.toString().toStdString() : "";
    bool hasDoc = !doc_id.empty();
    bool keepIt = hasDoc && keep.find(doc_id) != keep.end();
    if (hasDoc) {
      if (!keepIt) {
        project()->removeMapLayer(layer);
        impl_->owned_layers.erase(qgis_id);
        impl_->eraseMirrorByDocIdIfQgisMatches(doc_id, qgis_id);
      }
    } else {
      project()->removeMapLayer(layer);
      impl_->owned_layers.erase(qgis_id);
      impl_->eraseMirrorByQgisId(qgis_id);
    }
  }
  std::vector<std::string> stale_docs;
  for (const auto& kv : impl_->mirror_by_doc) {
    if (impl_->owned_layers.find(kv.second) == impl_->owned_layers.end() &&
        !project()->mapLayer(QString::fromStdString(kv.second))) {
      stale_docs.push_back(kv.first);
    }
  }
  for (const auto& d : stale_docs) impl_->eraseMirrorByDocId(d);
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
}

void QgisMapStack::setMirrorLayerOrder(const std::vector<std::string>& doc_ids_top_first) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  SuppressGuard guard(&impl_->suppress_tree_callbacks);
  QgsLayerTreeGroup* root = project()->layerTreeRoot();
  // 排序操作必须在 root 信号屏蔽 + registryBridge 禁用的保护区间内完成；
  // setCanvasLayers 依赖树信号驱动画布桥，必须等两个 RAII guard 析构后再调用。
  {
    auto* registryBridge = project()->layerTreeRegistryBridge();
    bool bridgeWasEnabled = false;
    if (registryBridge && registryBridge->isEnabled()) {
      bridgeWasEnabled = true;
      registryBridge->setEnabled(false);
    }
    struct BridgeReenable {
      QgsLayerTreeRegistryBridge* bridge;
      bool wasEnabled;
      ~BridgeReenable() { if (bridge && wasEnabled) bridge->setEnabled(true); }
    } reenable{registryBridge, bridgeWasEnabled};
    // #1154: the root node's signals must stay LIVE — blocking them kept
    // QgsLayerTreeModel/QgsLayerTreeView from ever seeing the reorder, so the
    // panel showed stale order/visibility while only the canvas bridge was
    // manually re-synced. But the registry bridge's removal accounting is not
    // switchable: groupWillRemoveChildren collects layer ids unconditionally
    // (no mEnabled check) and groupRemovedChildren queues a QueuedConnection
    // registry removal for any id not in the tree AT THAT INSTANT — which
    // every re-parented node is, between takeChildNode() and
    // insertChildNode(). Detach exactly those two slots for the dance and
    // restore them exactly as the bridge constructor wires them.
    // The two slots are protected, so member-pointer disconnect/connect is
    // unavailable; the generic sender/receiver disconnect plus string-based
    // reconnect (meta-object invokation reaches protected slots) covers
    // exactly the two connections the bridge constructor makes from mRoot.
    const bool bridgeDetached = registryBridge
        ? QObject::disconnect(root, nullptr, registryBridge, nullptr)
        : false;
    struct BridgeReconnect {
      QgsLayerTreeGroup* r;
      QgsLayerTreeRegistryBridge* b;
      bool detached;
      ~BridgeReconnect() {
        if (r == nullptr || b == nullptr || !detached) return;
        QObject::connect(
            r, SIGNAL(willRemoveChildren(QgsLayerTreeNode*,int,int)), b,
            SLOT(groupWillRemoveChildren(QgsLayerTreeNode*,int,int)));
        QObject::connect(
            r, SIGNAL(removedChildren(QgsLayerTreeNode*,int,int)), b,
            SLOT(groupRemovedChildren()));
      }
    } reconnect{root, registryBridge, bridgeDetached};
    for (auto it = doc_ids_top_first.rbegin(); it != doc_ids_top_first.rend(); ++it) {
      const std::string& doc_id = *it;
      auto mapIt = impl_->mirror_by_doc.find(doc_id);
      if (mapIt == impl_->mirror_by_doc.end()) continue;
      QgsMapLayer* layer = project()->mapLayer(QString::fromStdString(mapIt->second));
      if (!layer) continue;
      QgsLayerTreeLayer* node = root->findLayer(layer);
      if (!node) continue;
      QgsLayerTreeNode* parent = node->parent();
      if (!parent) continue;
      parent->takeChild(node);
      root->insertChildNode(0, node);
    }
  }
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
}

void QgisMapStack::setMirrorLayerVisibility(const std::string& doc_id, bool visible) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  SuppressGuard guard(&impl_->suppress_tree_callbacks);
  auto it = impl_->mirror_by_doc.find(doc_id);
  QgsMapLayer* layer = nullptr;
  if (it != impl_->mirror_by_doc.end()) {
    layer = project()->mapLayer(QString::fromStdString(it->second));
    if (!layer) {
      layer = findMapMirrorByDocId(project(), doc_id);
    }
  } else {
    layer = findMapMirrorByDocId(project(), doc_id);
    if (layer) {
      impl_->mirror_by_doc[doc_id] = layer->id().toStdString();
      impl_->owned_layers.insert(layer->id().toStdString());
    }
  }
  if (!layer) throw std::invalid_argument("unknown doc_id: " + doc_id);
  QgsLayerTreeLayer* node = project()->layerTreeRoot()->findLayer(layer);
  if (!node) throw std::invalid_argument("layer node not found for doc_id: " + doc_id);
  node->setItemVisibilityChecked(visible);
  impl_->known_layer_visibility[doc_id] = visible;
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
}

std::vector<std::string> QgisMapStack::mirrorOrderTopFirst() const {
  std::vector<std::string> result;
  QgsLayerTreeGroup* root = project()->layerTreeRoot();
  for (QgsLayerTreeNode* child : root->children()) {
    QgsLayerTreeLayer* layerNode = treeLayerCast(child);
    if (!layerNode) continue;
    QgsMapLayer* layer = layerNode->layer();
    if (!layer) continue;
    QVariant docVar = layer->customProperty(QStringLiteral("pwb/doc_id"));
    if (!docVar.isValid() || docVar.toString().isEmpty()) continue;
    if (impl_->owned_layers.find(layer->id().toStdString()) == impl_->owned_layers.end()) continue;
    result.push_back(docVar.toString().toStdString());
  }
  return result;
}

bool QgisMapStack::mirrorLayerVisibility(const std::string& doc_id) const {
  QgsMapLayer* layer = nullptr;
  auto it = impl_->mirror_by_doc.find(doc_id);
  if (it != impl_->mirror_by_doc.end()) {
    layer = project()->mapLayer(QString::fromStdString(it->second));
  }
  if (!layer) layer = findMapMirrorByDocId(project(), doc_id);
  if (!layer) throw std::invalid_argument("unknown doc_id: " + doc_id);
  QgsLayerTreeLayer* node = project()->layerTreeRoot()->findLayer(layer);
  if (!node) throw std::invalid_argument("layer node not found for doc_id: " + doc_id);
  return node->itemVisibilityChecked();
}

bool QgisMapStack::treeEchoSuppressed() const noexcept {
  return impl_ && impl_->suppress_tree_callbacks > 0;
}

// ---------------------------------------------------------------- V5 groups

QgsLayerTreeGroup* QgisMapStack::findGroupByGroupId(const std::string& group_id) const {
  return findGroupByGroupIdIn(project()->layerTreeRoot(), group_id);
}

bool QgisMapStack::groupExists(const std::string& group_id) const {
  if (!impl_ || !impl_->initialized) return false;
  return findGroupByGroupId(group_id) != nullptr;
}

bool QgisMapStack::upsertGroup(const std::string& group_id, const std::string& name,
                               const std::string& parent_group_id) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  if (group_id.empty()) throw std::invalid_argument("group_id must not be empty");
  QgsLayerTree* root = project()->layerTreeRoot();
  QgsLayerTreeGroup* parent = root;
  if (!parent_group_id.empty()) {
    parent = findGroupByGroupIdIn(root, parent_group_id);
    if (parent == nullptr) {
      throw std::invalid_argument("parent group not found: " + parent_group_id);
    }
  }
  SuppressGuard guard(&impl_->suppress_tree_callbacks);
  QgsLayerTreeGroup* existing = findGroupByGroupIdIn(root, group_id);
  if (existing == nullptr) {
    auto* node = new QgsLayerTreeGroup(QString::fromStdString(name));
    node->setCustomProperty(kGroupIdProp, QString::fromStdString(group_id));
    parent->addChildNode(node);
    existing = node;
    wireNodeExpandSignal(node);  // V5：新组接入展开态回调
  } else {
    if (existing->name().toStdString() != name) {
      existing->setName(QString::fromStdString(name));
    }
    if (existing != parent && existing->parent() != parent) {
      // 挂错父组：整体搬移。takeChild 会先递归卸下后代——先做子树
      // 保护性卸载再搬空组、按原结构挂回。
      QgsLayerTreeNode* oldParent = existing->parent();
      if (oldParent != nullptr && oldParent->children().indexOf(existing) >= 0) {
        QList<SubtreeDetachEntry*> subtreeLog;
        detachGroupSubtree(existing, &subtreeLog);
        oldParent->takeChild(existing);
        parent->addChildNode(existing);
        restoreGroupSubtree(subtreeLog);
        qDeleteAll(subtreeLog);
      }
    }
  }
  impl_->known_group_names[group_id] = name;
  // 可见性基线同步建立（否则用户首次勾选被当"首次见面"吞掉）。
  impl_->known_group_visibility[group_id] = existing->itemVisibilityChecked();
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
  return true;
}

int QgisMapStack::removeGroupsExcept(const std::vector<std::string>& group_ids) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  const std::unordered_set<std::string> keep(group_ids.begin(), group_ids.end());
  SuppressGuard guard(&impl_->suppress_tree_callbacks);
  QgsLayerTree* root = project()->layerTreeRoot();
  int removed = 0;
  // 注册表桥 detach（#1154）：removeChildNode 的 removedChildren 计数
  // 不受 setEnabled 控制，必须整体断开——上提的图层才不会被排队注销。
  {
    RegistryBridgeDetach bridgeDetach{project(), root};
    // 收集要删的组（自底向上删，子组先于父组）。
    std::vector<QgsLayerTreeGroup*> doomed;
    std::function<void(QgsLayerTreeGroup*)> collect =
        [&](QgsLayerTreeGroup* parent) {
          for (QgsLayerTreeNode* child : parent->children()) {
            auto* group = treeGroupCast(child);
            if (group == nullptr) continue;
            collect(group);
            const std::string gid = group->customProperty(kGroupIdProp).toString().toStdString();
            if (!gid.empty() && keep.find(gid) == keep.end()) {
              doomed.push_back(group);
            }
          }
        };
    collect(root);
    for (QgsLayerTreeGroup* group : doomed) {
      // 先把子节点上提到本组的父组——组删除绝不带走图层。
      QgsLayerTreeNode* parentNode = group->parent();
      auto* parentGroup = treeGroupCast(parentNode);
      if (parentGroup == nullptr) continue;
      const QList<QgsLayerTreeNode*> children = group->children();
      for (QgsLayerTreeNode* child : children) {
        group->takeChild(child);
        parentGroup->addChildNode(child);
      }
      const std::string gid = group->customProperty(kGroupIdProp).toString().toStdString();
      parentGroup->removeChildNode(group);
      impl_->known_group_names.erase(gid);
      impl_->known_group_visibility.erase(gid);
      removed++;
    }
  }
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
  return removed;
}

void QgisMapStack::renameGroup(const std::string& group_id, const std::string& name) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  QgsLayerTreeGroup* group = findGroupByGroupId(group_id);
  if (group == nullptr) throw std::invalid_argument("unknown group_id: " + group_id);
  {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    group->setName(QString::fromStdString(name));
  }
  impl_->known_group_names[group_id] = name;
}

void QgisMapStack::setGroupVisibility(const std::string& group_id, bool visible) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  QgsLayerTreeGroup* group = findGroupByGroupId(group_id);
  if (group == nullptr) throw std::invalid_argument("unknown group_id: " + group_id);
  {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    group->setItemVisibilityChecked(visible);
  }
  impl_->known_group_visibility[group_id] = visible;
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
}

void QgisMapStack::moveLayerToGroup(const std::string& doc_id,
                                    const std::string& group_id, int index) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  QgsVectorLayer* layer = nullptr;
  auto it = impl_->mirror_by_doc.find(doc_id);
  if (it != impl_->mirror_by_doc.end()) {
    layer = qobject_cast<QgsVectorLayer*>(
        project()->mapLayer(QString::fromStdString(it->second)));
  }
  if (layer == nullptr) layer = findMirrorByDocId(project(), doc_id);
  if (layer == nullptr) throw std::invalid_argument("unknown doc_id: " + doc_id);
  QgsLayerTree* root = project()->layerTreeRoot();
  QgsLayerTreeLayer* node = root->findLayer(layer);
  if (node == nullptr) throw std::invalid_argument("layer node not found: " + doc_id);
  QgsLayerTreeGroup* target = root;
  if (!group_id.empty()) {
    target = findGroupByGroupIdIn(root, group_id);
    if (target == nullptr) throw std::invalid_argument("unknown group_id: " + group_id);
  }
  {
    // 注册表桥 detach 舞步与 setMirrorLayerOrder 相同（#1154）。
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    RegistryBridgeDetach bridgeDetach{project(), root};
    QgsLayerTreeNode* parent = node->parent();
    if (parent == target) {
      const int current = target->children().indexOf(node);
      const int wanted = index < 0
          ? static_cast<int>(target->children().size()) - 1
          : std::min<int>(index, static_cast<int>(target->children().size()) - 1);
      if (current == wanted) return;  // 已就位：no-op
    }
    const int count = static_cast<int>(target->children().size());
    const int clamped = index < 0 ? count : std::min(index, count);
    if (parent != nullptr) {
      parent->takeChild(node);  // 解除挂载；节点指针仍有效
    }
    target->insertChildNode(clamped, node);
  }
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
}

void QgisMapStack::moveGroup(const std::string& group_id,
                             const std::string& parent_group_id, int index) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  QgsLayerTree* root = project()->layerTreeRoot();
  QgsLayerTreeGroup* group = findGroupByGroupIdIn(root, group_id);
  if (group == nullptr) throw std::invalid_argument("unknown group_id: " + group_id);
  QgsLayerTreeGroup* target = root;
  if (!parent_group_id.empty()) {
    target = findGroupByGroupIdIn(root, parent_group_id);
    if (target == nullptr) {
      throw std::invalid_argument("unknown parent group_id: " + parent_group_id);
    }
  }
  if (target != root && isDescendantOf(target, group)) {
    throw std::invalid_argument("cannot move a group into its own descendant");
  }
  {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    QgsLayerTreeNode* parent = group->parent();
    const int count = static_cast<int>(target->children().size());
    const int clamped = index < 0 ? count : std::min(index, count);
    if (parent != nullptr) {
      // 子树保护性卸载 → 空组搬运 → 原结构挂回（takeChild 递归 orphan 后代）。
      QList<SubtreeDetachEntry*> subtreeLog;
      detachGroupSubtree(group, &subtreeLog);
      parent->takeChild(group);
      target->insertChildNode(clamped, group);
      restoreGroupSubtree(subtreeLog);
      qDeleteAll(subtreeLog);
    } else {
      target->insertChildNode(clamped, group);
    }
  }
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
}

std::string QgisMapStack::treeSnapshotJson() const {
  if (!impl_ || !impl_->initialized) {
    throw std::runtime_error("map stack is not initialized");
  }
  QJsonArray children;
  for (QgsLayerTreeNode* child : project()->layerTreeRoot()->children()) {
    appendNodeToJson(child, &children);
  }
  QJsonObject root;
  root.insert(QStringLiteral("children"), children);
  return QJsonDocument(root).toJson(QJsonDocument::Compact).toStdString();
}

std::string QgisMapStack::mirrorLayerSchemaJson(const std::string& doc_id) const {
  // V8 M1 自省面：镜像层上真实落地的 provider schema（QgsFields/约束/
  // 别名/控件/默认值）。能力事实而非展示规则——供 qgis-marked 测试与
  // host 端 handshake（M10）消费；未镜像返回 {"exists": false}。
  if (!impl_ || !impl_->initialized) {
    throw std::runtime_error("map stack is not initialized");
  }
  QJsonObject out;
  QgsVectorLayer* layer = nullptr;
  auto it = impl_->mirror_by_doc.find(doc_id);
  if (it != impl_->mirror_by_doc.end()) {
    layer = qobject_cast<QgsVectorLayer*>(
        project()->mapLayer(QString::fromStdString(it->second)));
  }
  if (layer == nullptr) layer = findMirrorByDocId(project(), doc_id);
  if (layer == nullptr) {
    out.insert(QStringLiteral("exists"), false);
    return QJsonDocument(out).toJson(QJsonDocument::Compact).toStdString();
  }
  out.insert(QStringLiteral("exists"), true);
  QJsonArray fields;
  const QgsFields applied = layer->fields();
  for (int i = 0; i < applied.count(); ++i) {
    const QgsField field = applied.at(i);
    QJsonObject entry;
    entry.insert(QStringLiteral("name"), field.name());
    entry.insert(QStringLiteral("type"),
                 QString::fromUtf8(QMetaType(field.type()).name()));
    if (!field.alias().isEmpty()) {
      entry.insert(QStringLiteral("alias"), field.alias());
    }
    if (field.length() > 0) {
      entry.insert(QStringLiteral("length"), field.length());
    }
    if (field.precision() > 0) {
      entry.insert(QStringLiteral("precision"), field.precision());
    }
    const QgsFieldConstraints constraints = field.constraints();
    QJsonObject constraint_json;
    if (constraints.constraints() & QgsFieldConstraints::ConstraintNotNull) {
      constraint_json.insert(QStringLiteral("not_null"), true);
    }
    if (constraints.constraints() & QgsFieldConstraints::ConstraintUnique) {
      constraint_json.insert(QStringLiteral("unique"), true);
    }
    if (!constraints.constraintExpression().isEmpty()) {
      constraint_json.insert(
          QStringLiteral("expression"), constraints.constraintExpression());
    }
    if (!constraint_json.isEmpty()) {
      entry.insert(QStringLiteral("constraints"), constraint_json);
    }
    const QgsEditorWidgetSetup setup = layer->editorWidgetSetup(i);
    if (!setup.type().isEmpty()) {
      entry.insert(QStringLiteral("editor_widget"), setup.type());
      QJsonObject config;
      for (auto cfg = setup.config().constBegin();
           cfg != setup.config().constEnd(); ++cfg) {
        config.insert(cfg.key(), QJsonValue::fromVariant(cfg.value()));
      }
      entry.insert(QStringLiteral("editor_config"), config);
    }
    const QString default_expr =
        layer->defaultValueDefinition(i).expression();
    if (!default_expr.isEmpty()) {
      entry.insert(QStringLiteral("default"), default_expr);
    }
    fields.append(entry);
  }
  out.insert(QStringLiteral("fields"), fields);
  return QJsonDocument(out).toJson(QJsonDocument::Compact).toStdString();
}

std::string QgisMapStack::mirrorFeaturesJson(const std::string& doc_id,
                                             int limit) const {
  // V8 M1 自省面（数据侧）：镜像层上真实存储的要素 + typed 属性
  // （GeoJSON FeatureCollection）。与 mirrorLayerSchemaJson 成对，供
  // qgis-marked 测试与 host 端（Inspector/handshake）消费；limit 截断
  // 防止大层意外序列化。
  if (!impl_ || !impl_->initialized) {
    throw std::runtime_error("map stack is not initialized");
  }
  QJsonObject out;
  QgsVectorLayer* layer = nullptr;
  auto it = impl_->mirror_by_doc.find(doc_id);
  if (it != impl_->mirror_by_doc.end()) {
    layer = qobject_cast<QgsVectorLayer*>(
        project()->mapLayer(QString::fromStdString(it->second)));
  }
  if (layer == nullptr) layer = findMirrorByDocId(project(), doc_id);
  if (layer == nullptr) {
    out.insert(QStringLiteral("exists"), false);
    return QJsonDocument(out).toJson(QJsonDocument::Compact).toStdString();
  }
  out.insert(QStringLiteral("exists"), true);
  QJsonArray features;
  int emitted = 0;
  QgsFeature stored;
  QgsFeatureIterator cursor = layer->getFeatures();
  while (cursor.nextFeature(stored)) {
    if (emitted++ >= std::max(1, limit)) break;
    QJsonObject feature_json;
    if (stored.hasGeometry()) {
      feature_json.insert(QStringLiteral("geometry"),
                          QJsonDocument::fromJson(
                              stored.geometry().asJson().toUtf8()).object());
    }
    // 原始 QVariant 属性（不经 editor-widget formatter——Range 控件的
    // 千分位格式化会把 2500 变 "2,500"，自省面必须报告存储真相）。
    QJsonObject properties;
    const QgsFields stored_fields = layer->fields();
    for (int index = 0; index < stored_fields.count(); ++index) {
      const QVariant value = stored.attribute(index);
      if (!value.isValid() || value.isNull()) continue;
      switch (stored_fields.at(index).type()) {
        case QMetaType::Type::Double:
          properties.insert(stored_fields.at(index).name(), value.toDouble());
          break;
        case QMetaType::Type::LongLong:
        case QMetaType::Type::Int:
          properties.insert(stored_fields.at(index).name(),
                            static_cast<qint64>(value.toLongLong()));
          break;
        case QMetaType::Type::Bool:
          properties.insert(stored_fields.at(index).name(), value.toBool());
          break;
        default:
          properties.insert(stored_fields.at(index).name(), value.toString());
          break;
      }
    }
    feature_json.insert(QStringLiteral("properties"), properties);
    features.append(feature_json);
  }
  out.insert(QStringLiteral("features"), features);
  return QJsonDocument(out).toJson(QJsonDocument::Compact).toStdString();
}

void QgisMapStack::setGroupExpanded(std::uintptr_t tree_view,
                                    const std::string& node_id, bool expanded) {
  (void)treeViewOrThrow(tree_view);  // 树地址校验（节点级 setExpanded 自带视图联动）
  QgsLayerTreeNode* node = findGroupByGroupId(node_id);
  if (node == nullptr) return;
  {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    node->setExpanded(expanded);
  }
}

std::string QgisMapStack::applyTreePlacements(const std::string& placements_json) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  QJsonParseError parseErr;
  const QJsonDocument doc = QJsonDocument::fromJson(
      QByteArray::fromStdString(placements_json), &parseErr);
  if (parseErr.error != QJsonParseError::NoError || !doc.isArray()) {
    throw std::invalid_argument("invalid placements JSON");
  }
  QgsLayerTree* root = project()->layerTreeRoot();
  // 一次遍历建索引：doc_id → layer 节点；group_id → 组节点。
  std::unordered_map<std::string, QgsLayerTreeLayer*> layerByDoc;
  std::unordered_map<std::string, QgsLayerTreeGroup*> groupByGid;
  std::function<void(QgsLayerTreeGroup*)> index = [&](QgsLayerTreeGroup* parent) {
    for (QgsLayerTreeNode* child : parent->children()) {
      if (auto* layerNode = treeLayerCast(child)) {
        QgsMapLayer* layer = layerNode->layer();
        if (layer != nullptr) {
          const QString d = layer->customProperty(QStringLiteral("pwb/doc_id")).toString();
          if (!d.isEmpty()) {
            layerByDoc[d.toStdString()] = layerNode;
          }
        }
      } else if (auto* group = treeGroupCast(child)) {
        const std::string gid = ensureGroupNodeId(group);
        groupByGid[gid] = group;
        index(group);
      }
    }
  };
  index(root);

  int applied = 0;
  int skipped = 0;
  {
    SuppressGuard guard(&impl_->suppress_tree_callbacks);
    RegistryBridgeDetach bridgeDetach{project(), root};
    for (const QJsonValue& value : doc.array()) {
      if (!value.isObject()) continue;
      const QJsonObject item = value.toObject();
      const QString nodeRef = item.value(QStringLiteral("node")).toString();
      const QString parentRef = item.value(QStringLiteral("parent")).toString();
      const int index1 = item.value(QStringLiteral("index")).toInt(-1);
      QgsLayerTreeGroup* target = root;
      if (!parentRef.isEmpty()) {
        auto found = groupByGid.find(parentRef.toStdString());
        if (found == groupByGid.end()) { skipped++; continue; }
        target = found->second;
      }
      if (nodeRef.startsWith(QStringLiteral("group:"))) {
        auto found = groupByGid.find(
            nodeRef.mid(static_cast<int>(strlen("group:"))).toStdString());
        if (found == groupByGid.end()) { skipped++; continue; }
        QgsLayerTreeGroup* group = found->second;
        if (group == target || isDescendantOf(target, group)) { skipped++; continue; }
        QList<SubtreeDetachEntry*> subtreeLog;
        detachGroupSubtree(group, &subtreeLog);
        if (QgsLayerTreeNode* parent = group->parent()) {
          parent->takeChild(group);
        }
        const int count = static_cast<int>(target->children().size());
        target->insertChildNode(
            index1 < 0 ? count : std::min(index1, count), group);
        restoreGroupSubtree(subtreeLog);
        qDeleteAll(subtreeLog);
      } else {
        auto found = layerByDoc.find(nodeRef.toStdString());
        if (found == layerByDoc.end()) { skipped++; continue; }
        QgsLayerTreeLayer* node = found->second;
        if (QgsLayerTreeNode* parent = node->parent()) {
          parent->takeChild(node);
        }
        const int count = static_cast<int>(target->children().size());
        target->insertChildNode(
            index1 < 0 ? count : std::min(index1, count), node);
      }
      applied++;
    }
  }
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
  QJsonObject out;
  out.insert(QStringLiteral("applied"), applied);
  out.insert(QStringLiteral("skipped"), skipped);
  return QJsonDocument(out).toJson(QJsonDocument::Compact).toStdString();
}

std::string QgisMapStack::writeProjectXml() {
  if (!impl_ || !impl_->initialized)
    throw std::runtime_error("map stack is not initialized");
  QTemporaryDir dir;
  if (!dir.isValid())
    throw std::runtime_error("could not create temp dir for QgsProject write");
  const QString path = dir.filePath(QStringLiteral("map.qgs"));
  QgsProject* prj = project();
  const QString oldName = prj->fileName();
  const bool ok = prj->write(path);
  prj->setFileName(oldName);
  if (!ok) throw std::runtime_error("QgsProject::write failed");
  QFile file(path);
  if (!file.open(QIODevice::ReadOnly))
    throw std::runtime_error("could not read written QgsProject XML");
  return QString::fromUtf8(file.readAll()).toStdString();
}

int QgisMapStack::applyProjectXml(const std::string& xml) {
  if (!impl_ || !impl_->initialized)
    throw std::runtime_error("map stack is not initialized");
  if (xml.empty()) return 0;
  if (xml.find("<qgis") == std::string::npos)
    throw std::runtime_error("invalid QgsProject XML");

  QTemporaryDir dir;
  if (!dir.isValid())
    throw std::runtime_error("could not create temp dir for QgsProject read");
  const QString path = dir.filePath(QStringLiteral("map.qgs"));
  QFile out(path);
  if (!out.open(QIODevice::WriteOnly))
    throw std::runtime_error("could not write temp QgsProject XML");
  out.write(QByteArray::fromStdString(xml));
  out.close();

  QgsProject donor;
  if (!donor.read(path))
    throw std::runtime_error("QgsProject::read failed");

  SuppressGuard guard(&impl_->suppress_tree_callbacks);
  int applied = 0;
  // V5：donor 树按层级遍历（组 + 图层）。先应用样式/可见性，再恢复
  // 组结构与放置；无组时保持 legacy 平铺顺序路径。
  struct Placement {
    std::string doc_id;
    std::string parent_group_id;
    int index;
    bool visible;
  };
  // (id, name, parent_gid) 自上而下（父先于子）。
  std::vector<std::tuple<std::string, std::string, std::string>> groupPlacements;
  std::vector<Placement> placements;
  std::vector<std::string> flatOrder;
  std::function<void(QgsLayerTreeGroup*, const std::string&, bool)> walk =
      [&](QgsLayerTreeGroup* parent, const std::string& parent_gid, bool inGroup) {
        int index = 0;
        for (QgsLayerTreeNode* child : parent->children()) {
          if (auto* donorGroup = treeGroupCast(child)) {
            const QString gidRaw =
                donorGroup->customProperty(QStringLiteral("pwb/group_id")).toString();
            const std::string gid =
                gidRaw.isEmpty()
                    ? "user_" + QUuid::createUuid().toString(QUuid::WithoutBraces).toStdString()
                    : gidRaw.toStdString();
            groupPlacements.emplace_back(
                gid, donorGroup->name().toStdString(), parent_gid);
            walk(donorGroup, gid, true);
            continue;
          }
          auto* layerNode = treeLayerCast(child);
          if (layerNode == nullptr) continue;
          QgsMapLayer* donorLayer = layerNode->layer();
          if (donorLayer == nullptr) continue;
          const QString doc =
              donorLayer->customProperty(QStringLiteral("pwb/doc_id")).toString();
          if (doc.isEmpty()) continue;
          const std::string doc_id = doc.toStdString();
          flatOrder.push_back(doc_id);
          placements.push_back(
              {doc_id, parent_gid, index, layerNode->itemVisibilityChecked()});
          index++;
          QgsMapLayer* live = [&]() {
            auto liveIt = impl_->mirror_by_doc.find(doc_id);
            if (liveIt != impl_->mirror_by_doc.end()) {
              QgsMapLayer* mapped = project()->mapLayer(
                  QString::fromStdString(liveIt->second));
              if (mapped) return mapped;
            }
            return findMapMirrorByDocId(project(), doc_id);
          }();
          if (live == nullptr) continue;
          if (auto* donorVl = qobject_cast<QgsVectorLayer*>(donorLayer)) {
            auto* liveVl = qobject_cast<QgsVectorLayer*>(live);
            if (liveVl != nullptr) {
              if (donorVl->renderer() != nullptr) {
                liveVl->setRenderer(donorVl->renderer()->clone());
              }
              liveVl->setLabelsEnabled(donorVl->labelsEnabled());
              if (donorVl->labeling() != nullptr) {
                liveVl->setLabeling(donorVl->labeling()->clone());
              } else {
                liveVl->setLabeling(nullptr);
              }
            }
          } else if (auto* donorRl = qobject_cast<QgsRasterLayer*>(donorLayer)) {
            // v7 §5: raster presentation state (pseudocolor renderer)
            // round-trips through the same envelope as vector styles.
            auto* liveRl = qobject_cast<QgsRasterLayer*>(live);
            if (liveRl != nullptr && donorRl->renderer() != nullptr) {
              liveRl->setRenderer(donorRl->renderer()->clone());
            }
          }
          live->setOpacity(donorLayer->opacity());
          live->setName(donorLayer->name());
          QgsLayerTreeLayer* liveNode = project()->layerTreeRoot()->findLayer(live);
          if (liveNode != nullptr) {
            const bool visible = layerNode->itemVisibilityChecked();
            liveNode->setItemVisibilityChecked(visible);
            impl_->known_layer_visibility[doc_id] = visible;
          }
          applied++;
        }
      };
  walk(donor.layerTreeRoot(), std::string(), false);

  if (!groupPlacements.empty()) {
    // 组结构恢复：donor 出现序自上而下（父先于子），嵌套父级按 donor 挂载。
    for (const auto& [gid, name, parent_gid] : groupPlacements) {
      upsertGroupUnderLock(gid, name, parent_gid);
    }
    for (const auto& placement : placements) {
      if (findMirrorByDocId(project(), placement.doc_id) == nullptr) continue;
      try {
        moveLayerToGroupUnderLock(placement.doc_id, placement.parent_group_id,
                                  placement.index);
      } catch (const std::exception&) {
        // 放置失败不阻断其余恢复（如组缺失→根）。
      }
    }
  } else if (!flatOrder.empty()) {
    setMirrorLayerOrder(flatOrder);
  }
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
  return applied;
}

void QgisMapStack::upsertGroupUnderLock(const std::string& group_id,
                                        const std::string& name,
                                        const std::string& parent_group_id) {
  // applyProjectXml 已持 SuppressGuard；donor 出现序保证父组先建。
  QgsLayerTree* root = project()->layerTreeRoot();
  if (findGroupByGroupIdIn(root, group_id) != nullptr) return;
  QgsLayerTreeGroup* parent = root;
  if (!parent_group_id.empty()) {
    parent = findGroupByGroupIdIn(root, parent_group_id);
    if (parent == nullptr) parent = root;  // 父组缺失退根（不丢组）
  }
  auto* node = new QgsLayerTreeGroup(QString::fromStdString(name));
  node->setCustomProperty(kGroupIdProp, QString::fromStdString(group_id));
  parent->addChildNode(node);
  wireNodeExpandSignal(node);
  impl_->known_group_names[group_id] = name;
}

void QgisMapStack::moveLayerToGroupUnderLock(const std::string& doc_id,
                                             const std::string& group_id, int index) {
  QgsVectorLayer* layer = findMirrorByDocId(project(), doc_id);
  if (layer == nullptr) return;
  QgsLayerTree* root = project()->layerTreeRoot();
  QgsLayerTreeLayer* node = root->findLayer(layer);
  if (node == nullptr) return;
  QgsLayerTreeGroup* target = root;
  if (!group_id.empty()) {
    target = findGroupByGroupIdIn(root, group_id);
    if (target == nullptr) return;
  }
  QgsLayerTreeNode* parent = node->parent();
  const int count = static_cast<int>(target->children().size());
  if (parent != nullptr) {
    parent->takeChild(node);
  }
  target->insertChildNode(index < 0 ? count : std::min(index, count), node);
}

void QgisMapStack::setSnappingConfig(std::uintptr_t canvas_addr,
                                     const std::string& config_json) {
  ensureNotStale(canvas_addr);
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  QJsonParseError err;
  const QJsonDocument doc =
      QJsonDocument::fromJson(QByteArray::fromStdString(config_json), &err);
  if (err.error != QJsonParseError::NoError || !doc.isObject())
    throw std::invalid_argument("invalid snapping config JSON");
  const QJsonObject obj = doc.object();

  QgsSnappingConfig config;
  config.setEnabled(obj.value(QStringLiteral("enabled")).toBool(false));
  const bool hasLayers = obj.contains(QStringLiteral("layers"));
  const QString mode =
      obj.value(QStringLiteral("mode")).toString(QStringLiteral("all_layers"));
  if (hasLayers) {
    config.setMode(Qgis::SnappingMode::AdvancedConfiguration);
  } else if (mode == QLatin1String("active_layer")) {
    config.setMode(Qgis::SnappingMode::ActiveLayer);
  } else {
    config.setMode(Qgis::SnappingMode::AllLayers);
  }
  config.setTolerance(obj.value(QStringLiteral("tolerance_px")).toDouble(12.0));
  config.setUnits(Qgis::MapToolUnit::Pixels);
  config.setTypeFlag(parseSnappingTypes(
      obj.value(QStringLiteral("types")).toArray()));
  // V7：交点捕捉（Python SnappingService 的 intersection 模式）——
  // QgsSnappingConfig::intersectionSnapping 对全部配置层启用线段交点。
  config.setIntersectionSnapping(
      obj.value(QStringLiteral("intersection_enabled")).toBool(false));

  if (hasLayers) {
    const QJsonObject layers = obj.value(QStringLiteral("layers")).toObject();
    for (auto it = layers.begin(); it != layers.end(); ++it) {
      QgsVectorLayer* layer =
          findMirrorByDocId(project(), it.key().toStdString());
      if (layer == nullptr) continue;
      const QJsonObject ls = it.value().toObject();
      config.setIndividualLayerSettings(
          layer,
          QgsSnappingConfig::IndividualLayerSettings(
              ls.value(QStringLiteral("enabled")).toBool(true),
              parseSnappingTypes(ls.value(QStringLiteral("types")).toArray()),
              ls.value(QStringLiteral("tolerance_px"))
                  .toDouble(config.tolerance()),
              Qgis::MapToolUnit::Pixels));
    }
    // 参考点捕捉（井位等 pwb/reference 镜像层）：Python 侧 "reference" 模式
    // 的 QGIS 对应物——参考图层顶点参与捕捉；显式条目优先。
    if (obj.value(QStringLiteral("reference_enabled")).toBool(false)) {
      const auto configured = config.individualLayerSettings();
      for (auto* layer : project()->mapLayers().values()) {
        auto* vl = qobject_cast<QgsVectorLayer*>(layer);
        if (vl == nullptr || configured.contains(vl)) continue;
        if (vl->customProperty(QStringLiteral("pwb/reference")).toString() !=
            QLatin1String("true"))
          continue;
        config.setIndividualLayerSettings(
            vl, QgsSnappingConfig::IndividualLayerSettings(
                    true, Qgis::SnappingType::Vertex, config.tolerance(),
                    Qgis::MapToolUnit::Pixels));
      }
    }
  }
  canvas->snappingUtils()->setConfig(config);
}

std::string QgisMapStack::snapToMap(std::uintptr_t canvas_addr, double x,
                                    double y) const {
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  const QgsPointLocator::Match m =
      canvas->snappingUtils()->snapToMap(QgsPointXY(x, y));
  QJsonObject out;
  out[QStringLiteral("matched")] = m.isValid();
  if (m.isValid()) {
    const QgsPointXY p = m.point();
    out[QStringLiteral("x")] = p.x();
    out[QStringLiteral("y")] = p.y();
    out[QStringLiteral("vertex_index")] = m.hasVertex() ? m.vertexIndex() : -1;
    QString docId;
    if (m.layer() != nullptr) {
      docId = m.layer()
                  ->customProperty(QStringLiteral("pwb/doc_id"))
                  .toString();
    }
    out[QStringLiteral("layer_doc_id")] = docId;
  } else {
    out[QStringLiteral("x")] = x;
    out[QStringLiteral("y")] = y;
    out[QStringLiteral("vertex_index")] = -1;
    out[QStringLiteral("layer_doc_id")] = QString();
  }
  return QJsonDocument(out).toJson(QJsonDocument::Compact).toStdString();
}

bool QgisMapStack::nativeToolBusy(std::uintptr_t canvas_addr) const {
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  QgsMapTool* tool = canvas->mapTool();
  if (tool == nullptr) return false;
  // 采点中（已落至少一个点）：Esc 归原生工具（只取消本次捕捉）。
  // isCapturing() 是 protected，以 captureCurve 顶点数公开判定。
  if (const auto* capture = dynamic_cast<const QgsMapToolCapture*>(tool))
    return capture->captureCurve() != nullptr &&
           capture->captureCurve()->numPoints() > 0;
  // 顶点/移动拖动中：Esc 归原生工具（取消拖动，不退出工具）。
  if (const auto* pick = dynamic_cast<const PwbEditPickTool*>(tool))
    return pick->dragging();
  // 测距已采点：Esc 只清折线（V7）。
  if (const auto* measure = dynamic_cast<const PwbMeasureTool*>(tool))
    return measure->measuring();
  return false;
}

void QgisMapStack::setMapTool(std::uintptr_t canvas_addr, const std::string& kind) {
  ensureNotStale(canvas_addr);
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  impl_->canvas_refs[canvas_addr] = canvas;
  if (impl_->display_mode) {
    // measure 是只读检查工具（不写层），display 模式同样放行。
    if (kind != "pan" && kind != "zoomIn" && kind != "zoomOut" && kind != "measure") {
      throw std::runtime_error("display map stack does not host edit tools");
    }
  }
  // Release previous tool (Qt parent owns it) before overwriting — avoid double-delete
  auto existing = impl_->tools.find(canvas_addr);
  if (existing != impl_->tools.end() && existing->second) {
    if (canvas->mapTool() == existing->second.get()) {
      canvas->unsetMapTool(existing->second.get());
    }
    existing->second.release();
    impl_->tools.erase(existing);
  } else if (existing != impl_->tools.end()) {
    impl_->tools.erase(existing);
  }
  if (kind == "addPoint" || kind == "addLine" || kind == "addPolygon") {
    const int slot = kind == "addPoint" ? 0 : kind == "addLine" ? 1 : 2;
    canvas->setMapTool(digitizeToolFor(canvas_addr, canvas, slot));
    return;
  }
  if (kind == "vertex" || kind == "move") {
    canvas->setMapTool(editToolFor(canvas_addr, canvas, kind == "vertex"));
    return;
  }
  if (kind == "select" || kind == "identify") {
    std::weak_ptr<char> alive = alive_token_;
    auto cb = [this, alive, canvas_addr](const std::string& action,
                                         const std::string& payload) {
      if (alive.expired()) return;
      auto cbIt = impl_->selection_callbacks.find(canvas_addr);
      if (cbIt == impl_->selection_callbacks.end() || !cbIt->second) return;
      cbIt->second(action, payload);
    };
    if (kind == "select") {
      auto& slot = impl_->select_tools[canvas_addr];
      if (slot == nullptr)
        slot = new PwbSelectTool(canvas, std::move(cb), fidResolver());
      canvas->setMapTool(slot);
      return;
    }
    // identify 分支见下（targetLayer 钉死）。
    // QgsMapToolIdentifyFeature 无 setLayer——目标图层在构造时钉死；
    // 每次激活按当前图层新建（旧工具由 Qt parent=画布回收）。
    // 回调解析同样钉死构造时图层（终局审查 I3）：激活后切当前图层
    // 不得让 (doc_id, feature_id) 来自两个层。
    auto* targetLayer = qobject_cast<QgsVectorLayer*>(canvas->currentLayer());
    auto* tool = new QgsMapToolIdentifyFeature(canvas, targetLayer);
    impl_->identify_tools[canvas_addr] = tool;
    std::weak_ptr<char> alive2 = alive_token_;
    QObject::connect(
        tool,
        static_cast<void (QgsMapToolIdentifyFeature::*)(const QgsFeature&)>(
            &QgsMapToolIdentifyFeature::featureIdentified),
        canvas,
        [this, alive2, canvas_addr,
         target = QPointer<QgsVectorLayer>(targetLayer)](const QgsFeature& feature) {
        if (alive2.expired()) return;
        auto cbIt = impl_->selection_callbacks.find(canvas_addr);
        if (cbIt == impl_->selection_callbacks.end() || !cbIt->second) return;
        std::string docId;
        std::string fid = std::to_string(static_cast<long long>(feature.id()));
        if (!target.isNull()) {
          docId = target->customProperty(QStringLiteral("pwb/doc_id"))
                      .toString()
                      .toStdString();
          fid = fidResolver()(target.data(), feature.id());
        }
        cbIt->second("identify", std::string("{\"layer_doc_id\":\"") + docId +
                                     "\",\"feature_id\":\"" + fid + "\"}");
      });
    canvas->setMapTool(tool);
    return;
  }
  if (kind == "measure") {
    // V7 原生测距：工具实例缓存（Qt parent=画布），回调从 measure_callbacks
    // 表取——与 select/identify 同一防悬垂模式（alive_token_ + 表查找）。
    std::weak_ptr<char> alive = alive_token_;
    auto cb = [this, alive, canvas_addr](const std::string& action,
                                         const std::string& payload) {
      if (alive.expired()) return;
      auto cbIt = impl_->measure_callbacks.find(canvas_addr);
      if (cbIt == impl_->measure_callbacks.end() || !cbIt->second) return;
      cbIt->second(action, payload);
    };
    auto& slot = impl_->measure_tools[canvas_addr];
    if (slot == nullptr) slot = new PwbMeasureTool(canvas, std::move(cb));
    canvas->setMapTool(slot);
    return;
  }
  if (kind == "pan") {
    impl_->tools[canvas_addr] = std::make_unique<QgsMapToolPan>(canvas);
  } else if (kind == "zoomIn") {
    impl_->tools[canvas_addr] = std::make_unique<QgsMapToolZoom>(canvas, false);
  } else if (kind == "zoomOut") {
    impl_->tools[canvas_addr] = std::make_unique<QgsMapToolZoom>(canvas, true);
  } else {
    throw std::invalid_argument("unknown map tool kind: " + kind);
  }
  canvas->setMapTool(impl_->tools[canvas_addr].get());
}

QgsMapToolDigitizeFeature* QgisMapStack::digitizeToolFor(std::uintptr_t canvas_addr,
                                                         QgsMapCanvas* canvas, int slot) {
  auto& kit = impl_->capture_kits[canvas_addr];
  const QgsCoordinateReferenceSystem crs = canvas->mapSettings().destinationCrs();
  if (!kit.scratch[slot] || kit.scratch[slot]->crs() != crs) {
    const QString geom = slot == 0   ? QStringLiteral("Point")
                         : slot == 1 ? QStringLiteral("LineString")
                                     : QStringLiteral("Polygon");
    const QString uri = QStringLiteral("%1?crs=%2")
                            .arg(geom, crs.isValid() ? crs.authid()
                                                     : QStringLiteral("EPSG:4326"));
    auto layer = std::make_unique<QgsVectorLayer>(
        uri, QStringLiteral("__pwb_capture_scratch"), QStringLiteral("memory"));
    if (!layer->isValid())
      throw std::runtime_error("failed to create capture scratch layer");
    // QgsMapToolDigitizeFeature 要求 isEditable；scratch 不落持久化，无妨。
    layer->startEditing();
    kit.scratch[slot] = std::move(layer);
    kit.tools[slot] = nullptr;  // 旧工具由 Qt parent（画布）持有，弃用即可
  }
  if (kit.tools[slot] == nullptr) {
    QgsAdvancedDigitizingDockWidget* dock = nullptr;
    auto dockIt = impl_->cad_docks.find(canvas_addr);
    if (dockIt != impl_->cad_docks.end()) dock = dockIt->second.data();
    const auto mode = slot == 0   ? QgsMapToolCapture::CapturePoint
                      : slot == 1 ? QgsMapToolCapture::CaptureLine
                                  : QgsMapToolCapture::CapturePolygon;
    auto* tool = new QgsMapToolDigitizeFeature(canvas, dock, mode);
    tool->setLayer(kit.scratch[slot].get());
    std::weak_ptr<char> alive = alive_token_;
    QObject::connect(tool, &QgsMapToolDigitizeFeature::digitizingCompleted, canvas,
                     [this, alive, canvas_addr, slot, canvas](const QgsFeature& feature) {
      if (alive.expired()) return;
      auto cbIt = impl_->digitize_callbacks.find(canvas_addr);
      if (cbIt == impl_->digitize_callbacks.end() || !cbIt->second) return;
      // 终局审查 I2：scratch CRS 在工具激活时钉死；画布 CRS 中途变更后
      // 旧 CRS 几何不得静默写入权威会话——按 canceled 上报拒绝。
      // 画布 CRS 无效时 scratch 以 EPSG:4326 兜底创建（见 digitizeToolFor），
      // 该情形视为一致。
      auto kitIt = impl_->capture_kits.find(canvas_addr);
      const QgsCoordinateReferenceSystem canvasCrs =
          canvas->mapSettings().destinationCrs();
      if (canvasCrs.isValid() && kitIt != impl_->capture_kits.end() &&
          kitIt->second.scratch[slot] &&
          kitIt->second.scratch[slot]->crs() != canvasCrs) {
        cbIt->second("canceled", std::string());
        return;
      }
      cbIt->second("completed", feature.geometry().asJson().toStdString());
    });
    QObject::connect(tool, &QgsMapToolDigitizeFeature::digitizingCanceled, canvas,
                     [this, alive, canvas_addr]() {
      if (alive.expired()) return;
      auto cbIt = impl_->digitize_callbacks.find(canvas_addr);
      if (cbIt == impl_->digitize_callbacks.end() || !cbIt->second) return;
      cbIt->second("canceled", std::string());
    });
    kit.tools[slot] = tool;
  }
  return kit.tools[slot];
}

void QgisMapStack::setDigitizeCallback(
    std::uintptr_t canvas_addr,
    std::function<void(const std::string&, const std::string&)> callback) {
  ensureNotStale(canvas_addr);
  canvasOrThrow(canvas_addr);
  impl_->digitize_callbacks[canvas_addr] = std::move(callback);
}

std::function<std::string(QgsVectorLayer*, QgsFeatureId)>
QgisMapStack::fidResolver() {
  std::weak_ptr<char> alive = alive_token_;
  return [this, alive](QgsVectorLayer* vl, QgsFeatureId fid) -> std::string {
    if (alive.expired() || vl == nullptr) return {};
    const std::string docId = vl->customProperty(QStringLiteral("pwb/doc_id"))
                                  .toString()
                                  .toStdString();
    auto it = impl_->mirror_feature_fids.find(docId);
    if (it != impl_->mirror_feature_fids.end()) {
      auto jt = it->second.find(static_cast<long long>(fid));
      if (jt != it->second.end()) return jt->second;
    }
    return std::to_string(static_cast<long long>(fid));
  };
}

QgsMapTool* QgisMapStack::editToolFor(std::uintptr_t canvas_addr,
                                      QgsMapCanvas* canvas, bool vertex) {
  std::weak_ptr<char> alive = alive_token_;
  PwbEditPickTool::Callback cb = [this, alive, canvas_addr](
                                     const std::string& action,
                                     const std::string& payload) {
    if (alive.expired()) return;
    auto cbIt = impl_->edit_pick_callbacks.find(canvas_addr);
    if (cbIt == impl_->edit_pick_callbacks.end() || !cbIt->second) return;
    cbIt->second(action, payload);
  };
  PwbEditPickTool::FeatureIdResolver resolver = fidResolver();
  if (vertex) {
    auto& slot = impl_->vertex_tools[canvas_addr];
    if (slot == nullptr)
      slot = new PwbVertexTool(canvas, std::move(cb), std::move(resolver));
    return slot;
  }
  auto& slot = impl_->move_tools[canvas_addr];
  if (slot == nullptr)
    slot = new PwbMoveTool(canvas, std::move(cb), std::move(resolver));
  return slot;
}

void QgisMapStack::setEditPickCallback(
    std::uintptr_t canvas_addr,
    std::function<void(const std::string&, const std::string&)> callback) {
  ensureNotStale(canvas_addr);
  canvasOrThrow(canvas_addr);
  impl_->edit_pick_callbacks[canvas_addr] = std::move(callback);
}

void QgisMapStack::setSelectionCallback(
    std::uintptr_t canvas_addr,
    std::function<void(const std::string&, const std::string&)> callback) {
  ensureNotStale(canvas_addr);
  canvasOrThrow(canvas_addr);
  impl_->selection_callbacks[canvas_addr] = std::move(callback);
}

void QgisMapStack::setMeasureCallback(
    std::uintptr_t canvas_addr,
    std::function<void(const std::string&, const std::string&)> callback) {
  ensureNotStale(canvas_addr);
  canvasOrThrow(canvas_addr);
  impl_->measure_callbacks[canvas_addr] = std::move(callback);
}

void QgisMapStack::setCurrentLayer(std::uintptr_t canvas_addr,
                                   const std::string& doc_id) {
  ensureNotStale(canvas_addr);
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  QgsVectorLayer* layer = findMirrorByDocId(project(), doc_id);
  if (layer == nullptr)
    throw std::invalid_argument("unknown doc_id for current layer: " + doc_id);
  canvas->setCurrentLayer(layer);
}

void QgisMapStack::highlightFeatures(std::uintptr_t canvas_addr,
                                     const std::string& doc_id,
                                     const std::string& feature_ids_json) {
  ensureNotStale(canvas_addr);
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  QgsVectorLayer* layer = findMirrorByDocId(project(), doc_id);
  if (layer == nullptr)
    throw std::invalid_argument("unknown doc_id for highlight: " + doc_id);
  clearHighlights(canvas_addr);
  const QJsonDocument doc =
      QJsonDocument::fromJson(QByteArray::fromStdString(feature_ids_json));
  if (!doc.isArray()) throw std::invalid_argument("feature_ids must be a JSON array");
  // 反查：文档 feature_id → 镜像 QgsFeatureId
  std::unordered_map<std::string, long long> reverse;
  auto it = impl_->mirror_feature_fids.find(doc_id);
  if (it != impl_->mirror_feature_fids.end()) {
    for (const auto& kv : it->second) reverse[kv.second] = kv.first;
  }
  auto& bucket = impl_->highlights[canvas_addr];
  for (const QJsonValue& v : doc.array()) {
    const std::string fid = v.toString().toStdString();
    auto rit = reverse.find(fid);
    if (rit == reverse.end()) continue;
    QgsFeature feature;
    QgsFeatureIterator fit =
        layer->getFeatures(QgsFeatureRequest(static_cast<QgsFeatureId>(rit->second)));
    if (!fit.nextFeature(feature) || !feature.hasGeometry())
      continue;
    auto* h = new QgsHighlight(canvas, feature.geometry(), layer);
    bucket.emplace_back(h);
  }
  canvas->refresh();
}

void QgisMapStack::clearHighlights(std::uintptr_t canvas_addr) {
  auto it = impl_->highlights.find(canvas_addr);
  if (it != impl_->highlights.end()) {
    it->second.clear();
    impl_->highlights.erase(it);
  }
  auto refIt = impl_->canvas_refs.find(canvas_addr);
  if (refIt != impl_->canvas_refs.end() && !refIt->second.isNull())
    refIt->second->refresh();
}

int QgisMapStack::highlightCount(std::uintptr_t canvas_addr) const {
  auto it = impl_->highlights.find(canvas_addr);
  return it == impl_->highlights.end() ? 0 : static_cast<int>(it->second.size());
}

void QgisMapStack::setExtentCallback(std::uintptr_t canvas_addr, ExtentCallback callback) {
  ensureNotStale(canvas_addr);
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  impl_->canvas_refs[canvas_addr] = canvas;
  auto ecIt = impl_->extent_connections.find(canvas_addr);
  if (ecIt != impl_->extent_connections.end()) {
    QObject::disconnect(ecIt->second);
    impl_->extent_connections.erase(ecIt);
  }
  impl_->extent_callbacks[canvas_addr] = std::move(callback);
  QMetaObject::Connection conn = QObject::connect(canvas, &QgsMapCanvas::extentsChanged, canvas, [this, canvas_addr]() {
    auto refIt = impl_->canvas_refs.find(canvas_addr);
    if (refIt == impl_->canvas_refs.end() || refIt->second.isNull()) return;
    auto cbIt = impl_->extent_callbacks.find(canvas_addr);
    if (cbIt == impl_->extent_callbacks.end() || !cbIt->second) return;
    QgsMapCanvas* c = refIt->second;
    const QgsRectangle r = c->extent();
    cbIt->second(r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum());
  });
  impl_->extent_connections[canvas_addr] = conn;
}

void QgisMapStack::setXyCallback(std::uintptr_t canvas_addr, PointCallback callback) {
  ensureNotStale(canvas_addr);
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  impl_->canvas_refs[canvas_addr] = canvas;
  auto xcIt = impl_->xy_connections.find(canvas_addr);
  if (xcIt != impl_->xy_connections.end()) {
    QObject::disconnect(xcIt->second);
    impl_->xy_connections.erase(xcIt);
  }
  impl_->xy_callbacks[canvas_addr] = std::move(callback);
  QMetaObject::Connection conn = QObject::connect(canvas, &QgsMapCanvas::xyCoordinates, canvas,
                   [this, canvas_addr](const QgsPointXY& p) {
    auto refIt = impl_->canvas_refs.find(canvas_addr);
    if (refIt == impl_->canvas_refs.end() || refIt->second.isNull()) return;
    auto cbIt = impl_->xy_callbacks.find(canvas_addr);
    if (cbIt == impl_->xy_callbacks.end() || !cbIt->second) return;
    cbIt->second(p.x(), p.y());
  });
  impl_->xy_connections[canvas_addr] = conn;
}

void QgisMapStack::cleanupTreeViewState(std::uintptr_t tree_view) {
  // per-view 状态全清（M2 终局审查 I2）：view 先亡（面板关闭/重建）或地址
  // 复用时不得残留 flush 标记 / pending 批次 / 死连接，否则新树的回调整体失效。
  // 注意：不在此销毁含 py::function 的回调 std::function——destroyed 信号
  // 运行在 shiboken 延迟删除链上，就地销毁会踩解释器态（GC_Del segfault，
  // gdb 实锤）。挪到孤儿坟场，由 shutdown/dtor（绑定层正常路径）销毁。
  impl_->tree_change_connections.erase(tree_view);
  impl_->tree_sel_connections.erase(tree_view);
  auto selCb = impl_->tree_sel_callbacks.find(tree_view);
  if (selCb != impl_->tree_sel_callbacks.end()) {
    impl_->orphan_tree_callbacks.push_back(std::move(selCb->second));
    impl_->tree_sel_callbacks.erase(selCb);
  }
  auto changeCb = impl_->tree_change_callbacks.find(tree_view);
  if (changeCb != impl_->tree_change_callbacks.end()) {
    impl_->orphan_tree_callbacks.push_back(std::move(changeCb->second));
    impl_->tree_change_callbacks.erase(changeCb);
  }
  auto menuCb = impl_->tree_menu_callbacks.find(tree_view);
  if (menuCb != impl_->tree_menu_callbacks.end()) {
    impl_->orphan_tree_menu_callbacks.push_back(std::move(menuCb->second));
    impl_->tree_menu_callbacks.erase(menuCb);
  }
  auto expandCb = impl_->tree_expand_callbacks.find(tree_view);
  if (expandCb != impl_->tree_expand_callbacks.end()) {
    impl_->orphan_tree_expand_callbacks.push_back(std::move(expandCb->second));
    impl_->tree_expand_callbacks.erase(expandCb);
  }
  impl_->tree_pending.erase(tree_view);
  impl_->tree_flush_scheduled.erase(tree_view);
  impl_->tree_views.erase(tree_view);
  impl_->tree_models.erase(tree_view);
  impl_->tree_canvas.erase(tree_view);
}

std::uintptr_t QgisMapStack::createLayerTreeView(std::uintptr_t canvas_addr) {
  if (impl_->display_mode) {
    throw std::runtime_error("display map stack has no layer tree");
  }
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  (void)canvas;
  QgsLayerTree* root = project()->layerTreeRoot();
  auto* model = new QgsLayerTreeModel(root);
  auto* view = new QgsLayerTreeView();
  model->setParent(view);
  model->setFlag(QgsLayerTreeModel::ShowLegend);
  model->setFlag(QgsLayerTreeModel::AllowNodeReorder);
  model->setFlag(QgsLayerTreeModel::AllowNodeRename);
  model->setFlag(QgsLayerTreeModel::AllowNodeChangeVisibility);
  view->setModel(model);
  const auto addr = reinterpret_cast<std::uintptr_t>(view);
  cleanupTreeViewState(addr);  // 地址复用：先清残留（正常路径全为空，幂等）
  std::weak_ptr<char> alive = alive_token_;
  QObject::connect(view, &QObject::destroyed,
                   [this, alive, addr]() {
                     if (alive.expired()) return;  // 栈先析构：impl_ 不可达
                     cleanupTreeViewState(addr);
                   });
  impl_->tree_views[addr] = view;
  impl_->tree_models[addr] = model;
  impl_->tree_canvas[addr] = canvas;
  auto& conns = impl_->tree_change_connections[addr];
  conns.push_back(QObject::connect(
      model, &QgsLayerTreeModel::dataChanged, view,
      [this, addr](const QModelIndex& topLeft, const QModelIndex&, const QVector<int>& roles) {
        const bool allRoles = roles.isEmpty();
        onTreeDataChanged(addr, topLeft,
                          allRoles || roles.contains(Qt::CheckStateRole),
                          allRoles || roles.contains(Qt::DisplayRole) || roles.contains(Qt::EditRole));
      }));
  conns.push_back(QObject::connect(
      model, &QgsLayerTreeModel::rowsMoved, view,
      [this, addr](const QModelIndex&, int, int, const QModelIndex&, int) {
        onTreeOrderChanged(addr, true);
      }));
  // QGIS 的节点移动（含用户 DnD：insertChildNodes + removeRows）不产生
  // rowsMoved，而是 rowsInserted/rowsRemoved 成对出现；flush 已按 tick 合并。
  // V5 分组：组内插入/移除同样是结构变化；图例行（图层节点之下）仍是噪声。
  conns.push_back(QObject::connect(
      model, &QgsLayerTreeModel::rowsInserted, view,
      [this, addr, model](const QModelIndex& parent, int, int) {
        QgsLayerTreeNode* parentNode =
            parent.isValid() ? model->index2node(parent) : nullptr;
        if (parent.isValid()) {
          // 只关心 root/组之下的插入；图层节点下是图例行。
          if (treeLayerCast(parentNode) != nullptr) return;
          onTreeOrderChanged(addr, true);
          return;
        }
        onTreeOrderChanged(addr, false);  // 顶层排序变化（legacy order 键）
      }));
  conns.push_back(QObject::connect(
      model, &QgsLayerTreeModel::rowsRemoved, view,
      [this, addr, model](const QModelIndex& parent, int, int) {
        QgsLayerTreeNode* parentNode =
            parent.isValid() ? model->index2node(parent) : nullptr;
        if (parent.isValid()) {
          if (treeLayerCast(parentNode) != nullptr) return;
          onTreeOrderChanged(addr, true);
          return;
        }
        onTreeOrderChanged(addr, false);
      }));
  // 组展开态回调（V5 StageViewState 持久化）。expandedChanged 是
  // QgsLayerTreeNode 级信号：树视图创建/组创建时对全部节点接线。
  wireNodeExpandSignalsRecursively(root);
  return addr;
}

void QgisMapStack::wireNodeExpandSignalsRecursively(QgsLayerTreeNode* node) {
  // 只接组节点（StageViewState 的展开态是组级语义）；layer 接线会让
  // 大规模插入每层触发一次 Python 回调（GIL 往返），大树上不可接受。
  if (node == nullptr) return;
  if (treeGroupCast(node) == nullptr) return;
  if (node != project()->layerTreeRoot()) {
    wireNodeExpandSignal(node);
  }
  const QList<QgsLayerTreeNode*> children = node->children();
  for (QgsLayerTreeNode* child : children) {
    if (treeGroupCast(child) != nullptr) {
      wireNodeExpandSignalsRecursively(child);
    }
  }
}

void QgisMapStack::wireNodeExpandSignal(QgsLayerTreeNode* node) {
  if (node == nullptr) return;
  // 去重标记：custom property 随节点生灭（地址复用不会误判已接线）。
  if (node->customProperty("pwb/expand_wired").toBool()) return;
  node->setCustomProperty("pwb/expand_wired", true);
  std::weak_ptr<char> alive = alive_token_;
  impl_->node_expand_connections.push_back(QObject::connect(
      node, &QgsLayerTreeNode::expandedChanged, node,
      [this, alive](QgsLayerTreeNode* changed, bool expanded) {
        if (alive.expired()) return;
        if (impl_->suppress_tree_callbacks > 0) return;
        std::string id;
        if (auto* group = treeGroupCast(changed)) {
          id = ensureGroupNodeId(group);
        } else if (auto* layerNode = treeLayerCast(changed)) {
          if (layerNode->layer() != nullptr) {
            id = layerNode->layer()
                     ->customProperty(QStringLiteral("pwb/doc_id"))
                     .toString().toStdString();
          }
        }
        if (id.empty()) return;
        for (auto& kv : impl_->tree_expand_callbacks) {
          if (kv.second) kv.second(id, expanded);
        }
      }));
}

QgsLayerTreeView* QgisMapStack::treeViewOrThrow(std::uintptr_t address) const {
  const auto it = impl_->tree_views.find(address);
  if (it == impl_->tree_views.end() || it->second.isNull()) {
    throw std::invalid_argument("layer tree view address no longer valid");
  }
  return it->second.data();
}

void QgisMapStack::setTreeSelectionCallback(
    std::uintptr_t tree_addr, std::function<void(const std::string&)> callback) {
  QgsLayerTreeView* view = treeViewOrThrow(tree_addr);
  impl_->tree_sel_callbacks[tree_addr] = std::move(callback);
  auto connIt = impl_->tree_sel_connections.find(tree_addr);
  if (connIt != impl_->tree_sel_connections.end()) {
    QObject::disconnect(connIt->second);
    impl_->tree_sel_connections.erase(connIt);
  }
  impl_->tree_sel_connections[tree_addr] = QObject::connect(
      view, &QgsLayerTreeView::currentLayerChanged, view,
      [this, tree_addr](QgsMapLayer* layer) {
        const auto it = impl_->tree_sel_callbacks.find(tree_addr);
        if (it == impl_->tree_sel_callbacks.end() || !it->second) return;
        auto viewIt = impl_->tree_views.find(tree_addr);
        if (viewIt == impl_->tree_views.end() || viewIt->second.isNull()) return;
        std::string id;
        if (layer != nullptr) {
          const QVariant doc = layer->customProperty(QStringLiteral("pwb/doc_id"));
          id = (doc.isValid() && !doc.toString().isEmpty())
                   ? doc.toString().toStdString()
                   : layer->id().toStdString();
        }
        it->second(id);
      });
}

int QgisMapStack::treeViewRowCount(std::uintptr_t tree) const {
  QgsLayerTreeView* view = treeViewOrThrow(tree);
  QAbstractItemModel* model = view->model();
  if (model == nullptr) throw std::runtime_error("tree view model is null");
  return model->rowCount();
}

std::string QgisMapStack::treeViewLayerName(std::uintptr_t tree, int row) const {
  QgsLayerTreeView* view = treeViewOrThrow(tree);
  QAbstractItemModel* model = view->model();
  if (model == nullptr) throw std::runtime_error("tree view model is null");
  QModelIndex idx = model->index(row, 0);
  if (!idx.isValid()) throw std::out_of_range("tree view row out of range: " + std::to_string(row));
  QVariant d = model->data(idx, Qt::DisplayRole);
  return d.toString().toStdString();
}

void QgisMapStack::treeViewSetCurrentRow(std::uintptr_t tree, int row) {
  QgsLayerTreeView* view = treeViewOrThrow(tree);
  QAbstractItemModel* model = view->model();
  if (model == nullptr) throw std::runtime_error("tree view model is null");
  QModelIndex idx = model->index(row, 0);
  if (!idx.isValid()) throw std::out_of_range("tree view row out of range: " + std::to_string(row));
  view->setCurrentIndex(idx);
}

void QgisMapStack::setTreeChangeCallback(
    std::uintptr_t tree_addr, std::function<void(const std::string&)> callback) {
  treeViewOrThrow(tree_addr);
  impl_->tree_change_callbacks[tree_addr] = std::move(callback);
}

void QgisMapStack::setTreeExpandCallback(
    std::uintptr_t tree_addr,
    std::function<void(const std::string&, bool)> callback) {
  treeViewOrThrow(tree_addr);
  // 孤儿回调坟场语义同 tree_change_callbacks（destroyed 链上不能销毁
  // 含 py::function 的 std::function）。
  auto it = impl_->tree_expand_callbacks.find(tree_addr);
  if (it != impl_->tree_expand_callbacks.end()) {
    impl_->orphan_tree_expand_callbacks.push_back(std::move(it->second));
    impl_->tree_expand_callbacks.erase(it);
  }
  impl_->tree_expand_callbacks[tree_addr] = std::move(callback);
  // 既有树节点统一接线（新节点在 upsertGroup 时接线）。
  wireNodeExpandSignalsRecursively(project()->layerTreeRoot());
}

void QgisMapStack::onTreeDataChanged(std::uintptr_t tree_addr, const QModelIndex& topLeft,
                                     bool check_role, bool display_role) {
  if (impl_->suppress_tree_callbacks > 0) return;
  if (!impl_->tree_change_callbacks.count(tree_addr)) return;
  auto viewIt = impl_->tree_views.find(tree_addr);
  if (viewIt == impl_->tree_views.end() || viewIt->second.isNull()) return;
  auto mIt = impl_->tree_models.find(tree_addr);
  if (mIt == impl_->tree_models.end() || mIt->second.isNull()) return;
  QgsLayerTreeModel* model = mIt->second.data();
  // V5：index2node 支持任意深度（组内图层的勾选/改名同样回写）。
  QgsLayerTreeNode* node = topLeft.isValid() ? model->index2node(topLeft) : nullptr;
  if (node == nullptr) return;
  auto& pending = impl_->tree_pending[tree_addr];
  bool touched = false;
  if (auto* layerNode = treeLayerCast(node)) {
    QgsMapLayer* layer = layerNode->layer();
    if (layer == nullptr) return;
    const QVariant docVar = layer->customProperty(QStringLiteral("pwb/doc_id"));
    if (!docVar.isValid() || docVar.toString().isEmpty()) return;
    const std::string doc_id = docVar.toString().toStdString();
    if (check_role) {
      const bool checked = layerNode->itemVisibilityChecked();
      auto shadowIt = impl_->known_layer_visibility.find(doc_id);
      if (shadowIt == impl_->known_layer_visibility.end()) {
        impl_->known_layer_visibility[doc_id] = checked;  // 首次见面只建基线
      } else if (shadowIt->second != checked) {
        shadowIt->second = checked;
        pending.visibility[QString::fromStdString(doc_id)] = checked;
        appendTreeEvent(&pending.events, "visibility", "layer", doc_id, checked);
        touched = true;
      }
    }
    if (display_role) {
      const std::string name = layer->name().toStdString();
      auto shadowIt = impl_->known_layer_names.find(doc_id);
      if (shadowIt == impl_->known_layer_names.end()) {
        impl_->known_layer_names[doc_id] = name;  // 首次见面只建基线，不报重命名
      } else if (shadowIt->second != name) {
        shadowIt->second = name;
        pending.renames[QString::fromStdString(doc_id)] = QString::fromStdString(name);
        appendTreeEvent(&pending.events, "rename", "layer", doc_id, name);
        touched = true;
      }
    }
  } else if (auto* groupNode = treeGroupCast(node)) {
    // V5：组节点勾选（tri-state 语义由 QGIS 原生处理）/改名回写。
    const std::string gid = ensureGroupNodeId(groupNode);
    if (gid.empty()) return;
    if (check_role) {
      const bool checked = groupNode->itemVisibilityChecked();
      auto shadowIt = impl_->known_group_visibility.find(gid);
      if (shadowIt == impl_->known_group_visibility.end()) {
        impl_->known_group_visibility[gid] = checked;
      } else if (shadowIt->second != checked) {
        shadowIt->second = checked;
        appendTreeEvent(&pending.events, "visibility", "group", gid, checked);
        touched = true;
      }
    }
    if (display_role) {
      const std::string name = groupNode->name().toStdString();
      auto shadowIt = impl_->known_group_names.find(gid);
      if (shadowIt == impl_->known_group_names.end()) {
        impl_->known_group_names[gid] = name;
      } else if (shadowIt->second != name) {
        shadowIt->second = name;
        appendTreeEvent(&pending.events, "rename", "group", gid, name);
        touched = true;
      }
    }
  }
  if (touched) scheduleTreeChangeFlush(tree_addr);
}

void QgisMapStack::onTreeOrderChanged(std::uintptr_t tree_addr, bool structure) {
  if (impl_->suppress_tree_callbacks > 0) return;
  if (!impl_->tree_change_callbacks.count(tree_addr)) return;
  auto viewIt = impl_->tree_views.find(tree_addr);
  if (viewIt == impl_->tree_views.end() || viewIt->second.isNull()) return;
  auto& pending = impl_->tree_pending[tree_addr];
  pending.order.clear();
  for (const auto& doc : mirrorOrderTopFirst()) {
    pending.order.push_back(QString::fromStdString(doc));
  }
  if (structure) {
    // V5：全层级结构快照（覆盖 move/group-create/group-delete，用户在
    // QGIS 树里的任何重排/建组/删组经此一次性回声，Python 侧 diff）。
    pending.tree_dirty = true;
  }
  scheduleTreeChangeFlush(tree_addr);
}

void QgisMapStack::scheduleTreeChangeFlush(std::uintptr_t tree_addr) {
  if (!impl_->tree_flush_scheduled.insert(tree_addr).second) return;
  auto viewIt = impl_->tree_views.find(tree_addr);
  if (viewIt == impl_->tree_views.end() || viewIt->second.isNull()) {
    impl_->tree_flush_scheduled.erase(tree_addr);
    return;
  }
  QgsLayerTreeView* view = viewIt->second.data();
  std::weak_ptr<char> alive = alive_token_;
  QTimer::singleShot(0, view, [this, alive, tree_addr]() {
    if (alive.expired()) return;  // 栈先析构（view 由宿主面板持有，可活得更久）
    impl_->tree_flush_scheduled.erase(tree_addr);
    flushTreeChange(tree_addr);
  });
}

void QgisMapStack::flushTreeChange(std::uintptr_t tree_addr) {
  auto pIt = impl_->tree_pending.find(tree_addr);
  if (pIt == impl_->tree_pending.end()) return;
  Impl::TreeChangeBatch batch = std::move(pIt->second);
  impl_->tree_pending.erase(pIt);
  auto cbIt = impl_->tree_change_callbacks.find(tree_addr);
  if (cbIt == impl_->tree_change_callbacks.end() || !cbIt->second) return;
  if (batch.empty()) return;
  QJsonObject root;
  // V5 schema 2：保留 legacy visibility/order/renames 键（平铺图层语义，
  // 旧消费者不破），追加 typed events 与全层级 tree 快照。
  root.insert(QStringLiteral("schema"), 2);
  if (!batch.visibility.isEmpty()) {
    QJsonObject vis;
    for (auto it = batch.visibility.begin(); it != batch.visibility.end(); ++it) {
      vis.insert(it.key(), it.value());
    }
    root.insert(QStringLiteral("visibility"), vis);
  }
  if (!batch.order.isEmpty()) {
    root.insert(QStringLiteral("order"), QJsonArray::fromStringList(batch.order));
  }
  if (!batch.renames.isEmpty()) {
    QJsonObject ren;
    for (auto it = batch.renames.begin(); it != batch.renames.end(); ++it) {
      ren.insert(it.key(), it.value());
    }
    root.insert(QStringLiteral("renames"), ren);
  }
  if (!batch.events.isEmpty()) {
    root.insert(QStringLiteral("events"), batch.events);
  }
  if (batch.tree_dirty) {
    QJsonArray children;
    for (QgsLayerTreeNode* child : project()->layerTreeRoot()->children()) {
      appendNodeToJson(child, &children);
    }
    root.insert(QStringLiteral("tree"), children);
  }
  cbIt->second(QString::fromUtf8(
      QJsonDocument(root).toJson(QJsonDocument::Compact)).toStdString());
}

void QgisMapStack::treeViewSetRowChecked(std::uintptr_t tree, int row, bool checked) {
  QgsLayerTreeView* view = treeViewOrThrow(tree);
  QAbstractItemModel* model = view->model();
  if (model == nullptr) throw std::runtime_error("tree view model is null");
  QModelIndex idx = model->index(row, 0);
  if (!idx.isValid()) throw std::out_of_range("tree view row out of range: " + std::to_string(row));
  // 模拟用户勾选：不包 SuppressGuard，刻意触发回调
  if (!model->setData(idx, checked ? Qt::Checked : Qt::Unchecked, Qt::CheckStateRole)) {
    throw std::runtime_error("tree view setData(CheckStateRole) failed");
  }
}

void QgisMapStack::treeViewRenameRow(std::uintptr_t tree, int row, const std::string& name) {
  QgsLayerTreeView* view = treeViewOrThrow(tree);
  QAbstractItemModel* model = view->model();
  if (model == nullptr) throw std::runtime_error("tree view model is null");
  QModelIndex idx = model->index(row, 0);
  if (!idx.isValid()) throw std::out_of_range("tree view row out of range: " + std::to_string(row));
  // 模拟用户重命名：不包 SuppressGuard，刻意触发回调。
  // 注意：QGIS 的 setData(EditRole) 落地后 fallthrough 到 QAbstractItemModel::setData
  // 返回 false，返回值不可用作成败依据——以节点名核验。
  model->setData(idx, QString::fromStdString(name), Qt::EditRole);
  if (model->data(idx, Qt::DisplayRole).toString().toStdString() != name) {
    throw std::runtime_error("tree view rename failed (name not applied)");
  }
}

void QgisMapStack::treeViewMoveRow(std::uintptr_t tree, int from, int to) {
  QgsLayerTreeView* view = treeViewOrThrow(tree);
  QAbstractItemModel* model = view->model();
  if (model == nullptr) throw std::runtime_error("tree view model is null");
  const int count = model->rowCount();
  if (from < 0 || from >= count || to < 0 || to >= count) {
    throw std::out_of_range("tree view row out of range: " + std::to_string(from) +
                            " -> " + std::to_string(to));
  }
  if (from == to) return;
  // 用户拖拽等价物（与 QGIS DnD 同序）：先在目标位插入同一 layer 的新节点，
  // 再移除旧节点——registry bridge 的延迟删除按 findLayer 检查跳过仍在树中的
  // 图层（groupRemovedChildren: "ignores layers that were dragged'n'dropped:
  // 1. drop new 2. remove old"）。反过来先 take 后插会把图层从 project 误删。
  // QgsLayerTreeModel 不实现 moveRows，不能直接走模型。
  QgsLayerTreeGroup* root = project()->layerTreeRoot();
  QgsLayerTreeLayer* node = treeLayerCast(root->children().value(from));
  if (!node || !node->layer()) throw std::runtime_error("tree view moveRow: source node missing");
  QgsLayerTreeNode* parent = node->parent();
  if (!parent) throw std::runtime_error("tree view moveRow: node has no parent");
  auto* clone = new QgsLayerTreeLayer(node->layer());
  clone->setItemVisibilityChecked(node->itemVisibilityChecked());
  clone->setExpanded(node->isExpanded());
  root->insertChildNode(to > from ? to + 1 : to, clone);
  parent->takeChild(node);  // orphan，不销毁
  delete node;              // 旧节点由我们销毁（等价 DnD 的 removeRows 路径）
  if (model->rowCount() != count) {
    throw std::runtime_error("tree view moveRow failed (row count changed)");
  }
}

void QgisMapStack::setTreeMenuCallback(
    std::uintptr_t tree_addr,
    std::function<void(const std::string&, const std::string&)> callback) {
  QgsLayerTreeView* view = treeViewOrThrow(tree_addr);
  impl_->tree_menu_callbacks[tree_addr] = callback;
  // setMenuProvider 接管所有权并销毁旧 provider，重设安全。
  QPointer<QgsMapCanvas> canvas;
  auto canvasIt = impl_->tree_canvas.find(tree_addr);
  if (canvasIt != impl_->tree_canvas.end()) canvas = canvasIt->second;
  view->setMenuProvider(new PwbLayerTreeMenuProvider(
      view, canvas, std::move(callback)));
}

void QgisMapStack::zoomToLayer(std::uintptr_t tree_addr, const std::string& doc_id) {
  QgsLayerTreeView* view = treeViewOrThrow(tree_addr);
  (void)view;
  QgsVectorLayer* layer = nullptr;
  auto it = impl_->mirror_by_doc.find(doc_id);
  if (it != impl_->mirror_by_doc.end()) {
    layer = qobject_cast<QgsVectorLayer*>(
        project()->mapLayer(QString::fromStdString(it->second)));
  }
  if (!layer) layer = findMirrorByDocId(project(), doc_id);
  if (!layer) throw std::invalid_argument("unknown doc_id: " + doc_id);
  QPointer<QgsMapCanvas> canvas;
  auto canvasIt = impl_->tree_canvas.find(tree_addr);
  if (canvasIt != impl_->tree_canvas.end()) canvas = canvasIt->second;
  if (canvas.isNull()) throw std::runtime_error("tree view canvas is no longer valid");
  QgsRectangle ext = layer->extent();
  if (ext.isEmpty()) {
    // 语义与 QGIS「缩放至图层」归一（M2 移交项）：空图层（新建零要素）
    // 回退全图缩放，而不是无操作。
    canvas->zoomToFullExtent();
    canvas->refresh();
    return;
  }
  const QgsCoordinateReferenceSystem dest = canvas->mapSettings().destinationCrs();
  if (dest.isValid() && layer->crs() != dest) {
    QgsCoordinateTransform ct(layer->crs(), dest, project());
    ext = ct.transformBoundingBox(ext);
  }
  canvas->setExtent(ext);
  canvas->refresh();
}

void QgisMapStack::setEditIndicator(std::uintptr_t tree_addr,
                                    const std::string& doc_id, bool on) {
  QgsLayerTreeView* view = treeViewOrThrow(tree_addr);
  QgsMapLayer* layer = nullptr;
  auto it = impl_->mirror_by_doc.find(doc_id);
  if (it != impl_->mirror_by_doc.end()) {
    layer = project()->mapLayer(QString::fromStdString(it->second));
  }
  if (!layer) layer = findMirrorByDocId(project(), doc_id);
  if (!layer) return;  // 未镜像（例如尚未上树）时静默忽略——面板状态仍会记录
  QgsLayerTreeLayer* node = project()->layerTreeRoot()->findLayer(layer);
  if (!node) return;
  // 幂等：先摘除本栈挂过的编辑指示器（removeIndicator 负责销毁对象）。
  for (QgsLayerTreeViewIndicator* ind : view->indicators(node)) {
    if (ind->property("pwb_edit").toBool()) view->removeIndicator(node, ind);
  }
  if (!on) return;
  // QGIS 桌面经图层指示器呈现编辑态；vendored 主题无铅笔资源，绘字符图标。
  QPixmap pixmap(16, 16);
  pixmap.fill(Qt::transparent);
  QPainter painter(&pixmap);
  QFont font = painter.font();
  font.setPixelSize(13);
  painter.setFont(font);
  painter.drawText(pixmap.rect(), Qt::AlignCenter, QStringLiteral("✏"));
  auto* indicator = new QgsLayerTreeViewIndicator(view);
  indicator->setProperty("pwb_edit", true);
  indicator->setIcon(QIcon(pixmap));
  indicator->setToolTip(QStringLiteral("编辑中"));
  view->addIndicator(node, indicator);
}

int QgisMapStack::editIndicatorCount(std::uintptr_t tree_addr,
                                     const std::string& doc_id) const {
  QgsLayerTreeView* view = treeViewOrThrow(tree_addr);
  QgsMapLayer* layer = nullptr;
  auto it = impl_->mirror_by_doc.find(doc_id);
  if (it != impl_->mirror_by_doc.end()) {
    layer = project()->mapLayer(QString::fromStdString(it->second));
  }
  if (!layer) layer = findMirrorByDocId(project(), doc_id);
  if (!layer) return 0;
  QgsLayerTreeLayer* node = project()->layerTreeRoot()->findLayer(layer);
  if (!node) return 0;
  int count = 0;
  for (QgsLayerTreeViewIndicator* ind : view->indicators(node)) {
    if (ind->property("pwb_edit").toBool()) ++count;
  }
  return count;
}

// ---------------------------------------------------------------------------
// V8 M5: 通用行指示器。kinds 词汇与 host state_language（layer_decorations
// .py 的 LayerPresentationState 装饰集）逐词对齐——桥只绘制，不发明状态；
// 未知 kind 静默跳过（host 端"未知=无装饰"同语义）。editing 仍由
// setEditIndicator 独占（✏ 铅笔），本 API 不处理 editing。
// ---------------------------------------------------------------------------
namespace {
struct RowIndicatorStyle {
    const char* glyph;
    const char* label;
    const char* color;  // 设计 tokens（tokens.py）语义色的 hex
};

const QMap<QString, RowIndicatorStyle>& rowIndicatorStyles() {
    static const QMap<QString, RowIndicatorStyle> styles{
        {QStringLiteral("dirty"), {"✎", "未保存修改", "#b45309"}},
        {QStringLiteral("stale"), {"↻", "已过期", "#b45309"}},
        {QStringLiteral("missing"), {"✕", "缺失", "#d31f1f"}},
        {QStringLiteral("missing_input"), {"✕", "输入缺失", "#d31f1f"}},
        {QStringLiteral("superseded"), {"↻", "已被取代", "#b45309"}},
        {QStringLiteral("degraded"), {"◌", "回退", "#b45309"}},
        {QStringLiteral("frozen"), {"❄", "冻结", "#53616c"}},
        {QStringLiteral("published"), {"◉", "已发布", "#15803d"}},
        {QStringLiteral("reviewed"), {"✓", "已复核", "#15803d"}},
    };
    return styles;
}
}  // namespace

void QgisMapStack::setRowIndicators(std::uintptr_t tree_addr,
                                    const std::string& doc_id,
                                    const std::string& kinds_json) {
  QgsLayerTreeView* view = treeViewOrThrow(tree_addr);
  QgsMapLayer* layer = nullptr;
  auto it = impl_->mirror_by_doc.find(doc_id);
  if (it != impl_->mirror_by_doc.end()) {
    layer = project()->mapLayer(QString::fromStdString(it->second));
  }
  if (!layer) layer = findMirrorByDocId(project(), doc_id);
  if (!layer) return;  // 未镜像时静默忽略——面板状态记录仍是权威
  QgsLayerTreeLayer* node = project()->layerTreeRoot()->findLayer(layer);
  if (!node) return;
  // 幂等：先摘除本栈挂过的行指示器（edit 铅笔不动）。
  for (QgsLayerTreeViewIndicator* ind : view->indicators(node)) {
    if (ind->property("pwb_row").toBool()) view->removeIndicator(node, ind);
  }
  QJsonParseError err;
  const QJsonDocument doc = QJsonDocument::fromJson(
      QByteArray::fromStdString(kinds_json).trimmed(), &err);
  if (err.error != QJsonParseError::NoError || !doc.isArray()) {
    throw std::invalid_argument(
        "kinds_json: malformed indicator payload: " + err.errorString().toStdString());
  }
  int emitted = 0;
  for (const QJsonValue& v : doc.array()) {
    const auto style = rowIndicatorStyles().constFind(v.toString());
    if (style == rowIndicatorStyles().constEnd()) continue;  // 未知 kind：跳过
    QPixmap pixmap(16, 16);
    pixmap.fill(Qt::transparent);
    QPainter painter(&pixmap);
    QFont font = painter.font();
    font.setPixelSize(13);
    painter.setFont(font);
    painter.setPen(QColor(QLatin1String(style->color)));
    painter.drawText(pixmap.rect(), Qt::AlignCenter,
                     QString::fromUtf8(style->glyph));
    painter.end();
    auto* indicator = new QgsLayerTreeViewIndicator(view);
    indicator->setProperty("pwb_row", true);
    indicator->setProperty("pwb_kind", v.toString());
    indicator->setIcon(QIcon(pixmap));
    indicator->setToolTip(QString::fromUtf8(style->label));
    view->addIndicator(node, indicator);
    ++emitted;
  }
  node->setCustomProperty(QStringLiteral("pwb/row_indicator_count"), emitted);
}

int QgisMapStack::rowIndicatorCount(std::uintptr_t tree_addr,
                                    const std::string& doc_id,
                                    const std::string& kind) const {
  QgsLayerTreeView* view = treeViewOrThrow(tree_addr);
  QgsMapLayer* layer = nullptr;
  auto it = impl_->mirror_by_doc.find(doc_id);
  if (it != impl_->mirror_by_doc.end()) {
    layer = project()->mapLayer(QString::fromStdString(it->second));
  }
  if (!layer) layer = findMirrorByDocId(project(), doc_id);
  if (!layer) return 0;
  QgsLayerTreeLayer* node = project()->layerTreeRoot()->findLayer(layer);
  if (!node) return 0;
  int count = 0;
  for (QgsLayerTreeViewIndicator* ind : view->indicators(node)) {
    if (!ind->property("pwb_row").toBool()) continue;
    if (!kind.empty()
        && ind->property("pwb_kind").toString().toStdString() != kind) {
      continue;
    }
    ++count;
  }
  return count;
}

bool QgisMapStack::treeViewSelectDoc(std::uintptr_t tree, const std::string& doc_id) {
  QgsLayerTreeView* view = treeViewOrThrow(tree);
  QgsMapLayer* layer = nullptr;
  auto it = impl_->mirror_by_doc.find(doc_id);
  if (it != impl_->mirror_by_doc.end()) {
    layer = project()->mapLayer(QString::fromStdString(it->second));
  }
  if (!layer) layer = findMirrorByDocId(project(), doc_id);
  if (!layer) return false;
  QgsLayerTreeLayer* node = project()->layerTreeRoot()->findLayer(layer);
  if (!node) return false;
  view->setCurrentIndex(view->node2index(node));
  return true;
}

void QgisMapStack::setMirrorLayerOpacity(const std::string& doc_id, double opacity) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  QgsMapLayer* layer = nullptr;
  auto it = impl_->mirror_by_doc.find(doc_id);
  if (it != impl_->mirror_by_doc.end()) {
    layer = project()->mapLayer(QString::fromStdString(it->second));
  }
  if (!layer) layer = findMapMirrorByDocId(project(), doc_id);
  if (!layer) throw std::invalid_argument("unknown doc_id: " + doc_id);
  layer->setOpacity(std::clamp(opacity, 0.0, 1.0));  // 触发 repaintRequested → 画布桥自动刷新
}

std::map<std::string, std::string> QgisMapStack::execLayerProperties(
    std::uintptr_t canvas_addr, const std::string& doc_id) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  QCoreApplication* application = QCoreApplication::instance();
  if (application == nullptr || qobject_cast<QApplication*>(application) == nullptr) {
    throw std::runtime_error("layer properties dialog requires QApplication (GUI host)");
  }
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  QgsVectorLayer* layer = nullptr;
  auto it = impl_->mirror_by_doc.find(doc_id);
  if (it != impl_->mirror_by_doc.end()) {
    layer = qobject_cast<QgsVectorLayer*>(
        project()->mapLayer(QString::fromStdString(it->second)));
  }
  if (!layer) layer = findMirrorByDocId(project(), doc_id);
  if (!layer) throw std::invalid_argument("unknown mirror layer: " + doc_id);

  QgsVectorLayerProperties dialog(canvas, nullptr, layer);
  const int code = dialog.exec();
  std::map<std::string, std::string> result;
  result["ok"] = code == QDialog::Accepted ? "1" : "0";
  if (code != QDialog::Accepted) return result;
  if (layer->renderer() != nullptr) {
    result["renderer_xml"] = renderer_to_xml(*layer->renderer());
  }
  if (layer->labelsEnabled() && layer->labeling() != nullptr) {
    QDomDocument doc;
    QgsReadWriteContext context;
    doc.appendChild(layer->labeling()->save(doc, context));
    result["labeling_xml"] = doc.toString().toStdString();
  }
  result["opacity"] = std::to_string(layer->opacity());
  result["name"] = layer->name().toStdString();
  layer->triggerRepaint();
  return result;
}

// --------------------------------------------------------------------------- //
// M7: QgsLayout composition export (M6 component graph → native layout)
// --------------------------------------------------------------------------- //

namespace {

QgsLayoutPoint mmPoint(double x, double y) {
  return QgsLayoutPoint(x, y, Qgis::LayoutUnit::Millimeters);
}

QgsLayoutSize mmSize(double w, double h) {
  return QgsLayoutSize(w, h, Qgis::LayoutUnit::Millimeters);
}

QColor jsonColor(const QJsonObject& obj, const char* key, const QColor& fallback) {
  const QString raw = obj.value(QLatin1String(key)).toString();
  if (raw.isEmpty()) return fallback;
  return QColor(raw);
}

std::unique_ptr<QgsFillSymbol> fillSymbol(const QString& color, bool outline) {
  QVariantMap props;
  props.insert(QStringLiteral("color"), color);
  if (outline) {
    props.insert(QStringLiteral("outline_color"), QStringLiteral("#202020"));
    props.insert(QStringLiteral("outline_width"), QStringLiteral("0.3"));
  } else {
    props.insert(QStringLiteral("outline_style"), QStringLiteral("no"));
  }
  // QGIS 4 returns an owning pointer; the layout item takes ownership on set.
  return QgsFillSymbol::createSimple(props);
}

}  // namespace

std::string QgisMapStack::layoutExport(const std::string& spec_json,
                                       const std::string& output_path,
                                       const std::string& format,
                                       double dpi) {
  if (!QCoreApplication::instance()) {
    throw std::runtime_error(
        "layout export requires an initialised QGIS application (bridge "
        "initialize() must run first)");
  }
  const QJsonDocument doc = QJsonDocument::fromJson(
      QByteArray::fromStdString(spec_json));
  if (!doc.isObject()) {
    throw std::invalid_argument("layout spec must be a JSON object");
  }
  const QJsonObject spec = doc.object();
  const QJsonObject page = spec.value(QStringLiteral("page")).toObject();
  const double page_w = page.value(QStringLiteral("width_mm")).toDouble(297.0);
  const double page_h = page.value(QStringLiteral("height_mm")).toDouble(210.0);
  if (page_w <= 0.0 || page_h <= 0.0) {
    throw std::invalid_argument("page width_mm/height_mm must be positive");
  }

  QgsPrintLayout layout(project());
  layout.initializeDefaults();
  QgsLayoutItemPage* page_item = layout.pageCollection()->page(0);
  page_item->setPageSize(mmSize(page_w, page_h));
  const QString background =
      page.value(QStringLiteral("background")).toString();
  if (!background.isEmpty()) {
    page_item->setPageStyleSymbol(
        fillSymbol(background, /*outline=*/false).release());
  }

  std::map<std::string, QgsLayoutItemMap*> maps_by_key;
  int item_count = 0;
  const QJsonArray items = spec.value(QStringLiteral("items")).toArray();
  for (const QJsonValue& value : items) {
    if (!value.isObject()) continue;
    const QJsonObject item = value.toObject();
    const QString type = item.value(QStringLiteral("type")).toString();
    const double x = item.value(QStringLiteral("x")).toDouble();
    const double y = item.value(QStringLiteral("y")).toDouble();
    const double w = item.value(QStringLiteral("w")).toDouble();
    const double h = item.value(QStringLiteral("h")).toDouble();

    if (type == QLatin1String("map")) {
      QgsLayoutItemMap* map = new QgsLayoutItemMap(&layout);
      map->attemptMove(mmPoint(x, y));
      map->attemptResize(mmSize(w, h));
      const QString crs_id = item.value(QStringLiteral("crs")).toString();
      if (!crs_id.isEmpty()) {
        map->setCrs(QgsCoordinateReferenceSystem(crs_id));
      }
      const QJsonArray extent = item.value(QStringLiteral("extent")).toArray();
      if (extent.size() == 4) {
        map->setExtent(QgsRectangle(extent.at(0).toDouble(),
                                    extent.at(1).toDouble(),
                                    extent.at(2).toDouble(),
                                    extent.at(3).toDouble()));
      }
      // Layers: mirrorOrderTopFirst is top-first; QgsLayoutItemMap consumes
      // bottom-first draw order.
      QList<QgsMapLayer*> ordered;
      const std::vector<std::string> order = mirrorOrderTopFirst();
      for (auto it = order.rbegin(); it != order.rend(); ++it) {
        QgsMapLayer* layer = project()->mapLayer(
            QString::fromStdString(*it));
        if (layer) ordered.append(layer);
      }
      if (!ordered.isEmpty()) {
        map->setLayers(ordered);
      }
      map->setFrameEnabled(item.value(QStringLiteral("frame")).toBool(true));
      const QJsonObject grid = item.value(QStringLiteral("grid")).toObject();
      if (grid.value(QStringLiteral("enabled")).toBool(false)) {
        QgsLayoutItemMapGrid* map_grid = map->grid();  // first grid (auto-created)
        map_grid->setEnabled(true);
        map_grid->setIntervalX(
            grid.value(QStringLiteral("interval_x")).toDouble());
        map_grid->setIntervalY(
            grid.value(QStringLiteral("interval_y")).toDouble());
        map_grid->setAnnotationEnabled(
            grid.value(QStringLiteral("annotation")).toBool(true));
        if (!crs_id.isEmpty()) {
          map_grid->setCrs(QgsCoordinateReferenceSystem(crs_id));
        }
      }
      layout.addLayoutItem(map);
      const std::string key =
          item.value(QStringLiteral("key")).toString().toStdString();
      maps_by_key[key.empty() ? std::string("map") : key] = map;
      ++item_count;
      continue;
    }

    QgsLayoutItemMap* linked_map = nullptr;
    const std::string map_key =
        item.value(QStringLiteral("map_item")).toString().toStdString();
    if (!map_key.empty() || type == QLatin1String("legend") ||
        type == QLatin1String("scalebar") ||
        type == QLatin1String("north_arrow")) {
      const auto found = maps_by_key.find(
          map_key.empty() ? std::string("map") : map_key);
      if (found == maps_by_key.end()) {
        throw std::invalid_argument(
            "item references unknown map key: " + map_key);
      }
      linked_map = found->second;
    }

    if (type == QLatin1String("legend")) {
      QgsLayoutItemLegend* legend = new QgsLayoutItemLegend(&layout);
      legend->setTitle(item.value(QStringLiteral("title"))
                           .toString(QStringLiteral("图例")));
      if (linked_map) legend->setLinkedMap(linked_map);
      legend->setResizeToContents(
          item.value(QStringLiteral("resize_to_contents")).toBool(true));
      legend->attemptMove(mmPoint(x, y));
      legend->setBackgroundEnabled(
          item.value(QStringLiteral("background")).toBool(true));
      // V8 M8: legend filter（V7 08 §1 的显式 follow-up）。filter_layers 是
      // include 表（doc_id 或 QGIS layer id/name）。QGIS 4.2 的公开路径：
      // setSyncMode(Manual) 内部克隆工程树（setCustomLayerTree 已私有），
      // model()->rootGroup() 即那份手动树——在其上剪枝不动工程本树。
      // 空/缺省 = 不过滤（历史行为，列全部层）。
      const QJsonArray filter =
          item.value(QStringLiteral("filter_layers")).toArray();
      if (linked_map && !filter.isEmpty()) {
        QSet<QString> keep_ids;
        for (const QJsonValue& v : filter) {
          const QString key = v.toString();
          if (key.isEmpty()) continue;
          // 解析顺序：mirror doc_id → QGIS layer id → layer name。
          QString resolved;
          auto mirror = impl_->mirror_by_doc.find(key.toStdString());
          if (mirror != impl_->mirror_by_doc.end()) {
            resolved = QString::fromStdString(mirror->second);
          } else if (project()->mapLayer(key) != nullptr) {
            resolved = project()->mapLayer(key)->id();
          } else {
            const QList<QgsMapLayer*> by_name = project()->mapLayersByName(key);
            if (!by_name.isEmpty()) resolved = by_name.first()->id();
          }
          if (!resolved.isEmpty()) keep_ids.insert(resolved);
        }
        if (!keep_ids.isEmpty()) {
          legend->setSyncMode(Qgis::LegendSyncMode::Manual);
          // 剪掉不在 include 表里的层与因此变空的组（removeChildNode 连节点
          // 一起销毁——手动树归 legend 所有）；模型监听树信号自动重绘。
          const std::function<void(QgsLayerTreeGroup*)> prune =
              [&](QgsLayerTreeGroup* branch) {
                const QList<QgsLayerTreeNode*> children = branch->children();
                for (QgsLayerTreeNode* child : children) {
                  if (QgsLayerTree::isGroup(child)) {
                    prune(QgsLayerTree::toGroup(child));
                    if (child->children().isEmpty()) {
                      branch->removeChildNode(child);
                    }
                  } else if (QgsLayerTree::isLayer(child)) {
                    auto* layer_node = static_cast<QgsLayerTreeLayer*>(child);
                    if (layer_node->layer() == nullptr
                        || !keep_ids.contains(layer_node->layer()->id())) {
                      branch->removeChildNode(child);
                    }
                  }
                }
              };
          prune(legend->model()->rootGroup());
        }
      }
      layout.addLayoutItem(legend);
      ++item_count;
    } else if (type == QLatin1String("scalebar")) {
      QgsLayoutItemScaleBar* scalebar = new QgsLayoutItemScaleBar(&layout);
      if (!linked_map) {
        throw std::invalid_argument("scalebar requires a linked map item");
      }
      scalebar->setLinkedMap(linked_map);
      scalebar->applyDefaultSettings();
      scalebar->applyDefaultSize(Qgis::DistanceUnit::Meters);
      const int segments = item.value(QStringLiteral("segments")).toInt(0);
      if (segments > 0) scalebar->setNumberOfSegments(segments);
      const double units_per_segment =
          item.value(QStringLiteral("units_per_segment")).toDouble(0.0);
      if (units_per_segment > 0.0) {
        scalebar->setUnitsPerSegment(units_per_segment);
      }
      const QString unit_label =
          item.value(QStringLiteral("unit_label")).toString();
      if (!unit_label.isEmpty()) scalebar->setUnitLabel(unit_label);
      scalebar->attemptMove(mmPoint(x, y));
      layout.addLayoutItem(scalebar);
      ++item_count;
    } else if (type == QLatin1String("north_arrow") ||
               type == QLatin1String("picture")) {
      QString svg_path = item.value(QStringLiteral("svg_path"))
                             .toString(item.value(QStringLiteral("path"))
                                           .toString());
      if (svg_path.isEmpty() && type == QLatin1String("north_arrow")) {
        const QString data_dir = QgsApplication::pkgDataPath();
        QStringList candidates{
            data_dir + QStringLiteral("/svg/arrows/NorthArrow_02.svg"),
            data_dir + QStringLiteral("/data/svg/arrows/NorthArrow_02.svg"),
        };
        if (!PALEO_QGIS_PREFIX_PATH.empty()) {
          const QString vendor_prefix =
              QString::fromStdString(PALEO_QGIS_PREFIX_PATH);
          candidates << vendor_prefix +
                            QStringLiteral("/data/svg/arrows/NorthArrow_02.svg")
                     << vendor_prefix +
                            QStringLiteral("/svg/arrows/NorthArrow_02.svg");
        }
        for (const QString& candidate : candidates) {
          if (QFile::exists(candidate)) {
            svg_path = candidate;
            break;
          }
        }
        if (svg_path.isEmpty()) {
          throw std::runtime_error(
              "north arrow SVG not found in the vendored QGIS data dir; "
              "pass svg_path explicitly");
        }
      }
      QgsLayoutItemPicture* picture = new QgsLayoutItemPicture(&layout);
      picture->setPicturePath(svg_path);
      picture->attemptMove(mmPoint(x, y));
      picture->attemptResize(mmSize(w, h));
      layout.addLayoutItem(picture);
      ++item_count;
    } else if (type == QLatin1String("label")) {
      QgsLayoutItemLabel* label = new QgsLayoutItemLabel(&layout);
      label->setText(item.value(QStringLiteral("text")).toString());
      QgsTextFormat text_format;
      QFont font;
      font.setPointSizeF(
          item.value(QStringLiteral("font_size")).toDouble(10.0));
      font.setBold(item.value(QStringLiteral("bold")).toBool(false));
      text_format.setFont(font);
      text_format.setColor(jsonColor(item, "color", QColor(Qt::black)));
      label->setTextFormat(text_format);
      const QString halign =
          item.value(QStringLiteral("halign")).toString();
      if (halign == QLatin1String("center"))
        label->setHAlign(Qt::AlignHCenter);
      else if (halign == QLatin1String("right"))
        label->setHAlign(Qt::AlignRight);
      label->attemptMove(mmPoint(x, y));
      label->attemptResize(mmSize(w, h));
      layout.addLayoutItem(label);
      ++item_count;
    } else if (type == QLatin1String("shape")) {
      QgsLayoutItemShape* shape = new QgsLayoutItemShape(&layout);
      shape->setShapeType(QgsLayoutItemShape::Rectangle);
      const QString fill = item.value(QStringLiteral("fill")).toString();
      // Frame via symbology: outline when framed, no outline otherwise.
      shape->setSymbol(
          fillSymbol(
              fill.isEmpty() ? QStringLiteral("#00000000") : fill,
              item.value(QStringLiteral("frame")).toBool(true))
              .release());
      shape->attemptMove(mmPoint(x, y));
      shape->attemptResize(mmSize(w, h));
      layout.addLayoutItem(shape);
      ++item_count;
    } else {
      throw std::invalid_argument("unknown layout item type: " +
                                  type.toStdString());
    }
  }
  if (item_count == 0) {
    throw std::invalid_argument("layout spec contains no items");
  }

  QgsLayoutExporter exporter(&layout);
  QgsLayoutExporter::ExportResult result;
  if (format == QLatin1String("pdf")) {
    QgsLayoutExporter::PdfExportSettings settings;
    settings.dpi = dpi;
    // D10: GeoPDF is available in the vendored QGIS and opt-in per export.
    settings.writeGeoPdf =
        spec.value(QStringLiteral("geo_pdf")).toBool(false);
    result = exporter.exportToPdf(QString::fromStdString(output_path),
                                  settings);
  } else if (format == QLatin1String("svg")) {
    QgsLayoutExporter::SvgExportSettings settings;
    settings.dpi = dpi;
    result = exporter.exportToSvg(QString::fromStdString(output_path),
                                  settings);
  } else if (format == QLatin1String("png")) {
    QgsLayoutExporter::ImageExportSettings settings;
    settings.dpi = dpi;
    result = exporter.exportToImage(QString::fromStdString(output_path),
                                    settings);
  } else {
    throw std::invalid_argument("format must be pdf|svg|png, got: " + format);
  }
  if (result != QgsLayoutExporter::Success) {
    // D10/V7 never-fake contract: a failed export (e.g. GeoPDF without a
    // capable GDAL PDF driver — PrintError) must not leave a partial file
    // behind that callers could mistake for the requested product.
    std::error_code remove_error;
    std::filesystem::remove(output_path, remove_error);
    throw std::runtime_error("layout export failed with result code " +
                             std::to_string(static_cast<int>(result)));
  }
  QJsonObject report;
  report.insert(QStringLiteral("ok"), true);
  report.insert(QStringLiteral("path"),
                QString::fromStdString(output_path));
  report.insert(QStringLiteral("format"), QString::fromStdString(format));
  report.insert(QStringLiteral("dpi"), dpi);
  report.insert(QStringLiteral("items"), item_count);
  report.insert(QStringLiteral("page_mm"), QJsonArray{page_w, page_h});
  return QJsonDocument(report).toJson(QJsonDocument::Compact).toStdString();
}

}  // namespace pwb::qgis_render
