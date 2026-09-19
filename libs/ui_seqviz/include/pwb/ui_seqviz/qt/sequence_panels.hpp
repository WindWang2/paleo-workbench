#pragma once

// UI-10 — Qt Widgets shells for the sequence panels:
//   * sequence_boundary_table.py   → SequenceBoundaryTable (QFrame + table)
//   * sequence_target_panel.py     → SequenceTargetPanel (QFrame)
//   * sequence_scheme_summary.py   → SequenceSchemeSummary (QFrame)
//
// All view data comes from the Qt-free sequence_state core; these shells
// only own widgets, signals, and the _suppress/dedupe flag behavior.

#include <QComboBox>
#include <QFrame>
#include <QLabel>

#include <pwb/ui_seqviz/sequence_state.hpp>

class QTableWidget;

namespace pwb::ui_seqviz::qt {

// sequence_boundary_table.py — "层序界面清单" title + empty-state label +
// the 3-column boundary table; double-click on column 0 emits
// boundary_activated(stripped name).
class SequenceBoundaryTable : public QFrame {
    Q_OBJECT
public:
    explicit SequenceBoundaryTable(QWidget* parent = nullptr);

    // update_state parity — rows from sequence_boundary_rows(); the empty
    // label hides iff boundaries exist.
    void update_state(const StratigraphySlice& stratigraphy);

    QTableWidget* table() const { return table_; }

signals:
    void boundary_activated(const QString& name);

private:
    QLabel* title_label_ = nullptr;
    QLabel* empty_label_ = nullptr;
    QTableWidget* table_ = nullptr;
};

// sequence_target_panel.py — "层序格架设置" card: editable target combo
// (NoInsert, 未设置 placeholder), version label, scheme combo
// (LST/TST/HST + SEQUENCE_SCHEMES) and scope label. target_changed fires
// ONLY on commit (Enter / dropdown pick) with last-committed dedupe;
// scheme_changed fires on currentTextChanged (suppressed during refresh).
class SequenceTargetPanel : public QFrame {
    Q_OBJECT
public:
    explicit SequenceTargetPanel(QWidget* parent = nullptr);

    void update_state(const StratigraphySlice& stratigraphy);

    // current_target / target_horizon_text / current_scheme parity.
    QString current_target() const;
    QString target_horizon_text() const;
    QString current_scheme() const;

    QComboBox* target_combo() const { return target_combo_; }
    QComboBox* scheme_combo() const { return scheme_combo_; }

signals:
    void target_changed(const QString& target);
    void scheme_changed(const QString& scheme);

private:
    void on_target_committed();

    QComboBox* target_combo_ = nullptr;
    QComboBox* scheme_combo_ = nullptr;
    QLabel* version_value_ = nullptr;
    QLabel* scope_value_ = nullptr;
    TargetCommitTracker tracker_;
    bool suppress_ = false;
};

// sequence_scheme_summary.py — "层序方案摘要" card with save button.
class SequenceSchemeSummary : public QFrame {
    Q_OBJECT
public:
    explicit SequenceSchemeSummary(QWidget* parent = nullptr);

    void update_state(const StratigraphySlice& stratigraphy);
    // set_bind_status — post-action status override.
    void set_bind_status(const QString& text);

signals:
    void save_requested();

private:
    QLabel* scheme_value_ = nullptr;
    QLabel* boundary_count_value_ = nullptr;
    QLabel* systems_tract_value_ = nullptr;
    QLabel* status_value_ = nullptr;
};

}  // namespace pwb::ui_seqviz::qt
