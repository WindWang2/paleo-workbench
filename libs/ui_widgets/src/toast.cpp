#include "pwb/ui_widgets/toast.hpp"

#include "pwb/ui_widgets/badges.hpp"

#include <QApplication>
#include <QHBoxLayout>
#include <QLabel>
#include <QMainWindow>
#include <QMouseEvent>
#include <QTimer>

namespace pwb::ui_widgets {

namespace {

constexpr int kTopInset = 52;    // app bar 之下
constexpr int kSideMargin = 24;
constexpr int kGap = 8;
constexpr int kWidth = 460;

//: 每个宿主窗口当前挂着的 toasts（QPointer keys auto-null on host death;
//: dead entries are reaped on the next stack mutation).
QHash<QWidget*, QVector<QPointer<PwbToast>>>& active_stacks() {
    static QHash<QWidget*, QVector<QPointer<PwbToast>>> stacks;
    return stacks;
}

void reap_dead(QWidget* host) {
    auto it = active_stacks().find(host);
    if (it == active_stacks().end()) return;
    auto& stack = it.value();
    stack.erase(std::remove_if(stack.begin(), stack.end(),
                               [](const QPointer<PwbToast>& t) {
                                   return t.isNull();
                               }),
                stack.end());
    if (stack.isEmpty()) active_stacks().erase(it);
}

}  // namespace

PwbToast::PwbToast(QWidget* parent, const QString& text, const QString& tone,
                   const QString& title, int timeout_ms)
    : QFrame(parent) {
    setObjectName(QStringLiteral("PwbToast"));
    setAttribute(Qt::WA_TransparentForMouseEvents, false);
    setAttribute(Qt::WA_ShowWithoutActivating);

    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(12, 8, 8, 8);
    layout->setSpacing(8);
    auto* status = new PwbInlineStatus(text, tone, QString(), this);
    if (!title.isEmpty()) {
        auto* title_label = new QLabel(title, this);
        title_label->setObjectName(QStringLiteral("PwbToastTitle"));
        layout->addWidget(title_label, 0);
    }
    layout->addWidget(status, 1);
    if (timeout_ms > 0) {
        // 子 QTimer：toast 随宿主销毁时定时器一并销毁。
        auto* timer = new QTimer(this);
        timer->setSingleShot(true);
        connect(timer, &QTimer::timeout, this, &PwbToast::dismiss);
        timer->start(timeout_ms);
    }
    setMaximumWidth(kWidth);
}

void PwbToast::dismiss() {
    QWidget* host = parentWidget();
    if (host != nullptr) {
        auto it = active_stacks().find(host);
        if (it != active_stacks().end()) {
            it.value().erase(std::remove(it.value().begin(), it.value().end(),
                                         QPointer<PwbToast>(this)),
                             it.value().end());
        }
    }
    hide();
    deleteLater();
    if (host != nullptr) relayout(host);
}

void PwbToast::mousePressEvent(QMouseEvent* event) {
    Q_UNUSED(event);
    dismiss();
}

PwbToast* PwbToast::show_on(QWidget* parent, const QString& text,
                            const QString& tone, const QString& title,
                            int timeout_ms) {
    if (parent == nullptr) return nullptr;
    QWidget* host = qobject_cast<QMainWindow*>(parent) != nullptr
                        ? parent
                        : parent->window();
    reap_dead(host);
    auto* toast = new PwbToast(host, text, tone, title, timeout_ms);
    active_stacks()[host].append(toast);
    toast->setParent(host);
    toast->show();
    toast->raise();
    relayout(host);
    return toast;
}

int PwbToast::stack_count(QWidget* host) {
    reap_dead(host);
    const auto it = active_stacks().constFind(host);
    return it == active_stacks().constEnd() ? 0 : int(it.value().size());
}

void PwbToast::relayout(QWidget* host) {
    const auto it = active_stacks().constFind(host);
    if (it == active_stacks().constEnd() || it.value().isEmpty()) return;
    int y = kTopInset;
    const auto& stack = it.value();
    for (const QPointer<PwbToast>& toast : stack) {
        if (toast.isNull()) continue;
        const int width =
            qMin(kWidth, qMax(240, host->width() - 2 * kSideMargin));
        toast->setFixedWidth(width);
        const int x = qMax(kSideMargin, (host->width() - width) / 2);
        toast->move(x, y);
        toast->adjustSize();
        y += toast->height() + kGap;
    }
}

void notify(const QString& text, const QString& tone, const QString& title,
            int timeout_ms) {
    QApplication* app = qobject_cast<QApplication*>(QApplication::instance());
    if (app == nullptr) return;
    const auto tops = app->topLevelWidgets();
    for (QWidget* w : tops) {
        if (qobject_cast<QMainWindow*>(w) != nullptr && w->isVisible()) {
            PwbToast::show_on(w, text, tone, title, timeout_ms);
            return;
        }
    }
}

}  // namespace pwb::ui_widgets
