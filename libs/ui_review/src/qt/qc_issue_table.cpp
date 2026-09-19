#include "pwb/ui_review/qt/qc_issue_table.hpp"

#include "pwb/ui_review/qc_issue_rows.hpp"

#include <QColor>
#include <QHeaderView>
#include <QTableWidgetItem>
#include <QVBoxLayout>

namespace pwb::ui_review::qt {

QcIssueTable::QcIssueTable(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("QCIssueTable"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    table_ = new QTableWidget(this);
    table_->setColumnCount(4);
    // COLUMN_HEADERS verbatim.
    table_->setHorizontalHeaderLabels(
        {QStringLiteral("检查项目"), QStringLiteral("检查说明"),
         QStringLiteral("结果说明"), QStringLiteral("定位")});
    table_->setAlternatingRowColors(true);
    table_->verticalHeader()->setVisible(false);
    table_->setEditTriggers(QTableWidget::NoEditTriggers);
    table_->setSelectionBehavior(QTableWidget::SelectRows);
    // COLUMN_WIDTHS = [160, 0(stretch), 160, 100].
    auto* header = table_->horizontalHeader();
    header->resizeSection(0, 160);
    header->setSectionResizeMode(1, QHeaderView::Stretch);
    header->resizeSection(2, 160);
    header->resizeSection(3, 100);
    layout->addWidget(table_);
}

void QcIssueTable::update_state(const std::vector<domain::Json>& reports) {
    table_->setRowCount(0);
    spatial_by_rule_.clear();
    if (reports.empty()) {
        return;
    }
    const domain::Json& report = reports.front();
    const domain::Json empty_issues = domain::Json::array();
    const domain::Json* issues = &empty_issues;
    const auto iit = report.find("issues");
    if (iit != report.end() && iit->is_array()) {
        issues = &*iit;
    }
    const domain::Json* rules = nullptr;
    const auto rit = report.find("rules");
    if (rit != report.end() && rit->is_array()) {
        rules = &*rit;
    }
    if (rules == nullptr) {
        return;
    }
    spatial_by_rule_ = spatial_issues_by_rule(*issues);
    const auto rows = qc_issue_rows(*rules, *issues);
    table_->setRowCount(int(rows.size()));
    for (int row = 0; row < int(rows.size()); ++row) {
        const auto& spec = rows[std::size_t(row)];
        const QString texts[4] = {
            QString::fromStdString(spec.rule),
            QString::fromStdString(spec.description),
            QString::fromStdString(spec.result_text),
            QString::fromStdString(spec.location),
        };
        for (int col = 0; col < 4; ++col) {
            auto* item = new QTableWidgetItem(texts[col]);
            if (col == 2) {
                item->setForeground(
                    QColor(QString::fromStdString(spec.result_color)));
            }
            item->setFlags(item->flags() & ~Qt::ItemIsEditable);
            table_->setItem(row, col, item);
        }
        table_->setRowHeight(row, 28);
    }
}

std::vector<domain::Json>
QcIssueTable::spatial_issues_for_rule(const std::string& rule) const {
    const auto it = spatial_by_rule_.find(rule);
    return it != spatial_by_rule_.end() ? it->second
                                        : std::vector<domain::Json>{};
}

}  // namespace pwb::ui_review::qt
