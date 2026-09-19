#pragma once

// UI-10 — sequence framework page cores.
//
// Ports:
//   * workflow/stratigraphy.py — apply_stratigraphy_scheme /
//     set_target_from_boundary / active_target_horizon, operating on typed
//     host-collected slices (never a live ProjectDocument);
//   * sequence_target_panel.py update_state semantics — the combo option
//     list, selection, scope/version labels and the committed-edit dedupe
//     contract (target_changed only fires on Enter / dropdown commit);
//   * sequence_boundary_table.py — the (name, target, note) row model;
//   * sequence_scheme_summary.py — the summary field texts.

#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_seqviz {

// ---------------------------------------------------------------------------
// Stratigraphy slices (host-collected on the GUI thread)
// ---------------------------------------------------------------------------

// StratigraphicFramework — the fields the sequence pages read/write.
struct StratigraphySlice {
    std::string target_horizon;
    std::string interpretation_version = "v1";
    std::string systems_tract_scheme;
    std::vector<std::string> applicable_wells;
    std::vector<std::string> applicable_seismic_ranges;
    std::vector<std::string> sequence_boundaries;
};

struct CompilationRunSlice {
    std::string target_horizon;
    std::string sequence_scheme_ref;
};

struct PaleoMapDocumentSlice {
    std::string linked_target_horizon;
};

// The target-horizon binding fields (FactorMapTask). `name` participates in
// the horizon-prefix rename rule.
struct FactorTaskHorizonSlice {
    std::string target_horizon;
    std::string name;
    std::string factor_type;
};

struct StratigraphyProjectSlice {
    StratigraphySlice stratigraphy;
    std::vector<CompilationRunSlice> compilation_runs;
    std::vector<PaleoMapDocumentSlice> paleomap_documents;
    std::vector<FactorTaskHorizonSlice> factor_map_tasks;
};

// ---------------------------------------------------------------------------
// workflow/stratigraphy.py ports
// ---------------------------------------------------------------------------

// apply_stratigraphy_scheme — write the given fields, then (target change +
// bind_downstream) propagate the new horizon into the LAST compilation run,
// paleomap linked horizons and factor tasks that are empty or still carry
// the previous horizon (unrelated horizons are never clobbered).
StratigraphySlice& apply_stratigraphy_scheme(
    StratigraphyProjectSlice& project,
    std::optional<std::string> target_horizon = std::nullopt,
    std::optional<std::string> systems_tract_scheme = std::nullopt,
    std::optional<std::string> interpretation_version = std::nullopt,
    std::optional<std::vector<std::string>> sequence_boundaries = std::nullopt,
    bool bind_downstream = true);

// set_target_from_boundary — append the boundary to the catalog when new,
// then apply it as the active target horizon. Empty names are a no-op.
StratigraphySlice& set_target_from_boundary(
    StratigraphyProjectSlice& project, const std::string& boundary,
    bool bind_downstream = true);

// active_target_horizon — the single source of truth for the mapping/prep
// horizon: last compilation run's target first, else stratigraphy's.
std::string active_target_horizon(const StratigraphyProjectSlice& project);

// ---------------------------------------------------------------------------
// sequence_target_panel.py — update_state view
// ---------------------------------------------------------------------------

// The widget-facing snapshot of update_state: the target combo's option
// list (unique non-empty boundaries, active target promoted to front, a
// single "" item when empty), the selected index (-1 → free edit text),
// and the read-only version / scheme / scope labels.
struct SequenceTargetView {
    std::vector<std::string> options;
    int selected_index = 0;         // index into options; -1 → edit_text
    std::string edit_text;          // line-edit text ("" when index >= 0)
    std::string version_text;       // interpretation_version or "v1"
    std::string scheme_text;        // systems_tract_scheme or "LST/TST/HST"
    std::string scope_text;         // "N 口井 / M 条测线"
    // The committed-target cache resyncs to the project's target — a
    // programmatic refresh to a different target must not drop the next
    // user re-commit (#894-5).
    std::optional<std::string> last_committed_target;
};

SequenceTargetView sequence_target_view(const StratigraphySlice& stratigraphy);

// _on_target_committed dedupe: both returnPressed and activated fire for a
// single Enter on an editable combo — emit only when the committed text
// differs from the last committed target.
struct TargetCommitTracker {
    std::optional<std::string> last;

    // Returns true when `text` is a NEW committed target (advances `last`).
    bool should_emit(const std::string& text) {
        if (last.has_value() && *last == text) {
            return false;
        }
        last = text;
        return true;
    }

    // update_state resyncs the cache to the project's target.
    void resync(std::optional<std::string> target) { last = std::move(target); }
};

// ---------------------------------------------------------------------------
// sequence_boundary_table.py — row model
// ---------------------------------------------------------------------------

struct BoundaryRow {
    std::string name;    // column 0
    std::string target;  // column 1 — target_horizon or 未设置
    std::string note;    // column 2 — 当前目标 / 第 N 层序界面
};

std::vector<BoundaryRow> sequence_boundary_rows(
    const StratigraphySlice& stratigraphy);

// ---------------------------------------------------------------------------
// sequence_scheme_summary.py — summary texts
// ---------------------------------------------------------------------------

struct SequenceSchemeSummaryView {
    std::string scheme_text;          // systems_tract_scheme or LST/TST/HST
    std::string boundary_count_text;  // "N 个"
    std::string systems_tract_text;   // "LST / TST / HST"
    std::string status_text;          // 目标 X / 未设置目标层位
};

SequenceSchemeSummaryView sequence_scheme_summary_view(
    const StratigraphySlice& stratigraphy);

}  // namespace pwb::ui_seqviz
