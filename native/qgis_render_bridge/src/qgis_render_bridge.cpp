#include "qgis_render_bridge.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <mutex>
#include <stdexcept>
#include <unordered_map>
#include <utility>

#include <QCoreApplication>
#include <QDomDocument>
#include <QFile>
#include <QFont>
#include <QImage>
#include <QList>
#include <QMarginsF>
#include <QPageSize>
#include <QPdfWriter>
#include <QPainter>
#include <QRect>
#include <QSet>
#include <QSize>
#include <QString>
#include <QSvgGenerator>
#include <QVariantMap>

#include <qgsapplication.h>
#include <qgscoordinatereferencesystem.h>
#include <qgsfield.h>
#include <qgsfeature.h>
#include <qgsgeometry.h>
#include <qgslabeling.h>
#include <qgsmaplayer.h>
#include <qgsmaprendererparalleljob.h>
#include <qgsmaprenderercustompainterjob.h>
#include <qgsmapsettings.h>
#include <qgspallabeling.h>
#include <qgsreadwritecontext.h>
#include <qgsrectangle.h>
#include <qgsrasterlayer.h>
#include <qgsrendercontext.h>
#include <qgstextbuffersettings.h>
#include <qgstextformat.h>
#include <qgsvectordataprovider.h>
#include <qgsvectorlayer.h>
#include <qgsvectorlayerlabeling.h>

#include "style_codec.hpp"

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

/// Scale visibility (#929): VectorStyle.scale_range as 1:denominator bounds,
/// matching the fallback renderer's semantics. 0 disables a bound.
void apply_scale_range(QgsMapLayer& layer, const VectorLayerSpec& spec) {
    if (!spec.has_scale_range) {
        layer.setScaleBasedVisibility(false);
        return;
    }
    // QGIS semantics: minimumScale = the MOST zoomed-out bound (largest
    // denominator), maximumScale = most zoomed-in. VectorStyle.scale_range is
    // (min_denominator, max_denominator) with the same meaning.
    layer.setMinimumScale(spec.scale_range_max_denom);
    layer.setMaximumScale(spec.scale_range_min_denom);
    layer.setScaleBasedVisibility(true);
}

/// Pre-flight the style payloads of a spec WITHOUT touching any layer
/// (#929/#519 residual): mirrors that survive a failed snapshot update must
/// not keep half-applied styles. Mirrors apply_renderer_style's parse steps.
void validate_style_payloads(const VectorLayerSpec& spec) {
    if (!spec.renderer_xml.empty()) {
        auto renderer = renderer_from_xml(spec.renderer_xml);
        if (!renderer) {
            throw std::runtime_error("invalid QGIS renderer payload for layer " + spec.id);
        }
    }
    if (!spec.labeling_xml.empty()) {
        QDomDocument document;
        if (!document.setContent(QString::fromStdString(spec.labeling_xml))) {
            throw std::runtime_error("invalid QGIS labeling payload for layer " + spec.id);
        }
        const QDomElement element = document.firstChildElement();
        if (element.isNull()) {
            throw std::runtime_error("empty QGIS labeling payload for layer " + spec.id);
        }
        QgsReadWriteContext context;
        auto labeling = std::unique_ptr<QgsAbstractVectorLayerLabeling>(
            QgsAbstractVectorLayerLabeling::create(element, context)
        );
        if (!labeling) {
            throw std::runtime_error("QGIS labeling payload could not be parsed for layer " + spec.id);
        }
    }
}

void apply_renderer_style(QgsVectorLayer& layer, const VectorLayerSpec& spec) {    const Qgis::GeometryType geometry_type = layer.geometryType();
    if (geometry_type == Qgis::GeometryType::Null) return;
    // Authoritative path: a stored QGIS renderer payload owns the full
    // symbol-layer tree.  The legacy flat fields only build renderers when no
    // payload exists yet (legacy projects, minimal fallbacks).
    if (!spec.renderer_xml.empty()) {
        auto renderer = renderer_from_xml(spec.renderer_xml);
        if (!renderer) {
            throw std::runtime_error("invalid QGIS renderer payload for layer " + spec.id);
        }
        layer.setRenderer(renderer.release());
        return;
    }
    auto renderer = build_renderer_from_spec(geometry_type, spec);
    if (renderer) layer.setRenderer(renderer.release());
}

void apply_label_style(QgsVectorLayer& layer, const VectorLayerSpec& spec) {
    if (!spec.labeling_xml.empty()) {
        QDomDocument document;
        if (!document.setContent(QString::fromStdString(spec.labeling_xml))) {
            throw std::runtime_error("invalid QGIS labeling payload for layer " + spec.id);
        }
        QDomElement element = document.firstChildElement();
        if (element.isNull()) {
            throw std::runtime_error("empty QGIS labeling payload for layer " + spec.id);
        }
        QgsReadWriteContext context;
        auto labeling = std::unique_ptr<QgsAbstractVectorLayerLabeling>(
            QgsAbstractVectorLayerLabeling::create(element, context)
        );
        if (!labeling) {
            throw std::runtime_error("QGIS labeling payload could not be parsed for layer " + spec.id);
        }
        layer.setLabeling(labeling.release());
        layer.setLabelsEnabled(true);
        return;
    }
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

    Diagnostics diagnostics;

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
        // #929 (#519 residual): style application to REUSED mirrors mutates
        // live layers.  Validate every pending style payload up front so a
        // bad snapshot cannot leave half-applied styles behind on mirrors
        // that stay live when the update throws.
        for (const VectorLayerSpec& spec : layers) {
            auto existing = mirrors.find(spec.id);
            if (existing == mirrors.end()) continue;
            const bool rebuild = existing->second.data_revision != spec.data_revision
                || (spec.kind == VectorLayerSpec::Kind::Raster
                    && existing->second.style_revision != spec.style_revision)
                || existing->second.kind != spec.kind
                || existing->second.source_path != spec.source_path;
            if (!rebuild && spec.kind == VectorLayerSpec::Kind::Vector
                && existing->second.style_revision != spec.style_revision) {
                validate_style_payloads(spec);
            }
        }
        std::unordered_map<std::string, Mirror> next;
        std::vector<std::string> order;
        std::vector<std::string> reused;
        for (VectorLayerSpec& spec : layers) {
            if (spec.id.empty()) throw std::invalid_argument("QGIS vector layer id is required");
            auto existing = mirrors.find(spec.id);
            const bool rebuild = existing == mirrors.end()
                || existing->second.data_revision != spec.data_revision
                // Vector style can be reapplied to its existing memory layer;
                // retain the former conservative behavior for raster styles.
                || (spec.kind == VectorLayerSpec::Kind::Raster
                    && existing->second.style_revision != spec.style_revision)
                || existing->second.kind != spec.kind
                || existing->second.source_path != spec.source_path;

            if (!rebuild) {
                // Keep the live mirror in `mirrors` until the whole snapshot
                // validates.  A throw later in the loop must not leave the
                // registry holding a moved-from (null) layer that settings_for
                // would hand to QGIS, and must not delete the previously valid
                // layers (#519).
                Mirror& mirror = existing->second;
                if (spec.kind == VectorLayerSpec::Kind::Vector
                    && mirror.style_revision != spec.style_revision) {
                    auto* vector_layer = dynamic_cast<QgsVectorLayer*>(mirror.layer.get());
                    if (vector_layer == nullptr) {
                        throw std::runtime_error("QGIS vector mirror has an unexpected layer type");
                    }
                    apply_renderer_style(*vector_layer, spec);
                    apply_label_style(*vector_layer, spec);
                    diagnostics.style_reapplies += 1;
                }
                mirror.data_revision = spec.data_revision;
                mirror.style_revision = spec.style_revision;
                mirror.kind = spec.kind;
                mirror.source_path = spec.source_path;
                mirror.visible = spec.visible;
                mirror.layer->setOpacity(std::clamp(spec.opacity, 0.0, 1.0));
                apply_scale_range(*mirror.layer, spec);
                reused.push_back(spec.id);
                diagnostics.mirror_reuses += 1;
            } else {
                Mirror mirror;
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
                mirror.data_revision = spec.data_revision;
                mirror.style_revision = spec.style_revision;
                mirror.kind = spec.kind;
                mirror.source_path = spec.source_path;
                mirror.visible = spec.visible;
                mirror.layer->setOpacity(std::clamp(spec.opacity, 0.0, 1.0));
                apply_scale_range(*mirror.layer, spec);
                next.emplace(spec.id, std::move(mirror));
                diagnostics.mirror_builds += 1;
            }
            order.push_back(spec.id);
        }
        // Every layer validated: move the reused mirrors out of the live map.
        for (const std::string& id : reused) {
            auto it = mirrors.find(id);
            if (it != mirrors.end()) {
                next.emplace(id, std::move(it->second));
            }
        }
        mirrors = std::move(next);
        ordered_ids = std::move(order);
        project_crs = std::move(destination_crs);
    }

    [[nodiscard]] QgsMapSettings settings_for(const Request& request) const {
        QgsMapSettings settings;
        QList<QgsMapLayer*> layers;
        // Host snapshots order layers bottom-to-top; QGIS renders its layer
        // list in reverse (last entry first). Reverse here so screen frames
        // compose exactly like the fallback pipeline (#519 contract).
        for (auto it = ordered_ids.rbegin(); it != ordered_ids.rend(); ++it) {
            const auto mirror = mirrors.find(*it);
            // The deferred-commit apply_snapshot guarantees non-null layers;
            // skip defensively so a null can never reach QGIS (#519).
            if (mirror != mirrors.end() && mirror->second.visible && mirror->second.layer) {
                layers.append(mirror->second.layer.get());
            }
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
        const bool superseded = discard_active_result || pending_snapshot.has_value()
            || pending_request.has_value();
        std::optional<RenderResult> result;
        if (!superseded) {
            const QImage image = active_job->renderedImage().convertToFormat(QImage::Format_RGBA8888);
            RenderResult completed_result;
            completed_result.generation = request.generation;
            completed_result.width = image.width();
            completed_result.height = image.height();
            completed_result.stride = image.bytesPerLine();
            completed_result.render_ms = std::chrono::duration<double, std::milli>(finished - active_started).count();
            const auto* bytes = image.constBits();
            completed_result.rgba.assign(bytes, bytes + image.sizeInBytes());
            result = std::move(completed_result);
        }
        active_job.reset();
        active_request.reset();
        discard_active_result = false;
        if (result) completed = std::move(*result);

        if (pending_snapshot) {
            auto snapshot = std::move(*pending_snapshot);
            pending_snapshot.reset();
            try {
                apply_snapshot(std::move(snapshot.layers), std::move(snapshot.project_crs));
            } catch (...) {
                // A failed snapshot invalidates any render queued against it:
                // keeping pending_request would make the next completed render
                // look superseded and silently discard its frame (#519).
                pending_request.reset();
                throw;
            }
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

std::size_t QgisRenderBridge::export_vector(const std::string& path,
                                             const std::string& format,
                                             const std::array<double, 4>& extent,
                                             const int width, const int height,
                                             const double dpi) const {
    if (!impl_->initialized) throw std::runtime_error("QGIS renderer is not initialized");
    if (path.empty()) throw std::invalid_argument("export path is required");
    if (format != "svg" && format != "pdf") {
        throw std::invalid_argument("unsupported export format (svg or pdf)");
    }
    validate_request(width, height, dpi);
    if (impl_->active_job) {
        throw std::runtime_error("cannot export while an asynchronous QGIS job is active");
    }

    QgsMapSettings settings = impl_->settings_for(
        Impl::Request{extent, width, height, dpi, 0}
    );

    std::unique_ptr<QPaintDevice> device;
    if (format == "svg") {
        auto generator = std::make_unique<QSvgGenerator>();
        generator->setFileName(QString::fromStdString(path));
        generator->setSize(QSize(width, height));
        generator->setViewBox(QRect(0, 0, width, height));
        generator->setResolution(static_cast<int>(std::lround(dpi)));
        device = std::move(generator);
    } else {
        auto writer = std::make_unique<QPdfWriter>(QString::fromStdString(path));
        writer->setResolution(static_cast<int>(std::lround(dpi)));
        const QSizeF page_mm(width / dpi * 25.4, height / dpi * 25.4);
        writer->setPageSize(QPageSize(page_mm, QPageSize::Unit::Millimeter));
        writer->setPageMargins(QMarginsF(0, 0, 0, 0));
        device = std::move(writer);
    }

    QPainter painter(device.get());
    if (!painter.isActive()) {
        throw std::runtime_error("could not begin QGIS vector export");
    }
    try {
        painter.setRenderHint(QPainter::RenderHint::Antialiasing, true);
        settings.setFlag(Qgis::MapSettingsFlag::DrawLabeling, true);
        settings.setOutputSize(QSize(width, height));
        settings.setOutputDpi(dpi);
        QgsMapRendererCustomPainterJob job(settings, &painter);
        // Synchronous export: the caller owns completion semantics and the
        // file must be complete before this call returns.
        job.renderSynchronously();
    } catch (...) {
        painter.end();
        throw;
    }
    painter.end();

    QFile output(QString::fromStdString(path));
    return output.exists() ? static_cast<std::size_t>(output.size()) : 0;
}

bool QgisRenderBridge::initialized() const noexcept { return impl_->initialized; }

std::string QgisRenderBridge::version() const { return _QGIS_VERSION; }

QgisRenderBridge::Diagnostics QgisRenderBridge::diagnostics() const {
    return impl_->diagnostics;
}

}  // namespace pwb::qgis_render
