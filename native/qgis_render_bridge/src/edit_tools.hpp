#pragma once

// M3 Task 3：薄编辑工具（顶点编辑 / 要素移动）。
// QgsVertexTool / QgsMapToolMoveFeature 是 app 层（APP_EXPORT）不可链接，
// 这里自实现裁剪版：snapToMap 无关的独立拾取 + QgsRubberBand 拖动预览；
// 数据变更一律经回调交 Python 权威会话（VectorEditSession），镜像层只读。

#include <functional>
#include <memory>
#include <string>

#include <QPointer>

#include <qgsfeature.h>
#include <qgsfeaturerequest.h>
#include <qgsgeometry.h>
#include <qgsmaptool.h>
#include <qgspointxy.h>
#include <qgsvertexid.h>

class QgsRubberBand;
class QgsVectorLayer;
class QgsMapToolSelectionHandler;

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

 protected:
  static constexpr double kTolerancePx = 10.0;

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

  Callback callback_;
  FeatureIdResolver resolver_;
  std::unique_ptr<QgsRubberBand> rubber_;
  Pick current_;
  bool dragging_ = false;
};

class PwbVertexTool : public PwbEditPickTool {
 public:
  using PwbEditPickTool::PwbEditPickTool;
  void canvasPressEvent(QgsMapMouseEvent* e) override;
  void canvasMoveEvent(QgsMapMouseEvent* e) override;
  void canvasReleaseEvent(QgsMapMouseEvent* e) override;

 private:
  QgsVertexId vertex_id_;
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

}  // namespace pwb::qgis_render
