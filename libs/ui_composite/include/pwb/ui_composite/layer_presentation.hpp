// V14 layer presentation — the per-layer row status language for the
// layer manager panel / status bar (Prompt V14 §12; contracts 03 §9).
//
// Pure data projection: inputs are the binding record, freshness probe,
// edit state and target state; outputs are stable flag strings the panel
// renders as icons/chips instead of text walls. Flag vocabulary is
// frozen and aligned with the native bridge's setRowIndicators kinds
// (dirty/stale/missing/missing_input/superseded/degraded/frozen/
// published/reviewed) plus the target/binding flags from this line.
// Qt-free; Prompt 2's panels consume it.
#pragma once

#include "pwb/workspace/state.hpp"

#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_composite {

// Freshness vocabulary (derived from the dependency service; unknown
// when no probe is wired — never guessed).
enum class LayerFreshness {
    Fresh,
    Stale,
    SourceMissing,
    Superseded,
    Unknown,
};

struct LayerRowInputs {
    std::string layer_id;
    const pwb::workspace::LayerBinding* binding = nullptr;
    bool is_active = false;        // == active target
    bool is_editing = false;       // open edit session
    bool is_dirty = false;         // uncommitted geometry/attribute edits
    bool is_selected = false;      // tree selection
    bool is_locked = false;        // business/group lock
    LayerFreshness freshness = LayerFreshness::Unknown;
    bool selection_mismatch = false;  // selection != tool write target
    // RAW protection comes from the role vocabulary (raw roles are
    // edit-gated; the register/编辑 gate enforces it — this only shows).
};

struct LayerRowStatus {
    std::vector<std::string> flags;  // frozen vocabulary, stable order
    std::string role;                // binding role ("" unknown)
    bool raw_protected = false;      // role is a RAW source (no direct edit)
    bool bound_to_version = false;   // catalog_version pin
    bool bound_by_fingerprint = false;  // content_fingerprint pin
    bool binding_unknown = true;     // no membership record

    bool has_flag(const std::string& flag) const {
        return std::find(flags.begin(), flags.end(), flag) != flags.end();
    }
};

// Compute the row status (pure; deterministic).
LayerRowStatus build_layer_row_status(const LayerRowInputs& inputs);

// Human-readable one-line summary for tooltips (order: role → binding →
// freshness → targets).
std::string layer_row_summary(const LayerRowInputs& inputs);

}  // namespace pwb::ui_composite
