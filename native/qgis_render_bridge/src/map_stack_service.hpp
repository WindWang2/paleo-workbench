#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

class QgsMapCanvas;
class QgsLayerTreeView;

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
                                double opacity);
  void removeMirrorLayersExcept(const std::vector<std::string>& doc_ids);
  void setMirrorLayerOrder(const std::vector<std::string>& doc_ids_top_first);
  void setMirrorLayerVisibility(const std::string& doc_id, bool visible);
  std::vector<std::string> mirrorOrderTopFirst() const;
  bool mirrorLayerVisibility(const std::string& doc_id) const;
  bool treeEchoSuppressed() const noexcept;

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
  QgsMapCanvas* canvasOrThrow(std::uintptr_t canvas) const;
  QgsLayerTreeView* treeViewOrThrow(std::uintptr_t address) const;
  void ensureNotStale(std::uintptr_t canvas_addr);
  void eraseMirrorByQgisId(const std::string& qgis_id);
  void eraseMirrorByDocId(const std::string& doc_id);
};

}  // namespace pwb::qgis_render
