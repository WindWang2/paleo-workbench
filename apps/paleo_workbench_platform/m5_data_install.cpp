#include "m5_data_install.hpp"

#include "app_context.hpp"
#include "app_shell.hpp"
#include "data_lineage_panel.hpp"

#include <pwb/ui_pages_data/asset_view.hpp>
#include <pwb/ui_pages_data/qt/asset_selection_bus.hpp>
#include <pwb/ui_pages_data/qt/data_detail_panel.hpp>
#include <pwb/ui_pages_data/qt/data_workspace.hpp>
#include <pwb/ui_workstation/workstation_frame.hpp>

#include <QSplitter>
#include <QTabWidget>

namespace pwb::app::m5_data {

void install(const Install& install) {
    auto* shell = install.shell;
    auto* workspace =
        shell != nullptr ? shell->data_workspace() : nullptr;
    auto* frame =
        shell != nullptr ? shell->workstation() : nullptr;
    if (workspace == nullptr || frame == nullptr) return;
    auto* bus = workspace->selection_bus();

    // mockup 精确还原（ws0）：右列 = 数据属性（上）+ 数据血缘（下）
    // 竖排同显 —— 回到 DataWorkspace 页内 right_column_ 槽位（替换
    // 占位槽），不再是壳层右栏 dock。
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

    // 数据血缘：真实版本历史 + 来源关系（DataLineagePanel）。面板自身
    // 对血缘读侧切片缺席降级诚实（PWB_WITH_V14_DATA_LINEAGE 门查询）。
    auto* lineage = new DataLineagePanel(workspace);
    lineage->set_context(install.context);
    if (bus != nullptr) lineage->bind_selection_bus(bus);
    QObject::connect(lineage, &DataLineagePanel::status_message, shell,
                     &AppShell::status_message);

    // 页内右列竖排：[属性(0) | 血缘(1)] —— 占位槽位原位替换。
    if (auto* right =
            qobject_cast<QSplitter*>(workspace->right_column());
        right != nullptr) {
        right->insertWidget(0, detail);
        right->insertWidget(1, lineage);
        if (auto* old = right->widget(2)) old->hide();
        if (auto* old = right->widget(3)) old->hide();
        right->setSizes({260, 140});
    }

    // 原型 ws0 底签「版本历史 | 关联关系」—— 与右列血缘同一权威的另
    // 一视图：第二实例只做数据控制器（自身隐藏），其两个真实页进页
    // 内底签（稿中它们在数据列表下方的页内 tab 区）。
    auto* bottom_lineage = new DataLineagePanel(workspace);
    bottom_lineage->set_context(install.context);
    if (bus != nullptr) bottom_lineage->bind_selection_bus(bus);
    QObject::connect(bottom_lineage, &DataLineagePanel::status_message,
                     shell, &AppShell::status_message);
    // 先取指针再 reparent —— QTabWidget 页索引随移除前移，按序取会
    // 越界丢页。
    auto* history_page = bottom_lineage->tabs()->widget(0);
    auto* relations_page = bottom_lineage->tabs()->widget(1);
    if (auto* tabs =
            qobject_cast<QTabWidget*>(workspace->bottom_tabs());
        tabs != nullptr) {
        tabs->addTab(history_page, QStringLiteral("版本历史"));
        tabs->addTab(relations_page, QStringLiteral("关联关系"));
        tabs->show();
    }
    bottom_lineage->hide();  // 控制器壳隐藏，页面已提入页内底签
}

}  // namespace pwb::app::m5_data
