// UI-18 — Qt offscreen smoke (QT_QPA_PLATFORM=offscreen, pinned by
// ctest): the real RibbonBar over the real core table. Covers the M1
// contract: two workspace tabs, tab switching swaps the command band,
// three-mode heights inside the R:21-23 logical-pixel ranges, the three
// collapse entries (button / double-click active tab / Ctrl+F1 through
// the host ShortcutRegistry with the conflicts() guard), temporary
// expansion retracting on command/Esc, compact in-group overflow menus
// (declared + space-driven), host-injected QAT actions, command routing
// (intent signal vs bound QAction), the disabled-reason channel, icon
// gap reporting, and keyboard Tab traversal. Manual counters instead of
// QtTest (the local Qt install may lack the Test module).

#include <cstdio>
#include <string>

#include <QAction>
#include <QApplication>
#include <QCoreApplication>
#include <QDir>
#include <QEventLoop>
#include <QFile>
#include <QKeyEvent>
#include <QMenu>
#include <QShortcut>
#include <QStackedWidget>
#include <QTabBar>
#include <QTemporaryDir>
#include <QToolButton>
#include <QtGlobal>

#include <pwb/ui_ribbon/qt/ribbon_bar.hpp>
#include <pwb/ui_shell/shortcut_registry.hpp>

#include "ui_ribbon_test.hpp"

using pwb::ui_ribbon::CommandState;
using pwb::ui_ribbon::RibbonMode;
using RibbonBar = pwb::ui_ribbon::qt::RibbonBar;

namespace {

QToolButton* find_button(const RibbonBar& bar, const QString& name) {
    return bar.findChild<QToolButton*>(name);
}

QShortcut* find_shortcut(const RibbonBar& bar, const QString& key) {
    for (auto* shortcut : bar.findChildren<QShortcut*>()) {
        if (shortcut->key() == QKeySequence(key)) return shortcut;
    }
    return nullptr;
}

void pump() {
    for (int i = 0; i < 20; ++i) {
        QCoreApplication::processEvents(QEventLoop::AllEvents, 10);
    }
}

}  // namespace

// Declared FIRST: icon_factory caches per (name, tint, ratio) for the
// process lifetime, so the resource-root test must run before any other
// RibbonBar construction resolves the same names.
PWB_TEST(icon_resolution_and_gap_report) {
    QTemporaryDir dir;
    CHECK(dir.isValid());
    CHECK(QDir().mkpath(dir.path() + "/ui/assets/icons/map"));
    {
        QFile asset(dir.path() + "/ui/assets/icons/map/btn-import.svg");
        CHECK(asset.open(QIODevice::WriteOnly));
        asset.write("<svg xmlns=\"http://www.w3.org/2000/svg\" "
                    "width=\"16\" height=\"16\"></svg>");
    }
    qputenv("PALEO_RESOURCES_DIR", dir.path().toUtf8());
    {
        RibbonBar bar;
        bar.resize(1400, 300);
        bar.show();
        pump();
        const QStringList missing = bar.missing_icon_commands();
        // Resolvable asset: not a gap.
        CHECK(!missing.contains("data.import"));
        // Absent asset: runtime gap, QStyle fallback engaged.
        CHECK(missing.contains("data.scan"));
        // 编图静态带（模式 toggle + 输出组）同样走运行期缺口报告；
        // rb-send.svg 不在覆盖根 → map.submit 记为运行时 miss。
        CHECK(missing.contains("map.submit"));
        CHECK(missing.contains("mode.predict"));
    }
    qunsetenv("PALEO_RESOURCES_DIR");
}

PWB_TEST(construction_two_workspace_tabs) {
    RibbonBar bar;
    bar.resize(1400, 300);
    bar.show();
    pump();
    auto* tabs = bar.findChild<QTabBar*>("ribbonTabs");
    CHECK(tabs != nullptr);
    CHECK(tabs->count() == 2);
    CHECK(tabs->tabText(0) == "数据管理");
    CHECK(tabs->tabText(1) == "编图");
    auto* band = bar.findChild<QStackedWidget*>("ribbonBand");
    CHECK(band != nullptr);
    CHECK(band->count() == 2);
    CHECK(band->currentIndex() == 0);
    CHECK(bar.current_workspace() == 0);
    CHECK(bar.mode() == RibbonMode::Standard);
    CHECK(find_button(bar, "ribbonFileButton") != nullptr);
    CHECK(find_button(bar, "ribbonSearch") != nullptr);
    CHECK(find_button(bar, "ribbonCompact") != nullptr);
    CHECK(find_button(bar, "ribbonCollapse") != nullptr);
    // Every workspace page carries its groups' command buttons — 编图's
    // static band is the mode toggles + the output group.
    CHECK(find_button(bar, "ribbonCommand_data.import") != nullptr);
    CHECK(find_button(bar, "ribbonCommand_mode.predict") != nullptr);
    CHECK(find_button(bar, "ribbonCommand_map.export") != nullptr);
}

PWB_TEST(workspace_switching_switches_band) {
    RibbonBar bar;
    bar.resize(1400, 300);
    bar.show();
    pump();
    auto* band = bar.findChild<QStackedWidget*>("ribbonBand");
    int activated = -1;
    int emissions = 0;
    QObject::connect(&bar, &RibbonBar::workspaceActivated,
                     [&](int index) {
                         activated = index;
                         ++emissions;
                     });
    bar.set_current_workspace(1);
    pump();
    CHECK(bar.current_workspace() == 1);
    CHECK(band->currentIndex() == 1);
    CHECK(activated == 1);
    CHECK(emissions == 1);
    // Same index: no re-emission (true-change contract).
    bar.set_current_workspace(1);
    pump();
    CHECK(emissions == 1);
    // The active page's commands are the visible ones.
    CHECK(find_button(bar, "ribbonCommand_map.export")->isVisible());
    CHECK(!find_button(bar, "ribbonCommand_data.import")->isVisible());
    // Out-of-range requests are ignored.
    bar.set_current_workspace(9);
    bar.set_current_workspace(-1);
    pump();
    CHECK(bar.current_workspace() == 1);
}

PWB_TEST(three_mode_band_heights) {
    RibbonBar bar;
    bar.resize(1400, 300);
    bar.show();
    pump();
    auto* band = bar.findChild<QStackedWidget*>("ribbonBand");
    int mode_emissions = 0;
    RibbonMode last = RibbonMode::Standard;
    QObject::connect(&bar, &RibbonBar::modeChanged,
                     [&](RibbonMode mode) {
                         last = mode;
                         ++mode_emissions;
                     });

    const int standard = bar.band_height();
    CHECK(standard >= 76);
    CHECK(standard <= 96);
    CHECK(band->height() == standard);

    bar.set_compact(true);
    pump();
    const int compact = bar.band_height();
    CHECK(compact >= 40);
    CHECK(compact <= 48);
    CHECK(band->height() == compact);
    CHECK(bar.mode() == RibbonMode::Compact);
    CHECK(mode_emissions == 1);
    CHECK(last == RibbonMode::Compact);

    bar.set_collapsed(true);
    pump();
    CHECK(bar.mode() == RibbonMode::Collapsed);
    CHECK(!band->isVisible());
    CHECK(bar.band_height() == 0);
    CHECK(mode_emissions == 2);
    CHECK(last == RibbonMode::Collapsed);

    // The compact preference survives the collapse.
    bar.set_collapsed(false);
    pump();
    CHECK(bar.mode() == RibbonMode::Compact);
    CHECK(band->isVisible());
}

PWB_TEST(collapse_three_entries) {
    // Registry outlives the bar: register_shortcut's destroyed-hook runs
    // against `this` when a child QShortcut dies, so a stack registry must
    // be declared BEFORE the widget (reverse destruction order) — same
    // contract the static shortcut_registry() singleton guarantees.
    pwb::ui_shell::ShortcutRegistry registry;
    RibbonBar bar;
    bar.resize(1400, 300);
    bar.show();
    pump();
    auto* band = bar.findChild<QStackedWidget*>("ribbonBand");
    auto* tabs = bar.findChild<QTabBar*>("ribbonTabs");
    auto* collapse = find_button(bar, "ribbonCollapse");
    CHECK(collapse->isCheckable());

    // Entry 1: the collapse button.
    collapse->click();
    pump();
    CHECK(bar.mode() == RibbonMode::Collapsed);
    CHECK(!band->isVisible());
    CHECK(collapse->isChecked());
    collapse->click();
    pump();
    CHECK(bar.mode() == RibbonMode::Standard);
    CHECK(band->isVisible());

    // Entry 2: double-click the ACTIVE tab.
    emit tabs->tabBarDoubleClicked(tabs->currentIndex());
    pump();
    CHECK(bar.mode() == RibbonMode::Collapsed);
    emit tabs->tabBarDoubleClicked(tabs->currentIndex());
    pump();
    CHECK(bar.mode() == RibbonMode::Standard);

    // Entry 3: Ctrl+F1 through the host ShortcutRegistry.
    bar.set_shortcut_registry(&registry);
    CHECK(registry.get("ribbon.collapse") != nullptr);
    QShortcut* fold = find_shortcut(bar, "Ctrl+F1");
    CHECK(fold != nullptr);
    emit fold->activated();
    pump();
    CHECK(bar.mode() == RibbonMode::Collapsed);
    emit fold->activated();
    pump();
    CHECK(bar.mode() == RibbonMode::Standard);

    // A taken key is never registered (conflicts() guard, R:23).
    pwb::ui_shell::ShortcutRegistry taken;
    taken.register_meta(pwb::ui_shell::ShortcutSpec{
        .id = "other.owner", .key = "Ctrl+F1", .label = "占用"});
    RibbonBar other;
    other.set_shortcut_registry(&taken);
    CHECK(taken.get("ribbon.collapse") == nullptr);
    CHECK(find_shortcut(other, "Ctrl+F1") == nullptr);
}

PWB_TEST(temporary_expand_then_retract) {
    RibbonBar bar;
    bar.resize(1400, 300);
    bar.show();
    pump();
    auto* band = bar.findChild<QStackedWidget*>("ribbonBand");
    auto* tabs = bar.findChild<QTabBar*>("ribbonTabs");
    bar.set_collapsed(true);
    pump();
    CHECK(!band->isVisible());

    // Tab click while collapsed: temporary expansion (R:23).
    emit tabs->tabBarClicked(1);
    pump();
    CHECK(band->isVisible());
    CHECK(bar.current_workspace() == 0);  // the click alone does not switch
    tabs->setCurrentIndex(1);
    pump();
    CHECK(band->isVisible());
    CHECK(bar.current_workspace() == 1);

    // Choosing a command retracts the band.
    find_button(bar, "ribbonCommand_map.export")->click();
    pump();
    CHECK(!band->isVisible());

    // Esc retracts as well.
    emit tabs->tabBarClicked(0);
    pump();
    CHECK(band->isVisible());
    QShortcut* esc = find_shortcut(bar, "Esc");
    CHECK(esc != nullptr);
    emit esc->activated();
    pump();
    CHECK(!band->isVisible());
}

PWB_TEST(compact_overflow_menu) {
    RibbonBar bar;
    bar.resize(1600, 400);
    bar.show();
    pump();
    bar.set_current_workspace(0);
    pump();

    // Standard mode at a wide size: everything inline, no overflow entry.
    CHECK(bar.overflow_command_ids(0).isEmpty());
    CHECK(!bar.findChild<QToolButton*>("ribbonOverflow_data_import")
               ->isVisible());
    const qreal standard_font =
        find_button(bar, "ribbonCommand_data.import")->font().pointSizeF();

    // Compact: declared-overflow commands live in the group menu.
    bar.set_compact(true);
    pump();
    auto* overflow = bar.findChild<QToolButton*>("ribbonOverflow_data_import");
    CHECK(overflow->isVisible());
    CHECK(overflow->popupMode() == QToolButton::InstantPopup);
    const QStringList wide_menu = bar.overflow_command_ids(0);
    CHECK(wide_menu.contains("data.plan"));
    CHECK(wide_menu.contains("data.set_role"));
    CHECK(!wide_menu.contains("data.scan"));  // still inline at 1600

    // 禁止缩字 (C3): compact mode never shrinks the command font.
    const qreal compact_font =
        find_button(bar, "ribbonCommand_data.import")->font().pointSizeF();
    CHECK(qFuzzyCompare(standard_font, compact_font));

    // Narrow: simulate wider command labels (M4's real command sets are
    // wider than the M1 placeholders) by growing every command button's
    // font — the band content now exceeds the space, so space-driven
    // demotion moves further secondaries into the group menu. The
    // primary never leaves the band.
    for (auto* button : bar.findChildren<QToolButton*>()) {
        if (!button->objectName().startsWith(QLatin1String("ribbonCommand_"))) {
            continue;
        }
        QFont wide = button->font();
        wide.setPointSize(24);
        button->setFont(wide);
    }
    pump();
    const QStringList narrow_menu = bar.overflow_command_ids(0);
    CHECK(narrow_menu.size() > wide_menu.size());
    // At least one secondary beyond the declared-overflow set was demoted
    // by the space pressure; the primary never leaves the band.
    const QStringList declared = {"data.plan", "data.set_role", "data.units",
                                  "data.lineage"};
    QStringList demoted;
    for (const auto& id : narrow_menu) {
        if (!declared.contains(id)) demoted << id;
    }
    CHECK(!demoted.isEmpty());
    CHECK(!demoted.contains("data.import"));
    CHECK(find_button(bar, "ribbonCommand_data.import")->isVisible());
}

PWB_TEST(qat_actions_injected) {
    RibbonBar bar;
    bar.resize(1400, 300);
    bar.show();
    pump();
    auto* save = find_button(bar, "ribbonQatSave");
    auto* undo = find_button(bar, "ribbonQatUndo");
    auto* redo = find_button(bar, "ribbonQatRedo");
    CHECK(save != nullptr && undo != nullptr && redo != nullptr);
    // Hidden until the host injects — the library creates no QAction.
    CHECK(!save->isVisible());
    CHECK(!undo->isVisible());
    CHECK(!redo->isVisible());

    QAction save_action(QIcon(), QStringLiteral("保存"));
    QAction undo_action(QIcon(), QStringLiteral("撤销"));
    QAction redo_action(QIcon(), QStringLiteral("重做"));
    RibbonBar::QuickAccessActions qat;
    qat.save = &save_action;
    qat.undo = &undo_action;
    qat.redo = &redo_action;
    bar.set_quick_access_actions(qat);
    pump();
    CHECK(save->isVisible());
    CHECK(save->defaultAction() == &save_action);
    CHECK(undo->defaultAction() == &undo_action);
    CHECK(redo->defaultAction() == &redo_action);

    // Partial injection: a null action hides its button.
    RibbonBar::QuickAccessActions only_save;
    only_save.save = &save_action;
    bar.set_quick_access_actions(only_save);
    pump();
    CHECK(save->isVisible());
    CHECK(!undo->isVisible());
    CHECK(undo->defaultAction() == nullptr);
}

PWB_TEST(command_routing_and_binding) {
    RibbonBar bar;
    bar.resize(1400, 300);
    bar.show();
    pump();
    QString triggered;
    QObject::connect(&bar, &RibbonBar::commandTriggered,
                     [&](const QString& id) { triggered = id; });

    // Unbound placeholder: click emits the intent signal (host routes).
    auto* import = find_button(bar, "ribbonCommand_data.import");
    CHECK(import != nullptr);
    import->click();
    CHECK(triggered == "data.import");

    // Host QAction binding (D4): the button carries the host action and
    // the intent signal does not double-fire.
    QAction host_action(QIcon(), QStringLiteral("导入数据"));
    int host_fires = 0;
    QObject::connect(&host_action, &QAction::triggered,
                     [&] { ++host_fires; });
    bar.set_command_action("data.import", &host_action);
    pump();
    CHECK(import->defaultAction() == &host_action);
    triggered.clear();
    import->click();
    CHECK(host_fires == 1);
    CHECK(triggered.isEmpty());

    // Unbind restores the placeholder behavior.
    bar.set_command_action("data.import", nullptr);
    pump();
    CHECK(import->defaultAction() == nullptr);
    CHECK(import->text() == "导入数据");
    import->click();
    CHECK(triggered == "data.import");
}

PWB_TEST(disabled_reason_channel_applied) {
    RibbonBar bar;
    bar.resize(1400, 300);
    bar.show();
    pump();
    bar.set_command_evaluator(
        [](const std::string& id) -> CommandState {
            if (id == "data.import") return CommandState{false, "未打开工程"};
            return CommandState{};
        });
    auto* import = find_button(bar, "ribbonCommand_data.import");
    CHECK(!import->isEnabled());
    CHECK(import->toolTip().contains("未打开工程"));
    CHECK(find_button(bar, "ribbonCommand_data.scan")->isEnabled());

    // Clearing the evaluator re-enables (fail-open by design, D4).
    bar.set_command_evaluator(nullptr);
    pump();
    CHECK(import->isEnabled());
}

PWB_TEST(search_entry_emits) {
    RibbonBar bar;
    bar.resize(1400, 300);
    bar.show();
    pump();
    int fires = 0;
    QObject::connect(&bar, &RibbonBar::searchRequested, [&] { ++fires; });
    find_button(bar, "ribbonSearch")->click();
    CHECK(fires == 1);
}

PWB_TEST(keyboard_tab_traversal) {
    RibbonBar bar;
    bar.resize(1400, 300);
    bar.show();
    pump();
    // Host wiring: the file menu (enables the file button) + QAT actions.
    QMenu file_menu;
    bar.set_file_menu(&file_menu);
    QAction save_action(QIcon(), QStringLiteral("保存"));
    RibbonBar::QuickAccessActions qat;
    qat.save = &save_action;
    bar.set_quick_access_actions(qat);
    pump();
    // Focus-chain order = Tab traversal order: nav row first, then the
    // active workspace's command band; hidden widgets (unbound QAT,
    // other pages) stay out of the chain walk.
    QStringList order;
    const QWidget* start = find_button(bar, "ribbonFileButton");
    const QWidget* widget = start;
    for (int i = 0; i < 80 && widget != nullptr; ++i) {
        if (widget->isVisible() && widget->isEnabled() &&
            widget->focusPolicy() != Qt::NoFocus) {
            order << widget->objectName();
        }
        widget = widget->nextInFocusChain();
        if (widget == start) break;
    }
    CHECK(order.contains("ribbonTabs"));
    CHECK(order.contains("ribbonSearch"));
    CHECK(order.contains("ribbonCompact"));
    CHECK(order.contains("ribbonCollapse"));
    CHECK(order.contains("ribbonCommand_data.import"));
    CHECK(order.indexOf("ribbonTabs") <
          order.indexOf("ribbonCommand_data.import"));
    // Every visible chrome widget accepts focus.
    for (const char* name : {"ribbonFileButton", "ribbonTabs", "ribbonSearch",
                             "ribbonCompact", "ribbonCollapse"}) {
        auto* chrome = bar.findChild<QWidget*>(name);
        CHECK(chrome != nullptr);
        CHECK(chrome->focusPolicy() != Qt::NoFocus);
        chrome->setFocus();
        CHECK(bar.focusWidget() == chrome);
    }
    find_button(bar, "ribbonCommand_data.import")->setFocus();
    CHECK(bar.focusWidget() == find_button(bar, "ribbonCommand_data.import"));
}

PWB_TEST(context_groups_inject_clear_and_layout_stable) {
    RibbonBar bar;
    bar.resize(1400, 300);
    bar.show();
    bar.set_current_workspace(1);  // 编图 — the context host workspace
    pump();

    // A static group's frame geometry — the R:33 stability reference.
    auto* static_frame = bar.findChild<QFrame*>("ribbonGroup_map_output");
    CHECK(static_frame != nullptr);
    const QRect before = static_frame->geometry();
    CHECK(before.isValid());

    // Inject a context group into ws1 (编图) only — the two-page shell's
    // mode groups ride this exact mechanism. The probe id is NOT in the
    // static table so the lookups address the context instance.
    pwb::ui_ribbon::RibbonGroup spec;
    spec.id = "ctx_annotation";
    spec.label = "标注";
    spec.commands.push_back(pwb::ui_ribbon::RibbonCommand{
        "ctx.probe", "标注", "menu-new.svg",
        pwb::ui_ribbon::CommandKind::Secondary, false});
    bar.set_context_group(1, QStringLiteral("annotation"), spec);
    pump();

    CHECK(bar.context_group_keys(1) == QStringList{"annotation"});
    CHECK(bar.context_group_keys(0).isEmpty());
    // The context command renders as a real button and routes through
    // the SAME intent path as static commands.
    auto* annotate = find_button(bar, "ribbonCommand_ctx.probe");
    CHECK(annotate != nullptr);
    CHECK(annotate->isVisibleTo(&bar));
    QString triggered;
    QObject::connect(&bar, &RibbonBar::commandTriggered,
                     [&](const QString& id) { triggered = id; });
    annotate->click();
    CHECK(triggered == "ctx.probe");

    // Host QAction binding + evaluator apply to context commands too.
    QAction host_action(QIcon(), QStringLiteral("标注"));
    bar.set_command_action("ctx.probe", &host_action);
    pump();
    CHECK(annotate->defaultAction() == &host_action);
    bar.set_command_action("ctx.probe", nullptr);

    // R:33 layout stability: static groups do NOT move when the context
    // group appears (it sits in front of the trailing stretch).
    const QRect during = static_frame->geometry();
    CHECK(during.topLeft() == before.topLeft());

    // Same-key replace: no duplicate, still one group.
    bar.set_context_group(1, QStringLiteral("annotation"), spec);
    pump();
    CHECK(bar.context_group_keys(1) == QStringList{"annotation"});

    // Clear: the group and its separator are gone; static groups still
    // unmoved.
    bar.clear_context_group(1, QStringLiteral("annotation"));
    pump();
    CHECK(bar.context_group_keys(1).isEmpty());
    CHECK(find_button(bar, "ribbonCommand_ctx.probe") == nullptr);
    const QRect after = static_frame->geometry();
    CHECK(after.topLeft() == before.topLeft());

    // Second workspace slot is independent (two-page shell: the only
    // other band is ws0 数据管理).
    bar.set_context_group(0, QStringLiteral("constraint"), spec);
    pump();
    CHECK(bar.context_group_keys(0) == QStringList{"constraint"});
    CHECK(bar.context_group_keys(1).isEmpty());
    bar.clear_context_group(0, QStringLiteral("constraint"));
}

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    app.setStyle(QStringLiteral("Fusion"));
    return ::pwb_test::run_all("ui_ribbon.qt_smoke");
}
