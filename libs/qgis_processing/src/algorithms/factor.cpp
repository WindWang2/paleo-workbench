// Paleo factor algorithms for QGIS Processing: evidence fusion, facies
// class grid, representative facies. Thin adapters over factor_fusion and
// mapping kernels.

#include <QVariant>

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
#include <qgsrasterlayer.h>

#include <pwb/domain/json.hpp>
#include <pwb/qgis_processing/algorithm_ids.hpp>
#include <pwb/qgis_processing/grid_io.hpp>
#include <pwb/qgis_processing/paleo_algorithm.hpp>

#include <pwb/factor_fusion/fusion.hpp>
#include <pwb/mapping/class_grid.hpp>
#include <pwb/mapping/representative_facies.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <limits>
#include <memory>
#include <vector>

namespace pwb::qgis_processing {

namespace {

[[nodiscard]] pwb::factor_fusion::FactorGrid grid_to_fusion(
    const pwb::mapping::Grid& grid, const std::string& factor_name) {
    pwb::factor_fusion::FactorGrid fusion_grid;
    fusion_grid.height = grid.h;
    fusion_grid.width = grid.w;
    fusion_grid.grid_x = grid.grid_x;
    fusion_grid.grid_y = grid.grid_y;
    fusion_grid.grid_z.resize(grid.grid_z.size());
    for (size_t i = 0; i < grid.grid_z.size(); ++i) {
        fusion_grid.grid_z[i] = static_cast<float>(grid.grid_z[i]);
    }
    fusion_grid.factor_name = factor_name;
    fusion_grid.algorithm_id = "qgis_processing";
    return fusion_grid;
}

[[nodiscard]] bool write_fusion_grid(const pwb::factor_fusion::FactorGrid& grid,
                                     const QgsCoordinateReferenceSystem& crs,
                                     const QString& output_path, QString& error) {
    pwb::mapping::FactorGrid out;
    out.grid_x = grid.grid_x;
    out.grid_y = grid.grid_y;
    out.grid_z = grid.grid_z;
    return write_factor_grid_raster(out, crs, output_path, false, error);
}

// ---- paleo:factor_fusion ----------------------------------------------------

class FactorFusionAlgorithm final : public PaleoAlgorithm {
public:
    QString name() const override { return QString::fromLatin1(kAlgFactorFusion); }
    QString displayName() const override {
        return QStringLiteral("Multi-factor evidence fusion");
    }
    QString groupId() const override { return QString::fromLatin1(kGroupFactor); }
    QString group() const override { return QStringLiteral("Factor"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Weighted multi-evidence fusion over aligned factor rasters "
            "(Paleo kernel: likelihood/confidence/variance grids plus class "
            "thresholds). Evidence grids must share shape; alignment is "
            "validated by the kernel.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        addParameter(new QgsProcessingParameterMultipleLayers(
            QStringLiteral("INPUT"), QStringLiteral("Evidence rasters"),
            Qgis::ProcessingSourceType::Raster));
        addParameter(new QgsProcessingParameterString(
            QStringLiteral("WEIGHTS"),
            QStringLiteral("Evidence weights (comma separated, order of INPUT)"),
            QVariant(), false, true));
        addParameter(new QgsProcessingParameterString(
            QStringLiteral("THRESHOLDS"),
            QStringLiteral("Class thresholds (comma separated, ascending)"),
            QVariant(), false, true));
        addParameter(new QgsProcessingParameterString(
            QStringLiteral("CLASS_NAMES"), QStringLiteral("Class names (comma separated)"),
            QVariant(), false, true));
        addParameter(new QgsProcessingParameterRasterDestination(
            QStringLiteral("OUTPUT"), QStringLiteral("Likelihood grid")));
        addParameter(new QgsProcessingParameterRasterDestination(
            QStringLiteral("CONFIDENCE"), QStringLiteral("Confidence grid"),
            QVariant(), true));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("EVIDENCE_COUNT"), QStringLiteral("Evidence count")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        const QList<QgsMapLayer*> layers = parameterAsLayerList(
            parameters, QStringLiteral("INPUT"), context);
        if (layers.size() < 1) {
            throw QgsProcessingException(
                QStringLiteral("at least one evidence raster is required"));
        }

        // Weights: comma separated, default 1.0 each.
        std::vector<double> weights(static_cast<size_t>(layers.size()), 1.0);
        const QString weights_text =
            parameterAsString(parameters, QStringLiteral("WEIGHTS"), context);
        if (!weights_text.isEmpty()) {
            const QStringList tokens = weights_text.split(',', Qt::SkipEmptyParts);
            if (tokens.size() != layers.size()) {
                throw QgsProcessingException(
                    QStringLiteral("WEIGHTS has %1 entries but INPUT has %2 layers")
                        .arg(tokens.size())
                        .arg(layers.size()));
            }
            for (int i = 0; i < tokens.size(); ++i) {
                bool ok = false;
                const double weight = tokens[i].trimmed().toDouble(&ok);
                if (!ok || !std::isfinite(weight) || weight <= 0.0) {
                    throw QgsProcessingException(
                        QStringLiteral("WEIGHTS entry %1 is not a positive number")
                            .arg(i + 1));
                }
                weights[static_cast<size_t>(i)] = weight;
            }
        }

        pwb::factor_fusion::FusionModel model;
        model.name = "qgis_processing_fusion";
        model.kind = "weighted_evidence";
        QgsCoordinateReferenceSystem crs;
        QString error;
        for (int i = 0; i < layers.size(); ++i) {
            QgsRasterLayer* raster = qobject_cast<QgsRasterLayer*>(layers.at(i));
            if (raster == nullptr) {
                throw QgsProcessingException(
                    QStringLiteral("INPUT layer %1 is not a raster").arg(i + 1));
            }
            const GridBand band = read_raster_grid(raster, 1, feedback, error);
            if (!error.isEmpty()) throw QgsProcessingException(error);
            if (!crs.isValid()) crs = band.crs;
            try {
                model.evidences.emplace_back(
                    raster->name().toStdString(),
                    grid_to_fusion(band.grid, raster->name().toStdString()),
                    weights.at(static_cast<size_t>(i)),
                    pwb::factor_fusion::Normalization("minmax", 0.0, 1.0));
            } catch (const std::invalid_argument& bad) {
                throw QgsProcessingException(
                    QStringLiteral("evidence %1: %2")
                        .arg(i + 1)
                        .arg(QString::fromStdString(bad.what())));
            }
            if (feedback != nullptr) {
                feedback->setProgress(100.0 * static_cast<double>(i + 1) /
                                      static_cast<double>(layers.size()));
                if (feedback->isCanceled()) return {};
            }
        }
        const QString thresholds_text =
            parameterAsString(parameters, QStringLiteral("THRESHOLDS"), context);
        if (!thresholds_text.isEmpty()) {
            for (const QString& token :
                 thresholds_text.split(',', Qt::SkipEmptyParts)) {
                bool ok = false;
                const double threshold = token.trimmed().toDouble(&ok);
                if (ok && std::isfinite(threshold)) {
                    model.class_thresholds.push_back(threshold);
                }
            }
            std::sort(model.class_thresholds.begin(), model.class_thresholds.end());
        }
        const QString class_names =
            parameterAsString(parameters, QStringLiteral("CLASS_NAMES"), context);
        if (!class_names.isEmpty()) {
            for (const QString& token : class_names.split(',', Qt::SkipEmptyParts)) {
                model.class_names.push_back(token.trimmed().toStdString());
            }
        }

        const pwb::factor_fusion::FusionResult result = [this, &model, &parameters,
                                                         &context]() {
            try {
                return pwb::factor_fusion::fuse(model);
            } catch (const std::exception& bad) {
                throw QgsProcessingException(
                    QStringLiteral("fusion failed: %1")
                        .arg(QString::fromStdString(bad.what())));
            }
        }();
        if (feedback != nullptr && feedback->isCanceled()) return {};

        const QString output_path = parameterAsOutputLayer(
            parameters, QStringLiteral("OUTPUT"), context);
        if (!write_fusion_grid(result.likelihood, crs, output_path, error)) {
            throw QgsProcessingException(error);
        }
        context.addLayerToLoadOnCompletion(
            output_path,
            QgsProcessingContext::LayerDetails(displayName(), context.project(),
                                                QStringLiteral("OUTPUT")));

        QVariantMap results;
        results.insert(QStringLiteral("OUTPUT"), output_path);
        results.insert(QStringLiteral("EVIDENCE_COUNT"),
                       static_cast<qlonglong>(model.evidences.size()));
        const QVariant confidence_param =
            parameters.value(QStringLiteral("CONFIDENCE"));
        if (confidence_param.isValid() && !confidence_param.isNull()) {
            const QString confidence_path = parameterAsOutputLayer(
                parameters, QStringLiteral("CONFIDENCE"), context);
            if (!write_fusion_grid(result.confidence, crs, confidence_path, error)) {
                throw QgsProcessingException(error);
            }
            context.addLayerToLoadOnCompletion(
                confidence_path, QgsProcessingContext::LayerDetails(
                                     displayName(), context.project(),
                                     QStringLiteral("CONFIDENCE")));
            results.insert(QStringLiteral("CONFIDENCE"), confidence_path);
        }
        if (feedback != nullptr) feedback->setProgress(100.0);
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new FactorFusionAlgorithm();
    }
};

// ---- paleo:facies_class_grid -------------------------------------------------

class FaciesClassGridAlgorithm final : public PaleoAlgorithm {
public:
    QString name() const override { return QString::fromLatin1(kAlgFaciesClassGrid); }
    QString displayName() const override {
        return QStringLiteral("Nearest-neighbor facies classification grid");
    }
    QString groupId() const override { return QString::fromLatin1(kGroupFactor); }
    QString group() const override { return QStringLiteral("Factor"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Classifies a regular grid by nearest well facies point (kernel "
            "parity), optionally clipped by a boundary ring. Output raster "
            "carries class ids; the class legend comes back as FACIES_NAMES.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        addParameter(new QgsProcessingParameterFeatureSource(
            QStringLiteral("INPUT"), QStringLiteral("Facies points"),
            QList<int>()
                << static_cast<int>(Qgis::ProcessingSourceType::VectorPoint)));
        addParameter(new QgsProcessingParameterField(
            QStringLiteral("FACIESFIELD"), QStringLiteral("Facies name field"),
            QVariant(), QStringLiteral("INPUT")));
        addParameter(new QgsProcessingParameterExtent(
            QStringLiteral("EXTENT"), QStringLiteral("Grid extent"),
            QVariant(), false));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("GRID_N"), QStringLiteral("Grid resolution"),
            Qgis::ProcessingNumberParameterType::Integer, 80, false, 8, 2048));
        addParameter(new QgsProcessingParameterVectorLayer(
            QStringLiteral("BOUNDARY"), QStringLiteral("Clip boundary (polygon)"),
            QList<int>() << static_cast<int>(Qgis::ProcessingSourceType::VectorPolygon),
            QVariant(), true));
        addParameter(new QgsProcessingParameterCrs(
            QStringLiteral("CRS"), QStringLiteral("CRS"), QVariant()));
        addParameter(new QgsProcessingParameterRasterDestination(
            QStringLiteral("OUTPUT"), QStringLiteral("Facies class grid")));
        addOutput(new QgsProcessingOutputString(
            QStringLiteral("FACIES_NAMES"), QStringLiteral("Class legend (ordered)")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        std::unique_ptr<QgsProcessingFeatureSource> source(parameterAsSource(
            parameters, QStringLiteral("INPUT"), context));
        if (source == nullptr) {
            throw QgsProcessingException(QStringLiteral("INPUT is required"));
        }
        const QString facies_field = parameterAsString(
            parameters, QStringLiteral("FACIESFIELD"), context);
        const QgsFields fields = source->fields();
        const int facies_index = fields.indexOf(facies_field);
        if (facies_index < 0) {
            throw QgsProcessingException(
                QStringLiteral("FACIESFIELD '%1' not on INPUT").arg(facies_field));
        }

        std::vector<pwb::mapping::FaciesPoint> points;
        QgsFeature feature;
        QgsFeatureIterator iterator = source->getFeatures(QgsFeatureRequest());
        while (iterator.nextFeature(feature)) {
            const QgsGeometry geometry = feature.geometry();
            if (geometry.isNull() || geometry.isEmpty()) continue;
            const QgsPointXY point = geometry.asPoint();
            const QVariant facies = feature.attribute(facies_index);
            if (!facies.canConvert<QString>()) continue;
            pwb::mapping::FaciesPoint facies_point;
            facies_point.x = point.x();
            facies_point.y = point.y();
            facies_point.facies = facies.toString().toStdString();
            points.push_back(std::move(facies_point));
            if (feedback != nullptr && feedback->isCanceled()) return {};
        }
        if (points.empty()) {
            throw QgsProcessingException(
                QStringLiteral("INPUT has no facies points"));
        }

        const QgsRectangle extent = parameterAsExtent(
            parameters, QStringLiteral("EXTENT"), context);
        if (extent.isEmpty()) {
            throw QgsProcessingException(
                QStringLiteral("EXTENT is required (explicit or from layer)"));
        }
        std::vector<pwb::mapping::Point> clip_ring;
        if (std::unique_ptr<QgsProcessingFeatureSource> boundary =
                std::unique_ptr<QgsProcessingFeatureSource>(parameterAsSource(
                    parameters, QStringLiteral("BOUNDARY"), context))) {
            QString error;
            const pwb::mapping::constrained_idw::BoundaryPolygon polygon =
                read_boundary_polygon(boundary.get(), feedback, error);
            if (!error.isEmpty()) throw QgsProcessingException(error);
            clip_ring = polygon.exterior;
        }

        const QgsCoordinateReferenceSystem crs =
            parameterAsCrs(parameters, QStringLiteral("CRS"), context);
        const pwb::mapping::ClassGrid class_grid = pwb::mapping::nearest_neighbor_class_grid(
            points,
            std::array<double, 4>{extent.xMinimum(), extent.yMinimum(),
                                  extent.xMaximum(), extent.yMaximum()},
            parameterAsInt(parameters, QStringLiteral("GRID_N"), context), clip_ring);
        if (feedback != nullptr && feedback->isCanceled()) return {};

        pwb::mapping::FactorGrid grid;
        grid.grid_x = class_grid.grid_x;
        grid.grid_y = class_grid.grid_y;
        grid.grid_z = class_grid.grid_z;
        const QString output_path = parameterAsOutputLayer(
            parameters, QStringLiteral("OUTPUT"), context);
        QString error;
        if (!write_factor_grid_raster(grid, crs, output_path, false, error)) {
            throw QgsProcessingException(error);
        }
        context.addLayerToLoadOnCompletion(
            output_path, QgsProcessingContext::LayerDetails(
                             displayName(), context.project(), QStringLiteral("OUTPUT")));

        QStringList legend;
        for (const std::string& name : class_grid.facies_names) {
            legend << QString::fromStdString(name);
        }
        QVariantMap results;
        results.insert(QStringLiteral("OUTPUT"), output_path);
        results.insert(QStringLiteral("FACIES_NAMES"), legend.join(QLatin1Char(',')));
        if (feedback != nullptr) feedback->setProgress(100.0);
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new FaciesClassGridAlgorithm();
    }
};

// ---- paleo:representative_facies ---------------------------------------------

class RepresentativeFaciesAlgorithm final : public PaleoAlgorithm {
public:
    QString name() const override {
        return QString::fromLatin1(kAlgRepresentativeFacies);
    }
    QString displayName() const override {
        return QStringLiteral("Representative facies of prediction regions");
    }
    QString groupId() const override { return QString::fromLatin1(kGroupFactor); }
    QString group() const override { return QStringLiteral("Factor"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Aggregates a prediction result summary's spatial regions into the "
            "representative facies (probability-mass weighted), optionally "
            "filtered by horizon.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        addParameter(new QgsProcessingParameterFile(
            QStringLiteral("REGIONS"), QStringLiteral("Result summary (JSON)"),
            Qgis::ProcessingFileParameterBehavior::File, QStringLiteral("json")));
        addParameter(new QgsProcessingParameterString(
            QStringLiteral("HORIZON"), QStringLiteral("Horizon filter"), QVariant(),
            false, true));
        addOutput(new QgsProcessingOutputString(
            QStringLiteral("FACIES"), QStringLiteral("Representative facies")));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("MEAN_PROBABILITY"), QStringLiteral("Mean probability")));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("THICKNESS"), QStringLiteral("Total thickness")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback*) override {
        const QString regions_path =
            parameterAsFile(parameters, QStringLiteral("REGIONS"), context);
        std::ifstream input(regions_path.toStdString(), std::ios::binary);
        if (!input) {
            throw QgsProcessingException(
                QStringLiteral("cannot open REGIONS file %1").arg(regions_path));
        }
        pwb::domain::Json regions;
        try {
            input >> regions;
        } catch (const std::exception& parse_error) {
            throw QgsProcessingException(
                QStringLiteral("REGIONS is not valid JSON: %1")
                    .arg(QString::fromStdString(parse_error.what())));
        }
        const std::string horizon =
            parameterAsString(parameters, QStringLiteral("HORIZON"), context)
                .toStdString();
        const std::optional<pwb::mapping::RepresentativeFacies> representative =
            pwb::mapping::representative_facies(regions, horizon);
        if (!representative.has_value()) {
            throw QgsProcessingException(
                QStringLiteral("no usable regions in REGIONS"));
        }
        QVariantMap results;
        results.insert(QStringLiteral("FACIES"),
                       QString::fromStdString(representative->facies));
        results.insert(
            QStringLiteral("MEAN_PROBABILITY"),
            representative->mean_probability.has_value()
                ? QVariant(*representative->mean_probability)
                : QVariant());
        results.insert(QStringLiteral("THICKNESS"), QVariant(representative->thickness));
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new RepresentativeFaciesAlgorithm();
    }
};

}  // namespace

std::vector<QgsProcessingAlgorithm*> make_factor_algorithms() {
    std::vector<QgsProcessingAlgorithm*> algorithms;
    algorithms.push_back(new FactorFusionAlgorithm());
    algorithms.push_back(new FaciesClassGridAlgorithm());
    algorithms.push_back(new RepresentativeFaciesAlgorithm());
    return algorithms;
}

}  // namespace pwb::qgis_processing
