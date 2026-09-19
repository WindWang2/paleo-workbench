#pragma once

// Port of paleo_workbench/ui/dock_framework.py data layer (UI-01).
// Dock identity, default geometry and floatability live here as data.
// Qt-free: the shell consumes DockRegistry at construction; nothing else may
// hardcode dock identity. The Qt resize helpers (ensure_dock_usable /
// apply_first_run_sizes) live in the qt target (dock_resize.hpp).

#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::ui_shell {

enum class DockImportance {
    Core,       // mapping-critical chrome (nav, layers, inspector)
    Secondary,  // workflow panels (stage, input, linked views)
    Utility,    // bottom-row utilities (agent, tasks, logs, console)
};

// Dock areas by name — plain strings so the data layer stays Qt-free.
inline constexpr char kAreaLeft[] = "left";
inline constexpr char kAreaRight[] = "right";
inline constexpr char kAreaBottom[] = "bottom";

struct DockDescriptor {
    // min_floating_size applies ONLY while floating — a docked dock must never
    // carry a structural minimum (audit B-1/B-2). preferred_size is a
    // first-run/reset resizeDocks target, never applied on preset switches.
    std::string dock_id;
    std::string title;
    std::string preferred_area = kAreaLeft;
    DockImportance importance = DockImportance::Secondary;
    bool default_visible = true;
    // False for GL-bearing content: reparenting a GL viewport between
    // top-levels is the documented EGL segfault class.
    bool can_float = true;
    bool can_tabify = true;
    std::pair<int, int> min_floating_size{220, 160};
    std::optional<std::pair<int, int>> preferred_size;
    // Vertical split preferred height inside its area column (first-run only).
    std::optional<int> preferred_height;
    std::vector<std::string> workflow_tags;
    std::vector<std::string> context_tags;
    // Defaulted to "WorkstationDock_" + title by the registry (keeps the
    // historical objectName scheme so persisted layouts keep resolving).
    std::string object_name;
    std::string remark;
};

class DockRegistry {
public:
    explicit DockRegistry(std::vector<DockDescriptor> descriptors);

    const std::vector<DockDescriptor>& descriptors() const { return descriptors_; }
    std::vector<std::string> ids() const;
    const DockDescriptor* get(const std::string& dock_id) const;
    // Throws std::out_of_range for unknown ids (Python KeyError parity).
    const DockDescriptor& require(const std::string& dock_id) const;
    // Descriptor order preserved (Python tuple order).
    std::vector<const DockDescriptor*> by_tag(const std::string& tag) const;

private:
    std::vector<DockDescriptor> descriptors_;
    std::map<std::string, std::size_t> by_id_;
};

// Canonical workstation dock set. Order = canonical layout application order.
// Global constant (Python module-level `workstation_dock_registry` parity).
const DockRegistry& workstation_dock_registry();

// Logical window-width classes (V9 §8). Thresholds are in *logical* pixels.
enum class ViewportClass {
    Compact,    // < 1100  — 1366@125%, small laptops
    Normal,     // 1100-1599
    Wide,       // 1600-2199 — 1080p class
    Ultrawide,  // >= 2200 — 1440p+, 4K
};

inline constexpr int kViewportCompactMax = 1099;
inline constexpr int kViewportWideMin = 1600;
inline constexpr int kViewportUltrawideMin = 2200;

// Responsive inspector policy thresholds (window width, hysteresis band).
inline constexpr int kInspectorHideBelow = 1100;
inline constexpr int kInspectorRestoreAbove = 1200;

// App-bar command input minimum width per viewport class.
inline constexpr int kCommandInputFloorCompact = 220;
inline constexpr int kCommandInputFloorNormal = 300;

ViewportClass classify_viewport(int width);
const char* viewport_class_name(ViewportClass cls);

}  // namespace pwb::ui_shell
