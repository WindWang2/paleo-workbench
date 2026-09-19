#include <pwb/ui_pages_preview/qt/table_preview_widget.hpp>

#include <QApplication>
#include <QClipboard>
#include <QHeaderView>
#include <QItemSelection>
#include <QItemSelectionModel>
#include <QKeyEvent>
#include <QKeySequence>
#include <algorithm>
#include <map>

#include <pwb/ui_pages_preview/preview_settings.hpp>
#include <pwb/ui_pages_preview/preview_table.hpp>

namespace pwb::ui_pages_preview {

TablePreviewWidget::TablePreviewWidget(QWidget* parent)
    : QTableView(parent),
      model_(new TablePreviewModel(this)) {
    setModel(model_);
    setEditTriggers(QTableView::NoEditTriggers);
    setAlternatingRowColors(true);
    setShowGrid(true);
    setSelectionBehavior(QTableView::SelectItems);
    setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    horizontalHeader()->setStretchLastSection(true);
    verticalHeader()->setDefaultSectionSize(28);
}

void TablePreviewWidget::apply_settings(const PreviewSettings& settings) {
    QFont f = font();
    f.setPointSize(settings.font_size);
    setFont(f);
    set_auto_fit_columns(settings.auto_fit_columns);
}

void TablePreviewWidget::set_auto_fit_columns(bool enabled) {
    auto_fit_columns_ = enabled;
    horizontalHeader()->setSectionResizeMode(
        enabled ? QHeaderView::ResizeToContents : QHeaderView::Interactive);
}

int TablePreviewWidget::rowHeight(int row) const {
    return verticalHeader()->sectionSize(row);
}

int TablePreviewWidget::columnWidth(int column) const {
    return horizontalHeader()->sectionSize(column);
}

QString TablePreviewWidget::item_text(int row, int column) const {
    const QModelIndex idx = model_->index(row, column);
    return idx.isValid() ? idx.data(Qt::DisplayRole).toString() : QString();
}

QString TablePreviewWidget::header_text(int column) const {
    const auto& headers = model_->headers();
    if (column < 0 || column >= static_cast<int>(headers.size())) return {};
    return QString::fromStdString(headers[column]);
}

void TablePreviewWidget::load_table(
    const std::vector<std::string>& headers,
    const std::vector<std::vector<std::string>>& rows) {
    truncated_ = false;
    truncation_message_.clear();

    const auto trunc = table_truncation(rows.size(), headers.size());
    truncated_ = trunc.truncated;
    truncation_message_ = QString::fromStdString(trunc.message);
    setToolTip(truncation_message_);
    setStatusTip(truncation_message_);

    auto visible = rows;
    if (trunc.truncated) visible.resize(trunc.keep_rows);
    model_->set_table(headers, std::move(visible));

    if (!auto_fit_columns_) return;
    // Bounded SAMPLE of leading rows for the width fit (#1039 parity).
    auto* hdr = horizontalHeader();
    const int n_cols = model_->columnCount();
    hdr->setSectionResizeMode(QHeaderView::Interactive);
    hdr->setStretchLastSection(false);
    const int sample = std::min(model_->rowCount(), AUTO_FIT_SAMPLE_ROWS);
    const QFontMetrics metrics = fontMetrics();
    for (int col = 0; col < n_cols; ++col) {
        int width = metrics.horizontalAdvance(header_text(col)) + 24;
        for (int r = 0; r < sample; ++r) {
            const auto cells = model_->row_text(r);
            if (col < static_cast<int>(cells.size())) {
                width = std::max(
                    width,
                    metrics.horizontalAdvance(QString::fromStdString(cells[col])) + 24);
            }
        }
        hdr->resizeSection(col, std::max(width + 16, 75));
    }
    hdr->setStretchLastSection(true);
}

QString TablePreviewWidget::copy_all() const {
    std::vector<std::vector<std::string>> rows;
    rows.reserve(model_->rowCount());
    for (int r = 0; r < model_->rowCount(); ++r) {
        rows.push_back(model_->row_text(r));
    }
    return QString::fromStdString(table_to_tsv(model_->headers(), rows));
}

void TablePreviewWidget::copy_selection() {
    const QModelIndexList indexes = selectedIndexes();
    if (indexes.isEmpty()) return;
    std::map<int, std::map<int, QString>> by_row;
    for (const QModelIndex& idx : indexes) {
        by_row[idx.row()][idx.column()] = idx.data().toString();
    }
    QStringList lines;
    for (const auto& [row, cells] : by_row) {
        QStringList line;
        for (const auto& [col, text] : cells) line << text;
        lines << line.join('\t');
    }
    if (auto* clip = QApplication::clipboard()) {
        clip->setText(lines.join('\n'));
    }
}

void TablePreviewWidget::keyPressEvent(QKeyEvent* event) {
    if (event->matches(QKeySequence::Copy)) {
        copy_selection();
        event->accept();
        return;
    }
    QTableView::keyPressEvent(event);
}

}  // namespace pwb::ui_pages_preview
