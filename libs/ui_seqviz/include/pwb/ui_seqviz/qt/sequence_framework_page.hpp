#pragma once

// UI-10 — Qt shell for sequence_framework_page.py: target panel +
// boundary table + scheme summary in a horizontal splitter, plus the
// per-panel float wiring (FloatController + LayoutPersistence +
// PanelFloatButton) and the apply/refresh/status emit contract.

#include <QSplitter>
#include <QString>
#include <QWidget>

#include <memory>
#include <pwb/ui_seqviz/sequence_state.hpp>

namespace pwb::ui_seqviz::qt {

class SequenceBoundaryTable;
class SequenceSchemeSummary;
class SequenceTargetPanel;
}  // namespace pwb::ui_seqviz::qt

namespace pwb::ui_shell {
class FloatController;
class LayoutPersistence;
}  // namespace pwb::ui_shell

namespace pwb::ui_seqviz::qt {

class SequenceFrameworkPage : public QWidget {
    Q_OBJECT
public:
    explicit SequenceFrameworkPage(QWidget* parent = nullptr);
    ~SequenceFrameworkPage() override;

    // FloatController wiring — replaces the panels' parent chains when
    // called a second time (Python parity).
    void set_float_controller(ui_shell::LayoutPersistence* persistence);

    // Host-owned project slice (non-owning). Required before any of the
    // mutating actions (target/scheme/boundary/save) are invoked.
    void set_project(StratigraphyProjectSlice* project);

    // Repaint entry — refreshes all three panels.
    void update_state(const StratigraphySlice& stratigraphy);
    void refresh() { update_state(stratigraphy()); }

    // save_scheme — validates the scheme combo, applies and emits.
    // Returns false when the scheme is empty (warn + no-op).
    bool save_scheme();

    StratigraphyProjectSlice* project() const { return project_; }
    const StratigraphySlice& stratigraphy() const;
    SequenceTargetPanel* target_panel() const { return target_panel_; }
    SequenceBoundaryTable* boundary_table() const { return boundary_table_; }
    SequenceSchemeSummary* scheme_summary() const { return scheme_summary_; }

signals:
    void stratigraphy_updated();
    // Python ``_warn(title, message)`` seam — the host decides whether to
    // show a QMessageBox; the shell never blocks on a dialog.
    void warning_requested(const QString& title, const QString& message);

private:
    void on_target_changed(const QString& target);
    void on_scheme_changed(const QString& scheme);
    void on_boundary_activated(const QString& name);

    SequenceTargetPanel* target_panel_ = nullptr;
    SequenceBoundaryTable* boundary_table_ = nullptr;
    SequenceSchemeSummary* scheme_summary_ = nullptr;
    QSplitter* splitter_ = nullptr;
    std::unique_ptr<ui_shell::FloatController> float_controller_;
    StratigraphyProjectSlice* project_ = nullptr;  // not owned
};

}  // namespace pwb::ui_seqviz::qt
