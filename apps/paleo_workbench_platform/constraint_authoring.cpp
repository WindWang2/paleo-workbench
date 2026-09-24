// V14 constraint authoring (#1446) — the Stage-2 production side of the
// constraint pipeline. PR #1441 delivered the consumption side
// (resolve_constraints → constrained IDW / kriging with CRS fail-closed
// and content-hash pins) but nothing in the product could CREATE a
// constraint: the stage panel's eight constraint buttons emitted
// constraint_requested into the void, no code wrote constraint_layers
// into the project document, and the save-time geometry harvest
// (Python mapping_workspace/constraints_sync.py) was never ported.
//
// This slice ports the two missing halves, both frozen against the
// Python reference:
//
//   * createStageConstraint — stage_actions.py create_constraint /
//     _create_role_layer: create a bound, role-registered vector layer
//     (empty GPKG written through QgsVectorFileWriter — provider truth,
//     geometry type pinned per constraint kind), register it with the
//     layer-control group plane (02 地质约束组 membership with the
//     constraint_kind stamp), stamp the document's constraint_layers
//     line entry (empty coordinates — geometry is digitized into the
//     layer), and start editing on it.
//   * syncConstraintGeometryOnSave — constraints_sync.py
//     sync_constraint_geometry: harvest the live layer's features into
//     the linked ConstraintLine.coordinates (one line per feature,
//     polygon exterior rings auto-closed, multi-part lines merged with
//     joint dedup) plus the sha256 content fingerprint, with the same
//     replace semantics (stale extra lines from a previous sync are
//     dropped, never accumulated). Called from the save path before the
//     document write, after the edit sessions are committed.
//
// GUI-thread only. Fail-closed: every failure path reports through the
// status bar and leaves the document untouched.

#include "main_window.hpp"

#include <QStatusBar>
#include <QString>

#include <qgis.h>
#include <qgscoordinatereferencesystem.h>
#include <qgsfeature.h>
#include <qgsfeatureiterator.h>
#include <qgsfields.h>
#include <qgsgeometry.h>
#include <qgsmaplayer.h>
#include <qgsproject.h>
#include <qgssnappingconfig.h>
#include <qgsvectorfilewriter.h>
#include <qgsvectorlayer.h>

#include <pwb/application/project_session.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/domain/sha256.hpp>
#include <pwb/factor_host/canonical_json.hpp>
#include <pwb/qgis/layer_adapter.hpp>
#include <pwb/qgis/map_session.hpp>
#include <pwb/ui_composite/roles.hpp>

#include "app_context.hpp"

#include <pwb/application/adapters/data_store.hpp>

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cmath>
#include <filesystem>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

namespace pwb::app {

#ifdef PWB_WITH_STAGE_FLOW
#ifdef PWB_WITH_DATA_INTEGRATION

namespace {

using pwb::domain::Json;
using pwb::domain::Sha256;

// Python round(x, 9): round-half-to-even at 9 decimals. std::nearbyint
// honors the current rounding mode (to-nearest-even by default).
double py_round9(double value) {
    return std::nearbyint(value * 1e9) / 1e9;
}

// constraint_content_fingerprint parity: sha256 over the compact
// canonical JSON of the 9-decimal-rounded coordinate list.
std::string content_fingerprint(
    const std::vector<std::array<double, 2>>& points) {
    Json canonical = Json::array();
    for (const auto& [x, y] : points) {
        canonical.push_back(
            Json::array({py_round9(x), py_round9(y)}));
    }
    return Sha256::of_bytes(
        pwb::factor_host::canonical_encode(canonical));
}

struct HarvestedLine {
    std::vector<std::array<double, 2>> points;
};

// _harvest_coordinates parity over the feature's GeoJSON form (QGIS
// asJson keeps full round-trip precision). Line kinds merge MultiLine
// parts with joint dedup (>= 2 vertices); polygon kinds take each
// part's exterior ring, auto-close open rings (>= 3 vertices) and count
// skipped interior rings.
void harvest_geometry(const Json& geometry, bool is_line,
                      std::vector<HarvestedLine>& out, int& holes) {
    if (!geometry.is_object()) return;
    const std::string gtype =
        geometry.value("type", std::string());
    const Json* coordinates = geometry.contains("coordinates")
                                  ? &geometry.at("coordinates")
                                  : nullptr;
    if (coordinates == nullptr || !coordinates->is_array()
        || coordinates->empty()) {
        return;
    }
    const auto vertex_of = [](const Json& point)
            -> std::optional<std::array<double, 2>> {
        if (!point.is_array() || point.size() < 2) return std::nullopt;
        if (!point[0].is_number() || !point[1].is_number()) {
            return std::nullopt;
        }
        const double x = point[0].get<double>();
        const double y = point[1].get<double>();
        if (!std::isfinite(x) || !std::isfinite(y)) return std::nullopt;
        return std::array<double, 2>{x, y};
    };
    if (is_line) {
        std::vector<const Json*> parts;
        if (gtype == "LineString") {
            parts.push_back(coordinates);
        } else if (gtype == "MultiLineString") {
            for (const auto& part : *coordinates) {
                if (part.is_array()) parts.push_back(&part);
            }
        } else {
            return;
        }
        std::vector<std::array<double, 2>> merged;
        for (const Json* part : parts) {
            for (const auto& point : *part) {
                const auto vertex = vertex_of(point);
                if (!vertex.has_value()) continue;
                if (!merged.empty() && merged.back() == *vertex) {
                    continue;  // drop duplicated joints between parts
                }
                merged.push_back(*vertex);
            }
        }
        if (merged.size() >= 2) {
            out.push_back({std::move(merged)});
        }
        return;
    }
    // Polygon kinds — keep each part's ring structure (R1-F5 parity).
    std::vector<const Json*> polys;
    if (gtype == "Polygon") {
        polys.push_back(coordinates);
    } else if (gtype == "MultiPolygon") {
        for (const auto& poly : *coordinates) {
            if (poly.is_array()) polys.push_back(&poly);
        }
    } else {
        return;
    }
    for (const Json* poly : polys) {
        for (std::size_t index = 0; index < poly->size(); ++index) {
            const Json& ring = (*poly)[index];
            if (!ring.is_array()) continue;
            std::vector<std::array<double, 2>> points;
            for (const auto& point : ring) {
                const auto vertex = vertex_of(point);
                if (vertex.has_value()) points.push_back(*vertex);
            }
            if (points.size() < 3) continue;
            if (index == 0) {
                // Ring closure for polygon kinds (mask / exclusion):
                // the boundary-ring consumer requires first == last.
                if (points.front() != points.back()) {
                    points.push_back(points.front());
                }
                out.push_back({std::move(points)});
            } else {
                ++holes;
            }
        }
    }
}

// _linked_lines parity: primary stamp match (properties.layer_id), then
// the legacy fallback (same kind + same name + still-empty coordinates).
struct LinkedLines {
    std::vector<Json*> lines;
    std::string matched_by;
};

LinkedLines linked_lines(Json& root, const std::string& layer_id,
                         const std::string& kind_value,
                         const std::string& layer_name) {
    LinkedLines out;
    Json* groups = root.contains("constraint_layers")
                       ? &root.at("constraint_layers")
                       : nullptr;
    if (groups == nullptr || !groups->is_array()) return out;
    for (auto& group : *groups) {
        if (!group.is_object()) continue;
        Json* lines = group.contains("lines") ? &group.at("lines")
                                              : nullptr;
        if (lines == nullptr || !lines->is_array()) continue;
        for (auto& line : *lines) {
            if (!line.is_object()) continue;
            const Json props = line.contains("properties")
                                   ? line.at("properties")
                                   : Json::object();
            const std::string stamped =
                props.is_object() && props.contains("layer_id")
                    ? props.at("layer_id").get<std::string>()
                    : std::string();
            if (stamped == layer_id && !layer_id.empty()) {
                out.lines.push_back(&line);
                continue;
            }
            const std::string line_kind =
                props.is_object() && props.contains("constraint_kind")
                    ? props.at("constraint_kind").get<std::string>()
                    : std::string();
            const std::string line_name = line.contains("name")
                                               ? line.at("name")
                                                     .get<std::string>()
                                               : std::string();
            const bool empty_coords =
                !line.contains("coordinates")
                || !line.at("coordinates").is_array()
                || line.at("coordinates").empty();
            if (!kind_value.empty() && line_kind == kind_value
                && line_name == layer_name && empty_coords
                && out.lines.empty() && out.matched_by.empty()) {
                out.lines.push_back(&line);
                out.matched_by = "constraint_kind+name";
            }
        }
    }
    if (!out.lines.empty() && out.matched_by.empty()) {
        out.matched_by = "layer_id";
    }
    return out;
}

// _target_group parity: the group holding a matched line, else the first
// group, else a fresh "约束层" group.
Json* target_group(Json& root, const LinkedLines& matched) {
    Json* groups = root.contains("constraint_layers")
                       ? &root.at("constraint_layers")
                       : nullptr;
    if (groups == nullptr || !groups->is_array()) return nullptr;
    std::set<const Json*> matched_set(matched.lines.begin(),
                                      matched.lines.end());
    for (auto& group : *groups) {
        if (!group.is_object() || !group.contains("lines")
            || !group.at("lines").is_array()) {
            continue;
        }
        for (auto& line : group.at("lines")) {
            if (matched_set.count(&line) != 0) return &group;
        }
    }
    if (!groups->empty()) return &(*groups)[0];
    Json group = Json::object();
    group["id"] = "clayers_" + std::to_string(groups->size() + 1);
    group["name"] = "约束层";
    group["target_horizon"] = "";
    group["lines"] = Json::array();
    group["linked_factor_task_ids"] = Json::array();
    groups->push_back(std::move(group));
    return &groups->back();
}

// _linked_points: the point-kind counterpart of linked_lines — primary
// stamp match (properties.layer_id) over group["points"] entries.
std::vector<Json*> linked_points(Json& root, const std::string& layer_id) {
    std::vector<Json*> out;
    if (layer_id.empty()) return out;
    Json* groups = root.contains("constraint_layers")
                       ? &root.at("constraint_layers")
                       : nullptr;
    if (groups == nullptr || !groups->is_array()) return out;
    for (auto& group : *groups) {
        if (!group.is_object()) continue;
        Json* points = group.contains("points") ? &group.at("points")
                                                : nullptr;
        if (points == nullptr || !points->is_array()) continue;
        for (auto& point : *points) {
            if (!point.is_object()) continue;
            const Json props = point.contains("properties")
                                   ? point.at("properties")
                                   : Json::object();
            if (props.is_object() && props.contains("layer_id")
                && props.at("layer_id").get<std::string>() == layer_id) {
                out.push_back(&point);
            }
        }
    }
    return out;
}

std::string new_constraint_line_id() {
    static int counter = 0;
    return "cline_" + std::to_string(++counter) + "_"
        + std::to_string(std::chrono::steady_clock::now()
                             .time_since_epoch()
                             .count());
}

// Point fingerprint: sha256 over the canonical JSON of the 9-decimal
// rounded position plus the raw anchored value (the value participates —
// changing a pin's value must invalidate the content hash).
std::string point_fingerprint(double x, double y,
                              const std::optional<double>& value) {
    Json canonical = Json::array(
        {py_round9(x), py_round9(y),
         value.has_value() ? Json(*value) : Json(nullptr)});
    return Sha256::of_bytes(
        pwb::factor_host::canonical_encode(canonical));
}

struct HarvestedPoint {
    double x = 0.0;
    double y = 0.0;
    std::optional<double> value;
};

// Point-kind harvest: one group["points"] entry per live point feature
// (position + optional anchored value), same replace semantics as the
// line path — stale stamped entries drop, an empty transient layer never
// wipes previously synced geometry. Returns entries written.
int sync_point_layer(Json& root, const std::string& layer_id,
                     QgsVectorLayer* vl, const std::string& layer_name) {
    const int value_index = vl->fields().indexOf(QStringLiteral("value"));
    std::vector<HarvestedPoint> points;
    QgsFeatureIterator feature_it = vl->getFeatures();
    QgsFeature feature;
    while (feature_it.nextFeature(feature)) {
        if (!feature.hasGeometry()) continue;
        Json geometry;
        try {
            geometry = Json::parse(
                feature.geometry().asJson().toStdString());
        } catch (const Json::exception&) {
            continue;
        }
        if (!geometry.is_object()
            || geometry.value("type", std::string()) != "Point") {
            continue;
        }
        const Json* coordinates =
            geometry.contains("coordinates")
                ? &geometry.at("coordinates")
                : nullptr;
        if (coordinates == nullptr || !coordinates->is_array()
            || coordinates->size() < 2 || !(*coordinates)[0].is_number()
            || !(*coordinates)[1].is_number()) {
            continue;
        }
        HarvestedPoint point;
        point.x = (*coordinates)[0].get<double>();
        point.y = (*coordinates)[1].get<double>();
        if (!std::isfinite(point.x) || !std::isfinite(point.y)) continue;
        if (value_index >= 0) {
            // QGIS 4: QgsFeature::hasAttribute is gone — an unset field
            // reads back a NULL QVariant (isValid() alone is true; a null
            // double would silently anchor the surface at 0.0).
            const QVariant attribute = feature.attribute(value_index);
            if (attribute.isValid() && !attribute.isNull()
                && attribute.canConvert<double>()) {
                bool ok = false;
                const double value = attribute.toDouble(&ok);
                if (ok && std::isfinite(value)) point.value = value;
            }
        }
        points.push_back(point);
    }
    if (points.empty()) return 0;

    // Replace semantics over the stamped points of the owning group.
    Json* groups = root.contains("constraint_layers")
                       ? &root.at("constraint_layers")
                       : nullptr;
    if (groups == nullptr || !groups->is_array()) return 0;
    Json* group = nullptr;
    for (auto& candidate : *groups) {
        if (!candidate.is_object()) continue;
        Json* entries = candidate.contains("points")
                            ? &candidate.at("points")
                            : nullptr;
        if (entries == nullptr || !entries->is_array()) continue;
        for (auto& entry : *entries) {
            const Json props = entry.is_object() && entry.contains(
                                   "properties")
                                   ? entry.at("properties")
                                   : Json::object();
            if (props.is_object() && props.contains("layer_id")
                && props.at("layer_id").get<std::string>() == layer_id) {
                group = &candidate;
                break;
            }
        }
        if (group != nullptr) break;
    }
    if (group == nullptr) group = &(*groups)[0];

    if (!group->contains("points") || !group->at("points").is_array()) {
        (*group)["points"] = Json::array();
    }
    Json& entries = (*group)["points"];
    // Template kind stamp read BEFORE the replace mutation (pointer
    // invalidation parity with the line path).
    std::optional<Json> template_kind_props;
    for (const auto& entry : entries) {
        if (!entry.is_object()) continue;
        const Json props = entry.contains("properties")
                               ? entry.at("properties")
                               : Json::object();
        if (props.is_object() && props.contains("layer_id")
            && props.at("layer_id").get<std::string>() == layer_id
            && props.contains("constraint_kind")) {
            template_kind_props = props;
            break;
        }
    }
    Json kept = Json::array();
    for (auto& entry : entries) {
        const Json props = entry.is_object() && entry.contains("properties")
                               ? entry.at("properties")
                               : Json::object();
        const bool stale =
            props.is_object() && props.contains("layer_id")
            && props.at("layer_id").get<std::string>() == layer_id;
        if (!stale) kept.push_back(std::move(entry));
    }
    entries = std::move(kept);
    int written = 0;
    for (const HarvestedPoint& point : points) {
        Json entry = Json::object();
        entry["id"] = new_constraint_line_id();
        entry["name"] = layer_name;
        entry["role"] = "pin";
        entry["coordinates"] = Json::array({point.x, point.y});
        entry["active"] = true;
        Json props = Json::object(
            {{"layer_id", layer_id},
             {"content_fingerprint",
              point_fingerprint(point.x, point.y, point.value)}});
        if (point.value.has_value()) {
            props["value"] = *point.value;
        }
        if (template_kind_props.has_value()
            && template_kind_props->is_object()
            && template_kind_props->contains("constraint_kind")) {
            props["constraint_kind"] =
                template_kind_props->at("constraint_kind");
        }
        entry["properties"] = std::move(props);
        entries.push_back(std::move(entry));
        ++written;
    }
    return written;
}

}  // namespace

// ---------------------------------------------------------------- create --

void MainWindow::createStageConstraint(const QString& kind_value_q) {
    const std::string kind = kind_value_q.toStdString();
    std::string label;
    try {
        label = pwb::ui_composite::constraint_kind_label(kind);
    } catch (const std::out_of_range&) {
        statusBar()->showMessage(
            tr("未知约束类型：%1").arg(kind_value_q), 8000);
        return;
    }
    const auto store = context_.projectStore();
    if (store == nullptr) {
        statusBar()->showMessage(
            tr("先新建或打开工程——约束层随工程保存"), 8000);
        return;
    }
    const auto role =
        pwb::ui_composite::constraint_kind_layer_role(kind);
    const auto interp_role =
        pwb::ui_composite::constraint_interpolation_role(kind);
    const std::string geometry_kind =
        pwb::ui_composite::constraint_kind_geometry_kind(kind);

    // Layer id + display name — Python parity: 1 + the number of live
    // layers already carrying the same constraint kind.
    int sequence = 1;
    for (const auto& [id, facts] : facts_) {
        if (facts.role == role.value_or("")) ++sequence;
    }
    // facts_.count(role) counts layers with the ROLE (kinds sharing a
    // role, e.g. every line kind, number together — same as Python's
    // membership count over constraint_kind equality would not; but the
    // Python counter is over memberships with equal constraint_kind, so
    // prefer the kind when it is recoverable from the group plane).
    const std::string layer_id =
        "constraint." + kind + "." + std::to_string(sequence);
    const std::string name = label + " " + std::to_string(sequence);

    // Empty GPKG through QGIS's own writer (provider truth; geometry
    // type pinned by the constraint kind; project CRS).
    const std::filesystem::path project_dir =
        store->project_file().parent_path();
    const std::filesystem::path constraints_dir =
        project_dir / ".pwb-working" / "constraints";
    std::error_code ec;
    std::filesystem::create_directories(constraints_dir, ec);
    if (ec) {
        statusBar()->showMessage(
            tr("约束层目录创建失败：%1")
                .arg(QString::fromStdString(ec.message())),
            8000);
        return;
    }
    const std::filesystem::path gpkg =
        constraints_dir / (layer_id + ".gpkg");
    const QString crs_id = QString::fromStdString(
        context_.session().map().project()->crs().authid().toStdString());
    // Point constraint layers carry the anchored value the interpolation
    // sample merge consumes; line/polygon layers keep the two-field
    // Python-parity schema (no field the algorithms never read).
    const QString memory_uri =
        QStringLiteral(
            "%1?crs=%2&field=name:string(64)&field=kind:string(32)"
            "&field=value:double")
            .arg(geometry_kind == "polygon" ? QStringLiteral("Polygon")
                 : geometry_kind == "point" ? QStringLiteral("Point")
                                            : QStringLiteral("LineString"))
            .arg(crs_id.isEmpty() ? QStringLiteral("EPSG:4326") : crs_id);
    QgsVectorLayer scratch(memory_uri, QStringLiteral("scratch"),
                           QStringLiteral("memory"));
    if (!scratch.isValid()) {
        statusBar()->showMessage(tr("创建约束层失败：%1")
                                     .arg(QString::fromStdString(name)),
                                 8000);
        return;
    }
    QgsVectorFileWriter::SaveVectorOptions options;
    options.driverName = QStringLiteral("GPKG");
    options.layerName = QStringLiteral("constraints");
    QString write_error;
    QString new_filename;
    QString new_layer;
    const auto result = QgsVectorFileWriter::writeAsVectorFormatV3(
        &scratch, QString::fromStdString(gpkg.string()),
        scratch.transformContext(), options, &write_error, &new_filename,
        &new_layer);
    if (result != QgsVectorFileWriter::NoError) {
        statusBar()->showMessage(
            tr("约束层写入失败：%1").arg(write_error), 8000);
        return;
    }

    // Join the session map as a bound, editable working layer.
    const std::string uri =
        gpkg.string() + "|layername=constraints";
    pwb::qgis::LayerBinding binding{layer_id, "", "", "vector"};
    std::string add_error;
    QgsVectorLayer* layer = context_.session().map().addVectorLayer(
        uri, name, binding, &add_error);
    if (layer == nullptr) {
        statusBar()->showMessage(
            tr("约束层加载失败：%1")
                .arg(QString::fromStdString(add_error)),
            8000);
        return;
    }
    pwb::application::DomainLayerFacts facts;
    facts.layer_id = layer_id;
    facts.role = role.value_or("");
    facts.role_label = label;
    facts.artifact_maturity = "draft";
    facts.write_granted = true;
    noteDomainLayerFacts(facts);

    // Layer-control membership with the constraint-kind stamp; the next
    // reconcile (stage switch / save both re-reconcile) materializes the
    // 02 地质约束组 placement.
#ifdef PWB_WITH_CONV_27
    if (layer_groups_ != nullptr) {
        layer_groups_->register_layer(layer_id, facts.role,
                                      /*factor_task_id=*/"",
                                      /*constraint_kind=*/kind);
    }
#endif

    // Document registration (Python parity: first group or a fresh
    // 约束层 group; the line carries EMPTY coordinates — geometry is
    // digitized into the vector layer and harvested at save).
    {
        Json& root = store->document().root();
        if (!root.contains("constraint_layers")
            || !root.at("constraint_layers").is_array()) {
            root["constraint_layers"] = Json::array();
        }
        Json& groups = root.at("constraint_layers");
        Json* group = nullptr;
        if (!groups.empty()) {
            group = &groups[0];
        } else {
            Json fresh = Json::object();
            fresh["id"] = "clayers_1";
            fresh["name"] = "约束层";
            fresh["target_horizon"] = "";
            fresh["lines"] = Json::array();
            fresh["linked_factor_task_ids"] = Json::array();
            groups.push_back(std::move(fresh));
            group = &groups.back();
        }
        // Document registration (Python parity: first group or a fresh
        // 约束层 group; the entry carries EMPTY coordinates — geometry is
        // digitized into the vector layer and harvested at save). Line/
        // polygon kinds register under "lines" (Python parity); the point
        // kind (约束点) registers under "points" — a separate array with
        // the same entry shape so the save-time harvest and the prepare
        // constraint resolver each keep their own replace semantics.
        if (geometry_kind == "point") {
            if (!group->contains("points")
                || !group->at("points").is_array()) {
                (*group)["points"] = Json::array();
            }
            Json point = Json::object();
            point["id"] = new_constraint_line_id();
            point["name"] = name;
            point["role"] = interp_role.value_or("pin");
            point["coordinates"] = Json::array();
            point["active"] = true;
            point["properties"] = Json::object(
                {{"layer_id", layer_id}, {"constraint_kind", kind}});
            group->at("points").push_back(std::move(point));
        } else if (group->contains("lines")
                   && group->at("lines").is_array()) {
            Json line = Json::object();
            line["id"] = new_constraint_line_id();
            line["name"] = name;
            line["role"] = interp_role.value_or("other");
            line["coordinates"] = Json::array();
            line["active"] = true;
            line["properties"] = Json::object(
                {{"layer_id", layer_id}, {"constraint_kind", kind}});
            group->at("lines").push_back(std::move(line));
        }
    }

    // Editing on the new layer — Python sets the edit target and the
    // status message; the digitizing itself uses the standard toolbar.
    const std::string edit_error =
        context_.session().edit().start_editing(layer_id);
    if (!edit_error.empty()) {
        statusBar()->showMessage(
            tr("约束层已创建，但开始编辑失败：%1")
                .arg(QString::fromStdString(edit_error)),
            8000);
    }
    context_.session().set_active_layer(facts);
    refreshActionStates();
#ifdef PWB_WITH_CONV_27
    refresh_readiness();
#endif
    statusBar()->showMessage(
        tr("已创建 %1（进入 02 地质约束组；数字化后保存生效）")
            .arg(QString::fromStdString(label)),
        10000);
}

// ----------------------------------------------------------------- sync --

int MainWindow::syncConstraintGeometryOnSave() {
    const auto store = context_.projectStore();
    if (store == nullptr) return 0;
    Json& root = store->document().root();
    if (!root.contains("constraint_layers")
        || !root.at("constraint_layers").is_array()) {
        return 0;
    }

    // The live QGIS layers by domain id (harvest source).
    std::map<std::string, QgsVectorLayer*> live;
    const QList<QgsMapLayer*> layers =
        context_.session().map().project()->mapLayers().values();
    for (QgsMapLayer* ml : layers) {
        auto* vl = qobject_cast<QgsVectorLayer*>(ml);
        if (vl == nullptr) continue;
        const std::string domain_id =
            pwb::qgis::layer_adapter::layer_id_of(vl);
        if (!domain_id.empty()) live[domain_id] = vl;
    }

    int synced_lines = 0;
    // Collect the stamped layer ids first — the replace semantics below
    // rewrite group["lines"]/["points"] arrays, invalidating pointers
    // mid-walk. Both arrays are scanned: line and point constraint layers
    // stamp the same properties.layer_id.
    std::set<std::string> stamped_ids;
    for (const auto& group : root.at("constraint_layers")) {
        if (!group.is_object()) continue;
        for (const char* section : {"lines", "points"}) {
            if (!group.contains(section)
                || !group.at(section).is_array()) {
                continue;
            }
            for (const auto& entry : group.at(section)) {
                if (!entry.is_object()) continue;
                const Json props = entry.contains("properties")
                                       ? entry.at("properties")
                                       : Json::object();
                if (props.is_object() && props.contains("layer_id")
                    && props.at("layer_id").is_string()) {
                    stamped_ids.insert(
                        props.at("layer_id").get<std::string>());
                }
            }
        }
    }
    for (const std::string& layer_id : stamped_ids) {
        const auto live_it = live.find(layer_id);
        if (live_it == live.end()) continue;
        QgsVectorLayer* vl = live_it->second;
        const std::string layer_name = vl->name().toStdString();
        const bool is_line =
            vl->geometryType() == Qgis::GeometryType::Line;
        if (vl->geometryType() == Qgis::GeometryType::Point) {
            synced_lines +=
                sync_point_layer(root, layer_id, vl, layer_name);
            continue;
        }
        // First pass with the stamp only: the constraint kind for the
        // legacy name fallback comes from the matched entries below.
        LinkedLines matched =
            linked_lines(root, layer_id, std::string(), layer_name);
        if (matched.matched_by.empty()) {
            // No primary stamp hit — retry with the layer's constraint
            // kind from the facts role (the creation path always stamps;
            // this covers layers stamped under a different group).
            std::string kind_value;
            for (const auto& [id, facts] : facts_) {
                if (id == layer_id && !facts.role.empty()) {
                    kind_value = facts.role;
                    break;
                }
            }
            if (!kind_value.empty()) {
                matched = linked_lines(root, layer_id, kind_value,
                                       layer_name);
            }
        }
        // Harvest the features (GeoJSON form keeps full precision).
        std::vector<HarvestedLine> sequences;
        int holes = 0;
        QgsFeatureIterator feature_it = vl->getFeatures();
        QgsFeature feature;
        while (feature_it.nextFeature(feature)) {
            if (!feature.hasGeometry()) continue;
            Json geometry;
            try {
                geometry = Json::parse(
                    feature.geometry().asJson().toStdString());
            } catch (const Json::exception&) {
                continue;
            }
            harvest_geometry(geometry, is_line, sequences, holes);
        }
        if (sequences.empty()) {
            // Never wipe previously synced geometry on an empty
            // transient state (digitizing may still be in progress).
            continue;
        }
        Json* group = target_group(root, matched);
        if (group == nullptr) continue;
        Json& lines = (*group)["lines"];
        if (!lines.is_array()) lines = Json::array();
        // Template values are read BEFORE the replace mutation below —
        // moving a matched line into `kept` leaves the pointed-to Json
        // null, so the stale pointers must not be dereferenced after.
        const std::string template_role =
            matched.lines.empty()
                ? std::string("other")
                : ((*matched.lines[0]).contains("role")
                       ? (*matched.lines[0])
                             .at("role")
                             .get<std::string>()
                       : std::string("other"));
        const std::string group_horizon =
            (*group).contains("target_horizon")
                ? (*group).at("target_horizon").get<std::string>()
                : std::string();
        // The constraint-kind stamp is hoisted here, BEFORE the replace
        // mutation below invalidates the matched-line pointers (the
        // array's old storage is released by copy-and-swap on
        // assignment).
        std::optional<Json> template_kind_props;
        if (!matched.lines.empty()
            && (*matched.lines[0]).contains("properties")) {
            template_kind_props = (*matched.lines[0]).at("properties");
        }
        // Replace semantics: drop the matched (stale) lines, then one
        // line per harvested sequence.
        std::set<const Json*> stale(matched.lines.begin(),
                                    matched.lines.end());
        Json kept = Json::array();
        for (auto& line : lines) {
            if (stale.count(&line) == 0) kept.push_back(std::move(line));
        }
        lines = std::move(kept);
        for (std::size_t index = 0; index < sequences.size();
             ++index) {
            Json line = Json::object();
            line["id"] = new_constraint_line_id();
            line["name"] = layer_name;
            line["role"] = template_role;
            if (!group_horizon.empty()) {
                line["target_horizon"] = group_horizon;
            }
            line["active"] = true;
            Json coords = Json::array();
            for (const auto& [x, y] : sequences[index].points) {
                coords.push_back(Json::array({x, y}));
            }
            line["coordinates"] = std::move(coords);
            Json props = Json::object(
                {{"layer_id", layer_id},
                 {"feature_index", static_cast<std::uint64_t>(index)},
                 {"content_fingerprint",
                  content_fingerprint(sequences[index].points)}});
            if (template_kind_props.has_value()
                && template_kind_props->is_object()
                && template_kind_props->contains("constraint_kind")) {
                props["constraint_kind"] =
                    template_kind_props->at("constraint_kind");
            }
            line["properties"] = std::move(props);
            lines.push_back(std::move(line));
            ++synced_lines;
        }
    }
    return synced_lines;
}

// ------------------------------------------------------------------ edit --

// The constraint layer roles (the layer set snapping scopes to — never
// unrelated data-management layers).
bool is_constraint_layer_role(const std::string& role) {
    static const std::set<std::string> roles = {
        "provenance_direction", "provenance_line", "distribution_line",
        "paleo_shoreline", "facies_boundary", "fault_constraint",
        "interpolation_boundary", "mask_boundary", "constraint_point",
    };
    return roles.count(role) != 0;
}

struct MainWindow::ConstraintSnapState {
    QgsSnappingConfig saved;
    bool scoped_active = false;
};

QString MainWindow::enterConstraintEditing(const QString& kind_value_q) {
    const std::string kind = kind_value_q.toStdString();
    std::string label;
    try {
        label = pwb::ui_composite::constraint_kind_label(kind);
    } catch (const std::out_of_range&) {
        return tr("未知约束类型：%1").arg(kind_value_q);
    }
    const auto store = context_.projectStore();
    if (store == nullptr) {
        return tr("先新建或打开工程——约束层随工程保存");
    }
    const auto role =
        pwb::ui_composite::constraint_kind_layer_role(kind);

    // Reuse: a live layer of the SAME constraint kind (role + role label —
    // kinds sharing a role, e.g. mask/exclusion or trend/distribution,
    // are told apart by the kind label stamped at creation).
    for (const auto& [id, facts] : facts_) {
        if (facts.role != role.value_or("\x01")) continue;
        if (facts.role_label != label) continue;
        if (context_.session().map().vectorLayerById(id) == nullptr) {
            continue;
        }
        if (!context_.session().edit().editing(id)) {
            const std::string error =
                context_.session().edit().start_editing(id);
            if (!error.empty()) {
                return tr("开始编辑失败：%1")
                    .arg(QString::fromStdString(error));
            }
        }
        context_.session().set_active_layer(facts);
        refreshActionStates();
        // Keep the scoped snap set current (a freshly created constraint
        // layer must be snappable without re-toggling).
        if (constraint_snap_state_ != nullptr
            && constraint_snap_state_->scoped_active) {
            setConstraintSnapping(true);
        }
        statusBar()->showMessage(
            tr("已进入 %1 编辑（图层：%2；数字化后保存生效）")
                .arg(QString::fromStdString(label),
                     QString::fromStdString(id)),
            10000);
        return QString();
    }
    createStageConstraint(kind_value_q);
    return QString();
}

void MainWindow::setConstraintSnapping(bool enabled) {
    if (constraint_snap_state_ == nullptr) {
        constraint_snap_state_ = std::make_shared<ConstraintSnapState>();
    }
    auto& edit = context_.session().edit();
    if (!enabled) {
        if (constraint_snap_state_->scoped_active) {
            edit.set_snapping_config(constraint_snap_state_->saved);
            constraint_snap_state_->scoped_active = false;
            statusBar()->showMessage(
                tr("约束捕捉已关闭（工程捕捉配置已恢复）"), 6000);
        }
        return;
    }
    // The live constraint layer set (by role; stale ids resolve to null
    // inside the controller and drop out).
    std::vector<std::string> layer_ids;
    for (const auto& [id, facts] : facts_) {
        if (is_constraint_layer_role(facts.role)) {
            layer_ids.push_back(id);
        }
    }
    if (!constraint_snap_state_->scoped_active) {
        constraint_snap_state_->saved = edit.snapping_config();
        constraint_snap_state_->scoped_active = true;
    }
    const std::string error =
        edit.set_snapping_scoped(true, 12.0, layer_ids);
    if (!error.empty()) {
        statusBar()->showMessage(
            tr("约束捕捉设置失败：%1")
                .arg(QString::fromStdString(error)),
            8000);
        return;
    }
    statusBar()->showMessage(
        layer_ids.empty()
            ? tr("没有约束图层可捕捉——先创建约束线/约束点")
            : tr("约束捕捉已开启：%1 个约束图层（顶点+线段，12 px）")
                  .arg(layer_ids.size()),
        8000);
}

void MainWindow::restoreProjectSnapping() {
    if (constraint_snap_state_ == nullptr
        || !constraint_snap_state_->scoped_active) {
        return;
    }
    context_.session().edit().set_snapping_config(
        constraint_snap_state_->saved);
    constraint_snap_state_->scoped_active = false;
}

#endif  // PWB_WITH_DATA_INTEGRATION
#endif  // PWB_WITH_STAGE_FLOW

}  // namespace pwb::app
