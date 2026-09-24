#pragma once

// DataManagementPage — 数据管理页（两页壳层第 0 页）：
// QSplitter 两栏 —— 左「数据列表」(QTreeView)，右「信息展示」
// (选中条目的详情面板)。条目由宿主经 set_entries 注入（工程
// catalog 快照）；无工程/空目录时列表呈现诚实空态。

#include <QVector>
#include <QWidget>

class QStandardItemModel;
class QTextBrowser;
class QTreeView;

namespace pwb::app {

struct DataEntry {
    QString name;      // 显示名（资产/版本 id）
    QString kind;      // 类型（asset kind / payload format）
    QString location;  // 位置（catalog 相对路径 / 源 URI）
    QString detail;    // 详情（右栏展示的原始摘要，可为 HTML 文本）
};

class DataManagementPage : public QWidget {
    Q_OBJECT
public:
    explicit DataManagementPage(QWidget* parent = nullptr);

    // 一次整体替换列表内容（工程打开/关闭/保存后宿主重推）。
    void set_entries(const QVector<DataEntry>& entries);

signals:
    // 工具行「刷新」按钮 —— 宿主重读数据权威后回推 set_entries。
    void refresh_requested();

private:
    QTreeView* list_ = nullptr;
    QStandardItemModel* model_ = nullptr;
    QTextBrowser* info_ = nullptr;
};

}  // namespace pwb::app
