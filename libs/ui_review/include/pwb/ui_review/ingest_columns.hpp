#pragma once

// UI-11 — ingest_plan_dialog.py Qt-free semantics: the decision combo
// vocabulary, status/entity/confidence/note cell text, the summary and
// execute-done lines, the bulk-edit rules (_accept_all/_skip_unresolved),
// the _entity_type_for routing, and the detail-panel option models
// (role vocabulary + entity combo entries + the __new__ sentinel).
// The plan build/execute itself stays in Pwb::Data (build_ingest_plan /
// execute_ingest_plan) — this header only renders/edits its items.

#include "pwb/data/ingest_exec.hpp"
#include "pwb/data/ingest_plan.hpp"

#include <string>
#include <utility>
#include <vector>

namespace pwb::ui_review {

// _DECISION_LABELS — (value, zh label) pairs, combo order.
const std::vector<std::pair<std::string, std::string>>& decision_labels();

// _decision_display: label for value, else the raw decision.
std::string decision_display(const data::PlannedItem& item);

// _status_display: ⚠ 重复 (duplicate) → ? 待确认 (ambiguous) →
// 跳过 (skip) → ✓.
std::string ingest_status_display(const data::PlannedItem& item);

// _entity_display: "—" without strategy; "新建 {label} ({confidence})" or
// "{label} ({confidence})"; label = entity_name or entity_id.
std::string ingest_entity_display(const data::PlannedItem& item);

// confidence cell: identity.confidence when a strategy exists else "".
std::string ingest_confidence_display(const data::PlannedItem& item);

// note cell: item.note else ("重复: " + duplicate_of_asset[:12]) when a
// duplicate else "".
std::string ingest_note_display(const data::PlannedItem& item);

// _refresh_summary:
//   "共 {total} 个数据项：接受 {accepted}，重复 {dups}，待确认 {unres}，
//    文件族 {bundles}——选中行可在下方修改决策/角色/实体/主用"
// summary Json carries total/duplicates/unresolved/bundles keys.
std::string ingest_plan_summary_text(const data::IngestPlan& plan);

// _on_execute_done line (+ "（已取消——已完成分块保持一致，可重新执行）"
// when cancelled).
std::string ingest_done_text(const data::IngestExecuteReport& report);

// ---- bulk edits ------------------------------------------------------------
// _accept_all: decision="accept" for every NON-duplicate item.
void ingest_accept_all(data::IngestPlan& plan);
// _skip_unresolved: decision="skip" for plan.unresolved() items.
void ingest_skip_unresolved(data::IngestPlan& plan);
// _unresolved_skipped: all unresolved items have decision=="skip".
bool ingest_unresolved_skipped(const data::IngestPlan& plan);

// ---- detail panel option models ----------------------------------------------
// _entity_type_for: well when type∈WELL_BOUND_TYPES or
// identity.entity_type=="well"; seismic_survey when type∈SURVEY_BOUND_TYPES
// or identity.entity_type=="seismic_survey"; else geological_entity.
std::string ingest_entity_type_for(const data::PlannedItem& item);

// project.roles.roles_for_entity_type — ordered role vocabulary per
// entity type (frozen tables: WELL/SURVEY/GEOLOGICAL_ROLES + ("other",)).
const std::vector<std::string>&
ingest_roles_for_entity_type(const std::string& entity_type);

// One entity-combo entry (userData = (entity_type, entity_id)).
struct IngestEntityOption {
    std::string label;
    std::string entity_type;
    std::string entity_id;   // "__new__" sentinel for 新建, "" for 不绑定
};

// The well/survey rows of the project the entity combo lists. Plain DTOs —
// the widget adapts project.wells / project.seismic_surveys.
struct IngestEntityRow {
    std::string id;
    std::string name;
    std::string uwi;  // wells only ("" for surveys)
};

// _reload_entities entries: ("（不绑定）", {"", ""}) + project wells/surveys
// + proposal candidates (well only) + optional ("新建 {name}", {type,"__new__"}).
std::vector<IngestEntityOption> ingest_entity_options(
    const data::PlannedItem& item, const std::vector<IngestEntityRow>& wells,
    const std::vector<IngestEntityRow>& surveys);

// The combo's preselected (entity_type, entity_id) — ("","") when
// new_entity or no entity_id (Python ``current = ("", None)``).
std::pair<std::string, std::string>
ingest_entity_current(const data::PlannedItem& item);

inline constexpr std::string_view kIngestNewEntityId = "__new__";

}  // namespace pwb::ui_review
