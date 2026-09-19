#include "pwb/ui_widgets/dialog.hpp"

#include "pwb/ui_widgets/ui_context.hpp"

#include <QPushButton>
#include <QSpacerItem>

namespace pwb::ui_widgets {

PwbDialog::PwbDialog(const QString& title, QWidget* parent,
                     QDialogButtonBox::StandardButtons buttons,
                     const QString& ok_text, const QString& cancel_text,
                     bool danger)
    : QDialog(parent) {
    setWindowTitle(title);
    setObjectName(QStringLiteral("PwbDialog"));
    outer_ = new QVBoxLayout(this);
    outer_->setContentsMargins(kSpace2Xl, kSpaceXl, kSpace2Xl, kSpaceL);
    outer_->setSpacing(kSpaceL);
    // 构造时给出任一按钮参数即自动装配按钮盒（内容加到其上方）。
    if (buttons != QDialogButtonBox::NoButton || !ok_text.isNull() ||
        !cancel_text.isNull() || danger) {
        const auto effective =
            buttons == QDialogButtonBox::NoButton
                ? (QDialogButtonBox::Ok | QDialogButtonBox::Cancel)
                : buttons;
        add_buttons(effective, ok_text, cancel_text, danger);
    }
}

QWidget* PwbDialog::add_content(QWidget* widget, int stretch) {
    outer_->addWidget(widget, stretch);
    return widget;
}

void PwbDialog::add_content_spacing(int height) {
    outer_->addSpacerItem(new QSpacerItem(height, height));
}

QDialogButtonBox* PwbDialog::add_buttons(
    QDialogButtonBox::StandardButtons buttons, const QString& ok_text,
    const QString& cancel_text, bool danger) {
    auto* box = new QDialogButtonBox(buttons, this);
    if (!ok_text.isNull()) {
        QPushButton* ok = box->button(QDialogButtonBox::Ok);
        if (ok != nullptr) {
            ok->setText(ok_text);
            ok->setObjectName(danger ? QStringLiteral("PwbDangerButton")
                                     : QStringLiteral("PrimaryButton"));
        }
    }
    if (!cancel_text.isNull()) {
        QPushButton* cancel = box->button(QDialogButtonBox::Cancel);
        if (cancel != nullptr) cancel->setText(cancel_text);
    }
    connect(box, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(box, &QDialogButtonBox::rejected, this, &QDialog::reject);
    outer_->addWidget(box);
    button_box_ = box;
    return box;
}

QPushButton* PwbDialog::button(QDialogButtonBox::StandardButton role) const {
    return button_box_ != nullptr ? button_box_->button(role) : nullptr;
}

}  // namespace pwb::ui_widgets
