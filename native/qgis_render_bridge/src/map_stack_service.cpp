// pybind11 (and therefore Python.h) must be included BEFORE any Qt/QGIS
// header: Qt redefines `slots`, which corrupts PyType_Spec in object.h.
#include <pybind11/pybind11.h>

#include "map_stack_service.hpp"

#include <algorithm>
#include <cmath>
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
#include <QString>
#include <QTemporaryDir>
#include <QTimer>
#include <QWidget>

#include <qgsapplication.h>
#include <qgsadvanceddigitizingdockwidget.h>
#include <qgscoordinatereferencesystem.h>
#include <qgscoordinatetransform.h>
#include <qgscompoundcurve.h>
#include <qgsfeature.h>
#include <qgsjsonutils.h>
#include <qgslayertree.h>
#include <qgslayertreelayer.h>
#include <qgslayertreemapcanvasbridge.h>
#include <qgslayertreemodel.h>
#include <qgslayertreeregistrybridge.h>
#include <qgslayertreeview.h>
#include <qgslayertreeviewdefaultactions.h>
#include <qgslayertreeviewindicator.h>
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
#include <qgsproject.h>
#include <qgsreadwritecontext.h>
#include <qgsrectangle.h>
#include <qgsrubberband.h>
#include <qgshighlight.h>
#include <qgssnappingconfig.h>
#include <qgssnappingutils.h>
#include <qgsvectorlayer.h>
#include <qgswkbtypes.h>
#include <qgsvectorlayerlabeling.h>
#include <qgsvectorlayerproperties.h>

#include "qgis_render_bridge.hpp"
#include "style_codec.hpp"
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

Qgis::SnappingTypes parseSnappingTypes(const QJsonArray& arr) {

    Qgis::SnappingTypes types;
    for (const QJsonValue& v : arr) {
        const QString s = v.toString();
        if (s == QLatin1String("vertex")) types |= Qgis::SnappingType::Vertex;
        else if (s == QLatin1String("segment")) types |= Qgis::SnappingType::Segment;
        else if (s == QLatin1String("midpoint")) types |= Qgis::SnappingType::MiddleOfSegment;
        else if (s == QLatin1String("centroid")) types |= Qgis::SnappingType::Centroid;
        else if (s == QLatin1String("area")) types |= Qgis::SnappingType::Area;
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

static QgsVectorLayer* findMirrorByDocId(QgsProject* project, const std::string& doc_id) {
    if (!project || doc_id.empty()) return nullptr;
    const QString key = QStringLiteral("pwb/doc_id");
    const QString target = QString::fromStdString(doc_id);
    for (auto* layer : project->mapLayers().values()) {
        if (layer->customProperty(key).toString() == target)
            return qobject_cast<QgsVectorLayer*>(layer);
    }
    return nullptr;
}

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
    bool empty() const { return visibility.isEmpty() && order.isEmpty() && renames.isEmpty(); }
  };
  std::unordered_map<std::uintptr_t, std::function<void(const std::string&)>> tree_change_callbacks;
  std::unordered_map<std::uintptr_t, std::vector<QMetaObject::Connection>> tree_change_connections;
  std::unordered_map<std::uintptr_t, TreeChangeBatch> tree_pending;
  std::unordered_set<std::uintptr_t> tree_flush_scheduled;
  // 重命名影子表：doc_id -> 最近一次已知图层名；程序化 setName 同步更新，
  // 回调侧据此区分真实重命名与样式刷新等无关 dataChanged。
  std::unordered_map<std::string, std::string> known_layer_names;
  // 可见性影子表：doc_id -> 最近一次已知勾选态；QGIS 用户勾选与刷新都发
  // 空 roles 的 dataChanged，只能靠影子比对区分。
  std::unordered_map<std::string, bool> known_layer_visibility;
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
  // 画布侧回调坟场（同上理由）：canvas destroyed 链上的 reapCanvasTables
  // 把含 py::function 的回调表 move 进这里，由 shutdown/dtor 统一销毁。
  std::vector<std::function<void(const std::string&, const std::string&)>>
      orphan_digitize_callbacks;
  std::vector<std::function<void(const std::string&, const std::string&)>>
      orphan_edit_pick_callbacks;
  std::vector<std::function<void(const std::string&, const std::string&)>>
      orphan_selection_callbacks;
  std::unordered_map<std::string, std::string> mirror_by_doc;
  // 镜像层 QgsFeatureId → 文档 feature_id（M3 Task 3）：memory provider 不落
  // 属性字段，__pwb_fid 由 upsert 时从 geojson 原文与 addFeatures 后的
  // fid 顺序配对重建；reconcile 每次 truncate+add 后整表替换。
  std::unordered_map<std::string, std::unordered_map<long long, std::string>>
      mirror_feature_fids;
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
    QgsMapLayer* layer = view_->currentLayer();
    if (layer == nullptr) {
      addCustom(menu, QStringLiteral("新建矢量图层"), "create_layer", nullptr);
      addCustom(menu, QStringLiteral("导入参考图层"), "import_reference", nullptr);
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
    }
    return menu;
  }

 private:
  QAction* addCustom(QMenu* menu, const QString& text, const char* key, QgsMapLayer* layer) {
    QAction* action = menu->addAction(text, menu, [this, key = std::string(key),
                                 layer = QPointer<QgsMapLayer>(layer)]() {
      if (!cb_) return;
      std::string doc;
      if (!layer.isNull()) {
        doc = layer->customProperty(QStringLiteral("pwb/doc_id")).toString().toStdString();
      }
      cb_(key, doc);
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
  impl_->tree_pending.clear();
  impl_->tree_flush_scheduled.clear();
  impl_->known_layer_names.clear();
  impl_->known_layer_visibility.clear();
  impl_->tree_views.clear();
  impl_->tree_models.clear();
  impl_->tree_canvas.clear();
  impl_->tree_menu_callbacks.clear();
  impl_->orphan_tree_callbacks.clear();
  impl_->orphan_tree_menu_callbacks.clear();
  impl_->orphan_digitize_callbacks.clear();
  impl_->orphan_edit_pick_callbacks.clear();
  impl_->orphan_selection_callbacks.clear();
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
             inTable(impl_->select_tools) || inTable(impl_->identify_tools);
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
  }
  impl_->vertex_tools.erase(canvas_addr);
  impl_->move_tools.erase(canvas_addr);
  impl_->select_tools.erase(canvas_addr);
  impl_->identify_tools.erase(canvas_addr);
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
  // double 重载不截断亚像素坐标（M2 移交项：int 截断会吃掉 <1px 精度）。
  const QgsPointXY p = canvasOrThrow(canvas)->getCoordinateTransform()->toMapCoordinates(x, y);
  return {p.x(), p.y()};
}

std::vector<double> QgisMapStack::mapToScreen(std::uintptr_t canvas, double x, double y) const {
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
                                            bool reference_snap) {
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
    QgsFeatureList features = QgsJsonUtils::stringToFeatureList(
        QString::fromStdString(geojson_feature_collection));
    if (existing->dataProvider()) {
      if (!existing->dataProvider()->truncate()) {
        throw std::runtime_error("mirror truncate failed for doc_id: " + doc_id);
      }
    }
    if (!features.isEmpty()) {
      if (!existing->dataProvider() || !existing->dataProvider()->addFeatures(features)) {
        throw std::runtime_error("mirror addFeatures failed for doc_id: " + doc_id);
      }
    }
    recordMirrorFeatureFids(impl_->mirror_feature_fids[doc_id], features, geoBytes);
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
  QgsFeatureList features = QgsJsonUtils::stringToFeatureList(
      QString::fromStdString(geojson_feature_collection));
  if (!features.isEmpty()) {
    if (!layer->dataProvider()->addFeatures(features)) {
      throw std::runtime_error("addFeatures failed for new mirror layer: " + name);
    }
    layer->updateExtents();
  }
  recordMirrorFeatureFids(impl_->mirror_feature_fids[doc_id], features, geoBytes);
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
  QgsVectorLayer* layer = nullptr;
  if (it != impl_->mirror_by_doc.end()) {
    QgsMapLayer* base = project()->mapLayer(QString::fromStdString(it->second));
    layer = qobject_cast<QgsVectorLayer*>(base);
    if (!layer) {
      layer = findMirrorByDocId(project(), doc_id);
    }
  } else {
    layer = findMirrorByDocId(project(), doc_id);
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
    QgsLayerTreeLayer* layerNode = qobject_cast<QgsLayerTreeLayer*>(child);
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
  QgsVectorLayer* layer = nullptr;
  auto it = impl_->mirror_by_doc.find(doc_id);
  if (it != impl_->mirror_by_doc.end()) {
    QgsMapLayer* base = project()->mapLayer(QString::fromStdString(it->second));
    layer = qobject_cast<QgsVectorLayer*>(base);
  }
  if (!layer) layer = findMirrorByDocId(project(), doc_id);
  if (!layer) throw std::invalid_argument("unknown doc_id: " + doc_id);
  QgsLayerTreeLayer* node = project()->layerTreeRoot()->findLayer(layer);
  if (!node) throw std::invalid_argument("layer node not found for doc_id: " + doc_id);
  return node->itemVisibilityChecked();
}

bool QgisMapStack::treeEchoSuppressed() const noexcept {
  return impl_ && impl_->suppress_tree_callbacks > 0;
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
  std::vector<std::string> order;
  QgsLayerTreeGroup* donorRoot = donor.layerTreeRoot();
  for (QgsLayerTreeNode* child : donorRoot->children()) {
    auto* layerNode = qobject_cast<QgsLayerTreeLayer*>(child);
    if (layerNode == nullptr) continue;
    QgsMapLayer* donorLayer = layerNode->layer();
    if (donorLayer == nullptr) continue;
    const QString doc = donorLayer->customProperty(QStringLiteral("pwb/doc_id")).toString();
    if (doc.isEmpty()) continue;
    const std::string doc_id = doc.toStdString();
    order.push_back(doc_id);
    QgsVectorLayer* live = findMirrorByDocId(project(), doc_id);
    if (live == nullptr) continue;
    auto* donorVl = qobject_cast<QgsVectorLayer*>(donorLayer);
    if (donorVl != nullptr) {
      if (donorVl->renderer() != nullptr) {
        live->setRenderer(donorVl->renderer()->clone());
      }
      live->setLabelsEnabled(donorVl->labelsEnabled());
      if (donorVl->labeling() != nullptr) {
        live->setLabeling(donorVl->labeling()->clone());
      } else {
        live->setLabeling(nullptr);
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
  if (!order.empty()) {
    setMirrorLayerOrder(order);
  }
  for (auto& kv : impl_->canvas_refs) {
    if (!kv.second.isNull()) syncCanvasLayers(kv.first);
  }
  return applied;
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
  return false;
}

void QgisMapStack::setMapTool(std::uintptr_t canvas_addr, const std::string& kind) {
  ensureNotStale(canvas_addr);
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  impl_->canvas_refs[canvas_addr] = canvas;
  if (impl_->display_mode) {
    if (kind != "pan" && kind != "zoomIn" && kind != "zoomOut") {
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
        onTreeDataChanged(addr, topLeft.row(),
                          allRoles || roles.contains(Qt::CheckStateRole),
                          allRoles || roles.contains(Qt::DisplayRole) || roles.contains(Qt::EditRole));
      }));
  conns.push_back(QObject::connect(
      model, &QgsLayerTreeModel::rowsMoved, view,
      [this, addr](const QModelIndex&, int, int, const QModelIndex&, int) {
        onTreeOrderChanged(addr);
      }));
  // QGIS 的节点移动（含用户 DnD：insertChildNodes + removeRows）不产生
  // rowsMoved，而是 rowsInserted/rowsRemoved 成对出现；flush 已按 tick 合并。
  conns.push_back(QObject::connect(
      model, &QgsLayerTreeModel::rowsInserted, view,
      [this, addr](const QModelIndex& parent, int, int) {
        if (parent.isValid()) return;  // 图例行等子级变化不算顶层排序
        onTreeOrderChanged(addr);
      }));
  conns.push_back(QObject::connect(
      model, &QgsLayerTreeModel::rowsRemoved, view,
      [this, addr](const QModelIndex& parent, int, int) {
        if (parent.isValid()) return;
        onTreeOrderChanged(addr);
      }));
  return addr;
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

void QgisMapStack::onTreeDataChanged(std::uintptr_t tree_addr, int row,
                                     bool check_role, bool display_role) {
  if (impl_->suppress_tree_callbacks > 0) return;
  if (!impl_->tree_change_callbacks.count(tree_addr)) return;
  auto viewIt = impl_->tree_views.find(tree_addr);
  if (viewIt == impl_->tree_views.end() || viewIt->second.isNull()) return;
  auto mIt = impl_->tree_models.find(tree_addr);
  if (mIt == impl_->tree_models.end() || mIt->second.isNull()) return;
  QgsLayerTreeModel* model = mIt->second.data();
  QgsLayerTreeNode* node = model->index2node(model->index(row, 0));
  QgsLayerTreeLayer* layerNode = qobject_cast<QgsLayerTreeLayer*>(node);
  if (!layerNode) return;
  QgsMapLayer* layer = layerNode->layer();
  if (!layer) return;
  const QVariant docVar = layer->customProperty(QStringLiteral("pwb/doc_id"));
  if (!docVar.isValid() || docVar.toString().isEmpty()) return;
  const std::string doc_id = docVar.toString().toStdString();
  auto& pending = impl_->tree_pending[tree_addr];
  bool touched = false;
  if (check_role) {
    const bool checked = layerNode->itemVisibilityChecked();
    auto shadowIt = impl_->known_layer_visibility.find(doc_id);
    if (shadowIt == impl_->known_layer_visibility.end()) {
      impl_->known_layer_visibility[doc_id] = checked;  // 首次见面只建基线
    } else if (shadowIt->second != checked) {
      shadowIt->second = checked;
      pending.visibility[QString::fromStdString(doc_id)] = checked;
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
      touched = true;
    }
  }
  if (touched) scheduleTreeChangeFlush(tree_addr);
}

void QgisMapStack::onTreeOrderChanged(std::uintptr_t tree_addr) {
  if (impl_->suppress_tree_callbacks > 0) return;
  if (!impl_->tree_change_callbacks.count(tree_addr)) return;
  auto viewIt = impl_->tree_views.find(tree_addr);
  if (viewIt == impl_->tree_views.end() || viewIt->second.isNull()) return;
  auto& pending = impl_->tree_pending[tree_addr];
  pending.order.clear();
  for (const auto& doc : mirrorOrderTopFirst()) {
    pending.order.push_back(QString::fromStdString(doc));
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
  QgsLayerTreeLayer* node = qobject_cast<QgsLayerTreeLayer*>(root->children().value(from));
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
  QgsVectorLayer* layer = nullptr;
  auto it = impl_->mirror_by_doc.find(doc_id);
  if (it != impl_->mirror_by_doc.end()) {
    layer = qobject_cast<QgsVectorLayer*>(
        project()->mapLayer(QString::fromStdString(it->second)));
  }
  if (!layer) layer = findMirrorByDocId(project(), doc_id);
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

}  // namespace pwb::qgis_render
