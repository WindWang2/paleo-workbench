#include "qgis_render_bridge.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <mutex>
#include <stdexcept>
#include <unordered_map>
#include <utility>

#include <QCoreApplication>
#include <QImage>
#include <QList>
#include <QSize>
#include <QString>

#include <qgsapplication.h>
#include <qgscoordinatereferencesystem.h>
#include <qgsfeature.h>
#include <qgsgeometry.h>
#include <qgsmaplayer.h>
#include <qgsmaprendererparalleljob.h>
#include <qgsmapsettings.h>
#include <qgsrectangle.h>
#include <qgsvectordataprovider.h>
#include <qgsvectorlayer.h>

namespace pwb::qgis_render {
namespace {

std::mutex g_qgis_lifecycle_mutex;
std::size_t g_qgis_bridge_count = 0;
bool g_qgis_initialized = false;

QString geometry_uri_for(const VectorLayerSpec& spec) {
    for (const FeatureSpec& feature : spec.features) {
        const QString wkt = QString::fromStdString(feature.wkt).trimmed().toUpper();
        if (wkt.startsWith("MULTIPOLYGON")) return QStringLiteral("MultiPolygon");
        if (wkt.startsWith("POLYGON")) return QStringLiteral("Polygon");
        if (wkt.startsWith("MULTILINESTRING")) return QStringLiteral("MultiLineString");
        if (wkt.startsWith("LINESTRING")) return QStringLiteral("LineString");
        if (wkt.startsWith("MULTIPOINT")) return QStringLiteral("MultiPoint");
        if (wkt.startsWith("POINT")) return QStringLiteral("Point");
    }
    return QStringLiteral("Unknown");
}

QgsRectangle normalized_extent(const std::array<double, 4>& values) {
    if (!std::all_of(values.begin(), values.end(), [](double value) { return std::isfinite(value); })) {
        throw std::invalid_argument("render extent must contain finite coordinates");
    }
    const double xmin = values[0];
    const double ymin = values[1];
    const double xmax = values[2];
    const double ymax = values[3];
    if (xmax < xmin || ymax < ymin) {
        throw std::invalid_argument("render extent has inverted bounds");
    }
    const double dx = xmax - xmin;
    const double dy = ymax - ymin;
    const double pad = std::max({1.0, std::abs(xmin), std::abs(ymin), std::abs(xmax), std::abs(ymax)}) * 1e-9;
    return QgsRectangle(
        dx > 0.0 ? xmin : xmin - pad,
        dy > 0.0 ? ymin : ymin - pad,
        dx > 0.0 ? xmax : xmax + pad,
        dy > 0.0 ? ymax : ymax + pad
    );
}

void validate_request(const int width, const int height, const double dpi) {
    if (width < 1 || height < 1 || !std::isfinite(dpi) || dpi <= 0.0) {
        throw std::invalid_argument("render size and dpi must be positive");
    }
}

}  // namespace

class QgisRenderBridge::Impl {
  public:
    struct Mirror {
        std::uint64_t data_revision = 0;
        std::uint64_t style_revision = 0;
        bool visible = true;
        std::unique_ptr<QgsVectorLayer> layer;
    };

    struct SnapshotInput {
        std::vector<VectorLayerSpec> layers;
        std::string project_crs;
    };

    struct Request {
        std::array<double, 4> extent;
        int width = 0;
        int height = 0;
        double dpi = 96.0;
        std::uint64_t generation = 0;
    };

    bool initialized = false;
    std::string project_crs;
    std::vector<std::string> ordered_ids;
    std::unordered_map<std::string, Mirror> mirrors;
    std::unique_ptr<QgsMapRendererParallelJob> active_job;
    std::optional<Request> active_request;
    std::optional<Request> pending_request;
    std::optional<SnapshotInput> pending_snapshot;
    std::optional<RenderResult> completed;
    bool discard_active_result = false;
    std::chrono::steady_clock::time_point active_started;

    void apply_snapshot(std::vector<VectorLayerSpec> layers, std::string destination_crs) {
        std::unordered_map<std::string, Mirror> next;
        std::vector<std::string> order;
        for (VectorLayerSpec& spec : layers) {
            if (spec.id.empty()) throw std::invalid_argument("QGIS vector layer id is required");
            auto existing = mirrors.find(spec.id);
            const bool rebuild = existing == mirrors.end()
                || existing->second.data_revision != spec.data_revision
                || existing->second.style_revision != spec.style_revision;

            Mirror mirror;
            if (!rebuild) {
                mirror = std::move(existing->second);
            } else {
                const QString geometry_uri = geometry_uri_for(spec);
                const QString uri = QStringLiteral("%1?crs=%2")
                                        .arg(geometry_uri, QString::fromStdString(spec.crs));
                mirror.layer = std::make_unique<QgsVectorLayer>(
                    uri, QString::fromStdString(spec.name), QStringLiteral("memory")
                );
                if (!mirror.layer->isValid()) {
                    throw std::runtime_error("QGIS could not create memory layer " + spec.id);
                }
                QgsFeatureList features;
                for (const FeatureSpec& feature_spec : spec.features) {
                    QgsGeometry geometry = QgsGeometry::fromWkt(QString::fromStdString(feature_spec.wkt));
                    if (geometry.isNull()) {
                        throw std::invalid_argument("invalid WKT for QGIS layer " + spec.id);
                    }
                    QgsFeature feature(mirror.layer->fields());
                    feature.setGeometry(std::move(geometry));
                    features.push_back(std::move(feature));
                }
                if (!features.empty() && !mirror.layer->dataProvider()->addFeatures(features)) {
                    throw std::runtime_error("QGIS could not add features for layer " + spec.id);
                }
                mirror.layer->updateExtents();
            }
            mirror.data_revision = spec.data_revision;
            mirror.style_revision = spec.style_revision;
            mirror.visible = spec.visible;
            mirror.layer->setOpacity(std::clamp(spec.opacity, 0.0, 1.0));
            order.push_back(spec.id);
            next.emplace(spec.id, std::move(mirror));
        }
        mirrors = std::move(next);
        ordered_ids = std::move(order);
        project_crs = std::move(destination_crs);
    }

    [[nodiscard]] QgsMapSettings settings_for(const Request& request) const {
        QgsMapSettings settings;
        QList<QgsMapLayer*> layers;
        for (const std::string& id : ordered_ids) {
            const auto it = mirrors.find(id);
            if (it != mirrors.end() && it->second.visible) layers.append(it->second.layer.get());
        }
        settings.setLayers(layers);
        settings.setExtent(normalized_extent(request.extent));
        settings.setOutputSize(QSize(request.width, request.height));
        settings.setOutputDpi(request.dpi);
        settings.setOutputImageFormat(QImage::Format_RGBA8888);
        settings.setBackgroundColor(Qt::transparent);
        if (!project_crs.empty()) {
            settings.setDestinationCrs(QgsCoordinateReferenceSystem(
                QString::fromStdString(project_crs)
            ));
        }
        return settings;
    }

    void start(const Request& request) {
        active_started = std::chrono::steady_clock::now();
        active_request = request;
        active_job = std::make_unique<QgsMapRendererParallelJob>(settings_for(request));
        active_job->start();
    }

    void finish_active_if_done() {
        if (!active_job || active_job->isActive()) return;

        const auto finished = std::chrono::steady_clock::now();
        const Request request = *active_request;
        const QImage image = active_job->renderedImage().convertToFormat(QImage::Format_RGBA8888);
        RenderResult result;
        result.generation = request.generation;
        result.width = image.width();
        result.height = image.height();
        result.stride = image.bytesPerLine();
        result.render_ms = std::chrono::duration<double, std::milli>(finished - active_started).count();
        const auto* bytes = image.constBits();
        result.rgba.assign(bytes, bytes + image.sizeInBytes());

        const bool superseded = discard_active_result || pending_snapshot.has_value()
            || pending_request.has_value();
        active_job.reset();
        active_request.reset();
        discard_active_result = false;
        if (!superseded) completed = std::move(result);

        if (pending_snapshot) {
            auto snapshot = std::move(*pending_snapshot);
            pending_snapshot.reset();
            apply_snapshot(std::move(snapshot.layers), std::move(snapshot.project_crs));
        }
        if (pending_request) {
            const Request newest = *pending_request;
            pending_request.reset();
            start(newest);
        }
    }

    void wait_for_active_job() {
        if (!active_job) return;
        active_job->cancelWithoutBlocking();
        active_job->waitForFinished();
        active_job.reset();
        active_request.reset();
        pending_request.reset();
        pending_snapshot.reset();
        completed.reset();
        discard_active_result = false;
    }
};

QgisRenderBridge::QgisRenderBridge() : impl_(std::make_unique<Impl>()) {}

QgisRenderBridge::~QgisRenderBridge() {
    try {
        shutdown();
    } catch (...) {
        // A destructor must not surface QGIS shutdown errors through Python teardown.
    }
}

void QgisRenderBridge::initialize(const std::string& requested_prefix) {
    if (impl_->initialized) return;
    if (QCoreApplication::instance() == nullptr) {
        throw std::runtime_error("QGIS renderer requires an existing Qt application");
    }

    std::string prefix = requested_prefix;
    if (prefix.empty()) {
        if (const char* env_prefix = std::getenv("QGIS_PREFIX_PATH")) prefix = env_prefix;
    }
    if (prefix.empty()) prefix = PALEO_QGIS_PREFIX_PATH;
    if (prefix.empty()) {
        throw std::runtime_error("QGIS_PREFIX_PATH is required to initialize the renderer");
    }

    std::lock_guard<std::mutex> lock(g_qgis_lifecycle_mutex);
    if (!g_qgis_initialized) {
        QgsApplication::setPrefixPath(QString::fromStdString(prefix), true);
        QgsApplication::init();
        QgsApplication::initQgis();
        g_qgis_initialized = true;
    }
    ++g_qgis_bridge_count;
    impl_->initialized = true;
}

void QgisRenderBridge::set_layer_snapshot(std::vector<VectorLayerSpec> layers,
                                          std::string project_crs) {
    if (!impl_->initialized) throw std::runtime_error("QGIS renderer is not initialized");
    impl_->finish_active_if_done();
    if (impl_->active_job) {
        impl_->discard_active_result = true;
        impl_->pending_snapshot = Impl::SnapshotInput{std::move(layers), std::move(project_crs)};
        return;
    }
    impl_->apply_snapshot(std::move(layers), std::move(project_crs));
}

void QgisRenderBridge::request_render(const std::array<double, 4>& extent, const int width,
                                      const int height, const double dpi,
                                      const std::uint64_t generation) {
    if (!impl_->initialized) throw std::runtime_error("QGIS renderer is not initialized");
    validate_request(width, height, dpi);
    const Impl::Request request{extent, width, height, dpi, generation};
    impl_->finish_active_if_done();
    impl_->completed.reset();
    if (impl_->active_job) {
        impl_->pending_request = request;
        impl_->discard_active_result = true;
        impl_->active_job->cancelWithoutBlocking();
        return;
    }
    if (impl_->pending_snapshot) {
        auto snapshot = std::move(*impl_->pending_snapshot);
        impl_->pending_snapshot.reset();
        impl_->apply_snapshot(std::move(snapshot.layers), std::move(snapshot.project_crs));
    }
    impl_->start(request);
}

std::optional<RenderResult> QgisRenderBridge::take_completed_frame() {
    if (!impl_->initialized) throw std::runtime_error("QGIS renderer is not initialized");
    impl_->finish_active_if_done();
    auto result = std::move(impl_->completed);
    impl_->completed.reset();
    return result;
}

void QgisRenderBridge::cancel_render() {
    if (!impl_ || !impl_->initialized) return;
    impl_->completed.reset();
    impl_->pending_request.reset();
    if (impl_->active_job) {
        impl_->discard_active_result = true;
        impl_->active_job->cancelWithoutBlocking();
    }
    impl_->finish_active_if_done();
}

bool QgisRenderBridge::render_active() const noexcept {
    return impl_ && impl_->active_job && impl_->active_job->isActive();
}

RenderResult QgisRenderBridge::render_sync(const std::array<double, 4>& extent,
                                            const int width, const int height,
                                            const double dpi) const {
    if (!impl_->initialized) throw std::runtime_error("QGIS renderer is not initialized");
    if (impl_->active_job) {
        throw std::runtime_error("cannot synchronously render while an asynchronous QGIS job is active");
    }
    validate_request(width, height, dpi);
    const Impl::Request request{extent, width, height, dpi, 0};
    const auto started = std::chrono::steady_clock::now();
    QgsMapRendererParallelJob job(impl_->settings_for(request));
    job.start();
    job.waitForFinished();
    const QImage image = job.renderedImage().convertToFormat(QImage::Format_RGBA8888);
    const auto finished = std::chrono::steady_clock::now();
    RenderResult result;
    result.width = image.width();
    result.height = image.height();
    result.stride = image.bytesPerLine();
    result.render_ms = std::chrono::duration<double, std::milli>(finished - started).count();
    const auto* bytes = image.constBits();
    result.rgba.assign(bytes, bytes + image.sizeInBytes());
    return result;
}

void QgisRenderBridge::shutdown() {
    if (!impl_ || !impl_->initialized) return;
    impl_->wait_for_active_job();
    impl_->mirrors.clear();
    impl_->ordered_ids.clear();
    std::lock_guard<std::mutex> lock(g_qgis_lifecycle_mutex);
    if (g_qgis_bridge_count > 0) --g_qgis_bridge_count;
    // QGIS is process-global, like QApplication. QGIS 4.2 is not safely
    // re-initializable after exitQgis() inside a running PySide host, so bridge
    // shutdown releases all bridge-owned objects but intentionally retains the
    // initialized process runtime until application termination.
    impl_->initialized = false;
}

bool QgisRenderBridge::initialized() const noexcept { return impl_->initialized; }

std::string QgisRenderBridge::version() const { return _QGIS_VERSION; }

}  // namespace pwb::qgis_render
