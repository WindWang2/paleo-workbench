#pragma once

// UI-10 — PanelFloatButton, the corner button floating one side panel via
// a FloatController (identical verbatim class in sequence_framework_page,
// visualization_page and stratigraphy_correlation_page — ported once).
//
// Docked side of the FloatingPanel ⇲ dock-back chrome: pinned to the
// panel's top-right corner through an event filter and hidden while the
// panel is afloat (the floating window carries its own dock-back button).

#include <QEvent>
#include <QToolButton>

#include <pwb/ui_shell/float_controller.hpp>

namespace pwb::ui_seqviz::qt {

class PanelFloatButton : public QToolButton {
    Q_OBJECT
public:
    PanelFloatButton(std::string key, QWidget* panel,
                     ui_shell::FloatController* controller)
        : QToolButton(panel), key_(std::move(key)), panel_(panel),
          controller_(controller) {
        setObjectName("PanelFloatButton");
        setText(QString::fromUtf8("⇱"));
        setToolTip(QStringLiteral("浮动面板 (Float panel)"));
        // Icon-glyph text carries no semantics for assistive tech (F4).
        setAccessibleName(QStringLiteral("浮动面板"));
        setFixedSize(18, 18);
        connect(this, &QToolButton::clicked, this,
                [this] { controller_->toggle(key_); });
        panel_->installEventFilter(this);
        connect(controller_, &ui_shell::FloatController::float_changed, this,
                [this](const QString& key, bool floating) {
                    if (key.toStdString() == key_) {
                        setVisible(!floating);
                    }
                });
        reposition();
    }

private:
    void reposition() {
        move(panel_->width() - width() - 4, 2);
    }

    bool eventFilter(QObject* obj, QEvent* event) override {
        if (obj == panel_ && event->type() == QEvent::Resize) {
            reposition();
        }
        return false;
    }

    std::string key_;
    QWidget* panel_;
    ui_shell::FloatController* controller_;
};

}  // namespace pwb::ui_seqviz::qt
