// CONV-33 前置 — project 版本生命周期模型（实装，非桩）。
//
// 落盘依据：33-findings §B「project：document.hpp ProjectDocument 已移植；
// 缺口 = VersionSet/VersionSnapshot/ContourDraft/compilation_runs 模型
// （versioning.py 前置）」。字段逐字对 paleo_workbench/project/models.py：
//   WorkflowStep        (models.py L78)
//   CompilationRun      (models.py L105)
//   ContourSegment      (models.py L330)
//   ContourDraft        (models.py L340)
//   VersionSnapshot     (models.py L408)
//   VersionSet          (models.py L429)
//   QualityReport       (models.py L390 — qc.py / versioning.py 共同消费)
//
// 契约裁决（33-decisions D5）：Python `Literal[...]` 词表冻结为字符串常量，
// 不发明 C++ enum —— 状态串是跨模块隐式契约（service/dashboard/QC UI 直读），
// enum 会破坏 Json 对拍。to_dict() 按模型声明序输出全部键（含 None→null，
// pydantic model_dump parity；domain/json.hpp 要求键序保真）。
//
// id / 时间戳缝：pydantic default_factory（_id/_now_iso）在 C++ 侧显式注入
// （ModelClock）。默认实现 = 随机 hex / 墙钟；oracle 冻结时注入确定性实现。
// `uuid4().hex[:12]` parity = `<prefix>_<12 lowercase hex>`。
//
// Qt-free, Python-free.
#pragma once

#include <pwb/domain/json.hpp>

#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace pwb::project {

using domain::Json;

// ---------------------------------------------------------------- seams --

using NowIso = std::function<std::string()>;
using IdFactory = std::function<std::string(std::string_view prefix)>;

// datetime.now(timezone.utc).isoformat() 的 C++ 默认：UTC 秒级 ISO-8601
// （"YYYY-MM-DDTHH:MM:SS+00:00"）。已知偏差：无微秒（33-decisions D5；
// 时间戳不参与科学指纹，oracle 一律注入确定性 NowIso）。
[[nodiscard]] std::string default_now_iso();

// `f"{prefix}_{uuid4().hex[:12]}"` parity：12 个小写 hex，随机源。
[[nodiscard]] std::string default_make_id(std::string_view prefix);

struct ModelClock {
    NowIso now_iso{&default_now_iso};
    IdFactory make_id{&default_make_id};
};

// ------------------------------------------------------- vocabularies --

// WorkflowStep.step_type 词表（models.py L80-87；= service.STEP_ORDER）。
inline constexpr std::string_view kStepTypes[] = {
    "data_check", "factor_map", "prediction", "map_compile", "qc", "export",
};
// WorkflowStep.status 词表（models.py L88-98）。
inline constexpr std::string_view kStepStatuses[] = {
    "pending", "ready", "running", "complete",
    "stale",  // complete relative to history, outdated vs current inputs
    "warning", "failed", "skipped", "mock",
};
// CompilationRun.status 词表（models.py L110-118）。
inline constexpr std::string_view kCompilationRunStatuses[] = {
    "draft", "running", "blocked", "review_required",
    "export_ready", "exported", "failed",
};
// ContourDraft.status 词表（models.py L358）。
inline constexpr std::string_view kContourDraftStatuses[] = {
    "draft", "editing", "final",
};
// VersionSet.status 词表（models.py L435）。
inline constexpr std::string_view kVersionSetStatuses[] = {
    "open", "final", "superseded",
};

// ------------------------------------------------------------- models --

// models.py L78 — WorkflowStep.
struct WorkflowStep {
    std::string id;                 // "step_<hex12>"
    std::string step_type;
    std::string status = "pending";
    std::vector<std::string> required_input_resource_ids;
    std::vector<std::string> produced_ids;
    std::string blocking_issue_summary;
    std::string provenance_summary;

    [[nodiscard]] Json to_dict() const;
    [[nodiscard]] static WorkflowStep from_dict(const Json& data);
};

// models.py L105 — CompilationRun.
struct CompilationRun {
    std::string id;                 // "run_<hex12>"
    std::string name;
    std::string target_horizon;
    std::string sequence_scheme_ref;
    std::string status = "draft";
    std::vector<WorkflowStep> workflow_steps;
    std::vector<std::string> active_factor_map_task_ids;
    std::optional<std::string> active_prediction_task_id;
    std::optional<std::string> active_paleomap_document_id;
    std::optional<std::string> active_quality_report_id;
    std::vector<std::string> export_artifact_ids;
    std::string created_at;
    std::string updated_at;

    [[nodiscard]] Json to_dict() const;
    [[nodiscard]] static CompilationRun from_dict(const Json& data);
};

// models.py L330 — ContourSegment（一条等值线折线）。
struct ContourSegment {
    std::string id;                 // "cseg_<hex12>"
    double level = 0.0;
    std::vector<std::vector<double>> coordinates;  // [[x, y], ...]
    bool closed = false;
    Json properties = Json::object();

    [[nodiscard]] Json to_dict() const;
    [[nodiscard]] static ContourSegment from_dict(const Json& data);
};

// models.py L340 — ContourDraft.
struct ContourDraft {
    std::string id;                 // "cdraft_<hex12>"
    std::string name;
    std::string target_horizon;
    std::string factor_type;
    std::optional<std::string> linked_factor_task_id;
    std::optional<std::string> linked_map_document_id;
    std::vector<double> levels;
    std::vector<ContourSegment> segments;
    std::optional<std::int64_t> source_grid_n;
    std::optional<std::string> source_backend;
    std::vector<double> source_value_range;  // [min, max]
    std::string status = "draft";
    std::string generator_version = "contour-draft-v1";
    std::string created_at;
    std::string updated_at;

    [[nodiscard]] Json to_dict() const;
    [[nodiscard]] static ContourDraft from_dict(const Json& data);
};

// models.py L390 — QualityReport（QC 面与 versioning 共同消费）。
struct QualityReport {
    std::string id;                 // "qc_<hex12>"
    std::string linked_map_document_id;
    std::vector<std::string> rules;
    Json issues = Json::array();    // list[dict] — issue dict 契约在 qc.hpp
    std::string status = "pending";
    std::string generated_at;
    // catalog qc-DataRun 注册结果（H14）：false = 报告在但溯源 run 未登记
    // （可见，不静默）。
    bool provenance_registered = true;
    // V8 M11 诚实覆盖：rule → {"evaluated": bool, "reason": str}。
    Json rule_status = Json::object();
    Json coverage = Json::object();

    [[nodiscard]] Json to_dict() const;
    [[nodiscard]] static QualityReport from_dict(const Json& data);
};

// models.py L408 — VersionSnapshot（专家定稿时点状态）。
struct VersionSnapshot {
    std::string id;                 // "vsnap_<hex12>"
    std::string map_document_id;
    std::optional<std::string> contour_draft_id;
    std::optional<std::string> quality_report_id;
    std::vector<std::string> factor_task_ids;
    std::string map_name;
    std::string target_horizon;
    std::int64_t line_feature_count = 0;
    std::int64_t facies_count = 0;
    std::int64_t contour_segment_count = 0;
    std::string qc_status;
    std::string note;
    // 紧凑几何指纹（审计用，非全量载荷）— versioning._fingerprint_map。
    std::string content_fingerprint;
    std::string created_at;
    std::string created_by;

    [[nodiscard]] Json to_dict() const;
    [[nodiscard]] static VersionSnapshot from_dict(const Json& data);
};

// models.py L429 — VersionSet（层位/主题下的专家定稿版本 lineage）。
struct VersionSet {
    std::string id;                 // "vset_<hex12>"
    std::string name;
    std::string target_horizon;
    std::string status = "open";
    std::vector<VersionSnapshot> snapshots;
    std::optional<std::string> active_snapshot_id;
    std::string finalized_by;
    std::optional<std::string> finalized_at;
    std::optional<std::string> linked_compilation_run_id;
    std::string created_at;
    std::string updated_at;

    [[nodiscard]] Json to_dict() const;
    [[nodiscard]] static VersionSet from_dict(const Json& data);
};

// ----------------------------------------------- pydantic 构造 parity --

// WorkflowStep(step_type=..., status=...) — id 由工厂盖章。
[[nodiscard]] WorkflowStep make_workflow_step(std::string_view step_type,
                                              std::string_view status,
                                              const ModelClock& clock = {});

// CompilationRun(name=..., target_horizon=..., sequence_scheme_ref=...,
//                workflow_steps=[...]) — id/created_at/updated_at 盖章。
[[nodiscard]] CompilationRun make_compilation_run(
    std::string_view name, std::string_view target_horizon,
    std::string_view sequence_scheme_ref,
    const std::vector<WorkflowStep>& workflow_steps,
    const ModelClock& clock = {});

}  // namespace pwb::project
