// UI-06 — debounce/persist timings + data_toolbar verify-state model.
//
// The Python widgets own the QTimers; the Qt-free core pins the constants
// and the verify button's two-state toggle so tests don't depend on wall
// time.
#pragma once

#include <string>
#include <string_view>

namespace pwb::ui_pages_data {

// data_toolbar: search text debounce (self._search_timer.setInterval).
inline constexpr int kSearchDebounceMs = 180;
// tag_widgets.TagManagerWidget search debounce (_SEARCH_DEBOUNCE_MS).
inline constexpr int kTagSearchDebounceMs = 200;
// data_workspace: splitter persist delay (_DOCKED_SIZES_DELAY_MS).
inline constexpr int kLayoutPersistDelayMs = 400;
// data_page: bounded cooperative-shutdown wait (_SHUTDOWN_WAIT_MS = 5000).
inline constexpr int kWorkerShutdownTimeoutMs = 5000;

// data_toolbar.set_verify_running(running): button text + tooltip swap.
// The separate 取消导入 button's visibility is driven by IMPORT state
// (data_page sets toolbar.cancel_import_btn.setVisible(running)) — not
// by verify state.
struct VerifyButtonState {
    std::string text;
    std::string tooltip;
};
inline VerifyButtonState verify_button_state(bool verifying) {
    if (verifying) {
        return {"取消校验", "取消正在进行的完整性校验"};
    }
    return {"完整性校验", "后台校验数据资产完整性与 SHA-256"};
}

// Tag filter operator vocabulary (data_toolbar tag and/or selector).
inline constexpr std::string_view kTagOpAnd = "and";
inline constexpr std::string_view kTagOpOr = "or";

}  // namespace pwb::ui_pages_data
