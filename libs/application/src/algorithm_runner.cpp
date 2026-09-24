#include <pwb/application/algorithm_runner.hpp>

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <thread>
#include <utility>
#include <algorithm>

#include <QFile>
#include <QTemporaryDir>
#include <QVariantMap>

#include <qgsprocessingalgorithm.h>
#include <qgsprocessingfeedback.h>
#include <qgsprocessingparameters.h>

#include <pwb/application/adapters/volume_payload.hpp>
#include <pwb/qgis_processing/algorithm_ids.hpp>
#include <pwb/qgis_processing/provider.hpp>
#include <pwb/qgis_processing/runner.hpp>
#include <pwb/science/publisher.hpp>
#include <pwb/science/types.hpp>

namespace pwb::application {
namespace {

std::atomic<std::uint64_t> g_request_counter{0};

pwb::viz::VolumeGeometryV1 geometry_of(
    const pwb::application::VolumePayloadHeader& header) {
    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = {static_cast<std::int64_t>(header.ni),
                      static_cast<std::int64_t>(header.nc),
                      static_cast<std::int64_t>(header.ns)};
    geometry.strides = {0, 0, 0};  // PWBVOL1 payloads are packed C-order
    geometry.origin = {header.inline_start, header.crossline_start,
                       header.sample_start};
    geometry.step = {header.inline_step, header.crossline_step,
                     header.sample_step};
    geometry.unit = header.sample_unit;
    return geometry;
}

// Locates one catalog version and reads its PWBVOL1 payload; the version's
// project-relative path resolves against the store's project directory.
std::string load_version_volume(
    const std::shared_ptr<PwbDataStore>& store,
    const std::string& version_id, pwb::application::VolumePayload* payload,
    pwb::viz::VolumeGeometryV1* geometry) {
    auto snapshot = store->snapshot();
    if (!snapshot.is_ok()) {
        return "store snapshot failed: " + snapshot.error().message;
    }
    const std::filesystem::path project_dir =
        store->project_file().parent_path();
    for (const auto& version : snapshot.value().catalog_versions) {
        if (version.id.str() != version_id) continue;
        if (version.format != "PWBVOL1") {
            return "version " + version_id + " is not a PWBVOL1 volume ("
                + version.format + ")";
        }
        const std::filesystem::path payload_path = project_dir / version.path;
        const std::string read_error =
            pwb::application::read_volume_payload(payload_path, payload);
        if (!read_error.empty()) return read_error;
        *geometry = geometry_of(payload->header);
        return "";
    }
    return "version not found in catalog: " + version_id;
}

// Science-id / Processing-id normalization onto the registry vocabulary.
// "paleo:seismic_envelope" passes through; "seismic.envelope" maps through
// the shared helper; anything else fails closed (empty).
QString paleo_id_for(const std::string& algorithm_id) {
    const QString raw = QString::fromStdString(algorithm_id);
    if (raw.startsWith(QString::fromLatin1(pwb::qgis_processing::kProviderId)
                       + QLatin1Char(':'))) {
        return raw;
    }
    return pwb::qgis_processing::to_paleo_algorithm_id(raw);
}

// "paleo:seismic_rms_amplitude" -> "seismic.rms_amplitude": the catalog run
// operation keeps the science-kernel id (B-row parity with the old
// TaskRuntime rail, which published the kernel descriptor id).
std::string science_id_from_paleo(const QString& paleo_id) {
    const QString prefix =
        QString::fromLatin1(pwb::qgis_processing::kProviderId)
        + QLatin1Char(':') + QString::fromLatin1(pwb::qgis_processing::kGroupSeismic)
        + QLatin1Char('_');
    if (paleo_id.startsWith(prefix)) {
        return (QString::fromLatin1(pwb::qgis_processing::kGroupSeismic)
                + QLatin1Char('.') + paleo_id.mid(prefix.size()))
            .toStdString();
    }
    return paleo_id.toStdString();
}

// Kernel params (string-encoded scalars, the params_json vocabulary) ->
// Processing QVariantMap entries typed after the algorithm's parameter
// definitions. Unknown names are dropped: Processing owns the schema.
void encode_kernel_params(const QgsProcessingAlgorithm* prototype,
                          const std::map<std::string, std::string>& params,
                          QVariantMap* parameters) {
    for (const QgsProcessingParameterDefinition* definition :
         prototype->parameterDefinitions()) {
        const auto it = params.find(definition->name().toStdString());
        if (it == params.end()) continue;
        const std::string& raw = it->second;
        const QString type = definition->type();
        if (type == QLatin1String("QgsProcessingParameterNumber")) {
            const auto* number =
                static_cast<const QgsProcessingParameterNumber*>(definition);
            if (number->dataType()
                == Qgis::ProcessingNumberParameterType::Integer) {
                parameters->insert(definition->name(),
                                   static_cast<qlonglong>(
                                       std::strtoll(raw.c_str(), nullptr, 10)));
            } else {
                parameters->insert(definition->name(),
                                   std::strtod(raw.c_str(), nullptr));
            }
        } else if (type == QLatin1String("QgsProcessingParameterBoolean")) {
            parameters->insert(definition->name(),
                               raw == "true" || raw == "1");
        } else {
            parameters->insert(definition->name(),
                               QString::fromStdString(raw));
        }
    }
}

// Reads a packed float32 volume written by a paleo algorithm (the OUTPUT
// contract of the seismic family). Returns "" on success.
std::string read_f32_volume(const QString& path,
                            std::shared_ptr<std::vector<float>>* samples) {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) {
        return "cannot open algorithm output " + path.toStdString();
    }
    const QByteArray bytes = file.readAll();
    if (bytes.size() % static_cast<qint64>(sizeof(float)) != 0) {
        return "algorithm output is not a float32 multiple: "
            + path.toStdString();
    }
    auto buffer = std::make_shared<std::vector<float>>(
        static_cast<std::size_t>(bytes.size() / sizeof(float)));
    std::memcpy(buffer->data(), bytes.constData(),
                static_cast<std::size_t>(bytes.size()));
    *samples = std::move(buffer);
    return "";
}

// Publication lifecycle, extracted from the old TaskRuntime rail: registers
// the request context, publishes the success volume (or the failure) and
// reports the durable outcome (run id / version id / error). Called on the
// submitting thread right after run_paleo_algorithm returned.
CatalogResultPublisher::Outcome publish_run_outcome(
    const std::shared_ptr<PwbDataStore>& store,
    const std::filesystem::path& staged_dir, const std::string& request_id,
    const pwb::viz::VolumeGeometryV1& geometry,
    const std::map<std::string, std::string>& params,
    const std::string& input_version_id,
    const std::string& kernel_algorithm_id,
    const std::shared_ptr<std::vector<float>>& samples,
    const std::array<std::int64_t, 3>& shape, bool ok, bool cancelled,
    const std::string& error) {
    auto publisher = std::make_shared<pwb::application::CatalogResultPublisher>(
        store, staged_dir);
    pwb::application::RequestContext context;
    context.geometry = geometry;
    context.input_version_ids = {input_version_id};
    context.params_json = params;
    publisher->set_request_context(request_id, std::move(context));

    if (ok) {
        pwb::science::AlgorithmResultV1 result;
        result.request_id = request_id;
        pwb::science::ProducedVolume produced;
        produced.name = "volume";
        produced.volume.data = samples->data();
        produced.volume.shape = shape;
        produced.volume.strides = {0, 0, 0};  // packed C-order
        produced.volume.lifetime = samples;
        result.outputs.push_back(std::move(produced));
        result.provenance.algorithm_id = kernel_algorithm_id;
        result.provenance.algorithm_version = std::string();
        result.provenance.build_identity = "qgis_processing";
        result.provenance.params_json = params;
        publisher->publish_success(result);
    } else {
        pwb::science::IResultPublisherV1::Failure failure;
        failure.request_id = request_id;
        failure.code = cancelled ? "task.cancelled" : "algorithm.error";
        failure.message = error;
        failure.cancelled = cancelled;
        publisher->publish_failure(failure);
    }
    return publisher->outcome(request_id);
}

}  // namespace

AlgorithmRunner::AlgorithmRunner() {
    // Composition-root fallback: the provider is the single algorithm
    // authority. JobCenter's ctor also installs it (idempotent); hosts
    // that build a runner before any window still get the registry.
    pwb::qgis_processing::install_paleo_provider();
}

AlgorithmRunner::~AlgorithmRunner() = default;

std::string AlgorithmRunner::submit(
    const std::shared_ptr<PwbDataStore>& store, const std::string& algorithm_id,
    const std::map<std::string, std::string>& params,
    const std::string& input_version_id, std::string* error,
    CancelHook cancel_requested) {
    if (store == nullptr) {
        if (error != nullptr) *error = "no project store attached";
        return "";
    }
    const QString paleo_id = paleo_id_for(algorithm_id);
    const QgsProcessingAlgorithm* prototype =
        pwb::qgis_processing::paleo_algorithm_prototype(paleo_id);
    if (prototype == nullptr) {
        if (error != nullptr) {
            *error = "unknown algorithm id: " + algorithm_id
                + " (no paleo Processing algorithm for it)";
        }
        return "";
    }

    pwb::application::VolumePayload payload;
    pwb::viz::VolumeGeometryV1 geometry;
    const std::string load_error =
        load_version_volume(store, input_version_id, &payload, &geometry);
    if (!load_error.empty()) {
        if (error != nullptr) *error = load_error;
        return "";
    }

    // ':' would flow into run ids and staged payload file names; use the
    // dotted form ("paleo.seismic_rms_amplitude") instead.
    std::string dotted_id = paleo_id.toStdString();
    std::replace(dotted_id.begin(), dotted_id.end(), ':', '.');
    const std::string request_id =
        "run-" + dotted_id + "-" + std::to_string(
            g_request_counter.fetch_add(1));

    // Stage the input volume as the packed float32 file the Processing
    // algorithms take (PWBVOL1 payloads are already inline-major C order).
    QTemporaryDir staged_dir(
        QString::fromStdString(
            (store->project_file().parent_path() / ".pwb-runs-XXXXXX")
                .string()));
    if (!staged_dir.isValid()) {
        if (error != nullptr) *error = "cannot create staging directory";
        return "";
    }
    const QString input_path = staged_dir.filePath("input.f32");
    {
        QFile input(input_path);
        if (!input.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
            if (error != nullptr) {
                *error = "cannot stage input volume: "
                    + input.errorString().toStdString();
            }
            return "";
        }
        const qint64 byte_count = static_cast<qint64>(
            payload.samples.size() * sizeof(float));
        if (input.write(
                reinterpret_cast<const char*>(payload.samples.data()),
                byte_count) != byte_count) {
            if (error != nullptr) *error = "short write staging input volume";
            return "";
        }
    }

    QVariantMap parameters;
    parameters.insert(QStringLiteral("INPUT"), input_path);
    parameters.insert(QStringLiteral("SHAPE_IL"),
                      static_cast<qlonglong>(payload.header.ni));
    parameters.insert(QStringLiteral("SHAPE_XL"),
                      static_cast<qlonglong>(payload.header.nc));
    parameters.insert(
        QStringLiteral("SHAPE_SAMPLE"),
        static_cast<qlonglong>(payload.header.ns));
    encode_kernel_params(prototype, params, &parameters);
    const QString output_path = staged_dir.filePath("output.f32");
    parameters.insert(QStringLiteral("OUTPUT"), output_path);

    // Cancel bridge: the hook (job token / dialog) flips the Processing
    // feedback, which the paleo adapters translate into the kernel stop
    // token at their next safe point. The watcher thread is the only piece
    // that can observe the hook while the run blocks this thread.
    auto feedback = std::make_shared<QgsProcessingFeedback>();
    register_feedback(request_id, feedback);
    QVariantMap results;
    QString run_error;
    bool cancelled = false;
    bool ok = false;
    try {
        std::jthread cancel_watcher(
            [hook = std::move(cancel_requested),
             raw = feedback.get()](std::stop_token stop) {
                while (!stop.stop_requested()) {
                    if (hook && hook()) {
                        raw->cancel();
                        return;
                    }
                    std::this_thread::sleep_for(std::chrono::milliseconds(50));
                }
            });
        ok = pwb::qgis_processing::run_paleo_algorithm(
            paleo_id, parameters, /*project=*/nullptr, feedback.get(),
            results, run_error, &cancelled);
        // The watcher joins here (scope exit), while `feedback` is still
        // alive — no dangling raw pointer window.
    } catch (...) {
        unregister_feedback(request_id);
        throw;
    }
    unregister_feedback(request_id);

    // B-row parity: the catalog run operation keeps the science-kernel id
    // ("seismic.<name>") the old TaskRuntime rail published.
    const std::string kernel_id = science_id_from_paleo(paleo_id);
    const std::string run_error_std = run_error.toStdString();

    // Publish (durable run row + version) on THIS thread — the publisher is
    // thread-safe by contract (serialized store writes). A throwing publish
    // is a failed run (TaskRuntime's "publisher.publish_threw" parity),
    // never a silent success.
    std::shared_ptr<std::vector<float>> samples;
    if (ok) {
        const std::string read_error = read_f32_volume(output_path, &samples);
        if (!read_error.empty()) {
            Outcome outcome;
            outcome.known = true;
            outcome.status = "failed";
            outcome.error_code = "output.unreadable";
            outcome.error = read_error;
            const std::scoped_lock lock(mutex_);
            finished_[request_id] = outcome;
            if (error != nullptr) *error = read_error;
            return "";
        }
    }
    CatalogResultPublisher::Outcome published;
    std::string publish_error;
    try {
        published = publish_run_outcome(
            store, store->project_file().parent_path() / ".pwb-runs",
            request_id, geometry, params, input_version_id, kernel_id,
            samples,
            {static_cast<std::int64_t>(payload.header.ni),
             static_cast<std::int64_t>(payload.header.nc),
             static_cast<std::int64_t>(payload.header.ns)},
            ok, cancelled, run_error_std);
    } catch (const std::exception& failure) {
        publish_error = failure.what();
    }

    Outcome outcome;
    outcome.known = true;
    outcome.status = ok && publish_error.empty()
                         ? "succeeded"
                         : (cancelled ? "cancelled" : "failed");
    outcome.run_id = published.run_id;
    if (outcome.status == "succeeded") {
        outcome.version_id = published.version_id;
    } else {
        outcome.error_code = cancelled ? "task.cancelled" : "algorithm.error";
        if (!publish_error.empty()) {
            outcome.error_code = "publisher.publish_threw";
            outcome.error = publish_error;
        } else {
            outcome.error = published.error.empty() ? run_error_std
                                                    : published.error;
        }
    }
    {
        const std::scoped_lock lock(mutex_);
        finished_[request_id] = outcome;
    }
    if (outcome.status != "succeeded") {
        if (error != nullptr) {
            *error = outcome.error.empty() ? "algorithm failed"
                                           : outcome.error;
        }
        return "";
    }
    return request_id;
}

AlgorithmRunner::Outcome AlgorithmRunner::outcome(
    const std::string& request_id) {
    const std::scoped_lock lock(mutex_);
    const auto it = finished_.find(request_id);
    return it == finished_.end() ? Outcome{} : it->second;
}

// BEGIN CONV-30
bool AlgorithmRunner::cancel(const std::string& request_id) {
    std::shared_ptr<QgsProcessingFeedback> feedback;
    {
        const std::scoped_lock lock(mutex_);
        const auto it = active_.find(request_id);
        if (it == active_.end()) return false;
        feedback = it->second;
    }
    // Cross-thread by design (QgsFeedback::cancel); the paleo adapters
    // bridge it into the kernel stop token immediately.
    if (feedback != nullptr) feedback->cancel();
    return true;
}
// END CONV-30

void AlgorithmRunner::register_feedback(
    const std::string& request_id,
    std::shared_ptr<QgsProcessingFeedback> feedback) {
    const std::scoped_lock lock(mutex_);
    active_[request_id] = feedback;
}

void AlgorithmRunner::unregister_feedback(const std::string& request_id) {
    const std::scoped_lock lock(mutex_);
    active_.erase(request_id);
}

}  // namespace pwb::application
