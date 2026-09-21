#pragma once

// V14-THREE-STAGE-UX — unified busy/empty/error/stale surface model
// (Qt-free core).
//
// The Pwb* state widgets (ui_widgets/states.hpp) and the StateToken
// vocabulary (ui_workstation/state_language.hpp) both exist; what was
// missing is ONE derivation layer that maps domain facts onto a closed
// surface kind with mandatory title/hint text. Pages consume
// surface_state_for(...) instead of hand-picking a widget per module —
// that is how "诚实失败" stops meaning "every page fails differently".
//
// Constraints:
//  * Fail-closed: unknown/absent domain input maps to Unsupported /
//    NoProject / NoSelection with honest text — never a fabricated Ready.
//  * Dual signal: every surface has text; the token adds glyph+tone for
//    the style layer only (state_language principle).

#include <optional>
#include <string>

namespace pwb::ui_stageflow {

enum class SurfaceKind {
    Ready,
    Loading,
    Busy,
    Queued,
    Cancelled,
    Stale,
    Degraded,
    MissingSource,
    Unsupported,
    Error,
    NoProject,
    NoLayer,
    NoSelection,
    Empty,
};

struct SurfaceState {
    SurfaceKind kind = SurfaceKind::Empty;
    std::string title;
    std::string hint;
    // Retry is only meaningful for transient failures (Error/MissingSource/
    // Stale); empty otherwise.
    std::string retry_action_id;

    bool operator==(const SurfaceState&) const = default;
};

// Map a surface kind onto presentation facts. Titles/hints are stable
// product strings (Chinese, matching the workbench vocabulary).
SurfaceState surface_state_for(SurfaceKind kind);

// Token category/value for the state_language bridge (Qt side):
//   Ready/Stale/MissingSource/Unsupported -> "freshness"
//   Loading/Busy/Queued/Cancelled/Error/Degraded -> "task"
//   NoProject/NoLayer/NoSelection/Empty -> "readiness" (info)
struct SurfaceTokenKey {
    std::string category;
    std::string value;
};
SurfaceTokenKey surface_token_key(SurfaceKind kind);

// Convenience derivation from common domain facts. `subject` names what
// the surface is about ("预测图层", "单因素结果"...); it is embedded into
// title/hint so the user knows WHAT is busy/stale/missing.
SurfaceState surface_for_task(bool running, bool queued, bool cancelled,
                              bool failed, const std::string& error,
                              const std::string& subject);
SurfaceState surface_for_factor(bool computing, bool stale, bool missing_input,
                                bool failed, const std::string& subject);

}  // namespace pwb::ui_stageflow
