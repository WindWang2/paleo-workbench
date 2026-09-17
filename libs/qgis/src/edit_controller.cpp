#include <pwb/qgis/edit_controller.hpp>

#include <QCryptographicHash>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>

#include <qgsfeature.h>
#include <qgsgeometry.h>
#include <qgsjsonutils.h>
#include <qgsproject.h>
#include <qgssnappingconfig.h>
#include <qgsvectorlayer.h>
#include <qgsvectorlayereditbuffer.h>
#include <qgsvectorfilewriter.h>

#include <pwb/qgis/map_session.hpp>

namespace pwb::qgis {
namespace {

std::string geometry_to_geojson(const QgsGeometry& geometry) {
    // Compact GeoJSON geometry via QGIS's own exporter (no parallel codec).
    const QString json = geometry.asJson();
    return json.toStdString();
}

std::string sha256_of_file(const std::filesystem::path& path) {
    QFile file(QString::fromStdWString(path.wstring()));
    if (!file.open(QIODevice::ReadOnly)) return std::string();
    QCryptographicHash hash(QCryptographicHash::Sha256);
    if (!hash.addData(&file)) return std::string();
    return QString::fromLatin1(hash.result().toHex()).toStdString();
}

}  // namespace

EditController::EditController(MapSession& session) : session_(session) {}

EditController::~EditController() {
    for (auto& [layer_id, capture] : captures_) {
        for (const QMetaObject::Connection& connection : capture.connections)
            QObject::disconnect(connection);
    }
}

QgsVectorLayer* EditController::editingLayerOrError(const std::string& layer_id,
                                                    std::string* error) const {
    QgsVectorLayer* layer = session_.vectorLayerById(layer_id);
    if (layer == nullptr) {
        if (error != nullptr) *error = "layer not found: " + layer_id;
        return nullptr;
    }
    if (captures_.find(layer_id) == captures_.end()) {
        if (error != nullptr) *error = "layer not in an edit session: " + layer_id;
        return nullptr;
    }
    return layer;
}

std::string EditController::start_editing(const std::string& layer_id) {
    QgsVectorLayer* layer = session_.vectorLayerById(layer_id);
    if (layer == nullptr) return "layer not found: " + layer_id;
    if (captures_.find(layer_id) != captures_.end()) return "";  // idempotent

    EditDeltaV1 delta;
    delta.source_layer_id = layer_id;
    Capture capture;
    capture.delta = delta;

    const QString q_layer_id = QString::fromStdString(layer_id);
    capture.connections.push_back(QObject::connect(
        layer, &QgsVectorLayer::committedFeaturesAdded, layer,
        [this, q_layer_id](const QString&, const QgsFeatureList& added) {
            Capture& slot = captures_[q_layer_id.toStdString()];
            for (const QgsFeature& feature : added) {
                slot.delta.added_feature_geojson.push_back(
                    geometry_to_geojson(feature.geometry()));
            }
        }));
    capture.connections.push_back(QObject::connect(
        layer, &QgsVectorLayer::committedFeaturesRemoved, layer,
        [this, q_layer_id](const QString&, const QgsFeatureIds& removed) {
            Capture& slot = captures_[q_layer_id.toStdString()];
            for (QgsFeatureId fid : removed)
                slot.delta.removed_host_ids.push_back(static_cast<long long>(fid));
        }));
    capture.connections.push_back(QObject::connect(
        layer, &QgsVectorLayer::committedGeometriesChanges, layer,
        [this, q_layer_id](const QString&, const QgsGeometryMap& changes) {
            Capture& slot = captures_[q_layer_id.toStdString()];
            for (auto it = changes.constBegin(); it != changes.constEnd(); ++it) {
                GeometryChangeV1 change;
                change.host_fid = static_cast<long long>(it.key());
                change.geojson = geometry_to_geojson(it.value());
                slot.delta.geometry_changes.push_back(std::move(change));
            }
        }));
    capture.connections.push_back(QObject::connect(
        layer, &QgsVectorLayer::committedAttributeValuesChanges, layer,
        [this, q_layer_id, layer](const QString&, const QgsChangedAttributesMap& changes) {
            Capture& slot = captures_[q_layer_id.toStdString()];
            for (auto fit = changes.constBegin(); fit != changes.constEnd(); ++fit) {
                AttributeChangeV1 change;
                change.host_fid = static_cast<long long>(fit.key());
                for (auto ait = fit.value().constBegin();
                     ait != fit.value().constEnd(); ++ait) {
                    // QgsAttributeMap keys are field indexes; EditDeltaV1
                    // speaks field NAMES (domain vocabulary).
                    const int field_index = ait.key();
                    const QString field_name = layer->fields().field(field_index).name();
                    change.attrs[field_name.toStdString()] =
                        ait.value().toString().toStdString();
                }
                slot.delta.attribute_changes.push_back(std::move(change));
            }
        }));

    if (!layer->startEditing()) {
        for (const QMetaObject::Connection& connection : capture.connections)
            QObject::disconnect(connection);
        return "failed to start editing on layer " + layer_id;
    }
    captures_[layer_id] = std::move(capture);
    return "";
}

std::string EditController::roll_back(const std::string& layer_id) {
    std::string error;
    QgsVectorLayer* layer = editingLayerOrError(layer_id, &error);
    if (layer == nullptr) return error;
    layer->rollBack(true);
    return "";
}

std::string EditController::move_vertex(const std::string& layer_id,
                                        long long fid, int vertex_index,
                                        double x, double y) {
    std::string error;
    QgsVectorLayer* layer = editingLayerOrError(layer_id, &error);
    if (layer == nullptr) return error;

    QgsFeature feature = layer->getFeature(static_cast<QgsFeatureId>(fid));
    if (!feature.isValid() || !feature.hasGeometry()) {
        return "feature " + std::to_string(fid) + " has no geometry";
    }
    QgsGeometry geometry = feature.geometry();
    if (!geometry.moveVertex(x, y, vertex_index)) {
        return "vertex " + std::to_string(vertex_index) + " not found on feature "
            + std::to_string(fid);
    }
    layer->beginEditCommand(QObject::tr("移动顶点"));
    if (!layer->changeGeometry(static_cast<QgsFeatureId>(fid), geometry)) {
        layer->destroyEditCommand();
        return "changeGeometry rejected for feature " + std::to_string(fid);
    }
    layer->endEditCommand();
    layer->triggerRepaint();
    return "";
}

std::string EditController::add_feature_geojson(const std::string& layer_id,
                                                const std::string& geojson_feature) {
    std::string error;
    QgsVectorLayer* layer = editingLayerOrError(layer_id, &error);
    if (layer == nullptr) return error;
    const QgsFeatureList parsed = QgsJsonUtils::stringToFeatureList(
        QString::fromStdString(geojson_feature), layer->fields(), nullptr);
    if (parsed.isEmpty()) return "invalid geojson feature";
    layer->beginEditCommand(QObject::tr("添加要素"));
    for (QgsFeature feature : parsed) {
        feature.setFields(layer->fields());
        if (!layer->addFeature(feature)) {
            layer->destroyEditCommand();
            return "addFeature rejected";
        }
    }
    layer->endEditCommand();
    layer->triggerRepaint();
    return "";
}

std::string EditController::undo(const std::string& layer_id) {
    std::string error;
    QgsVectorLayer* layer = editingLayerOrError(layer_id, &error);
    if (layer == nullptr) return error;
    layer->undoStack()->undo();
    layer->triggerRepaint();
    return "";
}

std::string EditController::redo(const std::string& layer_id) {
    std::string error;
    QgsVectorLayer* layer = editingLayerOrError(layer_id, &error);
    if (layer == nullptr) return error;
    layer->undoStack()->redo();
    layer->triggerRepaint();
    return "";
}

std::vector<std::string> EditController::validate_topology(
    const std::string& layer_id) {
    std::vector<std::string> errors;
    QgsVectorLayer* layer = session_.vectorLayerById(layer_id);
    if (layer == nullptr || layer->editBuffer() == nullptr) return errors;
    const QgsGeometryMap changed = layer->editBuffer()->changedGeometries();
    int index = 0;
    for (auto it = changed.constBegin(); it != changed.constEnd(); ++it, ++index) {
        QVector<QgsGeometry::Error> geometry_errors;
        it.value().validateGeometry(geometry_errors,
                                    Qgis::GeometryValidationEngine::Geos);
        for (const QgsGeometry::Error& err : geometry_errors) {
            errors.push_back("feature " + std::to_string(static_cast<long long>(it.key()))
                + ": " + err.what().toStdString());
        }
    }
    return errors;
}

std::string EditController::commit(const std::string& layer_id,
                                   const std::filesystem::path& staged_dir,
                                   StagedAsset* out_staged, EditDeltaV1* out_delta) {
    std::string error;
    QgsVectorLayer* layer = editingLayerOrError(layer_id, &error);
    if (layer == nullptr) return error;

    // Topology gate first: illegal geometries block the commit and keep the
    // session (the buffer survives for repair + retry).
    std::vector<std::string> topology_errors = validate_topology(layer_id);
    if (!topology_errors.empty()) {
        std::string joined;
        for (size_t i = 0; i < topology_errors.size(); ++i) {
            if (i > 0) joined += "; ";
            joined += topology_errors[i];
        }
        return "拓扑校验失败，阻止提交: " + joined;
    }

    const std::uint64_t base_revision = base_revisions_[layer_id];
    if (!layer->commitChanges(true)) {
        QStringList commit_errors = layer->commitErrors();
        commit_errors.removeAll(QString());
        if (commit_errors.isEmpty()) commit_errors << QStringLiteral("commit failed");
        return commit_errors.join(QStringLiteral("; ")).toStdString();
    }
    layer->triggerRepaint();

    Capture& capture = captures_[layer_id];
    if (out_delta != nullptr) {
        capture.delta.base_revision = base_revision;
        *out_delta = capture.delta;
    }

    // Staged asset: full-layer GeoJSON written into the staged dir; hash +
    // provenance recorded. B's CommitRequest consumes this path — we never
    // write catalog.sqlite from the platform side.
    std::error_code ec;
    std::filesystem::create_directories(staged_dir, ec);
    const std::filesystem::path out_path =
        staged_dir / (layer_id + ".geojson");
    QgsVectorFileWriter::SaveVectorOptions options;
    options.driverName = QStringLiteral("GeoJSON");
    options.fileEncoding = QStringLiteral("UTF-8");
    QString writer_error;
    QString new_filename;
    QString new_layer;
    const auto writer_result = QgsVectorFileWriter::writeAsVectorFormatV3(
        layer, QString::fromStdWString(out_path.wstring()),
        layer->transformContext(), options, &writer_error, &new_filename,
        &new_layer);
    if (writer_result != QgsVectorFileWriter::NoError) {
        for (const QMetaObject::Connection& connection : capture.connections)
            QObject::disconnect(connection);
        captures_.erase(layer_id);
        return "staged asset write failed: " + writer_error.toStdString();
    }
    if (out_staged != nullptr) {
        out_staged->geojson_path = out_path;
        out_staged->sha256 = sha256_of_file(out_path);
        out_staged->source_layer_id = layer_id;
        out_staged->base_revision = base_revision;
        out_staged->feature_count =
            static_cast<std::uint64_t>(layer->featureCount());
    }
    for (const QMetaObject::Connection& connection : capture.connections)
        QObject::disconnect(connection);
    captures_.erase(layer_id);
    return "";
}

std::string EditController::set_snapping(bool enabled, double tolerance_px) {
    QgsProject* project = session_.project();
    if (project == nullptr) return "no project";
    QgsSnappingConfig config = project->snappingConfig();
    config.setEnabled(enabled);
    config.setMode(Qgis::SnappingMode::AllLayers);
    config.setTypeFlag(Qgis::SnappingTypes(Qgis::SnappingType::Vertex)
                           | Qgis::SnappingType::Segment);
    config.setTolerance(tolerance_px);
    project->setSnappingConfig(config);
    return "";
}

bool EditController::editing(const std::string& layer_id) const {
    QgsVectorLayer* layer = session_.vectorLayerById(layer_id);
    return layer != nullptr && layer->editBuffer() != nullptr;
}

bool EditController::dirty(const std::string& layer_id) const {
    QgsVectorLayer* layer = session_.vectorLayerById(layer_id);
    return layer != nullptr && layer->isModified();
}

bool EditController::can_undo(const std::string& layer_id) const {
    QgsVectorLayer* layer = session_.vectorLayerById(layer_id);
    return layer != nullptr && layer->undoStack() != nullptr
        && layer->undoStack()->canUndo();
}

bool EditController::can_redo(const std::string& layer_id) const {
    QgsVectorLayer* layer = session_.vectorLayerById(layer_id);
    return layer != nullptr && layer->undoStack() != nullptr
        && layer->undoStack()->canRedo();
}

}  // namespace pwb::qgis
