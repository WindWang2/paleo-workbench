// Missing-source detection + explicit external relink (conv-31;
// catalog/sources.py parity, catalog-scale-v5 D9).
//
// find_missing_sources is a stat-only scan over live versions reporting
// payloads the recorded path can no longer resolve — derived state, never
// persisted. relink_external_source re-points an EXTERNAL RAW version at
// its relocated file, fail-closed: identity must be provable against
// RECORDED facts (sha256 first, then the size+mtime_ns fingerprint); a
// same-basename stranger is the exact silent rebinding #1140 forbids.
// Managed payloads are deliberately NOT relinkable.
#pragma once

#include "pwb/catalog/document_index.hpp"
#include "pwb/catalog/models.hpp"
#include "pwb/domain/errors.hpp"

#include <filesystem>
#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::catalog {

inline constexpr const char* kExternalStatKey = "external_stat";
inline constexpr const char* kRelinkHistoryKey = "relink_history";

struct MissingSource {
    std::string version_id;
    std::string asset_id;
    std::string asset_name;
    domain::DataStage stage = domain::DataStage::Raw;
    bool managed = true;
    std::string recorded_path;
    std::optional<std::string> source_uri;
    std::optional<std::int64_t> size_bytes;
    bool relinkable = false;  // external + RAW
    domain::Json recorded_fingerprint;  // external_stat or null
};

struct MissingSourceReport {
    std::vector<MissingSource> entries;
    int scanned = 0;

    std::vector<const MissingSource*> relinkable() const;
};

// The path a missing-scan must check: ONLY the first resolution rung
// (managed project-join / recorded absolute / naive project-relative) —
// deliberately not the full relocation ladder (an O(versions) scan must
// not run identity hashing; the scan is an upper bound on missingness).
std::filesystem::path missing_probe_path(const std::filesystem::path& project_path,
                                          const DataVersion& version);

MissingSourceReport find_missing_sources(
    const CatalogDocument& document, const DocumentIndex& index,
    const std::filesystem::path& project_path, bool include_managed = true,
    const std::function<bool()>& cancel = nullptr);

// The recorded-fact proof tier for a relink: "sha256", "stat_fingerprint",
// or none.
std::optional<std::string> relink_identity_proof(
    const DataVersion& version, const std::filesystem::path& candidate);

// Fail-closed relink of an external RAW version. On success the version is
// updated in place (path/source_uri/size_bytes/external_stat + appended
// relink_history entry) and saved through *save* (any error → the
// pre-mutation fields are restored and the error returned). Error codes:
// NotFound (unknown/trashed), InvalidArgument (managed / non-RAW /
// candidate missing), ConflictBaseVersion (identity unprovable) — messages
// byte-identical to the Python texts.
domain::DataError relink_external_source(
    CatalogDocument* document, const DocumentIndex& index,
    const std::string& version_id, const std::filesystem::path& new_path,
    const std::function<domain::DataError()>& save,
    const std::string& actor = "user", const std::string& now_iso = "");

}  // namespace pwb::catalog
