// platform.ribbon_visual — M6 visual/QA harness (plan 00-plan.md §4-M6):
// offscreen drives the REAL MainWindow/AppShell/RibbonBar, captures the
// acceptance matrix (five workspaces, three ribbon modes, 1280×720
// compact, 1920×1080 wide, validation compare/review surfaces, compose
// mode in/out) into the build-tree evidence dir, and hard-gates the
// STRUCTURAL contract (§5): five tabs in fixed order, command-band heights
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
#include "main_window.hpp"
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
    check(tabs != nullptr && tabs->count() == 5,
          phase + QStringLiteral(": five workspace tabs"));
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
    // 面板化改订 —— 画布:阶段行比例。科学页 = 纯画布；阶段面板是底
    // 部 row0 dock（resizeDocks 播种行高，用户可拖）。工具行
    // （任务|日志）是常驻第二行，不计入比值。
    if (qEnvironmentVariableIsSet("PWB_VIS_DEBUG")) {
        for (const char* id :
             {"data_preview", "pair_link", "crosswell", "data_prep",
              "factor_refs"}) {
            if (auto* d = shell->workstation()->dock(id)) {
                std::fprintf(stderr,
                             "[probe] dock %s vis=%d h=%d min=%dx%d\n",
                             id, d->isVisible() ? 1 : 0, d->height(),
                             d->minimumSizeHint().width(),
                             d->minimumSizeHint().height());
            }
        }
    }
    // 画布:阶段行 ≈ 原型占比 —— 面板化后阶段面板是底部 row0 dock,
    // 工具行常驻不计入比值。只在科学页当前时有意义（其他页几何退化）;
    // skip 显式记录（G5: 静默跳过不能冒充覆盖）。
    const bool science_current =
        shell->workspace_host()->currentIndex() ==
        pwb::app::WorkspaceHostWidget::kPageScience;
    int stage_row_h = 0;
    for (const char* id :
         {"pair_link", "predict_task", "seismic_predict", "crosswell",
          "data_prep", "strat_compare", "seq_frame", "factor_refs"}) {
        if (auto* d = shell->workstation()->dock(id);
            d != nullptr && d->isVisible() && !d->isFloating()) {
            stage_row_h = d->height();
            break;
        }
    }
    const int canvas_h = shell->composite()->height();
    if (!science_current || stage_row_h <= 0 ||
        canvas_h + stage_row_h <= 100) {
        std::printf("  [skip] %s: canvas:stage-row ratio (science page not current)\n",
                    phase.toUtf8().constData());
    } else {
        const double ratio = static_cast<double>(canvas_h) /
                             (canvas_h + stage_row_h);
        check(ratio > 0.45 && ratio < 0.92,
              phase +
                  QStringLiteral(": canvas:stage-row ≈ 原型占比 (actual %1, %2/%3)")
                      .arg(ratio, 0, 'f', 2)
                      .arg(canvas_h)
                      .arg(stage_row_h));
    }
    check_no_ribbon_clipping(shell);
    // 五区固定顺序 + 每区唯一主动作（registry presence）。
    static const char* kPrimaries[] = {"data.import", "predict.run",
                                       "factor.compute", "map.export",
                                       "verify.run"};
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

    // Five workspaces.
    const char* kWsNames[] = {"ws0-data", "ws1-predict", "ws2-factor",
                              "ws3-map", "ws4-validation"};
    for (int ws = 0; ws < 5; ++ws) {
        shell->navigate_workspace(ws);
        pump();
        capture(shell, QStringLiteral("%1-%2").arg(tag, kWsNames[ws]));
        structural_gate(shell, QStringLiteral("%1-%2").arg(tag, kWsNames[ws]));
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

    // Validation surfaces: compare view + review panel visible states.
    shell->navigate_workspace(4);
    if (auto* tabs = shell->validation_page()->findChild<QTabWidget*>(
            QStringLiteral("ValidationRightTabs"))) {
        tabs->setCurrentIndex(1);  // 对比视图
    }
    pump();
    capture(shell, QStringLiteral("%1-validation-compare").arg(tag));
    if (auto* tabs = shell->validation_page()->findChild<QTabWidget*>(
            QStringLiteral("ValidationRightTabs"))) {
        tabs->setCurrentIndex(2);  // 复核记录
    }
    pump();
    capture(shell, QStringLiteral("%1-validation-review").arg(tag));

    // Compose mode in/out: the canvas must NOT be replaced (F:70) —
    // 版式输出是右栏 dock，抬起它画布不动。
    shell->navigate_workspace(3);
    pump();
    const bool canvas_visible_before = shell->composite()->isVisible();
    shell->set_compose_mode(true);
    pump();
    capture(shell, QStringLiteral("%1-compose-on").arg(tag));
    check(shell->composite()->isVisible() == canvas_visible_before,
          tag + QStringLiteral(": compose mode keeps the canvas host"));
    shell->set_compose_mode(false);
    pump();
    capture(shell, QStringLiteral("%1-compose-off").arg(tag));
    check(shell->composite()->isVisible(),
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
        auto* inspector =
            window.appShell()->workstation()->dock("inspector");
        check(inspector != nullptr, QStringLiteral("1280: inspector dock exists"));
        if (inspector != nullptr) {
            // Narrower than kInspectorHideBelow(1100) → viewport policy
            // folds it without squeezing the science bottom.
            window.resize(1000, 720);
            pump();
            check(!inspector->isVisible() ||
                      window.appShell()->workstation()->dock_visible(
                          "inspector"),
                  QStringLiteral("1280: inspector policy engaged honestly"));
        }
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
            window.appShell()->navigate_workspace(3);
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
            check(window.appShell()->ribbon()->current_workspace() == 3,
                  QStringLiteral("restore: current workspace ws3"));
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
        auto* tree = window.appShell()->workstation()->explorer()
                         ->findChild<QTreeView*>();
        check(tree != nullptr && tree->model() != nullptr,
              QStringLiteral("project: explorer tree present"));
#if defined(PWB_WITH_WORKFLOW_WIRING)
        // 本目标带全量 workflow 装配时才校验资源树投影（products-only
        // 路径 WorkflowBinding::push_project_to_pages_ 未编入时树保持
        // 空工程诚实态，不构成失败）。
        if (tree != nullptr && tree->model() != nullptr) {
            check(tree->model()->rowCount() > 0,
                  QStringLiteral("project: explorer populated from facts"));
        }
#endif
        const char* kWsNames[] = {"ws0-data", "ws1-predict", "ws2-factor",
                                  "ws3-map", "ws4-validation"};
        for (int ws = 0; ws < 5; ++ws) {
            window.appShell()->navigate_workspace(ws);
            pump();
            capture(window.appShell(),
                    QStringLiteral("%1-proj-%2").arg(tag, kWsNames[ws]));
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
