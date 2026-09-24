#pragma once

// M5-3 — 数据管理 (ws0) 右侧「版本历史 / 来源关系」面板 (F:52-54):
//
//   * 选中资产 → 经 catalog 真实血缘链 (closure_data_workspace::
//     lineage_rows, build_lineage_chain 读侧) 上屏：版本历史 =
//     ancestors 链（本版本的来历），来源关系 = descendants 链（下游影响）；
//   * 资产→版本解析走活动工程目录快照的真实 current_version_id
//     （无版本 → 诚实空态，不编造）；
//   * 选择状态 = AssetSelectionBus 单一权威（面板只订阅
//     current_asset_changed，不维护第二份选择）；
//   * 面板挂进 DataWorkspace 的 inspector 槽（set_inspector_panel），
//     随数据页浮动体系工作。
//
// 血缘查询仅在 PWB_WITH_V14_DATA_LINEAGE 构建中可用；其它构建面板
// 给出诚实原因（不伪造链）。

#include <functional>

#include <QWidget>

class QLabel;
class QListWidget;
class QTabWidget;
class QTableWidget;

namespace pwb::app {
class AppContext;
}
namespace pwb::ui_pages_data::qt {
class AssetSelectionBus;
}

namespace pwb::app {

class DataLineagePanel : public QWidget {
    Q_OBJECT
public:
    explicit DataLineagePanel(QWidget* parent = nullptr);

    // Host seams (the M5 data install binds these).
    void set_context(AppContext* context);
    void bind_selection_bus(
        pwb::ui_pages_data::qt::AssetSelectionBus* bus);

    // Test/inspection surface.
    QTabWidget* tabs() const { return tabs_; }
    QTableWidget* history_table() const { return history_; }
    QTableWidget* lineage_table() const { return lineage_; }
    QListWidget* impact_list() const { return impact_; }
    QLabel* header() const { return header_; }

signals:
    void status_message(const QString& message);

private:
    void refresh();
    void fill_table(QTableWidget* table, const QString& direction,
                    const QString& asset_label);
    void fill_impact(const QString& asset_label);

    AppContext* context_ = nullptr;
    pwb::ui_pages_data::qt::AssetSelectionBus* bus_ = nullptr;
    QLabel* header_ = nullptr;
    QTabWidget* tabs_ = nullptr;
    QTableWidget* history_ = nullptr;
    QTableWidget* lineage_ = nullptr;
    QListWidget* impact_ = nullptr;  // tab 2: 删除/替换影响分析
};

}  // namespace pwb::app
