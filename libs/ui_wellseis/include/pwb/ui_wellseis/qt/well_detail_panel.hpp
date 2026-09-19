#pragma once

// UI-09 — WellDetailPanel Qt shell (well_detail_panel.py).
// Identity header + roles table + three card lists (过期成果 / 未提交编辑 /
// 缺失/异常). The panel owns only the last handed view — no duplicated
// domain state (well_detail.hpp owns the text semantics).

#include <QString>
#include <QWidget>

#include <pwb/ui_wellseis/slices.hpp>

class QLabel;
class QTableView;
class QVBoxLayout;

namespace pwb::ui_wellseis::qt {

class StringTableModel;

class WellDetailPanel : public QWidget {
    Q_OBJECT
public:
    explicit WellDetailPanel(QWidget* parent = nullptr);

    // set_view parity — pass has_view=false to reset.
    void set_view(const WellDataViewSlice& view, bool has_view);
    // update_stale parity — late-arriving staleness results.
    void update_stale(const std::vector<StaleItemSlice>& items);
    void clear();

signals:
    void close_requested();

private:
    void fill_card(QVBoxLayout* body, const std::vector<std::string>& lines);

    QLabel* title_ = nullptr;
    QLabel* subtitle_ = nullptr;
    QTableView* roles_table_ = nullptr;
    StringTableModel* roles_model_ = nullptr;
    QVBoxLayout* stale_body_ = nullptr;
    QVBoxLayout* edits_body_ = nullptr;
    QVBoxLayout* missing_body_ = nullptr;
    bool has_view_ = false;
    WellDataViewSlice view_;
};

}  // namespace pwb::ui_wellseis::qt
