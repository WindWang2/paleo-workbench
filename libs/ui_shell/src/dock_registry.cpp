#include "pwb/ui_shell/dock_registry.hpp"

#include <stdexcept>
#include <utility>

namespace pwb::ui_shell {

namespace {

std::vector<DockDescriptor> make_workstation_docks() {
    auto d = [](std::string id, std::string title) {
        DockDescriptor desc;
        desc.dock_id = std::move(id);
        desc.title = std::move(title);
        return desc;
    };
    std::vector<DockDescriptor> docks;
    docks.reserve(14);

    {
        auto x = d("nav", "资源管理器");
        x.importance = DockImportance::Core;
        x.preferred_size = std::pair{280, 0};
        x.preferred_height = 420;
        x.workflow_tags = {"always"};
        x.remark = "rail + explorer";
        docks.push_back(std::move(x));
    }
    {
        auto x = d("mapping_stage", "编图阶段");
        x.preferred_size = std::pair{280, 0};
        x.preferred_height = 280;
        x.workflow_tags = {"mapping"};
        docks.push_back(std::move(x));
    }
    {
        auto x = d("inspector", "检查器");
        x.preferred_area = kAreaRight;
        x.importance = DockImportance::Core;
        x.preferred_size = std::pair{300, 0};
        x.workflow_tags = {"always"};
        docks.push_back(std::move(x));
    }
    {
        auto x = d("composite_layer", "图层管理");
        x.preferred_area = kAreaRight;
        x.importance = DockImportance::Core;
        x.preferred_size = std::pair{300, 0};
        x.workflow_tags = {"mapping"};
        docks.push_back(std::move(x));
    }
    {
        auto x = d("facies_palette", "相带画刷");
        x.preferred_area = kAreaRight;
        x.preferred_size = std::pair{240, 0};
        x.workflow_tags = {"mapping"};
        x.remark = "M2 相带调色板 + 吸色管 + 数字键装备";
        docks.push_back(std::move(x));
    }
    {
        auto x = d("hub", "功能页");
        x.preferred_area = kAreaRight;
        x.default_visible = false;
        // Hosts the whole page stack incl. the 3D GL page — never float.
        x.can_float = false;
        x.workflow_tags = {"navigation"};
        docks.push_back(std::move(x));
    }
    {
        auto x = d("composite_input", "输入与结果");
        x.default_visible = false;
        x.preferred_size = std::pair{280, 0};
        x.workflow_tags = {"mapping", "review"};
        docks.push_back(std::move(x));
    }
    {
        auto x = d("agent", "Agent");
        x.preferred_area = kAreaBottom;
        x.importance = DockImportance::Utility;
        x.default_visible = false;
        x.preferred_height = 245;
        x.workflow_tags = {"assistant"};
        docks.push_back(std::move(x));
    }
    {
        auto x = d("tasks", "任务中心");
        x.preferred_area = kAreaBottom;
        x.importance = DockImportance::Utility;
        x.default_visible = false;
        x.preferred_height = 200;
        x.workflow_tags = {"background"};
        docks.push_back(std::move(x));
    }
    {
        auto x = d("logs", "日志");
        x.preferred_area = kAreaBottom;
        x.importance = DockImportance::Utility;
        x.default_visible = false;
        x.preferred_height = 200;
        x.workflow_tags = {"diagnostics"};
        docks.push_back(std::move(x));
    }
    {
        auto x = d("console", "控制台");
        x.preferred_area = kAreaBottom;
        x.importance = DockImportance::Utility;
        x.default_visible = false;
        x.preferred_height = 200;
        x.workflow_tags = {"diagnostics"};
        docks.push_back(std::move(x));
    }
    {
        auto x = d("composite_linked", "联动视图");
        x.preferred_area = kAreaBottom;
        x.default_visible = false;
        x.preferred_height = 200;
        x.workflow_tags = {"mapping", "interpretation"};
        docks.push_back(std::move(x));
    }
    {
        auto x = d("well", "测井轨道");
        x.preferred_area = kAreaBottom;
        x.default_visible = false;
        // GL track canvas inside — floating reparents the GL context.
        x.can_float = false;
        x.preferred_height = 200;
        x.workflow_tags = {"well", "interpretation"};
        docks.push_back(std::move(x));
    }
    {
        auto x = d("seismic", "地震剖面");
        x.preferred_area = kAreaBottom;
        x.default_visible = false;
        x.can_float = false;
        x.preferred_height = 200;
        x.workflow_tags = {"seismic", "interpretation"};
        docks.push_back(std::move(x));
    }
    return docks;
}

}  // namespace

DockRegistry::DockRegistry(std::vector<DockDescriptor> descriptors)
    : descriptors_(std::move(descriptors)) {
    for (std::size_t i = 0; i < descriptors_.size(); ++i) {
        auto& desc = descriptors_[i];
        // Python __post_init__ parity: empty object_name gets the historical
        // scheme so persisted layouts (saveState bytes) keep resolving.
        if (desc.object_name.empty()) {
            desc.object_name = "WorkstationDock_" + desc.title;
        }
        const auto [it, inserted] = by_id_.emplace(desc.dock_id, i);
        if (!inserted) {
            throw std::invalid_argument("duplicate dock_id in descriptor set");
        }
    }
}

std::vector<std::string> DockRegistry::ids() const {
    std::vector<std::string> out;
    out.reserve(descriptors_.size());
    for (const auto& d : descriptors_) {
        out.push_back(d.dock_id);
    }
    return out;
}

const DockDescriptor* DockRegistry::get(const std::string& dock_id) const {
    const auto it = by_id_.find(dock_id);
    return it == by_id_.end() ? nullptr : &descriptors_[it->second];
}

const DockDescriptor& DockRegistry::require(const std::string& dock_id) const {
    const auto* desc = get(dock_id);
    if (desc == nullptr) {
        throw std::out_of_range("unknown dock_id: '" + dock_id + "'");
    }
    return *desc;
}

std::vector<const DockDescriptor*> DockRegistry::by_tag(
    const std::string& tag) const {
    std::vector<const DockDescriptor*> out;
    for (const auto& d : descriptors_) {
        for (const auto& t : d.workflow_tags) {
            if (t == tag) {
                out.push_back(&d);
                break;
            }
        }
    }
    return out;
}

const DockRegistry& workstation_dock_registry() {
    static const DockRegistry registry(make_workstation_docks());
    return registry;
}

ViewportClass classify_viewport(int width) {
    if (width <= kViewportCompactMax) {
        return ViewportClass::Compact;
    }
    if (width >= kViewportUltrawideMin) {
        return ViewportClass::Ultrawide;
    }
    if (width >= kViewportWideMin) {
        return ViewportClass::Wide;
    }
    return ViewportClass::Normal;
}

const char* viewport_class_name(ViewportClass cls) {
    switch (cls) {
        case ViewportClass::Compact:
            return "compact";
        case ViewportClass::Normal:
            return "normal";
        case ViewportClass::Wide:
            return "wide";
        case ViewportClass::Ultrawide:
            return "ultrawide";
    }
    return "normal";
}

}  // namespace pwb::ui_shell
