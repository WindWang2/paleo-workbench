#pragma once

// UI-02 — PwbSearchBox + make_form_row, ported from
// paleo_workbench/ui/components/inputs.py (V5-U2).

#include <QAction>
#include <QLabel>
#include <QLineEdit>
#include <QPointer>
#include <QWidget>

namespace pwb::ui_widgets {

// Search box with a clear action (reuses the global SearchBox QSS
// vocabulary): the clear action hides on empty text and uses the repo
// rb-clear icon — replaces the stacked "✕" QLabel idiom.
class PwbSearchBox : public QLineEdit {
    Q_OBJECT
public:
    explicit PwbSearchBox(const QString& placeholder = QString(),
                          QWidget* parent = nullptr);

private:
    void refresh_clear_action();
    QPointer<QAction> clear_action_;
};

// Standard form row: WorkFieldLabel + editor (+ optional unit suffix).
QWidget* make_form_row(const QString& label, QWidget* editor,
                       QLabel* label_w = nullptr,
                       const QString& unit = QString(),
                       bool stretch_editor = true);

}  // namespace pwb::ui_widgets
