#include "pwb/ui_widgets/buttons.hpp"

#include "pwb/ui_widgets/icon_factory.hpp"
#include "pwb/ui_widgets/ui_context.hpp"

#include <QHBoxLayout>
#include <QMenu>

namespace pwb::ui_widgets {

QString button_variant_object_name(const QString& variant) {
    static const QHash<QString, QString> names = {
        {"primary", "PrimaryButton"},
        {"secondary", "SecondaryButton"},
        {"tertiary", "WorkstationTertiaryButton"},
        {"danger", "PwbDangerButton"},
    };
    return names.value(variant, QStringLiteral("SecondaryButton"));
}

namespace {

bool is_variant(const QString& variant) {
    return variant == "primary" || variant == "secondary" ||
           variant == "tertiary" || variant == "danger";
}

}  // namespace

PwbButton::PwbButton(const QString& text, const QString& variant,
                     const QString& icon_name, QWidget* parent)
    : QPushButton(text, parent) {
    if (!icon_name.isEmpty()) setIcon(workstation_icon(icon_name));
    set_variant(variant);
}

void PwbButton::set_variant(const QString& variant) {
    variant_ = is_variant(variant) ? variant : QStringLiteral("secondary");
    setObjectName(button_variant_object_name(variant_));
    repolish(this);
}

PwbToolButton::PwbToolButton(const QString& icon_name, const QString& text,
                             bool checkable, bool chrome,
                             const QString& icon_color, QWidget* parent)
    : QToolButton(parent) {
    setCheckable(checkable);
    if (chrome) setObjectName(QStringLiteral("WorkstationContextButton"));
    if (!icon_name.isEmpty()) setIcon(workstation_icon(icon_name, icon_color));
    if (!text.isEmpty()) {
        setText(text);
        setToolButtonStyle(icon_name.isEmpty() ? Qt::ToolButtonTextOnly
                                              : Qt::ToolButtonTextBesideIcon);
    } else if (!icon_name.isEmpty()) {
        setToolButtonStyle(Qt::ToolButtonIconOnly);
    }
}

PwbSplitButton::PwbSplitButton(const QString& text, const QString& icon_name,
                               QMenu* menu, QWidget* parent)
    : QFrame(parent) {
    setObjectName(QStringLiteral("PwbSplitButton"));
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    main_ = new PwbButton(text, QStringLiteral("secondary"), icon_name, this);
    connect(main_, &QPushButton::clicked, this, &PwbSplitButton::clicked);
    arrow_ = new QToolButton(this);
    arrow_->setObjectName(QStringLiteral("PwbSplitArrow"));
    arrow_->setPopupMode(QToolButton::InstantPopup);
    arrow_->setIcon(workstation_icon(QStringLiteral("chevron-down.svg")));
    arrow_->setAutoRaise(true);
    layout->addWidget(main_);
    layout->addWidget(arrow_);
    if (menu != nullptr) set_menu(menu);
}

void PwbSplitButton::set_menu(QMenu* menu) { arrow_->setMenu(menu); }

QMenu* PwbSplitButton::menu() const { return arrow_->menu(); }

void PwbSplitButton::set_enabled_all(bool enabled) {
    main_->setEnabled(enabled);
    arrow_->setEnabled(enabled);
}

}  // namespace pwb::ui_widgets
