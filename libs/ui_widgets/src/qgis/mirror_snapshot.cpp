#include "pwb/ui_widgets/qgis/mirror_snapshot.hpp"

#include <QDomDocument>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QRegularExpression>
#include <QSet>

#include <cmath>

#include <qgscoordinatereferencesystem.h>
#include <qgsfeature.h>
#include <qgsfields.h>
#include <qgsgeometry.h>
#include <qgsjsonutils.h>
#include <qgslayertree.h>
#include <qgslayertreegroup.h>
#include <qgslayertreelayer.h>
#include <qgslayertreenode.h>
#include <qgsmapcanvas.h>
#include <qgsmaplayer.h>
#include <qgsproject.h>
#include <qgsreadwritecontext.h>
#include <qgsrenderer.h>
#include <qgsvectorlayer.h>
#include <qgsvectorlayerlabeling.h>

namespace pwb::ui_widgets::qgis {
namespace {

// _normalize_crs_name parity: leading "EPSG:<digits>" token uppercased
// is the stable comparison key; anything else stays raw.
QString normalize_crs_name(const QString& value) {
    const QString text = value.trimmed();
    static const QRegularExpression re(QStringLiteral("^(EPSG:\\d+)\\b"),
                                       QRegularExpression::CaseInsensitiveOption);
    const auto match = re.match(text);
    return match.hasMatch() ? match.captured(1).toUpper() : text;
}

// crs_is_geographic delegated to the real authority — QGIS itself.
// Unverifiable ids stay non-geographic (fail-open: the extent check only
// drops CRSs it can prove wrong — same contract as the Python literal).
bool crs_is_geographic(const QString& auth) {
    if (auth.isEmpty()) return false;
    return QgsCoordinateReferenceSystem(auth).isGeographic();
}

bool extent_fits_crs(const QString& crs, const std::vector<double>& extent) {
    if (extent.size() < 4) return true;
    if (!crs_is_geographic(crs)) return true;
    return std::abs(extent[0]) <= 180 && std::abs(extent[2]) <= 180 &&
           std::abs(extent[1]) <= 90 && std::abs(extent[3]) <= 90;
}

// Recursive coordinate walk → bounding box (crs_gate.feature_bounds
// parity: extent missing → feature-record bbox fallback).
bool feature_bounds(const QVariantList& features, double out[4]) {
    bool any = false;
    double xmin = 0, ymin = 0, xmax = 0, ymax = 0;
    QVariantList stack;
    for (const QVariant& f : features) {
        if (f.typeId() == QMetaType::QVariantMap) {
            stack.push_back(f.toMap()
                              .value(QStringLiteral("geometry"))
                              .toMap()
                              .value(QStringLiteral("coordinates")));
        }
    }
    while (!stack.isEmpty()) {
        const QVariant item = stack.takeLast();
        if (item.typeId() == QMetaType::QVariantList) {
            const QVariantList list = item.toList();
            bool all_numbers = !list.isEmpty();
            for (const QVariant& v : list) {
                switch (v.typeId()) {
                    case QMetaType::Int:
                    case QMetaType::UInt:
                    case QMetaType::LongLong:
                    case QMetaType::ULongLong:
                    case QMetaType::Double:
                    case QMetaType::Float:
                        break;
                    default:
                        all_numbers = false;
                        break;
                }
            }
            if (all_numbers && list.size() >= 2) {
                const double x = list[0].toDouble();
                const double y = list[1].toDouble();
                if (!any) {
                    xmin = xmax = x;
                    ymin = ymax = y;
                    any = true;
                } else {
                    xmin = std::min(xmin, x);
                    xmax = std::max(xmax, x);
                    ymin = std::min(ymin, y);
                    ymax = std::max(ymax, y);
                }
            } else {
                for (const QVariant& v : list) stack.push_back(v);
            }
        }
    }
    if (any) {
        out[0] = xmin;
        out[1] = ymin;
        out[2] = xmax;
        out[3] = ymax;
    }
    return any;
}

QString qgis_crs_for_snapshot(const MirrorSnapshot& snapshot,
                            const std::function<void(const QString&,
                                                     const QString&)>& sink) {
    const QString auth = normalize_crs_name(snapshot.project_crs);
    if (auth.isEmpty()) return {};
    for (const MirrorLayerSpec& layer : snapshot.layers) {
        if (!extent_fits_crs(auth, layer.extent)) {
            sink(layer.id,
                 QStringLiteral(
                     "snapshot layer extent outside degree domain — canvas "
                     "CRS %1 not pushed")
                     .arg(auth));
            return {};
        }
    }
    return auth;
}

QString qgis_crs_for_layer(const MirrorLayerSpec& layer,
                           const MirrorSnapshot& snapshot,
                           const std::function<void(const QString&,
                                                    const QString&)>& sink) {
    QString auth =
        normalize_crs_name(!layer.crs.isEmpty() ? layer.crs
                                                : snapshot.project_crs);
    std::vector<double> extent = layer.extent;
    if (!auth.isEmpty() && crs_is_geographic(auth) && extent.size() < 4) {
        // R5: extent missing → fall back to the feature-record bbox —
        // an empty extent must NOT let a geographic CRS through (the
        // local-coords layer + geographic project CRS pollution shape).
        double bounds[4];
        if (feature_bounds(layer.features, bounds)) {
            extent.assign(bounds, bounds + 4);
        }
    }
    if (!auth.isEmpty() && !extent_fits_crs(auth, extent)) {
        sink(layer.id,
             QStringLiteral(
                 "layer extent outside degree domain — CRS %1 not set on "
                 "mirror")
                 .arg(auth));
        return {};
    }
    return auth;
}

// style signature = renderer_xml \x1e labeling_xml \x1e legacy_json
// (Python _style_signature; \x1e is the ASCII record separator).
std::string style_signature(const QString& renderer_xml,
                            const QString& labeling_xml,
                            const QVariantMap& legacy_style) {
    QString legacy_json;
    if (!legacy_style.isEmpty()) {
        legacy_json = QString::fromUtf8(
            QJsonDocument::fromVariant(legacy_style).toJson(
                QJsonDocument::Compact));
    }
    return (renderer_xml + QLatin1Char('\x1e') + labeling_xml +
            QLatin1Char('\x1e') + legacy_json)
        .toStdString();
}

// GeoJSON type string → memory-provider geometry keyword.
QString geom_keyword(const MirrorLayerSpec& layer) {
    static const std::map<QString, QString> kTypeMap = {
        {"Point", "Point"},
        {"MultiPoint", "MultiPoint"},
        {"LineString", "LineString"},
        {"MultiLineString", "MultiLineString"},
        {"Polygon", "Polygon"},
        {"MultiPolygon", "MultiPolygon"},
    };
    if (!layer.features.isEmpty()) {
        const QVariantMap first = layer.features.first().toMap();
        const QString type =
            first.value(QStringLiteral("geometry"))
                .toMap()
                .value(QStringLiteral("type"))
                .toString();
        const auto it = kTypeMap.find(type);
        if (it != kTypeMap.end()) return it->second;
        return QStringLiteral("Point");
    }
    // Zero-feature layers still go on the tree (I1) — geometry kind from
    // metadata.geometry_kind, defaulting to Point.
    static const std::map<QString, QString> kKindGeom = {
        {"point", "Point"},
        {"line", "LineString"},
        {"polygon", "Polygon"},
    };
    const QString kind =
        layer.metadata.value(QStringLiteral("geometry_kind")).toString();
    const auto it = kKindGeom.find(kind);
    return it != kKindGeom.end() ? it->second : QStringLiteral("Point");
}

// fields_json → QgsFields ("name","type" records; the Python schema
// vocabulary uses QGIS-flavoured type names).
QgsFields fields_from_json(const QString& fields_json, bool* ok) {
    QgsFields fields;
    *ok = true;
    if (fields_json.isEmpty()) return fields;
    const QJsonDocument doc =
        QJsonDocument::fromJson(fields_json.toUtf8());
    if (!doc.isArray()) {
        *ok = false;
        return fields;
    }
    static const std::map<QString, QVariant::Type> kTypes = {
        {"string", QVariant::String}, {"text", QVariant::String},
        {"int", QVariant::Int}, {"integer", QVariant::Int},
        {"long", QVariant::LongLong}, {"double", QVariant::Double},
        {"real", QVariant::Double}, {"float", QVariant::Double},
        {"bool", QVariant::Bool}, {"boolean", QVariant::Bool},
        {"date", QVariant::Date}, {"datetime", QVariant::DateTime},
    };
    for (const QJsonValue& v : doc.array()) {
        const QJsonObject o = v.toObject();
        const QString name = o.value(QStringLiteral("name")).toString();
        if (name.isEmpty()) continue;
        const QString type =
            o.value(QStringLiteral("type")).toString().toLower();
        const auto it = kTypes.find(type);
        fields.append(QgsField(
            name, it != kTypes.end() ? it->second : QVariant::String));
    }
    return fields;
}

// Legacy property-only path: union of property keys across features
// (sorted — QVariantMap carries no insertion order; attribute identity
// is by name so order is observational only).
QgsFields fields_from_features(const QVariantList& features,
                               bool* has_fid_field) {
    QgsFields fields;
    QSet<QString> seen;
    *has_fid_field = false;
    for (const QVariant& f : features) {
        const QVariantMap props =
            f.toMap().value(QStringLiteral("properties")).toMap();
        for (auto it = props.constBegin(); it != props.constEnd(); ++it) {
            if (seen.contains(it.key())) continue;
            seen.insert(it.key());
            QVariant::Type type = QVariant::String;
            switch (it.value().typeId()) {
                case QMetaType::Int:
                    type = QVariant::Int;
                    break;
                case QMetaType::LongLong:
                case QMetaType::ULongLong:
                    type = QVariant::LongLong;
                    break;
                case QMetaType::Double:
                case QMetaType::Float:
                    type = QVariant::Double;
                    break;
                case QMetaType::Bool:
                    type = QVariant::Bool;
                    break;
                default:
                    type = QVariant::String;
            }
            fields.append(QgsField(it.key(), type));
        }
    }
    *has_fid_field = seen.contains(QString::fromLatin1(kPwbFidField));
    return fields;
}

// Push features onto a memory layer; returns "" or the failure reason.
QString push_features(QgsVectorLayer* vl, const QVariantList& features) {
    if (features.isEmpty()) return {};
    QgsFeatureList list;
    list.reserve(features.size());
    for (const QVariant& fv : features) {
        const QVariantMap f = fv.toMap();
        QgsFeature feature(vl->fields());
        const QVariantMap geometry_map =
            f.value(QStringLiteral("geometry")).toMap();
        if (!geometry_map.isEmpty()) {
            const QString geom_json = QString::fromUtf8(
                QJsonDocument::fromVariant(geometry_map)
                    .toJson(QJsonDocument::Compact));
            const QgsGeometry geom =
                QgsJsonUtils::geometryFromGeoJson(geom_json);
            if (geom.isNull()) {
                return QStringLiteral("invalid GeoJSON geometry");
            }
            feature.setGeometry(geom);
        }
        const QVariantMap props =
            f.value(QStringLiteral("properties")).toMap();
        for (auto it = props.constBegin(); it != props.constEnd(); ++it) {
            const int idx = vl->fields().indexOf(it.key());
            if (idx >= 0) {
                feature.setAttribute(idx, it.value());
            }
        }
        const int fid_idx =
            vl->fields().indexOf(QString::fromLatin1(kPwbFidField));
        if (fid_idx >= 0) {
            // Doc feature id rides along as __pwb_fid (memory provider
            // keeps no fid authority; native pick tools resolve through
            // it — the bridge-side fid map's role).
            const QVariant doc_fid = f.value(QStringLiteral("id"));
            if (doc_fid.isValid() && !doc_fid.isNull()) {
                feature.setAttribute(fid_idx, doc_fid.toString());
            }
        }
        list.push_back(feature);
    }
    if (!vl->dataProvider()->addFeatures(list)) {
        return QStringLiteral("memory provider refused features");
    }
    vl->updateExtents();
    return {};
}

// Apply renderer_xml (a <renderer-v2> fragment); returns failure reason
// or "". A fragment that fails to parse is an honest failure — never a
// silent default renderer (the Python bridge stores it verbatim).
QString apply_renderer_xml(QgsVectorLayer* vl, const QString& xml) {
    if (xml.trimmed().isEmpty()) return {};
    QDomDocument doc;
    QString error;
    int line = 0, col = 0;
    if (!doc.setContent(QStringLiteral("<root>") + xml +
                            QStringLiteral("</root>"),
                        &error, &line, &col)) {
        return QStringLiteral("renderer_xml parse failed: %1").arg(error);
    }
    const QDomElement root = doc.documentElement();
    QDomElement elem = root.firstChildElement(QStringLiteral("renderer-v2"));
    if (elem.isNull()) {
        // The stored payload may itself be the bare element.
        QDomDocument doc2;
        if (!doc2.setContent(xml)) {
            return QStringLiteral("renderer_xml parse failed");
        }
        elem = doc2.documentElement();
    }
    const QgsReadWriteContext context;
    QgsFeatureRenderer* renderer = QgsFeatureRenderer::load(elem, context);
    if (renderer == nullptr) {
        return QStringLiteral("renderer_xml rejected by QGIS");
    }
    vl->setRenderer(renderer);
    return {};
}

QString apply_labeling_xml(QgsVectorLayer* vl, const QString& xml) {
    if (xml.trimmed().isEmpty()) return {};
    QDomDocument doc;
    if (!doc.setContent(xml)) {
        return QStringLiteral("labeling_xml parse failed");
    }
    const QgsReadWriteContext context;
    QgsAbstractVectorLayerLabeling* labeling =
        QgsAbstractVectorLayerLabeling::create(doc.documentElement(),
                                               context);
    if (labeling == nullptr) {
        return QStringLiteral("labeling_xml rejected by QGIS");
    }
    vl->setLabeling(labeling);
    vl->setLabelsEnabled(true);
    return {};
}

QgsMapLayer* find_mirror_layer(QgsProject& project, const QString& doc_id) {
    const auto layers = project.mapLayers();
    for (auto it = layers.constBegin(); it != layers.constEnd(); ++it) {
        QgsMapLayer* layer = it.value();
        if (layer != nullptr &&
            layer->customProperty(QString::fromLatin1(kDocIdProperty))
                    .toString() == doc_id) {
            return layer;
        }
    }
    return nullptr;
}

void sink_into(QStringList* diags, const QString& doc_id,
               const QString& message) {
    if (diags != nullptr) {
        diags->append(doc_id + QStringLiteral(": ") + message);
    }
}

}  // namespace

const MirrorLedger::Tokens* MirrorLedger::entry(const QString& doc_id) const {
    const auto it = entries_.find(doc_id);
    return it != entries_.end() ? &it->second.second : nullptr;
}

void MirrorLedger::store(const QString& doc_id, const QString& qgis_id,
                         const Tokens& tokens) {
    entries_[doc_id] = {qgis_id, tokens};
}

void MirrorLedger::erase(const QString& doc_id) {
    entries_.erase(doc_id);
}

MirrorResult mirror_snapshot_to_project(QgsProject& project,
                                        const MirrorSnapshot& snapshot,
                                        const MirrorOptions& options,
                                        MirrorLedger& ledger,
                                        QStringList* diags) {
    MirrorResult result;
    const auto sink = [diags](const QString& doc_id,
                              const QString& message) {
        sink_into(diags, doc_id, message);
    };

    // Canvas/project CRS (V10 M-B: an EMPTY declared crs still gets
    // pushed — otherwise a project switch leaves the canvas rendering
    // under the previous project's CRS; invalid/no-OTF is the honest
    // raw-coordinate mode, aligned with the fallback renderer).
    const QString canvas_crs = qgis_crs_for_snapshot(snapshot, sink);
    {
        const QgsCoordinateReferenceSystem crs(canvas_crs);
        if (!canvas_crs.isEmpty() && !crs.isValid()) {
            result.failures.append(
                QStringLiteral("crs %1: invalid authority id").arg(canvas_crs));
        }
        project.setCrs(crs);
    }

    // V10 M-E: duplicate doc_ids in one snapshot — the first publishes,
    // later duplicates are refused (one Paleo layer == one QgsMapLayer).
    std::set<QString> seen_ids, duplicate_ids;
    for (const MirrorLayerSpec& layer : snapshot.layers) {
        if (!seen_ids.insert(layer.id).second) {
            duplicate_ids.insert(layer.id);
        }
    }
    for (const QString& dup : duplicate_ids) {
        result.failures.append(
            QStringLiteral("layer %1: duplicate layer id in snapshot").arg(dup));
        sink(dup, QStringLiteral(
                      "duplicate layer id in snapshot; publishing first "
                      "occurrence only"));
    }

    // Refresh window (tree_transaction parity): one native paint window
    // for the whole publish.
    QgsMapCanvas* window = options.refresh_window;
    const bool restore_render = window != nullptr && window->renderFlag();
    if (window != nullptr) {
        window->setRenderFlag(false);
    }

    std::set<QString> already_seen;
    for (const MirrorLayerSpec& layer : snapshot.layers) {
        if (duplicate_ids.count(layer.id) && already_seen.count(layer.id)) {
            continue;  // duplicate id: first occurrence already published
        }
        if (layer.layer_type != QLatin1String("vector")) {
            // scalar_grid / raster_source / unknown types: the scalar
            // data pipeline (GDAL data mirror + pseudocolor renderer) is
            // not part of this slice — an honest failure entry, never a
            // silent drop (Python parity when its pipeline is missing).
            result.failures.append(QStringLiteral(
                "layer %1: %2 mirror unavailable in native port "
                "(scalar/raster pipeline deferred); layer not mirrored")
                                       .arg(layer.id, layer.layer_type));
            sink(layer.id, QStringLiteral("raster/scalar pipeline unavailable"));
            continue;
        }

        const QString doc_id = layer.id;
        const QString geom = geom_keyword(layer);
        const QString crs = qgis_crs_for_layer(layer, snapshot, sink);

        // Style resolution (Python order): qgis_style.renderer_xml /
        // labeling_xml win; legacy style dict only survives when no
        // qgis payload is present.
        const QVariantMap qgis_style =
            layer.style.value(QStringLiteral("qgis_style")).toMap();
        QString renderer_xml =
            qgis_style.value(QStringLiteral("renderer_xml")).toString();
        const QString labeling_xml =
            qgis_style.value(QStringLiteral("labeling_xml")).toString();
        QVariantMap legacy_style;
        const bool has_qgis =
            !renderer_xml.trimmed().isEmpty() ||
            !labeling_xml.trimmed().isEmpty();
        if (!has_qgis) {
            for (auto it = layer.style.constBegin();
                 it != layer.style.constEnd(); ++it) {
                if (it.key() != QLatin1String("qgis_style")) {
                    legacy_style.insert(it.key(), it.value());
                }
            }
        }
        // fields_json: caller-supplied schema (spec resolution lives in
        // the mapping workspace — outside this slice; a declared role
        // without a schema is a diagnosable gap, not a silent legacy).
        QString fields_json =
            layer.metadata.value(QStringLiteral("fields_json")).toString();
        const QString role =
            layer.metadata.value(QStringLiteral("role")).toString();
        if (fields_json.isEmpty() && !role.isEmpty()) {
            sink(doc_id,
                 QStringLiteral(
                     "role '%1' has no resolved GeologicalLayerSpec — "
                     "layer published un-schematized")
                     .arg(role));
        }

        // Ledger no-op gate (v7 §9 tokens).
        MirrorLedger::Tokens live;
        live.data_revision = layer.data_revision;
        live.style_sig =
            style_signature(renderer_xml, labeling_xml, legacy_style);
        live.visible = layer.visible;
        live.opacity = layer.opacity;
        live.geom_kind = geom.toStdString();
        live.name = (layer.name.isEmpty() ? layer.id : layer.name).toStdString();
        live.min_scale = layer.min_scale;
        live.max_scale = layer.max_scale;
        live.fields_json = fields_json.toStdString();
        live.crs = crs.toStdString();

        const bool ledger_active = layer.data_revision != 0;
        const MirrorLedger::Tokens* entry =
            ledger_active ? ledger.entry(doc_id) : nullptr;
        QgsMapLayer* existing = find_mirror_layer(project, doc_id);
        if (entry != nullptr && (existing == nullptr || !existing->isValid())) {
            // Ledger self-heal: the entry claims published but the mirror
            // is gone/invalid — a no-op would freeze "missing data" into
            // permanent invisibility. Invalidate and republish.
            ledger.erase(doc_id);
            entry = nullptr;
            sink(doc_id, QStringLiteral(
                             "ledger entry invalidated: mirror layer "
                             "missing/invalid"));
        }

        if (options.edit_frozen_ids.count(doc_id)) {
            // M0 §3 stop-publish window: data re-push short-circuits —
            // the mirror IS the edit buffer; republishing would destroy
            // it. The ledger stays frozen (changes pending until the
            // window closes).
            sink(doc_id, QStringLiteral("publish:edit-window (data frozen)"));
            result.seen_doc_ids.append(doc_id);
            if (existing != nullptr) {
                result.mirrored_qgis_ids.append(existing->id());
            }
            already_seen.insert(doc_id);
            continue;
        }

        if (entry != nullptr && *entry == live) {
            // no-op publish: tokens unchanged → ship nothing.
            sink(doc_id, QStringLiteral("publish:no-op"));
            result.seen_doc_ids.append(doc_id);
            if (existing != nullptr) {
                result.mirrored_qgis_ids.append(existing->id());
            }
            already_seen.insert(doc_id);
            continue;
        }

        // --- upsert -----------------------------------------------------
        QgsVectorLayer* vl = qobject_cast<QgsVectorLayer*>(existing);
        bool created = false;
        if (vl == nullptr) {
            QString uri = geom;
            if (!crs.isEmpty()) {
                uri += QStringLiteral("?crs=%1").arg(crs);
            }
            vl = new QgsVectorLayer(
                uri, layer.name.isEmpty() ? layer.id : layer.name,
                QStringLiteral("memory"));
            if (!vl->isValid()) {
                result.failures.append(
                    QStringLiteral("layer %1: memory provider rejected uri")
                        .arg(doc_id));
                sink(doc_id, QStringLiteral("memory layer creation failed"));
                delete vl;
                continue;
            }
            vl->setCustomProperty(QString::fromLatin1(kDocIdProperty),
                                  doc_id);
            created = true;
        }

        // Schema + data re-push (full resend — the Python delta channel
        // is a ship optimization with identical visible semantics).
        bool schema_ok = true;
        QgsFields fields;
        bool has_fid_field = false;
        if (!fields_json.isEmpty()) {
            fields = fields_from_json(fields_json, &schema_ok);
            if (!schema_ok) {
                sink(doc_id, QStringLiteral("fields_json rejected — "
                                            "falling back to property schema"));
                fields = fields_from_features(layer.features, &has_fid_field);
            } else {
                has_fid_field = fields.indexOf(
                                    QString::fromLatin1(kPwbFidField)) >= 0;
            }
        } else {
            fields = fields_from_features(layer.features, &has_fid_field);
        }
        if (!has_fid_field) {
            fields.append(QgsField(QString::fromLatin1(kPwbFidField),
                                   QVariant::String));
        }

        {
            // Rebuild attributes+features. For an existing memory layer
            // the honest full-resend is truncate + re-add; fields that
            // changed shape get rebuilt by deleting the layer (simplest
            // correct path — the Python bridge rebuilds on schema drift
            // too).
            bool rebuild = created;
            if (!rebuild) {
                const QgsFields old = vl->fields();
                if (old.count() != fields.count()) {
                    rebuild = true;
                } else {
                    for (int i = 0; i < old.count(); ++i) {
                        if (old.at(i).name() != fields.at(i).name()) {
                            rebuild = true;
                            break;
                        }
                    }
                }
            }
            if (rebuild && !created) {
                // Field schema drift → recreate the mirror layer (keeps
                // the doc_id binding + tree position via re-insert).
                project.removeMapLayer(vl->id());
                QString uri = geom;
                if (!crs.isEmpty()) {
                    uri += QStringLiteral("?crs=%1").arg(crs);
                }
                vl = new QgsVectorLayer(
                    uri, layer.name.isEmpty() ? layer.id : layer.name,
                    QStringLiteral("memory"));
                if (!vl->isValid()) {
                    result.failures.append(QStringLiteral(
                        "layer %1: memory provider rejected uri").arg(doc_id));
                    delete vl;
                    already_seen.insert(doc_id);
                    continue;
                }
                vl->setCustomProperty(QString::fromLatin1(kDocIdProperty),
                                      doc_id);
                created = true;
            }
            if (created) {
                vl->dataProvider()->addAttributes(fields.toList());
                vl->updateFields();
            } else {
                // Same schema: truncate rows only.
                vl->dataProvider()->truncate();
            }
            const QString feature_error = push_features(vl, layer.features);
            if (!feature_error.isEmpty()) {
                result.failures.append(
                    QStringLiteral("layer %1: %2").arg(doc_id, feature_error));
                sink(doc_id, feature_error);
                if (created) delete vl;
                already_seen.insert(doc_id);
                continue;
            }
        }

        if (created) {
            project.addMapLayer(vl);
        }

        // Presentation tokens (cheap setters — Python pushes them through
        // the same upsert; visibility lives on the tree node).
        vl->setName(layer.name.isEmpty() ? layer.id : layer.name);
        vl->setOpacity(layer.opacity);
        if (layer.min_scale > 0.0 || layer.max_scale > 0.0) {
            vl->setScaleBasedVisibility(true);
            vl->setMinimumScale(layer.max_scale > 0.0 ? layer.max_scale
                                                      : layer.min_scale);
            vl->setMaximumScale(layer.min_scale > 0.0 ? layer.min_scale
                                                      : layer.max_scale);
        } else {
            vl->setScaleBasedVisibility(false);
        }
        const QString renderer_error = apply_renderer_xml(vl, renderer_xml);
        if (!renderer_error.isEmpty()) {
            sink(doc_id, renderer_error);
        }
        const QString labeling_error = apply_labeling_xml(vl, labeling_xml);
        if (!labeling_error.isEmpty()) {
            sink(doc_id, labeling_error);
        }
        if (QgsLayerTreeGroup* root = project.layerTreeRoot()) {
            if (QgsLayerTreeLayer* node = root->findLayer(vl->id())) {
                node->setItemVisibilityChecked(layer.visible);
            }
        }

        if (ledger_active) {
            ledger.store(doc_id, vl->id(), live);
        }
        result.seen_doc_ids.append(doc_id);
        result.mirrored_qgis_ids.append(vl->id());
        already_seen.insert(doc_id);
    }

    // Removals: mirror layers whose doc_id vanished from the snapshot.
    QStringList remove_ids;
    const auto project_layers = project.mapLayers();
    for (auto it = project_layers.constBegin();
         it != project_layers.constEnd(); ++it) {
        QgsMapLayer* layer = it.value();
        const QString doc_id =
            layer->customProperty(QString::fromLatin1(kDocIdProperty))
                .toString();
        if (!doc_id.isEmpty() && !already_seen.count(doc_id)) {
            remove_ids.append(layer->id());
            ledger.erase(doc_id);
        }
    }
    if (!remove_ids.isEmpty()) {
        project.removeMapLayers(remove_ids);
    }

    // Flat root order (groups=False): the snapshot layer order becomes
    // the root's top-to-bottom order. Nodes are taken and re-inserted
    // (identity preserved — checked state/custom props survive).
    if (!options.groups) {
        if (QgsLayerTreeGroup* root = project.layerTreeRoot()) {
            int position = 0;
            for (const MirrorLayerSpec& layer : snapshot.layers) {
                QgsMapLayer* ml = find_mirror_layer(project, layer.id);
                if (ml == nullptr) continue;
                QgsLayerTreeLayer* node = root->findLayer(ml->id());
                if (node == nullptr) continue;
                const int current = root->children().indexOf(node);
                if (current != position) {
                    QgsLayerTreeNode* taken = node->clone();
                    root->removeChildNode(node);
                    root->insertChildNode(position, taken);
                }
                ++position;
            }
        }
    }

    if (restore_render) {
        window->setRenderFlag(true);
        window->refresh();
    }
    return result;
}

}  // namespace pwb::ui_widgets::qgis
