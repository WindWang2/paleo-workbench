// Cartography algorithms for QGIS Processing: scalar classification breaks
// over a raster band (pwb::cartography scalar_style kernels — numpy parity:
// linspace equal intervals, linear quantiles, Fisher-Jenks natural breaks).

#include <QVariant>

#include <qgsexception.h>
#include <qgsprocessingcontext.h>
#include <qgsprocessingfeedback.h>
#include <qgsprocessingoutputs.h>
#include <qgsprocessingparameters.h>
#include <qgsrasterlayer.h>

#include <pwb/qgis_processing/algorithm_ids.hpp>
#include <pwb/qgis_processing/grid_io.hpp>
#include <pwb/qgis_processing/paleo_algorithm.hpp>

#include <pwb/cartography/scalar_style.hpp>

#include <algorithm>
#include <cmath>
#include <exception>
#include <limits>
#include <vector>

namespace pwb::qgis_processing {

namespace {

// ---- paleo:scalar_classification ------------------------------------------------

class ScalarClassificationAlgorithm final : public PaleoAlgorithm {
public:
    QString name() const override {
        return QString::fromLatin1(kAlgScalarClassification);
    }
    QString displayName() const override {
        return QStringLiteral("Scalar classification breaks");
    }
    QString groupId() const override {
        return QString::fromLatin1(kGroupCartography);
    }
    QString group() const override { return QStringLiteral("Cartography"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Classified-renderer breaks for a raster band using the Paleo "
            "cartography kernels: equal interval (numpy linspace), quantile "
            "(linear interpolation) or natural breaks (Fisher-Jenks, "
            "deterministic sample draw). BREAKS is the comma-joined break "
            "list; CLASS_COUNT the number of breaks.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        addParameter(new QgsProcessingParameterRasterLayer(
            QStringLiteral("INPUT"), QStringLiteral("Input raster")));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("BAND"), QStringLiteral("Band"),
            Qgis::ProcessingNumberParameterType::Integer, 1, false, 1, 256));
        addParameter(new QgsProcessingParameterEnum(
            QStringLiteral("METHOD"), QStringLiteral("Classification method"),
            QStringList() << QStringLiteral("equal")
                          << QStringLiteral("quantile")
                          << QStringLiteral("natural")));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("CLASSES"), QStringLiteral("Classes"),
            Qgis::ProcessingNumberParameterType::Integer, 5, false, 2, 256));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("DECIMALS"), QStringLiteral("Label decimals"),
            Qgis::ProcessingNumberParameterType::Integer, 2, false, 0, 16));
        addOutput(new QgsProcessingOutputString(
            QStringLiteral("BREAKS"), QStringLiteral("Breaks (comma joined)")));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("CLASS_COUNT"), QStringLiteral("Break count")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        QgsRasterLayer* layer = parameterAsRasterLayer(
            parameters, QStringLiteral("INPUT"), context);
        QString error;
        const GridBand band = read_raster_grid(
            layer, parameterAsInt(parameters, QStringLiteral("BAND"), context),
            feedback, error);
        if (!error.isEmpty()) throw QgsProcessingException(error);

        // Finite values (quantile / natural breaks input) and the finite
        // span (equal interval input).
        std::vector<double> values;
        values.reserve(band.grid.grid_z.size());
        double vmin = std::numeric_limits<double>::quiet_NaN();
        double vmax = std::numeric_limits<double>::quiet_NaN();
        for (const double value : band.grid.grid_z) {
            if (!std::isfinite(value)) continue;
            values.push_back(value);
            vmin = std::isnan(vmin) ? value : std::min(vmin, value);
            vmax = std::isnan(vmax) ? value : std::max(vmax, value);
        }
        if (values.empty() || std::isnan(vmin) || std::isnan(vmax)) {
            throw QgsProcessingException(
                QStringLiteral("input band has no finite cells to classify"));
        }

        pwb::cartography::ScalarStyleSpec spec;
        static const char* kClassifications[] = {"equal_interval", "quantile",
                                                 "natural_breaks"};
        spec.classification = kClassifications[std::clamp(
            parameterAsEnum(parameters, QStringLiteral("METHOD"), context), 0, 2)];
        spec.n_classes = parameterAsInt(
            parameters, QStringLiteral("CLASSES"), context);
        spec.colorbar_decimals = parameterAsInt(
            parameters, QStringLiteral("DECIMALS"), context);

        const pwb::cartography::ClassifiedBreaks classified = [this, &spec,
                                                               &values, vmin,
                                                               vmax]() {
            try {
                return pwb::cartography::classify_breaks(spec, values, vmin, vmax);
            } catch (const std::exception& kernel_error) {
                throw QgsProcessingException(
                    QStringLiteral("classification failed: %1")
                        .arg(QString::fromStdString(kernel_error.what())));
            }
        }();
        if (feedback != nullptr && feedback->isCanceled()) return {};

        QStringList break_texts;
        break_texts.reserve(classified.breaks.size());
        for (const double value : classified.breaks) {
            break_texts << QString::fromStdString(
                pwb::cartography::format_fixed(value, spec.colorbar_decimals));
        }

        QVariantMap results;
        results.insert(QStringLiteral("BREAKS"),
                       break_texts.join(QLatin1Char(',')));
        results.insert(QStringLiteral("CLASS_COUNT"),
                       static_cast<qlonglong>(classified.breaks.size()));
        if (feedback != nullptr) feedback->setProgress(100.0);
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new ScalarClassificationAlgorithm();
    }
};

}  // namespace

std::vector<QgsProcessingAlgorithm*> make_cartography_algorithms() {
    std::vector<QgsProcessingAlgorithm*> algorithms;
    algorithms.push_back(new ScalarClassificationAlgorithm());
    return algorithms;
}

}  // namespace pwb::qgis_processing
