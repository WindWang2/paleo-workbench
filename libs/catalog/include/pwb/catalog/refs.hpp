// Lifecycle value types of the catalog seam (conv-31; catalog/types.py
// parity) plus the Data-Manager display payload (view.py
// version_display_payload).
//
// DataVersionRef / DataRunRef / LineageEdge are the wire DTOs business
// modules exchanged in Python; the JSON codecs reproduce the exact
// to_dict/from_dict key sets. Timestamps follow types.py _now_iso
// (UTC ISO-8601 with microseconds); the clock is injectable for
// deterministic tests.
#pragma once

#include "pwb/catalog/document_index.hpp"
#include "pwb/domain/errors.hpp"
#include "pwb/domain/json.hpp"
#include "pwb/domain/stage.hpp"

#include <filesystem>
#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::catalog {

// types.py IntegrityStatus.
enum class IntegrityStatus { Verified, Modified, Missing, Unknown };

inline constexpr std::string_view to_string(IntegrityStatus status) {
    switch (status) {
        case IntegrityStatus::Verified: return "verified";
        case IntegrityStatus::Modified: return "modified";
        case IntegrityStatus::Missing: return "missing";
        case IntegrityStatus::Unknown: return "unknown";
    }
    return "unknown";
}

std::optional<IntegrityStatus> integrity_status_from_string(
    std::string_view value);

// types.py _now_iso: datetime.now(timezone.utc).isoformat().
std::string utc_now_iso();
// types.py _id: prefix + 16 hex chars of a uuid4.
std::string new_ref_id(const std::string& prefix);

struct DataVersionRef {
    std::string asset_id;
    std::string version_id;
    std::string name;
    domain::DataStage stage = domain::DataStage::Intermediate;
    std::string path;
    std::optional<std::string> checksum;
    bool external = false;
    std::optional<std::string> producing_run_id;
    std::string created_at;          // "" → utc_now_iso() on construction
    std::vector<std::string> tags;
    std::string kind;
    std::string format_field;        // "format" on the wire
    IntegrityStatus integrity = IntegrityStatus::Unknown;
    std::optional<std::string> legacy_resource_id;
    bool trashed = false;
    int version_number = 0;

    domain::Json to_dict() const;
    // from_dict parity: unknown stage strings are rejected (Python
    // DataStage(...) raises); created_at default None → now.
    static domain::Result<DataVersionRef> from_dict(const domain::Json& data);
};

struct DataRunRef {
    std::string run_id;
    std::string operation;
    std::vector<std::string> input_version_ids;
    std::vector<std::string> output_version_ids;
    domain::Json parameters = domain::Json::object();
    std::optional<std::string> generator_version;
    std::string status = "running";
    std::string started_at;
    std::optional<std::string> finished_at;
    std::optional<std::string> domain_task_id;
    std::optional<std::string> input_snapshot_hash;

    domain::Json to_dict() const;
    static DataRunRef from_dict(const domain::Json& data);
};

struct LineageEdgeRef {
    std::string source_version_id;
    std::string target_version_id;
    std::optional<std::string> run_id;

    domain::Json to_dict() const;
};

// ---- view.py version_display_payload ---------------------------------------

// Payload resolver seam (view.py called through CatalogPort): the document
// supplies refs; the payload path resolver + integrity probe are injected
// so the display contract stays IO-free and testable.
struct DisplayContext {
    const CatalogDocument* document = nullptr;
    const DocumentIndex* index = nullptr;
    // Payload path for a version (first-rung resolution by default).
    std::function<std::filesystem::path(const DataVersion&)> resolve_path;
};

// The 16-key display contract of view.py (None for unknown versions).
std::optional<domain::Json> version_display_payload(
    const std::string& version_id, const DisplayContext& context);

}  // namespace pwb::catalog
