#include <pwb/closure_science/catalog_envelope_publisher.hpp>

#include <pwb/domain/diagnostics.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/science/types.hpp>

#include <atomic>
#include <cctype>
#include <fstream>
#include <stdexcept>
#include <utility>

namespace pwb::closure_science {

using pwb::domain::Json;
using pwb::science::AlgorithmResultV1;

namespace {

[[nodiscard]] std::string sanitize_segment(const std::string& raw) {
    std::string safe;
    safe.reserve(raw.size());
    for (char c : raw) {
        safe.push_back((std::isalnum(static_cast<unsigned char>(c)) || c == '-'
                        || c == '_' || c == '.')
                           ? c
                           : '_');
    }
    if (safe.empty() || safe == "." || safe == "..") {
        safe = "unnamed";
    }
    return safe;
}

[[nodiscard]] std::string now_iso() { return domain::now_iso8601(); }

void atomic_write(const std::filesystem::path& target,
                  const std::string& content) {
    std::filesystem::create_directories(target.parent_path());
    static std::atomic<unsigned long long> counter{0};
    const std::filesystem::path tmp =
        target.parent_path() / (".tmp-" + std::to_string(counter.fetch_add(1)));
    {
        std::ofstream stream(tmp, std::ios::binary | std::ios::trunc);
        if (!stream.good()) throw std::runtime_error("cannot write " + tmp.string());
        stream.write(content.data(), static_cast<std::streamsize>(content.size()));
        stream.flush();
        if (!stream.good()) {
            stream.close();
            std::filesystem::remove(tmp);
            throw std::runtime_error("short write to " + tmp.string());
        }
    }
    std::error_code ec;
    std::filesystem::rename(tmp, target, ec);
    if (ec) {
        std::filesystem::remove(tmp);
        throw std::runtime_error("cannot move " + tmp.string() + " to " +
                                 target.string());
    }
}

[[nodiscard]] Json provenance_json(const pwb::science::ProvenanceRecord& source) {
    Json provenance = Json::object();
    provenance["algorithm_id"] = source.algorithm_id;
    provenance["algorithm_version"] = source.algorithm_version;
    provenance["build_identity"] = source.build_identity;
    Json params = Json::object();
    for (const auto& [key, value] : source.params_json) {
        params[key] = value;
    }
    provenance["params_json"] = std::move(params);
    Json inputs = Json::array();
    for (const auto& ref : source.input_refs) {
        inputs.push_back(Json{{"asset_id", ref.asset_id},
                              {"version_id", ref.version_id},
                              {"path", ref.path}});
    }
    provenance["input_refs"] = std::move(inputs);
    provenance["started_utc"] = source.started_utc;
    provenance["finished_utc"] = source.finished_utc;
    provenance["approximate"] = source.approximate;
    provenance["wall_time_ms"] = source.wall_time_ms;
    return provenance;
}

}  // namespace

CatalogEnvelopePublisher::CatalogEnvelopePublisher(
    catalog::CatalogDocument& document, catalog::SaveHook save,
    std::filesystem::path publish_root, std::filesystem::path project_dir)
    : document_(document),
      save_(std::move(save)),
      publish_root_(std::move(publish_root)),
      project_dir_(std::move(project_dir)) {
    std::error_code ec;
    std::filesystem::create_directories(publish_root_, ec);
    if (ec) {
        throw std::runtime_error("CatalogEnvelopePublisher: cannot create " +
                                 publish_root_.string() + ": " + ec.message());
    }
}

std::string CatalogEnvelopePublisher::last_output_version_id() const {
    const std::lock_guard<std::mutex> lock(mutex_);
    return last_output_version_id_;
}

std::string CatalogEnvelopePublisher::last_run_id() const {
    const std::lock_guard<std::mutex> lock(mutex_);
    return last_run_id_;
}

void CatalogEnvelopePublisher::publish_success(
    const AlgorithmResultV1& result) {
    const std::lock_guard<std::mutex> lock(mutex_);
    const std::filesystem::path dir = publish_root_ / sanitize_segment(result.request_id);
    std::error_code ec;
    std::filesystem::create_directories(dir, ec);
    if (ec) {
        throw std::runtime_error("publish_success: cannot create " + dir.string());
    }

    // Directory contract (science_service DirectoryEnvelopePublisher
    // parity): envelope.json first record wins; volume-only results still
    // publish a minimal envelope.
    std::string envelope_content;
    bool envelope_record = false;
    for (const auto& record : result.records) {
        if (record.name == "envelope" && !envelope_record) {
            envelope_content = record.content_json;
            envelope_record = true;
            continue;
        }
        atomic_write(dir / "records" / sanitize_segment(record.name),
                     record.content_json);
    }
    if (!envelope_record) {
        // Volume-only result: still publish a minimal envelope so the
        // directory contract (envelope.json always present) holds.
        Json env = Json::object();
        env["schema_version"] = 1;
        env["result_type"] = "algorithm_result";
        env["algorithm_id"] = result.provenance.algorithm_id;
        env["payload"] = Json::object();
        envelope_content = pwb::domain::dump_json_python_compatible(env);
    }
    atomic_write(dir / "envelope.json", envelope_content);
    atomic_write(dir / "result.json",
                 pwb::domain::dump_json_python_compatible(
                     Json{{"request_id", result.request_id},
                          {"provenance", provenance_json(result.provenance)},
                          {"diagnostics", [&] {
                               Json array = Json::array();
                               for (const auto& d : result.diagnostics) {
                                   array.push_back(Json{{"code", d.code},
                                                        {"severity", d.severity},
                                                        {"message", d.message}});
                               }
                               return array;
                           }()}}));

    // Catalog rows: one run (lineage from the provenance input refs) + one
    // DERIVED version over the request directory (envelope member first).
    catalog::DataRun run;
    run.id = domain::RunId(domain::make_id("run_"));
    run.operation = "science:" + result.provenance.algorithm_id;
    for (const auto& ref : result.provenance.input_refs) {
        if (!ref.version_id.empty()) {
            run.input_version_ids.push_back(
                domain::VersionId(ref.version_id));
        }
    }
    run.parameters = Json{
        {"request_id", result.request_id},
        {"algorithm_id", result.provenance.algorithm_id},
        {"algorithm_version", result.provenance.algorithm_version},
        {"build_identity", result.provenance.build_identity},
        {"_finished_at", now_iso()}};
    run.generator = "science-service-v1";
    run.status = "complete";
    run.created_at = now_iso();

    catalog::DataAsset asset;
    asset.id = domain::AssetId(domain::make_id("asset_"));
    asset.name = result.provenance.algorithm_id + " 结果";
    asset.type = "science_result";
    asset.metadata = Json{
        {"kind", "science-envelope"},
        {"result_type", envelope_record ? Json("envelope")
                                        : Json("algorithm_result")},
        {"request_id", result.request_id}};
    asset.created_at = now_iso();
    asset.updated_at = asset.created_at;

    catalog::DataVersion version;
    version.id = domain::VersionId(domain::make_id("ver_"));
    version.asset_id = asset.id;
    version.version_number = 1;
    version.stage = domain::DataStage::Derived;
    version.managed = true;
    if (!project_dir_.empty()) {
        std::filesystem::path relative =
            std::filesystem::relative(dir, project_dir_, ec);
        version.path = ec ? dir.string() : relative.generic_string();
    } else {
        version.path = dir.string();
    }
    version.format = "json";
    version.run_id = run.id;
    version.members.push_back(catalog::VersionMember{
        "envelope", "envelope.json", "envelope", 0, true, std::nullopt,
        std::nullopt});
    version.metadata = Json{
        {"kind", "science-envelope"},
        {"payload_kind", "envelope_dir"},
        {"request_id", result.request_id},
        {"algorithm_id", result.provenance.algorithm_id}};
    version.created_at = now_iso();

    document_.runs.push_back(run);
    document_.assets.push_back(asset);
    document_.versions.push_back(version);
    catalog::DirtySet dirty;
    dirty.runs.push_back(run.id.str());
    dirty.assets.push_back(asset.id.str());
    dirty.versions.push_back(version.id.str());
    auto saved = save_(dirty);
    if (saved.code != domain::ErrorCode::Ok) {
        document_.runs.pop_back();
        document_.assets.pop_back();
        document_.versions.pop_back();
        throw std::runtime_error("publish_success: catalog save failed: " +
                                 saved.message);
    }
    last_output_version_id_ = version.id.str();
    last_run_id_ = run.id.str();
}

void CatalogEnvelopePublisher::publish_failure(const Failure& failure) {
    const std::lock_guard<std::mutex> lock(mutex_);
    const std::filesystem::path dir =
        publish_root_ / sanitize_segment(failure.request_id);
    std::error_code ec;
    std::filesystem::create_directories(dir, ec);
    if (ec) {
        throw std::runtime_error("publish_failure: cannot create " + dir.string());
    }
    atomic_write(dir / "failure.json",
                 pwb::domain::dump_json_python_compatible(
                     Json{{"request_id", failure.request_id},
                          {"code", failure.code},
                          {"message", failure.message},
                          {"cancelled", failure.cancelled}}));
    // Honest visibility: the failed/cancelled request lands as a terminal
    // catalog run (never a fabricated output version).
    catalog::DataRun run;
    run.id = domain::RunId(domain::make_id("run_"));
    run.operation = "science:request";
    run.parameters = Json{
        {"request_id", failure.request_id},
        {"code", failure.code},
        {"error", failure.message},
        {"_finished_at", now_iso()}};
    run.generator = "science-service-v1";
    run.status = failure.cancelled ? "cancelled" : "failed";
    run.created_at = now_iso();
    document_.runs.push_back(run);
    catalog::DirtySet dirty;
    dirty.runs.push_back(run.id.str());
    auto saved = save_(dirty);
    if (saved.code != domain::ErrorCode::Ok) {
        document_.runs.pop_back();
        throw std::runtime_error("publish_failure: catalog save failed: " +
                                 saved.message);
    }
    last_run_id_ = run.id.str();
}

}  // namespace pwb::closure_science
