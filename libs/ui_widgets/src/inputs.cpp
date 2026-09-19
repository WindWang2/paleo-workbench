#include "pwb/ui_widgets/inputs.hpp"

#include "pwb/ui_widgets/icon_factory.hpp"
#include "pwb/ui_widgets/ui_context.hpp"

#include <QHBoxLayout>

namespace pwb::ui_widgets {

PwbSearchBox::PwbSearchBox(const QString& placeholder, QWidget* parent)
    : QLineEdit(parent) {
    setObjectName(QStringLiteral("SearchBox"));
    setPlaceholderText(placeholder);
    setClearButtonEnabled(false);
    refresh_clear_action();
    connect(this, &QLineEdit::textChanged, this,
            [this](const QString&) { refresh_clear_action(); });
}

void PwbSearchBox::refresh_clear_action() {
    const bool has_text = !text().isEmpty();
    if (has_text && clear_action_.isNull()) {
        auto* action = new QAction(this);
        action->setIcon(workstation_icon(QStringLiteral("rb-clear.svg")));
        action->setToolTip(QStringLiteral("清除"));
        connect(action, &QAction::triggered, this, &QLineEdit::clear);
        clear_action_ = action;
        addAction(action, QLineEdit::TrailingPosition);
    } else if (!has_text && !clear_action_.isNull()) {
        removeAction(clear_action_.data());
        delete clear_action_.data();
        clear_action_ = nullptr;
    }
}

QWidget* make_form_row(const QString& label, QWidget* editor,
                       QLabel* label_w, const QString& unit,
                       bool stretch_editor) {
    auto* row = new QWidget();
    auto* form = new QHBoxLayout(row);
    form->setContentsMargins(0, 0, 0, 0);
    form->setSpacing(kSpaceM);
    QLabel* lab = label_w;
    if (lab == nullptr) {
        lab = new QLabel(label, row);
        lab->setObjectName(QStringLiteral("WorkFieldLabel"));
    }
    form->addWidget(lab, 0);
    form->addWidget(editor, stretch_editor ? 1 : 0);
    if (!unit.isEmpty()) {
        auto* unit_label = new QLabel(unit, row);
        unit_label->setObjectName(QStringLiteral("WorkFieldLabel"));
        form->addWidget(unit_label, 0);
    }
    return row;
}

}  // namespace pwb::ui_widgets
