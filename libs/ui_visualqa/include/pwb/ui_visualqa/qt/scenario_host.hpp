#pragma once

// UI-16 — V11 scenario builders + surface seams (qt target).
//
// visual_qa_v11.py builds REAL panel widgets (DataPage / TaskPanelBase /
// WorkstationInspector / TaskCenter / MappingStageBar+Panel /
// SeismicContextToolbar / CommandPalette / state widgets) with only
// synthetic facts injected. The C++ port does the same where the panels
// are already ported:
//
//   real C++ widgets:  PredictionTaskPanel, SeismicContextToolbar,
//                      WorkstationInspector, WorkstationTaskCenter +
//                      OperationRegistry, CommandPalette +
//                      CommandRegistry (authoritative evaluator), the
//                      PwbEmpty/Loading/Badge state widgets
//   injected surfaces: AppShell (unported — integration domain),
//                      DataPage (UI-06 deferred), MappingStageBar+Panel
//                      (UI-13 composite — not merged at this baseline)
//
// A scenario whose surface seam is unbound builds an honest
// seam-unavailable placeholder — never a fake widget — and its check
// run reports the reason.

#include <functional>
#include <memory>
#include <string>
#include <vector>

#include <QWidget>

#include <pwb/ui_visualqa/qa_check.hpp>
#include <pwb/ui_visualqa/qa_snapshot.hpp>

namespace pwb::ui_visualqa::qt {

// ---- shell-bound surfaces -----------------------------------------------

// first_open_empty_shell — the AppShell facts the check reads
// (ws.inspector.header, ws.inspector._current identity vs shell.project,
// task_center.model.rowCount, project wells/resources).
class QaShellSurface {
public:
    virtual ~QaShellSurface() = default;
    virtual QWidget* widget() = 0;
    virtual QaShellSnapshot snapshot() const = 0;
};

// data_manager_surface — the DataPage facts (asset rows vs project
// resources, inspector title/empty/tabs). refresh + select_asset are
// the Python _refresh/_set_selected_asset/_update_inspector sequence.
class QaDataPageSurface {
public:
    virtual ~QaDataPageSurface() = default;
    virtual QWidget* widget() = 0;
    virtual int resource_count() const = 0;
    virtual void refresh() = 0;
    virtual void select_asset(int index) = 0;
    virtual QaDataManagerSnapshot snapshot() const = 0;
};

// stage_bar_phase{1,2,3} (+ theme_matrix_smoke reuse) — the
// MappingStageBar+Panel facts the check reads (bar markers, panel page,
// horizon, constraints row). set_horizon_state/set_stage are the
// builder's set_horizon_state/set_current_stage+set_stage parity.
class QaStageSurface {
public:
    virtual ~QaStageSurface() = default;
    virtual QWidget* widget() = 0;
    virtual void set_horizon_state(
        const std::string& current,
        const std::vector<std::string>& horizons) = 0;
    virtual void set_stage(const std::string& stage_value) = 0;
    virtual QaStageSurfaceSnapshot snapshot() const = 0;
};

// One stage-scoped palette command row (the Python shell's
// _register_stage_palette_commands parity — a STAGE_CONTEXT_ACTIONS
// row + its STAGE_ACTION_TOOLS mapping). The vocabulary itself is
// unported domain data (mapping_workspace/stage_vocabulary.py — not
// in this slice's scope), so the command_palette_disabled_reason
// scenario receives it through this seam rather than re-declaring a
// second table here. Empty = the palette registers no stage commands
// (palette_has_disabled_command then reports honestly).
struct QaStageActionSpec {
    std::string stage_value;  // stages whitelist (single value)
    std::string action_id;
    std::string title;        // label suffix after "阶段动作 · "
    std::string tool_id;      // STAGE_ACTION_TOOLS mapping; "" = none
};

// The injected factories + vocabulary. An unset std::function = seam
// unbound — the scenario reports unavailable honestly.
struct ScenarioSeams {
    std::function<std::unique_ptr<QaShellSurface>()> shell_factory;
    std::function<std::unique_ptr<QaDataPageSurface>()> data_page_factory;
    std::function<std::unique_ptr<QaStageSurface>()> stage_surface_factory;
    // Stage-scoped command vocabulary (stage_vocabulary.py parity) —
    // the host injects the authoritative table.
    std::vector<QaStageActionSpec> stage_actions;
};

// ---- scenario handles -----------------------------------------------------

// Owns one built scenario widget plus whatever the checks probe. The
// collector fills exactly the scenario's ScenarioSnapshot section —
// widget-side reads stay in the qt layer, verdicts stay in the core.
class ScenarioHandle {
public:
    virtual ~ScenarioHandle() = default;
    // The grabbable widget (never null for a known scenario — seam-
    // unbound scenarios return the honest placeholder).
    virtual QWidget* widget() = 0;
    // False when the scenario needed an unbound surface seam — the
    // widget() is then the seam-unavailable placeholder.
    virtual bool available() const { return true; }
    virtual std::string unavailable_reason() const { return {}; }
    // Collect this scenario's facts (the Python check's widget reads).
    virtual void collect(ScenarioSnapshot& out) = 0;
};

// build_scenario(name, seams) — KeyError parity for unknown names
// (throws std::invalid_argument).
std::unique_ptr<ScenarioHandle> build_scenario(
    const std::string& name, const ScenarioSeams& seams = {});

// run_scenario_checks(name, handle) — collect() then the pure check
// table; unavailable surfaces report `surface_available:false` + the
// seam reason (non-gating harness parity — the gate tests assert only
// on available surfaces).
std::vector<CheckResult> run_scenario_checks(const std::string& name,
                                             ScenarioHandle& handle);

// ---- per-scenario builders (the Python build_<scenario> parity) ----------

std::unique_ptr<ScenarioHandle> build_first_open_empty_shell(
    const ScenarioSeams& seams);
std::unique_ptr<ScenarioHandle> build_data_manager_surface(
    const ScenarioSeams& seams);
std::unique_ptr<ScenarioHandle> build_well_task_workflow_panel();
std::unique_ptr<ScenarioHandle> build_seismic_context_surface();
std::unique_ptr<ScenarioHandle> build_stage_bar_phase(
    const std::string& stage_value, const ScenarioSeams& seams);
std::unique_ptr<ScenarioHandle> build_inspector_version_payload();
std::unique_ptr<ScenarioHandle> build_inspector_run_payload();
std::unique_ptr<ScenarioHandle> build_task_center_operations();
// The palette wires the real CommandPalette + CommandRegistry +
// CommandContext directly (the Python AppShell parity); the stage-action
// vocabulary arrives through seams.stage_actions.
std::unique_ptr<ScenarioHandle> build_command_palette_disabled_reason(
    const ScenarioSeams& seams);
std::unique_ptr<ScenarioHandle> build_error_empty_states_composite();
std::unique_ptr<ScenarioHandle> build_theme_matrix_smoke(
    const ScenarioSeams& seams);

}  // namespace pwb::ui_visualqa::qt
