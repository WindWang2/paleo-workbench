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

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace pwb::qgis_render
