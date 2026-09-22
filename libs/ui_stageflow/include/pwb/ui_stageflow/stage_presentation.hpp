#pragma once

// V14-THREE-STAGE-UX — stage presentation projection (Qt-free core).
//
// Design contract (docs/development/v14-three-stage-ux/02-architecture.md):
//  * This module holds NO domain authority. The runtime stage authority is
//    ProjectSession::mapping_stage(); the persisted value is the project
//    document's mapping_workspace.current_stage. Everything here is a
//    derived projection consumed by the workbench presentation layer.
//  * StageLayoutProfile is a pure function of the stage value — its panel
//    visibility derives from tool_policy::kStageGroupVisibility semantics
//    (stage1 hides factor/layout_export, stage2 shows factor, stage3 shows
//    layout_export), so presentation can never drift from tool gating.
//  * Persistence carries USER PREFERENCES ONLY (per-stage dock overrides,
//    split ratios) through an injected KV sink; scientific state never
//    passes through this module.

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include <pwb/tool_policy/stages.hpp>

namespace pwb::ui_stageflow {

// ---------------------------------------------------------------------------
// Snapshot — immutable derived view of the workbench stage context.
// ---------------------------------------------------------------------------

enum class StageReadinessKind { Unknown, Ready, ReadyWithWarnings, NotReady };

struct StagePresentationSnapshot {
    // MappingStage.value ("facies_calibration" | "constraint_factor |
    // integrated_compilation"); empty = no project / not entered.
    std::string stage_value;
    // Derived display label (tool_policy stage_label; raw value when the
    // stage is unknown — honest, never guessed).
    std::string stage_label;
    // project.stratigraphy.target_horizon (nullopt = no project / absent).
    std::optional<std::string> horizon;
    bool project_open = false;
    bool write_granted = false;
    int running_tasks = 0;
    StageReadinessKind readiness = StageReadinessKind::Unknown;

    bool operator==(const StagePresentationSnapshot&) const = default;
};

// Canonical stage values (tool_policy authority, listed for consumers).
inline constexpr const char* kStage1Value = "facies_calibration";
inline constexpr const char* kStage2Value = "constraint_factor";
inline constexpr const char* kStage3Value = "integrated_compilation";

std::string stage_display_label(const std::string& stage_value);

// ---------------------------------------------------------------------------
// StageLayoutProfile — the per-stage "stage setting" of the workbench.
// ---------------------------------------------------------------------------

// Lower-pane focus per stage (presentation hint; the surfaces themselves are
// owned by the dock/panel hosts).
inline constexpr const char* kLowerPaneNone = "none";
inline constexpr const char* kLowerPaneSeismicWell = "seismic_well";
inline constexpr const char* kLowerPaneCrossWell = "crosswell";
inline constexpr const char* kLowerPaneFactors = "factors";

struct StageLayoutProfile {
    std::string stage_value;
    // dock/panel visibility for the docks the profile manages. Keys are
    // namespaced: "workstation.<dock_id>" (WorkstationFrame registry),
    // "mapping.<panel>" (MappingPage dock manager), "window.<dock>"
    // (MainWindow-level docks). Absent key = not managed by the profile
    // (user/viewport policy keeps control) — profiles never fight the user
    // for docks they do not own.
    std::map<std::string, bool> visibility;
    std::string lower_pane_mode = kLowerPaneNone;
};

// Pure derivation from the stage value. Unknown/empty stage -> the stage-1
// profile (lenient fallback, workspace codec parity).
StageLayoutProfile stage_layout_profile(const std::string& stage_value);

// Generalized presentation profile (M2 of docs/development/
// ribbon-five-workspaces/00-plan.md, D2 extension): the same projection
// mechanism keyed by an arbitrary presentation key. The three stage values
// resolve to the stage profiles above; the two non-scientific workspaces
// add their own profiles ("data_management" / "validation" — entering
// 数据管理/验证 must reshape the docks without rewriting the stage):
//   data_management: every science/mapping surface hidden (the data page
//     owns the central area); nav/inspector/tasks stay user-policy.
//   validation: the review/QC surfaces on (mapping chrome/reference/bottom),
//     composer + factor/constraint surfaces off.
// Unknown keys keep the stage-1 lenient fallback.
StageLayoutProfile presentation_profile(const std::string& presentation_key);

// The two non-scientific workspace presentation keys (pwb::ui_ribbon
// workspace ids; duplicated as literals here to keep this core Qt-free and
// ui_ribbon-independent).
inline constexpr const char* kPresentationDataManagement = "data_management";
inline constexpr const char* kPresentationValidation = "validation";

// All keys any profile manages (stable order) — assertion/test surface.
std::vector<std::string> profile_managed_keys();

// ---------------------------------------------------------------------------
// Per-stage user preferences (QSettings-backed through an injected sink).
// ---------------------------------------------------------------------------

// Minimal KV seam so the Qt-free core stays testable; the Qt side binds a
// QSettings group. save/load round-trip the overrides for one stage.
struct StagePreferenceSink {
    // key is "<stage>/<name>" relative to the stage_presentation group.
    std::function<std::optional<std::string>(const std::string& key)> load;
    std::function<void(const std::string& key, const std::string& value)> save;
};

struct StageUserPreferences {
    // dock/panel key -> visible. Only entries the user explicitly toggled;
    // the profile default fills the rest.
    std::map<std::string, bool> visibility_overrides;

    bool operator==(const StageUserPreferences&) const = default;
};

// Parse/serialize. Serialization is a compact "key=value" comma list —
// corrupt entries are skipped (honest partial load), and an unknown dock
// key is preserved verbatim so a future profile can adopt it.
std::string serialize_stage_preferences(const StageUserPreferences& prefs);
StageUserPreferences parse_stage_preferences(const std::string& blob);

class StagePreferenceStore {
public:
    explicit StagePreferenceStore(StagePreferenceSink sink);

    // Version fence: stored "version" must match kPreferenceVersion exactly
    // for any load to succeed (window-layout restore parity); a mismatch
    // yields empty preferences and the next save rewrites the fence.
    static constexpr int kPreferenceVersion = 1;

    StageUserPreferences load(const std::string& stage_value) const;
    void save(const std::string& stage_value,
              const StageUserPreferences& prefs);
    // Test/diagnostic channel.
    StagePreferenceSink& sink() { return sink_; }

private:
    StagePreferenceSink sink_;
};

// Effective visibility = profile default overridden by user toggles.
std::map<std::string, bool> effective_visibility(
    const StageLayoutProfile& profile,
    const StageUserPreferences& prefs);

}  // namespace pwb::ui_stageflow
