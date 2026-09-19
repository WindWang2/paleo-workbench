#pragma once

// Port of paleo_workbench/ui/deferred_page_bindings.py (UI-01).
// Small main-thread queue for non-visible project-page bindings: holds only
// the newest callback for each named binding and owns no project model —
// callers retain authority for the live document and invoke flush() on the
// GUI thread.
// Qt-free.

#include <functional>
#include <map>
#include <string>
#include <vector>

namespace pwb::ui_shell {

class DeferredPageBindings {
public:
    // Queue `callback` under `name` for page `index`. Re-scheduling the same
    // name replaces the callback but keeps its original position (Python
    // dict-assignment parity).
    void schedule(int index, std::string name, std::function<void()> callback);

    // Drain every binding queued for `index` until stable: a binding may
    // enqueue further bindings for the same index, so first navigation never
    // requires a second click. The binding named "project" runs ahead of
    // state callbacks regardless of enqueue order.
    void flush(int index);

    bool has_pending(int index) const;

private:
    using BindingList = std::vector<std::pair<std::string, std::function<void()>>>;
    std::map<int, BindingList> pending_;
};

}  // namespace pwb::ui_shell
