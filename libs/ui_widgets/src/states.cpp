#include "pwb/ui_widgets/states.hpp"

#include "pwb/ui_widgets/buttons.hpp"
#include "pwb/ui_widgets/icon_factory.hpp"
#include "pwb/ui_widgets/ui_context.hpp"

namespace pwb::ui_widgets {

PwbEmptyState::PwbEmptyState(const QString& title, const QString& hint,
                             const QString& icon_name, QPushButton* action,
                             QWidget* parent)
    : QFrame(parent), action_(action), icon_name_(icon_name) {
    setObjectName(QStringLiteral("PwbStateSurface"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(18, 16, 18, 16);
    layout->setSpacing(6);
    layout->setAlignment(Qt::AlignCenter);

    icon_ = new QLabel(this);
    icon_->setAlignment(Qt::AlignCenter);
    layout->addWidget(icon_);

    title_ = new QLabel(title, this);
    title_->setObjectName(QStringLiteral("PwbStateTitle"));
    title_->setAlignment(Qt::AlignCenter);
    title_->setWordWrap(true);
    layout->addWidget(title_);

    hint_ = new QLabel(hint, this);
    hint_->setObjectName(QStringLiteral("PwbStateHint"));
    hint_->setAlignment(Qt::AlignCenter);
    hint_->setWordWrap(true);
    hint_->setVisible(!hint.isEmpty());
    layout->addWidget(hint_);

    if (action_ != nullptr) {
        auto* wrap = new QWidget(this);
        auto* row = new QVBoxLayout(wrap);
        row->setContentsMargins(0, 6, 0, 0);
        action_->setParent(wrap);
        row->addWidget(action_);
        wrap->setStyleSheet(QStringLiteral("background: transparent;"));
        layout->addWidget(wrap);
    }
    refresh_icon();
}

void PwbEmptyState::refresh_icon() {
    const QPixmap pm = tinted_pixmap(icon_name_, QStringLiteral("TEXT_SECONDARY"),
                                     24, icon_->devicePixelRatioF());
    icon_->setPixmap(pm);
    icon_->setVisible(!pm.isNull());
}

void PwbEmptyState::set_state(const QString& title, const QString& hint) {
    title_->setText(title);
    hint_->setText(hint);
    hint_->setVisible(!hint.isEmpty());
}

void PwbEmptyState::set_action(QPushButton* action) {
    if (action_ != nullptr) action_->setParent(nullptr);
    action_ = action;
    if (action_ != nullptr) {
        action_->setParent(this);
        layout()->addWidget(action_);
    }
}

PwbErrorState::PwbErrorState(const QString& title, const QString& hint,
                             std::function<void()> retry_callback,
                             QWidget* parent)
    : PwbEmptyState(title, hint, QStringLiteral("alert-triangle.svg"),
                    nullptr, parent) {
    retry_button_ = new PwbButton(QStringLiteral("重试"), QStringLiteral("tertiary"),
                                QStringLiteral("rotate-cw.svg"), this);
    if (retry_callback) {
        connect(retry_button_, &QPushButton::clicked, this,
                [cb = std::move(retry_callback)]() { cb(); });
    }
    // Python parity: the ctor-path action lives in a transparent wrap with
    // a 6px top margin (set_action()'s post-ctor path differs on purpose).
    auto* wrap = new QWidget(this);
    auto* row = new QVBoxLayout(wrap);
    row->setContentsMargins(0, 6, 0, 0);
    retry_button_->setParent(wrap);
    row->addWidget(retry_button_);
    wrap->setStyleSheet(QStringLiteral("background: transparent;"));
    layout()->addWidget(wrap);
    action_ = retry_button_;
}

void PwbErrorState::set_retry_callback(std::function<void()> callback) {
    if (!callback) {
        retry_button_->setVisible(false);
        return;
    }
    connect(retry_button_, &QPushButton::clicked, this,
            [cb = std::move(callback)]() { cb(); });
    retry_button_->setVisible(true);
}

PwbLoadingState::PwbLoadingState(const QString& text, QWidget* parent)
    : QFrame(parent) {
    setObjectName(QStringLiteral("PwbStateSurface"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(18, 16, 18, 16);
    layout->setSpacing(8);
    layout->setAlignment(Qt::AlignCenter);
    bar_ = new QProgressBar(this);
    bar_->setObjectName(QStringLiteral("PwbProgress"));
    bar_->setRange(0, 0);  // indeterminate
    bar_->setTextVisible(false);
    text_ = new QLabel(text, this);
    text_->setObjectName(QStringLiteral("PwbStateHint"));
    text_->setAlignment(Qt::AlignCenter);
    text_->setWordWrap(true);
    layout->addWidget(bar_);
    layout->addWidget(text_);
}

void PwbLoadingState::set_text(const QString& text) { text_->setText(text); }

PwbProgress::PwbProgress(const QString& state, QWidget* parent)
    : QProgressBar(parent) {
    setObjectName(QStringLiteral("PwbProgress"));
    setTextVisible(false);
    set_state(state);
}

void PwbProgress::set_state(const QString& state) {
    QString effective = state;
    bool known = false;
    for (const char* s : kStates) {
        if (state == QLatin1String(s)) {
            known = true;
            break;
        }
    }
    if (!known) effective = QStringLiteral("normal");
    state_ = effective;
    setProperty("progressState", effective);
    repolish(this);
}

}  // namespace pwb::ui_widgets
