#include "pwb/ui_shell/deferred_page_bindings.hpp"

#include <utility>

namespace pwb::ui_shell {

void DeferredPageBindings::schedule(int index, std::string name,
                                    std::function<void()> callback) {
    auto& list = pending_[index];
    for (auto& entry : list) {
        if (entry.first == name) {
            entry.second = std::move(callback);
            return;
        }
    }
    list.emplace_back(std::move(name), std::move(callback));
}

void DeferredPageBindings::flush(int index) {
    // Drain until stable: bindings may enqueue further bindings for the same
    // index during the flush.
    for (;;) {
        const auto it = pending_.find(index);
        if (it == pending_.end() || it->second.empty()) {
            return;
        }
        BindingList callbacks = std::move(it->second);
        pending_.erase(it);

        // "project" assignment runs ahead of state callbacks regardless of
        // enqueue order.
        std::function<void()> project;
        BindingList rest;
        rest.reserve(callbacks.size());
        for (auto& [name, cb] : callbacks) {
            if (name == "project" && !project) {
                project = std::move(cb);
            } else {
                rest.emplace_back(std::move(name), std::move(cb));
            }
        }
        if (project) {
            project();
        }
        for (auto& [name, cb] : rest) {
            if (cb) {
                cb();
            }
        }
    }
}

bool DeferredPageBindings::has_pending(int index) const {
    const auto it = pending_.find(index);
    return it != pending_.end() && !it->second.empty();
}

}  // namespace pwb::ui_shell
