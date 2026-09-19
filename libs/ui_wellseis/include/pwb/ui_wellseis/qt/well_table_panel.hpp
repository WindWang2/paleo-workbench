#pragma once

// UI-09 — WellTablePanel Qt shell (well_table_panel.py).
// Model/view table over the 11-column schema (kWellTableColumns) with
// QC-token foregrounds and stable well_id selection across refreshes.

#include <optional>
#include <string>

#include <QString>
#include <QWidget>

#include <pwb/ui_wellseis/slices.hpp>

class QLabel;
class QTableView;

namespace pwb::ui_wellseis::qt {

class StringTableModel;

class WellTablePanel : public QWidget {
    Q_OBJECT
public:
    explicit WellTablePanel(QWidget* parent = nullptr);

    // update_from_well_table parity — rebuilds rows, keeps selection by
    // well_id, refreshes title + "N 行 · qc:n" summary.
    void update_from_well_table(const WellTableSlice& table);
    void clear();

    [[nodiscard]] std::optional<std::string> selected_well_id() const;
    void select_well(const std::string& well_id);
    [[nodiscard]] QString title_text() const;
    [[nodiscard]] QString summary_text() const;
    [[nodiscard]] StringTableModel* model() const;

signals:
    void well_activated(const QString& well_id);

private:
    QLabel* title_label_ = nullptr;
    QLabel* summary_label_ = nullptr;
    QTableView* table_ = nullptr;
    StringTableModel* model_ = nullptr;
    WellTableSlice well_table_;
};

}  // namespace pwb::ui_wellseis::qt
