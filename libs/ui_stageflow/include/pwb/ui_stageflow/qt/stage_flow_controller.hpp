#pragma once

// V14-THREE-STAGE-UX — Qt shell of the stage presentation projection.
//
// StageFlowController is the ONE composition point that fans stage context
// out to the workbench surfaces (stage bar, dock visibility, status
// mirrors). It owns no domain authority: stage/horizon read+write go
// through injected seams that the platform install binds to
// ProjectSession / the project document. Missing seams degrade to honest
// no-ops — the controller never fabricates a stage.
//
// Threading: GUI thread only. Signals are direct-connection in practice;
// the snapshot type is still declared as a metatype for safety.

#include <functional>
#include <map>
#include <optional>
#include <string>

#include <QObject>
#include <QSettings>
#include <QString>

#include <pwb/ui_stageflow/stage_presentation.hpp>

namespace pwb::ui_stageflow::qt {

class StageFlowController : public QObject {
    Q_OBJECT
public:
    // Authority + application seams. All optional; an unset seam makes the
    // corresponding action a no-op (and the command layer will show it as
    // unavailable rather than silently succeeding).
    struct Seams {
        std::function<std::optional<std::string>()> read_stage;
        std::function<void(const std::string&)> apply_stage;
        std::function<std::optional<std::string>()> read_horizon;
        std::function<void(const std::string&)> apply_horizon;
        // Apply the effective per-stage visibility (already merged with
        // user preferences by the controller).
        std::function<void(const std::map<std::string, bool>&)> apply_visibility;
        // Facts for the snapshot (defaults keep honest unknowns).
        std::function<bool()> project_open;
        std::function<bool()> write_granted;
        std::function<int()> running_tasks;
        std::function<StageReadinessKind()> readiness;
    };

    explicit StageFlowController(StagePreferenceSink preference_sink,
                                 QObject* parent = nullptr);

    void set_seams(Seams seams) { seams_ = std::move(seams); }

    // Re-read the authorities, rebuild the snapshot, and — on a real
    // change — emit snapshot_changed + re-apply the stage layout.
    // Same-value refresh emits nothing (true-change contract, the
    // ThemeService precedent).
    void refresh();

    // User-intent entries (from the stage bar, commands, menus — all one
    // implementation). They route through the apply seams and then
    // refresh(); a missing apply seam is a no-op.
    void request_stage(const std::string& stage_value);
    void request_horizon(const std::string& horizon);

    // Explicit user dock toggle for the CURRENT stage (persisted as a
    // preference override and re-applied live).
    void set_panel_visible(const std::string& panel_key, bool visible);
    void reset_stage_preferences();  // "恢复本阶段默认布局"

    const StagePresentationSnapshot& snapshot() const { return snapshot_; }
    StageReadinessKind stage_readiness() const { return snapshot_.readiness; }

    // Test/inspection channel.
    size_t applied_visibility_count() const { return applied_visibility_count_; }

signals:
    void snapshot_changed();
    void stage_applied(const QString& stage_value);
    void horizon_applied(const QString& horizon);

private:
    void apply_stage_layout(const std::string& stage_value);

    Seams seams_;
    StagePreferenceStore preferences_;
    StagePresentationSnapshot snapshot_;
    size_t applied_visibility_count_ = 0;
};

// Bind a preference sink to a QSettings group ("stage_presentation/").
// Keys become "<group>/<key>" inside the given settings object — the
// caller owns the QSettings identity (PaleoWorkbench/Workstation).
StagePreferenceSink make_qsettings_preference_sink(QSettings& settings);

}  // namespace pwb::ui_stageflow::qt

Q_DECLARE_METATYPE(pwb::ui_stageflow::StagePresentationSnapshot)
