#include "pwb/ui_review/ingest_columns.hpp"

#include <set>

namespace pwb::ui_review {

namespace {

// ingest_plan.WELL_BOUND_TYPES / SURVEY_BOUND_TYPES verbatim.
const std::set<std::string>& well_bound_types() {
    static const std::set<std::string> types = {
        "well_log", "well_head", "well_stratification", "time_depth",
    };
    return types;
}
const std::set<std::string>& survey_bound_types() {
    static const std::set<std::string> types = {"seismic", "segy"};
    return types;
}

}  // namespace

const std::vector<std::pair<std::string, std::string>>& decision_labels() {
    static const std::vector<std::pair<std::string, std::string>> labels = {
        {"pending", "待定"},
        {"accept", "接受"},
        {"skip", "跳过"},
        {"as_new_version", "作为新版本"},
    };
    return labels;
}

std::string decision_display(const data::PlannedItem& item) {
    for (const auto& [value, label] : decision_labels()) {
        if (value == item.decision) {
            return label;
        }
    }
    return item.decision;
}

std::string ingest_status_display(const data::PlannedItem& item) {
    if (!item.duplicate_of_version.empty()) {
        return "⚠ 重复";
    }
    if (item.identity.strategy == "ambiguous") {
        return "? 待确认";
    }
    if (item.decision == "skip") {
        return "跳过";
    }
    return "✓";
}

std::string ingest_entity_display(const data::PlannedItem& item) {
    const auto& proposal = item.identity;
    if (proposal.strategy.empty()) {
        return "—";
    }
    const std::string label =
        !proposal.entity_name.empty() ? proposal.entity_name
                                      : proposal.entity_id;
    const std::string prefix = proposal.new_entity ? "新建 " : "";
    if (label.empty()) {
        return "—";
    }
    return prefix + label + " (" + proposal.confidence + ")";
}

std::string ingest_confidence_display(const data::PlannedItem& item) {
    return item.identity.strategy.empty() ? "" : item.identity.confidence;
}

std::string ingest_note_display(const data::PlannedItem& item) {
    if (!item.note.empty()) {
        return item.note;
    }
    if (!item.duplicate_of_version.empty()) {
        return "重复: " + item.duplicate_of_asset.substr(0, 12);
    }
    return "";
}

std::string ingest_plan_summary_text(const data::IngestPlan& plan) {
    const domain::Json s = plan.summary();
    auto at = [&s](const char* key) -> long long {
        const auto it = s.find(key);
        return (it != s.end() && it->is_number()) ? it->get<long long>() : 0;
    };
    int accepted = 0;
    for (const auto& item : plan.items) {
        if (item.decision == "accept") {
            ++accepted;
        }
    }
    return "共 " + std::to_string(at("total")) + " 个数据项：接受 " +
           std::to_string(accepted) + "，重复 " +
           std::to_string(at("duplicates")) + "，待确认 " +
           std::to_string(at("unresolved")) + "，文件族 " +
           std::to_string(at("bundles")) +
           "——选中行可在下方修改决策/角色/实体/主用";
}

std::string ingest_done_text(const data::IngestExecuteReport& report) {
    std::string text =
        "导入完成：登记 " +
        std::to_string(report.imported_version_ids.size()) + "，跳过 " +
        std::to_string(report.skipped.size()) + "，绑定 " +
        std::to_string(report.bound_links) + "，新建实体 " +
        std::to_string(report.created_entities) + "，问题 " +
        std::to_string(report.issues.size());
    if (report.cancelled) {
        text += "（已取消——已完成分块保持一致，可重新执行）";
    }
    return text;
}

void ingest_accept_all(data::IngestPlan& plan) {
    for (auto& item : plan.items) {
        if (item.duplicate_of_version.empty()) {
            item.decision = "accept";
        }
    }
}

void ingest_skip_unresolved(data::IngestPlan& plan) {
    for (auto& item : plan.items) {
        if (item.identity.strategy == "ambiguous") {
            item.decision = "skip";
        }
    }
}

bool ingest_unresolved_skipped(const data::IngestPlan& plan) {
    for (const auto& item : plan.items) {
        if (item.identity.strategy == "ambiguous" &&
            item.decision != "skip") {
            return false;
        }
    }
    return true;
}

std::string ingest_entity_type_for(const data::PlannedItem& item) {
    if (well_bound_types().count(item.type) ||
        item.identity.entity_type == "well") {
        return "well";
    }
    if (survey_bound_types().count(item.type) ||
        item.identity.entity_type == "seismic_survey") {
        return "seismic_survey";
    }
    return "geological_entity";
}

const std::vector<std::string>&
ingest_roles_for_entity_type(const std::string& entity_type) {
    // project.roles WELL_ROLES / SURVEY_ROLES / GEOLOGICAL_ROLES verbatim.
    static const std::vector<std::string> well = {
        "well_head", "well_log", "trajectory", "tops", "time_depth",
        "core", "interpretation", "qc", "other",
    };
    static const std::vector<std::string> survey = {
        "seismic_volume", "geometry", "velocity", "horizon", "fault",
        "interpretation", "other",
    };
    static const std::vector<std::string> geological = {
        "horizon", "tops", "fault", "other",
    };
    static const std::vector<std::string> fallback = {"other"};
    if (entity_type == "well") return well;
    if (entity_type == "seismic_survey") return survey;
    if (entity_type == "geological_entity") return geological;
    return fallback;
}

std::vector<IngestEntityOption> ingest_entity_options(
    const data::PlannedItem& item, const std::vector<IngestEntityRow>& wells,
    const std::vector<IngestEntityRow>& surveys) {
    std::vector<IngestEntityOption> out;
    out.push_back({"（不绑定）", "", ""});
    const auto& proposal = item.identity;
    if (proposal.entity_type == "well") {
        for (const auto& well : wells) {
            std::string label = well.name;
            if (!well.uwi.empty()) {
                label += " / " + well.uwi;
            }
            out.push_back({"井 " + label, "well", well.id});
        }
        for (const auto& cand : proposal.candidates) {
            const auto id_it = cand.find("id");
            const auto eid_it = cand.find("entity_id");
            const auto name_it = cand.find("name");
            std::string cid;
            if (id_it != cand.end() && id_it->is_string()) {
                cid = id_it->get<std::string>();
            } else if (eid_it != cand.end() && eid_it->is_string()) {
                cid = eid_it->get<std::string>();
            }
            const std::string cname =
                (name_it != cand.end() && name_it->is_string())
                    ? name_it->get<std::string>()
                    : "";
            if (!cid.empty()) {
                out.push_back(
                    {"候选 " + (cname.empty() ? cid : cname), "well", cid});
            }
        }
    } else if (proposal.entity_type == "seismic_survey") {
        for (const auto& survey : surveys) {
            out.push_back(
                {"调查 " + survey.name, "seismic_survey", survey.id});
        }
    }
    if (!proposal.entity_name.empty() || proposal.new_entity) {
        out.push_back({"新建 " +
                           (proposal.entity_name.empty()
                                ? "…"
                                : proposal.entity_name),
                       proposal.entity_type.empty()
                           ? "well"
                           : proposal.entity_type,
                       std::string(kIngestNewEntityId)});
    }
    return out;
}

std::pair<std::string, std::string>
ingest_entity_current(const data::PlannedItem& item) {
    const auto& proposal = item.identity;
    if (!proposal.entity_id.empty() && !proposal.new_entity) {
        return {proposal.entity_type, proposal.entity_id};
    }
    return {"", ""};
}

}  // namespace pwb::ui_review
