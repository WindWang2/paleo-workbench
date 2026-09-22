#pragma once

// UI-18 — RibbonBar: the Qt Widgets shell of the five-workspace ribbon
// chrome (M1, docs/development/ribbon-five-workspaces/00-plan.md D3;
// design contract docs/ui-redesign/qt-ribbon-workspaces-2026-09-21/
// README.md).
//
// Structure mirrors the prototype's chrome (prototypes/qt_ribbon_native/
// main.cpp:114-124, 207-211) — ONE nav row (file button + QAT + five
// workspace tabs + stretch + command search + compact/collapse toggles)
// over a QStackedWidget of per-workspace command bands (group frames with
// a horizontal QToolButton row + bottom group label + separators).
// Structure only: the prototype's synthetic data, inline QSS and QStyle
// icon heuristics never enter production.
//
// Command wiring (D4): the library creates NO QAction. Command buttons
// either carry a host-injected governed QAction (set_command_action —
// the same action the menus/shortcuts/palette reuse) or, while unbound
// (M1), stay plain buttons that emit commandTriggered for the host to
// route. The QAT save/undo/redo actions are host-injected the same way.
// The disabled-reason channel is an injected evaluator over command ids
// (ribbon_state.hpp) — this library never links CommandRegistry.
//
// Ctrl+F1 registers through the host's ShortcutRegistry and only when
// conflicts()/all_specs() show the key is free (R:23).

#include <array>
#include <functional>
#include <vector>

#include <QAction>
#include <QString>
#include <QStringList>
#include <QWidget>

#include <pwb/ui_ribbon/ribbon_spec.hpp>
#include <pwb/ui_ribbon/ribbon_state.hpp>

class QFrame;
class QHBoxLayout;
class QLabel;
class QMenu;
class QEvent;
class QResizeEvent;
class QShortcut;
class QStackedWidget;
class QTabBar;
class QToolButton;

namespace pwb::ui_shell {
class ShortcutRegistry;
}

namespace pwb::ui_ribbon::qt {

class RibbonBar : public QWidget {
    Q_OBJECT

public:
    // Host-injected quick-access actions (D4). Null action -> the button
    // stays hidden; the library never creates parallel QActions.
    struct QuickAccessActions {
        QAction* save = nullptr;
        QAction* undo = nullptr;
        QAction* redo = nullptr;
    };

    explicit RibbonBar(QWidget* parent = nullptr);

    // ---- host wiring (M2/M4 install binds these) -------------------------
    // File button popup (host owns the menu: MRU + all commands).
    void set_file_menu(QMenu* menu);
    void set_quick_access_actions(const QuickAccessActions& actions);
    // Bind (or unbind, with nullptr) a governed QAction to a command
    // button; the menu entries of the compact overflow reuse the same
    // action. Rebinding re-applies mode + availability.
    void set_command_action(const QString& command_id, QAction* action);
    // Shortcut registry for the Ctrl+F1 collapse entry (nullptr = the
    // entry is not registered — the host may register it itself).
    void set_shortcut_registry(pwb::ui_shell::ShortcutRegistry* registry);
    // Disabled-reason channel: (command id) -> (enabled, reason). Applied
    // to the UNBOUND buttons only — bound buttons follow their host
    // QAction (single source of truth, D4).
    void set_command_evaluator(pwb::ui_ribbon::CommandEvaluator evaluator);
    void refresh_command_availability();

    // ---- state ------------------------------------------------------------
    int current_workspace() const { return current_workspace_; }
    void set_current_workspace(int index);

    // ---- M5 context groups (R:33) ------------------------------------------
    // One transient group per (workspace, key), injected by the host when
    // a context object is selected (约束线/标注/图例/地图框). The group
    // renders at the END of that workspace's band page, in front of the
    // trailing stretch — static groups stay left-packed, so the group's
    // appearance/disappearance never moves the main buttons (R:33 layout
    // stability). Same-key set replaces in place (no flicker). Commands
    // inside ride the SAME id binding + evaluator + overflow paths as the
    // static table (D4 — no parallel actions).
    void set_context_group(int workspace, const QString& key,
                           const pwb::ui_ribbon::RibbonGroup& spec);
    void clear_context_group(int workspace, const QString& key);

    pwb::ui_ribbon::RibbonMode mode() const { return mode_state_.mode(); }
    void set_mode(pwb::ui_ribbon::RibbonMode mode);
    void set_compact(bool on);
    void set_collapsed(bool on);
    void toggle_collapsed() { set_collapsed(!mode_state_.collapsed()); }

    // ---- inspection -------------------------------------------------------
    // Icon asset gap inventory: declared-empty + runtime misses (asset
    // absent behind the resource locator). Empty = every icon resolved.
    QStringList missing_icon_commands() const;
    // M5 context groups (R:33): the keys currently injected into one
    // workspace's band (empty when no context object is selected).
    QStringList context_group_keys(int workspace) const;
    // Command band height (logical px, excluding the tab row) for the
    // effective mode; 0 while collapsed.
    int band_height() const;
    // Command ids currently inside the compact overflow menus of one
    // workspace's groups (empty in standard mode unless space-driven
    // demotion kicked in).
    QStringList overflow_command_ids(int workspace) const;

signals:
    void workspaceActivated(int index);
    void commandTriggered(const QString& command_id);
    void searchRequested();
    void modeChanged(pwb::ui_ribbon::RibbonMode mode);

protected:
    void resizeEvent(QResizeEvent* event) override;
    // Command-button font/label changes (density switch, host rebind)
    // change the space the bands need without a resize — relayout on
    // layout invalidation too.
    bool event(QEvent* event) override;

private:
    // ------------------------------------------------------------------
    struct CommandButton {
        QToolButton* button = nullptr;
        QAction* bound_action = nullptr;  // host-owned, never created here
        // The placeholder intent connection; disconnected while a host
        // QAction is bound so one click never fires both paths.
        QMetaObject::Connection clicked_connection;
        QString id;
        QString text;   // spec copy for unbind/restore
        QString icon;   // spec copy
        pwb::ui_ribbon::CommandKind kind =
            pwb::ui_ribbon::CommandKind::Secondary;
        bool overflow = false;
    };

    struct GroupWidgets {
        QFrame* frame = nullptr;
        QHBoxLayout* row = nullptr;
        QLabel* label = nullptr;
        QToolButton* overflow_button = nullptr;
        QMenu* overflow_menu = nullptr;
        std::vector<CommandButton> commands;
    };

    // M5 context group (R:33): a host-injected transient group rendered
    // at the band end (before the trailing stretch) of ONE workspace.
    struct ContextGroup {
        QString key;
        QFrame* separator = nullptr;
        GroupWidgets group;
    };

    void build_band_pages();
    QWidget* build_nav_row();
    GroupWidgets build_group(const pwb::ui_ribbon::RibbonGroup& spec);
    CommandButton create_command_button(const pwb::ui_ribbon::RibbonCommand& spec);
    void configure_command_button(CommandButton& command);

    // Iterate EVERY group of every workspace — static table + injected
    // context groups — so bindings/availability/mode/overflow apply
    // uniformly (one code path, D4).
    void for_each_group(const std::function<void(GroupWidgets&)>& fn);

    QIcon resolve_icon(const QString& name, const QString& gap_id);
    QFrame* create_group_separator();

    void apply_mode();
    int band_height_for(pwb::ui_ribbon::RibbonMode mode) const;
    void relayout_overflow();
    void relayout_group_overflow(GroupWidgets& group, int available_width);
    void rebuild_overflow_menu(GroupWidgets& group,
                               const std::vector<CommandButton*>& menu_commands);

    void on_workspace_changed(int index);
    void on_command_clicked(const QString& command_id);
    void register_collapse_shortcut();
    bool shortcut_key_free(const std::string& key) const;

    QString build_ribbon_qss() const;

    pwb::ui_ribbon::RibbonModeState mode_state_;
    pwb::ui_ribbon::CommandEvaluator evaluator_;
    int current_workspace_ = 0;

    // nav row
    QToolButton* file_button_ = nullptr;
    QToolButton* qat_save_ = nullptr;
    QToolButton* qat_undo_ = nullptr;
    QToolButton* qat_redo_ = nullptr;
    QTabBar* tabs_ = nullptr;
    QToolButton* search_button_ = nullptr;
    QToolButton* compact_button_ = nullptr;
    QToolButton* collapse_button_ = nullptr;
    QShortcut* esc_shortcut_ = nullptr;

    // command bands
    QStackedWidget* band_ = nullptr;
    std::array<std::vector<GroupWidgets>, pwb::ui_ribbon::kWorkspaceCount>
        workspace_groups_;
    // Band row per workspace (the trailing stretch lives at its end) —
    // context groups insert before the stretch so static groups never
    // move (R:33 layout stability).
    std::array<QHBoxLayout*, pwb::ui_ribbon::kWorkspaceCount> band_rows_{};
    // M5 context groups per workspace (R:33).
    std::array<std::vector<ContextGroup>, pwb::ui_ribbon::kWorkspaceCount>
        context_groups_;

    pwb::ui_shell::ShortcutRegistry* shortcut_registry_ = nullptr;
    QStringList missing_icons_;  // gap report (sorted, deduplicated)
};

}  // namespace pwb::ui_ribbon::qt
