#pragma once

// LayoutAuthority — QgsLayoutManager-backed persistent layout authority
// (docs/development/qgis-native-layout-convergence/01).
//
// Every compilation document is a *real* QgsPrintLayout registered in the
// MapSession project's layout manager. The authority owns the lifecycle
// (create / instantiate / migrate / duplicate / remove), persistence
// (serialize/restore into the project document — the host calls
// serialize_state() from its save hook and restore_state() on open), and
// the dirty contract (a single is_dirty()/mark_saved() pair over all layout
// undo stacks feeding the project save flow).

#include <pwb/domain/json.hpp>
#include <pwb/qgis/map_session.hpp>

#include <array>
#include <memory>
#include <optional>
#include <string>
#include <vector>

class QgsPrintLayout;

namespace pwb::qgis {

struct LayoutInfo {
    std::string name;
    std::string template_id;
    std::string template_category;
    std::string legacy_composition_id;
    bool dirty = false;
    int item_count = 0;
};

class LayoutAuthority {
public:
    explicit LayoutAuthority(MapSession& session);

    // Fresh empty layout (A4 landscape, QGIS defaults).
    QgsPrintLayout* create_layout(const std::string& name);

    // Native geological-template instantiation: the declarative composer
    // template definitions (mapping_document — retained as template
    // semantics source) materialized through the shared element engine
    // into a persistent layout registered in the manager.
    struct InstantiateReport {
        QgsPrintLayout* layout = nullptr;
        int items = 0;
        std::vector<std::string> warnings;
    };
    InstantiateReport instantiate_template(const std::string& template_id,
                                           const std::string& title = {});

    // One-shot legacy Composition migration (idempotent per composition
    // id: a second call for the same document reports skipped).
    struct MigrationResult {
        QgsPrintLayout* layout = nullptr;
        int items = 0;
        std::vector<std::string> unknown_types;
        std::vector<std::string> warnings;
        bool skipped_already_migrated = false;
        std::string layout_name;
    };
    MigrationResult migrate_composition(const domain::Json& composition_json,
                                        const std::string& preferred_name = {});

    std::vector<LayoutInfo> layouts() const;
    QgsPrintLayout* layout_by_name(const std::string& name) const;
    bool remove_layout(const std::string& name);
    QgsPrintLayout* duplicate_layout(const std::string& name,
                                     const std::string& new_name);
    // Drop every layout (project switch: the previous project's layouts
    // must not leak into the next one).
    void clear();

    // Phase 8: re-sync every map item's layers (and the main map's extent
    // when the live canvas provides one) to the current session state, so
    // the layout map and the canvas consume the same layers/renderer
    // authority. Call before preview/export.
    void sync_map_state(QgsPrintLayout* layout);

    // Extent/CRS seed for template maps (defaults to the session's live
    // canvas state; overridable for tests/headless use).
    void set_map_seed(const std::optional<std::array<double, 4>>& extent,
                      const std::string& crs);

    // ---- persistence ------------------------------------------------------
    // Section shape (ProjectDocument::root()["layouts"]):
    //   {"version": 1, "layouts": [{"name", "template_id",
    //     "template_category", "legacy_composition_id", "xml"}, ...]}
    domain::Json serialize_state() const;
    struct RestoreReport {
        int restored = 0;
        std::vector<std::string> errors;
    };
    RestoreReport restore_state(const domain::Json& state);

    // ---- dirty contract (single project save hook) ------------------------
    bool is_dirty() const;
    void mark_saved();

    // Unique-name helper ("图" → "图 2" → "图 3" …).
    std::string unique_layout_name(const std::string& base) const;

private:
    QgsPrintLayout* register_layout(std::unique_ptr<QgsPrintLayout> layout,
                                    const std::string& name);
    MapSession& session_;
    std::optional<std::array<double, 4>> seed_extent_;
    std::string seed_crs_;
};

}  // namespace pwb::qgis
