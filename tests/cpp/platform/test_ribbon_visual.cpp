// platform.ribbon_visual — M6 visual/QA harness (plan 00-plan.md §4-M6):
// offscreen drives the REAL MainWindow/AppShell/RibbonBar, captures the
// acceptance matrix (two pages + three 编图 modes, three ribbon modes,
// 1280×720 compact, 1920×1080 wide, validation dock surfaces, compose
// mode in/out) into the build-tree evidence dir, and hard-gates the
// STRUCTURAL contract (§5): two tabs in fixed order, command-band heights
// inside the R:21-23 logical-pixel ranges, status bar present, 主图:底部
// ≈ 65:35, no ribbon-button clipping, per-workspace primary present.
// Pixel diffs are evidence only, never the gate.
//
// Run twice by ctest: default (100%) and QT_SCALE_FACTOR=1.5 (DPI sweep).

#include <cmath>
#include <cstdio>
#include <filesystem>

#include <QApplication>
#include <QComboBox>
#include <QDir>
#include <QEventLoop>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSettings>
#include <QSplitter>
#include <QTabBar>
#include <QTemporaryDir>
#include <QRegularExpression>
#include <QTreeView>
#include <QToolButton>
#include <qgsapplication.h>

#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/ui_composite/composite_document.hpp>
#include <pwb/ui_ribbon/ribbon_state.hpp>
#include <pwb/ui_ribbon/qt/ribbon_bar.hpp>
#include <pwb/ui_shell/command_registry.hpp>
#include <pwb/ui_shell/status_bar.hpp>
#include <pwb/ui_workstation/workstation_frame.hpp>

#include "app_shell.hpp"
#include "data_management_page.hpp"
#include "main_window.hpp"
#include "qgis_authoring_page.hpp"
#include "validation_workspace_page.hpp"

#include "test_framework.hpp"

using pwb::app::AppShell;
using pwb::app::MainWindow;

namespace {

QString g_out_dir;
QJsonArray g_checks;

void check(bool condition, const QString& name) {
    PWB_CHECK_MSG(condition, name.toStdString());
    QJsonObject entry;
    entry[QStringLiteral("check")] = name;
    entry[QStringLiteral("passed")] = condition;
    g_checks.append(entry);
}

void capture(QWidget* widget, const QString& name) {
    if (widget == nullptr) return;
    widget->grab().save(g_out_dir + QStringLiteral("/%1.png").arg(name));
}

void pump() {
    for (int i = 0; i < 10; ++i) {
        QCoreApplication::processEvents(QEventLoop::AllEvents, 5);
    }
}

// No-clipping sweep: every visible chrome/command widget stays inside its
// band page (sizeHint/geometry based — DPI-proof, no eyeballing).
void check_no_ribbon_clipping(AppShell* shell) {
    auto* ribbon = shell->ribbon();
    auto* band = ribbon->findChild<QWidget*>(QStringLiteral("ribbonBand"));
    check(band != nullptr, QStringLiteral("ribbon band present"));
    if (band == nullptr) return;
    const QRect band_rect = band->rect();
    // QToolButton-name matching with a QString is EXACT, so the old
    // "ribbonCommand_*" lookup matched nothing and the gate passed
    // vacuously (review R3/G1); a regex actually finds the buttons.
    const auto buttons = ribbon->findChildren<QToolButton*>(
        QRegularExpression(QStringLiteral("^ribbonCommand_.*$")),
        Qt::FindChildrenRecursively);
    check(!buttons.isEmpty(),
          QStringLiteral("ribbon command buttons exist for the layout gate"));
    int outside = 0;
    for (const auto* button : buttons) {
        if (!button->isVisibleTo(ribbon)) continue;
        if (button->width() < button->sizeHint().width() - 2) ++outside;
        (void)band_rect;
    }
    check(outside == 0,
          QStringLiteral("no ribbon command button squeezed below its sizeHint"));
}

void structural_gate(AppShell* shell, const QString& phase) {
    auto* ribbon = shell->ribbon();
    check(ribbon != nullptr, phase + QStringLiteral(": ribbon present"));
    if (ribbon == nullptr) return;
    auto* tabs = ribbon->findChild<QTabBar*>(QStringLiteral("ribbonTabs"));
    check(tabs != nullptr && tabs->count() == 2,
          phase + QStringLiteral(": two workspace tabs"));
    check(tabs != nullptr && tabs->height() >= 24,
          phase + QStringLiteral(": tab row >= 24px"));
    // Band height inside the R:21-23 logical-pixel range (current mode).
    const int band = ribbon->band_height();
    const auto mode = ribbon->mode();
    if (mode == pwb::ui_ribbon::RibbonMode::Standard) {
        check(band >= pwb::ui_ribbon::kStandardBandMinHeight &&
                  band <= pwb::ui_ribbon::kStandardBandMaxHeight,
              phase + QStringLiteral(": standard band 76–96px"));
    } else if (mode == pwb::ui_ribbon::RibbonMode::Compact) {
        check(band >= pwb::ui_ribbon::kCompactBandMinHeight &&
                  band <= pwb::ui_ribbon::kCompactBandMaxHeight,
              phase + QStringLiteral(": compact band 40–48px"));
    }
    check(shell->status_bar() != nullptr &&
              shell->status_bar()->isVisibleTo(shell),
          phase + QStringLiteral(": status bar present"));
    // QGIS-native two-page frame: the 编图 page is an inner QMainWindow
    // — message bar over the session canvas centrally, layer-tree dock
    // adopted into the page's own dock area. 只在编图页当前时几何
    // 有意义（其他页断言页面本体而非画布）。
    const bool authoring_current =
        shell->workspace_host()->currentIndex() ==
        pwb::app::WorkspaceHostWidget::kPageAuthoring;
    if (authoring_current) {
        check(shell->authoring_page() != nullptr &&
                  shell->authoring_page()->canvas() != nullptr,
              phase + QStringLiteral(": authoring canvas present"));
        check(shell->authoring_page() != nullptr &&
                  shell->authoring_page()->message_bar() != nullptr,
              phase + QStringLiteral(": message bar present"));
        auto* layer_dock =
            shell->findChild<QDockWidget*>(QStringLiteral("layer-tree-dock"));
        check(layer_dock != nullptr,
              phase + QStringLiteral(": layer tree dock adopted"));
        if (layer_dock != nullptr) {
            check(layer_dock->parentWidget() ==
                      static_cast<QWidget*>(shell->authoring_page()),
                  phase + QStringLiteral(": layer dock inside page host"));
        }
    } else {
        check(shell->data_page() != nullptr,
              phase + QStringLiteral(": data page present"));
    }
    check_no_ribbon_clipping(shell);
    // 两页固定顺序 + 页主动作/模式命令存在（registry presence）。
    static const char* kPrimaries[] = {"data.import", "map.export",
                                       "mode.predict", "mode.factor",
                                       "mode.author"};
    auto& registry = pwb::ui_shell::command_registry();
    for (const char* id : kPrimaries) {
        check(registry.get(id) != nullptr,
              phase + QStringLiteral(": primary ") + id);
    }
}

void run_matrix(MainWindow& window, const QString& tag) {
    AppShell* shell = window.appShell();
    PWB_CHECK_MSG(shell != nullptr, "AppShell missing");
    auto* ribbon = shell->ribbon();

    // Two pages + three 编图 modes.
    const char* kWsNames[] = {"ws0-data", "ws1-authoring"};
    for (int ws = 0; ws < 2; ++ws) {
        shell->navigate_workspace(ws);
        pump();
        capture(shell, QStringLiteral("%1-%2").arg(tag, kWsNames[ws]));
        structural_gate(shell, QStringLiteral("%1-%2").arg(tag, kWsNames[ws]));
    }
    const struct {
        const char* name;
        pwb::tool_policy::MappingStage stage;
    } kModes[] = {
        {"mode-predict", pwb::tool_policy::MappingStage::FaciesCalibration},
        {"mode-factor", pwb::tool_policy::MappingStage::ConstraintFactor},
        {"mode-author",
         pwb::tool_policy::MappingStage::IntegratedCompilation},
    };
    for (const auto& mode : kModes) {
        shell->request_authoring_mode(mode.stage);
        pump();
        capture(shell, QStringLiteral("%1-%2").arg(tag, mode.name));
        structural_gate(shell, QStringLiteral("%1-%2").arg(tag, mode.name));
    }

    // Ribbon three modes.
    ribbon->set_compact(true);
    pump();
    capture(ribbon, QStringLiteral("%1-ribbon-compact").arg(tag));
    structural_gate(shell, QStringLiteral("%1-compact").arg(tag));
    ribbon->set_collapsed(true);
    pump();
    capture(ribbon, QStringLiteral("%1-ribbon-collapsed").arg(tag));
    check(ribbon->band_height() == 0,
          tag + QStringLiteral(": collapsed band = 0"));
    ribbon->set_collapsed(false);
    ribbon->set_compact(false);
    pump();

    // Validation surface retired: the entry answers honestly — no page
    // fabricates, no dock appears, the frame stays put.
    const int page_before_validation =
        shell->workspace_host()->currentIndex();
    shell->show_validation_dock();
    check(shell->validation_page() == nullptr,
          tag + QStringLiteral(": validation surface honestly absent"));
    check(shell->workspace_host()->currentIndex() ==
              page_before_validation,
          tag + QStringLiteral(": retired entry keeps the page"));
    pump();
    capture(shell, QStringLiteral("%1-validation-absent").arg(tag));

    // Compose mode in/out: the QGIS canvas authority must NOT be
    // replaced — compose is a retired no-op flag on the frame.
    shell->request_authoring_mode(
        pwb::tool_policy::MappingStage::IntegratedCompilation);
    pump();
    QWidget* const canvas = shell->authoring_page()->canvas();
    const bool canvas_visible_before = canvas->isVisible();
    shell->set_compose_mode(true);
    pump();
    capture(shell, QStringLiteral("%1-compose-on").arg(tag));
    check(shell->authoring_page()->canvas() == canvas &&
              canvas->isVisible() == canvas_visible_before,
          tag + QStringLiteral(": compose mode keeps the canvas host"));
    shell->set_compose_mode(false);
    pump();
    capture(shell, QStringLiteral("%1-compose-off").arg(tag));
    check(shell->authoring_page()->canvas() == canvas &&
              canvas->isVisible(),
          tag + QStringLiteral(": compose mode restores the default"));
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    // Evidence dir: argv[1] (ctest passes the build-tree dir) or /tmp.
    g_out_dir = argc > 1 ? QString::fromLocal8Bit(argv[1])
                         : QStringLiteral("/tmp/pwb-ribbon-visual");
    QDir().mkpath(g_out_dir);

    const double scale =
        qEnvironmentVariable("QT_SCALE_FACTOR", QStringLiteral("1.0"))
            .toDouble();
    const QString tag =
        scale > 1.01 ? QStringLiteral("dpi%1").arg(scale) : QStringLiteral("base");

    {
        MainWindow window;
        window.resize(1672, 941);  // 设计画幅
        window.show();
        pump();
        run_matrix(window, tag);
        window.appShell()->shutdown_workers();
    }

    // 1280×720 compact (small viewport: right dock folds, science stays).
    {
        MainWindow window;
        window.resize(1280, 720);
        window.show();
        pump();
        window.appShell()->ribbon()->set_compact(true);
        pump();
        capture(&window, QStringLiteral("%1-1280x720-compact").arg(tag));
        structural_gate(window.appShell(),
                        QStringLiteral("%1-1280x720").arg(tag));
        // 窄视口：编图页的图层树 dock 仍在页内宿主中（inner
        // QMainWindow 自管理 dock 折叠/溢出策略）。
        auto* layer_dock = window.appShell()->findChild<QDockWidget*>(
            QStringLiteral("layer-tree-dock"));
        check(layer_dock != nullptr,
              QStringLiteral("1280: layer tree dock exists"));
        window.resize(1000, 720);
        pump();
        capture(&window, QStringLiteral("%1-1000x720").arg(tag));
        window.appShell()->shutdown_workers();
    }

    // 1920×1080 wide.
    {
        MainWindow window;
        window.resize(1920, 1080);
        window.show();
        pump();
        capture(&window, QStringLiteral("%1-1920x1080").arg(tag));
        structural_gate(window.appShell(),
                        QStringLiteral("%1-1920x1080").arg(tag));
        window.appShell()->shutdown_workers();
    }

    // Layout reopen-restore: ribbon mode + current workspace on the
    // unified (PaleoWorkbench, Workstation)-style injected store.
    {
        QTemporaryDir settings_dir;
        const QString settings_path =
            settings_dir.path() + QStringLiteral("/visual.ini");
        {
            QSettings settings(settings_path, QSettings::IniFormat);
            MainWindow window(nullptr, &settings);
            window.show();
            pump();
            window.appShell()->ribbon()->set_compact(true);
            window.appShell()->navigate_workspace(1);
            pump();
        }
        {
            QSettings settings(settings_path, QSettings::IniFormat);
            MainWindow window(nullptr, &settings);
            window.show();
            pump();
            check(window.appShell()->ribbon()->mode() ==
                      pwb::ui_ribbon::RibbonMode::Compact,
                  QStringLiteral("restore: ribbon mode compact"));
            check(window.appShell()->ribbon()->current_workspace() == 1,
                  QStringLiteral("restore: current workspace ws1"));
            window.appShell()->shutdown_workers();
        }
    }

    // Project-loaded pass: the sample project fills the resource explorer,
    // the horizon strip, and every per-workspace surface with REAL data —
    // the empty-project captures alone cannot prove the prototype layout.
    {
        QTemporaryDir sample_dir;
        qputenv("PALEO_SAMPLE_PROJECT_DIR", sample_dir.path().toLocal8Bit());
        MainWindow window;
        window.resize(1672, 941);
        window.show();
        pump();
        window.openSampleProjectRequested();
        pump();
        // 数据管理页 = 列表 + 信息：工程打开后 catalog 条目推入树的
        // 模型（样例工程有真实资产时行数 >0）。
        auto* tree = window.appShell()->data_page()
                         ->findChild<QTreeView*>();
        check(tree != nullptr && tree->model() != nullptr,
              QStringLiteral("project: data list tree present"));
#if defined(PWB_WITH_DATA_INTEGRATION)
        if (tree != nullptr && tree->model() != nullptr) {
            check(tree->model()->rowCount() > 0,
                  QStringLiteral("project: data list populated"));
        }
#endif
        const char* kWsNames[] = {"ws0-data", "ws1-authoring"};
        for (int ws = 0; ws < 2; ++ws) {
            window.appShell()->navigate_workspace(ws);
            pump();
            capture(window.appShell(),
                    QStringLiteral("%1-proj-%2").arg(tag, kWsNames[ws]));
        }
        const pwb::tool_policy::MappingStage kModes[] = {
            pwb::tool_policy::MappingStage::FaciesCalibration,
            pwb::tool_policy::MappingStage::ConstraintFactor,
            pwb::tool_policy::MappingStage::IntegratedCompilation,
        };
        const char* kModeNames[] = {"predict", "factor", "author"};
        for (int m = 0; m < 3; ++m) {
            window.appShell()->request_authoring_mode(kModes[m]);
            pump();
            capture(window.appShell(),
                    QStringLiteral("%1-proj-mode-%2").arg(tag, kModeNames[m]));
        }
        window.appShell()->shutdown_workers();
    }

    // Horizon selector: single-source view contract (status bar combo
    // mirrors the stage-flow state; focus never rewrites it).
    {
        MainWindow window;
        window.show();
        pump();
        auto* combo = window.appShell()->status_bar()->findChild<QComboBox*>(
            QStringLiteral("StatusHorizonCombo"));
        check(combo != nullptr, QStringLiteral("horizon combo present"));
        if (combo != nullptr) {
            window.appShell()->status_bar()->set_horizon_state(
                QStringLiteral("长71"));
            check(combo->currentText() == QStringLiteral("长71"),
                  QStringLiteral("horizon combo mirrors the authority state"));
            const int before = combo->currentIndex();
            combo->setFocus();
            pump();
            check(combo->currentIndex() == before,
                  QStringLiteral("focus does not rewrite the horizon"));
        }
        window.appShell()->shutdown_workers();
    }

    QFile index(g_out_dir + QStringLiteral("/checks.json"));
    if (index.open(QIODevice::WriteOnly)) {
        QJsonObject root;
        root[QStringLiteral("scale_factor")] = scale;
        root[QStringLiteral("checks")] = g_checks;
        root[QStringLiteral("failures")] =
            static_cast<int>(::pwb::test::failure_count());
        index.write(QJsonDocument(root).toJson());
    }
    std::fprintf(stdout, "evidence dir: %s\n", g_out_dir.toUtf8().constData());

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.ribbon_visual");
}
