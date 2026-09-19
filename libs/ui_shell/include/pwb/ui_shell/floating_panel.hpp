#pragma once

// Port of paleo_workbench/ui/floating_panel.py (UI-01).
// Top-level window hosting a panel widget while floated. Created lazily by
// FloatController on first float so offscreen CI never instantiates a real
// window by default.

#include <QLabel>
#include <QToolButton>
#include <QWidget>

class QVBoxLayout;

namespace pwb::ui_shell {

class FloatingPanel : public QWidget {
    Q_OBJECT
public:
    FloatingPanel(std::string key, const QString& title,
                  QWidget* parent = nullptr);

    const std::string& key() const { return key_; }

    // Reparent `widget` into the central slot. No replace semantics: the
    // slot hosts exactly one widget per float; a second call stacks another
    // widget (callers dock-back or take_content() first — Python parity).
    void set_content(QWidget* widget);
    // Detach the hosted widget (reparented to top-level) and return it.
    QWidget* take_content();
    void set_panel_title(const QString& title);

signals:
    void dock_back_requested(const QString& key);
    // Emitted from showEvent/hideEvent — never for an empty window (an
    // emptied panel's lifecycle is controller cleanup, not panel state).
    void visibility_changed(const QString& key, bool visible);

protected:
    void showEvent(QShowEvent* event) override;
    void hideEvent(QHideEvent* event) override;

private:
    void emit_visibility(bool visible);

    std::string key_;
    QLabel* title_label_ = nullptr;
    QWidget* content_host_ = nullptr;
    QVBoxLayout* content_layout_ = nullptr;
};

}  // namespace pwb::ui_shell
