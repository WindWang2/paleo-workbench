#include "pwb/ui_ribbon/qt/ribbon_bar.hpp"

#include <pwb/platform_services/theme_tokens.hpp>
#include <pwb/ui_shell/shortcut_registry.hpp>
#include <pwb/ui_widgets/icon_factory.hpp>

#include <QFontMetrics>
#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QMenu>
#include <QResizeEvent>
#include <QShortcut>
#include <QStackedWidget>
#include <QStringList>
#include <QStyle>
#include <QTabBar>
#include <QToolButton>
#include <QVBoxLayout>

#include <algorithm>

namespace pwb::ui_ribbon::qt {

namespace {

// Icon sizes (logical px, R:21-22): 主按钮 32px；次级/紧凑 16–20px。
constexpr int kPrimaryIconSize = 32;
constexpr int kSecondaryIconSize = 18;
constexpr int kCompactIconSize = 18;
// Vertical chrome around the command row (margins + label row spacing).
constexpr int kBandPadding = 10;
// Floor for a proportional group share so a group never collapses to 0.
constexpr int kMinGroupShare = 72;

}  // namespace

RibbonBar::RibbonBar(QWidget* parent) : QWidget(parent) {
    qRegisterMetaType<pwb::ui_ribbon::RibbonMode>(
        "pwb::ui_ribbon::RibbonMode");
    setObjectName("ribbonBar");

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    layout->addWidget(build_nav_row());

    band_ = new QStackedWidget;
    band_->setObjectName("ribbonBand");
    build_band_pages();
    layout->addWidget(band_);

    // Esc re-collapses a temporarily expanded band (R:23). Disabled
    // unless a temporary expansion is active so it never steals Esc from
    // inner widgets.
    esc_shortcut_ = new QShortcut(QKeySequence(QStringLiteral("Esc")), this);
    esc_shortcut_->setContext(Qt::WidgetWithChildrenShortcut);
    esc_shortcut_->setEnabled(false);
    connect(esc_shortcut_, &QShortcut::activated, this, [this] {
        if (!mode_state_.temporarily_expanded()) return;
        mode_state_.set_temporarily_expanded(false);
        apply_mode();
    });

    setStyleSheet(build_ribbon_qss());
    apply_mode();
    tabs_->setCurrentIndex(0);
}

// ---------------------------------------------------------------------------
// host wiring
// ---------------------------------------------------------------------------

void RibbonBar::set_file_menu(QMenu* menu) {
    file_button_->setMenu(menu);
    file_button_->setEnabled(menu != nullptr);
    file_button_->setToolTip(menu != nullptr ? QStringLiteral("文件菜单")
                                             : QStringLiteral("文件菜单（宿主未注入）"));
}

void RibbonBar::set_quick_access_actions(const QuickAccessActions& actions) {
    auto bind = [](QToolButton* button, QAction* action) {
        if (action != nullptr) {
            button->setDefaultAction(action);
            button->show();
        } else {
            button->setDefaultAction(nullptr);
            button->hide();
        }
    };
    bind(qat_save_, actions.save);
    bind(qat_undo_, actions.undo);
    bind(qat_redo_, actions.redo);
}

void RibbonBar::set_command_action(const QString& command_id, QAction* action) {
    for_each_group([&](GroupWidgets& group) {
        for (auto& command : group.commands) {
            if (command.id != command_id) continue;
            command.bound_action = action;
            if (action != nullptr) {
                // D4: the button carries the host's governed QAction —
                // the same action menus/shortcuts/palette reuse. The
                // placeholder intent path steps aside so one click
                // never fires both.
                command.button->setDefaultAction(action);
                QObject::disconnect(command.clicked_connection);
            } else {
                command.button->setDefaultAction(nullptr);
                configure_command_button(command);
                if (!command.clicked_connection) {
                    command.clicked_connection = connect(
                        command.button, &QToolButton::clicked, this,
                        [this, id = command.id] { on_command_clicked(id); });
                }
            }
        }
    });
    apply_mode();
    refresh_command_availability();
}

void RibbonBar::set_shortcut_registry(
    pwb::ui_shell::ShortcutRegistry* registry) {
    shortcut_registry_ = registry;
    register_collapse_shortcut();
}

void RibbonBar::set_command_evaluator(
    pwb::ui_ribbon::CommandEvaluator evaluator) {
    evaluator_ = std::move(evaluator);
    refresh_command_availability();
}

void RibbonBar::refresh_command_availability() {
    for_each_group([&](GroupWidgets& group) {
        for (auto& command : group.commands) {
            // Bound buttons follow their host QAction (D4 single
            // source); the reason channel only speaks for the
            // unbound placeholder commands.
            if (command.bound_action != nullptr) continue;
            const auto state = pwb::ui_ribbon::evaluate_command(
                evaluator_, command.id.toStdString());
            command.button->setEnabled(state.enabled);
            QString tip = command.text;
            if (!state.enabled && !state.reason.empty()) {
                tip += QLatin1Char('\n') +
                       QString::fromStdString(state.reason);
            }
            command.button->setToolTip(tip);
        }
    });
}

// ---------------------------------------------------------------------------
// state
// ---------------------------------------------------------------------------

void RibbonBar::set_current_workspace(int index) {
    if (index < 0 || index >= pwb::ui_ribbon::kWorkspaceCount) return;
    if (index == current_workspace_) return;
    tabs_->setCurrentIndex(index);  // currentChanged -> on_workspace_changed
}

void RibbonBar::set_mode(pwb::ui_ribbon::RibbonMode mode) {
    // Collapse PRESERVES the compact preference (ribbon_state.hpp
    // invariant; review R6): the old form reset compact to false, so
    // collapsed+compact restored as standard.
    bool changed = false;
    if (mode == pwb::ui_ribbon::RibbonMode::Collapsed) {
        changed = mode_state_.set_collapsed(true);
    } else {
        changed = mode_state_.set_collapsed(false);
        changed = mode_state_.set_compact(
                      mode == pwb::ui_ribbon::RibbonMode::Compact) ||
                  changed;
    }
    if (!changed) return;
    apply_mode();
    emit modeChanged(mode_state_.mode());
}

void RibbonBar::set_compact(bool on) {
    if (!mode_state_.set_compact(on)) return;
    apply_mode();
    emit modeChanged(mode_state_.mode());
}

void RibbonBar::set_collapsed(bool on) {
    if (!mode_state_.set_collapsed(on)) return;
    apply_mode();
    emit modeChanged(mode_state_.mode());
}

// ---------------------------------------------------------------------------
// M5 context groups (R:33)
// ---------------------------------------------------------------------------

void RibbonBar::set_context_group(
    int workspace, const QString& key, const pwb::ui_ribbon::RibbonGroup& spec) {
    if (workspace < 0 || workspace >= pwb::ui_ribbon::kWorkspaceCount ||
        key.isEmpty()) {
        return;
    }
    auto& entries = context_groups_[static_cast<size_t>(workspace)];
    // Same-key replace in place: remove the old widgets first so the
    // swap never flickers the static groups.
    for (auto it = entries.begin(); it != entries.end(); ++it) {
        if (it->key != key) continue;
        if (auto* row = band_rows_[static_cast<size_t>(workspace)];
            row != nullptr) {
            row->removeWidget(it->separator);
            row->removeWidget(it->group.frame);
        }
        delete it->separator;
        delete it->group.frame;
        entries.erase(it);
        break;
    }
    QHBoxLayout* row = band_rows_[static_cast<size_t>(workspace)];
    if (row == nullptr) return;

    ContextGroup context;
    context.key = key;
    context.separator = create_group_separator();
    context.group = build_group(spec);
    // Insert in front of the trailing stretch: the static groups stay
    // left-packed and never move (R:33 layout stability — the stretch
    // absorbs the width change).
    const int before_stretch = std::max(row->count() - 1, 0);
    row->insertWidget(before_stretch, context.separator);
    row->insertWidget(before_stretch + 1, context.group.frame);
    entries.push_back(std::move(context));

    apply_mode();                    // mode chrome for the new buttons
    refresh_command_availability();  // evaluator channel applies too
    relayout_overflow();
}

void RibbonBar::clear_context_group(int workspace, const QString& key) {
    if (workspace < 0 || workspace >= pwb::ui_ribbon::kWorkspaceCount) return;
    auto& entries = context_groups_[static_cast<size_t>(workspace)];
    for (auto it = entries.begin(); it != entries.end(); ++it) {
        if (it->key != key) continue;
        if (auto* row = band_rows_[static_cast<size_t>(workspace)];
            row != nullptr) {
            row->removeWidget(it->separator);
            row->removeWidget(it->group.frame);
        }
        delete it->separator;
        delete it->group.frame;
        entries.erase(it);
        relayout_overflow();
        // Availability tracked context commands: removing the group can
        // remove disabled context entries — re-evaluate like
        // set_context_group does (review R8).
        refresh_command_availability();
        return;
    }
}

QStringList RibbonBar::context_group_keys(int workspace) const {
    QStringList keys;
    if (workspace < 0 || workspace >= pwb::ui_ribbon::kWorkspaceCount) {
        return keys;
    }
    for (const auto& context : context_groups_[static_cast<size_t>(workspace)]) {
        keys << context.key;
    }
    keys.sort();
    return keys;
}

void RibbonBar::for_each_group(
    const std::function<void(GroupWidgets&)>& fn) {
    for (auto& groups : workspace_groups_) {
        for (auto& group : groups) fn(group);
    }
    for (auto& contexts : context_groups_) {
        for (auto& context : contexts) fn(context.group);
    }
}

// ---------------------------------------------------------------------------
// inspection
// ---------------------------------------------------------------------------

QStringList RibbonBar::missing_icon_commands() const {
    QStringList out = missing_icons_;
    for (const auto& id : pwb::ui_ribbon::commands_without_icon()) {
        out << QString::fromStdString(id);
    }
    out.sort();
    out.removeDuplicates();
    return out;
}

int RibbonBar::band_height() const {
    if (!mode_state_.band_visible()) return 0;
    return band_height_for(mode_state_.effective_mode());
}

QStringList RibbonBar::overflow_command_ids(int workspace) const {
    QStringList out;
    if (workspace < 0 || workspace >= pwb::ui_ribbon::kWorkspaceCount) {
        return out;
    }
    const auto& static_groups = workspace_groups_[static_cast<size_t>(workspace)];
    const auto& contexts = context_groups_[static_cast<size_t>(workspace)];
    for (size_t g = 0; g < static_groups.size() + contexts.size(); ++g) {
        const GroupWidgets& group =
            g < static_groups.size() ? static_groups[g]
                                     : contexts[g - static_groups.size()].group;
        if (group.overflow_menu == nullptr) continue;
        for (const auto* action : group.overflow_menu->actions()) {
            if (action->isSeparator()) continue;
            // Library-created entries are named "ribbonMenu_<id>"; entries
            // bound to a host QAction reuse the host action and carry no
            // ribbon id here.
            const QString name = action->objectName();
            if (name.startsWith(QLatin1String("ribbonMenu_"))) {
                out << name.mid(11);
            }
        }
    }
    return out;
}

// ---------------------------------------------------------------------------
// construction
// ---------------------------------------------------------------------------

QWidget* RibbonBar::build_nav_row() {
    auto* nav = new QWidget(this);
    nav->setObjectName("ribbonNav");
    auto* layout = new QHBoxLayout(nav);
    layout->setContentsMargins(8, 2, 8, 2);
    layout->setSpacing(4);

    file_button_ = new QToolButton(nav);
    file_button_->setObjectName("ribbonFileButton");
    file_button_->setText(QStringLiteral("文件"));
    file_button_->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
    file_button_->setPopupMode(QToolButton::InstantPopup);
    file_button_->setAutoRaise(true);
    set_file_menu(nullptr);
    layout->addWidget(file_button_);

    // QAT 快捷访问区 — host-injected actions only (D4); hidden until the
    // host injects them.
    qat_save_ = new QToolButton(nav);
    qat_undo_ = new QToolButton(nav);
    qat_redo_ = new QToolButton(nav);
    for (auto* button : {qat_save_, qat_undo_, qat_redo_}) {
        button->setAutoRaise(true);
        button->hide();
    }
    qat_save_->setObjectName("ribbonQatSave");
    qat_undo_->setObjectName("ribbonQatUndo");
    qat_redo_->setObjectName("ribbonQatRedo");
    layout->addWidget(qat_save_);
    layout->addWidget(qat_undo_);
    layout->addWidget(qat_redo_);

    tabs_ = new QTabBar(nav);
    tabs_->setObjectName("ribbonTabs");
    tabs_->setExpanding(false);
    tabs_->setDrawBase(false);
    for (const auto workspace : pwb::ui_ribbon::kWorkspaceOrder) {
        tabs_->addTab(QString::fromUtf8(
            pwb::ui_ribbon::workspace_label(workspace)));
    }
    layout->addWidget(tabs_);
    layout->addStretch();

    // 命令搜索入口 — click opens the host CommandPalette (Ctrl+K stays
    // with the host's own shortcut registration).
    search_button_ = new QToolButton(nav);
    search_button_->setObjectName("ribbonSearch");
    search_button_->setText(QStringLiteral("搜索命令  Ctrl+K"));
    search_button_->setToolTip(QStringLiteral("命令面板 · Ctrl+K"));
    search_button_->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
    search_button_->setAutoRaise(true);
    search_button_->setIcon(resolve_icon("menu-search.svg", "chrome.search"));
    connect(search_button_, &QToolButton::clicked, this,
            [this] { emit searchRequested(); });
    layout->addWidget(search_button_);

    compact_button_ = new QToolButton(nav);
    compact_button_->setObjectName("ribbonCompact");
    compact_button_->setText(QStringLiteral("紧凑"));
    compact_button_->setToolTip(QStringLiteral("紧凑模式"));
    compact_button_->setCheckable(true);
    compact_button_->setAutoRaise(true);
    connect(compact_button_, &QToolButton::toggled, this,
            [this](bool on) { set_compact(on); });
    layout->addWidget(compact_button_);

    collapse_button_ = new QToolButton(nav);
    collapse_button_->setObjectName("ribbonCollapse");
    collapse_button_->setText(QStringLiteral("折叠"));
    collapse_button_->setToolTip(QStringLiteral("折叠 Ribbon · Ctrl+F1"));
    collapse_button_->setCheckable(true);
    collapse_button_->setAutoRaise(true);
    connect(collapse_button_, &QToolButton::toggled, this,
            [this](bool on) { set_collapsed(on); });
    layout->addWidget(collapse_button_);

    connect(tabs_, &QTabBar::currentChanged, this,
            &RibbonBar::on_workspace_changed);
    connect(tabs_, &QTabBar::tabBarClicked, this, [this](int) {
        // 折叠时点击标签临时展开（R:23）。
        if (mode_state_.collapsed()) {
            mode_state_.set_temporarily_expanded(true);
            apply_mode();
        }
    });
    connect(tabs_, &QTabBar::tabBarDoubleClicked, this, [this](int index) {
        // 双击活动标签切换固定/折叠状态（R:23）。
        if (index == current_workspace_) toggle_collapsed();
    });
    return nav;
}

void RibbonBar::build_band_pages() {
    const auto& specs = pwb::ui_ribbon::workspace_specs();
    for (size_t w = 0; w < specs.size() && w < workspace_groups_.size(); ++w) {
        auto* page = new QWidget;
        page->setObjectName("ribbonPage_" + QString::fromUtf8(
                                                  pwb::ui_ribbon::workspace_id(
                                                      specs[w].workspace)));
        auto* row = new QHBoxLayout(page);
        row->setContentsMargins(6, 2, 6, 2);
        row->setSpacing(3);
        band_rows_[w] = row;  // M5: context groups insert before stretch
        bool first_group = true;
        for (const auto& group_spec : specs[w].groups) {
            if (!first_group) row->addWidget(create_group_separator());
            first_group = false;
            GroupWidgets group = build_group(group_spec);
            row->addWidget(group.frame);
            workspace_groups_[w].push_back(std::move(group));
        }
        row->addStretch();
        band_->addWidget(page);
    }
}

RibbonBar::GroupWidgets RibbonBar::build_group(
    const pwb::ui_ribbon::RibbonGroup& spec) {
    GroupWidgets group;
    group.frame = new QFrame;
    group.frame->setObjectName("ribbonGroup_" +
                               QString::fromStdString(spec.id));
    auto* vertical = new QVBoxLayout(group.frame);
    vertical->setContentsMargins(4, 1, 6, 0);
    vertical->setSpacing(0);
    group.row = new QHBoxLayout;
    group.row->setSpacing(1);
    for (const auto& command_spec : spec.commands) {
        CommandButton command = create_command_button(command_spec);
        group.row->addWidget(command.button);
        group.commands.push_back(std::move(command));
    }
    // 组尾"更多"钮 — the compact-mode in-group overflow entry.
    group.overflow_button = new QToolButton;
    group.overflow_button->setObjectName("ribbonOverflow_" +
                                         QString::fromStdString(spec.id));
    group.overflow_button->setText(QStringLiteral("更多"));
    group.overflow_button->setToolTip(QStringLiteral("更多命令"));
    group.overflow_button->setAutoRaise(true);
    group.overflow_button->setPopupMode(QToolButton::InstantPopup);
    group.overflow_button->setToolButtonStyle(
        Qt::ToolButtonTextBesideIcon);
    group.overflow_button->setIcon(
        resolve_icon("chevron-down.svg", "chrome.overflow"));
    group.overflow_menu = new QMenu(group.overflow_button);
    group.overflow_button->setMenu(group.overflow_menu);
    group.overflow_button->hide();
    group.row->addWidget(group.overflow_button);

    vertical->addLayout(group.row, 1);
    group.label = new QLabel(QString::fromStdString(spec.label));
    group.label->setObjectName("ribbonGroupLabel");
    group.label->setAlignment(Qt::AlignCenter);
    vertical->addWidget(group.label);
    return group;
}

RibbonBar::CommandButton RibbonBar::create_command_button(
    const pwb::ui_ribbon::RibbonCommand& spec) {
    CommandButton command;
    command.id = QString::fromStdString(spec.id);
    command.text = QString::fromStdString(spec.text);
    command.icon = QString::fromStdString(spec.icon);
    command.kind = spec.kind;
    command.overflow = spec.overflow;
    command.button = new QToolButton;
    command.button->setObjectName("ribbonCommand_" + command.id);
    configure_command_button(command);
    command.clicked_connection =
        connect(command.button, &QToolButton::clicked, this,
                [this, id = command.id] { on_command_clicked(id); });
    return command;
}

void RibbonBar::configure_command_button(CommandButton& command) {
    command.button->setText(command.text);
    command.button->setIcon(resolve_icon(command.icon, command.id));
    command.button->setCheckable(command.kind ==
                                 pwb::ui_ribbon::CommandKind::Toggle);
    command.button->setAutoRaise(true);
    command.button->setToolTip(command.text);
}

QIcon RibbonBar::resolve_icon(const QString& name, const QString& gap_id) {
    if (!name.isEmpty()) {
        const QIcon icon = pwb::ui_widgets::workstation_icon(name);
        if (!icon.isNull()) return icon;
    }
    // Declared gap or asset absent behind the resource locator: QStyle
    // standard fallback + gap report (M1 icon inventory).
    if (!gap_id.isEmpty() && !missing_icons_.contains(gap_id)) {
        missing_icons_ << gap_id;
    }
    return style()->standardIcon(QStyle::SP_FileIcon);
}

QFrame* RibbonBar::create_group_separator() {
    auto* separator = new QFrame;
    separator->setObjectName("ribbonSeparator");
    separator->setFrameShape(QFrame::VLine);
    separator->setFixedWidth(1);
    return separator;
}

// ---------------------------------------------------------------------------
// mode application
// ---------------------------------------------------------------------------

void RibbonBar::apply_mode() {
    const auto effective = mode_state_.effective_mode();
    const bool compact = effective == pwb::ui_ribbon::RibbonMode::Compact;

    for_each_group([&](GroupWidgets& group) {
        // 组名仅标准模式显示（紧凑带 40–48px 放不下标签行）。
        group.label->setVisible(!compact);
        for (auto& command : group.commands) {
            command.button->setToolButtonStyle(
                compact ? Qt::ToolButtonTextBesideIcon
                        : Qt::ToolButtonTextUnderIcon);
            const int icon_px =
                compact ? kCompactIconSize
                        : (command.kind == pwb::ui_ribbon::CommandKind::
                                                Primary
                               ? kPrimaryIconSize
                               : kSecondaryIconSize);
            command.button->setIconSize(QSize(icon_px, icon_px));
        }
    });
    band_->setVisible(mode_state_.band_visible());
    if (mode_state_.band_visible()) {
        band_->setFixedHeight(band_height_for(effective));
    }
    compact_button_->setChecked(mode_state_.compact());
    collapse_button_->setChecked(mode_state_.collapsed());
    esc_shortcut_->setEnabled(mode_state_.temporarily_expanded());
    relayout_overflow();
}

int RibbonBar::band_height_for(pwb::ui_ribbon::RibbonMode mode) const {
    const auto metrics = pwb::ui_ribbon::metrics_for(mode);
    if (mode == pwb::ui_ribbon::RibbonMode::Collapsed) return 0;
    // Font-metric composition (R:24: 逻辑像素与字体度量，不写死截图坐标),
    // clamped into the spec区间 R:21-22.
    const QFontMetrics fm(font());
    int content = kBandPadding;
    if (mode == pwb::ui_ribbon::RibbonMode::Standard) {
        content += kPrimaryIconSize + 2 * fm.height() + fm.height();
    } else {
        content += kCompactIconSize + fm.height();
    }
    return qBound(metrics.min_height, content, metrics.max_height);
}

void RibbonBar::relayout_overflow() {
    if (band_ == nullptr) return;
    const int available = std::max(band_->width(), 1);
    for (size_t w = 0; w < workspace_groups_.size(); ++w) {
        // Static groups first, then the injected context groups — both
        // share the band width (compact demotion applies to context
        // commands exactly like static ones).
        std::vector<GroupWidgets*> groups;
        for (auto& group : workspace_groups_[w]) groups.push_back(&group);
        for (auto& context : context_groups_[w]) {
            groups.push_back(&context.group);
        }
        if (groups.empty()) continue;
        // Natural width per group with the CURRENT mode's button metrics;
        // shares are proportional so 2-command groups are not starved by
        // 5-command ones.
        std::vector<int> natural(groups.size(), 0);
        int total = 0;
        for (size_t g = 0; g < groups.size(); ++g) {
            int width = 0;
            for (const auto& command : groups[g]->commands) {
                width += command.button->sizeHint().width();
            }
            width += groups[g]->row->spacing() *
                     (static_cast<int>(groups[g]->commands.size()) + 1);
            width += 12;  // frame contents margins + separator allowance
            natural[g] = width;
            total += width;
        }
        for (size_t g = 0; g < groups.size(); ++g) {
            const int share = total <= available
                                  ? natural[g]
                                  : std::max(available * natural[g] / total,
                                             kMinGroupShare);
            relayout_group_overflow(*groups[g], share);
        }
    }
}

void RibbonBar::relayout_group_overflow(GroupWidgets& group,
                                        int available_width) {
    const bool compact =
        mode_state_.effective_mode() == pwb::ui_ribbon::RibbonMode::Compact;
    const int spacing = group.row->spacing();

    // Inline set first: in compact mode the declared-overflow commands
    // always live in the group menu (R:22); in standard mode everything
    // starts inline.
    std::vector<CommandButton*> inline_set;
    std::vector<CommandButton*> menu_set;
    for (auto& command : group.commands) {
        if (compact && command.overflow) {
            menu_set.push_back(&command);
        } else {
            inline_set.push_back(&command);
        }
    }

    auto row_width = [&]() {
        int width = 0;
        for (const auto* command : inline_set) {
            width += command->button->sizeHint().width();
        }
        const int shown = static_cast<int>(inline_set.size()) +
                          (menu_set.empty() ? 0 : 1);
        if (shown > 1) width += spacing * (shown - 1);
        if (!menu_set.empty()) {
            width += group.overflow_button->sizeHint().width();
        }
        return width;
    };

    // Space-driven demotion: while the row exceeds the group's share,
    // demote the LAST non-primary command into the menu — the primary
    // action never leaves the band.
    while (row_width() > available_width) {
        auto it = std::find_if(
            inline_set.rbegin(), inline_set.rend(),
            [](const CommandButton* command) {
                return command->kind != pwb::ui_ribbon::CommandKind::Primary;
            });
        if (it == inline_set.rend()) break;
        menu_set.push_back(*it);
        inline_set.erase(std::next(it).base());
    }

    for (auto& command : group.commands) {
        const bool in_menu =
            std::find(menu_set.begin(), menu_set.end(), &command) !=
            menu_set.end();
        command.button->setVisible(!in_menu);
    }
    rebuild_overflow_menu(group, menu_set);
    group.overflow_button->setVisible(!menu_set.empty());
}

void RibbonBar::rebuild_overflow_menu(
    GroupWidgets& group, const std::vector<CommandButton*>& menu_commands) {
    if (group.overflow_menu == nullptr) return;
    group.overflow_menu->clear();  // deletes the library-owned entries only
    for (auto* command : menu_commands) {
        if (command->bound_action != nullptr) {
            // D4: reuse the host's governed QAction — never a parallel one.
            group.overflow_menu->addAction(command->bound_action);
            continue;
        }
        auto* action = new QAction(
            resolve_icon(command->icon, command->id), command->text,
            group.overflow_menu);
        action->setObjectName("ribbonMenu_" + command->id);
        const auto state = pwb::ui_ribbon::evaluate_command(
            evaluator_, command->id.toStdString());
        action->setEnabled(state.enabled);
        if (!state.enabled && !state.reason.empty()) {
            action->setToolTip(command->text + QLatin1Char('\n') +
                               QString::fromStdString(state.reason));
        }
        connect(action, &QAction::triggered, this,
                [this, id = command->id] { on_command_clicked(id); });
        group.overflow_menu->addAction(action);
    }
}

// ---------------------------------------------------------------------------
// events / routing
// ---------------------------------------------------------------------------

void RibbonBar::resizeEvent(QResizeEvent* event) {
    QWidget::resizeEvent(event);
    relayout_overflow();
}

bool RibbonBar::event(QEvent* event) {
    if (event->type() == QEvent::LayoutRequest) {
        relayout_overflow();
    }
    return QWidget::event(event);
}

void RibbonBar::on_workspace_changed(int index) {
    if (index < 0 || index >= pwb::ui_ribbon::kWorkspaceCount) return;
    current_workspace_ = index;
    band_->setCurrentIndex(index);
    emit workspaceActivated(index);
}

void RibbonBar::on_command_clicked(const QString& command_id) {
    // 选择命令后收回临时展开的命令带（R:23）。
    if (mode_state_.temporarily_expanded()) {
        mode_state_.set_temporarily_expanded(false);
        apply_mode();
    }
    emit commandTriggered(command_id);
}

bool RibbonBar::shortcut_key_free(const std::string& key) const {
    if (shortcut_registry_ == nullptr) return false;
    for (const auto& spec : shortcut_registry_->all_specs()) {
        if (spec.key == key) return false;  // another owner already bound it
    }
    return shortcut_registry_->conflicts().count(key) == 0;
}

void RibbonBar::register_collapse_shortcut() {
    if (shortcut_registry_ == nullptr) return;
    // Register only when the key is free (R:23): conflicts() reports
    // same-key duplicate registrations, and any pre-existing spec means
    // another owner took the key — honest skip, the host decides.
    if (!shortcut_key_free("Ctrl+F1")) return;
    shortcut_registry_->register_shortcut(
        this,
        pwb::ui_shell::ShortcutSpec{.id = "ribbon.collapse",
                                    .key = "Ctrl+F1",
                                    .label = "折叠/展开 Ribbon"},
        [this] { toggle_collapsed(); },
        /*enabled_in_text_input=*/false);
}

// ---------------------------------------------------------------------------
// styling
// ---------------------------------------------------------------------------

QString RibbonBar::build_ribbon_qss() const {
    // Light token set. theme_tokens is the vocabulary source (设计规范
    // Qt 实施边界: 使用统一 QPalette/主题 token，避免再造第二套主题); the
    // design literals (#F0F0F0/#FFFFFF/#CCD1D6/#25313D/#0078D4) are the
    // fallback for roles the palette does not name.
    const auto palette = pwb::platform_services::palette_for(
        pwb::platform_services::ThemeMode::Light);
    auto token = [&palette](const char* name,
                            const char* fallback) -> QString {
        const auto it = palette.find(name);
        return it == palette.end() ? QString::fromUtf8(fallback)
                                   : QString::fromStdString(it->second);
    };
    const QString shell = token("BG_BODY", "#F0F0F0");
    const QString surface = token("SURFACE_RAISED", "#FFFFFF");
    const QString separator = token("BORDER", "#CCD1D6");
    const QString text_muted = token("TEXT_SECONDARY", "#53616C");
    const QString text = token("TEXT_PRIMARY", "#25313D");
    const QString hover = token("BG_MENU_HOVER", "#EDF2F4");
    const QString selection = token("BG_SELECTION", "#D8EBEF");
    const QString focus = token("FOCUS_RING", "#0078D4");
    // 少量状态/间距 QSS only; sizes come from font metrics + logical px.
    return QStringLiteral(
               "RibbonBar { background: %1; }"
               "QWidget#ribbonNav { background: %1; }"
               "QStackedWidget#ribbonBand { background: %2; }"
               "QFrame#ribbonSeparator { background: %3; }"
               "QLabel#ribbonGroupLabel { color: %4; }"
               "QToolButton { color: %5; border: 1px solid transparent;"
               " border-radius: 2px; padding: 4px; }"
               "QToolButton:hover { background: %6; }"
               "QToolButton:checked { background: %7; }"
               "QToolButton:focus { border: 1px solid %8; }"
               "QTabBar::tab { padding: 6px 12px; border: none;"
               " border-bottom: 2px solid transparent; }"
               "QTabBar::tab:selected { color: %8;"
               " border-bottom: 2px solid %8; }")
        .arg(shell, shell, surface, separator, text_muted, text, hover,
             selection, focus);
}

}  // namespace pwb::ui_ribbon::qt
