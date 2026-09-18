#include <pwb/workflow_contracts/models.hpp>

#include <stdexcept>
#include <utility>

namespace pwb::workflow_contracts {
namespace {

// Enum helpers: table-driven to_string/from_string. from_string throws
// std::invalid_argument — frozen data never triggers it.
template <typename E, std::size_t N>
std::string enum_str(E v, const char* const (&names)[N]) {
    return names[static_cast<std::size_t>(v)];
}

template <typename E, std::size_t N>
E enum_from(const std::string& s, const char* const (&names)[N],
            const char* enum_name) {
    for (std::size_t i = 0; i < N; ++i)
        if (s == names[i]) return static_cast<E>(i);
    throw std::invalid_argument("'" + s + "' is not a valid " + enum_name);
}

Json str_vec(const std::vector<std::string>& v) {
    Json out = Json::array();
    for (const auto& s : v) out.push_back(s);
    return out;
}

std::vector<std::string> str_vec_from(const Json& j) {
    std::vector<std::string> out;
    if (j.is_array())
        for (const auto& v : j) out.push_back(v.get<std::string>());
    return out;
}

Json ev_vec(const std::vector<WorkflowSourceEvidence>& v) {
    Json out = Json::array();
    for (const auto& e : v) out.push_back(e.model_dump());
    return out;
}

std::vector<WorkflowSourceEvidence> ev_vec_from(const Json& j) {
    std::vector<WorkflowSourceEvidence> out;
    if (j.is_array())
        for (const auto& e : j)
            out.push_back(WorkflowSourceEvidence::from_json(e));
    return out;
}

// Field reader: j.value(key, fallback) for strings/bools — mirrors pydantic
// defaults when the key is absent.
std::string get_str(const Json& j, const char* key,
                    const std::string& def = "") {
    if (!j.contains(key) || j.at(key).is_null()) return def;
    return j.at(key).get<std::string>();
}

bool get_bool(const Json& j, const char* key, bool def = false) {
    if (!j.contains(key) || j.at(key).is_null()) return def;
    return j.at(key).get<bool>();
}

std::optional<std::string> get_opt(const Json& j, const char* key) {
    if (!j.contains(key) || j.at(key).is_null()) return std::nullopt;
    return j.at(key).get<std::string>();
}

void set_opt(Json& j, const char* key,
             const std::optional<std::string>& v) {
    j[key] = v ? Json(*v) : Json(nullptr);
}

constexpr const char* kCertainty[] = {
    "KNOWN_FROM_CODE", "INFERRED", "EXPERT_CONFIRMATION_REQUIRED"};
constexpr const char* kImplStatus[] = {
    "PRODUCTION", "PARTIAL", "DEMO", "PLACEHOLDER"};
constexpr const char* kCardinality[] = {
    "EXACTLY_ONE", "ONE_OR_MORE", "ZERO_OR_MORE", "ZERO_OR_ONE"};
constexpr const char* kVersionSemantics[] = {
    "ANY_VERSION", "CURRENT_VERSION", "EXPLICIT_SELECTED_VERSION",
    "RAW_ONLY", "DERIVED_ALLOWED"};
constexpr const char* kInputRole[] = {
    "PRIMARY", "CONSTRAINT", "REFERENCE", "CALIBRATION", "OPTIONAL_CONTEXT"};
constexpr const char* kParamCategory[] = {
    "SCIENTIFIC", "ALGORITHM", "DISPLAY", "IO"};
constexpr const char* kQCSeverity[] = {"HARD_GATE", "WARNING", "INFORMATION"};
constexpr const char* kQuestionCategory[] = {
    "INPUT",   "PARAMETER",       "OPERATION",    "OUTPUT",
    "QC",      "WORKFLOW",        "GEOLOGICAL_RULE",
    "DATA_QUALITY", "VERSIONING"};
constexpr const char* kQuestionPriority[] = {"P0", "P1", "P2"};
constexpr const char* kQuestionStatus[] = {"OPEN", "ANSWERED", "NOT_REQUIRED"};
constexpr const char* kReadinessStatus[] = {
    "READY", "PARTIAL", "BLOCKED", "UNKNOWN"};

}  // namespace

std::string to_string(Certainty v) { return enum_str(v, kCertainty); }
std::string to_string(ImplementationStatus v) {
    return enum_str(v, kImplStatus);
}
std::string to_string(InputCardinality v) {
    return enum_str(v, kCardinality);
}
std::string to_string(InputVersionSemantics v) {
    return enum_str(v, kVersionSemantics);
}
std::string to_string(InputRole v) { return enum_str(v, kInputRole); }
std::string to_string(ParameterCategory v) {
    return enum_str(v, kParamCategory);
}
std::string to_string(QCSeverity v) { return enum_str(v, kQCSeverity); }
std::string to_string(ExpertQuestionCategory v) {
    return enum_str(v, kQuestionCategory);
}
std::string to_string(ExpertQuestionPriority v) {
    return enum_str(v, kQuestionPriority);
}
std::string to_string(ExpertQuestionStatus v) {
    return enum_str(v, kQuestionStatus);
}
std::string to_string(ReadinessStatus v) {
    return enum_str(v, kReadinessStatus);
}

Certainty certainty_from(const std::string& v) {
    return enum_from<Certainty>(v, kCertainty, "Certainty");
}
ImplementationStatus implementation_status_from(const std::string& v) {
    return enum_from<ImplementationStatus>(v, kImplStatus,
                                           "ImplementationStatus");
}
InputCardinality input_cardinality_from(const std::string& v) {
    return enum_from<InputCardinality>(v, kCardinality, "InputCardinality");
}
InputVersionSemantics input_version_semantics_from(const std::string& v) {
    return enum_from<InputVersionSemantics>(v, kVersionSemantics,
                                            "InputVersionSemantics");
}
InputRole input_role_from(const std::string& v) {
    return enum_from<InputRole>(v, kInputRole, "InputRole");
}
ParameterCategory parameter_category_from(const std::string& v) {
    return enum_from<ParameterCategory>(v, kParamCategory,
                                        "ParameterCategory");
}
QCSeverity qc_severity_from(const std::string& v) {
    return enum_from<QCSeverity>(v, kQCSeverity, "QCSeverity");
}
ExpertQuestionCategory expert_question_category_from(const std::string& v) {
    return enum_from<ExpertQuestionCategory>(v, kQuestionCategory,
                                             "ExpertQuestionCategory");
}
ExpertQuestionPriority expert_question_priority_from(const std::string& v) {
    return enum_from<ExpertQuestionPriority>(v, kQuestionPriority,
                                             "ExpertQuestionPriority");
}
ExpertQuestionStatus expert_question_status_from(const std::string& v) {
    return enum_from<ExpertQuestionStatus>(v, kQuestionStatus,
                                           "ExpertQuestionStatus");
}
ReadinessStatus readiness_status_from(const std::string& v) {
    return enum_from<ReadinessStatus>(v, kReadinessStatus,
                                      "ReadinessStatus");
}

// ---------------------------------------------------------------------------
// WorkflowSourceEvidence
// ---------------------------------------------------------------------------

Json WorkflowSourceEvidence::model_dump() const {
    return Json{{"path", path}, {"symbol", symbol},
                {"description", description}};
}

WorkflowSourceEvidence
WorkflowSourceEvidence::from_json(const Json& j) {
    WorkflowSourceEvidence e;
    e.path = get_str(j, "path");
    e.symbol = get_str(j, "symbol");
    e.description = get_str(j, "description");
    return e;
}

// ---------------------------------------------------------------------------
// WorkflowInputSpec
// ---------------------------------------------------------------------------

Json WorkflowInputSpec::model_dump() const {
    return Json{{"id", id},
                {"name", name},
                {"description", description},
                {"resource_types", str_vec(resource_types)},
                {"asset_kinds", str_vec(asset_kinds)},
                {"accepted_formats", str_vec(accepted_formats)},
                {"stage_requirement", stage_requirement},
                {"cardinality", to_string(cardinality)},
                {"required", required},
                {"current_version_required", current_version_required},
                {"version_semantics", to_string(version_semantics)},
                {"role", to_string(role)},
                {"scientific_constraints", scientific_constraints},
                {"software_validation", software_validation},
                {"source_evidence", ev_vec(source_evidence)},
                {"certainty", to_string(certainty)},
                {"expert_question_ids", str_vec(expert_question_ids)}};
}

WorkflowInputSpec WorkflowInputSpec::from_json(const Json& j) {
    WorkflowInputSpec s;
    s.id = get_str(j, "id");
    s.name = get_str(j, "name");
    s.description = get_str(j, "description");
    s.resource_types = str_vec_from(j.value("resource_types", Json::array()));
    s.asset_kinds = str_vec_from(j.value("asset_kinds", Json::array()));
    s.accepted_formats =
        str_vec_from(j.value("accepted_formats", Json::array()));
    s.stage_requirement = get_str(j, "stage_requirement");
    if (j.contains("cardinality") && !j["cardinality"].is_null())
        s.cardinality =
            input_cardinality_from(j["cardinality"].get<std::string>());
    s.required = get_bool(j, "required");
    s.current_version_required = get_bool(j, "current_version_required");
    if (j.contains("version_semantics") &&
        !j["version_semantics"].is_null())
        s.version_semantics = input_version_semantics_from(
            j["version_semantics"].get<std::string>());
    if (j.contains("role") && !j["role"].is_null())
        s.role = input_role_from(j["role"].get<std::string>());
    s.scientific_constraints = get_str(j, "scientific_constraints");
    s.software_validation = get_str(j, "software_validation");
    s.source_evidence =
        ev_vec_from(j.value("source_evidence", Json::array()));
    if (j.contains("certainty") && !j["certainty"].is_null())
        s.certainty = certainty_from(j["certainty"].get<std::string>());
    s.expert_question_ids =
        str_vec_from(j.value("expert_question_ids", Json::array()));
    return s;
}

// ---------------------------------------------------------------------------
// WorkflowParameterSpec
// ---------------------------------------------------------------------------

Json WorkflowParameterSpec::model_dump() const {
    Json j{{"id", id},
           {"name", name},
           {"description", description},
           {"value_type", value_type},
           {"unit", unit},
           {"default", default_value},
           {"range_hint", range_hint},
           {"required", required},
           {"category", to_string(category)},
           {"certainty", to_string(certainty)},
           {"source_evidence", ev_vec(source_evidence)}};
    set_opt(j, "expert_question_id", expert_question_id);
    // pydantic field order: expert_question_id precedes source_evidence.
    Json ordered = Json::object();
    for (auto it = j.begin(); it != j.end(); ++it)
        if (it.key() != "expert_question_id" &&
            it.key() != "source_evidence")
            ordered[it.key()] = it.value();
    ordered["expert_question_id"] = j["expert_question_id"];
    ordered["source_evidence"] = j["source_evidence"];
    return ordered;
}

WorkflowParameterSpec WorkflowParameterSpec::from_json(const Json& j) {
    WorkflowParameterSpec s;
    s.id = get_str(j, "id");
    s.name = get_str(j, "name");
    s.description = get_str(j, "description");
    s.value_type = get_str(j, "value_type", "str");
    s.unit = get_str(j, "unit");
    s.default_value = j.value("default", Json(nullptr));
    s.range_hint = get_str(j, "range_hint");
    s.required = get_bool(j, "required");
    if (j.contains("category") && !j["category"].is_null())
        s.category =
            parameter_category_from(j["category"].get<std::string>());
    if (j.contains("certainty") && !j["certainty"].is_null())
        s.certainty = certainty_from(j["certainty"].get<std::string>());
    s.expert_question_id = get_opt(j, "expert_question_id");
    s.source_evidence =
        ev_vec_from(j.value("source_evidence", Json::array()));
    return s;
}

// ---------------------------------------------------------------------------
// WorkflowOperationStep
// ---------------------------------------------------------------------------

Json WorkflowOperationStep::model_dump() const {
    return Json{{"id", id},
                {"name", name},
                {"description", description},
                {"executor_ref", executor_ref},
                {"input_refs", str_vec(input_refs)},
                {"output_refs", str_vec(output_refs)},
                {"user_action", user_action},
                {"software_action", software_action},
                {"blocking_requirements", str_vec(blocking_requirements)},
                {"datarun_operation", datarun_operation},
                {"source_evidence", ev_vec(source_evidence)},
                {"certainty", to_string(certainty)}};
}

WorkflowOperationStep WorkflowOperationStep::from_json(const Json& j) {
    WorkflowOperationStep s;
    s.id = get_str(j, "id");
    s.name = get_str(j, "name");
    s.description = get_str(j, "description");
    s.executor_ref = get_str(j, "executor_ref");
    s.input_refs = str_vec_from(j.value("input_refs", Json::array()));
    s.output_refs = str_vec_from(j.value("output_refs", Json::array()));
    s.user_action = get_str(j, "user_action");
    s.software_action = get_str(j, "software_action");
    s.blocking_requirements =
        str_vec_from(j.value("blocking_requirements", Json::array()));
    s.datarun_operation = get_str(j, "datarun_operation");
    s.source_evidence =
        ev_vec_from(j.value("source_evidence", Json::array()));
    if (j.contains("certainty") && !j["certainty"].is_null())
        s.certainty = certainty_from(j["certainty"].get<std::string>());
    return s;
}

// ---------------------------------------------------------------------------
// WorkflowOutputSpec
// ---------------------------------------------------------------------------

Json WorkflowOutputSpec::model_dump() const {
    return Json{{"id", id},
                {"name", name},
                {"description", description},
                {"asset_kind", asset_kind},
                {"format", format},
                {"data_stage", data_stage},
                {"versioned", versioned},
                {"persistent", persistent},
                {"scientific_meaning", scientific_meaning},
                {"output_class", output_class},
                {"downstream_usage", str_vec(downstream_usage)},
                {"qc_required", qc_required},
                {"source_evidence", ev_vec(source_evidence)},
                {"certainty", to_string(certainty)}};
}

WorkflowOutputSpec WorkflowOutputSpec::from_json(const Json& j) {
    WorkflowOutputSpec s;
    s.id = get_str(j, "id");
    s.name = get_str(j, "name");
    s.description = get_str(j, "description");
    s.asset_kind = get_str(j, "asset_kind");
    s.format = get_str(j, "format");
    s.data_stage = get_str(j, "data_stage");
    s.versioned = get_bool(j, "versioned");
    s.persistent = get_bool(j, "persistent");
    s.scientific_meaning = get_str(j, "scientific_meaning");
    s.output_class = get_str(j, "output_class", "scientific");
    s.downstream_usage =
        str_vec_from(j.value("downstream_usage", Json::array()));
    s.qc_required = get_bool(j, "qc_required");
    s.source_evidence =
        ev_vec_from(j.value("source_evidence", Json::array()));
    if (j.contains("certainty") && !j["certainty"].is_null())
        s.certainty = certainty_from(j["certainty"].get<std::string>());
    return s;
}

// ---------------------------------------------------------------------------
// WorkflowQCSpec
// ---------------------------------------------------------------------------

Json WorkflowQCSpec::model_dump() const {
    return Json{{"id", id},
                {"name", name},
                {"description", description},
                {"severity", to_string(severity)},
                {"check_type", check_type},
                {"implemented", implemented},
                {"implementation_ref", implementation_ref},
                {"expert_confirmation_required",
                 expert_confirmation_required},
                {"source_evidence", ev_vec(source_evidence)},
                {"certainty", to_string(certainty)}};
}

WorkflowQCSpec WorkflowQCSpec::from_json(const Json& j) {
    WorkflowQCSpec s;
    s.id = get_str(j, "id");
    s.name = get_str(j, "name");
    s.description = get_str(j, "description");
    if (j.contains("severity") && !j["severity"].is_null())
        s.severity = qc_severity_from(j["severity"].get<std::string>());
    s.check_type = get_str(j, "check_type");
    s.implemented = get_bool(j, "implemented");
    s.implementation_ref = get_str(j, "implementation_ref");
    s.expert_confirmation_required =
        get_bool(j, "expert_confirmation_required");
    s.source_evidence =
        ev_vec_from(j.value("source_evidence", Json::array()));
    if (j.contains("certainty") && !j["certainty"].is_null())
        s.certainty = certainty_from(j["certainty"].get<std::string>());
    return s;
}

// ---------------------------------------------------------------------------
// ExpertConsultationQuestion
// ---------------------------------------------------------------------------

Json ExpertConsultationQuestion::model_dump() const {
    return Json{{"id", id},
                {"module_id", module_id},
                {"category", to_string(category)},
                {"question", question},
                {"current_software_behavior", current_software_behavior},
                {"why_it_matters", why_it_matters},
                {"options_if_known", str_vec(options_if_known)},
                {"impact_if_unresolved", impact_if_unresolved},
                {"priority", to_string(priority)},
                {"certainty", to_string(certainty)},
                {"status", to_string(status)},
                {"source_evidence", ev_vec(source_evidence)}};
}

ExpertConsultationQuestion
ExpertConsultationQuestion::from_json(const Json& j) {
    ExpertConsultationQuestion q;
    q.id = get_str(j, "id");
    q.module_id = get_str(j, "module_id");
    if (j.contains("category") && !j["category"].is_null())
        q.category =
            expert_question_category_from(j["category"].get<std::string>());
    q.question = get_str(j, "question");
    q.current_software_behavior =
        get_str(j, "current_software_behavior");
    q.why_it_matters = get_str(j, "why_it_matters");
    q.options_if_known =
        str_vec_from(j.value("options_if_known", Json::array()));
    q.impact_if_unresolved = get_str(j, "impact_if_unresolved");
    if (j.contains("priority") && !j["priority"].is_null())
        q.priority =
            expert_question_priority_from(j["priority"].get<std::string>());
    if (j.contains("certainty") && !j["certainty"].is_null())
        q.certainty = certainty_from(j["certainty"].get<std::string>());
    if (j.contains("status") && !j["status"].is_null())
        q.status =
            expert_question_status_from(j["status"].get<std::string>());
    q.source_evidence =
        ev_vec_from(j.value("source_evidence", Json::array()));
    return q;
}

// ---------------------------------------------------------------------------
// ReadinessReason
// ---------------------------------------------------------------------------

Json ReadinessReason::model_dump() const {
    Json j{{"code", code}, {"message_zh", message_zh},
           {"severity", severity}};
    set_opt(j, "input_id", input_id);
    return j;
}

ReadinessReason ReadinessReason::from_json(const Json& j) {
    ReadinessReason r;
    r.code = get_str(j, "code");
    r.message_zh = get_str(j, "message_zh");
    r.severity = get_str(j, "severity", "block");
    r.input_id = get_opt(j, "input_id");
    return r;
}

// ---------------------------------------------------------------------------
// DomainWorkflowContract
// ---------------------------------------------------------------------------

Json DomainWorkflowContract::model_dump() const {
    Json inputs_j = Json::array();
    for (const auto& x : inputs) inputs_j.push_back(x.model_dump());
    Json params_j = Json::array();
    for (const auto& x : parameters) params_j.push_back(x.model_dump());
    Json ops_j = Json::array();
    for (const auto& x : operations) ops_j.push_back(x.model_dump());
    Json outs_j = Json::array();
    for (const auto& x : outputs) outs_j.push_back(x.model_dump());
    Json qc_j = Json::array();
    for (const auto& x : qc_rules) qc_j.push_back(x.model_dump());
    Json qs_j = Json::array();
    for (const auto& x : expert_questions) qs_j.push_back(x.model_dump());
    return Json{{"id", id},
                {"name", name},
                {"name_zh", name_zh},
                {"category", category},
                {"description", description},
                {"description_zh", description_zh},
                {"implementation_status", to_string(implementation_status)},
                {"entry_points", str_vec(entry_points)},
                {"inputs", std::move(inputs_j)},
                {"parameters", std::move(params_j)},
                {"operations", std::move(ops_j)},
                {"outputs", std::move(outs_j)},
                {"qc_rules", std::move(qc_j)},
                {"upstream_contract_ids", str_vec(upstream_contract_ids)},
                {"downstream_contract_ids",
                 str_vec(downstream_contract_ids)},
                {"datarun_operations", str_vec(datarun_operations)},
                {"workflow_step_types", str_vec(workflow_step_types)},
                {"assumptions", str_vec(assumptions)},
                {"expert_questions", std::move(qs_j)},
                {"source_evidence", ev_vec(source_evidence)}};
}

Json DomainWorkflowContract::completeness() const {
    std::size_t open_q = 0;
    for (const auto& q : expert_questions)
        if (q.status == ExpertQuestionStatus::OPEN) ++open_q;
    return Json{{"input_contract_complete", !inputs.empty()},
                {"operation_contract_complete", !operations.empty()},
                {"output_contract_complete", !outputs.empty()},
                {"qc_contract_complete", !qc_rules.empty()},
                {"expert_questions_resolved", open_q == 0},
                {"has_open_expert_questions", open_q > 0}};
}

DomainWorkflowContract
DomainWorkflowContract::from_json(const Json& j) {
    DomainWorkflowContract c;
    c.id = get_str(j, "id");
    c.name = get_str(j, "name");
    c.name_zh = get_str(j, "name_zh");
    c.category = get_str(j, "category");
    c.description = get_str(j, "description");
    c.description_zh = get_str(j, "description_zh");
    if (j.contains("implementation_status") &&
        !j["implementation_status"].is_null())
        c.implementation_status = implementation_status_from(
            j["implementation_status"].get<std::string>());
    c.entry_points = str_vec_from(j.value("entry_points", Json::array()));
    for (const auto& x : j.value("inputs", Json::array()))
        c.inputs.push_back(WorkflowInputSpec::from_json(x));
    for (const auto& x : j.value("parameters", Json::array()))
        c.parameters.push_back(WorkflowParameterSpec::from_json(x));
    for (const auto& x : j.value("operations", Json::array()))
        c.operations.push_back(WorkflowOperationStep::from_json(x));
    for (const auto& x : j.value("outputs", Json::array()))
        c.outputs.push_back(WorkflowOutputSpec::from_json(x));
    for (const auto& x : j.value("qc_rules", Json::array()))
        c.qc_rules.push_back(WorkflowQCSpec::from_json(x));
    c.upstream_contract_ids =
        str_vec_from(j.value("upstream_contract_ids", Json::array()));
    c.downstream_contract_ids =
        str_vec_from(j.value("downstream_contract_ids", Json::array()));
    c.datarun_operations =
        str_vec_from(j.value("datarun_operations", Json::array()));
    c.workflow_step_types =
        str_vec_from(j.value("workflow_step_types", Json::array()));
    c.assumptions = str_vec_from(j.value("assumptions", Json::array()));
    for (const auto& x : j.value("expert_questions", Json::array()))
        c.expert_questions.push_back(
            ExpertConsultationQuestion::from_json(x));
    c.source_evidence =
        ev_vec_from(j.value("source_evidence", Json::array()));
    return c;
}

}  // namespace pwb::workflow_contracts
