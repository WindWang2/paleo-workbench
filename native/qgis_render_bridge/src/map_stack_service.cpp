#include "map_stack_service.hpp"

#include <stdexcept>

#include <QCoreApplication>
#include <QString>

#include <qgsapplication.h>
#include <qgsproject.h>

namespace pwb::qgis_render {

#ifdef PALEO_QGIS_PREFIX_PATH
#undef PALEO_QGIS_PREFIX_PATH
#endif
extern const std::string PALEO_QGIS_PREFIX_PATH;

struct QgisMapStack::Impl {
  bool initialized = false;
};

QgisMapStack::QgisMapStack() : impl_(std::make_unique<Impl>()) {}
QgisMapStack::~QgisMapStack() = default;

void QgisMapStack::initialize() {
  if (impl_->initialized) return;
  if (QCoreApplication::instance() == nullptr) {
    throw std::runtime_error("QgisMapStack requires an existing Qt application");
  }
  if (PALEO_QGIS_PREFIX_PATH.empty()) {
    throw std::runtime_error("vendored QGIS prefix is not configured");
  }
  QgsApplication::setPrefixPath(
      QString::fromStdString(PALEO_QGIS_PREFIX_PATH), true);
  QgsApplication::init();
  QgsApplication::initQgis();
  impl_->initialized = true;
}

bool QgisMapStack::initialized() const noexcept { return impl_->initialized; }

int QgisMapStack::projectLayerCount() const {
  return static_cast<int>(QgsProject::instance()->count());
}

void QgisMapStack::shutdown() {
  QgsProject::instance()->removeAllMapLayers();
  impl_->initialized = false;
}

}  // namespace pwb::qgis_render
