#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

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

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace pwb::qgis_render
