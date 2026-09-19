#pragma once

// UI-02 — PwbDialog, ported from paleo_workbench/ui/components/dialog.py
// (V5-U4): unified title/content/button-box structure; the look lives in
// the global QSS. `danger` gives the confirm button the PwbDangerButton
// vocabulary (destructive actions).

#include <QDialog>
#include <QDialogButtonBox>
#include <QVBoxLayout>

namespace pwb::ui_widgets {

class PwbDialog : public QDialog {
    Q_OBJECT
public:
    explicit PwbDialog(
        const QString& title, QWidget* parent = nullptr,
        QDialogButtonBox::StandardButtons buttons =
            QDialogButtonBox::NoButton,
        const QString& ok_text = QString(),
        const QString& cancel_text = QString(), bool danger = false);

    // Content area (above the button box).
    QVBoxLayout* content_layout() const { return outer_; }

    QWidget* add_content(QWidget* widget, int stretch = 0);
    void add_content_spacing(int height);

    QDialogButtonBox* add_buttons(
        QDialogButtonBox::StandardButtons buttons =
            QDialogButtonBox::Ok | QDialogButtonBox::Cancel,
        const QString& ok_text = QString(),
        const QString& cancel_text = QString(), bool danger = false);

    QPushButton* button(QDialogButtonBox::StandardButton role) const;

    QDialogButtonBox* button_box_ = nullptr;

private:
    QVBoxLayout* outer_ = nullptr;
};

}  // namespace pwb::ui_widgets
