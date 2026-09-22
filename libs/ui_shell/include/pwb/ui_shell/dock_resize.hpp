#pragma once

// Port of paleo_workbench/ui/dock_framework.py QMainWindow helpers (UI-01):
// ensure_dock_usable + apply_first_run_sizes. Grow-only programmatic
// resizing — never shrink a user-arranged dock (audit B-3).

class QMainWindow;
class QDockWidget;

#include <map>
#include <string>

namespace pwb::ui_shell {

// Grow-only programmatic resize: may only grow a dock currently below the
// usability floor, never shrink or pin a user-chosen size. Returns true
// when a resize was issued. No-op for floating/hidden/null docks.
bool ensure_dock_usable(QMainWindow* host, QDockWidget* dock, int minimum,
                        bool vertical);

// First-run / explicit-reset sizing from the registry's preferred_size.
// Replaces the hardcoded resizeDocks block (shell B-3): sizes come from
// descriptors; call only on first run or explicit layout reset — never on
// preset apply. Missing dock ids are skipped; missing descriptors use the
// same fallbacks as the Python call sites.
// include_heights=false skips the vertical resizeDocks pass — used by the
// deferred post-show re-run so the bottom strip can't squeeze the central
// science splitter below its 65:35 seed.
void apply_first_run_sizes(
    QMainWindow* host,
    const std::map<std::string, QDockWidget*>& docks_by_id,
    bool include_heights = true);

}  // namespace pwb::ui_shell
