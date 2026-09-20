#include "pwb/catalog/refs.hpp"
#include "pwb/catalog/checksum.hpp"

#include <atomic>
#include <chrono>
#include <cstdio>
#include <random>
#include <sys/stat.h>

namespace pwb::catalog {

std::optional<IntegrityStatus> integrity_status_from_string(
    std::string_view value) {
    if (value == "verified") return IntegrityStatus::Verified;
    if (value == "modified") return IntegrityStatus::Modified;
    if (value == "missing") return IntegrityStatus::Missing;
    if (value == "unknown") return IntegrityStatus::Unknown;
    return std::nullopt;
}

std::string utc_now_iso() {
    // datetime.now(timezone.utc).isoformat(): YYYY-MM-DDTHH:MM:SS.ffffff+00:00
    using namespace std::chrono;
    const auto now = system_clock::now();
    const std::time_t secs = system_clock::to_time_t(now);
    const auto usec = duration_cast<microseconds>(now.time_since_epoch()).count() % 1'000'000;
    std::tm tm{};
#if defined(_WIN32)
    gmtime_s(&tm, &secs);
#else
    gmtime_r(&secs, &tm);
#endif
    char buffer[64];
    std::snprintf(buffer, sizeof(buffer), "%04d-%02d-%02dT%02d:%02d:%02d.%06lld+00:00",
                  tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour, tm.tm_min,
                  tm.tm_sec, static_cast<long long>(usec));
    return buffer;
}

std::string new_ref_id(const std::string& prefix) {
    // uuid4().hex[:16] — random, non-enumerable, same shape as Python.
    static std::atomic<std::uint64_t> counter{0};
    std::random_device rd;
    const std::uint64_t a = (static_cast<std::uint64_t>(rd()) << 32) ^ rd();
    const std::uint64_t b = counter.fetch_add(1) + a;
    char buffer[17];
    std::snprintf(buffer, sizeof(buffer), "%016llx",
                  static_cast<unsigned long long>(b));
    return prefix + "_" + buffer;
}

namespace {
std::string stage_wire(domain::DataStage stage) {
    return std::string(domain::to_string(stage));
}

domain::Json optional_string(const std::optional<std::string>& value) {
    return value.has_value() ? domain::Json(*value) : domain::Json();
}

domain::Json tags_wire(const std::vector<std::string>& tags) {
    domain::Json out = domain::Json::array();
    for (const auto& tag : tags) out.push_back(tag);
    return out;
}

// view.py _probe-style first rung: project-relative join or the recorded
// absolute path (the full relocation ladder stays a service-side concern).
std::filesystem::path default_resolve(const DataVersion& version) {
    std::filesystem::path raw(version.path);
    if (raw.is_absolute()) return raw;
    return raw;  // caller joins with the project dir when relative
}
}  // namespace

domain::Json DataVersionRef::to_dict() const {
    domain::Json out = domain::Json::object();
    out["asset_id"] = asset_id;
    out["version_id"] = version_id;
    out["name"] = name;
    out["stage"] = stage_wire(stage);
    out["path"] = path;
    out["checksum"] = optional_string(checksum);
    out["external"] = external;
    out["producing_run_id"] = optional_string(producing_run_id);
    out["created_at"] = created_at;
    out["tags"] = tags_wire(tags);
    out["kind"] = kind;
    out["format"] = format_field;
    out["integrity"] = std::string(to_string(integrity));
    out["legacy_resource_id"] = optional_string(legacy_resource_id);
    out["trashed"] = trashed;
    out["version_number"] = version_number;
    return out;
}

domain::Result<DataVersionRef> DataVersionRef::from_dict(
    const domain::Json& data) {
    if (!data.is_object() || !data.contains("asset_id") ||
        !data.contains("version_id")) {
        return domain::DataError(domain::ErrorCode::InvalidArgument,
                                 "version ref requires asset_id and version_id");
    }
    DataVersionRef ref;
    ref.asset_id = data["asset_id"].get<std::string>();
    ref.version_id = data["version_id"].get<std::string>();
    ref.name = data.value("name", std::string());
    std::string stage_text = data.value("stage", std::string("intermediate"));
    // types.py _coerce_stage: strip().lower() then DataStage(value) — an
    // unknown vocabulary raises.
    stage_text.erase(0, stage_text.find_first_not_of(" \t\r\n"));
    stage_text.erase(stage_text.find_last_not_of(" \t\r\n") + 1);
    for (char& c : stage_text) {
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    }
    auto stage = domain::data_stage_from_string(stage_text);
    if (!stage.has_value()) {
        return domain::DataError(domain::ErrorCode::InvalidArgument,
                                 "'" + stage_text + "' is not a valid DataStage");
    }
    ref.stage = *stage;
    ref.path = data.value("path", std::string());
    if (data.contains("checksum") && data["checksum"].is_string()) {
        ref.checksum = data["checksum"].get<std::string>();
    }
    ref.external = data.value("external", false);
    if (data.contains("producing_run_id") && data["producing_run_id"].is_string()) {
        ref.producing_run_id = data["producing_run_id"].get<std::string>();
    }
    ref.created_at = data.value("created_at", std::string());
    if (ref.created_at.empty()) ref.created_at = utc_now_iso();
    if (data.contains("tags") && data["tags"].is_array()) {
        for (const auto& tag : data["tags"]) {
            if (tag.is_string()) ref.tags.push_back(tag.get<std::string>());
        }
    }
    ref.kind = data.value("kind", std::string());
    ref.format_field = data.value("format", std::string());
    std::string integrity_text = data.value("integrity", std::string("unknown"));
    auto integrity = integrity_status_from_string(integrity_text);
    ref.integrity = integrity.value_or(IntegrityStatus::Unknown);
    if (data.contains("legacy_resource_id") &&
        data["legacy_resource_id"].is_string()) {
        ref.legacy_resource_id = data["legacy_resource_id"].get<std::string>();
    }
    ref.trashed = data.value("trashed", false);
    ref.version_number = data.value("version_number", 0);
    return ref;
}

domain::Json DataRunRef::to_dict() const {
    domain::Json out = domain::Json::object();
    out["run_id"] = run_id;
    out["operation"] = operation;
    out["input_version_ids"] = tags_wire(input_version_ids);
    out["output_version_ids"] = tags_wire(output_version_ids);
    out["parameters"] = parameters;
    out["generator_version"] = optional_string(generator_version);
    out["status"] = status;
    out["started_at"] = started_at;
    out["finished_at"] = optional_string(finished_at);
    out["domain_task_id"] = optional_string(domain_task_id);
    out["input_snapshot_hash"] = optional_string(input_snapshot_hash);
    return out;
}

DataRunRef DataRunRef::from_dict(const domain::Json& data) {
    DataRunRef run;
    run.run_id = data.at("run_id").get<std::string>();
    run.operation = data.at("operation").get<std::string>();
    auto read_ids = [&data](const char* key, std::vector<std::string>* out) {
        out->clear();
        if (data.contains(key) && data[key].is_array()) {
            for (const auto& id : data[key]) {
                if (id.is_string()) out->push_back(id.get<std::string>());
            }
        }
    };
    read_ids("input_version_ids", &run.input_version_ids);
    read_ids("output_version_ids", &run.output_version_ids);
    if (data.contains("parameters") && data["parameters"].is_object()) {
        run.parameters = data["parameters"];
    }
    auto read_opt = [&data](const char* key) {
        return (data.contains(key) && data[key].is_string())
                   ? std::optional<std::string>(data[key].get<std::string>())
                   : std::nullopt;
    };
    run.generator_version = read_opt("generator_version");
    run.status = data.value("status", std::string("running"));
    run.started_at = data.value("started_at", std::string());
    if (run.started_at.empty()) run.started_at = utc_now_iso();
    run.finished_at = read_opt("finished_at");
    run.domain_task_id = read_opt("domain_task_id");
    run.input_snapshot_hash = read_opt("input_snapshot_hash");
    return run;
}

domain::Json LineageEdgeRef::to_dict() const {
    domain::Json out = domain::Json::object();
    out["source_version_id"] = source_version_id;
    out["target_version_id"] = target_version_id;
    out["run_id"] = optional_string(run_id);
    return out;
}

std::optional<domain::Json> version_display_payload(
    const std::string& version_id, const DisplayContext& context) {
    if (context.document == nullptr || context.index == nullptr) {
        return std::nullopt;
    }
    const DataVersion* version = context.index->version(version_id);
    if (version == nullptr) return std::nullopt;
    const DataAsset* asset = context.index->asset(version->asset_id.str());
    if (asset == nullptr) return std::nullopt;

    const DataRun* run =
        version->run_id ? context.index->run(version->run_id->str()) : nullptr;

    // view.py went through verify_integrity (a full re-hash). The display
    // contract only needs the STATUS; probe shape: missing payload →
    // "missing", no recorded checksum → "unknown", else re-hash.
    std::string integrity_label = "unknown";
    {
        auto resolver = context.resolve_path ? context.resolve_path
                                             : &default_resolve;
        std::filesystem::path payload = resolver(*version);
#if defined(_WIN32)
        // MSVC stat() takes a narrow path; fs::path::c_str() is wchar_t
        // there. is_regular_file is the same probe S_ISREG made.
        std::error_code probe_ec{};
        const bool payload_is_regular =
            !payload.empty() && std::filesystem::is_regular_file(payload, probe_ec);
#else
        struct ::stat probe {};
        const bool payload_is_regular =
            !payload.empty() && ::stat(payload.c_str(), &probe) == 0 &&
            S_ISREG(probe.st_mode);
#endif
        if (payload_is_regular) {
            if (version->sha256.has_value() && !version->sha256->empty()) {
                auto digest = sha256_file(payload);
                integrity_label = (digest.is_ok() && digest.value() == *version->sha256)
                                      ? "verified" : "modified";
            } else {
                integrity_label = "unknown";  // nothing recorded to compare
            }
        } else {
            integrity_label = "missing";
        }
    }

    domain::Json inputs = domain::Json::array();
    for (const auto& parent : version->parent_version_ids) {
        const DataVersion* ancestor = context.index->version(parent.str());
        if (ancestor == nullptr) continue;
        const DataAsset* ancestor_asset =
            context.index->asset(ancestor->asset_id.str());
        domain::Json row = domain::Json::object();
        row["version_id"] = ancestor->id.str();
        row["name"] = ancestor_asset != nullptr ? ancestor_asset->name
                                                : ancestor->asset_id.str();
        row["stage"] = stage_wire(ancestor->stage);
        inputs.push_back(row);
    }

    domain::Json out = domain::Json::object();
    out["version_id"] = version->id.str();
    out["asset_id"] = version->asset_id.str();
    out["name"] = asset->name;
    out["stage"] = stage_wire(version->stage);
    out["path"] = version->path;
    out["format"] = version->format;
    out["kind"] = asset->type;  // view.py mirrors ref.kind ← asset type seam
    out["external"] = !version->managed;
    out["integrity"] = integrity_label;
    out["checksum"] = optional_string(version->sha256);
    out["created_at"] = version->created_at;
    out["tags"] = [&] {
        domain::Json tags = domain::Json::array();
        // Document association order (asset→version tags in Python carry the
        // display names of associated Tag entities).
        for (const auto& [owner, tag_id] : context.document->version_tags) {
            if (owner != version->id.str()) continue;
            for (const auto& tag : context.document->tags) {
                if (tag.id == tag_id) {
                    tags.push_back(tag.display_name.value_or(tag.name));
                }
            }
        }
        return tags;
    }();
    out["producing_run_id"] =
        version->run_id.has_value() ? domain::Json(version->run_id->str())
                                    : domain::Json();
    out["producing_operation"] =
        run != nullptr ? domain::Json(run->operation) : domain::Json();
    // adapter.py _run_ref: generator_version = run.generator or None.
    out["generator_version"] =
        run != nullptr && !run->generator.empty()
            ? domain::Json(run->generator)
            : domain::Json();
    out["inputs"] = inputs;
    return out;
}

}  // namespace pwb::catalog
