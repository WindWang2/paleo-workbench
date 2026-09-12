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
class QgsProject;
class QgsLayerTreeNode;
class QgsLayerTreeGroup;
class QModelIndex;
using QgsFeatureId = long long;

namespace pwb::qgis_render {

class QgisMapStack {
public:
  QgisMapStack();
  ~QgisMapStack();

  void initialize(bool display = false);
  bool isDisplay() const noexcept;
  bool initialized() const noexcept;
  int projectLayerCount() const;
  int canvasLayerCount(std::uintptr_t canvas) const;
  void shutdown();

  std::uintptr_t createCanvas();
  void destroyCanvas(std::uintptr_t canvas);
  // Qt 直接销毁画布（绕过 destroyCanvas）时的表回收：绝不解引用画布。
  void reapCanvasTables(std::uintptr_t canvas_addr);
  void setCanvasWhiteBackground(std::uintptr_t canvas);
  void setDestinationCrs(std::uintptr_t canvas, const std::string& crs_auth_id);
  /// V9 W1: canvas authority scale (QgsMapCanvas::scale()); 0.0 when the
  /// canvas has no extent yet. Host ToolContext.scale_denominator source.
  double canvasScale(std::uintptr_t canvas) const;
  /// V9 W7: current canvas destination CRS auth id ("" when unset/invalid).
  /// Digitize-commit CRS guard compares it against the session layer's CRS.
  std::string canvasDestinationCrs(std::uintptr_t canvas) const;
  void setCanvasExtent(std::uintptr_t canvas, double xmin, double ymin,
                       double xmax, double ymax);
  std::vector<double> canvasExtent(std::uintptr_t canvas) const;
  void zoomToFullExtent(std::uintptr_t canvas);
  void zoomToPreviousExtent(std::uintptr_t canvas);
  void zoomToNextExtent(std::uintptr_t canvas);
  void refreshCanvas(std::uintptr_t canvas);
  /// #1156: refresh is asynchronous; callers that need a finished frame
  /// pump the outer event loop and poll this until false.
  bool isCanvasRendering(std::uintptr_t canvas) const;
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
  // V5 分组扩展（schema 2）：payload 追加 "schema":2 与 "events":[{type,...}]
  // typed 事件（layer/group 的 visibility/rename）与 "tree":[...] 全层级
  // 结构快照（结构变化时携带，覆盖 move/group-create/group-delete）。
  void setTreeChangeCallback(std::uintptr_t tree_view,
                             std::function<void(const std::string&)> callback);

  // 组节点展开态回调（V5 StageViewState 持久化）：callback(node_id, expanded)；
  // node_id 为 group_id（组）或 doc_id（图层的图例行）。
  void setTreeExpandCallback(std::uintptr_t tree_view,
                             std::function<void(const std::string&, bool)> callback);

  // ---------------------------------------------------------------- V5 groups
  // QGIS 原生 QgsLayerTreeGroup 管理：稳定 group id 经 custom property
  // "pwb/group_id" 寻址（与显示名解耦）。parent_group_id 为空串 = 根。
  // group API 全部程序化（SuppressGuard），用户树操作经 tree change 回调回声。
  bool groupExists(const std::string& group_id) const;
  bool upsertGroup(const std::string& group_id, const std::string& name,
                   const std::string& parent_group_id);
  // 移除不在列表中的组；**绝不移动/删除组内图层**——子节点先上提到父组，
  // 空组才删除（QgsLayerTreeRegistryBridge 不会因此注销图层）。
  // 返回移除的组数量。
  int removeGroupsExcept(const std::vector<std::string>& group_ids);
  void renameGroup(const std::string& group_id, const std::string& name);
  void setGroupVisibility(const std::string& group_id, bool visible);
  // 把镜像图层节点放入目标组（group_id 空 = 根）的 index 位置；index 越界钳制。
  void moveLayerToGroup(const std::string& doc_id, const std::string& group_id, int index);
  // 组重挂（禁止移入自身后代，违反抛 invalid_argument）。
  void moveGroup(const std::string& group_id, const std::string& parent_group_id, int index);
  // 树结构快照（观察）：[{"type":"group","id":gid,"name":n,"visible":bool,
  // "children":[...]},{"type":"layer","id":doc_id,"name":n,"visible":bool}]，
  // 深度优先、自上而下（渲染序）。无 pwb/group_id 的组获得稳定 "user_<uuid>" id。
  std::string treeSnapshotJson() const;
  // 程序化展开/收起组节点（恢复 StageViewState）。
  void setGroupExpanded(std::uintptr_t tree_view, const std::string& node_id, bool expanded);

  // V5 批量放置：placements JSON [{"node":"doc 或 group:<gid>","parent":"<gid|''>",
  // "index":int}, ...] —— 单次桥调用完成全部放置 + 仅一次画布同步
  //（逐个 move_* 是 O(N²)：每次都做全树 find + 全画布 sync）。
  // 返回应用的放置数；未知节点跳过并计数在返回 JSON {"applied":n,"skipped":m}。
  std::string applyTreePlacements(const std::string& placements_json);

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
  // 原生工具是否占有键盘取消语义（M3 Task 5）：采点中/拖动中为 true，
  // 此时 Esc 应由画布直接派发给原生工具，不上送 Python 工具栈。
  bool nativeToolBusy(std::uintptr_t canvas) const;

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

  // 测距回调（V7）：callback(action, payload_json)，action ∈
  // "measure_updated"|"measure_completed"（points/segments/total/ellipsoidal）
  // |"measure_canceled"（空 payload）。set_map_tool kind 扩展 "measure"。
  void setMeasureCallback(
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
                                bool is_editable = false,
                                // 参考图层「参与捕捉」勾选态投影（Python 权威），菜单读取。
                                bool reference_snap = false,
                                // v7 §9: host data revision (0 = unknown; a
                                // zero disables the delta channel).
                                std::uint64_t data_revision = 0,
                                // v7 §9: incremental payload — applied in
                                // place when the mirror provably holds
                                // base_revision; a mismatch falls back to the
                                // full-collection path (concurrent reset is a
                                // full-ship case, never an error).
                                const std::string& delta_json = "",
                                // v7 R3-1: spec-authored field schema JSON
                                // (qgis_layer_schema wire). Persisted as the
                                // pwb/fields_json custom property and
                                // re-applied on rebuild; memory-provider field
                                // application is the documented follow-up.
                                const std::string& fields_json = "",
                                // V10 M-O: scale-based visibility channel
                                // (denominators; 0 = unbounded on that side;
                                // both 0 disables). Applied to new AND reused
                                // mirrors — the native authoring canvas
                                // previously had no scale-visibility at all.
                                double min_scale = 0.0,
                                double max_scale = 0.0);
  /// v7 §5: raster mirror upsert (single-band scalar GeoTIFF + optional
  /// pseudocolor renderer XML).  Same doc-keyed contract as the vector
  /// mirror: reuse by doc_id, rebuild on source change, style-only change
  /// reapplies the renderer without touching the raster source.  The CRS
  /// comes from the GeoTIFF itself (crs_auth_id is advisory metadata for
  /// the host and may be empty).
  std::string upsertRasterMirrorLayer(const std::string& doc_id,
                                      const std::string& name,
                                      const std::string& source_path,
                                      const std::string& crs_auth_id,
                                      const std::string& renderer_xml,
                                      bool visible,
                                      double opacity,
                                      bool is_reference = false);
  void removeMirrorLayersExcept(const std::vector<std::string>& doc_ids);
  void setMirrorLayerOrder(const std::vector<std::string>& doc_ids_top_first);
  void setMirrorLayerVisibility(const std::string& doc_id, bool visible);
  std::vector<std::string> mirrorOrderTopFirst() const;
  bool mirrorLayerVisibility(const std::string& doc_id) const;
  bool treeEchoSuppressed() const noexcept;
  // ✏ 编辑态图层指示器（M2 移交项：QGIS 桌面经图层指示器呈现编辑态）；
  // 幂等整组替换，on=false 时清除。doc_id 未镜像时静默忽略。
  void setEditIndicator(std::uintptr_t tree, const std::string& doc_id, bool on);
  int editIndicatorCount(std::uintptr_t tree, const std::string& doc_id) const;
  // V8 M5: 通用行指示器——kinds_json 为字符串数组，词汇与 host
  // state_language 的 LayerPresentationState 装饰集对齐（dirty/stale/
  // missing/missing_input/superseded/degraded/frozen/published/reviewed）。
  // 幂等整组替换（不动 ✏ 编辑铅笔）；未知 kind 跳过；doc_id 未镜像时
  // 静默忽略。kind 过滤的计数用于 parity 测试。
  void setRowIndicators(std::uintptr_t tree, const std::string& doc_id,
                        const std::string& kinds_json);
  int rowIndicatorCount(std::uintptr_t tree, const std::string& doc_id,
                        const std::string& kind = "") const;

  // M5: mini QgsProject XML envelope (renderer/labeling/visibility/opacity/order).
  // Features stay in Python; apply matches live mirrors by pwb/doc_id.
  std::string writeProjectXml();
  // V8 M1 自省面：doc_id 镜像层上真实应用的 provider schema（fields/
  // constraints/alias/editor widget/default 的 JSON 事实）。未镜像 →
  // {"exists": false}。当前消费者为 qgis-marked 测试；host 侧
  // Inspector/handshake 接入为后续（能力事实面，非展示规则）。
  std::string mirrorLayerSchemaJson(const std::string& doc_id) const;
  // V8 M1 自省面（数据侧）：镜像层真实存储的要素 + typed 属性
  // （GeoJSON FeatureCollection，limit 截断）。
  std::string mirrorFeaturesJson(const std::string& doc_id, int limit = 16) const;
  // V10 M-A: one-shot runtime facts as JSON — QGIS/PROJ/GDAL versions,
  // prefix/data/svg paths, provider registry, CRS probes (EPSG:4326/4490/
  // 4214/4610) and a 4326→4490 transform probe. Headless (no canvas);
  // requires initialize(). Consumed by qgis_runtime.health — the honest
  // replacement for "canvas renders, so the runtime must be fine".
  std::string runtimeFacts() const;
  // V10 M-C: push the owning project's CRS (+ ellipsoid derived from it) so
  // QgsProject::transformContext()/ellipsoid() consumers (measure,
  // identify) stop seeing the empty default. Returns "" on success, else a
  // human-readable reason (invalid/unresolvable authid).
  std::string setProjectCrs(const std::string& authid);
  // V10 M-O: map-settings facts the host must read, not re-estimate.
  // canvasMapUnits → QgsUnitTypes encoded unit ("degrees"/"meters"/...).
  std::string canvasMapUnits(std::uintptr_t canvas) const;
  double canvasOutputDpi(std::uintptr_t canvas) const;
  // V10 M-H: provider capability snapshot for a mirrored layer (JSON).
  // Vector: provider/storage/geometry/wkbType, capability flags
  // (add/delete features, change geometry/attributes, add/delete
  // attributes, create spatial index), supportsEditing, transactions,
  // spatial index presence, feature count, extent, CRS. Raster: provider,
  // extent, bandCount, per-band data type + nodata, CRS. Unmirrored →
  // {"exists": false}.
  std::string mirrorProviderFacts(const std::string& doc_id) const;
  // V10 M-K: applied renderer/labeling XML read-back (drift check on the
  // Python side, mirroring mirrorLayerSchemaJson for fields).
  std::string mirrorStyleJson(const std::string& doc_id) const;
  int applyProjectXml(const std::string& xml);

  // M7: component-graph → QgsLayout export. The spec is a JSON document
  // {"page":{width_mm,height_mm,background},"items":[...]} with item types
  // map/legend/scalebar/north_arrow/picture/label/shape. The layout is built
  // from the stack's mirrored layers at export time and discarded — never a
  // second writable map document. format ∈ "pdf"|"svg"|"png".
  // Returns a JSON report {ok,path,format,dpi,items,page_mm}.
  std::string layoutExport(const std::string& spec_json,
                           const std::string& output_path,
                           const std::string& format,
                           double dpi);

private:
  struct Impl;

  /// v7 §9: apply {"base_revision","changed":[Feature],"removed_ids":[id]}
  /// to a live mirror by __pwb_fid (delete + re-add, mirroring the offscreen
  /// #932 semantics).  False ⇒ caller falls back to the full path.
  bool applyMirrorFeatureDelta(QgsVectorLayer& layer, const std::string& doc_id,
                               const std::string& delta_json,
                               std::uint64_t new_revision);
  /// V10（review-5 #1257）：镜像要素几何变更后失效各画布上该层的
  /// QgsPointLocator 索引（provider 级 truncate/add/delete 不发 layer
  /// dataChanged，定位器会拿着过期几何继续服务捕捉）。仅处理已建索引的
  /// 定位器；未预热层不在发布热路径上构建索引。幂等。
  void invalidateLocators(const QgsVectorLayer& layer);
  std::unique_ptr<Impl> impl_;
  QgsProject* project() const;
  void syncCanvasLayers(std::uintptr_t canvas);
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
  void onTreeDataChanged(std::uintptr_t tree, const QModelIndex& topLeft,
                         bool check_role, bool display_role);
  void onTreeOrderChanged(std::uintptr_t tree, bool structure);
  void scheduleTreeChangeFlush(std::uintptr_t tree);
  void flushTreeChange(std::uintptr_t tree);
  // V5 groups 内部：组寻址 + 树 JSON 组装（深度优先、自上而下）。
  QgsLayerTreeGroup* findGroupByGroupId(const std::string& group_id) const;
  // 节点级 expandedChanged 接线（V5 StageViewState）。
  void wireNodeExpandSignalsRecursively(QgsLayerTreeNode* node);
  void wireNodeExpandSignal(QgsLayerTreeNode* node);
  // applyProjectXml 内部（调用方已持 SuppressGuard）的轻量组恢复。
  void upsertGroupUnderLock(const std::string& group_id, const std::string& name,
                            const std::string& parent_group_id);
  void moveLayerToGroupUnderLock(const std::string& doc_id,
                                 const std::string& group_id, int index);
};

}  // namespace pwb::qgis_render
