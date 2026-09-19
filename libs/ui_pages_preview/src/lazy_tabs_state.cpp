#include <pwb/ui_pages_preview/lazy_tabs_state.hpp>

namespace pwb::ui_pages_preview {

void LazyTabsState::tab_changed(int index) {
    current_tab = index;
    if (index != 1 || requested) return;
    requested = true;
    ++visualization_emitted;
}

void LazyTabsState::load_summary() {
    requested = false;
    visual = VisualPage::prompt;
    current_tab = 0;
}

void LazyTabsState::show_loading() {
    requested = true;
    visual = VisualPage::loading;
}

void LazyTabsState::show_preview(bool activate) {
    const bool was_visual = current_tab == 1;
    requested = true;
    visual = VisualPage::host;
    if (activate || was_visual) current_tab = 1;
}

void LazyTabsState::show_error(bool retryable, bool activate) {
    const bool was_visual = current_tab == 1;
    requested = !retryable;
    visual = VisualPage::message;
    if (activate || was_visual) {
        // Python: setCurrentIndex(1) → _on_current_changed — a still-false
        // _requested (retryable error) latches and emits through the tab
        // path, exactly like a user click.
        tab_changed(1);
    }
}

void LazyTabsState::request_retry() {
    requested = true;
    ++visualization_emitted;
}

void LazyTabsState::reset() {
    requested = false;
    visual = VisualPage::prompt;
    current_tab = 0;
}

}  // namespace pwb::ui_pages_preview
