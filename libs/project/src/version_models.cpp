// CONV-33 前置 — version_models.hpp 实装（字段/键序/None 语义逐字对
// paleo_workbench/project/models.py；见头注释与 33-decisions D5）。
#include "pwb/project/version_models.hpp"

#include <chrono>
#include <ctime>
#include <random>

namespace pwb::project {

namespace {

// 缺键 / null → 默认（pydantic default_factory 之外的字段宽松回填；硬
// schema 校验仍属 document/schema.cpp 层 — 33-decisions D5）。
std::string opt_string(const Json& data, const char* key) {
    const auto it = data.find(key);
    if (it == data.end() || it->is_null() || !it->is_string()) {
        return {};
    }
    return it->get<std::string>();
}

std::optional<std::string> opt_nullable_string(const Json& data,
                                               const char* key) {
    const auto it = data.find(key);
    if (it == data.end() || it->is_null() || !it->is_string()) {
        return std::nullopt;
    }
    return it->get<std::string>();
}

std::vector<std::string> opt_string_array(const Json& data, const char* key) {
    const auto it = data.find(key);
    if (it == data.end() || !it->is_array()) {
        return {};
    }
    std::vector<std::string> out;
    out.reserve(it->size());
    for (const Json& item : *it) {
        if (item.is_string()) {
            out.push_back(item.get<std::string>());
        }
    }
    return out;
}

std::vector<double> opt_double_array(const Json& data, const char* key) {
    const auto it = data.find(key);
    if (it == data.end() || !it->is_array()) {
        return {};
    }
    std::vector<double> out;
    out.reserve(it->size());
    for (const Json& item : *it) {
        if (item.is_number()) {
            out.push_back(item.get<double>());
        }
    }
    return out;
}

std::optional<std::int64_t> opt_int(const Json& data, const char* key) {
    const auto it = data.find(key);
    if (it == data.end() || it->is_null() || !it->is_number_integer()) {
        return std::nullopt;
    }
    return it->get<std::int64_t>();
}

std::int64_t int_or(const Json& data, const char* key, std::int64_t def) {
    const auto it = data.find(key);
    if (it == data.end() || !it->is_number_integer()) {
        return def;
    }
    return it->get<std::int64_t>();
}

double double_or(const Json& data, const char* key, double def) {
    const auto it = data.find(key);
    if (it == data.end() || !it->is_number()) {
        return def;
    }
    return it->get<double>();
}

bool bool_or(const Json& data, const char* key, bool def) {
    const auto it = data.find(key);
    if (it == data.end() || !it->is_boolean()) {
        return def;
    }
    return it->get<bool>();
}

}  // namespace

// ---------------------------------------------------------------- seams --

std::string default_now_iso() {
    const std::time_t tt = std::chrono::system_clock::to_time_t(
        std::chrono::system_clock::now());
    std::tm utc{};
#if defined(_MSC_VER)
    gmtime_s(&utc, &tt);
#else
    gmtime_r(&tt, &utc);
#endif
    char buffer[32] = {};
    std::strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%S+00:00", &utc);
    return buffer;
}

std::string default_make_id(std::string_view prefix) {
    thread_local std::mt19937_64 rng{std::random_device{}()};
    std::uniform_int_distribution<int> nibble{0, 15};
    std::string out{prefix};
    out.push_back('_');
    for (int i = 0; i < 12; ++i) {
        out.push_back("0123456789abcdef"[static_cast<std::size_t>(nibble(rng))]);
    }
    return out;
}

// ------------------------------------------------------------ WorkflowStep --

Json WorkflowStep::to_dict() const {
    Json out = Json::object();
    out["id"] = id;
    out["step_type"] = step_type;
    out["status"] = status;
    out["required_input_resource_ids"] = required_input_resource_ids;
    out["produced_ids"] = produced_ids;
    out["blocking_issue_summary"] = blocking_issue_summary;
    out["provenance_summary"] = provenance_summary;
    return out;
}

WorkflowStep WorkflowStep::from_dict(const Json& data) {
    WorkflowStep step;
    step.id = opt_string(data, "id");
    step.step_type = opt_string(data, "step_type");
    step.status = opt_string(data, "status");
    if (step.status.empty()) {
        step.status = "pending";
    }
    step.required_input_resource_ids =
        opt_string_array(data, "required_input_resource_ids");
    step.produced_ids = opt_string_array(data, "produced_ids");
    step.blocking_issue_summary = opt_string(data, "blocking_issue_summary");
    step.provenance_summary = opt_string(data, "provenance_summary");
    return step;
}

// --------------------------------------------------------- CompilationRun --

Json CompilationRun::to_dict() const {
    Json out = Json::object();
    out["id"] = id;
    out["name"] = name;
    out["target_horizon"] = target_horizon;
    out["sequence_scheme_ref"] = sequence_scheme_ref;
    out["status"] = status;
    Json steps = Json::array();
    for (const WorkflowStep& step : workflow_steps) {
        steps.push_back(step.to_dict());
    }
    out["workflow_steps"] = std::move(steps);
    out["active_factor_map_task_ids"] = active_factor_map_task_ids;
    out["active_prediction_task_id"] = active_prediction_task_id
                                           ? Json(*active_prediction_task_id)
                                           : Json(nullptr);
    out["active_paleomap_document_id"] = active_paleomap_document_id
                                             ? Json(*active_paleomap_document_id)
                                             : Json(nullptr);
    out["active_quality_report_id"] = active_quality_report_id
                                          ? Json(*active_quality_report_id)
                                          : Json(nullptr);
    out["export_artifact_ids"] = export_artifact_ids;
    out["created_at"] = created_at;
    out["updated_at"] = updated_at;
    return out;
}

CompilationRun CompilationRun::from_dict(const Json& data) {
    CompilationRun run;
    run.id = opt_string(data, "id");
    run.name = opt_string(data, "name");
    run.target_horizon = opt_string(data, "target_horizon");
    run.sequence_scheme_ref = opt_string(data, "sequence_scheme_ref");
    run.status = opt_string(data, "status");
    if (run.status.empty()) {
        run.status = "draft";
    }
    if (const auto it = data.find("workflow_steps");
        it != data.end() && it->is_array()) {
        run.workflow_steps.reserve(it->size());
        for (const Json& item : *it) {
            run.workflow_steps.push_back(WorkflowStep::from_dict(item));
        }
    }
    run.active_factor_map_task_ids =
        opt_string_array(data, "active_factor_map_task_ids");
    run.active_prediction_task_id =
        opt_nullable_string(data, "active_prediction_task_id");
    run.active_paleomap_document_id =
        opt_nullable_string(data, "active_paleomap_document_id");
    run.active_quality_report_id =
        opt_nullable_string(data, "active_quality_report_id");
    run.export_artifact_ids = opt_string_array(data, "export_artifact_ids");
    run.created_at = opt_string(data, "created_at");
    run.updated_at = opt_string(data, "updated_at");
    return run;
}

// -------------------------------------------------------- ContourSegment --

Json ContourSegment::to_dict() const {
    Json out = Json::object();
    out["id"] = id;
    out["level"] = level;
    Json coords = Json::array();
    for (const std::vector<double>& point : coordinates) {
        coords.push_back(point);
    }
    out["coordinates"] = std::move(coords);
    out["closed"] = closed;
    out["properties"] = properties;
    return out;
}

ContourSegment ContourSegment::from_dict(const Json& data) {
    ContourSegment segment;
    segment.id = opt_string(data, "id");
    segment.level = double_or(data, "level", 0.0);
    if (const auto it = data.find("coordinates");
        it != data.end() && it->is_array()) {
        segment.coordinates.reserve(it->size());
        for (const Json& point : *it) {
            if (point.is_array() && point.size() >= 2 &&
                point[0].is_number() && point[1].is_number()) {
                segment.coordinates.push_back(
                    {point[0].get<double>(), point[1].get<double>()});
            }
        }
    }
    segment.closed = bool_or(data, "closed", false);
    if (const auto it = data.find("properties");
        it != data.end() && it->is_object()) {
        segment.properties = *it;
    }
    return segment;
}

// ----------------------------------------------------------- ContourDraft --

Json ContourDraft::to_dict() const {
    Json out = Json::object();
    out["id"] = id;
    out["name"] = name;
    out["target_horizon"] = target_horizon;
    out["factor_type"] = factor_type;
    out["linked_factor_task_id"] = linked_factor_task_id
                                        ? Json(*linked_factor_task_id)
                                        : Json(nullptr);
    out["linked_map_document_id"] = linked_map_document_id
                                        ? Json(*linked_map_document_id)
                                        : Json(nullptr);
    out["levels"] = levels;
    Json segs = Json::array();
    for (const ContourSegment& segment : segments) {
        segs.push_back(segment.to_dict());
    }
    out["segments"] = std::move(segs);
    out["source_grid_n"] = source_grid_n ? Json(*source_grid_n)
                                         : Json(nullptr);
    out["source_backend"] = source_backend ? Json(*source_backend)
                                           : Json(nullptr);
    out["source_value_range"] = source_value_range;
    out["status"] = status;
    out["generator_version"] = generator_version;
    out["created_at"] = created_at;
    out["updated_at"] = updated_at;
    return out;
}

ContourDraft ContourDraft::from_dict(const Json& data) {
    ContourDraft draft;
    draft.id = opt_string(data, "id");
    draft.name = opt_string(data, "name");
    draft.target_horizon = opt_string(data, "target_horizon");
    draft.factor_type = opt_string(data, "factor_type");
    draft.linked_factor_task_id =
        opt_nullable_string(data, "linked_factor_task_id");
    draft.linked_map_document_id =
        opt_nullable_string(data, "linked_map_document_id");
    draft.levels = opt_double_array(data, "levels");
    if (const auto it = data.find("segments");
        it != data.end() && it->is_array()) {
        draft.segments.reserve(it->size());
        for (const Json& item : *it) {
            draft.segments.push_back(ContourSegment::from_dict(item));
        }
    }
    draft.source_grid_n = opt_int(data, "source_grid_n");
    draft.source_backend = opt_nullable_string(data, "source_backend");
    draft.source_value_range = opt_double_array(data, "source_value_range");
    draft.status = opt_string(data, "status");
    if (draft.status.empty()) {
        draft.status = "draft";
    }
    draft.generator_version = opt_string(data, "generator_version");
    if (draft.generator_version.empty()) {
        draft.generator_version = "contour-draft-v1";
    }
    draft.created_at = opt_string(data, "created_at");
    draft.updated_at = opt_string(data, "updated_at");
    return draft;
}

// ---------------------------------------------------------- QualityReport --

Json QualityReport::to_dict() const {
    Json out = Json::object();
    out["id"] = id;
    out["linked_map_document_id"] = linked_map_document_id;
    out["rules"] = rules;
    out["issues"] = issues;
    out["status"] = status;
    out["generated_at"] = generated_at;
    out["provenance_registered"] = provenance_registered;
    out["rule_status"] = rule_status;
    out["coverage"] = coverage;
    return out;
}

QualityReport QualityReport::from_dict(const Json& data) {
    QualityReport report;
    report.id = opt_string(data, "id");
    report.linked_map_document_id = opt_string(data, "linked_map_document_id");
    report.rules = opt_string_array(data, "rules");
    if (const auto it = data.find("issues");
        it != data.end() && it->is_array()) {
        report.issues = *it;
    }
    report.status = opt_string(data, "status");
    if (report.status.empty()) {
        report.status = "pending";
    }
    report.generated_at = opt_string(data, "generated_at");
    report.provenance_registered = bool_or(data, "provenance_registered", true);
    if (const auto it = data.find("rule_status");
        it != data.end() && it->is_object()) {
        report.rule_status = *it;
    }
    if (const auto it = data.find("coverage");
        it != data.end() && it->is_object()) {
        report.coverage = *it;
    }
    return report;
}

// -------------------------------------------------------- VersionSnapshot --

Json VersionSnapshot::to_dict() const {
    Json out = Json::object();
    out["id"] = id;
    out["map_document_id"] = map_document_id;
    out["contour_draft_id"] = contour_draft_id ? Json(*contour_draft_id)
                                               : Json(nullptr);
    out["quality_report_id"] = quality_report_id ? Json(*quality_report_id)
                                                 : Json(nullptr);
    out["factor_task_ids"] = factor_task_ids;
    out["map_name"] = map_name;
    out["target_horizon"] = target_horizon;
    out["line_feature_count"] = line_feature_count;
    out["facies_count"] = facies_count;
    out["contour_segment_count"] = contour_segment_count;
    out["qc_status"] = qc_status;
    out["note"] = note;
    out["content_fingerprint"] = content_fingerprint;
    out["created_at"] = created_at;
    out["created_by"] = created_by;
    return out;
}

VersionSnapshot VersionSnapshot::from_dict(const Json& data) {
    VersionSnapshot snapshot;
    snapshot.id = opt_string(data, "id");
    snapshot.map_document_id = opt_string(data, "map_document_id");
    snapshot.contour_draft_id = opt_nullable_string(data, "contour_draft_id");
    snapshot.quality_report_id =
        opt_nullable_string(data, "quality_report_id");
    snapshot.factor_task_ids = opt_string_array(data, "factor_task_ids");
    snapshot.map_name = opt_string(data, "map_name");
    snapshot.target_horizon = opt_string(data, "target_horizon");
    snapshot.line_feature_count = int_or(data, "line_feature_count", 0);
    snapshot.facies_count = int_or(data, "facies_count", 0);
    snapshot.contour_segment_count =
        int_or(data, "contour_segment_count", 0);
    snapshot.qc_status = opt_string(data, "qc_status");
    snapshot.note = opt_string(data, "note");
    snapshot.content_fingerprint = opt_string(data, "content_fingerprint");
    snapshot.created_at = opt_string(data, "created_at");
    snapshot.created_by = opt_string(data, "created_by");
    return snapshot;
}

// ------------------------------------------------------------ VersionSet --

Json VersionSet::to_dict() const {
    Json out = Json::object();
    out["id"] = id;
    out["name"] = name;
    out["target_horizon"] = target_horizon;
    out["status"] = status;
    Json snaps = Json::array();
    for (const VersionSnapshot& snapshot : snapshots) {
        snaps.push_back(snapshot.to_dict());
    }
    out["snapshots"] = std::move(snaps);
    out["active_snapshot_id"] = active_snapshot_id
                                   ? Json(*active_snapshot_id)
                                   : Json(nullptr);
    out["finalized_by"] = finalized_by;
    out["finalized_at"] = finalized_at ? Json(*finalized_at) : Json(nullptr);
    out["linked_compilation_run_id"] = linked_compilation_run_id
                                           ? Json(*linked_compilation_run_id)
                                           : Json(nullptr);
    out["created_at"] = created_at;
    out["updated_at"] = updated_at;
    return out;
}

VersionSet VersionSet::from_dict(const Json& data) {
    VersionSet set;
    set.id = opt_string(data, "id");
    set.name = opt_string(data, "name");
    set.target_horizon = opt_string(data, "target_horizon");
    set.status = opt_string(data, "status");
    if (set.status.empty()) {
        set.status = "open";
    }
    if (const auto it = data.find("snapshots");
        it != data.end() && it->is_array()) {
        set.snapshots.reserve(it->size());
        for (const Json& item : *it) {
            set.snapshots.push_back(VersionSnapshot::from_dict(item));
        }
    }
    set.active_snapshot_id = opt_nullable_string(data, "active_snapshot_id");
    set.finalized_by = opt_string(data, "finalized_by");
    set.finalized_at = opt_nullable_string(data, "finalized_at");
    set.linked_compilation_run_id =
        opt_nullable_string(data, "linked_compilation_run_id");
    set.created_at = opt_string(data, "created_at");
    set.updated_at = opt_string(data, "updated_at");
    return set;
}

// ---------------------------------------------------- pydantic 构造 parity --

WorkflowStep make_workflow_step(std::string_view step_type,
                                std::string_view status,
                                const ModelClock& clock) {
    WorkflowStep step;
    step.id = clock.make_id("step");
    step.step_type = std::string(step_type);
    step.status = std::string(status);
    return step;
}

CompilationRun make_compilation_run(
    std::string_view name, std::string_view target_horizon,
    std::string_view sequence_scheme_ref,
    const std::vector<WorkflowStep>& workflow_steps,
    const ModelClock& clock) {
    CompilationRun run;
    run.id = clock.make_id("run");
    run.name = std::string(name);
    run.target_horizon = std::string(target_horizon);
    run.sequence_scheme_ref = std::string(sequence_scheme_ref);
    run.workflow_steps = workflow_steps;
    run.created_at = clock.now_iso();
    run.updated_at = run.created_at;
    return run;
}

}  // namespace pwb::project
