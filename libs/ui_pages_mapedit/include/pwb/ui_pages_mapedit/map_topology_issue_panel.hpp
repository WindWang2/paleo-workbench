// UI-08 — paleo_workbench/ui/pages/map_topology_issue_panel.py port: the
// bottom-workbench「拓扑问题」panel — QTableView + ObjectTableModel over
// issue dicts (rows keyed "i:feature_id"), PwbEmptyState overlay, and the
// QTableWidget-compat accessors tests drive.
//
// Issue dicts are QVariantMap (feature_id/message/severity/...
// — the Json→variant bridge happens at the scene's emit).
#pragma once

#include <QTableView>
#include <QWidget>

#include <QString>
#include <QVariantMap>
#include <optional>
#include <vector>

class QLabel;
class QModelIndex;

namespace pwb::ui_data_core {
class Json;
}
namespace pwb::ui_widgets {
class ObjectTableModel;
class PwbEmptyState;
}  // namespace pwb::ui_widgets

namespace pwb::ui_pages_mapedit {

// _TopologyCellProxy — test-facing cell handle (row/column/text).
class TopologyCellProxy {
public:
    TopologyCellProxy(QAbstractItemModel* model, int row, int column)
        : model_(model), row_(row), column_(column) {}

    int row() const { return row_; }
    int column() const { return column_; }
    QString text() const;

private:
    QAbstractItemModel* model_;
    int row_;
    int column_;
};

// _TopologyTableView — QTableView + QTableWidget-compat accessors
// (itemDoubleClicked signal/cell positioning).
class TopologyTableView : public QTableView {
    Q_OBJECT
public:
    explicit TopologyTableView(QWidget* parent = nullptr);

    int rowCount() const;
    // Ephemeral cell view (Python item() parity): owned by the view,
    // replaced on the next item() call — never null-checked away by
    // callers but also never leaked.
    TopologyCellProxy* item(int row, int column);
    void setCurrentCell(int row, int column);
    void emit_item_double_clicked(const QModelIndex& index);

signals:
    // QTableWidget 兼容信号：(row, column)/(item) 语义。
    void itemDoubleClicked(TopologyCellProxy* item);

private:
    std::optional<TopologyCellProxy> last_item_;
};

class MapTopologyIssuePanel : public QWidget {
    Q_OBJECT
public:
    explicit MapTopologyIssuePanel(QWidget* parent = nullptr);

    // set_issues(list of dicts) — issues as QVariantMap rows.
    void set_issues(const std::vector<QVariantMap>& issues);
    const std::vector<QVariantMap>& issues() const { return issues_; }

    QLabel* summary = nullptr;
    TopologyTableView* table = nullptr;

signals:
    void locate_requested(const QString& feature_id);

protected:
    void resizeEvent(QResizeEvent* event) override;

private:
    void on_item_double_clicked(TopologyCellProxy* item);
    void on_row_activated(const QModelIndex& index);
    void update_empty_state();

    std::vector<QVariantMap> issues_;
    ui_widgets::ObjectTableModel* model_ = nullptr;
    ui_widgets::PwbEmptyState* empty_state_ = nullptr;
};

}  // namespace pwb::ui_pages_mapedit
