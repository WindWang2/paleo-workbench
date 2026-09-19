// Read-side queries over the canonical document (conv-31;
// catalog/queries.py + the tags.py tag-lookup helpers parity).
//
// verify_integrity re-hashes payloads against recorded SHA-256 — reports
// only, a mismatch is never written back. search_assets is the canonical
// document scan path (queries.py fallback shape): NFKC+casefold is carried
// as the bounded ASCII fold of entity_view.hpp (declared deviation D6 —
// identical for ASCII and caseless scripts). Tag lookups resolve by
// normalized name over the association maps.
#pragma once

#include "pwb/catalog/checksum.hpp"
#include "pwb/catalog/document_index.hpp"
#include "pwb/catalog/models.hpp"

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::catalog {

// db.py metadata_search_value: booleans → "1"/"0", numbers decimal text,
// strings verbatim (the SQLite CAST round-trip shape).
std::string metadata_search_value(const domain::Json& value);

struct IntegrityReport {
    std::map<std::string, std::string> statuses;  // version_id → status
    bool cancelled = false;

    std::string status_for(const std::string& version_id) const;
    bool ok() const;  // every status verified
};

// queries.verify_integrity parity: trashed versions skipped; payload stat
// + recorded-checksum re-hash; cancel polled per payload. The payload
// resolver defaults to the recorded path (first-rung semantics).
IntegrityReport verify_integrity(
    const CatalogDocument& document,
    const std::optional<std::string>& version_id = std::nullopt,
    const std::function<std::filesystem::path(const DataVersion&)>& resolve = nullptr,
    const CancelPoll& cancel = nullptr);

struct AssetSearchQuery {
    std::string text;                   // "" = no name filter
    std::optional<domain::DataStage> stage;
    std::vector<std::string> tags;      // normalized before matching
    std::string tag_op = "and";         // "and" | "or" (else invalid_argument)
    std::optional<std::string> type;
    std::vector<std::pair<std::string, domain::Json>> metadata;  // equality
    bool include_trashed = false;
};

// queries.search_assets document-scan parity. Returns document-order
// asset ids (the Python function returns models; identity maps here).
std::vector<std::string> search_assets_scan(const CatalogDocument& document,
                                            const DocumentIndex& index,
                                            const AssetSearchQuery& query);

// tags.py find_assets_by_tag / find_versions_by_tag (document scan shape).
std::vector<std::string> find_assets_by_tag(const CatalogDocument& document,
                                             const std::string& name);
std::vector<std::string> find_versions_by_tag(const CatalogDocument& document,
                                               const std::string& name);

}  // namespace pwb::catalog
