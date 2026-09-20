// Implementation of dependency_audit.hpp — branch-for-branch port of
// paleo_workbench/interchange/dependency_audit.py.
#include <pwb/interchange/dependency_audit.hpp>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <stdexcept>

namespace pwb::interchange {

namespace {

std::vector<std::filesystem::path> sorted_recursive_files(
    const std::filesystem::path& root) {
    std::vector<std::filesystem::path> out;
    std::error_code ec;
    for (auto it = std::filesystem::recursive_directory_iterator(
             root, std::filesystem::directory_options::none, ec);
         it != std::filesystem::recursive_directory_iterator(); it.increment(ec)) {
        if (ec) break;
        out.push_back(it->path());
    }
    std::sort(out.begin(), out.end());
    return out;
}

// Python st_mtime as a double (epoch seconds).
std::optional<double> epoch_mtime(const std::filesystem::path& path) {
    std::error_code ec;
    auto file_time = std::filesystem::last_write_time(path, ec);
    if (ec) return std::nullopt;
    const auto system_time =
        std::chrono::clock_cast<std::chrono::system_clock>(file_time);
    const auto since_epoch = system_time.time_since_epoch();
    return static_cast<double>(
               std::chrono::duration_cast<std::chrono::microseconds>(since_epoch)
                   .count()) /
           1e6;
}

}  // namespace

std::string_view to_string(DependencyStatus status) {
    switch (status) {
        case DependencyStatus::VALID: return "valid";
        case DependencyStatus::MISSING: return "missing";
        case DependencyStatus::CHANGED: return "changed";
        case DependencyStatus::UNKNOWN: return "unknown";
        case DependencyStatus::RELINK_CANDIDATE: return "relink_candidate";
    }
    return "missing";
}

Json RelinkCandidate::to_json() const {
    Json out = Json::object();
    out["path"] = path;
    out["size_bytes"] = size_bytes;
    out["sha256"] = sha256.has_value() ? Json(*sha256) : Json(nullptr);
    out["basis"] = basis;
    return out;
}

Json DependencyRecord::to_json() const {
    Json out = Json::object();
    out["version_id"] = version_id;
    out["asset"] = asset_name;
    out["managed"] = managed;
    out["path"] = path;
    out["status"] = std::string(to_string(status));
    out["observed_size"] =
        observed_size.has_value() ? Json(*observed_size) : Json(nullptr);
    if (observed_mtime.has_value()) {
        out["observed_mtime"] = *observed_mtime;
    } else {
        out["observed_mtime"] = Json(nullptr);
    }
    out["expected_size"] =
        expected_size.has_value() ? Json(*expected_size) : Json(nullptr);
    out["expected_sha256"] =
        expected_sha256.has_value() ? Json(*expected_sha256) : Json(nullptr);
    out["relink_candidates"] = Json::array();
    for (const auto& candidate : relink_candidates) {
        out["relink_candidates"].push_back(candidate.to_json());
    }
    out["detail"] = detail;
    return out;
}

Json DependencyAuditReport::summary() const {
    Json counts = Json::object();
    for (const auto& record : records) {
        const std::string key(to_string(record.status));
        counts[key] = counts.value(key, 0) + 1;
    }
    Json out = Json::object();
    out["total"] = static_cast<long long>(records.size());
    out["counts"] = std::move(counts);
    out["hashed_bytes"] = hashed_bytes;
    return out;
}

Json DependencyAuditReport::to_json() const {
    Json out = summary();
    out["records"] = Json::array();
    for (const auto& record : records) {
        out["records"].push_back(record.to_json());
    }
    return out;
}

bool DependencyAuditReport::ok() const {
    return std::all_of(records.begin(), records.end(), [](const auto& record) {
        return record.status == DependencyStatus::VALID ||
               record.status == DependencyStatus::UNKNOWN;
    });
}

DependencyAuditReport ExternalDependencyAuditor::audit(
    const CancelToken& cancel) const {
    DependencyAuditReport report;
    for (const auto& asset : catalog_->list_assets()) {
        cancel.checkpoint();
        for (const auto& version : catalog_->list_versions(asset.id)) {
            report.records.push_back(
                audit_version(version, asset.name, report));
        }
    }
    return report;
}

DependencyRecord ExternalDependencyAuditor::audit_version(
    const CatalogVersionRef& version, const std::string& asset_name,
    DependencyAuditReport& report) const {
    std::optional<std::filesystem::path> path;
    try {
        path = catalog_->resolve_path(version);
    } catch (...) {
        path = std::nullopt;
    }
    DependencyRecord record;
    record.version_id = version.id;
    record.asset_name = asset_name;
    record.managed = version.managed;
    record.path = path.has_value() ? path->string() : version.path;
    record.status = DependencyStatus::MISSING;
    if (version.size_bytes >= 0) {
        record.expected_size = version.size_bytes;
    }
    if (!version.sha256.empty()) {
        record.expected_sha256 = version.sha256;
    }

    std::error_code ec;
    if (!path.has_value() || !std::filesystem::is_regular_file(*path, ec)) {
        record.detail = "文件不存在";
        return record;
    }
    record.observed_size = static_cast<long long>(
        std::filesystem::file_size(*path, ec));
    if (ec) {
        record.status = DependencyStatus::UNKNOWN;
        record.detail = "无法读取文件大小";
        return record;
    }
    record.observed_mtime = epoch_mtime(*path);
    if (!version.managed && record.expected_sha256 == std::nullopt) {
        // link_external never hashes: existence-only reference.
        record.status = DependencyStatus::UNKNOWN;
        record.detail = "外部引用未记录校验和（无法验证内容）";
        return record;
    }
    if (record.expected_size.has_value() &&
        record.observed_size.has_value() &&
        *record.observed_size != *record.expected_size) {
        record.status = DependencyStatus::CHANGED;
        record.detail = "size 变化: 记录 " + std::to_string(*record.expected_size) +
                        "B，实际 " + std::to_string(*record.observed_size) + "B";
        return record;
    }
    if (record.expected_sha256 == std::nullopt) {
        record.status = DependencyStatus::UNKNOWN;
        record.detail = "无记录校验和";
        return record;
    }
    const long long file_size =
        record.observed_size.has_value() ? *record.observed_size : 0;
    if (report.hashed_bytes + file_size <= hash_budget_) {
        const auto digest = sha256_file(*path);
        report.hashed_bytes += file_size;
        if (digest.has_value() && *digest == *record.expected_sha256) {
            record.status = DependencyStatus::VALID;
        } else {
            record.status = DependencyStatus::CHANGED;
            record.detail = "sha256 不匹配（内容已变化）";
        }
    } else {
        record.status = DependencyStatus::UNKNOWN;
        record.detail = "超过哈希预算：未验证内容";
    }
    return record;
}

std::vector<RelinkCandidate> ExternalDependencyAuditor::find_relink_candidates(
    const DependencyRecord& record,
    const std::vector<std::filesystem::path>& search_roots, int max_candidates,
    const CancelToken& cancel) const {
    if (record.status != DependencyStatus::MISSING) {
        return {};
    }
    const std::optional<long long> expected_size = record.expected_size;
    const std::optional<std::string> expected_sha = record.expected_sha256;
    if (expected_size == std::nullopt && expected_sha == std::nullopt) {
        // No recorded identity at all: ANY file would "match". Refusing to
        // guess is the whole point — relink needs something to verify.
        return {};
    }
    std::vector<RelinkCandidate> candidates;
    for (const auto& root : search_roots) {
        std::error_code ec;
        if (!std::filesystem::is_directory(root, ec)) continue;
        for (const auto& path : sorted_recursive_files(root)) {
            cancel.checkpoint();
            std::error_code file_ec;
            if (!std::filesystem::is_regular_file(path, file_ec)) continue;
            if (std::filesystem::is_symlink(path, file_ec)) continue;
            const auto size = static_cast<long long>(
                std::filesystem::file_size(path, file_ec));
            if (file_ec) continue;
            if (expected_size.has_value() && size != *expected_size) continue;
            RelinkCandidate candidate;
            candidate.path = path.string();
            candidate.size_bytes = size;
            if (expected_sha.has_value() && size <= hash_budget_) {
                candidate.sha256 = sha256_file(path);
                candidate.basis = "size+hash";
            }
            candidates.push_back(std::move(candidate));
            if (static_cast<int>(candidates.size()) >= max_candidates) {
                return candidates;
            }
        }
    }
    // Verified (hash match) candidates first, then by path.
    std::stable_sort(candidates.begin(), candidates.end(),
                     [&expected_sha](const RelinkCandidate& a,
                                     const RelinkCandidate& b) {
                         const bool a_match =
                             a.sha256.has_value() && expected_sha.has_value() &&
                             *a.sha256 == *expected_sha;
                         const bool b_match =
                             b.sha256.has_value() && expected_sha.has_value() &&
                             *b.sha256 == *expected_sha;
                         if (a_match != b_match) return a_match > b_match;
                         return a.path < b.path;
                     });
    return candidates;
}

void ExternalDependencyAuditor::attach_candidates(
    DependencyAuditReport& report,
    const std::vector<std::filesystem::path>& search_roots,
    const CancelToken& cancel) const {
    for (auto& record : report.records) {
        cancel.checkpoint();
        if (record.status != DependencyStatus::MISSING) continue;
        record.relink_candidates =
            find_relink_candidates(record, search_roots, 20, cancel);
        if (!record.relink_candidates.empty()) {
            record.status = DependencyStatus::RELINK_CANDIDATE;
        }
    }
}

ILinkableCatalog::LinkResult ExternalDependencyAuditor::apply_relink(
    const DependencyRecord& record, const RelinkCandidate& candidate,
    bool confirm_unverified, const std::optional<std::string>& asset_name) const {
    if (record.expected_sha256.has_value() && candidate.sha256.has_value() &&
        *candidate.sha256 != *record.expected_sha256) {
        throw RelinkError("候选文件校验和与记录不一致：拒绝重连");
    }
    if (record.expected_sha256.has_value() && !candidate.sha256.has_value() &&
        !confirm_unverified) {
        throw RelinkError(
            "候选未经内容校验（size-only）：需人工确认 confirm_unverified=True");
    }
    Json metadata = Json::object();
    metadata["relinked_from"] = record.version_id;
    metadata["relink_basis"] = candidate.basis;
    return catalog_->link_external(candidate.path,
                                   asset_name.value_or(record.asset_name),
                                   std::move(metadata));
}

}  // namespace pwb::interchange
