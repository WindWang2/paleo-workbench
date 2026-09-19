// UI-08 — paleo_workbench/ui/pages/table_preview_widget.py port (the
// inspector-side surface): QTableView + lazy string model with
// ``load_table(headers, rows)`` and the QTableWidget-compatible cell
// accessors host panels/tests rely on.
#pragma once

#include <QTableView>

#include <QString>
#include <QStringList>
#include <vector>

class QKeyEvent;

namespace pwb::ui_pages_mapedit {

class TablePreviewModel;

class TablePreviewWidget : public QTableView {
    Q_OBJECT
public:
    explicit TablePreviewWidget(QWidget* parent = nullptr);

    // load_table(("属性", "值"), ((k, v), ...)) — headers + string rows.
    // Enforces the Python MAX_PREVIEW_CELLS truncation contract.
    void load_table(const QStringList& headers,
                    const std::vector<QStringList>& rows);

    // Python ``apply_settings(settings)``: font size + auto-fit flag.
    void apply_settings(int font_size, bool auto_fit_columns);

    // 返回当前显示表格的 TSV（含表头），仅复制已截断后的可见行。
    QString copy_all() const;

    int rowCount() const;     // QTableWidget parity
    int columnCount() const;  // QTableWidget parity
    QString item_text(int row, int column) const;
    QStringList row_text(int row) const;  // copy/export path parity
    QString horizontal_header_text(int column) const;
    // Python setRangeSelected(table_range, select) compat.
    void set_range_selected(int top_row, int left_column, int bottom_row,
                            int right_column, bool select);
    // Public seam for _fit_key_value_table (protected sizeHintForColumn).
    int column_content_width(int column) const {
        return sizeHintForColumn(column);
    }

    TablePreviewModel* preview_model() const { return model_; }

    // Python widget attributes.
    bool auto_fit_columns = true;
    bool truncated = false;
    QString truncation_message;

protected:
    void keyPressEvent(QKeyEvent* event) override;

private:
    TablePreviewModel* model_ = nullptr;  // owned via setModel (Qt parent)
};

}  // namespace pwb::ui_pages_mapedit
