// UI-06 — resource_table.py :: ResourceTable Qt shell.
//
// 工程资源清单表 — QTableView + object model (ui.modelview seam inlined:
// ColumnSpec columns over AssetView rows, bind_table_defaults verbatim).
// Status-column foreground token comes from table_model.hpp.
#pragma once

#include <QAbstractTableModel>
#include <QTableView>
#include <QWidget>

#include <vector>

#include <pwb/ui_pages_data/asset_view.hpp>

class QLabel;

namespace pwb::ui_pages_data::qt {

// modelview.ObjectTableModel seam — ColumnSpec columns over AssetView rows.
// Headers: 文件名 类型 格式 状态 路径 (COLUMN_HEADERS verbatim).
class ResourceTableModel : public QAbstractTableModel {
    Q_OBJECT
public:
    explicit ResourceTableModel(QObject* parent = nullptr);

    void set_rows(std::vector<AssetView> rows);
    const AssetView* row_at(int row) const;
    // key_of parity: id → path → name (first non-empty).
    std::string key_for_row(int row) const;
    int index_for_key(const std::string& key) const;

    int rowCount(const QModelIndex& parent = {}) const override;
    int columnCount(const QModelIndex& parent = {}) const override;
    QVariant data(const QModelIndex& index,
                  int role = Qt::ItemDataRole::DisplayRole) const override;
    QVariant headerData(int section, Qt::Orientation orientation,
                        int role = Qt::ItemDataRole::DisplayRole) const override;

private:
    std::vector<AssetView> rows_;
};

class ResourceTable : public QWidget {
    Q_OBJECT
public:
    explicit ResourceTable(QWidget* parent = nullptr);

    void update_resources(std::vector<AssetView> resources);
    QTableView* table() { return table_; }
    ResourceTableModel* model() { return model_; }

protected:
    void resizeEvent(QResizeEvent* event) override;

private:
    void update_empty_state();

    ResourceTableModel* model_;
    QTableView* table_;
    QLabel* empty_state_;
};

}  // namespace pwb::ui_pages_data::qt
