// CONV-23 — workflow/contracts/models.py port.
//
// Pydantic-lite: the Python models use only field defaults +
// Field(default_factory=list), so these are plain structs with the same
// defaults plus model_dump()/from_json() equivalents. All enums are
// str-valued in Python (``str, Enum``); here they are scoped enums with
// faithful string maps, and `X.value` semantics == to_string(X).
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::workflow_contracts {

using pwb::domain::Json;

// ---------------------------------------------------------------------------
// enums — str-valued, in Python declaration order
// ---------------------------------------------------------------------------

enum class Certainty {
    KNOWN_FROM_CODE,
    INFERRED,
    EXPERT_CONFIRMATION_REQUIRED,
};

enum class ImplementationStatus { PRODUCTION, PARTIAL, DEMO, PLACEHOLDER };

enum class InputCardinality {
    EXACTLY_ONE,
    ONE_OR_MORE,
    ZERO_OR_MORE,
    ZERO_OR_ONE,
};

enum class InputVersionSemantics {
    ANY_VERSION,
    CURRENT_VERSION,
    EXPLICIT_SELECTED_VERSION,
    RAW_ONLY,
    DERIVED_ALLOWED,
};

enum class InputRole {
    PRIMARY,
    CONSTRAINT,
    REFERENCE,
    CALIBRATION,
    OPTIONAL_CONTEXT,
};

enum class ParameterCategory { SCIENTIFIC, ALGORITHM, DISPLAY, IO };

enum class QCSeverity { HARD_GATE, WARNING, INFORMATION };

enum class ExpertQuestionCategory {
    INPUT,
    PARAMETER,
    OPERATION,
    OUTPUT,
    QC,
    WORKFLOW,
    GEOLOGICAL_RULE,
    DATA_QUALITY,
    VERSIONING,
};

enum class ExpertQuestionPriority { P0, P1, P2 };

enum class ExpertQuestionStatus { OPEN, ANSWERED, NOT_REQUIRED };

enum class ReadinessStatus { READY, PARTIAL, BLOCKED, UNKNOWN };

// to_string == Python ``.value``; from_string throws ValueError with the
// Python enum error shape ``'x' is not a valid <EnumName>`` — pydantic would
// surface it as ValidationError, but our contract specs are frozen-valid so
// the only caller (from_json on generated data) never trips it.
std::string to_string(Certainty v);
std::string to_string(ImplementationStatus v);
std::string to_string(InputCardinality v);
std::string to_string(InputVersionSemantics v);
std::string to_string(InputRole v);
std::string to_string(ParameterCategory v);
std::string to_string(QCSeverity v);
std::string to_string(ExpertQuestionCategory v);
std::string to_string(ExpertQuestionPriority v);
std::string to_string(ExpertQuestionStatus v);
std::string to_string(ReadinessStatus v);

Certainty certainty_from(const std::string& v);
ImplementationStatus implementation_status_from(const std::string& v);
InputCardinality input_cardinality_from(const std::string& v);
InputVersionSemantics input_version_semantics_from(const std::string& v);
InputRole input_role_from(const std::string& v);
ParameterCategory parameter_category_from(const std::string& v);
QCSeverity qc_severity_from(const std::string& v);
ExpertQuestionCategory expert_question_category_from(const std::string& v);
ExpertQuestionPriority expert_question_priority_from(const std::string& v);
ExpertQuestionStatus expert_question_status_from(const std::string& v);
ReadinessStatus readiness_status_from(const std::string& v);

// ---------------------------------------------------------------------------
// models — field order mirrors the pydantic declarations
// ---------------------------------------------------------------------------

struct WorkflowSourceEvidence {
    std::string path;
    std::string symbol;
    std::string description;
    Json model_dump() const;
    static WorkflowSourceEvidence from_json(const Json& j);
};

struct WorkflowInputSpec {
    std::string id;
    std::string name;
    std::string description;
    std::vector<std::string> resource_types;
    std::vector<std::string> asset_kinds;
    std::vector<std::string> accepted_formats;
    std::string stage_requirement;
    InputCardinality cardinality = InputCardinality::ZERO_OR_MORE;
    bool required = false;
    bool current_version_required = false;
    InputVersionSemantics version_semantics =
        InputVersionSemantics::ANY_VERSION;
    InputRole role = InputRole::PRIMARY;
    std::string scientific_constraints;
    std::string software_validation;
    std::vector<WorkflowSourceEvidence> source_evidence;
    Certainty certainty = Certainty::KNOWN_FROM_CODE;
    std::vector<std::string> expert_question_ids;
    Json model_dump() const;
    static WorkflowInputSpec from_json(const Json& j);
};

struct WorkflowParameterSpec {
    std::string id;
    std::string name;
    std::string description;
    std::string value_type = "str";
    std::string unit;
    Json default_value;  // Any — stays Json
    std::string range_hint;
    bool required = false;
    ParameterCategory category = ParameterCategory::ALGORITHM;
    Certainty certainty = Certainty::KNOWN_FROM_CODE;
    std::optional<std::string> expert_question_id;
    std::vector<WorkflowSourceEvidence> source_evidence;
    Json model_dump() const;
    static WorkflowParameterSpec from_json(const Json& j);
};

struct WorkflowOperationStep {
    std::string id;
    std::string name;
    std::string description;
    std::string executor_ref;
    std::vector<std::string> input_refs;
    std::vector<std::string> output_refs;
    std::string user_action;
    std::string software_action;
    std::vector<std::string> blocking_requirements;
    std::string datarun_operation;
    std::vector<WorkflowSourceEvidence> source_evidence;
    Certainty certainty = Certainty::KNOWN_FROM_CODE;
    Json model_dump() const;
    static WorkflowOperationStep from_json(const Json& j);
};

struct WorkflowOutputSpec {
    std::string id;
    std::string name;
    std::string description;
    std::string asset_kind;
    std::string format;
    std::string data_stage;
    bool versioned = false;
    bool persistent = false;
    std::string scientific_meaning;
    std::string output_class = "scientific";
    std::vector<std::string> downstream_usage;
    bool qc_required = false;
    std::vector<WorkflowSourceEvidence> source_evidence;
    Certainty certainty = Certainty::KNOWN_FROM_CODE;
    Json model_dump() const;
    static WorkflowOutputSpec from_json(const Json& j);
};

struct WorkflowQCSpec {
    std::string id;
    std::string name;
    std::string description;
    QCSeverity severity = QCSeverity::WARNING;
    std::string check_type;
    bool implemented = false;
    std::string implementation_ref;
    bool expert_confirmation_required = false;
    std::vector<WorkflowSourceEvidence> source_evidence;
    Certainty certainty = Certainty::KNOWN_FROM_CODE;
    Json model_dump() const;
    static WorkflowQCSpec from_json(const Json& j);
};

struct ExpertConsultationQuestion {
    std::string id;
    std::string module_id;
    ExpertQuestionCategory category = ExpertQuestionCategory::INPUT;
    std::string question;
    std::string current_software_behavior;
    std::string why_it_matters;
    std::vector<std::string> options_if_known;
    std::string impact_if_unresolved;
    ExpertQuestionPriority priority = ExpertQuestionPriority::P1;
    Certainty certainty = Certainty::EXPERT_CONFIRMATION_REQUIRED;
    ExpertQuestionStatus status = ExpertQuestionStatus::OPEN;
    std::vector<WorkflowSourceEvidence> source_evidence;
    Json model_dump() const;
    static ExpertConsultationQuestion from_json(const Json& j);
};

struct ReadinessReason {
    std::string code;
    std::string message_zh;
    std::string severity = "block";  // block|warn|info — str field in Python
    std::optional<std::string> input_id;
    Json model_dump() const;
    static ReadinessReason from_json(const Json& j);
};

struct DomainWorkflowContract {
    std::string id;
    std::string name;
    std::string name_zh;
    std::string category;
    std::string description;
    std::string description_zh;
    ImplementationStatus implementation_status =
        ImplementationStatus::PARTIAL;
    std::vector<std::string> entry_points;
    std::vector<WorkflowInputSpec> inputs;
    std::vector<WorkflowParameterSpec> parameters;
    std::vector<WorkflowOperationStep> operations;
    std::vector<WorkflowOutputSpec> outputs;
    std::vector<WorkflowQCSpec> qc_rules;
    std::vector<std::string> upstream_contract_ids;
    std::vector<std::string> downstream_contract_ids;
    std::vector<std::string> datarun_operations;
    std::vector<std::string> workflow_step_types;
    std::vector<std::string> assumptions;
    std::vector<ExpertConsultationQuestion> expert_questions;
    std::vector<WorkflowSourceEvidence> source_evidence;
    Json model_dump() const;
    Json completeness() const;
    static DomainWorkflowContract from_json(const Json& j);
};

}  // namespace pwb::workflow_contracts
