#pragma once

// UI-05 — MapDockManager + DockRail (map_dock_manager.py): collapsible
// dock rails and the panel manager for the mapping workspace.
//
// Presentation only: a narrow icon rail per side expands/collapses the
// panel area; a checkable 面板 menu toggles every panel from one place.
// Panels additionally float through pwb::ui_shell::FloatController — the
// panels menu gains a checkable 浮动 toggle per panel, rail buttons get a
// context menu with the same toggle, and while a panel is floating its
// rail button keeps meaning "panel visible" by showing/hiding the
// floating window instead of the docked widget.
//
// Rail and area are SIBLING widgets so the page can place the area inside
// a QSplitter — hiding the area returns its space to the central canvas.

#include <functional>
#include <map>
#include <string>
#include <vector>

#include <QObject>
#include <QPointer>

class QAction;
class QFrame;
class QMenu;
class QToolButton;
class QVBoxLayout;
class QWidget;

namespace pwb::ui_shell {
class FloatController;
class FloatingPanel;
}

namespace pwb::ui_map {

class DockRail {
public:
    DockRail(const std::string& side, QWidget* parent = nullptr);

    QToolButton* rail_button(const QString& title, const QString& icon_name);
    // Show the panel area only while at least one docked panel is visible.
    void sync_area_visibility();

    std::string side;
    QFrame* rail = nullptr;    // the always-visible icon strip (Qt child)
    QFrame* area = nullptr;    // the collapsible panel area (Qt child)
    QVBoxLayout* rail_layout = nullptr;
    QVBoxLayout* area_layout = nullptr;
};

class MapDockManager : public QObject {
    Q_OBJECT
public:
    explicit MapDockManager(QObject* parent = nullptr);

    // Enable panel floating: float toggles appear in the panels menu and
    // in each rail button's context menu, kept in sync with the
    // controller. The controller is caller-owned (Python parity).
    void attach_float_controller(pwb::ui_shell::FloatController* controller);

    // Dock `widget` into a side rail under a checkable rail button.
    // float_key is the namespaced FloatController key (defaults to key).
    void add_panel(const std::string& key, const QString& title,
                   const QString& icon_name, QWidget* widget,
                   const std::string& side, bool checked,
                   const std::string& float_key = "");

    // Register the bottom workbench: a left-rail bottom toggle plus menu
    // entry. `apply` recomputes the widget's real visibility from the user
    // preference combined with page mode flags (preview/canvas priority).
    void register_bottom(const std::string& key, const QString& title,
                         const QString& icon_name, QWidget* widget,
                         std::function<void()> apply,
                         const std::string& float_key = "");

    // BEGIN CLOSURE-MAPPING (08-line additive install seam — function
    // lease registered in codex-coordination/cpp-close-wave/08-line.json)
    // Repoint a registered panel entry at a replacement widget so rail /
    // menu / float behavior keeps targeting the live widget. No-op when
    // the key is unknown.
    void adopt_panel_widget(const std::string& key, QWidget* widget);
    // END CLOSURE-MAPPING

    void set_panel_visible(const std::string& key, bool visible);
    bool is_panel_visible(const std::string& key) const;
    QToolButton* panel_button(const std::string& key) const;

    bool bottom_user_visible() const { return bottom_user_visible_; }

    // Programmatic (preference/mode-derived) visibility for a floating
    // bottom window — the mirror ignores this transition (it is not a
    // user close and must not write back into bottom_user_visible_).
    void set_bottom_window_visible(bool visible);

    // Display title for a panel key or float key (the floating window's
    // title); the last ":"-separated segment or the whole key otherwise.
    std::string panel_title(const std::string& key) const;

    bool is_floating(const std::string& key) const;
    void toggle_float(const std::string& key);

    // Checkable 面板 menu: one visibility action plus one 浮动 toggle per
    // panel (menu + actions are parented to `parent`, recreated per call).
    QMenu* panels_menu(QWidget* parent = nullptr);
    // The context menu a rail button shows (currently: the float toggle).
    QMenu* rail_context_menu(const std::string& key);

    DockRail* left_dock() { return &left_dock_; }
    DockRail* right_dock() { return &right_dock_; }

signals:
    void panel_toggled(const QString& key, bool visible);

private:
    struct PanelEntry {
        std::string key;
        QString title;
        QString icon_name;
        QPointer<QWidget> widget;
        DockRail* dock = nullptr;  // nullptr for the bottom panel
        QPointer<QToolButton> button;
        std::string float_key;
        QPointer<QAction> menu_action;
        QPointer<QAction> float_menu_action;
    };

    const PanelEntry* entry_for(const std::string& key) const;
    PanelEntry* entry_for(const std::string& key);
    std::string float_key_of(const std::string& key) const;
    std::string key_for_float_key(const std::string& float_key) const;

    void install_rail_context_menu(const std::string& key);
    QAction* float_menu_action(QObject* parent, const std::string& key);
    void show_rail_menu(const std::string& key, const QPoint& pos);
    void sync_menu_action(const std::string& key, bool on);
    void sync_float_menu_action(const std::string& key, bool floating);

    void on_rail_toggled(const std::string& key, bool on);
    void on_float_changed(const QString& float_key, bool floating);
    void on_floating_window_visibility(const std::string& float_key,
                                       bool visible);
    void on_float_action_toggled(const std::string& key, bool on);
    void on_bottom_toggled(const std::string& key, bool on);

    DockRail left_dock_;
    DockRail right_dock_;
    std::map<std::string, PanelEntry> panels_;
    std::vector<std::string> panel_order_;  // insertion order (dict parity)
    QPointer<QWidget> bottom_widget_;
    std::function<void()> bottom_apply_;
    bool bottom_user_visible_ = true;
    bool bottom_programmatic_ = false;
    QPointer<pwb::ui_shell::FloatController> float_controller_;
    QPointer<QMenu> menu_;
};

}  // namespace pwb::ui_map
