#pragma once
// CONV-32 — interpretation revisions (interpretation/revision.py port):
// human-edit provenance chains per layer + layer content fingerprints.
// Document is a Json tree (interpretation_revisions array mutated in place;
// integrated_interpretations array receives the domain link).
#include <pwb/domain/json.hpp>

#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::workflow_interpretation {

using domain::Json;

inline constexpr const char* TARGET_PHASE1_DRAFT = "phase1_draft";
inline constexpr const char* TARGET_INTEGRATED_FACIES = "integrated_facies";
inline constexpr const char* TARGET_INTEGRATED_BOUNDARY = "integrated_boundary";
inline constexpr const char* BASE_RAW = "raw";
inline constexpr const char* BASE_FUSION = "fusion";
inline constexpr const char* BASE_FACTOR = "factor";
inline constexpr const char* BASE_DRAFT = "draft";
inline constexpr const char* BASE_MANUAL = "manual";

struct InterpretationRevision {
    std::string revision_id;
    std::string target_kind;
    std::string target_layer_id;
    std::string interpretation_id;
    std::string parent_revision_id;
    std::string base_kind = BASE_MANUAL;
    std::string base_version_id;
    std::vector<std::string> evidence_refs;
    std::string actor;
    std::string created_at;
    std::string content_fingerprint;
    Json delta = Json::object();  // {"features": int, "vertices": int}
    std::string note;

    [[nodiscard]] Json to_dict() const;
    // Tolerant: every key optional, str(x or "") coercions, base_kind
    // falls back to "manual", non-object delta -> {}.
    [[nodiscard]] static InterpretationRevision from_dict(const Json& data);
};

struct LayerFingerprint {
    std::string digest;
    long features = 0;
    long vertices = 0;
};
// sha256 over sort_keys JSON with Python default separators (", " / ": "),
// numbers rounded to 9dp; vertices = raw-tree 2-element numeric arrays.
[[nodiscard]] LayerFingerprint layer_content_fingerprint(const Json& layer);

// "irev_" + 12 lowercase hex (uuid4 slice parity is opaque; injectable).
using RevisionIdGen = std::function<std::string()>;
[[nodiscard]] RevisionIdGen default_revision_id_gen();

// Unchanged content vs latest -> nullopt (no revision recorded).
// Mutates document: appends to interpretation_revisions and links the
// revision into matching integrated_interpretations records.
[[nodiscard]] std::optional<InterpretationRevision> record_interpretation_revision(
    Json& document, const std::string& target_kind,
    const std::string& target_layer_id, const Json& layer,
    const std::string& actor = "", const std::string& now = "",
    const std::string& interpretation_id = "",
    const std::string& base_kind = BASE_MANUAL,
    const std::string& base_version_id = "",
    const std::vector<std::string>& evidence_refs = {},
    const std::string& note = "", const RevisionIdGen& id_gen = nullptr);

[[nodiscard]] std::vector<InterpretationRevision> revisions_for_layer(
    const Json& document, const std::string& layer_id);
[[nodiscard]] std::optional<InterpretationRevision> latest_revision_for_layer(
    const Json& document, const std::string& layer_id);
// {"layer_id","revisions",...} — empty chain detail
// "无修订记录（未保存或旧工程）".
[[nodiscard]] Json revision_summary(const Json& document, const std::string& layer_id);

}  // namespace pwb::workflow_interpretation
