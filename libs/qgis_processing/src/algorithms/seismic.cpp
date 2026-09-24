// Seismic attribute algorithms for QGIS Processing.
//
// One generic adapter (SeismicAttributeAlgorithm) wraps every pwb::science
// IAlgorithm from the seismic attribute kernel set: the ten descriptors of
// pwb::seismic_attributes plus seismic.coherence_c3 from pwb::science.
// Identity mapping: "seismic.<name>" -> "paleo:seismic_<name>".
//
// The adapter only translates parameters/results: INPUT is a raw packed
// float32 volume (inline-major C order) whose shape the user declares;
// OUTPUT is the produced volume written as raw float32 bytes. Numerics are
// entirely the kernels'.

#include <QByteArray>
#include <QFile>
#include <QVariant>

#include <qgsexception.h>
#include <qgsprocessingcontext.h>
#include <qgsprocessingfeedback.h>
#include <qgsprocessingoutputs.h>
#include <qgsprocessingparameters.h>

#include <pwb/qgis_processing/algorithm_ids.hpp>
#include <pwb/qgis_processing/paleo_algorithm.hpp>

#include <pwb/science/algorithm.hpp>
#include <pwb/science/algorithms/coherence_c3.hpp>
#include <pwb/science/types.hpp>
#include <pwb/seismic_attributes/attributes.hpp>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <limits>
#include <memory>
#include <string>
#include <vector>

namespace pwb::qgis_processing {

namespace {

using pwb::science::AlgorithmRequestV1;
using pwb::science::IAlgorithm;

// Round-trip JSON scalar text for params_json (kernels parse with the
// pwb::science scalar parser: bare numbers, true/false, quoted strings).
[[nodiscard]] std::string encode_number_scalar(double value) {
    return QString::number(value, 'g', 17).toStdString();
}

[[nodiscard]] std::string encode_string_scalar(const std::string& value) {
    std::string out = "\"";
    for (const char c : value) {
        if (c == '"' || c == '\\') out.push_back('\\');
        out.push_back(c);
    }
    out.push_back('"');
    return out;
}

// Generic adapter over one science algorithm. The factory is kept so
// createInstance() can mint a fresh kernel instance.
class SeismicAttributeAlgorithm final : public PaleoAlgorithm {
public:
    using AlgorithmFactory = std::function<std::unique_ptr<IAlgorithm>()>;

    explicit SeismicAttributeAlgorithm(AlgorithmFactory factory)
        : factory_(std::move(factory)), algorithm_(factory_()) {}

    QString name() const override {
        // "seismic.envelope" -> "seismic_envelope" (=> paleo:seismic_envelope).
        return QString::fromLatin1("seismic_") + QString::fromStdString(
            algorithm_->descriptor().algorithm_id.substr(
                algorithm_->descriptor().algorithm_id.find('.') + 1));
    }
    QString displayName() const override {
        return QString::fromStdString(algorithm_->descriptor().display_name);
    }
    QString groupId() const override { return QString::fromLatin1(kGroupSeismic); }
    QString group() const override { return QStringLiteral("Seismic"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Seismic volume attribute (Paleo science kernel %1, version %2). "
            "INPUT is a packed float32 volume in inline-major C order; the "
            "shape is declared by SHAPE_IL/SHAPE_XL/SHAPE_SAMPLE (SAMPLE = 0 "
            "infers the sample count from the file size). OUTPUT is the "
            "attribute volume as raw float32 bytes with the same shape.")
            .arg(QString::fromStdString(algorithm_->descriptor().algorithm_id),
                 QString::fromStdString(algorithm_->descriptor().version));
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        addParameter(new QgsProcessingParameterFile(
            QStringLiteral("INPUT"), QStringLiteral("Input volume (packed float32)"),
            Qgis::ProcessingFileParameterBehavior::File));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("SHAPE_IL"), QStringLiteral("Inline count"),
            Qgis::ProcessingNumberParameterType::Integer, 1, false, 1));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("SHAPE_XL"), QStringLiteral("Crossline count"),
            Qgis::ProcessingNumberParameterType::Integer, 1, false, 1));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("SHAPE_SAMPLE"), QStringLiteral(
                "Samples per trace (0 = infer from file size)"),
            Qgis::ProcessingNumberParameterType::Integer, 0, false, 0));

        // Kernel parameters, mapped from the descriptor's ParamSpec table.
        for (const pwb::science::ParamSpec& spec :
             algorithm_->descriptor().parameters) {
            const QString pname = QString::fromLatin1(spec.name);
            const QString description =
                spec.unit.empty()
                    ? pname
                    : pname + QStringLiteral(" (%1)").arg(
                          QString::fromLatin1(spec.unit));
            // types.hpp: maximum == 0 with minimum <= 0 means unbounded.
            const bool bounded = spec.maximum > 0.0;
            switch (spec.type) {
            case pwb::science::ParamSpec::Type::integer: {
                QVariant default_value;
                if (!spec.default_json.empty()) {
                    default_value = static_cast<int>(
                        std::strtoll(spec.default_json.c_str(), nullptr, 10));
                }
                addParameter(new QgsProcessingParameterNumber(
                    pname, description, Qgis::ProcessingNumberParameterType::Integer,
                    default_value, spec.default_json.empty(),
                    bounded ? spec.minimum
                            : std::numeric_limits<double>::lowest() + 1,
                    bounded ? spec.maximum : std::numeric_limits<double>::max()));
                break;
            }
            case pwb::science::ParamSpec::Type::number: {
                QVariant default_value;
                if (!spec.default_json.empty()) {
                    default_value = std::strtod(spec.default_json.c_str(), nullptr);
                }
                addParameter(new QgsProcessingParameterNumber(
                    pname, description, Qgis::ProcessingNumberParameterType::Double,
                    default_value, spec.default_json.empty(),
                    bounded ? spec.minimum
                            : std::numeric_limits<double>::lowest() + 1,
                    bounded ? spec.maximum : std::numeric_limits<double>::max()));
                break;
            }
            case pwb::science::ParamSpec::Type::boolean: {
                addParameter(new QgsProcessingParameterBoolean(
                    pname, description,
                    QVariant(spec.default_json == "true"),
                    spec.default_json.empty()));
                break;
            }
            case pwb::science::ParamSpec::Type::string: {
                QString default_value;
                if (spec.default_json.size() >= 2 && spec.default_json.front() == '"' &&
                    spec.default_json.back() == '"') {
                    default_value = QString::fromStdString(
                        spec.default_json.substr(1, spec.default_json.size() - 2));
                }
                addParameter(new QgsProcessingParameterString(
                    pname, description, default_value, false,
                    spec.default_json.empty()));
                break;
            }
            }
        }

        addParameter(new QgsProcessingParameterFileDestination(
            QStringLiteral("OUTPUT"), QStringLiteral("Attribute volume (float32)"),
            QStringLiteral("Float32 volume (*.f32)")));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("VALID_CELLS"), QStringLiteral("Non-NaN cell count")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        const std::string input_path = parameterAsFile(
            parameters, QStringLiteral("INPUT"), context).toStdString();
        QFile input(QString::fromStdString(input_path));
        if (!input.open(QIODevice::ReadOnly)) {
            throw QgsProcessingException(
                QStringLiteral("cannot open INPUT file %1").arg(input.fileName()));
        }
        const QByteArray bytes = input.readAll();

        const std::int64_t n_il = parameterAsInt(
            parameters, QStringLiteral("SHAPE_IL"), context);
        const std::int64_t n_xl = parameterAsInt(
            parameters, QStringLiteral("SHAPE_XL"), context);
        std::int64_t n_sample = parameterAsInt(
            parameters, QStringLiteral("SHAPE_SAMPLE"), context);
        const std::int64_t plane = n_il * n_xl;
        if (n_sample <= 0) {
            // Infer: file size must be an exact float32 multiple of one plane.
            if (plane <= 0 || bytes.isEmpty() ||
                bytes.size() % (plane * static_cast<qint64>(sizeof(float))) != 0) {
                throw QgsProcessingException(
                    QStringLiteral(
                        "SHAPE_SAMPLE is 0 but the input size (%1 bytes) is not a "
                        "float32 multiple of SHAPE_IL x SHAPE_XL = %2 cells")
                        .arg(bytes.size())
                        .arg(plane));
            }
            n_sample = bytes.size() / (plane * static_cast<qint64>(sizeof(float)));
        }
        const std::int64_t expected =
            plane * n_sample * static_cast<std::int64_t>(sizeof(float));
        if (static_cast<std::int64_t>(bytes.size()) != expected) {
            throw QgsProcessingException(
                QStringLiteral(
                    "INPUT size %1 bytes does not match the declared shape "
                    "%2 x %3 x %4 x 4 = %5 bytes")
                    .arg(bytes.size())
                    .arg(n_il)
                    .arg(n_xl)
                    .arg(n_sample)
                    .arg(expected));
        }

        // Backing storage kept alive through the kernel run via the view's
        // lifetime guard.
        auto buffer = std::make_shared<std::vector<float>>(
            static_cast<std::size_t>(plane * n_sample));
        std::memcpy(buffer->data(), bytes.constData(),
                    static_cast<std::size_t>(expected));

        pwb::science::VolumeView view;
        view.data = buffer->data();
        view.shape = {n_il, n_xl, n_sample};
        view.strides = {0, 0, 0};  // packed C-order
        view.lifetime = buffer;

        AlgorithmRequestV1 request;
        request.algorithm_id = algorithm_->descriptor().algorithm_id;
        request.algorithm_version = algorithm_->descriptor().version;
        request.input_volumes.push_back(view);
        for (const pwb::science::ParamSpec& spec :
             algorithm_->descriptor().parameters) {
            const QString pname = QString::fromLatin1(spec.name);
            switch (spec.type) {
            case pwb::science::ParamSpec::Type::integer:
                request.params_json[spec.name] = std::to_string(
                    parameterAsInt(parameters, pname, context));
                break;
            case pwb::science::ParamSpec::Type::number:
                request.params_json[spec.name] = encode_number_scalar(
                    parameterAsDouble(parameters, pname, context));
                break;
            case pwb::science::ParamSpec::Type::boolean:
                request.params_json[spec.name] =
                    parameterAsBool(parameters, pname, context) ? "true" : "false";
                break;
            case pwb::science::ParamSpec::Type::string:
                request.params_json[spec.name] = encode_string_scalar(
                    parameterAsString(parameters, pname, context).toStdString());
                break;
            }
        }

        pwb::science::AlgorithmResultV1 result;
        QString error;
        if (!run_science_algorithm(*algorithm_, request, feedback, result, error)) {
            if (!error.isEmpty()) throw QgsProcessingException(error);
            return {};  // cancelled
        }
        if (result.outputs.empty()) {
            throw QgsProcessingException(
                QStringLiteral("kernel produced no output volume"));
        }
        const pwb::science::VolumeView& volume = result.outputs.front().volume;
        const std::int64_t cell_count = volume.size();

        const QString output_path = parameterAsOutputLayer(
            parameters, QStringLiteral("OUTPUT"), context);
        QFile output(output_path);
        if (!output.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
            throw QgsProcessingException(
                QStringLiteral("cannot write OUTPUT file %1").arg(output_path));
        }
        const qint64 byte_count =
            cell_count * static_cast<qint64>(sizeof(float));
        if (output.write(reinterpret_cast<const char*>(volume.data),
                         byte_count) != byte_count) {
            throw QgsProcessingException(
                QStringLiteral("short write to OUTPUT file %1").arg(output_path));
        }

        qlonglong valid_cells = 0;
        for (std::int64_t i = 0; i < cell_count; ++i) {
            if (!std::isnan(volume.data[i])) ++valid_cells;
        }

        QVariantMap results;
        results.insert(QStringLiteral("OUTPUT"), output_path);
        results.insert(QStringLiteral("VALID_CELLS"), valid_cells);
        if (feedback != nullptr) feedback->setProgress(100.0);
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new SeismicAttributeAlgorithm(factory_);
    }

private:
    AlgorithmFactory factory_;
    std::unique_ptr<IAlgorithm> algorithm_;
};

constexpr auto kBuildIdentity = "qgis_processing";

}  // namespace

std::vector<QgsProcessingAlgorithm*> make_seismic_algorithms() {
    using pwb::seismic_attributes::make_curvature_mean;
    using pwb::seismic_attributes::make_dip_azimuth;
    using pwb::seismic_attributes::make_dip_crossline;
    using pwb::seismic_attributes::make_dip_inline;
    using pwb::seismic_attributes::make_envelope;
    using pwb::seismic_attributes::make_instantaneous_frequency;
    using pwb::seismic_attributes::make_instantaneous_phase;
    using pwb::seismic_attributes::make_relative_impedance;
    using pwb::seismic_attributes::make_rms_amplitude;
    using pwb::seismic_attributes::make_sweetness;

    const std::vector<SeismicAttributeAlgorithm::AlgorithmFactory> factories = {
        [] { return make_envelope(kBuildIdentity); },
        [] { return make_instantaneous_phase(kBuildIdentity); },
        [] { return make_instantaneous_frequency(kBuildIdentity); },
        [] { return make_rms_amplitude(kBuildIdentity); },
        [] { return make_sweetness(kBuildIdentity); },
        [] { return make_relative_impedance(kBuildIdentity); },
        [] { return make_dip_inline(kBuildIdentity); },
        [] { return make_dip_crossline(kBuildIdentity); },
        [] { return make_dip_azimuth(kBuildIdentity); },
        [] { return make_curvature_mean(kBuildIdentity); },
        [] { return pwb::science::algorithms::make_coherence_c3(kBuildIdentity); },
    };
    std::vector<QgsProcessingAlgorithm*> algorithms;
    algorithms.reserve(factories.size());
    for (const auto& factory : factories) {
        algorithms.push_back(new SeismicAttributeAlgorithm(factory));
    }
    return algorithms;
}

}  // namespace pwb::qgis_processing
