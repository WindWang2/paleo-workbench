#include "qgis_render_bridge.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <mutex>
#include <stdexcept>
#include <unordered_map>
#include <utility>

#include <QCoreApplication>
#include <QFont>
#include <QImage>
#include <QList>
#include <QSet>
#include <QSize>
#include <QString>
#include <QVariantMap>

#include <qgsapplication.h>
#include <qgscategorizedsymbolrenderer.h>
#include <qgscoordinatereferencesystem.h>
#include <qgsfield.h>
#include <qgsfeature.h>
#include <qgsfillsymbol.h>
#include <qgsgraduatedsymbolrenderer.h>
#include <qgsgeometry.h>
#include <qgslinesymbol.h>
#include <qgsmaplayer.h>
#include <qgsmaprendererparalleljob.h>
#include <qgsmapsettings.h>
#include <qgsrectangle.h>
#include <qgsrasterlayer.h>
#include <qgsmarkersymbol.h>
#include <qgspallabeling.h>
#include <qgsrendererrange.h>
#include <qgssinglesymbolrenderer.h>
#include <qgssymbol.h>
#include <qgstextbuffersettings.h>
#include <qgstextformat.h>
#include <qgsvectordataprovider.h>
#include <qgsvectorlayer.h>
#include <qgsvectorlayerlabeling.h>

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

std::unique_ptr<QgsSymbol> symbol_for(const Qgis::GeometryType geometry_type,
                                      const VectorLayerSpec& spec,
                                      const QString& requested_fill = {}) {
    const QString fill = requested_fill.isEmpty() ? QString::fromStdString(spec.fill) : requested_fill;
    const QString stroke = QString::fromStdString(spec.stroke);
    const QString width = QString::number(std::max(0.0, spec.stroke_width), 'g', 12);
    const QString marker_size = QString::number(std::max(0.1, spec.marker_size), 'g', 12);
    QVariantMap properties;
    switch (geometry_type) {
        case Qgis::GeometryType::Polygon: {
            properties.insert(QStringLiteral("color"), fill);
            properties.insert(QStringLiteral("outline_color"), stroke);
            properties.insert(QStringLiteral("outline_width"), width);
            return QgsFillSymbol::createSimple(properties);
        }
        case Qgis::GeometryType::Line: {
            properties.insert(QStringLiteral("line_color"), stroke);
            properties.insert(QStringLiteral("color"), stroke);
            properties.insert(QStringLiteral("line_width"), width);
            properties.insert(QStringLiteral("width"), width);
            return QgsLineSymbol::createSimple(properties);
        }
        case Qgis::GeometryType::Point: {
            properties.insert(QStringLiteral("color"), fill);
            properties.insert(QStringLiteral("outline_color"), stroke);
            properties.insert(QStringLiteral("size"), marker_size);
            return QgsMarkerSymbol::createSimple(properties);
        }
        default:
            return {};
    }
}

void apply_renderer_style(QgsVectorLayer& layer, const VectorLayerSpec& spec) {
    const Qgis::GeometryType geometry_type = layer.geometryType();
    if (geometry_type == Qgis::GeometryType::Null) return;
    if (spec.renderer_kind == "categorized" && !spec.classification_field.empty()
        && !spec.categories.empty()) {
        QgsCategoryList categories;
        for (const CategorySpec& category : spec.categories) {
            auto symbol = symbol_for(geometry_type, spec, QString::fromStdString(category.color));
            if (symbol) {
                categories.emplace_back(
                    QVariant(QString::fromStdString(category.value)), symbol.release(),
                    QString::fromStdString(category.label)
                );
            }
        }
        layer.setRenderer(new QgsCategorizedSymbolRenderer(
            QString::fromStdString(spec.classification_field), categories
        ));
        return;
    }
    if (spec.renderer_kind == "graduated" && !spec.classification_field.empty()
        && !spec.ranges.empty()) {
        QgsRangeList ranges;
        for (const RangeSpec& range : spec.ranges) {
            auto symbol = symbol_for(geometry_type, spec, QString::fromStdString(range.color));
            if (symbol) {
                ranges.emplace_back(
                    range.lower, range.upper, symbol.release(),
                    QString::fromStdString(range.label)
                );
            }
        }
        layer.setRenderer(new QgsGraduatedSymbolRenderer(
            QString::fromStdString(spec.classification_field), ranges
        ));
        return;
    }
    auto symbol = symbol_for(geometry_type, spec);
    if (symbol) layer.setRenderer(new QgsSingleSymbolRenderer(symbol.release()));
}

void apply_label_style(QgsVectorLayer& layer, const VectorLayerSpec& spec) {
    if (!spec.labels_enabled || spec.label_field.empty()) {
        layer.setLabelsEnabled(false);
        return;
    }
    QgsPalLayerSettings settings;
    settings.fieldName = QString::fromStdString(spec.label_field);
    settings.isExpression = false;
    QgsTextFormat format;
    QFont font;
    if (!spec.label_font_family.empty()) font.setFamily(QString::fromStdString(spec.label_font_family));
    format.setFont(font);
    format.setSize(std::max(0.1, spec.label_size));
    format.setColor(QColor(QString::fromStdString(spec.label_color)));
    if (spec.label_buffer_size > 0.0) {
        QgsTextBufferSettings buffer;
        buffer.setEnabled(true);
        buffer.setSize(spec.label_buffer_size);
        buffer.setColor(Qt::white);
        format.setBuffer(buffer);
    }
    settings.setFormat(format);
    layer.setLabeling(new QgsVectorLayerSimpleLabeling(settings));
    layer.setLabelsEnabled(true);
}

}  // namespace

class QgisRenderBridge::Impl {
  public:
    struct Mirror {
        std::uint64_t data_revision = 0;
        std::uint64_t style_revision = 0;
        VectorLayerSpec::Kind kind = VectorLayerSpec::Kind::Vector;
        std::string source_path;
        bool visible = true;
        std::unique_ptr<QgsMapLayer> layer;
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
                || existing->second.style_revision != spec.style_revision
                || existing->second.kind != spec.kind
                || existing->second.source_path != spec.source_path;

            Mirror mirror;
            if (!rebuild) {
                mirror = std::move(existing->second);
            } else {
                if (spec.kind == VectorLayerSpec::Kind::Raster) {
                    mirror.layer = std::make_unique<QgsRasterLayer>(
                        QString::fromStdString(spec.source_path),
                        QString::fromStdString(spec.name),
                        QStringLiteral("gdal")
                    );
                    if (!mirror.layer->isValid()) {
                        throw std::runtime_error("QGIS could not open raster layer " + spec.id);
                    }
                } else {
                    const QString geometry_uri = geometry_uri_for(spec);
                    const QString uri = QStringLiteral("%1?crs=%2")
                                            .arg(geometry_uri, QString::fromStdString(spec.crs));
                    auto vector_layer = std::make_unique<QgsVectorLayer>(
                        uri, QString::fromStdString(spec.name), QStringLiteral("memory")
                    );
                    if (!vector_layer->isValid()) {
                        throw std::runtime_error("QGIS could not create memory layer " + spec.id);
                    }
                    QSet<QString> attribute_names;
                    attribute_names.insert(QStringLiteral("__pwb_id"));
                    for (const FeatureSpec& feature_spec : spec.features) {
                        for (const auto& attribute : feature_spec.attributes) {
                            attribute_names.insert(QString::fromStdString(attribute.first));
                        }
                    }
                    QList<QgsField> fields;
                    for (const QString& attribute_name : attribute_names) {
                        fields.append(QgsField(attribute_name, QMetaType::Type::QString));
                    }
                    if (!fields.empty() && !vector_layer->dataProvider()->addAttributes(fields)) {
                        throw std::runtime_error("QGIS could not create fields for layer " + spec.id);
                    }
                    vector_layer->updateFields();
                    QgsFeatureList features;
                    for (const FeatureSpec& feature_spec : spec.features) {
                        QgsGeometry geometry = QgsGeometry::fromWkt(QString::fromStdString(feature_spec.wkt));
                        if (geometry.isNull()) {
                            throw std::invalid_argument("invalid WKT for QGIS layer " + spec.id);
                        }
                        QgsFeature feature(vector_layer->fields());
                        feature.setGeometry(std::move(geometry));
                        feature.setAttribute(QStringLiteral("__pwb_id"), QString::fromStdString(feature_spec.id));
                        for (const auto& attribute : feature_spec.attributes) {
                            feature.setAttribute(
                                QString::fromStdString(attribute.first),
                                QString::fromStdString(attribute.second)
                            );
                        }
                        features.push_back(std::move(feature));
                    }
                    if (!features.empty() && !vector_layer->dataProvider()->addFeatures(features)) {
                        throw std::runtime_error("QGIS could not add features for layer " + spec.id);
                    }
                    vector_layer->updateExtents();
                    apply_renderer_style(*vector_layer, spec);
                    apply_label_style(*vector_layer, spec);
                    mirror.layer = std::move(vector_layer);
                }
            }
            mirror.data_revision = spec.data_revision;
            mirror.style_revision = spec.style_revision;
            mirror.kind = spec.kind;
            mirror.source_path = spec.source_path;
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

    const std::string prefix = PALEO_QGIS_PREFIX_PATH;
    if (prefix.empty()) throw std::runtime_error("vendored QGIS prefix is not configured");
    if (!requested_prefix.empty() && requested_prefix != prefix) {
        throw std::invalid_argument("QGIS renderer only accepts the vendored QGIS prefix");
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
        // Explicit cancellation is used by deterministic export/shutdown paths,
        // where it is safer to wait than to let a stale QGIS job race a sync job.
        impl_->wait_for_active_job();
        return;
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
