#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

class QgsMapCanvas;

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

  std::string addVectorLayerGeoJson(const std::string& name,
                                    const std::string& geometry_type,
                                    const std::string& crs_auth_id,
                                    const std::string& geojson_feature_collection);
  bool removeLayer(const std::string& layer_id);
  void setLayerVisibility(const std::string& layer_id, bool visible);
  void setLayerOpacity(const std::string& layer_id, double opacity);
  void clearProjectLayers();

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
  QgsMapCanvas* canvasOrThrow(std::uintptr_t canvas) const;
  void ensureNotStale(std::uintptr_t canvas_addr);
};

}  // namespace pwb::qgis_render
