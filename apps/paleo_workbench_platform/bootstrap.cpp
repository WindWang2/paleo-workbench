#include "bootstrap.hpp"

#include "app_context.hpp"
#include "diagnostics.hpp"
#include "main_window.hpp"
#include "self_check.hpp"

#include <QCommandLineParser>
#include <QTextStream>

#include <string_view>

#include <qgsapplication.h>

#include <pwb/platform_services/diagnostics_report.hpp>
#include <pwb/platform_services/qt_session_policy.hpp>
#include <pwb/platform_services/settings_service.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/qgis_processing/provider.hpp>
#include <pwb/qgis_processing/runner.hpp>

#include <exception>

namespace pwb::app {
namespace {

enum class RunMode { Interactive, SelfCheck, Capabilities, Diagnostics };

struct StartupFatal {
    QString subsystem;
    QString message;
};

RunMode parse_mode(const QCommandLineParser& parser) {
    if (parser.isSet(QStringLiteral("headless-self-check"))
        || parser.isSet(QStringLiteral("self-check"))) {
        return RunMode::SelfCheck;
    }
    if (parser.isSet(QStringLiteral("capabilities"))) return RunMode::Capabilities;
    if (parser.isSet(QStringLiteral("diagnostics"))) return RunMode::Diagnostics;
    return RunMode::Interactive;
}

int run_capabilities(QTextStream& out) {
    const diagnostics::EnvironmentReport env = diagnostics::probe_environment();
    AppContext context;  // runtime service probes (kernel registrations, ...)
    const QVector<AppContext::RuntimeCapability> caps = context.capabilities();
    out << "capability build runtime class title\n";
    for (const auto& cap : caps) {
        QString cls;
        switch (cap.cls) {
        case capabilities::BuildClass::hard: cls = QStringLiteral("hard"); break;
        case capabilities::BuildClass::optional: cls = QStringLiteral("optional"); break;
        case capabilities::BuildClass::kernel: cls = QStringLiteral("kernel"); break;
        }
        out << "capability " << cap.id
            << (cap.in_closure ? QStringLiteral(" linked") : QStringLiteral(" absent"))
            << (cap.runtime_ok ? QStringLiteral(" runtime-ok")
                               : QStringLiteral(" runtime-degraded"))
            << QStringLiteral(" ") << cls
            << QStringLiteral(" ") << cap.title
            << QStringLiteral(" — ") << cap.detail << "\n";
    }
    out << "env python-runtime " << env.python_runtime_state << "\n";
    // Phase 4: the algorithm inventory the registry (provider "paleo")
    // exposes — the E2E/batch capability outlet. Idempotent install: the
    // capabilities mode has no JobCenter, so make sure the provider is up
    // before listing (AppContext's runner already did it in full builds).
    pwb::qgis_processing::install_paleo_provider();
    const QStringList algorithm_ids = pwb::qgis_processing::paleo_algorithm_ids();
    for (const QString& id : algorithm_ids) {
        out << "algorithm " << id << "\n";
    }
    out << "algorithm-count " << algorithm_ids.size() << "\n";
    out.flush();
    return 0;
}

int run_diagnostics(QTextStream& out) {
    const diagnostics::EnvironmentReport env = diagnostics::probe_environment();
    out << diagnostics::render_report(env, diagnostics::collected_tail());
    out.flush();
    return 0;
}

int run_self_check(QTextStream& out) {
    // (The offscreen fallback for --headless-self-check already ran before
    // QgsApplication constructed; nothing platform-related can change now.)
    const QVector<SelfCheck::Result> results =
        SelfCheck::run(QStringLiteral(PWB_SOURCE_DIR));
    out << SelfCheck::render(results);
    out.flush();
    for (const SelfCheck::Result& result : results) {
        if (!result.passed) return 1;
    }
    return 0;
}

int run_interactive() {
    AppContext context;
    MainWindow window(context);
    window.show();
    const int code = QApplication::exec();
    // Window/context are stack objects: window destructs first (its
    // teardown closes the session while the canvas is alive), then the
    // context finishes service shutdown. QgisRuntime is released by the
    // caller after this returns.
    return code;
}

int dispatch(RunMode mode) {
    QTextStream out(stdout);
    switch (mode) {
    case RunMode::Capabilities: return run_capabilities(out);
    case RunMode::Diagnostics: return run_diagnostics(out);
    case RunMode::SelfCheck: return run_self_check(out);
    case RunMode::Interactive: return run_interactive();
    }
    return 2;
}

}  // namespace

int Bootstrap::run(int argc, char** argv) {
    // The Qt platform plugin is chosen when QGuiApplication constructs, so
    // the headless fallback must be in the environment BEFORE that — the
    // QCommandLineParser below runs too late (bootstrap.hpp contract).
    bool headless_flag = false;
    for (int i = 1; i < argc; ++i) {
        if (std::string_view(argv[i]) == "--headless-self-check") {
            headless_flag = true;
            break;
        }
    }
    if (headless_flag && qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM")) {
        qputenv("QT_QPA_PLATFORM", "offscreen");
    }

    diagnostics::install_message_collector();

    // Session policy must run before the application object exists
    // (qt_platform.py contract): EGL pin, xcb clear, fractional-scale guard.
    pwb::platform_services::configure_qt_platform_for_session();
    pwb::platform_services::apply_wayland_fractional_scale_guard();

    // QgsApplication must be THE application object (QGIS 4.x contract);
    // GUI-enabled so the interactive shell and offscreen self-checks share
    // one code path.
    QgsApplication app(argc, argv, true);
    QApplication::setApplicationName(QStringLiteral("pwb-platform"));
    QApplication::setOrganizationName(QStringLiteral("paleo-workbench"));
    QApplication::setApplicationVersion(QString::fromStdString(
        pwb::platform_services::version_line()));

    QCommandLineParser parser;
    parser.setApplicationDescription(
        QStringLiteral("Paleo Workbench native C++ platform"));
    parser.addHelpOption();
    parser.addVersionOption();
    parser.addOption({QStringLiteral("self-check"),
                      QStringLiteral("headless product self-check battery "
                                     "(fixtures + kernels + render + lifecycle)")});
    parser.addOption({QStringLiteral("headless-self-check"),
                      QStringLiteral("like --self-check, forces the offscreen "
                                     "Qt platform when none is set")});
    parser.addOption({QStringLiteral("capabilities"),
                      QStringLiteral("print the build+runtime capability "
                                     "matrix and exit")});
    parser.addOption({QStringLiteral("diagnostics"),
                      QStringLiteral("print the product diagnostics report "
                                     "(versions/providers/probes/log tail)")});
    parser.process(app);

    const RunMode mode = parse_mode(parser);

    // The unified settings identity predates the native shell: migrate the
    // legacy (WorkstationV3 / paleo-workbench) stores on interactive
    // startups — idempotent, cheap (ui/layout_persistence.py contract).
    // R2-26: read-only probe modes (--diagnostics / --capabilities) must
    // not touch the user's store; two concurrently started probes used to
    // interleave whole-file QSettings syncs and race the migration.
    const bool probe_mode = mode == RunMode::Diagnostics
                            || mode == RunMode::Capabilities
                            || mode == RunMode::SelfCheck;
    if (!probe_mode) {
        pwb::platform_services::migrate_legacy_settings();
    }

    // Single QGIS init for the process; failures are a startup fatal with
    // a structured report (never a silent half-initialized runtime).
    try {
        pwb::qgis::QgisRuntime::acquire();
    } catch (const std::exception& error) {
        diagnostics::critical(diagnostics::LogArea::Qgis,
                              QStringLiteral("QgisRuntime::acquire threw: %1")
                                  .arg(QString::fromUtf8(error.what())));
        QTextStream(stderr) << "FATAL startup qgis: " << error.what() << "\n"
                            << diagnostics::render_report(
                                   diagnostics::probe_environment(),
                                   diagnostics::collected_tail());
        return 2;
    } catch (...) {
        diagnostics::critical(diagnostics::LogArea::Qgis,
                              QStringLiteral("QgisRuntime::acquire threw an "
                                             "unknown exception"));
        return 2;
    }

    int exit_code = 2;
    try {
        exit_code = dispatch(mode);
    } catch (const std::exception& error) {
        // Top-level exception gate: report with subsystem attribution and
        // the collected log tail; never let it cross exec()/main().
        diagnostics::critical(diagnostics::LogArea::Startup,
                              QStringLiteral("unhandled exception: %1")
                                  .arg(QString::fromUtf8(error.what())));
        QTextStream(stderr) << "FATAL runtime exception: " << error.what() << "\n"
                            << diagnostics::render_report(
                                   diagnostics::probe_environment(),
                                   diagnostics::collected_tail());
        exit_code = 2;
    } catch (...) {
        diagnostics::critical(diagnostics::LogArea::Startup,
                              QStringLiteral("unhandled unknown exception"));
        QTextStream(stderr) << "FATAL runtime exception (unknown type)\n";
        exit_code = 2;
    }

    pwb::qgis::QgisRuntime::release();
    return exit_code;
}

}  // namespace pwb::app
