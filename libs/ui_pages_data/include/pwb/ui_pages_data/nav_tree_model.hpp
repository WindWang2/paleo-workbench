// UI-06 — NavigationTree row model (navigation_tree.py).
//
// The Python widget is a QTreeWidget whose items are built, counted and
// paged by hand. This core reproduces the full row semantics — tree
// structure, paged entity materialization (#1046), per-well role groups,
// flag/count suffixes, dynamic tag/review leaves, selection fallback —
// against a duck-typed NavProjectView seam. The Qt shell only renders
// NavRows into QTreeWidgetItems and forwards selection changes.
#pragma once

#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <vector>

#include <pwb/ui_pages_data/filter_query.hpp>

namespace pwb::ui_pages_data {

// --- domain seam (project.domain shapes) ---------------------------------------
// Mirrors the members navigation_tree reads; adapter fills from
// pwb::project::ProjectDocument or the Python-shaped Json.
struct NavEntityLink {          // EntityAssetLink
    std::string entity_type;    // "well" | "seismic_survey" | ...
    std::string entity_id;
    std::string asset_id;
    std::string role;           // "" → grouped under "other"
    bool unresolved = false;
};

struct NavEntity {              // Well / SeismicSurvey / GeologicalEntity
    std::string id;
    std::string name;
    std::string uwi;
    // Well-only flags evaluated by the domain predicates, carried raw so the
    // core re-evaluates them (oracle-verified):
    std::string coordinate_status;      // != "ok" → ⚠坐标 flag
    std::string spatial_scope;          // "reference" → 其他参考井 group
};

struct NavProjectView {
    std::vector<NavEntity> wells;
    std::vector<NavEntity> seismic_surveys;
    std::vector<NavEntity> geological_entities;
    std::vector<NavEntityLink> entity_asset_links;
};

// Domain predicates (project.domain): kept in the core so the oracle pins
// them against the real Python functions.
bool nav_is_reference_well(const NavEntity& well);        // spatial_scope == "reference"
bool nav_coord_flagged(const NavEntity& well);            // coordinate_status != "ok"

// --- row model -------------------------------------------------------------------
// One rendered row. `query` empty ⇒ non-selectable header/empty/show-more row.
struct NavRow {
    int depth = 0;
    std::string text;               // includes count suffix
    std::string key;                // UserRole+1 legacy key ("entity:x" etc.)
    std::optional<FilterQuery> query;
    bool selectable = true;
    bool disabled = false;
    bool expanded = false;
    // "show more" affordance: group key when this row is the pager button.
    std::optional<std::string> show_more_group;
    std::string tooltip;
    int parent = -1;                // index into rows(), -1 = top level
};

// Role vocabulary seam (project.roles, unported): entity_type → ordered
// role list; role → display label (Python: role_definition(r).display or r).
using RoleOrderFn = std::function<std::vector<std::string>(const std::string&)>;
using RoleDisplayFn = std::function<std::string(const std::string&)>;
// asset_id → display label (DataPage supplies a catalog-aware provider).
using AssetLabelFn = std::function<std::string(const std::string&)>;

class NavTreeModel {
public:
    static constexpr int kEntityPageSize = 500;      // ENTITY_PAGE_SIZE
    static constexpr int kMaxWellFileChildren = 30;  // MAX_WELL_FILE_CHILDREN

    NavTreeModel();

    void set_role_order_fn(RoleOrderFn fn) { role_order_ = std::move(fn); }
    void set_role_display_fn(RoleDisplayFn fn) { role_display_ = std::move(fn); }
    void set_asset_label_fn(AssetLabelFn fn) { asset_label_ = std::move(fn); }

    // Bind a project and rebuild the entity sections (set_project).
    // Selection on an entity node is restored when the same id survives.
    void set_project(const NavProjectView& project);
    void clear_project();

    // Rebuild the static skeleton (全部/回收站/概览/组…). Called once by
    // the Qt shell at construction; counts applied via apply_counts.
    void build();

    // Count pass (update_counts → _update_tree_counts). Rewrites the
    // "{label} {n}" suffixes and rebuilds dynamic tag/review leaves.
    void apply_counts(const CatalogCounts& counts);
    void set_trash_count(int count);

    // Paging (#1046): materialize next page for a group; returns true when
    // pages remain after it. group_key ∈ {"well","reference_well",
    // "seismic_survey","geological_entity"}.
    bool activate_next_page(const std::string& group_key);
    int entity_population(const std::string& group_key) const;

    // Selection semantics.
    const std::vector<NavRow>& rows() const { return rows_; }
    std::optional<int> selected_row() const { return selected_; }
    FilterQuery current_filter_query() const;
    std::string selected_category() const;
    // Select a row; emits nothing itself (shell diffs & forwards signals).
    void select(std::optional<int> row);
    // Map → Data direction: materialize pages until the well row exists,
    // select it. Returns false when the id is unknown.
    bool highlight_well(const std::string& well_id);
    // Row lookup helpers (tests + shell).
    std::optional<int> find_entity_row(const std::string& entity_id) const;
    std::optional<int> find_row_by_key_prefix(const std::string& label) const;
    // Context-menu classification for the Qt shell:
    //   "manage_tags" on the tag group, "delete_well" on a concrete well row.
    enum class RowMenu { None, ManageTags, DeleteWell };
    RowMenu row_menu(int row) const;

private:
    struct EntityPage {
        std::string group_key;
        std::string icon;
        std::string count_key;      // entity-type key into _entity_counts
        std::vector<NavEntity> entities;
        int rendered = 0;
        // entity_id → links (well/reference_well pages only; empty map ⇒
        // the per-well role-group block is skipped entirely, matching the
        // Python `if well_links:` truthiness gate).
        std::map<std::string, std::vector<NavEntityLink>> well_links;
        std::set<std::string> unresolved;
        std::set<std::string> invalid_coord;
        int group_id = -1;          // stable row id of the group header
        std::optional<std::string> selected_key;
    };

    // Stable row ids — rows_ entries shift indices as dynamic subtrees are
    // rebuilt, so group/structural rows are referenced by id and resolved
    // to an index on use. row_ids_[i] pairs with rows_[i].
    int append_row(NavRow row, int parent);
    int subtree_end(int row) const;
    int index_of_id(int id) const;
    void erase_rows(int first, int last);   // [first, last)
    void erase_children(int parent_row);
    void rebuild_entity_groups();
    void append_entity_page(const std::string& group_key);
    void materialize_page_for(const std::string& group_key,
                              const std::string& entity_id);
    void update_tag_nodes(const std::map<std::string, int>& tag_counts);
    void update_review_nodes(const std::map<std::string, int>& review_counts);
    std::string label_base(int row) const;      // text minus trailing " n"
    void reset_filter_to_all();
    std::string asset_label(const std::string& asset_id) const;

    NavProjectView project_;
    bool has_project_ = false;
    std::vector<NavRow> rows_;
    std::vector<int> row_ids_;       // stable id per row (header comment above)
    int next_row_id_ = 1;
    std::optional<int> selected_;
    // Stable row ids for structural rows (resolve via index_of_id).
    int all_row_ = -1, trash_row_ = -1, overview_row_ = -1;
    int tag_group_row_ = -1, review_group_row_ = -1, geo_group_row_ = -1;
    int well_group_row_ = -1, ref_well_group_row_ = -1, survey_group_row_ = -1;
    std::map<std::string, EntityPage> pages_;
    std::map<std::pair<std::string, std::string>, int> entity_counts_;

    RoleOrderFn role_order_;
    RoleDisplayFn role_display_;
    AssetLabelFn asset_label_;
};

}  // namespace pwb::ui_pages_data
