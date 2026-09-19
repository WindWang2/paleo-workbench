#pragma once

// UI-11 — qc_issue_table.py Qt shell. Python deliberately keeps the
// fixed 4-column QTableWidget shape (row height per row; model/view
// brings no gain at this size), so the C++ table is a QTableWidget too.

#include <QTableWidget>
#include <QWidget>

#include <map>
#include <string>
#include <vector>

#include "pwb/domain/json.hpp"

namespace pwb::ui_review::qt {

class QcIssueTable : public QWidget {
    Q_OBJECT
public:
    explicit QcIssueTable(QWidget* parent = nullptr);

    // update_state(reports) — QualityReport dicts ({rules:[], issues:[]});
    // only reports[0] is rendered (Python parity).
    void update_state(const std::vector<domain::Json>& reports);

    // spatial_issues_for_rule(rule) — the locatable issues of one rule.
    std::vector<domain::Json>
    spatial_issues_for_rule(const std::string& rule) const;

    QTableWidget* table() const { return table_; }

private:
    QTableWidget* table_ = nullptr;
    std::map<std::string, std::vector<domain::Json>> spatial_by_rule_;
};

}  // namespace pwb::ui_review::qt
