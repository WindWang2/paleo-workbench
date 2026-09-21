// V14-DATA-LINEAGE (P4) — IngestPlanModel implementation (Qt-free,
// Pwb::Data-free; see ingest_plan_model.hpp for the DTO boundary).
#include <pwb/ui_pages_data/ingest_plan_model.hpp>

#include <map>
#include <set>
#include <tuple>
#include <utility>

namespace pwb::ui_pages_data {
namespace {

bool is_known_decision(const std::string& decision) {
    return decision == kPlanDecisionPending ||
           decision == kPlanDecisionAccept ||
           decision == kPlanDecisionSkip ||
           decision == kPlanDecisionAsNewVersion;
}

}  // namespace

IngestPlanModel::IngestPlanModel(std::vector<PlanItemRow> rows)
    : rows_(std::move(rows)) {
    recompute_primary();
}

const PlanItemRow* IngestPlanModel::row(std::size_t index) const {
    if (index >= rows_.size()) return nullptr;
    return &rows_[index];
}

void IngestPlanModel::toggle_include(std::size_t index) {
    if (index >= rows_.size()) return;
    rows_[index].include = !rows_[index].include;
    recompute_primary();
}

void IngestPlanModel::set_decision(std::size_t index,
                                   const std::string& decision) {
    if (index >= rows_.size()) return;
    rows_[index].decision = decision;
    recompute_primary();
}

void IngestPlanModel::set_role(std::size_t index, const std::string& role) {
    if (index >= rows_.size()) return;
    rows_[index].role = role;
    recompute_primary();
}

void IngestPlanModel::set_all_decisions(const std::string& decision) {
    for (auto& row : rows_) row.decision = decision;
    recompute_primary();
}

bool IngestPlanModel::effectively_accepted(const PlanItemRow& row) const {
    // Only accepted + included rows land in the catalog; a skipped or
    // excluded item never executes regardless of its decision string.
    return row.include && row.decision == kPlanDecisionAccept;
}

void IngestPlanModel::recompute_primary() {
    // Slot = (entity_id, role) with the registry's primary policy
    // precomputed onto the rows. Unknown-entity rows (empty entity_id)
    // never join a slot — execute-time binding decides those.
    std::map<std::pair<std::string, std::string>,
             std::vector<PlanItemRow*>>
        slots;
    for (auto& row : rows_) {
        if (!row.primary_required || row.entity_id.empty()) continue;
        slots[{row.entity_id, row.role}].push_back(&row);
    }
    for (auto& [slot, members] : slots) {
        std::vector<PlanItemRow*> accepted;
        for (auto* member : members) {
            if (effectively_accepted(*member)) accepted.push_back(member);
        }
        if (accepted.size() == 1) {
            // Single-primary invariant preview: the surviving item is the
            // primary; siblings clear (never two stars in one slot).
            for (auto* member : members) member->primary = false;
            accepted.front()->primary = true;
        } else if (accepted.empty()) {
            for (auto* member : members) member->primary = false;
        }
        // >1 accepted: keep the plan-built proposal — validation() reports
        // the competition instead of silently choosing a winner.
    }
}

std::vector<std::string> IngestPlanModel::validation() const {
    std::vector<std::string> issues;

    int accepted_total = 0;
    for (const auto& row : rows_) {
        if (effectively_accepted(row)) ++accepted_total;
    }
    if (rows_.empty()) {
        issues.push_back("导入计划为空：没有可审查的文件");
        return issues;
    }
    if (accepted_total == 0) {
        issues.push_back("没有接受任何条目：请至少接受一项（或使用全部接受）");
    }

    // Per-row checks over the rows that would actually execute.
    std::map<std::pair<std::string, std::string>, int> slot_competition;
    for (const auto& row : rows_) {
        if (!is_known_decision(row.decision)) {
            issues.push_back("文件 " + row.filename + " 的决定状态无效: " +
                             row.decision);
            continue;
        }
        if (!effectively_accepted(row)) continue;

        if (!row.allowed_roles.empty()) {
            bool in_vocabulary = false;
            for (const auto& allowed : row.allowed_roles) {
                if (allowed == row.role) {
                    in_vocabulary = true;
                    break;
                }
            }
            if (!in_vocabulary) {
                issues.push_back(
                    "文件 " + row.filename + " 的角色 \"" + row.role +
                    "\" 不在实体类型 " +
                    (row.entity_type.empty() ? std::string("(未解析)")
                                             : row.entity_type) +
                    " 的角色词汇表中");
            }
        }

        if (row.ambiguous) {
            issues.push_back("文件 " + row.filename +
                             " 的实体归属存在歧义（策略: " + row.strategy +
                             "），请先在计划中明确归属");
        } else if (row.entity_id.empty() && !row.new_entity) {
            issues.push_back("文件 " + row.filename + " 未解析到任何实体" +
                             (row.strategy.empty()
                                  ? std::string()
                                  : std::string("（策略: ") + row.strategy +
                                        "）"));
        }

        if (row.primary_required && !row.entity_id.empty()) {
            ++slot_competition[{row.entity_id, row.role}];
        }
    }

    for (const auto& [slot, count] : slot_competition) {
        if (count > 1) {
            issues.push_back("实体 " + slot.first + " 的角色 \"" + slot.second +
                             "\" 有 " + std::to_string(count) +
                             " 个已接受条目竞争主件，请跳过其余条目或调整角色");
        }
    }
    return issues;
}

PlanSummary IngestPlanModel::summary() const {
    PlanSummary out;
    out.total = static_cast<int>(rows_.size());
    for (const auto& row : rows_) {
        if (row.include) ++out.included;
        if (row.duplicate) ++out.duplicates;
        if (row.decision == kPlanDecisionPending) ++out.pending;
        if (row.decision == kPlanDecisionAccept) ++out.accepted;
        if (row.decision == kPlanDecisionSkip) ++out.skipped;
        if (row.decision == kPlanDecisionAsNewVersion) ++out.as_new_version;
    }
    // Slots whose single-primary preview resolved (>=1 accepted primary).
    std::set<std::pair<std::string, std::string>> primary_slots;
    for (const auto& row : rows_) {
        if (!row.primary_required || row.entity_id.empty()) continue;
        if (row.primary) primary_slots.insert({row.entity_id, row.role});
    }
    out.primary_slots = static_cast<int>(primary_slots.size());
    return out;
}

}  // namespace pwb::ui_pages_data
