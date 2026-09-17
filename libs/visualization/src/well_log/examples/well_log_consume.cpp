// Standalone consumer of the production well-log viewer stack (no test
// harness): loads a real LAS through the public header + real WLE SDK and
// saves a rendered PNG. This is the proof that Pwb::VisualizationWellLog is
// linkable and useful with tests completely off (v3-contracts.md §3).
//
//   pwb-well-log-consume <path-to-A1.Las> [output.png]

#include <pwb/viz/well_log_host_widget.hpp>

#include <QApplication>
#include <QCommandLineParser>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QImage>
#include <QThread>

#include <welllog/qtwidgets/well_log_view.hpp>

#include <cstdio>
#include <functional>

namespace {

bool process_until(const std::function<bool()>& condition, int timeout_ms) {
    QElapsedTimer timer;
    timer.start();
    while (!condition()) {
        QApplication::processEvents(QEventLoop::AllEvents, 20);
        if (timer.elapsed() > timeout_ms) {
            return condition();
        }
        QThread::msleep(10);
    }
    return true;
}

} // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    QCommandLineParser parser;
    parser.addHelpOption();
    parser.addPositionalArgument("las", "LAS file to load (e.g. A1.Las)");
    parser.addPositionalArgument("png", "rendered output image", "[output.png]");
    parser.process(app);
    if (parser.positionalArguments().isEmpty()) {
        parser.showHelp(2);
    }
    const QString las_path = parser.positionalArguments().constFirst();
    const QString png_path = parser.positionalArguments().size() > 1
                                 ? parser.positionalArguments().at(1)
                                 : QStringLiteral("well_log_consumer.png");

    pwb::viz::WellLogHostWidget host;
    host.resize(420, 600);
    QString error;
    if (!host.load_las(las_path, &error)) {
        std::fprintf(stderr, "pwb-well-log-consumer: load failed: %s\n",
                     error.toStdString().c_str());
        return 3;
    }
    host.show();
    if (!process_until(
            [&host] { return host.view()->capability_report().initialization_complete; },
            15000)) {
        std::fprintf(stderr, "pwb-well-log-consumer: GL context did not initialize\n");
        return 4;
    }
    if (!host.select_depth_range(102.0, 106.0)) {
        std::fprintf(stderr, "pwb-well-log-consumer: selection rejected\n");
        return 5;
    }
    process_until([&host] { return host.view()->selection().has_value(); }, 10000);
    const QImage image = host.view()->grabFramebuffer();
    if (image.isNull() || !image.save(png_path)) {
        std::fprintf(stderr, "pwb-well-log-consumer: render/save failed\n");
        return 6;
    }
    std::printf("pwb-well-log-consumer: loaded %s (document %s rev %llu), "
                "selection 102-106 m, rendered %dx%d -> %s\n",
                las_path.toStdString().c_str(),
                host.document_id_text().toStdString().c_str(),
                static_cast<unsigned long long>(host.document_revision()),
                image.width(), image.height(), png_path.toStdString().c_str());
    return 0;
}
