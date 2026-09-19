#pragma once

// Port of paleo_workbench/ui/workstation/ui_context.py (UI-12).
// Derived UI context — presentation aggregation, NOT a second domain
// authority (goal V6 §2):
//
//  * The service holds no domain state; every snapshot field comes from a
//    registered provider (authority-side adapter: selection context /
//    mapping workspace controller / QGIS bridge probe / permission /
//    task scheduler…).
//  * Absent provider -> field is an honest unknown (nullopt / safe
//    default), never fabricated.
//  * Provider exception -> logged + falls back to unknown (fail-closed,
//    no UI crash).
//  * refresh() is triggered by authority change signals on the GUI
//    thread; snapshots are immutable, compared by value, and
//    context_changed is emitted only on real change.
//
// Qt-free core. The Qt signal shell is UIContextServiceQt
// (ui_context_qt.hpp).

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <variant>
#include <vector>

namespace pwb::ui_workstation {

// Field values a provider may return. monostate == explicit unknown
// (Python None). Wrong-typed values coerce to unknown (fail-closed —
// see ui_context.cpp notes).
using UIContextFieldValue =
    std::variant<std::monostate, bool, int, std::string,
                 std::vector<std::string>>;

struct UIContextSnapshot {
    // Project context
    bool project_open = false;
    std::optional<std::string> project_name;
    // Workspace / mapping stage (MappingStage.value; nullopt = no project
    // or mapping not entered)
    std::optional<std::string> mapping_stage;
    std::optional<std::string> mapping_stage_label;
    // Active edit target (role-resolved layer id and its role verdict)
    std::optional<std::string> active_layer_id;
    std::optional<std::string> active_layer_role;
    std::optional<bool> active_layer_editable;
    std::optional<std::string> active_layer_block_reason;
    // Active layer geometry kind / maturity / freeze-miss-degrade facts
    // (nullopt = honest unknown)
    std::optional<std::string> active_layer_kind;
    std::optional<std::string> active_layer_maturity;
    bool active_layer_frozen = false;
    bool active_layer_missing = false;
    bool active_layer_degraded = false;
    // Active layer is raster/reference (vector-only tool gate input)
    bool active_layer_is_raster = false;
    // Data-source writability — orthogonal to the role-gate editable
    // verdict (nullopt = provider absent)
    std::optional<bool> active_layer_writable;
    bool editing_active = false;
    // Edit-session run facts (nullopt = provider absent, conservative
    // handling downstream)
    std::optional<bool> editing_dirty;
    std::optional<int> selection_count;
    std::optional<bool> can_undo;
    std::optional<bool> can_redo;
    // split/merge/reshape session-geometry preconditions (host collectors;
    // nullopt = provider absent -> conservative disable)
    std::optional<bool> split_ready;
    std::optional<bool> merge_ready;
    std::optional<bool> reshape_ready;
    // Native canvas availability + capability flags (nullopt/empty =
    // provider absent -> conservative)
    std::optional<bool> native_canvas_available;
    std::vector<std::string> native_capability_flags;
    // Modal blocking-task label (nullopt = provider absent -> treated as
    // no blocking task; execution-side re-gate still intercepts)
    std::optional<std::string> blocking_task;
    // Queryable layer count (identify gate input; nullopt = provider
    // absent -> adapter falls back to "active layer means 1")
    std::optional<int> queryable_layer_count;
    // SelectionContext geological slot summaries
    std::optional<std::string> active_well_id;
    std::optional<std::string> active_horizon_id;
    std::optional<std::string> active_fault_id;
    std::optional<std::string> active_interpretation_id;
    // V11 slot summaries (authority stays in SelectionContext / DataPage /
    // MappingWorkspaceController; these are derived projections)
    std::optional<std::string> selected_layer_id;
    std::optional<std::string> edit_target_layer_id;
    std::optional<std::string> selected_asset_id;
    std::optional<std::string> selected_version_id;
    std::optional<std::string> active_survey_id;
    std::optional<std::string> active_task_id;
    // Workflow stage (same-authority value as mapping_stage)
    std::optional<std::string> workflow_stage;
    // Currently running operation label (nullopt = no foreground op)
    std::optional<std::string> running_operation;
    // Backend capability / degraded path
    std::optional<bool> qgis_bridge_available;
    // Capability tri-state (native/degraded/unavailable) + reason
    std::optional<std::string> capability_mode;
    std::optional<std::string> capability_reason;
    // Permission (WRITE grant; authority in action permissions)
    bool write_granted = false;
    // Task-state summary (task scheduler authority)
    int running_task_count = 0;

    bool operator==(const UIContextSnapshot&) const = default;
};

// All snapshot field names (Python frozenset parity — provider
// registration validates against this set).
const std::vector<std::string>& ui_context_field_names();
bool ui_context_has_field(const std::string& name);

class UIContextService {
public:
    using Provider = std::function<UIContextFieldValue()>;
    using ChangeListener =
        std::function<void(const UIContextSnapshot&)>;

    UIContextService() = default;

    // Register/replace a field adapter. `name` must be a snapshot field
    // name; unknown names throw std::out_of_range (Python KeyError
    // parity).
    void set_provider(const std::string& name, Provider fn);
    void clear_provider(const std::string& name);
    bool has_provider(const std::string& name) const;

    // Build a snapshot from current provider values (no notification;
    // provider exceptions degrade to unknown).
    UIContextSnapshot snapshot() const;

    // The snapshot from the last refresh(); when never refreshed,
    // computed on demand (Python `current` parity).
    UIContextSnapshot current() const;

    // Rebuild the snapshot; notify the change listener only on real
    // change (returns the new snapshot either way).
    UIContextSnapshot refresh();

    // Qt-free notification seam — the Qt shell binds a signal emission;
    // tests bind a recorder. Single listener (Python context_changed
    // parity); re-set replaces.
    void set_change_listener(ChangeListener listener);

private:
    std::map<std::string, Provider> providers_;
    std::optional<UIContextSnapshot> last_;
    ChangeListener listener_;
};

}  // namespace pwb::ui_workstation
