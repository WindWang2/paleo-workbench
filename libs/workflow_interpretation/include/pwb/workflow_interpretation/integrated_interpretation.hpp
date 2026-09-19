#pragma once
// CONV-32 — IntegratedInterpretation — 综合解释一等成果（V9 ADR-8,
// goal §15）. Port of paleo_workbench/workflow/interpretation/
// integrated_interpretation.py (Python authoritative, verbatim strings).
//
// The integrated product is no longer "a polygon layer + a dict":
// IntegratedInterpretation binds input_set (pinned CompilationInputSet),
// run (fusion DataRun / catalog version), geometry artifact (layer_id +
// committed catalog DERIVED version), class schema / confidence /
// uncertainty / conflicts, manual edits (InterpretationRevision chain) and
// QA / version / maturity. commit_integrated_interpretation registers the
// layer geometry as a catalog DERIVED version + an
// "integrated_interpretation" DataRun.
//
// Seam mapping (Python duck-typed collaborators -> C++):
//   document (ProjectDocument)            -> Json tree; the
//       integrated_interpretations array is mutated in place (created when
//       missing), the interpretation_revisions array is owned by
//       revision.cpp's record_interpretation_revision.
//   layer (UserVectorLayer / edit layer)  -> Json object
//       {"features": [{"feature_id"?, "id"?, "geometry"?,
//                      "attributes"? | "properties"?}]}
//   catalog (DataCatalogService)          -> workflow_runtime::
//       CatalogRepository pointer (null == Python None -> honest ValueError;
//       payload transport is the canonical TEXT, not a temp-file path —
//       documented divergence, the bytes are the identity).
#include <pwb/domain/json.hpp>
#include <pwb/workflow_interpretation/revision.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <array>
#include <functional>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace pwb::workflow_interpretation {

using domain::Json;

inline constexpr const char* OPERATION_INTEGRATED_INTERPRETATION =
    "integrated_interpretation";
inline constexpr const char* ASSET_TYPE_INTEGRATED_INTERPRETATION =
    "integrated_interpretation";

// fusion QC → 综合解释 conflicts 摘要的键（stage/summary 共用，防漂移）。
inline constexpr std::array<const char*, 4> FUSION_CONFLICT_KEYS{{
    "low_confidence_fraction",
    "mean_conflict_fraction",
    "high_conflict_fraction",
    "low_margin_fraction",
}};

// 成熟度（goal §31 与 MapProduct 对齐的语义阶梯；本模块无迁移逻辑）。
inline constexpr const char* MATURITY_DRAFT = "draft";
inline constexpr const char* MATURITY_REVIEWED = "reviewed";
inline constexpr const char* MATURITY_FROZEN = "frozen";
inline constexpr const char* MATURITY_PUBLISHED = "published";
inline constexpr const char* MATURITY_SUPERSEDED = "superseded";

// Python ValueError seam: guardrails (duplicate create / missing catalog /
// empty geometry) must surface as the Python exception class they are.
class IntegratedInterpretationValueError : public std::runtime_error {
public:
    explicit IntegratedInterpretationValueError(const std::string& what_arg)
        : std::runtime_error(what_arg) {}

    [[nodiscard]] static const char* python_class() { return "ValueError"; }
};

// 一个综合解释成果的领域身份（dict 载体持久化）。
struct IntegratedInterpretation {
    std::string interpretation_id;
    std::string name;
    // CompilationInputSet id（pinned 输入；""=旧工程无结构化输入集）。
    std::string input_set_id;
    // QGIS/文档编辑层（authoring surface）。
    std::string layer_id;
    // fusion catalog 版本（算法种子；""=人工起草）。
    std::string fusion_version_id;
    // 最新一次融合 run 的版本（重跑融合后前移；种子不变——评审 R3-F9）。
    std::string latest_fusion_version_id;
    std::string run_id;
    // 提交后的 catalog DERIVED 版本（""=从未提交）。
    std::string committed_version_id;
    std::vector<std::string> class_schema;
    Json confidence_summary = Json::object();
    Json uncertainty_summary = Json::object();
    // goal §18：agreement/conflict/support count（fusion QC 提取）。
    Json conflicts = Json::object();
    std::vector<std::string> revision_ids;
    // 最近一次 commit 对应的修订 id（其后的修订 = 未提交编辑）。
    std::string last_committed_revision_id;
    std::string qa_report_ref;
    std::string maturity = MATURITY_DRAFT;
    std::string created_at;
    std::string created_by;
    std::string committed_at;

    // 已提交且有后续修订 → live 层 ≠ 最新提交。
    [[nodiscard]] bool has_uncommitted_edits() const;
    // 19 declared fields in Python declaration order, then "active": true.
    [[nodiscard]] Json to_dict() const;
    // Tolerant: str(x or "") coercions, arrays of str, dicts copied,
    // maturity falls back to "draft" on empty, "active"/extras ignored.
    [[nodiscard]] static IntegratedInterpretation from_dict(const Json& data);
};

// IdGen seam returning 12 hex chars; ids are "iint_" + idgen().
using IntegratedIdGen = std::function<std::string()>;
[[nodiscard]] IntegratedIdGen default_integrated_id_gen();

// 创建综合解释记录（同层重复创建 → ValueError）。Appends to_dict() to
// document["integrated_interpretations"] (array created when missing).
[[nodiscard]] IntegratedInterpretation create_integrated_interpretation(
    Json& document, const std::string& name, const std::string& layer_id,
    const std::string& input_set_id = "",
    const std::string& fusion_version_id = "",
    const std::string& run_id = "",
    const std::vector<std::string>& class_schema = {},
    const Json& confidence_summary = Json::object(),
    const Json& conflicts = Json::object(),
    const std::string& created_by = "", const std::string& created_at = "",
    const IntegratedIdGen& id_gen = nullptr);

// Entries with a non-empty interpretation_id, in document order.
[[nodiscard]] std::vector<IntegratedInterpretation>
interpretations_for_document(const Json& document);

// First layer_id match else nullopt.
[[nodiscard]] std::optional<IntegratedInterpretation> find_by_layer(
    const Json& document, const std::string& layer_id);

// Replace the record with the same interpretation_id else append. PUBLIC:
// the revision domain link (revision.cpp) calls exactly this seam.
void upsert_interpretation(Json& document,
                           const IntegratedInterpretation& interpretation);

// _layer_payload port: geometry + class schema + input/seed references
// (snapshot). Feature shape {"id", "geometry", "properties"} with the
// feature_id > id precedence and attributes > properties fallback of the
// Python getattr chain. Payload key order: schema, interpretation_id,
// layer_id, class_schema, input_set_id, fusion_version_id, features.
[[nodiscard]] Json layer_payload(const IntegratedInterpretation& interpretation,
                                 const Json& layer);

// json.dumps(payload, ensure_ascii=False, sort_keys=True) — Python DEFAULT
// separators (", " / ": ") and Python float repr. Exposed so the catalog
// payload text stays byte-identical to the Python chain.
[[nodiscard]] std::string python_dumps_sorted(const Json& payload);

// 提交综合解释：层几何 → catalog DERIVED 版本 + DataRun + revision。
// Returns the new version id. catalog == nullptr -> ValueError; empty
// feature set -> ValueError (no state mutated before both checks). On a
// repository failure after register_run the run is marked "failed"
// (best-effort) and the exception re-raised. revision_id_gen passthrough
// (C++-only seam, defaults to revision.cpp's generator).
[[nodiscard]] std::string commit_integrated_interpretation(
    Json& document, const IntegratedInterpretation& interpretation,
    const Json& layer, workflow_runtime::CatalogRepository* catalog,
    const std::string& actor = "", const std::string& now = "",
    const std::vector<std::string>& evidence_refs = {},
    const RevisionIdGen& revision_id_gen = nullptr);

// Inspector 摘要（goal §15/§25）。Missing record -> {layer_id, status
// "missing", detail 无综合解释记录（旧工程或未创建）}; else the 13-key
// ok shape with "revisions": revision_summary(document, layer_id).
[[nodiscard]] Json interpretation_summary(const Json& document,
                                          const std::string& layer_id);

}  // namespace pwb::workflow_interpretation
