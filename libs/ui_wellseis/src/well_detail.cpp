#include <pwb/ui_wellseis/well_detail.hpp>

#include <unordered_map>

namespace pwb::ui_wellseis {

namespace {

constexpr std::size_t kMaxCardLines = 8;
constexpr std::size_t kMaxMemberNames = 4;
constexpr std::size_t kMaxMissingSources = 4;
constexpr std::size_t kVersionIdPreview = 14;

std::string truncate_version_id(const std::string& version_id) {
    if (version_id.size() <= kVersionIdPreview) {
        return version_id + "…";
    }
    return version_id.substr(0, kVersionIdPreview) + "…";
}

const RoleMemberSlice* primary_member(const RoleSlotSlice& slot) {
    for (const RoleMemberSlice& member : slot.members) {
        if (member.is_primary) {
            return &member;
        }
    }
    return nullptr;
}

}  // namespace

std::string well_role_display(const std::string& role) {
    static const std::unordered_map<std::string, std::string> displays = {
        {"well_head", "井身/井位"}, {"well_log", "测井曲线"},
        {"trajectory", "井斜轨迹"}, {"tops", "分层顶"},
        {"time_depth", "时深关系"}, {"core", "岩心"},
        {"interpretation", "井周解释"}, {"qc", "质量控制"},
        {"other", "其他"},
    };
    const auto it = displays.find(role);
    return it == displays.end() ? role : it->second;
}

std::vector<WellRoleRow> well_role_rows(const WellDataViewSlice& view) {
    std::vector<WellRoleRow> rows;
    for (const RoleSlotSlice& slot : view.role_slots) {
        if (slot.members.empty() && !slot.unresolved) {
            continue;
        }
        WellRoleRow row;
        row.role = slot.role;
        row.role_display = well_role_display(slot.role);
        const std::size_t shown =
            std::min(slot.members.size(), kMaxMemberNames);
        for (std::size_t i = 0; i < shown; ++i) {
            if (i != 0) {
                row.member_names += "、";
            }
            row.member_names += slot.members[i].name;
        }
        if (slot.members.size() > kMaxMemberNames) {
            row.member_names += " …(+" +
                std::to_string(slot.members.size() - kMaxMemberNames) + ")";
        }
        const RoleMemberSlice* primary = primary_member(slot);
        row.primary_mark = primary != nullptr ? "✓" : "";
        row.current_version_text =
            primary != nullptr && !primary->current_version_id.empty()
                ? truncate_version_id(primary->current_version_id)
                : "—";
        for (const RoleMemberSlice& member : slot.members) {
            row.version_count_sum += member.version_count;
        }
        rows.push_back(std::move(row));
    }
    return rows;
}

std::vector<std::string> well_empty_roles(const WellDataViewSlice& view) {
    std::vector<std::string> roles;
    for (const RoleSlotSlice& slot : view.role_slots) {
        if (slot.members.empty()) {
            roles.push_back(slot.role);
        }
    }
    return roles;
}

std::vector<std::string> well_stale_lines(const WellDataViewSlice& view,
                                          bool truncate_ids) {
    std::vector<std::string> lines;
    const std::size_t shown =
        std::min(view.stale_items.size(), kMaxCardLines);
    for (std::size_t i = 0; i < shown; ++i) {
        const StaleItemSlice& item = view.stale_items[i];
        std::string line = item.stage + " · " +
            (truncate_ids ? truncate_version_id(item.version_id)
                          : item.version_id);
        if (item.pinned) {
            line += " · pinned";
        }
        lines.push_back(std::move(line));
    }
    if (truncate_ids && view.stale_items.size() > kMaxCardLines) {
        lines.push_back("…另有 " +
                        std::to_string(view.stale_items.size() - kMaxCardLines) +
                        " 项");
    }
    if (lines.empty()) {
        lines.push_back("无过期成果");
    }
    return lines;
}

std::vector<std::string> well_edit_lines(const WellDataViewSlice& view) {
    std::vector<std::string> lines;
    const std::size_t shown =
        std::min(view.uncommitted_edits.size(), kMaxCardLines);
    for (std::size_t i = 0; i < shown; ++i) {
        const UncommittedEditSlice& edit = view.uncommitted_edits[i];
        lines.push_back(edit.state + " · " + edit.source_version_id);
    }
    if (lines.empty()) {
        lines.push_back("无未提交编辑");
    }
    return lines;
}

std::vector<std::string> well_missing_lines(const WellDataViewSlice& view) {
    std::vector<std::string> lines;
    for (const std::string& role : well_empty_roles(view)) {
        if (role != "other") {
            lines.push_back("角色缺失: " + well_role_display(role));
        }
    }
    const std::size_t shown =
        std::min(view.missing_source_asset_ids.size(), kMaxMissingSources);
    for (std::size_t i = 0; i < shown; ++i) {
        lines.push_back("源文件缺失: " + view.missing_source_asset_ids[i]);
    }
    if (lines.empty()) {
        lines.push_back("—");
    }
    return lines;
}

std::string well_detail_title(const WellDataViewSlice& view) {
    return view.well_name.empty() ? "井数据视图" : view.well_name;
}

std::string well_detail_subtitle(const WellDataViewSlice& view) {
    return view.uwi.empty() ? "" : "UWI: " + view.uwi;
}

}  // namespace pwb::ui_wellseis
