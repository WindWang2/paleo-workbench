// Ingest plan orchestration (conv-26; paleo_workbench/resources/ingest_plan.py
// two-phase parity): build_ingest_plan is PURE (scan → classify → shapefile
// family grouping → identity proposal → duplicate detection → primary
// proposal) and mutates nothing; execute_ingest_plan (ingest_exec.hpp) is
// the mutating phase. Scientific semantics are never guessed silently —
// ambiguous or unmatched files land in plan.unresolved for the caller to
// settle, and directory names are only low-confidence hints.
//
// Declared boundaries (26-decisions.md): well-name HEADER extraction
// (LAS/WITSML engines) follows Python's engine-missing fallback — identity
// proposes through the directory-hint chain; normalize_well_name is the
// bounded fold (entity_identity.hpp).
#pragma once

#include "pwb/catalog/models.hpp"
#include "pwb/data/entity_identity.hpp"
#include "pwb/project/document.hpp"

#include <cstdint>
#include <filesystem>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::data {

namespace fs = std::filesystem;

// Files above this size skip plan-level full hashing (execute-time dedup
// still applies); their duplicate verdict stays an honest unknown.
inline constexpr std::uintmax_t kPlanHashLimitBytes = 256ull * 1024 * 1024;

// Extensions that group into one logical bundle (shapefile family).
inline constexpr const char* kShapefileMemberExtensions[] = {
    ".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".sbn"};
inline constexpr const char* kShapefileRequired[] = {".shp", ".shx", ".dbf"};

struct IdentityProposal {
    std::string entity_type;  // well | seismic_survey | geological_entity | ""
    std::string entity_id;    // "" = None (unresolved / new)
    std::string entity_name;
    bool new_entity = false;
    std::string strategy;     // canonical_name | uwi | directory_hint | none |
                              // ambiguous | file_stem | persisted_id...
    std::string confidence = "low";  // high | medium | low (dataclass default)
    std::vector<domain::Json> candidates;  // [{well_id, name}]
};

struct BundleSuggestion {
    std::vector<std::string> member_paths;  // absolute POSIX strings, sorted
    std::string kind = "shapefile_family";
    // First .shp member, else the first member ("" when empty).
    std::string primary_path() const;
};

struct PlannedItem {
    fs::path path;
    std::string type;
    std::string format;
    std::optional<std::int64_t> size_bytes;
    std::optional<std::string> sha256;
    std::optional<BundleSuggestion> bundle;
    IdentityProposal identity;
    std::string role = "other";
    bool primary = false;
    std::string duplicate_of_version;  // "" = not a duplicate
    std::string duplicate_of_asset;
    std::string decision = "pending";  // pending | accept | skip | as_new_version
    std::string note;
};

struct IngestPlan {
    fs::path root;
    std::vector<PlannedItem> items;
    std::vector<std::string> issues;

    std::vector<const PlannedItem*> unresolved() const;   // strategy == ambiguous
    std::vector<const PlannedItem*> duplicates() const;   // duplicate_of_version set
    // Python to_dict projection: dataclass field values, Path → string.
    domain::Json to_json() const;
    domain::Json summary() const;
};

using ProgressFn = std::function<void(int, int)>;
using CancelFn = std::function<bool()>;

struct IngestPlanOptions {
    bool preferred_only = true;
    ProgressFn progress;                       // (index, total) per file
    CancelFn cancel;                           // polled per file
    // Catalog snapshot for duplicate detection; nullptr disables matching.
    const catalog::CatalogDocument* catalog = nullptr;
};

// Scan *root* (directory or single file) and propose an ingest plan. Pure:
// touches no catalog, no project state. Classification reuses the CONV-19
// ingest classifier (classify_import_path incl. bounded XML sniffing).
IngestPlan build_ingest_plan(const fs::path& root,
                             const project::ProjectDocument& project,
                             const IngestPlanOptions& options = {});

}  // namespace pwb::data
