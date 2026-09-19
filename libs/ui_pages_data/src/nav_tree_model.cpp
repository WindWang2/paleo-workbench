// UI-06 — NavigationTree row model (navigation_tree.py).
//
// Faithful port of the Python tree's construction/count/paging/selection
// semantics onto a flat pre-order row vector. The Qt shell renders NavRows
// into QTreeWidgetItems and forwards signals; every policy decision lives
// here so the oracle can pin it.
#include <pwb/ui_pages_data/nav_tree_model.hpp>
#include <pwb/ui_pages_data/vocab.hpp>

#include <algorithm>
#include <map>
#include <utility>

namespace pwb::ui_pages_data {
namespace {

// AUXILIARY_TYPES (filter_index.py) — a Python set; iteration order only
// feeds a sum, so order is irrelevant.
constexpr const char* kAuxiliaryTypes[] = {
    "document", "image_reference", "reference_map", "tabular",
};

FilterQuery q(std::string node_type, std::optional<std::string> value = {},
            std::optional<std::string> asset = {}) {
    FilterQuery query;
    query.node_type = std::move(node_type);
    query.node_value = std::move(value);
    query.asset_id = std::move(asset);
    return query;
}

// text.rsplit(" ", 1)[0] — the "label base" for count rewrites.
std::string label_of(const std::string& text) {
    const std::size_t pos = text.rfind(' ');
    return pos == std::string::npos ? text : text.substr(0, pos);
}

// Well-role display map (project/roles.py defaults): known role → display,
// unknown → FALLBACK_ROLE_DEFINITION.display == "其他".
const std::map<std::string, std::string>& role_displays() {
    static const std::map<std::string, std::string> map = {
        {"well_head", "井身/井位"},   {"well_log", "测井曲线"},
        {"trajectory", "井斜轨迹"},   {"tops", "分层顶"},
        {"time_depth", "时深关系"},   {"core", "岩心"},
        {"interpretation", "井周解释"}, {"qc", "质量控制"},
        {"seismic_volume", "地震数据体"}, {"geometry", "观测系统"},
        {"velocity", "速度场"},      {"horizon", "层位"},
        {"fault", "断层"},           {"other", "其他"},
    };
    return map;
}

}  // namespace

// --- domain predicates (project/domain.py) -----------------------------------

bool nav_is_reference_well(const NavEntity& well) {
    // str(getattr(well, "spatial_scope", "workarea") or "workarea") == "reference"
    return well.spatial_scope == "reference";
}

bool nav_coord_flagged(const NavEntity& well) {
    // coordinate_status_is_flagged: status != CoordinateStatus.OK.
    return well.coordinate_status != "ok";
}

// --- construction --------------------------------------------------------------

NavTreeModel::NavTreeModel() {
    // Python defaults the seams to None; C++ defaults to the bundled
    // role tables + identity labels so the model is usable standalone.
    role_order_ = [](const std::string& entity_type) {
        if (entity_type == "well") {
            return std::vector<std::string>{
                "well_head", "well_log", "trajectory", "tops", "time_depth",
                "core", "interpretation", "qc", "other"};
        }
        if (entity_type == "seismic_survey") {
            return std::vector<std::string>{
                "seismic_volume", "geometry", "velocity", "horizon",
                "fault", "interpretation", "other"};
        }
        if (entity_type == "geological_entity") {
            return std::vector<std::string>{"horizon", "tops", "fault",
                                            "other"};
        }
        return std::vector<std::string>{"other"};
    };
    role_display_ = [](const std::string& role) {
        const auto& map = role_displays();
        const auto it = map.find(role);
        return it != map.end() ? it->second : std::string("其他");
    };
    asset_label_ = [](const std::string& asset_id) { return asset_id; };
}

// --- flat row storage ------------------------------------------------------------

int NavTreeModel::subtree_end(int row) const {
    int j = row + 1;
    const int depth = rows_[row].depth;
    while (j < static_cast<int>(rows_.size()) && rows_[j].depth > depth) ++j;
    return j;
}

int NavTreeModel::index_of_id(int id) const {
    for (int i = 0; i < static_cast<int>(row_ids_.size()); ++i)
        if (row_ids_[i] == id) return i;
    return -1;
}

int NavTreeModel::append_row(NavRow row, int parent) {
    int pos;
    if (parent < 0) {
        pos = static_cast<int>(rows_.size());
        row.depth = 0;
    } else {
        pos = subtree_end(parent);
        row.depth = rows_[parent].depth + 1;
    }
    row.parent = parent;
    // Existing parent references >= pos shift right.
    for (auto& r : rows_)
        if (r.parent >= pos) ++r.parent;
    rows_.insert(rows_.begin() + pos, std::move(row));
    row_ids_.insert(row_ids_.begin() + pos, next_row_id_++);
    return pos;
}

void NavTreeModel::erase_rows(int first, int last) {
    // Fix parent references in surviving rows.
    const int count = last - first;
    for (auto& r : rows_)
        if (r.parent >= last) r.parent -= count;
    rows_.erase(rows_.begin() + first, rows_.begin() + last);
    row_ids_.erase(row_ids_.begin() + first, row_ids_.begin() + last);
    if (selected_ && *selected_ >= first) {
        // Selection on a removed row is cleared (Python QTreeWidget does the
        // same — currentItem() becomes null); the callers re-select.
        if (*selected_ < last)
            selected_.reset();
        else
            *selected_ -= count;
    }
}

void NavTreeModel::erase_children(int parent_row) {
    const int end = subtree_end(parent_row);
    if (parent_row + 1 < end) erase_rows(parent_row + 1, end);
}

// --- static skeleton (_build_tree) -------------------------------------------------

void NavTreeModel::build() {
    rows_.clear();
    row_ids_.clear();
    selected_.reset();
    pages_.clear();
    entity_counts_.clear();

    NavRow row;
    row.text = "全部数据 0";
    row.query = q("all", "全部");
    row.key = "全部";
    all_row_ = row_ids_[append_row(row, -1)];

    row = NavRow{};
    row.text = "回收站 0";
    row.query = q("trash", "trash");
    row.key = "回收站";
    trash_row_ = row_ids_[append_row(row, -1)];

    row = NavRow{};
    row.text = "工区概览";
    row.query = q("overview");
    row.key = "工区概览";
    overview_row_ = row_ids_[append_row(row, -1)];

    // _ENTITY_GROUPS dict order: well then seismic_survey.
    row = NavRow{};
    row.text = "◉ 井";
    row.query = q("entity_group", "well");
    row.key = "井";
    well_group_row_ = row_ids_[append_row(row, -1)];

    row = NavRow{};
    row.text = "◈ 地震";
    row.query = q("entity_group", "seismic_survey");
    row.key = "地震";
    survey_group_row_ = row_ids_[append_row(row, -1)];

    row = NavRow{};
    row.text = "◆ 其他参考井";
    row.query = q("entity_group", "reference_well");
    row.key = "其他参考井";
    ref_well_group_row_ = row_ids_[append_row(row, -1)];

    row = NavRow{};
    row.text = "地质解释";
    row.selectable = false;
    row.key = "地质解释";
    geo_group_row_ = row_ids_[append_row(row, -1)];

    row = NavRow{};
    row.text = "辅助资料 0";
    row.query = q("auxiliary");
    row.key = "辅助资料";
    append_row(row, -1);

    row = NavRow{};
    row.text = "工作数据 0";
    row.query = q("stage_any", "derived,intermediate");
    row.key = "工作数据";
    append_row(row, -1);

    row = NavRow{};
    row.text = "成果 0";
    row.query = q("stage", "output");
    // Legacy key keeps the canonical lifecycle vocabulary (see Python note).
    row.key = "output";
    append_row(row, -1);

    // 生命阶段 group + leaves.
    int group = append_row(
        [] {
            NavRow r;
            r.text = "生命阶段";
            r.selectable = false;
            return r;
        }(),
        -1);
    for (const auto& [label, value] : stage_leaves()) {
        NavRow child;
        child.text = label + " 0";
        child.query = q("stage", value);
        child.key = value;
        append_row(child, group);
    }

    // 数据类型 group + leaves.
    group = append_row(
        [] {
            NavRow r;
            r.text = "数据类型";
            r.selectable = false;
            return r;
        }(),
        -1);
    for (const auto& [label, value] : type_leaves()) {
        NavRow child;
        child.text = label + " 0";
        child.query = q("type", value);
        child.key = label;
        append_row(child, group);
    }

    // 标签 group (dynamic children; expanded).
    {
        NavRow r;
        r.text = "标签 0";
        r.selectable = false;
        r.expanded = true;
        tag_group_row_ = row_ids_[append_row(r, -1)];
    }

    // 状态与完整性 group + leaves.
    group = append_row(
        [] {
            NavRow r;
            r.text = "状态与完整性";
            r.selectable = false;
            return r;
        }(),
        -1);
    for (const auto& [label, value] : integrity_leaves()) {
        NavRow child;
        child.text = label + " 0";
        child.query = q("integrity", value);
        child.key = value;
        append_row(child, group);
    }

    // 治理 · 审核状态 group (dynamic children).
    {
        NavRow r;
        r.text = "治理 · 审核状态 0";
        r.selectable = false;
        review_group_row_ = row_ids_[append_row(r, -1)];
    }
}

// --- project binding (set_project / _rebuild_entity_groups) -----------------------

void NavTreeModel::clear_project() {
    project_ = NavProjectView{};
    has_project_ = false;
    rebuild_entity_groups();
}

void NavTreeModel::set_project(const NavProjectView& project) {
    project_ = project;
    has_project_ = true;
    const FilterQuery current_query = current_filter_query();
    rebuild_entity_groups();
    if (current_query.node_type == "entity" ||
        current_query.node_type == "entity_group") {
        const auto restored =
            find_entity_row(current_query.node_value.value_or(""));
        if (restored) select(restored);
    }
}

void NavTreeModel::rebuild_entity_groups() {
    const NavProjectView& project = project_;
    const auto& all_wells = has_project_ ? project.wells
                                         : std::vector<NavEntity>{};
    const auto& surveys =
        has_project_ ? project.seismic_surveys : std::vector<NavEntity>{};
    const auto& links =
        has_project_ ? project.entity_asset_links
                     : std::vector<NavEntityLink>{};

    std::vector<NavEntity> wells, reference_wells;
    for (const auto& well : all_wells) {
        (nav_is_reference_well(well) ? reference_wells : wells)
            .push_back(well);
    }

    std::map<std::string, int> well_counts, survey_counts;
    std::set<std::string> unresolved_wells, invalid_coord_wells;
    std::map<std::string, std::vector<NavEntityLink>> well_links;
    for (const auto& link : links) {
        if (link.entity_type == "well") {
            ++well_counts[link.entity_id];
            well_links[link.entity_id].push_back(link);
            if (link.unresolved) unresolved_wells.insert(link.entity_id);
        } else if (link.entity_type == "seismic_survey") {
            ++survey_counts[link.entity_id];
        }
    }
    for (const auto& well : all_wells) {
        if (nav_coord_flagged(well)) invalid_coord_wells.insert(well.id);
    }

    entity_counts_.clear();
    for (const auto& well : all_wells)
        entity_counts_[{"well", well.id}] = well_counts[well.id];
    for (const auto& survey : surveys)
        entity_counts_[{"seismic_survey", survey.id}] =
            survey_counts[survey.id];
    if (has_project_) {
        for (const auto& entity : project.geological_entities) {
            int n = 0;
            for (const auto& link : links)
                if (link.entity_id == entity.id) ++n;
            entity_counts_[{"geological_entity", entity.id}] = n;
        }
    }

    pages_.clear();
    for (int id : {geo_group_row_, well_group_row_, ref_well_group_row_,
                   survey_group_row_}) {
        const int row = index_of_id(id);
        if (row >= 0) erase_children(row);
    }

    auto sorted = [](std::vector<NavEntity> entities) {
        std::stable_sort(entities.begin(), entities.end(),
                         [](const NavEntity& a, const NavEntity& b) {
                             return std::tie(a.name, a.id) <
                                    std::tie(b.name, b.id);
                         });
        return entities;
    };

    // 地质解释 page.
    if (geo_group_row_ >= 0) {
        EntityPage page;
        page.group_key = "geological_entity";
        page.icon = "⛰";
        page.count_key = "geological_entity";
        page.entities = sorted(has_project_ ? project.geological_entities
                                            : std::vector<NavEntity>{});
        page.group_id = geo_group_row_;
        pages_[page.group_key] = std::move(page);
        append_entity_page("geological_entity");
        const int grow = index_of_id(geo_group_row_);
        if (grow >= 0) {
            auto& page_ref = pages_["geological_entity"];
            if (page_ref.entities.empty()) {
                NavRow empty;
                empty.text = "暂无地质解释，导入层位数据后自动识别";
                empty.selectable = false;
                empty.disabled = true;
                append_row(empty, grow);
            }
            rows_[grow].expanded = !page_ref.entities.empty() &&
                                   page_ref.entities.size() <= 200;
        }
    }

    struct GroupSpec {
        int* group_id;
        std::vector<NavEntity> entities;
        std::string key;
        std::string icon;
        std::string count_key;
        bool with_links;
        const char* empty_label;
    };
    GroupSpec specs[] = {
        {&well_group_row_, std::move(wells), "well", "◉", "well", true,
         "暂无测区井，导入井位文件后自动识别"},
        {&ref_well_group_row_, std::move(reference_wells), "reference_well",
         "◆", "well", true, "暂无其他参考井"},
        {&survey_group_row_, std::move(surveys), "seismic_survey", "◈",
         "seismic_survey", false, "暂无地震工区"},
    };
    for (auto& spec : specs) {
        if (*spec.group_id < 0) continue;
        const int grow = index_of_id(*spec.group_id);
        if (grow < 0) continue;
        // Capture selection on a direct child of this group before the
        // page rebuild (children were already erased above).
        EntityPage page;
        page.group_key = spec.key;
        page.icon = spec.icon;
        page.count_key = spec.count_key;
        page.entities = sorted(std::move(spec.entities));
        page.group_id = *spec.group_id;
        if (spec.with_links) {
            page.well_links = well_links;
            page.unresolved = unresolved_wells;
            page.invalid_coord = invalid_coord_wells;
        }
        pages_[spec.key] = std::move(page);
        append_entity_page(spec.key);
        auto& page_ref = pages_[spec.key];
        // Restore selection deterministically now.
        if (page_ref.selected_key) {
            const std::string& key = *page_ref.selected_key;
            bool already = false;
            for (int i = 0; i < page_ref.rendered; ++i)
                if (page_ref.entities[i].id == key) already = true;
            if (!already) materialize_page_for(spec.key, key);
        }
        if (page_ref.entities.empty()) {
            NavRow empty;
            empty.text = spec.empty_label;
            empty.selectable = false;
            empty.disabled = true;
            append_row(empty, grow);
        }
        rows_[grow].expanded =
            spec.key == "well" && !page_ref.entities.empty() &&
            page_ref.entities.size() <= 200;
    }
}

// --- paged entity population (#1046) ------------------------------------------------

void NavTreeModel::append_entity_page(const std::string& group_key) {
    auto it = pages_.find(group_key);
    if (it == pages_.end()) return;
    EntityPage& page = it->second;
    const int grow = index_of_id(page.group_id);
    if (grow < 0) return;

    const int start = page.rendered;
    const int stop =
        std::min(start + kEntityPageSize,
                 static_cast<int>(page.entities.size()));
    for (int i = start; i < stop; ++i) {
        const NavEntity& entity = page.entities[i];
        std::string flags;
        if (page.unresolved.count(entity.id))
            flags = " ⚠";
        else if (page.invalid_coord.count(entity.id))
            flags = " ⚠坐标";
        const int count =
            entity_counts_[{page.count_key, entity.id}];
        NavRow child;
        child.text = page.icon + " " + entity.name + flags + " " +
                     std::to_string(count);
        child.query = q("entity", entity.id);
        child.key = "entity:" + entity.id;
        child.tooltip = entity.uwi.empty() ? entity.name : entity.uwi;
        const int child_row = append_row(child, grow);

        if (!page.well_links.empty()) {
            // V11 role grouping.
            const auto links_it = page.well_links.find(entity.id);
            const std::vector<NavEntityLink> empty_links;
            const auto& entity_links =
                links_it != page.well_links.end() ? links_it->second
                                                  : empty_links;
            std::map<std::string, std::vector<NavEntityLink>> by_role;
            for (const auto& link : entity_links)
                by_role[link.role.empty() ? "other" : link.role].push_back(
                    link);
            const auto order = role_order_ ? role_order_("well")
                                           : std::vector<std::string>{};
            std::map<std::string, int> role_order;
            for (int k = 0; k < static_cast<int>(order.size()); ++k)
                role_order[order[k]] = k;
            std::vector<std::string> ordered_roles;
            for (const auto& [role, _] : by_role)
                ordered_roles.push_back(role);
            std::stable_sort(
                ordered_roles.begin(), ordered_roles.end(),
                [&](const std::string& a, const std::string& b) {
                    const int ia = role_order.count(a)
                                       ? role_order[a]
                                       : static_cast<int>(order.size());
                    const int ib = role_order.count(b)
                                       ? role_order[b]
                                       : static_cast<int>(order.size());
                    return std::tie(ia, a) < std::tie(ib, b);
                });
            int rendered = 0;
            int total_files = 0;
            for (const auto& [_, links_v] : by_role)
                total_files += static_cast<int>(links_v.size());
            for (const auto& role : ordered_roles) {
                const int remaining = kMaxWellFileChildren - rendered;
                if (remaining <= 0) break;
                auto links_v = by_role[role];
                std::stable_sort(
                    links_v.begin(), links_v.end(),
                    [&](const NavEntityLink& a, const NavEntityLink& b) {
                        const std::string la = asset_label(a.asset_id);
                        const std::string lb = asset_label(b.asset_id);
                        if (la != lb) return la < lb;
                        return a.asset_id < b.asset_id;
                    });
                if (static_cast<int>(links_v.size()) > remaining)
                    links_v.resize(remaining);
                const std::string display =
                    role_display_ ? role_display_(role) : role;
                NavRow role_row;
                role_row.text = "◧ " + display + " (" +
                                std::to_string(by_role[role].size()) + ")";
                role_row.key = "role:" + entity.id + ":" + role;
                role_row.selectable = false;
                const int role_idx = append_row(role_row, child_row);
                for (const auto& link : links_v) {
                    const std::string label = asset_label(link.asset_id);
                    NavRow file_row;
                    file_row.text = "▤ " + label;
                    file_row.query = q("entity", entity.id, link.asset_id);
                    file_row.key = "asset:" + link.asset_id;
                    file_row.tooltip = label;
                    append_row(file_row, role_idx);
                    ++rendered;
                }
            }
            if (rendered < total_files) {
                NavRow overflow;
                overflow.text = "…另有 " +
                                std::to_string(total_files - rendered) +
                                " 个文件";
                overflow.selectable = false;
                overflow.disabled = true;
                append_row(overflow, child_row);
            }
        }
        if (page.selected_key && *page.selected_key == entity.id) {
            select(child_row);
            page.selected_key.reset();
        }
    }
    page.rendered = stop;
    if (stop < static_cast<int>(page.entities.size())) {
        NavRow more;
        more.text = "▣ 显示更多（已显示 " + std::to_string(stop) + "/" +
                    std::to_string(page.entities.size()) + "）";
        more.show_more_group = group_key;
        append_row(more, grow);
    }
}

bool NavTreeModel::activate_next_page(const std::string& group_key) {
    auto it = pages_.find(group_key);
    if (it == pages_.end()) return false;
    EntityPage& page = it->second;
    const int grow = index_of_id(page.group_id);
    if (grow < 0) return false;
    // Drop the current affordance row (last show-more child of the group).
    const int end = subtree_end(grow);
    for (int i = end - 1; i > grow; --i) {
        if (rows_[i].show_more_group) {
            erase_rows(i, i + 1);
            break;
        }
    }
    append_entity_page(group_key);
    return page.rendered < static_cast<int>(page.entities.size());
}

int NavTreeModel::entity_population(const std::string& group_key) const {
    const auto it = pages_.find(group_key);
    return it != pages_.end() ? static_cast<int>(it->second.entities.size())
                              : 0;
}

void NavTreeModel::materialize_page_for(const std::string& group_key,
                                        const std::string& entity_id) {
    const auto it = pages_.find(group_key);
    if (it == pages_.end()) return;
    int index = -1;
    for (int i = 0; i < static_cast<int>(it->second.entities.size()); ++i)
        if (it->second.entities[i].id == entity_id) {
            index = i;
            break;
        }
    if (index < 0) return;
    while (it->second.rendered <= index) {
        if (!activate_next_page(group_key)) break;
    }
}

// --- counts (update_counts / _update_tree_counts) ------------------------------------

void NavTreeModel::set_trash_count(int count) {
    const int row = index_of_id(trash_row_);
    if (row >= 0) rows_[row].text = "回收站 " + std::to_string(count);
}

void NavTreeModel::apply_counts(const CatalogCounts& counts) {
    static const std::set<std::string> kDomainNodes = {
        "entity", "entity_group", "overview", "auxiliary", "stage_any"};

    // _update_node_recursive over every row.
    for (auto& row : rows_) {
        if (!row.query ||
            kDomainNodes.count(row.query->node_type)) {
            continue;
        }
        int count = 0;
        const auto& nt = row.query->node_type;
        const auto nv = row.query->node_value.value_or("");
        if (nt == "all")
            count = counts.total;
        else if (nt == "stage" && row.query->node_value)
            count = counts.stages.count(nv) ? counts.stages.at(nv) : 0;
        else if (nt == "type" && row.query->node_value)
            count = counts.types.count(nv) ? counts.types.at(nv) : 0;
        else if (nt == "integrity" && row.query->node_value)
            count =
                counts.integrity.count(nv) ? counts.integrity.at(nv) : 0;
        else if (nt == "tag" && row.query->node_value)
            count = counts.tags.count(nv) ? counts.tags.at(nv) : 0;
        else if (nt == "review_status" && row.query->node_value)
            count = counts.review_status.count(nv)
                        ? counts.review_status.at(nv)
                        : 0;
        row.text = label_of(row.text) + " " + std::to_string(count);
    }

    // Domain smart-view totals on the top-level rows only.
    int aux_total = 0;
    for (const char* t : kAuxiliaryTypes)
        aux_total += counts.types.count(t) ? counts.types.at(t) : 0;
    const int working_total =
        (counts.stages.count("derived") ? counts.stages.at("derived") : 0) +
        (counts.stages.count("intermediate")
             ? counts.stages.at("intermediate")
             : 0);
    for (auto& row : rows_) {
        if (row.depth != 0 || !row.query) continue;
        if (row.query->node_type == "auxiliary")
            row.text = "辅助资料 " + std::to_string(aux_total);
        else if (row.query->node_type == "stage_any")
            row.text = "工作数据 " + std::to_string(working_total);
    }

    update_tag_nodes(counts.tags);
    update_review_nodes(counts.review_status);
}

void NavTreeModel::update_tag_nodes(
    const std::map<std::string, int>& tag_counts) {
    const int parent_row = index_of_id(tag_group_row_);
    if (parent_row < 0) return;

    int total = 0;
    for (const auto& [_, n] : tag_counts) total += n;
    rows_[parent_row].text = "标签 " + std::to_string(total);

    std::optional<std::string> selected_tag;
    if (selected_ && rows_[*selected_].parent == parent_row &&
        rows_[*selected_].query &&
        rows_[*selected_].query->node_type == "tag") {
        selected_tag = rows_[*selected_].query->node_value;
    }

    erase_children(parent_row);
    std::optional<int> reselect;
    for (const auto& [tag_name, count] : tag_counts) {
        NavRow child;
        child.text = "#" + tag_name + " " + std::to_string(count);
        child.query = q("tag", tag_name);
        child.key = "tag:" + tag_name;
        const int idx = append_row(child, parent_row);
        if (selected_tag && tag_name == *selected_tag) reselect = idx;
    }
    if (reselect)
        select(reselect);
    else if (selected_tag)
        reset_filter_to_all();
}

void NavTreeModel::update_review_nodes(
    const std::map<std::string, int>& review_counts) {
    const int parent_row = index_of_id(review_group_row_);
    if (parent_row < 0) return;

    std::optional<std::string> selected_value;
    if (selected_ && rows_[*selected_].parent == parent_row &&
        rows_[*selected_].query &&
        rows_[*selected_].query->node_type == "review_status") {
        selected_value = rows_[*selected_].query->node_value;
    }

    erase_children(parent_row);
    int total = 0;
    for (const auto& [_, n] : review_counts) total += n;
    rows_[parent_row].text =
        "治理 · 审核状态 " + std::to_string(total);

    std::optional<int> reselect;
    for (const auto& [value, count] : review_counts) {
        const std::string label(review_status_label(value));
        NavRow child;
        child.text = label + " " + std::to_string(count);
        child.query = q("review_status", value);
        child.key = value;
        const int idx = append_row(child, parent_row);
        if (selected_value && value == *selected_value) reselect = idx;
    }
    if (reselect)
        select(reselect);
    else if (selected_value)
        reset_filter_to_all();
}

void NavTreeModel::reset_filter_to_all() {
    // topLevelItem(0) — the 全部数据 row.
    const int row = index_of_id(all_row_);
    if (row >= 0) select(row);
}

// --- selection ------------------------------------------------------------------------

std::string NavTreeModel::asset_label(const std::string& asset_id) const {
    if (asset_label_) {
        const std::string label = asset_label_(asset_id);
        if (!label.empty()) return label;
    }
    return asset_id;
}

void NavTreeModel::select(std::optional<int> row) { selected_ = row; }

FilterQuery NavTreeModel::current_filter_query() const {
    if (!selected_ || *selected_ < 0 ||
        *selected_ >= static_cast<int>(rows_.size()))
        return q("all");
    const auto& query = rows_[*selected_].query;
    return query ? *query : q("all");
}

std::string NavTreeModel::selected_category() const {
    if (!selected_ || *selected_ < 0 ||
        *selected_ >= static_cast<int>(rows_.size()))
        return "全部";
    const NavRow& row = rows_[*selected_];
    if (!row.key.empty()) return row.key;
    if (row.query && row.query->node_value)
        return *row.query->node_value;
    return "全部";
}

bool NavTreeModel::highlight_well(const std::string& well_id) {
    for (const char* group_key : {"well", "reference_well"}) {
        const auto it = pages_.find(group_key);
        if (it == pages_.end()) continue;
        bool found = false;
        for (const auto& e : it->second.entities)
            if (e.id == well_id) found = true;
        if (found) {
            materialize_page_for(group_key, well_id);
            break;
        }
    }
    const auto row = find_entity_row(well_id);
    if (!row) return false;
    select(row);
    return true;
}

std::optional<int>
NavTreeModel::find_entity_row(const std::string& entity_id) const {
    for (int i = 0; i < static_cast<int>(rows_.size()); ++i) {
        const auto& query = rows_[i].query;
        if (query && query->node_type == "entity" &&
            query->node_value == entity_id)
            return i;
    }
    return std::nullopt;
}

std::optional<int>
NavTreeModel::find_row_by_key_prefix(const std::string& label) const {
    for (int i = 0; i < static_cast<int>(rows_.size()); ++i) {
        if (label_of(rows_[i].text) == label ||
            rows_[i].text.rfind(label, 0) == 0)
            return i;
    }
    return std::nullopt;
}

NavTreeModel::RowMenu NavTreeModel::row_menu(int row) const {
    if (row < 0 || row >= static_cast<int>(rows_.size()))
        return RowMenu::None;
    if (row_ids_[row] == tag_group_row_) return RowMenu::ManageTags;
    const NavRow& r = rows_[row];
    const auto& query = r.query;
    if (!query || query->node_type != "entity" || query->asset_id)
        return RowMenu::None;
    const int parent_id = r.parent >= 0 ? row_ids_[r.parent] : -1;
    if (parent_id == well_group_row_ || parent_id == ref_well_group_row_)
        return RowMenu::DeleteWell;
    return RowMenu::None;
}

}  // namespace pwb::ui_pages_data
