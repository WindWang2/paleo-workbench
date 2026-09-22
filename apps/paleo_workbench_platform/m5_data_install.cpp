#include "m5_data_install.hpp"

#include "app_context.hpp"
#include "app_shell.hpp"
#include "data_lineage_panel.hpp"

#include <pwb/ui_pages_data/asset_view.hpp>
#include <pwb/ui_pages_data/qt/asset_selection_bus.hpp>
#include <pwb/ui_pages_data/qt/data_detail_panel.hpp>
#include <pwb/ui_pages_data/qt/data_workspace.hpp>

#include <QTabWidget>

namespace pwb::app::m5_data {

void install(const Install& install) {
    auto* shell = install.shell;
    auto* workspace =
        shell != nullptr ? shell->data_workspace() : nullptr;
    if (workspace == nullptr) return;
    auto* bus = workspace->selection_bus();

    // 原型 ws0 右列 = 数据属性（上）+ 数据血缘/处理流程（下）。
    // 数据属性：真实元数据表单（类型/格式/状态/路径/校验），选择走
    // 单一 AssetSelectionBus 权威 —— 与数据表/血缘同一选择。
    auto* detail =
        new pwb::ui_pages_data::qt::DataDetailPanel(workspace);
    if (bus != nullptr) {
        QObject::connect(
            bus, &pwb::ui_pages_data::qt::AssetSelectionBus::
                     current_asset_changed,
            detail,
            [detail](const std::optional<
                     pwb::ui_pages_data::AssetRow>& asset) {
                detail->update_asset(asset);
            });
    }
    workspace->set_inspector_panel(detail);

    // 数据血缘：真实版本历史 + 来源关系（DataLineagePanel）。面板自身
    // 对血缘读侧切片缺席降级诚实（PWB_WITH_V14_DATA_LINEAGE 门查询）。
    auto* lineage = new DataLineagePanel(workspace);
    lineage->set_context(install.context);
    if (bus != nullptr) lineage->bind_selection_bus(bus);
    QObject::connect(lineage, &DataLineagePanel::status_message, shell,
                     &AppShell::status_message);
    workspace->set_lineage_panel(lineage);

    // 原型 ws0 表格下页签的「版本历史 | 关联关系」—— 与右列血缘同一
    // 权威的另一视图：第二实例只做数据控制器（自身隐藏），其两个真实
    // 页提入底部页签条；两个实例订阅同一 bus，选择一致。
    auto* bottom_lineage = new DataLineagePanel(workspace);
    bottom_lineage->set_context(install.context);
    if (bus != nullptr) bottom_lineage->bind_selection_bus(bus);
    QObject::connect(bottom_lineage, &DataLineagePanel::status_message,
                     shell, &AppShell::status_message);
    if (auto* tabs = workspace->bottom_tabs(); tabs != nullptr) {
        QWidget* history = bottom_lineage->tabs()->widget(0);
        QWidget* relations = bottom_lineage->tabs()->widget(1);
        tabs->addTab(history, QStringLiteral("版本历史"));
        tabs->addTab(relations, QStringLiteral("关联关系"));
    }
    bottom_lineage->hide();  // 控制器壳隐藏，页面已提入底签
}

}  // namespace pwb::app::m5_data
