#pragma once

// UI-02 — PwbEmptyState / PwbErrorState / PwbLoadingState / PwbProgress,
// ported from paleo_workbench/ui/components/states.py (V5-U2). All
// surfaces consume the PwbStateSurface / PwbStateTitle / PwbStateHint /
// PwbProgress global-QSS vocabulary.

#include <QFrame>
#include <QLabel>
#include <QProgressBar>
#include <QPushButton>
#include <QVBoxLayout>

#include <functional>

namespace pwb::ui_widgets {

class PwbEmptyState : public QFrame {
    Q_OBJECT
public:
    explicit PwbEmptyState(const QString& title, const QString& hint = QString(),
                           const QString& icon_name = QStringLiteral("inbox.svg"),
                           QPushButton* action = nullptr,
                           QWidget* parent = nullptr);

    void set_state(const QString& title, const QString& hint = QString());
    void set_action(QPushButton* action);

protected:
    QPushButton* action_ = nullptr;  // set_action() bookkeeping (subclass sets)

private:
    void refresh_icon();

    QLabel* icon_ = nullptr;
    QLabel* title_ = nullptr;
    QLabel* hint_ = nullptr;
    QString icon_name_;
};

// Error state: alert icon + optional "重试" action (retry callback).
class PwbErrorState : public PwbEmptyState {
    Q_OBJECT
public:
    explicit PwbErrorState(const QString& title = QStringLiteral("加载失败"),
                           const QString& hint = QString(),
                           std::function<void()> retry_callback = {},
                           QWidget* parent = nullptr);

    void set_retry_callback(std::function<void()> callback);

private:
    QPushButton* retry_button_ = nullptr;
};

// Loading state: indeterminate busy bar + caption.
class PwbLoadingState : public QFrame {
    Q_OBJECT
public:
    explicit PwbLoadingState(const QString& text = QStringLiteral("正在加载…"),
                             QWidget* parent = nullptr);

    void set_text(const QString& text);

private:
    QProgressBar* bar_ = nullptr;
    QLabel* text_ = nullptr;
};

// Slim state-colored progress bar (same vocabulary as the task center).
// state ∈ {normal, running, queued, done, failed}; running = process amber.
class PwbProgress : public QProgressBar {
    Q_OBJECT
public:
    static constexpr const char* kStates[] = {"normal", "running", "queued",
                                              "done", "failed"};

    explicit PwbProgress(const QString& state = QStringLiteral("normal"),
                         QWidget* parent = nullptr);

    void set_state(const QString& state);
    QString state() const { return state_; }

private:
    QString state_;
};

}  // namespace pwb::ui_widgets
