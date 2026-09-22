#include "pwb/ui_workstation/verify_records_panel.hpp"

#include <QHeaderView>
#include <QTableWidget>
#include <QVBoxLayout>

namespace pwb::ui_workstation {

namespace {
const char* const kColumns[] = {"对象", "检查项", "严重度",
                                "结论", "复核人", "时间"};
}

VerifyRecordsPanel::VerifyRecordsPanel(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("VerifyRecordsPanel"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(4, 4, 4, 4);
    layout->setSpacing(0);
    table_ = new QTableWidget(this);
    table_->setColumnCount(6);
    QStringList headers;
    for (const char* column : kColumns) {
        headers << QString::fromUtf8(column);
    }
    table_->setHorizontalHeaderLabels(headers);
    table_->horizontalHeader()->setStretchLastSection(true);
    table_->verticalHeader()->setVisible(false);
    table_->setEditTriggers(QAbstractItemView::NoEditTriggers);
    table_->setSelectionBehavior(QAbstractItemView::SelectRows);
    table_->setShowGrid(false);
    table_->setAlternatingRowColors(true);
    connect(table_, &QTableWidget::cellDoubleClicked, this,
            [this](int row, int) { emit record_activated(row); });
    layout->addWidget(table_);
}

void VerifyRecordsPanel::set_records_provider(RecordsProvider provider) {
    provider_ = std::move(provider);
    refresh();
}

void VerifyRecordsPanel::refresh() {
    const auto rows = provider_ ? provider_() : std::vector<QStringList>{};
    table_->setRowCount(static_cast<int>(rows.size()));
    for (int i = 0; i < static_cast<int>(rows.size()); ++i) {
        const QStringList& row = rows[static_cast<size_t>(i)];
        for (int c = 0; c < 6; ++c) {
            auto* item = new QTableWidgetItem(
                c < row.size() ? row[c] : QString());
            table_->setItem(i, c, item);
        }
    }
    table_->resizeColumnsToContents();
}

int VerifyRecordsPanel::record_count() const { return table_->rowCount(); }

}  // namespace pwb::ui_workstation
