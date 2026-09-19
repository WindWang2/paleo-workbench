// Document IO for the mapping_document kernels (CONV-27).
//
// Two surfaces ported from the Python product:
//
// 1. The feature-normalization glue of paleo_workbench/mapping/document_io.py
//    (+ mapping/geometry_schema.py normalize_*): the legacy PaleoMapDocument
//    record shape (facies_polygons / well_overlays / line_features /
//    label_features) ↔ editor feature lists, as pure JSON functions. The
//    well/label malformed-coordinate contracts (audit #1162) are frozen:
//    unusable wells are flagged (coordinate_status), malformed labels are
//    skipped with a diagnostic — never a crash, never fabricated positions.
//
// 2. File-level IO with the atomic-write seam and the recovery decision
//    table (mirroring project/manager.py `_write_payload` / `_load_data`,
//    adapted to the composition / map-document formats, which the Python
//    composition panel still writes non-atomically — see
//    ledgers/27-decisions.md D-27-07): temp+fsync+main→bak+replace saves,
//    backup recovery for interrupted saves, corrupt-main quarantine
//    (*.corrupt-<ts>) with backup restore, and unknown-field warnings that
//    never drop data (the kernels preserve extras).
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/mapping_document/composition.hpp>
#include <pwb/mapping_document/map_document.hpp>

#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace pwb::mapping_document {

// ---------------------------------------------------------------------------
// Diagnostics
// ---------------------------------------------------------------------------

struct DocumentIoDiagnostics {
    std::vector<std::string> warnings;   // skipped features, unknown fields
    std::string recovery_source;         // "" | "backup-interrupted-save" | "backup-corrupt-main"
    std::string last_recovery;           // human-readable recovery record
};

// ---------------------------------------------------------------------------
// Feature normalization (document_io.py + geometry_schema.py)
// ---------------------------------------------------------------------------

// Host-injected id seam (geometry_schema.new_feature_id uses uuid4; D-27-04:
// new ids are the host's responsibility). Default: deterministic
// "<prefix>_%012x" counters. Copyable: the counter lives behind a
// shared_ptr so copies share one sequence (no dangling-lambda copies).
class FeatureIdGenerator {
public:
    FeatureIdGenerator();
    explicit FeatureIdGenerator(std::function<std::string(const std::string& prefix)> generator);
    std::string new_id(const std::string& prefix);

private:
    std::function<std::string(const std::string& prefix)> generator_;
    std::shared_ptr<long long> counter_ = std::make_shared<long long>(1);
};

// normalize_facies over one raw record (holes and MultiPolygon parts kept).
Json normalize_facies_record(const Json& raw, FeatureIdGenerator& ids);

// normalize_well: malformed coordinates flagged "invalid", never crashes.
Json normalize_well_record(const Json& raw, FeatureIdGenerator& ids);

Json normalize_line_record(const Json& raw, FeatureIdGenerator& ids);

// normalize_label: throws std::invalid_argument on a malformed anchor
// (callers catch + skip, like features_from_document).
Json normalize_label_record(const Json& raw, FeatureIdGenerator& ids);

// document_io.features_from_document: legacy document record (JSON object
// with facies_polygons/well_overlays/line_features/label_features) → editor
// feature array. Malformed records are skipped with diagnostics.
Json features_from_document(const Json& paleo_doc,
                            DocumentIoDiagnostics* diagnostics,
                            FeatureIdGenerator& ids);

// document_io.apply_features_to_document: write editor features back into
// the record shape (in place), preserving payload fields.
void apply_features_to_document(Json& paleo_doc, const Json& features,
                                DocumentIoDiagnostics* diagnostics,
                                FeatureIdGenerator& ids);

// ---------------------------------------------------------------------------
// File IO: atomic-write seam + recovery
// ---------------------------------------------------------------------------

// Storage seam: the product binds StdFileStore; tests inject memory/fault
// stores to exercise the failure paths without touching a real disk.
class DocumentStore {
public:
    virtual ~DocumentStore() = default;
    // Missing file → false, error "missing"; unreadable → false + reason.
    virtual bool read(const std::string& path, std::string& bytes,
                      std::string& error) = 0;
    // Atomic save: temp file in the target dir + fsync + main→bak + replace.
    virtual bool write_atomic(const std::string& path, const std::string& bytes,
                              std::string& error) = 0;
    virtual bool rename(const std::string& from, const std::string& to,
                        std::string& error) = 0;
    virtual bool remove(const std::string& path, std::string& error) = 0;
    virtual bool exists(const std::string& path) = 0;
};

std::unique_ptr<DocumentStore> make_std_file_store();

enum class LoadStatus {
    kOk,                     // main parsed
    kRecoveredFromBackup,    // main missing; .bak parsed (interrupted save)
    kRecoveredCorrupt,       // main unparsable; quarantined + .bak restored
    kUnreadable,             // main exists but unreadable — never fall back
    kCorrupt,                // unparsable and no usable .bak; main untouched
};

struct LoadResult {
    LoadStatus status = LoadStatus::kOk;
    Json payload;       // parsed document JSON (kOk / recovered statuses)
    std::string error;  // kUnreadable / kCorrupt detail
};

// Raw JSON load with the recovery table. `backup_path` defaults to
// path + ".bak"; quarantine suffix: path + ".corrupt-<unix-seconds>".
LoadResult load_document_file(DocumentStore& store, const std::string& path,
                              DocumentIoDiagnostics* diagnostics);

// Atomic JSON save (dump_json_python_compatible formatting).
bool save_document_file(DocumentStore& store, const std::string& path,
                        const Json& payload, std::string& error);

// Typed wrappers: parse/dump through the CONV-02 kernels and record
// unknown-field warnings (data is preserved in `extras`; the warning is the
// diagnostic channel, never a rejection).
LoadResult load_composition_file(DocumentStore& store, const std::string& path,
                                 Composition& out,
                                 DocumentIoDiagnostics* diagnostics);
bool save_composition_file(DocumentStore& store, const std::string& path,
                           const Composition& doc, std::string& error);
LoadResult load_map_document_file(DocumentStore& store, const std::string& path,
                                  MapDocument& out,
                                  DocumentIoDiagnostics* diagnostics);
bool save_map_document_file(DocumentStore& store, const std::string& path,
                            const MapDocument& doc, std::string& error);

// Unknown-field warnings for a raw payload (top level + composition
// elements): every unknown key is preserved by the kernel; this reports it.
void warn_unknown_fields(const Json& payload, DocumentIoDiagnostics* diagnostics);

}  // namespace pwb::mapping_document
