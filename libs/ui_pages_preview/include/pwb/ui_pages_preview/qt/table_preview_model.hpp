#pragma once

// Port of paleo_workbench/ui/pages/table_preview_widget.py TablePreviewModel
// (UI-07): virtual read-only model over detached row vectors — cell text and
// formatting computed on demand for the viewport only (#1039).

#include <QAbstractTableModel>
#include <QFont>
#include <QString>
#include <vector>

#include <pwb/ui_pages_preview/preview_table.hpp>  // CellKind

namespace pwb::ui_pages_preview {

class TablePreviewModel : public QAbstractTableModel {
    Q_OBJECT
public:
    explicit TablePreviewModel(QObject* parent = nullptr);

    void set_table(std::vector<std::string> headers,
                   std::vector<std::vector<std::string>> rows);

    int rowCount(const QModelIndex& parent = {}) const override;
    int columnCount(const QModelIndex& parent = {}) const override;
    QVariant headerData(int section, Qt::Orientation orientation,
                        int role = Qt::DisplayRole) const override;
    QVariant data(const QModelIndex& index,
                  int role = Qt::DisplayRole) const override;

    // Formatted cell strings of one row (copy/export path).
    std::vector<std::string> row_text(int row) const;
    const std::vector<std::string>& headers() const { return headers_; }

private:
    std::vector<std::string> headers_;
    std::vector<std::vector<std::string>> rows_;
    // Precomputed at set_table (#1388): data() serves 4-6 roles per
    // visible cell; trim + cell_kind were recomputed per role.
    std::vector<std::vector<std::string>> cell_texts_;
    std::vector<std::vector<CellKind>> cell_kinds_;
    int depth_col_ = -1;
    bool curve_def_ = false;
    QFont mono_;
    QFont mono_bold_;
};

}  // namespace pwb::ui_pages_preview
