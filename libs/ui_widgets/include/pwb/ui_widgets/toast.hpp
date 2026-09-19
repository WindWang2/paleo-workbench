#pragma once

// UI-02 — PwbToast + notify, ported from
// paleo_workbench/ui/components/toast.py (V5-U2/U6): non-blocking
// notification bar stacked top-center on the parent window, auto-dismiss,
// click-to-dismiss, deterministic offscreen (no animation dependency).

#include <QFrame>
#include <QHash>
#include <QPointer>
#include <QVector>

namespace pwb::ui_widgets {

class PwbToast : public QFrame {
    Q_OBJECT
public:
    PwbToast(QWidget* parent, const QString& text,
             const QString& tone = QStringLiteral("neutral"),
             const QString& title = QString(), int timeout_ms = 4000);

    void dismiss();

    // Stack a notification on `parent`'s window (top-center) and return it.
    static PwbToast* show_on(QWidget* parent, const QString& text,
                             const QString& tone = QStringLiteral("neutral"),
                             const QString& title = QString(),
                             int timeout_ms = 4000);

    // Live stacks per host window (test/diagnostic access).
    static int stack_count(QWidget* host);

protected:
    void mousePressEvent(QMouseEvent* event) override;

private:
    static void relayout(QWidget* host);
};

// Process-level convenience: attach to the first visible QMainWindow
// top-level (Python notify() parity).
void notify(const QString& text, const QString& tone = QStringLiteral("neutral"),
            const QString& title = QString(), int timeout_ms = 4000);

}  // namespace pwb::ui_widgets
