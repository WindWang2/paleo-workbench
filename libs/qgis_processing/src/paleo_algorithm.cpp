#include <pwb/qgis_processing/paleo_algorithm.hpp>

#include <QPointer>

#include <qgsexception.h>
#include <qgsfeedback.h>
#include <qgsprocessingcontext.h>

#include <pwb/qgis_processing/grid_io.hpp>

namespace pwb::qgis_processing {

PaleoAlgorithm::PointTable PaleoAlgorithm::read_point_table(
    const QVariantMap& parameters, QgsProcessingContext& context,
    QgsProcessingFeedback* feedback) const {
    PointTable table;
    std::unique_ptr<QgsProcessingFeatureSource> source(parameterAsSource(
        parameters, QStringLiteral("INPUT"), context));
    QString error;
    table.points = read_sample_points(
        source.get(),
        parameterAsString(parameters, QStringLiteral("XFIELD"), context),
        parameterAsString(parameters, QStringLiteral("YFIELD"), context),
        parameterAsString(parameters, QStringLiteral("VALUEFIELD"), context), feedback,
        error);
    if (!error.isEmpty()) {
        throw QgsProcessingException(
            QStringLiteral("INPUT: %1").arg(error));
    }
    if (table.points.empty()) {
        throw QgsProcessingException(
            QStringLiteral(
                "INPUT has no usable sample points (need finite x/y/value)"));
    }
    table.crs = parameterAsCrs(parameters, QStringLiteral("CRS"), context);
    return table;
}

Qgis::ProcessingAlgorithmFlags PaleoAlgorithm::flags() const {
    // Deterministic, batch-capable, cancellable — the paleo product default.
    return Qgis::ProcessingAlgorithmFlag::SupportsBatch |
           Qgis::ProcessingAlgorithmFlag::CanCancel;
}

pwb::science::ProgressSink PaleoAlgorithm::progress_sink(
    QgsProcessingFeedback* feedback, double scale, double offset) {
    // QPointer guards against feedback destruction racing a late progress
    // report from a kernel that ignores cancellation.
    QPointer<QgsProcessingFeedback> guarded(feedback);
    return [guarded, scale, offset](const pwb::science::ProgressReport& report) {
        QgsProcessingFeedback* fb = guarded.data();
        if (fb == nullptr) return;
        const double clamped = report.fraction < 0.0
                                   ? 0.0
                                   : (report.fraction > 1.0 ? 1.0 : report.fraction);
        if (!report.stage.empty()) fb->setProgressText(QString::fromStdString(report.stage));
        fb->setProgress(100.0 * (offset + scale * clamped));
    };
}

std::pair<std::stop_source, std::shared_ptr<void>> PaleoAlgorithm::cancel_bridge(
    QgsProcessingFeedback* feedback) {
    auto source = std::make_shared<std::stop_source>();
    // DirectConnection: request_stop() is an atomic, so running it on the
    // cancelling thread is safe and immediate (no event-loop hop that a
    // worker-thread feedback would never serve).
    QMetaObject::Connection connection = QObject::connect(
        feedback, &QgsFeedback::canceled, feedback,
        [source]() { source->request_stop(); }, Qt::DirectConnection);
    // Opaque holder that breaks the connection when released.
    auto holder = std::shared_ptr<void>(nullptr, [feedback, connection](void*) {
        if (feedback != nullptr) QObject::disconnect(connection);
    });
    return {std::move(*source), std::move(holder)};
}

bool PaleoAlgorithm::run_science_algorithm(
    pwb::science::IAlgorithm& algorithm,
    const pwb::science::AlgorithmRequestV1& request,
    QgsProcessingFeedback* feedback,
    pwb::science::AlgorithmResultV1& out_result,
    QString& out_error) {
    auto [source, guard] = cancel_bridge(feedback);
    auto result = algorithm.run(request, progress_sink(feedback), source.get_token());
    if (result.has_value()) {
        out_result = std::move(result.value());
        return true;
    }
    if (result.is_cancelled()) return false;
    std::string message = "algorithm '" + algorithm.descriptor().algorithm_id + "' failed";
    for (const auto& diagnostic : result.error().diagnostics) {
        message += "\n[" + diagnostic.code + "] " + diagnostic.message;
    }
    out_error = QString::fromStdString(message);
    return false;
}

void PaleoAlgorithm::throw_processing_error(const std::string& what) {
    throw QgsProcessingException(QString::fromStdString(what));
}

}  // namespace pwb::qgis_processing
