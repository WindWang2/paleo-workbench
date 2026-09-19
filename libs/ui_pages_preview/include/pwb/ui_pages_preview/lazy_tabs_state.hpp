#pragma once

// Port of paleo_workbench/ui/pages/lazy_visualization_tabs.py state machine
// (UI-07) — Qt-free part. The QTabWidget shell owns the actual widgets;
// this tracks the observable contract: which tab is current, which visual
// page shows, the _requested latch and visualization_requested emissions.

namespace pwb::ui_pages_preview {

enum class VisualPage {
    prompt,    // "点击此选项卡生成可视化预览"
    loading,   // "正在生成可视化预览…"
    message,   // error panel with reload button
    host,      // the visualization host widget
};

struct LazyTabsState {
    bool requested = false;
    int current_tab = 0;                 // 0 = 数据列表, 1 = 可视化预览
    VisualPage visual = VisualPage::prompt;
    int visualization_emitted = 0;       // visualization_requested count

    // _on_current_changed(index): only a first click on tab 1 emits —
    // index!=1 or already requested → no-op.
    void tab_changed(int index);

    // load_summary(): requested=false, prompt, tab back to 0.
    void load_summary();

    // show_loading(): requested=true, loading page. No tab steal (background
    // prefetches also emit loading; completion owns the same contract #630).
    void show_loading();

    // show_preview(activate): visual=host; tab=1 when activate || already
    // on the visual tab. requested=true.
    void show_preview(bool activate);

    // show_error(retryable, activate): visual=message; requested=!retryable
    // (a structural error latches "already asked" only when not retryable);
    // tab=1 when activate || already on the visual tab.
    void show_error(bool retryable, bool activate);

    // _request_retry(): requested=true, emits visualization_requested.
    void request_retry();

    // reset(): requested=false, prompt, tab 0.
    void reset();
};

}  // namespace pwb::ui_pages_preview
