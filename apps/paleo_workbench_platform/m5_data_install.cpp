#include "m5_data_install.hpp"

#if defined(PWB_WITH_V14_DATA_LINEAGE)

#include "app_context.hpp"
#include "app_shell.hpp"
#include "data_lineage_panel.hpp"

#include <pwb/ui_pages_data/qt/asset_selection_bus.hpp>
#include <pwb/ui_pages_data/qt/data_workspace.hpp>

namespace pwb::app::m5_data {

void install(const Install& install) {
    auto* shell = install.shell;
    if (shell == nullptr || shell->data_workspace() == nullptr) {
        return;
    }
    auto* panel = new DataLineagePanel(shell);
    panel->set_context(install.context);
    // 选择状态单一权威：直接订阅数据页已绑定的 AssetSelectionBus。
    if (auto* bus = shell->data_workspace()->selection_bus();
        bus != nullptr) {
        panel->bind_selection_bus(bus);
    }
    QObject::connect(panel, &DataLineagePanel::status_message, shell,
                     &AppShell::status_message);
    // inspector 槽 = ws0 右侧属性/版本/来源区域（浮动体系原生支持）。
    shell->data_workspace()->set_inspector_panel(panel);
}

}  // namespace pwb::app::m5_data

#endif  // PWB_WITH_V14_DATA_LINEAGE
