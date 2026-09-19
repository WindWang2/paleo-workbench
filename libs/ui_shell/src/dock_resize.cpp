#include "pwb/ui_shell/dock_resize.hpp"

#include <QDockWidget>
#include <QMainWindow>

#include <pwb/ui_shell/dock_registry.hpp>

namespace pwb::ui_shell {

bool ensure_dock_usable(QMainWindow* host, QDockWidget* dock, int minimum,
                        bool vertical) {
    if (host == nullptr || dock == nullptr || dock->isFloating() ||
        !dock->isVisible()) {
        return false;
    }
    const int current = vertical ? dock->height() : dock->width();
    if (current >= minimum) {
        return false;
    }
    const auto orientation =
        vertical ? Qt::Orientation::Vertical : Qt::Orientation::Horizontal;
    host->resizeDocks({dock}, {minimum}, orientation);
    return true;
}

void apply_first_run_sizes(
    QMainWindow* host,
    const std::map<std::string, QDockWidget*>& docks_by_id) {
    if (host == nullptr) {
        return;
    }
    const DockRegistry& registry = workstation_dock_registry();

    auto dock = [&](const std::string& id) -> QDockWidget* {
        const auto it = docks_by_id.find(id);
        return it == docks_by_id.end() ? nullptr : it->second;
    };
    auto preferred_w = [&](const std::string& id, int fallback) {
        const DockDescriptor* d = registry.get(id);
        return (d != nullptr && d->preferred_size.has_value() &&
                d->preferred_size->first > 0)
                   ? d->preferred_size->first
                   : fallback;
    };
    auto preferred_h = [&](const std::string& id, int fallback) {
        const DockDescriptor* d = registry.get(id);
        return (d != nullptr && d->preferred_height.has_value() &&
                *d->preferred_height > 0)
                   ? *d->preferred_height
                   : fallback;
    };
    auto widths = [&](std::initializer_list<
                      std::pair<const char*, int>> pairs) {
        QList<QDockWidget*> docks;
        QList<int> sizes;
        for (const auto& [id, w] : pairs) {
            QDockWidget* d = dock(id);
            if (d != nullptr) {
                docks.push_back(d);
                sizes.push_back(w);
            }
        }
        if (!docks.isEmpty()) {
            host->resizeDocks(docks, sizes, Qt::Orientation::Horizontal);
        }
    };
    auto heights = [&](std::initializer_list<
                       std::pair<const char*, int>> pairs) {
        QList<QDockWidget*> docks;
        QList<int> sizes;
        for (const auto& [id, h] : pairs) {
            QDockWidget* d = dock(id);
            if (d != nullptr) {
                docks.push_back(d);
                sizes.push_back(h);
            }
        }
        if (!docks.isEmpty()) {
            host->resizeDocks(docks, sizes, Qt::Orientation::Vertical);
        }
    };

    widths({{"nav", preferred_w("nav", 280)}});
    widths({{"mapping_stage", preferred_w("mapping_stage", 280)},
            {"composite_input", preferred_w("composite_input", 280)}});
    heights({{"nav", preferred_h("nav", 420)},
             {"mapping_stage", preferred_h("mapping_stage", 280)}});
    widths({{"inspector", preferred_w("inspector", 300)},
            {"composite_layer", preferred_w("composite_layer", 300)}});
    heights({{"agent", preferred_h("agent", 200)},
             {"tasks", preferred_h("tasks", 200)},
             {"composite_linked", preferred_h("composite_linked", 200)}});
}

}  // namespace pwb::ui_shell
