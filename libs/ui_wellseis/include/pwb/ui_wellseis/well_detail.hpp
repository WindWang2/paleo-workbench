#pragma once

// UI-09 — WellDetailPanel view-model semantics (Qt-free).
//
// Ports well_detail_panel.py::set_view / update_stale:
//   - title = well name, subtitle = "UWI: {uwi}" ("" when no uwi)
//   - roles table rows: slots with members OR unresolved, insertion order;
//     members "、"-join first 4 + " …(+N)"; "✓" when primary member exists;
//     current version = primary.current_version_id[:14] + "…" else "—";
//     version count = sum of member version_counts
//   - stale card: first 8 "{stage} · {version_id}" (+ " · pinned"),
//     else "无过期成果"; the async update_stale path truncates the id to
//     [:14] + "…" and appends "…另有 N 项" past 8
//   - edits card: first 8 "{state} · {source_version_id}",
//     else "无未提交编辑"
//   - missing card: "角色缺失: {display}" for empty slots (role != "other")
//     + first 4 "源文件缺失: {id}", else "—"
//   - role display via project/roles.py well-role registry

#include <string>
#include <vector>

#include <pwb/ui_wellseis/slices.hpp>

namespace pwb::ui_wellseis {

// project/roles.py::role_definition(role).display or role — well roles.
std::string well_role_display(const std::string& role);

// One row of the roles table (5 columns).
struct WellRoleRow {
    std::string role;                 // UserRole payload (raw role key)
    std::string role_display;         // localized label
    std::string member_names;         // "、"-joined first 4 + " …(+N)"
    std::string primary_mark;         // "✓" or ""
    std::string current_version_text; // "{id[:14]}…" or "—"
    int version_count_sum = 0;
};

// Slots rendered in the table (members non-empty OR unresolved).
std::vector<WellRoleRow> well_role_rows(const WellDataViewSlice& view);

// Empty-role keys (no members) — insertion order — feeding "角色缺失" lines.
std::vector<std::string> well_empty_roles(const WellDataViewSlice& view);

// Card line lists (each already falls back to its empty-state text).
// truncate_ids mirrors the async update_stale path ("{id[:14]}…" +
// "…另有 N 项" past 8); the set_view path keeps full ids.
std::vector<std::string> well_stale_lines(const WellDataViewSlice& view,
                                          bool truncate_ids);
std::vector<std::string> well_edit_lines(const WellDataViewSlice& view);
std::vector<std::string> well_missing_lines(const WellDataViewSlice& view);

// Header text.
std::string well_detail_title(const WellDataViewSlice& view);
std::string well_detail_subtitle(const WellDataViewSlice& view);

}  // namespace pwb::ui_wellseis
