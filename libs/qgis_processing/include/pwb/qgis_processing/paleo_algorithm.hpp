#pragma once

// Paleo algorithm base for QGIS Processing.
//
// Contract (docs/development/qgis-native-processing-convergence/07):
//   * QgsProcessingAlgorithm subclasses here are context/parameter/feedback
//     adapters ONLY — the science stays in the Qt-free Paleo kernels;
//   * progress flows through QgsProcessingFeedback (optionally
//     QgsProcessingMultiStepFeedback for staged kernels);
//   * cancellation: kernels that accept a stop vocabulary get a bridge;
//     pure kernels are cancellable between stages only;
//   * provenance is recorded by the CALLER after completion (catalog rail);
//     processAlgorithm itself stays re-runnable and side-effect-free
//     apart from its declared outputs.

#include <memory>
#include <stop_token>
#include <string>
#include <utility>
#include <vector>

#include <qgsprocessingalgorithm.h>
#include <qgsprocessingfeedback.h>
#include <qgsprocessingparameters.h>

#include <pwb/mapping/interpolator.hpp>
#include <pwb/science/algorithm.hpp>

class QgsCoordinateReferenceSystem;
class QgsProcessingContext;

namespace pwb::qgis_processing {

// Shared base: provider tag + helpers common to every paleo algorithm.
class PaleoAlgorithm : public QgsProcessingAlgorithm {
public:
    // All paleo algorithms are deterministic, batch-capable, cancellable
    // (between stages at minimum) and live in the provider's flag default.
    Qgis::ProcessingAlgorithmFlags flags() const override;

    QString providerId() const { return QStringLiteral("paleo"); }

    // Point-table inputs (x/y/value fields over a feature source), shared
    // by the interpolation / factor / facies families.
    struct PointTable {
        std::vector<pwb::mapping::SamplePoint> points;
        QgsCoordinateReferenceSystem crs;
    };

protected:
    // Reads INPUT (FeatureSource) + XFIELD/YFIELD/VALUEFIELD + CRS into
    // kernel sample points; throws QgsProcessingException on bad input.
    [[nodiscard]] PointTable read_point_table(const QVariantMap& parameters,
                                              QgsProcessingContext& context,
                                              QgsProcessingFeedback* feedback) const;

    // Standard parameter scaffold for the point-table algorithms.
    template <typename Add>
    static void add_point_table_params(Add&& add) {
        add(std::make_unique<QgsProcessingParameterFeatureSource>(
            QStringLiteral("INPUT"), QStringLiteral("Sample points"),
            QList<int>()
                << static_cast<int>(Qgis::ProcessingSourceType::VectorPoint)));
        add(std::make_unique<QgsProcessingParameterField>(
            QStringLiteral("XFIELD"), QStringLiteral("X field"), QVariant(),
            QStringLiteral("INPUT")));
        add(std::make_unique<QgsProcessingParameterField>(
            QStringLiteral("YFIELD"), QStringLiteral("Y field"), QVariant(),
            QStringLiteral("INPUT")));
        add(std::make_unique<QgsProcessingParameterField>(
            QStringLiteral("VALUEFIELD"), QStringLiteral("Value field"), QVariant(),
            QStringLiteral("INPUT")));
        add(std::make_unique<QgsProcessingParameterCrs>(
            QStringLiteral("CRS"), QStringLiteral("Target CRS"), QVariant()));
        add(std::make_unique<QgsProcessingParameterRasterDestination>(
            QStringLiteral("OUTPUT"), QStringLiteral("Interpolated grid")));
    }
    // Bridges a Processing feedback into the Qt-free kernel vocabulary.
    // Thread note: processAlgorithm runs on a worker thread while feedback
    // is owned by the submitter; QgsFeedback::setProgress/progressText are
    // used cross-thread by QGIS' own task bridge, so the same contract
    // applies here.
    [[nodiscard]] static pwb::science::ProgressSink progress_sink(
        QgsProcessingFeedback* feedback, double scale = 1.0, double offset = 0.0);

    // Cancel-aware stop_source bridge: feedback->canceled() (fired on
    // cancel() from any thread) requests a stop that kernels observing a
    // stop_token can see at their next safe point. The returned source must
    // outlive the kernel call.
    [[nodiscard]] static std::pair<std::stop_source, std::shared_ptr<void>>
    cancel_bridge(QgsProcessingFeedback* feedback);

    // Convenience: run a pwb::science IAlgorithm with feedback + cancel
    // bridged; throws QgsProcessingException on error, returns cancelled
    // state as false so the caller can terminate the algorithm cleanly.
    [[nodiscard]] static bool run_science_algorithm(
        pwb::science::IAlgorithm& algorithm,
        const pwb::science::AlgorithmRequestV1& request,
        QgsProcessingFeedback* feedback,
        pwb::science::AlgorithmResultV1& out_result,
        QString& out_error);

    [[noreturn]] static void throw_processing_error(const std::string& what);
};

// QString helper for kernel messages (kernels are UTF-8 std::string).
[[nodiscard]] inline QString to_qs(const std::string& s) {
    return QString::fromStdString(s);
}

}  // namespace pwb::qgis_processing
