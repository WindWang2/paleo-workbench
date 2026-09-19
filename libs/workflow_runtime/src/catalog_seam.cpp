// catalog_seam.cpp — RuntimeStore, the deterministic in-memory
// CatalogRepository (see include/pwb/workflow_runtime/catalog_seam.hpp).

#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <pwb/domain/sha256.hpp>

#include <algorithm>
#include <cstdio>
#include <stdexcept>
#include <utility>

namespace pwb::workflow_runtime {

namespace {
std::string padded_counter(const char* prefix, unsigned long value) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%s%06lu", prefix, value);
    return buf;
}

// Largest numeric suffix of `<prefix><number>` ids (padded_counter order).
template <typename Records, typename Field>
unsigned long max_numeric_suffix(const Records& records, Field field) {
    unsigned long max_value = 0;
    for (const auto& record : records) {
        const std::string& id = (record.*field);
        std::size_t pos = id.size();
        while (pos > 0 && id[pos - 1] >= '0' && id[pos - 1] <= '9') {
            --pos;
        }
        if (pos < id.size()) {
            const unsigned long value = std::strtoul(id.c_str() + pos, nullptr, 10);
            if (value > max_value) max_value = value;
        }
    }
    return max_value;
}
}  // namespace

RuntimeStore::RuntimeStore(Clock clock) : clock_(std::move(clock)) {}

std::string RuntimeStore::next_time() {
    if (clock_) return clock_();
    // Default deterministic clock: 2026-01-01T00:00:00Z + 1s per call.
    const long total = tick_++;
    const long hours = (total / 3600) % 24;  // wrap: stay a valid clock
    const long minutes = (total % 3600) / 60;
    const long seconds = total % 60;
    char buf[40];
    std::snprintf(buf, sizeof(buf), "2026-01-01T%02ld:%02ld:%02ld", hours,
                  minutes, seconds);
    return buf;
}

void RuntimeStore::restore_state(std::vector<AssetRecord> assets,
                                 std::vector<VersionRecord> versions,
                                 std::vector<RunRecord> runs) {
    assets_ = std::move(assets);
    versions_ = std::move(versions);
    runs_ = std::move(runs);
    asset_index_.clear();
    version_index_.clear();
    run_index_.clear();
    asset_versions_index_.clear();
    for (std::size_t i = 0; i < assets_.size(); ++i) {
        if (!asset_index_.emplace(assets_[i].id, i).second) {
            throw std::invalid_argument("duplicate asset id in store: " +
                                        assets_[i].id);
        }
    }
    for (std::size_t i = 0; i < versions_.size(); ++i) {
        if (!version_index_.emplace(versions_[i].version_id, i).second) {
            throw std::invalid_argument("duplicate version id in store: " +
                                        versions_[i].version_id);
        }
        asset_versions_index_[versions_[i].asset_id].push_back(i);
    }
    for (std::size_t i = 0; i < runs_.size(); ++i) {
        if (!run_index_.emplace(runs_[i].run_id, i).second) {
            throw std::invalid_argument("duplicate run id in store: " +
                                        runs_[i].run_id);
        }
    }
    // Counters resume past the LARGEST loaded id — container size would
    // collide after a snapshot with gaps (fail-closed hardening).
    next_asset_ = max_numeric_suffix(assets_, &AssetRecord::id);
    next_version_ = max_numeric_suffix(versions_, &VersionRecord::version_id);
    next_run_ = max_numeric_suffix(runs_, &RunRecord::run_id);
}

std::vector<AssetRecord> RuntimeStore::list_assets() { return assets_; }

std::optional<AssetRecord> RuntimeStore::resolve_asset(
    const std::string& asset_id) {
    const auto it = asset_index_.find(asset_id);
    if (it == asset_index_.end()) return std::nullopt;
    return assets_[it->second];
}

std::vector<VersionRecord> RuntimeStore::list_versions(
    const std::string& asset_id) {
    const auto it = asset_versions_index_.find(asset_id);
    if (it == asset_versions_index_.end()) return {};
    std::vector<VersionRecord> out;
    out.reserve(it->second.size());
    for (std::size_t idx : it->second) {
        out.push_back(versions_[idx]);
    }
    return out;
}

std::optional<VersionRecord> RuntimeStore::resolve_version(
    const std::string& version_id) {
    const auto it = version_index_.find(version_id);
    if (it == version_index_.end()) return std::nullopt;
    return versions_[it->second];
}

std::vector<RunRecord> RuntimeStore::list_runs() { return runs_; }

std::optional<RunRecord> RuntimeStore::resolve_run(const std::string& run_id) {
    const auto it = run_index_.find(run_id);
    if (it == run_index_.end()) return std::nullopt;
    return runs_[it->second];
}

std::string RuntimeStore::register_run(
    const std::string& operation,
    const std::vector<std::string>& input_version_ids, const Json& parameters,
    const std::optional<std::string>& generator_version,
    const std::string& status, const std::optional<std::string>& domain_task_id,
    const std::optional<std::string>& input_snapshot_hash,
    const std::optional<std::string>& actor) {
    RunRecord run;
    run.run_id = padded_counter("run_", ++next_run_);
    run.operation = operation;
    run.input_version_ids = input_version_ids;
    run.parameters = parameters;
    run.generator_version = generator_version;
    run.domain_task_id = domain_task_id;
    run.input_snapshot_hash = input_snapshot_hash;
    run.status = status;
    run.started_at = next_time();
    run.actor = actor;
    runs_.push_back(std::move(run));
    run_index_[runs_.back().run_id] = runs_.size() - 1;
    return runs_.back().run_id;
}

RegisteredAssetVersion RuntimeStore::register_result_asset(
    const std::string& name, const std::string& type,
    const std::string& format, const Json& asset_metadata,
    const std::string& payload_json, const std::string& stage,
    const std::string& run_id, const Json& version_metadata) {
    AssetRecord asset;
    asset.id = padded_counter("asset_", ++next_asset_);
    asset.name = name;
    asset.type = type;
    asset.format = format;
    asset.metadata = asset_metadata;
    assets_.push_back(std::move(asset));
    asset_index_[assets_.back().id] = assets_.size() - 1;

    VersionRecord version;
    version.asset_id = assets_.back().id;
    version.version_id = padded_counter("ver_", ++next_version_);
    version.name = name;
    version.producing_run_id = run_id;
    version.checksum = pwb::domain::Sha256::of_bytes(payload_json);
    version.created_at = next_time();
    version.metadata = version_metadata;
    version.payload_json = payload_json;
    assets_.back().current_version_id = version.version_id;
    versions_.push_back(std::move(version));
    asset_versions_index_[versions_.back().asset_id].push_back(
        versions_.size() - 1);
    version_index_[versions_.back().version_id] = versions_.size() - 1;

    // stage is recorded in version metadata parity surface (RAW/DERIVED).
    versions_.back().metadata["stage"] = stage;
    return {assets_.back().id, versions_.back().version_id};
}

std::string RuntimeStore::register_version(
    const std::string& asset_id, const std::string& payload_json,
    const std::string& stage, const std::vector<std::string>& parent_version_ids,
    const std::string& run_id, const Json& metadata) {
    const auto it = asset_index_.find(asset_id);
    if (it == asset_index_.end()) {
        throw std::invalid_argument("unknown asset: " + asset_id);
    }
    VersionRecord version;
    version.asset_id = asset_id;
    version.version_id = padded_counter("ver_", ++next_version_);
    version.name = assets_[it->second].name;
    version.producing_run_id = run_id;
    version.checksum = pwb::domain::Sha256::of_bytes(payload_json);
    version.created_at = next_time();
    version.metadata = metadata;
    version.metadata["stage"] = stage;
    if (!parent_version_ids.empty()) {
        version.metadata["parent_version_ids"] = parent_version_ids;
    }
    version.payload_json = payload_json;
    versions_.push_back(std::move(version));
    asset_versions_index_[asset_id].push_back(versions_.size() - 1);
    version_index_[versions_.back().version_id] = versions_.size() - 1;
    return versions_.back().version_id;
}

void RuntimeStore::update_run_status(const std::string& run_id,
                                     const std::string& status) {
    const auto it = run_index_.find(run_id);
    if (it == run_index_.end()) {
        throw std::invalid_argument("unknown run: " + run_id);
    }
    runs_[it->second].status = status;
    if (status == "complete" || status == "failed" || status == "cancelled") {
        runs_[it->second].finished_at = next_time();
    }
}

void RuntimeStore::update_run_status(const std::string& run_id,
                                     const std::string& status,
                                     const Json& extra_parameters) {
    const auto it = run_index_.find(run_id);
    if (it == run_index_.end()) {
        throw std::invalid_argument("unknown run: " + run_id);
    }
    update_run_status(run_id, status);
    if (extra_parameters.is_object()) {
        Json& metadata = runs_[it->second].run_metadata;
        if (!metadata.is_object()) metadata = Json::object();
        for (auto entry = extra_parameters.begin();
             entry != extra_parameters.end(); ++entry) {
            metadata[entry.key()] = entry.value();
        }
    }
}

void RuntimeStore::set_current_version(const std::string& asset_id,
                                       const std::string& version_id) {
    const auto it = asset_index_.find(asset_id);
    if (it == asset_index_.end()) {
        throw std::invalid_argument("unknown asset: " + asset_id);
    }
    assets_[it->second].current_version_id = version_id;
}

void RuntimeStore::attach_run_output(const std::string& run_id,
                                     const std::string& version_id) {
    const auto it = run_index_.find(run_id);
    if (it == run_index_.end()) {
        throw std::invalid_argument("unknown run: " + run_id);
    }
    auto& outputs = runs_[it->second].output_version_ids;
    if (std::find(outputs.begin(), outputs.end(), version_id) ==
        outputs.end()) {
        outputs.push_back(version_id);
    }
}

std::optional<std::string> RuntimeStore::verify_integrity(
    const std::string& version_id) {
    const auto it = version_index_.find(version_id);
    if (it == version_index_.end()) return std::nullopt;
    const VersionRecord& ver = versions_[it->second];
    if (ver.checksum.empty()) return std::nullopt;
    const std::string actual =
        pwb::domain::Sha256::of_bytes(ver.payload_json);
    return actual == ver.checksum ? std::optional<std::string>("verified")
                                  : std::optional<std::string>("modified");
}

}  // namespace pwb::workflow_runtime
