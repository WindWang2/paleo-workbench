#include "pwb/catalog/sources.hpp"
#include "pwb/catalog/checksum.hpp"
#include "pwb/catalog/refs.hpp"
#include "pwb/catalog/trash.hpp"

#include <sys/stat.h>

namespace pwb::catalog {

namespace {
using domain::DataError;
using domain::ErrorCode;
}  // namespace

std::filesystem::path missing_probe_path(const std::filesystem::path& project_path,
                                          const DataVersion& version) {
    std::error_code ec;
    const std::filesystem::path project_dir =
        std::filesystem::weakly_canonical(project_path.parent_path(), ec);
    const std::filesystem::path raw(version.path);
    if (version.managed) return project_dir / raw;
    if (raw.is_absolute()) return raw;
    return project_dir / raw;
}

std::vector<const MissingSource*> MissingSourceReport::relinkable() const {
    std::vector<const MissingSource*> out;
    for (const auto& entry : entries) {
        if (entry.relinkable) out.push_back(&entry);
    }
    return out;
}

MissingSourceReport find_missing_sources(
    const CatalogDocument& document, const DocumentIndex& index,
    const std::filesystem::path& project_path, bool include_managed,
    const std::function<bool()>& cancel) {
    MissingSourceReport report;
    for (const auto& version : document.versions) {
        if (cancel && cancel()) break;
        if (version.trashed) continue;
        if (!include_managed && version.managed) continue;
        report.scanned += 1;
        const DataAsset* asset = index.asset(version.asset_id.str());
        const std::filesystem::path probe = missing_probe_path(project_path, version);
        struct ::stat probe_stat {};
        const bool resolved =
            ::stat(probe.c_str(), &probe_stat) == 0 && S_ISREG(probe_stat.st_mode);
        if (resolved) continue;
        MissingSource entry;
        entry.version_id = version.id.str();
        entry.asset_id = version.asset_id.str();
        entry.asset_name = asset != nullptr ? asset->name : version.asset_id.str();
        entry.stage = version.stage;
        entry.managed = version.managed;
        entry.recorded_path = version.path;
        entry.source_uri = version.source_uri;
        entry.size_bytes = version.size_bytes;
        entry.relinkable = !version.managed && version.stage == domain::DataStage::Raw;
        if (version.metadata.is_object() && version.metadata.contains(kExternalStatKey) &&
            version.metadata[kExternalStatKey].is_object()) {
            entry.recorded_fingerprint = version.metadata[kExternalStatKey];
        }
        report.entries.push_back(std::move(entry));
    }
    return report;
}

std::optional<std::string> relink_identity_proof(
    const DataVersion& version, const std::filesystem::path& candidate) {
    if (version.sha256.has_value() && !version.sha256->empty()) {
        auto candidate_sha = sha256_file_or_none(candidate);
        if (!candidate_sha.has_value()) return std::nullopt;
        if (*candidate_sha != *version.sha256) return std::nullopt;
        return std::string("sha256");
    }
    if (version.metadata.is_object() && version.metadata.contains(kExternalStatKey) &&
        version.metadata[kExternalStatKey].is_object()) {
        const auto& fingerprint = version.metadata[kExternalStatKey];
        struct ::stat st {};
        if (::stat(candidate.c_str(), &st) == 0 &&
            fingerprint.contains("size") && fingerprint.contains("mtime_ns") &&
            fingerprint["size"].is_number_integer() &&
            fingerprint["mtime_ns"].is_number_integer() &&
            fingerprint["size"].get<std::int64_t>() == st.st_size &&
            fingerprint["mtime_ns"].get<std::int64_t>() ==
                static_cast<std::int64_t>(st.st_mtim.tv_nsec)) {
            return std::string("stat_fingerprint");
        }
    }
    return std::nullopt;
}

domain::DataError relink_external_source(
    CatalogDocument* document, const DocumentIndex& index,
    const std::string& version_id, const std::filesystem::path& new_path,
    const std::function<domain::DataError()>& save, const std::string& actor,
    const std::string& now_iso) {
    DataError invalid(ErrorCode::InvalidArgument, "");
    DataVersion* version = document->find_version_mut(domain::VersionId(version_id));
    if (version == nullptr) {
        return DataError(ErrorCode::NotFound, "Unknown version: " + version_id);
    }
    if (version->trashed) {
        return DataError(ErrorCode::InvalidArgument,
                         "Cannot relink a trashed version (restore it first)");
    }
    if (version->managed) {
        return DataError(ErrorCode::InvalidArgument,
                         "托管版本的载荷缺失属于损坏，不能改链接；请重新导入生成新版本");
    }
    if (version->stage != domain::DataStage::Raw) {
        return DataError(ErrorCode::InvalidArgument,
                         "只有外部 RAW 版本支持 relink；派生数据请重新生成");
    }
    struct ::stat candidate_stat {};
    if (::stat(new_path.c_str(), &candidate_stat) != 0 ||
        !S_ISREG(candidate_stat.st_mode)) {
        return DataError(ErrorCode::InvalidArgument,
                         "Candidate file not found: " + new_path.string());
    }
    auto proof = relink_identity_proof(*version, new_path);
    if (!proof.has_value()) {
        return DataError(ErrorCode::ConflictBaseVersion,
                         "无法证明新文件与记录是同一份数据（sha256 与 size+mtime 指纹均不符或"
                         "缺失）。为避免静默错绑已拒绝；若确为新数据，请走导入生成新版本。");
    }

    // Prior-field snapshot for the rollback path.
    const std::string prior_path = version->path;
    const std::optional<std::string> prior_uri = version->source_uri;
    const std::optional<std::int64_t> prior_size = version->size_bytes;
    const domain::Json prior_metadata = version->metadata;

    const std::string posix_path =
        std::filesystem::weakly_canonical(new_path).string();
    version->path = posix_path;
    version->source_uri = posix_path;
    version->size_bytes = candidate_stat.st_size;
    if (!version->metadata.is_object()) version->metadata = domain::Json::object();
    domain::Json stat_json = domain::Json::object();
    stat_json["size"] = candidate_stat.st_size;
    stat_json["mtime_ns"] = static_cast<std::int64_t>(candidate_stat.st_mtim.tv_nsec);
    version->metadata[kExternalStatKey] = std::move(stat_json);
    domain::Json history = domain::Json::array();
    if (version->metadata.contains(kRelinkHistoryKey) &&
        version->metadata[kRelinkHistoryKey].is_array()) {
        history = version->metadata[kRelinkHistoryKey];
    }
    domain::Json entry = domain::Json::object();
    entry["at"] = now_iso.empty() ? utc_now_iso() : now_iso;
    entry["proof"] = *proof;
    entry["old_path"] = prior_path;
    entry["new_path"] = posix_path;
    entry["actor"] = actor;
    history.push_back(std::move(entry));
    version->metadata[kRelinkHistoryKey] = std::move(history);

    DataError error = save ? save() : DataError(ErrorCode::Ok, "");
    if (!error.ok()) {
        version->path = prior_path;
        version->source_uri = prior_uri;
        version->size_bytes = prior_size;
        version->metadata = prior_metadata;
    }
    (void)index;
    (void)invalid;
    return error;
}

}  // namespace pwb::catalog
