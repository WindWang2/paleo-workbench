// UI-01 — Qt widget smoke test (offscreen): instantiate every ported
// widget once and drive the primary entry points. Complements the oracle
// replay (which covers the Qt-free cores) by proving the Qt shells
// construct and respond under QT_QPA_PLATFORM=offscreen.

#include <QApplication>
#include <QEvent>
#include <QLineEdit>
#include <QSplitter>
#include <QWidget>

#include <cstdio>
#include <map>
#include <string>

#include <pwb/ui_shell/adaptive_page_stack.hpp>
#include <pwb/ui_shell/command_palette.hpp>
#include <pwb/ui_shell/command_registry.hpp>
#include <pwb/ui_shell/crs_guidance.hpp>
#include <pwb/ui_shell/dock_manager.hpp>
#include <pwb/ui_shell/float_controller.hpp>
#include <pwb/ui_shell/floating_panel.hpp>
#include <pwb/ui_shell/layout_persistence.hpp>
#include <pwb/ui_shell/map_status_bar.hpp>
#include <pwb/ui_shell/page_placeholder.hpp>
#include <pwb/ui_shell/screen_inventory.hpp>
#include <pwb/ui_shell/shortcut_registry.hpp>
#include <pwb/ui_shell/status_bar.hpp>
#include <pwb/ui_shell/style_registry.hpp>

using namespace pwb::ui_shell;

namespace {

int failures = 0;

void check(bool condition, const char* what) {
    if (!condition) {
        ++failures;
        std::fprintf(stderr, "FAIL %s\n", what);
    } else {
        std::fprintf(stderr, "PASS %s\n", what);
    }
}

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);

    // --- status bar ---
    StatusBar status;
    status.set_project_name(QStringLiteral("测试工程"));
    check(status.findChild<QLabel*>() != nullptr, "status constructs");
    status.set_workbench_context(QStringLiteral("编图 · 编辑中"));
    status.update_context(QStringLiteral("X: 1  Y: 2"), QString(), QString(),
                          QStringLiteral("5000"));
    status.update_engine_status(QStringLiteral("CPU · Native C++"));

    // --- map status bar ---
    MapStatusBar map_status;
    map_status.resize(1200, 24);
    map_status.update_coordinate({123.456789, 39.5},
                                 QStringLiteral("EPSG:4326"));
    map_status.update_scale(25000.0);
    map_status.set_measure(QStringLiteral("1.2 km"));
    MapStatusFacts facts;
    facts.crs = std::string("EPSG:4326");
    facts.layer_crs = std::string("EPSG:4490");
    facts.crs_mismatch = true;
    facts.snapping_enabled = true;
    facts.snapping_tolerance_px = 12.0;
    facts.snapping_modes =
        std::vector<std::string>{"顶点", "线段"};
    facts.topology_enabled = true;
    facts.topology_error_count = 3;
    facts.editing = true;
    facts.dirty = true;
    facts.layer_name = std::string("构造线");
    facts.edit_gate_open = true;
    facts.save_blocked = true;
    map_status.apply_context(facts);
    map_status.set_snap_match(true, QStringLiteral("顶点"),
                              QStringLiteral("layer-a"), 0.5);
    // CRS mismatch warning must surface as text glyph, not color only.
    check(map_status.findChildren<QLabel*>().size() >= 9,
          "map_status labels exist");

    check(short_crs_name(QStringLiteral("+proj=tmerc +units=m"))
              .contains(QStringLiteral("本地坐标")),
          "short_crs_name +proj fold");
    check(short_crs_name(QStringLiteral("EPSG:4490")) ==
              QStringLiteral("EPSG:4490"),
          "short_crs_name auth id");
    check(format_scale(25000.0) == QStringLiteral("1:25,000"),
          "format_scale thousands");
    check(format_scale(0.0) == QStringLiteral("1:—"),
          "format_scale honest unknown");

    // --- floating panel + controller ---
    QWidget shell_host;
    shell_host.resize(800, 600);
    auto* splitter = new QSplitter(&shell_host);
    auto* docked = new QWidget(splitter);
    splitter->addWidget(docked);

    FloatController controller(
        [](const std::string&) -> QWidget* { return nullptr; },
        nullptr,  // persistence off — hermetic
        nullptr, &shell_host);
    check(controller.float_panel("page:panel", docked),
          "float_panel floats");
    check(controller.is_floating("page:panel"), "is_floating");
    FloatingPanel* window = controller.floating_panel("page:panel");
    check(window != nullptr, "floating window exists");
    check(controller.dock_panel("page:panel"), "dock_panel restores");
    check(!controller.is_floating("page:panel"), "docked again");

    // --- #1389: floatable_panel_entries callbacks must survive target
    // destruction (raw-pointer captures dangled into deleteLater'd objects).
    {
        // Case A — floating-window capture: dock_panel() deleteLater()s the
        // FloatingPanel; after DeferredDelete runs the captured pointer is
        // dead and set_visible must no-op instead of dereferencing it.
        auto* widget_a = new QWidget(splitter);
        const std::map<std::string, QWidget*> panels_a{{"page:a", widget_a}};
        controller.float_panel("page:a", widget_a);
        const auto entries_a = floatable_panel_entries(controller, panels_a);
        check(!entries_a.empty(), "entries built for floating panel");
        controller.dock_panel("page:a");
        QApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);
        entries_a[0].set_visible(false);  // dead window — must no-op
        entries_a[0].toggle_float();      // controller+widget alive — refloat
        controller.dock_panel("page:a");
        QApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);

        // Case B — docked-widget capture: the widget itself is gone.
        auto* widget_b = new QWidget(splitter);
        const std::map<std::string, QWidget*> panels_b{{"page:b", widget_b}};
        const auto entries_b = floatable_panel_entries(controller, panels_b);
        check(!entries_b.empty(), "entries built for docked widget");
        delete widget_b;
        entries_b[0].set_visible(true);   // dead widget — must no-op
        entries_b[0].toggle_float();      // guarded controller, dead widget
        check(true, "entries survive destroyed panel/widget");
    }

    // --- command palette ---
    CommandRegistry registry;
    registry.register_command(CommandSpec{
        .id = "nav:mapping",
        .label = "编图",
        .hint = "hub",
        .callback = [] {},
    });
    CommandPalette palette(&shell_host, registry);
    palette.popup();
    palette.dismiss();
    check(true, "palette popup/dismiss");

    // --- adaptive page stack ---
    AdaptivePageStack stack;
    auto* narrow = new QWidget;
    narrow->setMinimumSize(200, 100);
    auto* wide = new QWidget;
    wide->setMinimumSize(900, 100);
    stack.addWidget(narrow);
    stack.addWidget(wide);
    stack.setCurrentWidget(narrow);
    check(stack.minimumSizeHint().width() <= 300,
          "adaptive stack tracks current page");
    stack.setCurrentWidget(wide);
    check(stack.minimumSizeHint().width() >= 900,
          "adaptive stack follows switch");

    // --- page placeholder + misc ---
    PagePlaceholder placeholder(QStringLiteral("井"));
    check(placeholder.findChild<QLabel*>() != nullptr,
          "placeholder constructs");

    check(screen_inventory().hubs.size() == 5, "screen inventory hubs");
    check(dock_manager().panel_title("workstation:inspector") ==
              std::string("检查器"),
          "dock manager seeded");

    // --- shortcut registry (QShortcut needs a widget parent) ---
    QWidget shortcut_host;
    bool fired = false;
    shortcut_registry().register_shortcut(
        &shortcut_host, ShortcutSpec{"ui.test", "Ctrl+T", "测试"},
        [&fired] { fired = true; });
    check(shortcut_registry().get("ui.test") != nullptr,
          "shortcut registered");
    shortcut_registry().unregister("ui.test");

    // --- style registry ---
    StyleRegistry styles;
    QLabel styled;
    styles.bind(&styled, [] { return QStringLiteral("color: red;"); });
    check(styled.styleSheet().contains(QStringLiteral("red")),
          "style bind applies");

    if (failures == 0) {
        std::fprintf(stderr, "qt_widgets_smoke: all checks passed\n");
        return 0;
    }
    std::fprintf(stderr, "qt_widgets_smoke: %d failure(s)\n", failures);
    return 1;
}
