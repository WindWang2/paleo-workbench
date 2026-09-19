#pragma once

// Port of paleo_workbench/ui/panel_float_controller.py (UI-01).
// FloatController: float docked panels into top-level windows — and back.
// Owns the float state of page panels keyed by an opaque caller string
// (conventional shape "page:panel", e.g. "mapping:layer_tree").

#include <QObject>
#include <QPointer>
#include <QRect>
#include <QSize>

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

class QSplitter;
class QWidget;

namespace pwb::ui_shell {

class FloatingPanel;
class LayoutPersistence;

// Smallest sensible floating window when the docked widget never got a size.
inline const QSize kDefaultFloatSize{420, 320};
// Offset from the dock parent's top-left when no saved geometry exists.
inline constexpr int kDefaultFloatOffset = 48;

// Dock context captured at float time so dock-back can restore it.
// QPointer members null out when their C++ object is destroyed — the
// parity of Python's RuntimeError-on-deleted-wrap detection in
// _reinsert (dock-back keeps the record instead of orphaning).
struct FloatRecord {
    QPointer<QWidget> widget;
    QPointer<QWidget> dock_parent;
    // True when dock_parent was alive at record time — distinguishes
    // "recorded null" (legal: setParent(nullptr) = top-level) from "alive
    // then destroyed" (dock-back must keep the record, Python parity).
    bool dock_parent_was_set = false;
    QRect dock_geometry;
    QPointer<QSplitter> splitter;
    std::optional<int> splitter_index;
    std::optional<std::vector<int>> restore_sizes;
};

// V5-U6 multi-monitor robustness: clamp a window geometry into the visible
// desktop union. Fully off-screen → snap back to the primary screen (24px
// margin, size bounded to it); partially off-screen → pull back so at least
// a 60px grabbable strip stays inside the desktop bounds.
QRect clamp_geometry_to_screens(const QRect& geometry);

class FloatController : public QObject {
    Q_OBJECT
public:
    // resolver: optional key -> QWidget lookup for float-by-key callers.
    // persistence: optional LayoutPersistence; nullptr disables persistence
    //   entirely (tests/offscreen CI stay hermetic).
    // title_for: optional key -> title for floating windows; default
    //   consults the shared panel registry (dock_manager).
    explicit FloatController(
        std::function<QWidget*(const std::string&)> resolver = nullptr,
        LayoutPersistence* persistence = nullptr,
        std::function<QString(const std::string&)> title_for = nullptr,
        QObject* parent = nullptr);

    // Float `key`'s widget into a FloatingPanel. Returns true when the
    // widget is now floating; false when already floating or unresolvable.
    bool float_panel(const std::string& key, QWidget* widget = nullptr,
                     std::optional<QRect> geometry = std::nullopt);
    // Dock `key`'s widget back at its recorded splitter slot. False when
    // not floating or the dock parent is gone (the panel stays floating
    // rather than orphaning the widget).
    bool dock_panel(const std::string& key);
    // Float a docked panel, or dock a floating one.
    bool toggle(const std::string& key, QWidget* widget = nullptr);

    bool is_floating(const std::string& key) const;
    std::vector<std::string> floating_keys() const;
    FloatingPanel* floating_panel(const std::string& key) const;

    // Re-apply a persisted layout for `key` (safe no-op when empty). Pages
    // are eagerly constructed, so a widget is always available to restore
    // into. Returns true when any saved state was applied.
    bool restore_saved(const std::string& key, QWidget* widget = nullptr);

signals:
    void float_changed(const QString& key, bool floating);

private:
    QWidget* resolve(const std::string& key) const;
    FloatingPanel* ensure_panel(const std::string& key);
    void on_panel_visibility_changed(const std::string& key, bool visible);
    bool can_reinsert(const FloatRecord& record) const;
    void reinsert(const FloatRecord& record);
    static QSplitter* enclosing_splitter(QWidget* widget);
    static QRect default_geometry(QWidget* widget, QWidget* dock_parent);

    std::function<QWidget*(const std::string&)> resolver_;
    LayoutPersistence* persistence_ = nullptr;  // not owned
    std::function<QString(const std::string&)> title_for_;
    std::map<std::string, FloatRecord> floats_;
    std::map<std::string, QPointer<FloatingPanel>> panels_;
};

// Ribbon 右键面板菜单 entries for a page's floatable panels — each entry
// carries key/title/visible/floating plus set_visible(bool)/toggle_float()
// actions. Visibility reads the explicit-hide flag for docked widgets
// (isVisible() is false for everything before the window shows) and the
// floating window's own visibility once afloat.
struct FloatablePanelEntry {
    std::string key;
    QString title;
    bool visible = false;
    bool floating = false;
    std::function<void(bool)> set_visible;
    std::function<void()> toggle_float;
};

std::vector<FloatablePanelEntry> floatable_panel_entries(
    FloatController& controller,
    const std::map<std::string, QWidget*>& panels);

}  // namespace pwb::ui_shell
