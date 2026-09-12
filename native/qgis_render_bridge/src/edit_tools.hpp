#pragma once

// M3 Task 3：薄编辑工具（顶点编辑 / 要素移动）。
// QgsVertexTool / QgsMapToolMoveFeature 是 app 层（APP_EXPORT）不可链接，
// 这里自实现裁剪版：snapToMap 无关的独立拾取 + QgsRubberBand 拖动预览。
// 数据变更双模（拓扑编辑迁移 M1 §2 编辑权迁移）：
// - v1（默认，无原生编辑会话）：回调交 Python 权威会话，镜像层只读；
// - v2（当前层处于 M1 原生会话，setEditLayerProvider 解析）：直接编辑
//   镜像层缓冲——每手势恰一宏（begin/endEditCommand），共享节点
//   （1e-8 精确重合）联合拖动/联合删除，手势经 edit_gesture 回调记账。

#include <functional>
#include <memory>
#include <string>
#include <vector>

#include <QPointer>

#include <qgsfeature.h>
#include <qgsfeaturerequest.h>
#include <qgsgeometry.h>
#include <qgsmaptool.h>
#include <qgspointlocator.h>
#include <qgspointxy.h>
#include <qgsvertexid.h>
#include <qgsvertexmarker.h>

class QgsRubberBand;
class QgsSnapIndicator;
class QgsVectorLayer;
class QgsMapToolSelectionHandler;
class QgsDistanceArea;

namespace pwb::qgis_render {

class PwbEditPickTool : public QgsMapTool {
 public:
  using Callback =
      std::function<void(const std::string& action, const std::string& payload_json)>;
  // 文档 feature_id 解析（桥侧镜像 fid 映射表）；空则回落数值 fid。
  using FeatureIdResolver =
      std::function<std::string(QgsVectorLayer* layer, QgsFeatureId fid)>;

  PwbEditPickTool(QgsMapCanvas* canvas, Callback callback,
                  FeatureIdResolver resolver = nullptr);
  ~PwbEditPickTool() override;

  void keyPressEvent(QKeyEvent* e) override;
  void deactivate() override;
  // M3 Task 5：键盘路径归一——拖动中 Esc 归原生工具，不上送 Python。
  bool dragging() const noexcept { return dragging_; }

 protected:
  static constexpr double kTolerancePx = 10.0;
  // 共享节点判定（M1 §2 不变式）：map CRS 下 1e-8 精确重合（≠吸附容差）。
  static constexpr double kSharedNodeEpsilon = 1e-8;

  struct Pick {
    QPointer<QgsVectorLayer> layer;
    QgsFeatureId fid = FID_NULL;
    QgsGeometry geometry;  // 层 CRS（镜像层即工程/画布 CRS）
    std::string docId;
    std::string featureId;  // __pwb_fid 属性；无则数值 fid 字符串
  };

  // 最近要素拾取（与捕捉开关无关，编辑工具桌面语义）：命中返回 true。
  bool pickFeature(const QgsPointXY& mapPoint, Pick& out) const;
  // 几何内最近顶点（容差内）；Python 路径经 vertexPathJson 换算。
  bool nearestVertex(const Pick& pick, const QgsPointXY& mapPoint,
                     QgsVertexId& out) const;
  // (part, ring, vertex) + wkb 类型 → Python 顶点路径 JSON（"[]"/"[i]"/"[r,i]"/...）。
  static std::string vertexPathJson(Qgis::WkbType wkbType, const QgsVertexId& id);
  // 捕捉开启时吸附，否则原样。
  QgsPointXY snapOrRaw(const QgsPointXY& mapPoint) const;
  std::string basePayload(const Pick& pick) const;
  void cancelDrag();

  // -- V10：snap 指示 + 节流反馈（QgsSnapIndicator 为 GUI 公开类，直接复用）--
  // 查询捕捉命中（不吸附坐标）：hover 检测与反馈共用。
  QgsPointLocator::Match snapMatch(const QgsPointXY& mapPoint) const;
  // 指示器更新 + "snap_feedback" 回调（签名变化或命中点位移 > 1 像素才回传，
  // 60Hz 纯 hover 不打 FFI）。已有命中的调用方传 match（复用同一查询——
  // 每次 move 只允许一次 snapToMap，review-4 #2）。
  void updateSnapIndicator(const QgsPointXY& mapPoint,
                           const QgsPointLocator::Match* match = nullptr);
  void hideSnapIndicator();

  Callback callback_;
  FeatureIdResolver resolver_;
  std::unique_ptr<QgsRubberBand> rubber_;
  Pick current_;
  bool dragging_ = false;
  std::unique_ptr<QgsSnapIndicator> snap_indicator_;
  std::string snap_feedback_signature_;
  bool snap_feedback_emitted_ = false;
  double snap_feedback_x_ = 0.0;
  double snap_feedback_y_ = 0.0;
};

class PwbVertexTool : public PwbEditPickTool {
 public:
  using PwbEditPickTool::PwbEditPickTool;
  // unique_ptr 成员的析构需完整类型：显式声明，定义在 edit_tools.cpp。
  ~PwbVertexTool() override;
  void canvasPressEvent(QgsMapMouseEvent* e) override;
  void canvasMoveEvent(QgsMapMouseEvent* e) override;
  void canvasReleaseEvent(QgsMapMouseEvent* e) override;
  // V10：双击段上插点 / Delete 删除 hover 顶点（QGIS 桌面顶点工具语义）。
  void canvasDoubleClickEvent(QgsMapMouseEvent* e) override;
  void keyPressEvent(QKeyEvent* e) override;
  void deactivate() override;

  // 拓扑编辑迁移 M1（§4 顶点工具 v2 当前层档）：原生编辑目标解析器——
  // 返回处于 M1 原生会话的画布当前层（无会话 → nullptr = v1 回调模式，
  // 行为与 V10 完全一致）。QgisMapStack 在工具创建时注入。
  void setEditLayerProvider(
      std::function<QgsVectorLayer*()> provider) {
    edit_layer_provider_ = std::move(provider);
  }

 private:
  // hover 状态：顶点命中（Delete 删点）或段命中（双击插点，insert_before 为
  // 段终点 QgsVertexId——Python insert 语义 = parent.insert(index, point)）。
  struct HoverState {
    bool has_vertex = false;
    bool has_segment = false;
    Pick pick;
    QgsVertexId vertex;
    QgsVertexId insert_before;
    QgsPointXY segment_point;
  };

  // v2：共享节点引用（map CRS 下 1e-8 精确重合集，§2 不变式）。
  struct VertexRef {
    QgsFeatureId fid = FID_NULL;
    QgsVertexId vid;
    QgsPointXY pos;
  };

  // 刷新 hover（snapping locator 优先；关闭时容差拾取回退）。返回是否有命中。
  bool updateHover(const QgsPointXY& mapPoint);
  // 同 updateHover，但把已查询的 locator 命中返回给调用方复用（单 move 单查询）。
  QgsPointLocator::Match updateHoverMatch(const QgsPointXY& mapPoint);
  bool nearestSegmentOnFeature(const Pick& pick, const QgsPointXY& mapPoint,
                               QgsVertexId& endVid, QgsPointXY& projOut) const;
  // 删除后仍满足最少顶点（ring>=4 含闭合点 / line>=2）；点/多点不支持。
  bool minVerticesAfterDelete(const Pick& pick, const QgsVertexId& vid) const;
  void updateHoverMarker();
  void clearHover();

  // -- v2（当前层档；仅 editLayer() 非空时启用）--------------------------
  QgsVectorLayer* editLayer() const;
  // 层内与 center 距离 <= radius 的全部顶点（getFeatures 合并编辑缓冲——
  // 共享节点发现的事实源）。线性扫描：当前层档要素量级下确定可接受。
  static std::vector<VertexRef> verticesNear(QgsVectorLayer* layer,
                                             const QgsPointXY& center,
                                             double radius);
  void beginSharedDrag(const QgsPointXY& anchor,
                       std::vector<VertexRef> shared);
  void finishSharedDrag(QgsVectorLayer* layer, const QgsPointXY& target);
  void clearSharedMarkers();
  void emitGesture(const char* gesture, const char* undo_text,
                   QgsVectorLayer* layer,
                   const std::vector<QgsFeatureId>& fids) const;

  QgsVertexId vertex_id_;
  HoverState hover_;
  std::unique_ptr<QgsVertexMarker> hover_marker_;
  // v2 状态：拖动中的共享节点集（含框选扩展）与高亮 marker。
  std::function<QgsVectorLayer*()> edit_layer_provider_;
  std::vector<VertexRef> shared_drag_;
  QgsPointXY drag_anchor_;
  std::vector<std::unique_ptr<QgsVertexMarker>> shared_markers_;
};

class PwbMoveTool : public PwbEditPickTool {
 public:
  using PwbEditPickTool::PwbEditPickTool;
  void canvasPressEvent(QgsMapMouseEvent* e) override;
  void canvasMoveEvent(QgsMapMouseEvent* e) override;
  void canvasReleaseEvent(QgsMapMouseEvent* e) override;

 private:
  QgsPointXY origin_;
};

// 原生选择工具（M3 Task 4）：QgsMapToolSelectionHandler 承载
// 点击/框选/多边形等交互与 rubber band，命中计算在桥内（当前图层），
// 结果经回调交 Python——不写 QGIS 层选集（选集权威在 Python）。
class PwbSelectTool : public PwbEditPickTool {
 public:
  PwbSelectTool(QgsMapCanvas* canvas, Callback callback,
                FeatureIdResolver resolver = nullptr);
  void canvasPressEvent(QgsMapMouseEvent* e) override;
  void canvasMoveEvent(QgsMapMouseEvent* e) override;
  void canvasReleaseEvent(QgsMapMouseEvent* e) override;
  void keyReleaseEvent(QKeyEvent* e) override;
  void deactivate() override;

 private:
  void onGeometryChanged(Qt::KeyboardModifiers modifiers);

  std::unique_ptr<QgsMapToolSelectionHandler> handler_;
};


// 原生测距工具（V7）：折线采点 + QgsDistanceArea 距离测算。
// 地理坐标系 + 椭球体配置时自动走椭球测算（修正 Python math.dist 在
// 地理系下的平面距离错误）；结果经回调上浮（updated/completed/canceled），
// 不写任何层——与其它编辑工具一致，权威在 Python 宿主。
class PwbMeasureTool : public PwbEditPickTool {
 public:
  // 需在构造时配置 QgsDistanceArea（画布 CRS + 工程椭球），不能继承基类
  // 构造（PwbVertexTool/PwbMoveTool 的无状态模式不适用）。
  PwbMeasureTool(QgsMapCanvas* canvas, Callback callback);
  ~PwbMeasureTool() override;

  void canvasPressEvent(QgsMapMouseEvent* e) override;
  void canvasMoveEvent(QgsMapMouseEvent* e) override;
  void canvasReleaseEvent(QgsMapMouseEvent* e) override;
  void keyPressEvent(QKeyEvent* e) override;
  void deactivate() override;
  // 已采点（Esc 归原生工具：只清折线，不退出工具）。
  bool measuring() const noexcept { return !points_.isEmpty(); }

 private:
  // payload: {"points":[[x,y]...],"segments":[d...],"total":t,
  //           "ellipsoidal":bool}（segments 含 hover 段）。
  std::string payloadJson(const char* action, const QgsPointXY& hover) const;
  double totalIncluding(const QgsPointXY& hover) const;
  void reset();

  std::unique_ptr<QgsRubberBand> rubber_;
  std::unique_ptr<QgsDistanceArea> distance_;
  QVector<QgsPointXY> points_;
  bool ellipsoidal_ = false;
};

}  // namespace pwb::qgis_render
