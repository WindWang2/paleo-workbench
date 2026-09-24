// Well log science algorithms for QGIS Processing: curve operations over
// two-column depth/value CSVs (pwb::well_science curve_ops dispatch table),
// DTW log matching (well_science/dtw.hpp) and the well-head scatter parser
// (ui_pages_preview well_head_scatter_core). Thin adapters: numerics stay
// in the Qt-free kernels.

#include <QVariant>

#include <qgscoordinatereferencesystem.h>
#include <qgsexception.h>
#include <qgsfeature.h>
#include <qgsfeaturesink.h>
#include <qgsfields.h>
#include <qgsgeometry.h>
#include <qgspointxy.h>
#include <qgsprocessingcontext.h>
#include <qgsprocessingfeedback.h>
#include <qgsprocessingoutputs.h>
#include <qgsprocessingparameters.h>

#include "detail.hpp"

#include <pwb/qgis_processing/algorithm_ids.hpp>
#include <pwb/qgis_processing/paleo_algorithm.hpp>

#include <pwb/ui_pages_preview/well_head_scatter_core.hpp>
#include <pwb/well_science/curve_ops.hpp>
#include <pwb/well_science/dtw.hpp>

#include <cmath>
#include <cstdint>
#include <exception>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace pwb::qgis_processing {

namespace {

// ---- paleo:well_curve_operation ---------------------------------------------

class WellCurveOperationAlgorithm final : public PaleoAlgorithm {
public:
    QString name() const override {
        return QString::fromLatin1(kAlgWellCurveOperation);
    }
    QString displayName() const override {
        return QStringLiteral("Well curve operation");
    }
    QString groupId() const override { return QString::fromLatin1(kGroupWell); }
    QString group() const override { return QStringLiteral("Well"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Applies one curve_interpretation operation (pwb::well_science "
            "dispatch table) to a two-column depth,value CSV. PARAM is the "
            "operation's numeric argument: delta_m for depth_shift, delta for "
            "baseline_shift, window for smooth/median_filter, step for "
            "resample, threshold_sigma for despike (default 3) and the "
            "symmetric percentile band for clip_outliers. Operations needing "
            "string arguments (unit_conversion, depth_unit_normalize, "
            "derive_curve) are not exposed here.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        QStringList operation_names;
        for (const pwb::well_science::CurveOperationInfo& info :
             pwb::well_science::curve_operations()) {
            operation_names << QString::fromLatin1(info.name);
        }
        addParameter(new QgsProcessingParameterFile(
            QStringLiteral("INPUT"), QStringLiteral("Curve CSV (depth,value)"),
            Qgis::ProcessingFileParameterBehavior::File));
        addParameter(new QgsProcessingParameterEnum(
            QStringLiteral("OPERATION"), QStringLiteral("Operation"),
            operation_names));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("PARAM"), QStringLiteral("Operation parameter"),
            Qgis::ProcessingNumberParameterType::Double, QVariant(), true));
        addParameter(new QgsProcessingParameterFileDestination(
            QStringLiteral("OUTPUT"), QStringLiteral("Result CSV"),
            QStringLiteral("CSV files (*.csv)")));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("OUTPUT_POINTS"), QStringLiteral("Output row count")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        QString error;
        const detail::CurveCsv curve = detail::read_curve_csv(
            parameterAsFile(parameters, QStringLiteral("INPUT"), context), error);
        if (!error.isEmpty()) throw QgsProcessingException(error);
        if (curve.depth.empty()) {
            throw QgsProcessingException(
                QStringLiteral("INPUT has no numeric depth,value rows"));
        }

        const std::vector<pwb::well_science::CurveOperationInfo>& operations =
            pwb::well_science::curve_operations();
        const int operation_index = parameterAsEnum(
            parameters, QStringLiteral("OPERATION"), context);
        if (operation_index < 0 ||
            static_cast<std::size_t>(operation_index) >= operations.size()) {
            throw QgsProcessingException(
                QStringLiteral("OPERATION index %1 is out of range")
                    .arg(operation_index));
        }
        const std::string operation_name(
            operations[static_cast<std::size_t>(operation_index)].name);

        const QVariant param_value = parameters.value(QStringLiteral("PARAM"));
        const bool has_param = param_value.isValid() && !param_value.isNull();
        const double param = has_param ? param_value.toDouble() : 0.0;
        auto require_param = [has_param](const char* what) {
            if (!has_param) {
                throw QgsProcessingException(
                    QStringLiteral("%1 requires PARAM").arg(QLatin1String(what)));
            }
        };

        std::vector<double> depth = curve.depth;
        std::vector<double> values = curve.value;
        try {
            if (operation_name == "depth_shift") {
                require_param("depth_shift");
                depth = pwb::well_science::depth_shift(depth, param, "m");
            } else if (operation_name == "despike") {
                values = pwb::well_science::despike(
                    values, has_param ? param : 3.0, /*window=*/3);
            } else if (operation_name == "baseline_shift") {
                require_param("baseline_shift");
                values = pwb::well_science::baseline_shift(values, param);
            } else if (operation_name == "smooth") {
                const int window = has_param
                                       ? std::max(1, static_cast<int>(std::llround(param)))
                                       : 5;
                values = pwb::well_science::moving_average(values, window);
            } else if (operation_name == "median_filter") {
                const int window = has_param
                                       ? std::max(1, static_cast<int>(std::llround(param)))
                                       : 5;
                values = pwb::well_science::median_filter_curve(values, window);
            } else if (operation_name == "normalize") {
                values = pwb::well_science::normalize_curve(values, "zscore");
            } else if (operation_name == "clip_outliers") {
                require_param("clip_outliers");
                values = pwb::well_science::clip_outliers(
                    values, std::nullopt, std::nullopt, param);
            } else if (operation_name == "resample") {
                require_param("resample");
                const std::vector<double> axis =
                    pwb::well_science::resample_axis(depth, param);
                values = pwb::well_science::interp_gap_preserving(
                    axis, depth, values);
                depth = axis;
            } else {
                throw QgsProcessingException(
                    QStringLiteral(
                        "operation '%1' needs string parameters that this "
                        "adapter does not expose; use the well toolbox")
                        .arg(QString::fromStdString(operation_name)));
            }
        } catch (const QgsProcessingException&) {
            throw;
        } catch (const std::exception& kernel_error) {
            throw QgsProcessingException(
                QStringLiteral("%1: %2")
                    .arg(QString::fromStdString(operation_name))
                    .arg(QString::fromStdString(kernel_error.what())));
        }
        if (feedback != nullptr && feedback->isCanceled()) return {};

        const QString output_path = parameterAsOutputLayer(
            parameters, QStringLiteral("OUTPUT"), context);
        if (!detail::write_curve_csv(output_path, depth, values,
                                     QStringLiteral("depth,value"), error)) {
            throw QgsProcessingException(error);
        }

        QVariantMap results;
        results.insert(QStringLiteral("OUTPUT"), output_path);
        results.insert(QStringLiteral("OUTPUT_POINTS"),
                       static_cast<qlonglong>(depth.size()));
        if (feedback != nullptr) feedback->setProgress(100.0);
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new WellCurveOperationAlgorithm();
    }
};

// ---- paleo:well_log_match ------------------------------------------------------

class WellLogMatchAlgorithm final : public PaleoAlgorithm {
public:
    QString name() const override { return QString::fromLatin1(kAlgWellLogMatch); }
    QString displayName() const override {
        return QStringLiteral("DTW well log match");
    }
    QString groupId() const override { return QString::fromLatin1(kGroupWell); }
    QString group() const override { return QStringLiteral("Well"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Optimal non-linear DTW alignment of two logs (two-column "
            "depth,value CSVs, kernel well_science::match_curves). WINDOW is "
            "the Sakoe-Chiba band in samples (0 = unbounded). OUTPUT lists "
            "target_depth,reference_depth per path step and the total "
            "alignment cost.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        addParameter(new QgsProcessingParameterFile(
            QStringLiteral("REFERENCE"), QStringLiteral("Reference curve CSV"),
            Qgis::ProcessingFileParameterBehavior::File));
        addParameter(new QgsProcessingParameterFile(
            QStringLiteral("TARGET"), QStringLiteral("Target curve CSV"),
            Qgis::ProcessingFileParameterBehavior::File));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("WINDOW"), QStringLiteral(
                "Sakoe-Chiba window (samples, 0 = unbounded)"),
            Qgis::ProcessingNumberParameterType::Integer, 100, false, 0));
        addParameter(new QgsProcessingParameterFileDestination(
            QStringLiteral("OUTPUT"), QStringLiteral("Alignment CSV"),
            QStringLiteral("CSV files (*.csv)")));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("MATCH_COUNT"), QStringLiteral("Matched step count")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        QString error;
        const detail::CurveCsv reference = detail::read_curve_csv(
            parameterAsFile(parameters, QStringLiteral("REFERENCE"), context),
            error);
        if (!error.isEmpty()) throw QgsProcessingException(error);
        const detail::CurveCsv target = detail::read_curve_csv(
            parameterAsFile(parameters, QStringLiteral("TARGET"), context), error);
        if (!error.isEmpty()) throw QgsProcessingException(error);
        if (reference.value.empty() || target.value.empty()) {
            throw QgsProcessingException(
                QStringLiteral("REFERENCE and TARGET both need numeric rows"));
        }

        // Kernel signature is a sample count (int64 band) — the parameter
        // type matches it, so fractional windows cannot sneak in.
        const int window = parameterAsInt(
            parameters, QStringLiteral("WINDOW"), context);
        const std::optional<std::int64_t> band =
            window > 0
                ? std::optional<std::int64_t>(
                      static_cast<std::int64_t>(window))
                : std::nullopt;
        const pwb::well_science::AlignmentResult alignment =
            pwb::well_science::match_curves(reference.value, target.value, band);
        if (alignment.path_ref.empty() || alignment.path_target.empty() ||
            std::isinf(alignment.cost)) {
            throw QgsProcessingException(
                QStringLiteral(
                    "alignment failed (empty curves or the window cannot reach "
                    "the DP endpoint)"));
        }
        if (feedback != nullptr && feedback->isCanceled()) return {};

        const QString output_path = parameterAsOutputLayer(
            parameters, QStringLiteral("OUTPUT"), context);
        QFile file(output_path);
        if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
            throw QgsProcessingException(
                QStringLiteral("cannot write OUTPUT file %1").arg(output_path));
        }
        QTextStream stream(&file);
        stream.setEncoding(QStringConverter::Utf8);
        stream << QStringLiteral("target_depth,reference_depth,cost\n");
        const QString cost_text = detail::format_csv_double(alignment.cost);
        for (std::size_t i = 0; i < alignment.path_target.size() &&
                               i < alignment.path_ref.size();
             ++i) {
            const std::int64_t target_index = alignment.path_target[i];
            const std::int64_t reference_index = alignment.path_ref[i];
            if (target_index < 0 ||
                static_cast<std::size_t>(target_index) >= target.depth.size() ||
                reference_index < 0 ||
                static_cast<std::size_t>(reference_index) >= reference.depth.size()) {
                throw QgsProcessingException(
                    QStringLiteral("alignment path indexes outside the curves"));
            }
            stream << detail::format_csv_double(
                          target.depth[static_cast<std::size_t>(target_index)])
                   << QLatin1Char(',')
                   << detail::format_csv_double(reference.depth[static_cast<
                           std::size_t>(reference_index)])
                   << QLatin1Char(',') << cost_text << '\n';
            if (feedback != nullptr &&
                (i % 4096 == 0) && feedback->isCanceled()) {
                return {};
            }
        }

        QVariantMap results;
        results.insert(QStringLiteral("OUTPUT"), output_path);
        results.insert(QStringLiteral("MATCH_COUNT"),
                       static_cast<qlonglong>(alignment.path_target.size()));
        if (feedback != nullptr) feedback->setProgress(100.0);
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new WellLogMatchAlgorithm();
    }
};

// ---- paleo:well_head_scatter ---------------------------------------------------

class WellHeadScatterAlgorithm final : public PaleoAlgorithm {
public:
    QString name() const override {
        return QString::fromLatin1(kAlgWellHeadScatter);
    }
    QString displayName() const override {
        return QStringLiteral("Well head scatter (DAT import)");
    }
    QString groupId() const override { return QString::fromLatin1(kGroupWell); }
    QString group() const override { return QStringLiteral("Well"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Parses a well-head DAT text (kernel build_well_head_scatter: "
            "column aliases, CRS/unit declarations, quoted shlex line "
            "splitting, issue cap) into a point layer with x/y/name/uwi "
            "attributes. ISSUES carries the parser's row diagnostics.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        addParameter(new QgsProcessingParameterFile(
            QStringLiteral("INPUT"), QStringLiteral("Well head DAT text"),
            Qgis::ProcessingFileParameterBehavior::File));
        addParameter(new QgsProcessingParameterVectorDestination(
            QStringLiteral("OUTPUT"), QStringLiteral("Well head points"),
            Qgis::ProcessingSourceType::VectorPoint));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("POINT_COUNT"), QStringLiteral("Valid well count")));
        addOutput(new QgsProcessingOutputString(
            QStringLiteral("ISSUES"), QStringLiteral("Parse issues (lines)")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        const QString input_path =
            parameterAsFile(parameters, QStringLiteral("INPUT"), context);
        QFile input(input_path);
        if (!input.open(QIODevice::ReadOnly)) {
            throw QgsProcessingException(
                QStringLiteral("cannot open INPUT file %1").arg(input_path));
        }
        const QByteArray bytes = input.readAll();
        const std::string text(bytes.constData(), static_cast<std::size_t>(bytes.size()));

        const pwb::ui_pages_preview::xy_scatter::WellHeadScatterResult result =
            pwb::ui_pages_preview::xy_scatter::build_well_head_scatter(text);
        if (!result.ok) {
            QString message = QString::fromStdString(result.error);
            if (!result.detail.empty()) {
                message += QStringLiteral(": %1")
                               .arg(QString::fromStdString(result.detail));
            }
            throw QgsProcessingException(message);
        }
        const pwb::ui_pages_preview::xy_scatter::WellHeadScatter& scatter =
            result.payload;
        if (feedback != nullptr && feedback->isCanceled()) return {};

        // CRS from the file/asset declaration when it resolves, else none.
        QgsCoordinateReferenceSystem crs;
        if (!scatter.source_crs.empty()) {
            crs = QgsCoordinateReferenceSystem(
                QString::fromStdString(scatter.source_crs));
        }

        QgsFields fields;
        fields.append(QgsField(QStringLiteral("x"), QMetaType::Type::Double));
        fields.append(QgsField(QStringLiteral("y"), QMetaType::Type::Double));
        fields.append(QgsField(QStringLiteral("name"), QMetaType::Type::QString));
        fields.append(QgsField(QStringLiteral("uwi"), QMetaType::Type::QString));
        QString sink_id;
        // Caller-owned sink (QGIS core contract): destruction finalizes the
        // output file. A raw pointer here leaks the writer and leaves file
        // sinks without their committed layer.
        std::unique_ptr<QgsFeatureSink> sink(parameterAsSink(
            parameters, QStringLiteral("OUTPUT"), context, sink_id, fields,
            Qgis::WkbType::Point, crs));
        if (sink == nullptr) {
            throw QgsProcessingException(QStringLiteral("failed to create output sink"));
        }

        const std::size_t point_count = scatter.x.size();
        for (std::size_t i = 0; i < point_count; ++i) {
            if (i >= scatter.y.size()) break;
            QgsFeature feature(fields);
            feature.setGeometry(QgsGeometry::fromPointXY(
                QgsPointXY(scatter.x[i], scatter.y[i])));
            feature.setAttribute(0, QVariant(scatter.x[i]));
            feature.setAttribute(1, QVariant(scatter.y[i]));
            feature.setAttribute(2, QVariant(i < scatter.names.size()
                                     ? QString::fromStdString(scatter.names[i])
                                     : QString()));
            feature.setAttribute(3, QVariant(i < scatter.uwis.size()
                                     ? QString::fromStdString(scatter.uwis[i])
                                     : QString()));
            sink->addFeature(feature, QgsFeatureSink::FastInsert);
            if (feedback != nullptr && (i % 4096 == 0) &&
                feedback->isCanceled()) {
                return {};
            }
        }

        QStringList issues;
        for (const auto& issue : scatter.issues) {
            issues << QStringLiteral("row %1: %2")
                          .arg(static_cast<qlonglong>(issue.source_row))
                          .arg(QString::fromStdString(issue.reason));
        }
        if (scatter.omitted_issue_count > 0) {
            issues << QStringLiteral("... %1 more issue(s) omitted")
                          .arg(static_cast<qlonglong>(scatter.omitted_issue_count));
        }

        QVariantMap results;
        results.insert(QStringLiteral("OUTPUT"), sink_id);
        results.insert(QStringLiteral("POINT_COUNT"),
                       static_cast<qlonglong>(scatter.valid_records));
        results.insert(QStringLiteral("ISSUES"), issues.join(QLatin1Char('\n')));
        if (feedback != nullptr) feedback->setProgress(100.0);
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new WellHeadScatterAlgorithm();
    }
};

}  // namespace

std::vector<QgsProcessingAlgorithm*> make_well_algorithms() {
    std::vector<QgsProcessingAlgorithm*> algorithms;
    algorithms.push_back(new WellCurveOperationAlgorithm());
    algorithms.push_back(new WellLogMatchAlgorithm());
    algorithms.push_back(new WellHeadScatterAlgorithm());
    return algorithms;
}

}  // namespace pwb::qgis_processing
