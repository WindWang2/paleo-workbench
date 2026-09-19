// pwb::interchange — project-level external dependency audit, a faithful C++
// port of paleo_workbench/interchange/dependency_audit.py (I13).
//
// Classifies every external reference (and managed payload) as valid /
// missing / changed / unknown / relink_candidate and produces content-
// verified relink candidates for missing ones. Hard rules preserved:
//   * identity is size + sha256 (mtime informational only); a same-basename
//     file with a different hash is NEVER auto-relinked;
//   * apply_relink does not mutate catalog history — it registers a NEW
//     external version through the catalog seam, so the catalog stays the
//     single write authority;
//   * hashing has a global budget; over budget degrades to unknown, never
//     to a fake verdict.
//
// Catalog seam: the Python auditor walks the live catalog object; C++ uses
// ILinkableCatalog — the package builder's CatalogSource plus an optional
// sha256 per version (the field lives on CatalogVersionRef) and the
// link_external write port. Qt-free, Python-free.
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/interchange/contracts.hpp>
#include <pwb/interchange/package_runtime.hpp>

#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace pwb::interchange {

using Json = pwb::domain::Json;

enum class DependencyStatus {
    VALID,
    MISSING,
    CHANGED,
    UNKNOWN,            // exists but no recorded hash → cannot verify
    RELINK_CANDIDATE,   // missing, with verified candidates
};

std::string_view to_string(DependencyStatus status);

// apply_relink refusals (Python ValueError with these exact messages).
class RelinkError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

struct RelinkCandidate {
    std::string path;
    long long size_bytes = 0;
    std::optional<std::string> sha256;  // verified content hash when computed
    std::string basis = "size";         // "size+hash" | "size"

    Json to_json() const;
};

struct DependencyRecord {
    std::string version_id;
    std::string asset_name;
    bool managed = false;
    std::string path;
    DependencyStatus status = DependencyStatus::MISSING;
    std::optional<long long> observed_size;
    std::optional<double> observed_mtime;  // Python st_mtime (epoch seconds)
    std::optional<long long> expected_size;  // Python None -> nullopt
    std::optional<std::string> expected_sha256;
    std::vector<RelinkCandidate> relink_candidates;
    std::string detail;

    Json to_json() const;
};

struct DependencyAuditReport {
    std::vector<DependencyRecord> records;
    long long hashed_bytes = 0;

    Json summary() const;   // {total, counts, hashed_bytes}
    Json to_json() const;   // {**summary, records}
    bool ok() const;        // every record valid or unknown
};

// The package builder's read surface plus the link_external write port.
// Tests fake it; the sqlite-backed catalog adapts when line 01 grows it.
class ILinkableCatalog : public CatalogSource {
public:
    struct LinkResult {
        std::string asset_id;
        std::string version_id;
    };
    // Registers a NEW external version (never mutates history). May throw —
    // apply_relink propagates.
    virtual LinkResult link_external(const std::filesystem::path& path,
                                     const std::string& name,
                                     Json metadata = Json::object()) = 0;
};

class ExternalDependencyAuditor {
public:
    explicit ExternalDependencyAuditor(ILinkableCatalog* catalog,
                                       long long hash_budget_bytes =
                                           4LL * 1024 * 1024 * 1024)
        : catalog_(catalog), hash_budget_(hash_budget_bytes) {}

    DependencyAuditReport audit(const CancelToken& cancel = null_cancel()) const;

    // Content-verified candidates for a MISSING dependency: same size as
    // recorded, then same sha256 when the recorded hash is known. Basename
    // similarity never promotes a candidate.
    std::vector<RelinkCandidate> find_relink_candidates(
        const DependencyRecord& record,
        const std::vector<std::filesystem::path>& search_roots,
        int max_candidates = 20,
        const CancelToken& cancel = null_cancel()) const;

    // Attaches candidates to every MISSING record; records with at least
    // one candidate become RELINK_CANDIDATE.
    void attach_candidates(DependencyAuditReport& report,
                           const std::vector<std::filesystem::path>& search_roots,
                           const CancelToken& cancel = null_cancel()) const;

    // Registers a NEW external version pointing at the candidate. Only a
    // hash-verified candidate auto-approves; a size-only candidate needs
    // confirm_unverified=true (human decision).
    ILinkableCatalog::LinkResult apply_relink(
        const DependencyRecord& record, const RelinkCandidate& candidate,
        bool confirm_unverified = false,
        const std::optional<std::string>& asset_name = std::nullopt) const;

private:
    DependencyRecord audit_version(const CatalogVersionRef& version,
                                   const std::string& asset_name,
                                   DependencyAuditReport& report) const;

    ILinkableCatalog* catalog_;
    long long hash_budget_;
};

}  // namespace pwb::interchange
