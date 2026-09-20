// CLOSURE-PREVIEW (task 04) — the concrete row source the data page ships
// with. DataAssetTable's AssetRowSource seam was designed for UI-03's
// paged SQL model; until that host lands, the unified data page still
// needs a REAL working table — this vector-backed source mirrors the
// Python data_table_columns.COLUMN_DEFINITIONS vocabulary over AssetView
// rows and is auto-installed by DataAssetTable when the host has not
// injected its own model.
#pragma once

#include <QAbstractTableModel>

#include <vector>

#include <pwb/ui_pages_data/asset_view.hpp>
#include <pwb/ui_pages_data/qt/data_asset_table.hpp>

namespace pwb::ui_pages_data::qt {

class VectorAssetRowSource : public AssetRowSource {
    Q_OBJECT
public:
    explicit VectorAssetRowSource(QObject* parent = nullptr);

    // Replace the row set (canonical order preserved).
    void set_rows(const std::vector<AssetRow>& rows);

    // AssetRowSource:
    const AssetRow* asset_at(int row) const override;
    int rowCount(const QModelIndex& parent = QModelIndex{}) const override;
    int columnCount(const QModelIndex& parent = QModelIndex{}) const override;
    QVariant data(const QModelIndex& index,
                  int role = Qt::DisplayRole) const override;
    QVariant headerData(int section, Qt::Orientation orientation,
                        int role = Qt::DisplayRole) const override;

private:
    std::vector<AssetRow> rows_;
};

}  // namespace pwb::ui_pages_data::qt
