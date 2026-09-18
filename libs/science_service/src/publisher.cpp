// pwb::science_service — publisher implementations (CONV-28).

#include <pwb/science_service/publisher.hpp>

#include <pwb/domain/json.hpp>

#include <unistd.h>

#include <atomic>
#include <cctype>
#include <fstream>
#include <stdexcept>
#include <utility>

namespace pwb::science_service {

using pwb::domain::Json;

DirectoryEnvelopePublisher::DirectoryEnvelopePublisher(
    std::filesystem::path root)
    : root_(std::move(root)) {
    std::error_code ec;
    std::filesystem::create_directories(root_, ec);
    if (ec) {
        throw std::runtime_error("DirectoryEnvelopePublisher: cannot create "
                                 + root_.string() + ": " + ec.message());
    }
}

std::filesystem::path DirectoryEnvelopePublisher::request_dir(
    const std::string& request_id) const {
    // Sanitize: the request id is foreign input at this boundary — only
    // path-safe characters may reach the filesystem.
    std::string safe;
    safe.reserve(request_id.size());
    for (char c : request_id) {
        safe.push_back((std::isalnum(static_cast<unsigned char>(c)) || c == '-'
                        || c == '_' || c == '.')
                           ? c
                           : '_');
    }
    if (safe.empty() || safe == "." || safe == "..") {
        safe = "unnamed";
    }
    return root_ / safe;
}

void DirectoryEnvelopePublisher::atomic_write(
    const std::filesystem::path& target, const std::string& content) {
    std::filesystem::create_directories(target.parent_path());
    // Unique temp name in the target directory: pid + deterministic counter
    // (single publisher instance; the mutex serializes writes).
    static std::atomic<unsigned long long> counter{0};
    const std::filesystem::path tmp = target.parent_path()
        / (".tmp-" + std::to_string(::getpid()) + "-"
           + std::to_string(counter.fetch_add(1)));
    {
        std::ofstream stream(tmp, std::ios::binary | std::ios::trunc);
        if (!stream.good()) {
            throw std::runtime_error("cannot write " + tmp.string());
        }
        stream.write(content.data(), static_cast<std::streamsize>(content.size()));
        stream.flush();
        if (!stream.good()) {
            std::filesystem::remove(tmp);
            throw std::runtime_error("short write to " + tmp.string());
        }
    }
    std::filesystem::rename(tmp, target);
}

void DirectoryEnvelopePublisher::publish_success(
    const science::AlgorithmResultV1& result) {
    const std::lock_guard<std::mutex> lock(mutex_);
    const std::filesystem::path dir = request_dir(result.request_id);
    std::error_code ec;
    std::filesystem::create_directories(dir, ec);
    if (ec) {
        throw std::runtime_error("publish_success: cannot create "
                                 + dir.string() + ": " + ec.message());
    }
    // Envelope record (first match wins; volume-only algorithms have none).
    bool envelope_written = false;
    for (const auto& record : result.records) {
        if (record.name == "envelope" && !envelope_written) {
            atomic_write(dir / "envelope.json", record.content_json);
            envelope_written = true;
            continue;
        }
        atomic_write(dir / "records" / record.name, record.content_json);
    }
    if (!envelope_written) {
        // Volume-only result: still publish a minimal envelope so the
        // directory contract (envelope.json always present) holds.
        Json env = Json::object();
        env["schema_version"] = 1;
        env["result_type"] = "algorithm_result";
        env["algorithm_id"] = result.provenance.algorithm_id;
        env["payload"] = Json::object();
        atomic_write(dir / "envelope.json",
                     pwb::domain::dump_json_python_compatible(env));
    }
    // Full result dump (provenance + diagnostics + record index).
    Json dump = Json::object();
    dump["request_id"] = result.request_id;
    Json provenance = Json::object();
    provenance["algorithm_id"] = result.provenance.algorithm_id;
    provenance["algorithm_version"] = result.provenance.algorithm_version;
    provenance["build_identity"] = result.provenance.build_identity;
    provenance["params_json"] = result.provenance.params_json;
    Json inputs = Json::array();
    for (const auto& ref : result.provenance.input_refs) {
        inputs.push_back(Json{ref.asset_id, ref.version_id, ref.path});
    }
    provenance["input_refs"] = std::move(inputs);
    provenance["started_utc"] = result.provenance.started_utc;
    provenance["finished_utc"] = result.provenance.finished_utc;
    provenance["approximate"] = result.provenance.approximate;
    provenance["wall_time_ms"] = result.provenance.wall_time_ms;
    dump["provenance"] = std::move(provenance);
    Json diagnostics = Json::array();
    for (const auto& d : result.diagnostics) {
        diagnostics.push_back(Json{{"code", d.code},
                                   {"severity", d.severity},
                                   {"message", d.message}});
    }
    dump["diagnostics"] = std::move(diagnostics);
    Json outputs = Json::array();
    for (const auto& vol : result.outputs) {
        outputs.push_back(Json{{"name", vol.name},
                               {"unit", vol.unit},
                               {"shape", Json::array({vol.volume.shape[0],
                                                      vol.volume.shape[1],
                                                      vol.volume.shape[2]})}});
    }
    dump["outputs"] = std::move(outputs);
    Json records = Json::array();
    for (const auto& rec : result.records) {
        records.push_back(Json{{"name", rec.name},
                               {"media_type", rec.media_type}});
    }
    dump["records"] = std::move(records);
    atomic_write(dir / "result.json",
                 pwb::domain::dump_json_python_compatible(dump));
    last_dir_ = dir;
}

void DirectoryEnvelopePublisher::publish_failure(
    const science::IResultPublisherV1::Failure& failure) {
    const std::lock_guard<std::mutex> lock(mutex_);
    const std::filesystem::path dir = request_dir(failure.request_id);
    std::error_code ec;
    std::filesystem::create_directories(dir, ec);
    if (ec) {
        throw std::runtime_error("publish_failure: cannot create "
                                 + dir.string() + ": " + ec.message());
    }
    Json dump = Json::object();
    dump["request_id"] = failure.request_id;
    dump["code"] = failure.code;
    dump["message"] = failure.message;
    dump["cancelled"] = failure.cancelled;
    atomic_write(dir / "failure.json",
                 pwb::domain::dump_json_python_compatible(dump));
    last_dir_ = dir;
}

std::filesystem::path DirectoryEnvelopePublisher::last_request_dir() const {
    const std::lock_guard<std::mutex> lock(mutex_);
    return last_dir_;
}

void InMemoryCapturePublisher::publish_success(
    const science::AlgorithmResultV1& result) {
    const std::lock_guard<std::mutex> lock(mutex_);
    successes_.push_back(result);
}

void InMemoryCapturePublisher::publish_failure(
    const science::IResultPublisherV1::Failure& failure) {
    const std::lock_guard<std::mutex> lock(mutex_);
    failures_.push_back(failure);
}

std::vector<science::AlgorithmResultV1> InMemoryCapturePublisher::successes()
    const {
    const std::lock_guard<std::mutex> lock(mutex_);
    return successes_;
}

std::vector<science::IResultPublisherV1::Failure>
InMemoryCapturePublisher::failures() const {
    const std::lock_guard<std::mutex> lock(mutex_);
    return failures_;
}

}  // namespace pwb::science_service
