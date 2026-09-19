#pragma once

// Port of paleo_workbench/ui/pages/table_preview_widget.py TablePreviewWidget
// (UI-07): virtualized read-only QTableView + TablePreviewModel (#1039).

#include <QTableView>
#include <vector>
#include <string>

#include <pwb/ui_pages_preview/qt/table_preview_model.hpp>

namespace pwb::ui_pages_preview {

struct PreviewSettings;

class TablePreviewWidget : public QTableView {
    Q_OBJECT
public:
    explicit TablePreviewWidget(QWidget* parent = nullptr);

    void apply_settings(const PreviewSettings& settings);

    // QTableWidget-compatible accessors used by host panels.
    int rowCount() const { return model_->rowCount(); }
    int columnCount() const { return model_->columnCount(); }
    int rowHeight(int row) const;
    int columnWidth(int column) const;
    QString item_text(int row, int column) const;
    QString header_text(int column) const;

    void load_table(const std::vector<std::string>& headers,
                    const std::vector<std::vector<std::string>>& rows);

    // TSV of the visible table (headers + truncated-visible rows).
    QString copy_all() const;

    bool truncated() const { return truncated_; }
    const QString& truncation_message() const { return truncation_message_; }
    bool auto_fit_columns() const { return auto_fit_columns_; }
    void set_auto_fit_columns(bool enabled);

protected:
    void keyPressEvent(QKeyEvent* event) override;

private:
    void copy_selection();

    TablePreviewModel* model_ = nullptr;
    bool auto_fit_columns_ = true;
    bool truncated_ = false;
    QString truncation_message_;
};

}  // namespace pwb::ui_pages_preview
