#pragma once

#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <vector>

class QgsMapCanvas;
class QgsLayerTreeView;
class QgsMapTool;
class QgsMapToolDigitizeFeature;
class QgsVectorLayer;
using QgsFeatureId = long long;

namespace pwb::qgis_render {

class QgisMapStack {
public:
  QgisMapStack();
  ~QgisMapStack();

  void initialize();
  bool initialized() const noexcept;
  int projectLayerCount() const;
  void shutdown();

  std::uintptr_t createCanvas();
  void destroyCanvas(std::uintptr_t canvas);
  void setCanvasWhiteBackground(std::uintptr_t canvas);
  void setDestinationCrs(std::uintptr_t canvas, const std::string& crs_auth_id);
  void setCanvasExtent(std::uintptr_t canvas, double xmin, double ymin,
                       double xmax, double ymax);
  std::vector<double> canvasExtent(std::uintptr_t canvas) const;
  void zoomToFullExtent(std::uintptr_t canvas);
  void zoomToPreviousExtent(std::uintptr_t canvas);
  void zoomToNextExtent(std::uintptr_t canvas);
  void refreshCanvas(std::uintptr_t canvas);
  std::vector<double> screenToMap(std::uintptr_t canvas, double x, double y) const;
  std::vector<double> mapToScreen(std::uintptr_t canvas, double x, double y) const;

  void setMapTool(std::uintptr_t canvas, const std::string& kind);
  using ExtentCallback = std::function<void(double, double, double, double)>;
  using PointCallback = std::function<void(double, double)>;
  void setExtentCallback(std::uintptr_t canvas, ExtentCallback callback);
  void setXyCallback(std::uintptr_t canvas, PointCallback callback);

  std::uintptr_t createLayerTreeView(std::uintptr_t canvas);
  void setTreeSelectionCallback(std::uintptr_t tree_view,
                                std::function<void(const std::string&)> callback);

  // Tree drive/inspection API — used by tests and M2 panel tasks to drive
  // and inspect the native QgsLayerTreeView without exposing Qt model types
  // across the address boundary. Invalid tree address throws via
  // treeViewOrThrow (invalid_argument); invalid row index throws
  // std::out_of_range.
  int treeViewRowCount(std::uintptr_t tree) const;
  std::string treeViewLayerName(std::uintptr_t tree, int row) const;
  void treeViewSetCurrentRow(std::uintptr_t tree, int row);
  // 用户语义驱动（不包 SuppressGuard，刻意触发树变更回调；测试/Task 4 面板用）
  void treeViewSetRowChecked(std::uintptr_t tree, int row, bool checked);
  void treeViewRenameRow(std::uintptr_t tree, int row, const std::string& name);
  void treeViewMoveRow(std::uintptr_t tree, int from, int to);

  // 树变更回调：JSON 批次 {"visibility":{doc:bool},"order":[doc...],"renames":{doc:name}}，
  // 只含本次实际变更；程序化 reconcile（suppress 计数 >0）期间不触发。
  void setTreeChangeCallback(std::uintptr_t tree_view,
                             std::function<void(const std::string&)> callback);

  // 右键菜单：C++ 侧组装（QGIS 默认动作 + 自定义动作键），自定义动作触发
  // callback(action_key, doc_id)。重设会替换旧 provider（view 接管所有权）。
  void setTreeMenuCallback(
      std::uintptr_t tree_view,
      std::function<void(const std::string&, const std::string&)> callback);
  // 缩放到镜像图层范围（C++ 直接作用画布，不经 Python 回环）；空范围 no-op。
  void zoomToLayer(std::uintptr_t tree_view, const std::string& doc_id);
  // 按 doc_id 置当前图层；找不到返回 false。
  bool treeViewSelectDoc(std::uintptr_t tree, const std::string& doc_id);
  // 镜像图层透明度直写（doc_id 寻址），避免整快照 reconcile。
  void setMirrorLayerOpacity(const std::string& doc_id, double opacity);
  // 原生 QgsVectorLayerProperties 模态对话框（矢量镜像专用）。返回键：
  // ok("1"/"0")；ok=1 时另有 renderer_xml/labeling_xml/opacity/name。
  // doc_id 未命中镜像或图层非矢量时抛 invalid_argument。
  std::map<std::string, std::string> execLayerProperties(
      std::uintptr_t canvas_addr, const std::string& doc_id);

  // 捕捉配置下推（M3）：JSON {"enabled":bool,"mode":"all_layers"|"active_layer",
  // "tolerance_px":double,"types":["vertex","segment","midpoint","centroid","area"],
  // "layers":{doc_id:{"enabled":bool,"types":[...],"tolerance_px":double}}}。
  // 带 layers 键时强制 AdvancedConfiguration 模式；doc_id 经 pwb/doc_id 解析镜像层。
  void setSnappingConfig(std::uintptr_t canvas, const std::string& config_json);
  // 地图坐标捕捉探测（测试/诊断用）：返回 JSON
  // {"matched":bool,"x":,"y":,"layer_doc_id":str,"vertex_index":int(-1=非顶点)}。
  std::string snapToMap(std::uintptr_t canvas, double x, double y) const;

  // 原生采点完成/取消回调（M3）：callback(status, geojson_geometry)，
  // status ∈ "completed"|"canceled"；completed 时 geojson 为 GeoJSON geometry
  // 对象字符串（画布 destination CRS），canceled 时为空串。
  // set_map_tool kind 相应扩展 "addPoint"|"addLine"|"addPolygon"。
  void setDigitizeCallback(
      std::uintptr_t canvas,
      std::function<void(const std::string&, const std::string&)> callback);

  // 顶点/移动编辑拾取回调（M3 Task 3）：callback(action, payload_json)，
  // action ∈ "vertex_moved"（path/x/y）|"feature_moved"（dx/dy）|"pick_miss"。
  // set_map_tool kind 相应扩展 "vertex"|"move"。
  void setEditPickCallback(
      std::uintptr_t canvas,
      std::function<void(const std::string&, const std::string&)> callback);

  // 选择/identify 回调（M3 Task 4）：callback(action, payload_json)，
  // action ∈ "selection"（layer_doc_id/feature_ids/modifiers）|"identify"
  // （layer_doc_id/feature_id）。set_map_tool kind 扩展 "select"|"identify"。
  void setSelectionCallback(
      std::uintptr_t canvas,
      std::function<void(const std::string&, const std::string&)> callback);
  // 画布当前图层（原生选择/identify 的目标图层）；doc_id 未命中镜像抛
  // invalid_argument。
  void setCurrentLayer(std::uintptr_t canvas, const std::string& doc_id);
  // 选中高亮投影（QgsHighlight，QGIS 桌面选中样式）：Python 选集是权威，
  // 每次调用整组替换。feature_ids_json 为 JSON 字符串数组；未知 id 跳过。
  void highlightFeatures(std::uintptr_t canvas, const std::string& doc_id,
                         const std::string& feature_ids_json);
  void clearHighlights(std::uintptr_t canvas);
  int highlightCount(std::uintptr_t canvas) const;

  std::string addVectorLayerGeoJson(const std::string& name,
                                    const std::string& geometry_type,
                                    const std::string& crs_auth_id,
                                    const std::string& geojson_feature_collection,
                                    const std::string& renderer_xml = "",
                                    const std::string& labeling_xml = "",
                                    const std::string& legacy_style_json = "");
  void setLayerStyle(const std::string& layer_id,
                     const std::string& renderer_xml,
                     const std::string& labeling_xml,
                     const std::string& legacy_style_json = "");
  bool removeLayer(const std::string& layer_id);
  void setLayerVisibility(const std::string& layer_id, bool visible);
  void setLayerOpacity(const std::string& layer_id, double opacity);
  void clearProjectLayers();

  std::string upsertMirrorLayer(const std::string& doc_id,
                                const std::string& name,
                                const std::string& geometry_type,
                                const std::string& crs_auth_id,
                                const std::string& geojson_feature_collection,
                                const std::string& renderer_xml,
                                const std::string& labeling_xml,
                                const std::string& legacy_style_json,
                                bool visible,
                                double opacity,
                                bool is_reference = false,
                                bool is_editable = false);
  void removeMirrorLayersExcept(const std::vector<std::string>& doc_ids);
  void setMirrorLayerOrder(const std::vector<std::string>& doc_ids_top_first);
  void setMirrorLayerVisibility(const std::string& doc_id, bool visible);
  std::vector<std::string> mirrorOrderTopFirst() const;
  bool mirrorLayerVisibility(const std::string& doc_id) const;
  bool treeEchoSuppressed() const noexcept;

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
  // 存活性令牌：destroyed/flush 等队列回调经 weak_ptr 探测栈是否已析构，
  // 防 QgisMapStack 先亡时的 this 悬垂（M2 终局审查 I2）。
  std::shared_ptr<char> alive_token_ = std::make_shared<char>(0);
  QgsMapCanvas* canvasOrThrow(std::uintptr_t canvas) const;
  QgsLayerTreeView* treeViewOrThrow(std::uintptr_t address) const;
  // slot: 0=Point 1=LineString 2=Polygon；惰性建 scratch 层 + 工具（M3 Task 2）。
  QgsMapToolDigitizeFeature* digitizeToolFor(std::uintptr_t canvas_addr,
                                             QgsMapCanvas* canvas, int slot);
  // vertex=true → PwbVertexTool，false → PwbMoveTool（M3 Task 3）。
  QgsMapTool* editToolFor(std::uintptr_t canvas_addr, QgsMapCanvas* canvas,
                          bool vertex);
  // 文档 feature_id 解析器（镜像 fid 映射表）；供 select/identify 共用。
  std::function<std::string(QgsVectorLayer*, QgsFeatureId)> fidResolver();
  void ensureNotStale(std::uintptr_t canvas_addr);
  void eraseMirrorByQgisId(const std::string& qgis_id);
  void eraseMirrorByDocId(const std::string& doc_id);
  void cleanupTreeViewState(std::uintptr_t tree_view);
  void onTreeDataChanged(std::uintptr_t tree, int row, bool check_role, bool display_role);
  void onTreeOrderChanged(std::uintptr_t tree);
  void scheduleTreeChangeFlush(std::uintptr_t tree);
  void flushTreeChange(std::uintptr_t tree);
};

}  // namespace pwb::qgis_render
