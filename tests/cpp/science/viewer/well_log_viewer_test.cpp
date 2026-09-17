// science.viewer.well_log — real well-log-engine Qt adapter test (G5).
// Requires the actual WLE SDK and a real OpenGL context: no Qt-free fakes.
// Receives the LAS fixture path as argv[1] from the CMake test registration.
// Covers: real LAS parse/render, SelectionEventV1 business ids/units,
// viewport reset, PNG export, Unicode paths, negative loads, and a 20x
// load/close robustness loop (no hangs, no dangling callbacks).

#include "../pwb_test.hpp"

#include <pwb/viz/well_log_host_widget.hpp>

#include <QApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QImage>
#include <QTemporaryDir>
#include <QThread>

#include <welllog/qtwidgets/well_log_view.hpp>

#include <algorithm>
#include <cstdio>
#include <functional>
#include <string>
#include <vector>

using pwb::viz::SelectionEventV1;
using pwb::viz::WellLogHostWidget;

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

std::size_t distinct_colors(const QImage& image) {
    std::vector<QRgb> colors;
    for (int y = 0; y < image.height(); y += 2) {
        for (int x = 0; x < image.width(); x += 2) {
            colors.push_back(image.pixel(x, y));
        }
    }
    std::sort(colors.begin(), colors.end());
    colors.erase(std::unique(colors.begin(), colors.end()), colors.end());
    return colors.size();
}

} // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s <path-to-A1.Las>\n", argv[0]);
        return 2;
    }
    const QString las_path = QString::fromLocal8Bit(argv[1]);

    WellLogHostWidget host;
    host.resize(420, 600);

    // 1. Real LAS fixture loads through the engine's own parser.
    QString error;
    PWB_CHECK_MSG(host.load_las(las_path, &error), error.toStdString().c_str());
    PWB_CHECK(host.has_document());
    PWB_CHECK(host.document_revision() >= 1);
    PWB_CHECK(!host.document_id_text().isEmpty());
    PWB_CHECK(host.view() != nullptr);
    PWB_CHECK(host.session() != nullptr);

    // 2. Real GL surface initializes (capability report comes from the
    // engine; a headless/fake GL would fail here — that is the point).
    host.show();
    PWB_CHECK(process_until(
        [&host] { return host.view()->capability_report().initialization_complete; },
        15000));
    const welllog::CapabilityReport& report = host.view()->capability_report();
    PWB_CHECK_MSG(report.graphics_available, report.unavailable_reason.c_str());
    PWB_CHECK(report.open_gl_major > 3 ||
              (report.open_gl_major == 3 && report.open_gl_minor >= 3));

    // 3. The view actually renders curve pixels (depth axis + curve lines),
    // not just a blank widget.
    PWB_CHECK(process_until(
        [&host] {
            const QImage grabbed = host.view()->grabFramebuffer();
            return !grabbed.isNull() && distinct_colors(grabbed) > 1;
        },
        15000));

    // 4. Selection via the host API surfaces as SelectionEventV1 with stable
    // domain id / unit / origin / revision (no widget addresses involved).
    std::vector<SelectionEventV1> events;
    host.set_selection_callback([&events](const SelectionEventV1& event) {
        events.push_back(event);
    });
    PWB_CHECK(host.select_depth_range(102.0, 106.0));
    PWB_CHECK(process_until([&events] { return !events.empty(); }, 10000));
    {
        const SelectionEventV1& event = events.front();
        PWB_CHECK(event.document_id == host.document_id_text().toStdString());
        PWB_CHECK(event.range.unit == "m"); // A1.Las declares DEPT.M
        PWB_CHECK(event.range.top == 102.0);
        PWB_CHECK(event.range.bottom == 106.0);
        PWB_CHECK(event.revision == host.document_revision());
        PWB_CHECK(!event.origin.empty());
        PWB_CHECK(event.domain == pwb::viz::DepthDomainKind::measured_depth);
    }

    // 5. Range interaction: viewport reset + clear selection round-trip.
    host.reset_viewport();
    host.clear_selection();
    PWB_CHECK(process_until(
        [&host] { return !host.view()->selection().has_value(); }, 10000));

    // 5b. PNG export: the rendered view is a real, non-empty image file.
    {
        const QImage grabbed = host.view()->grabFramebuffer();
        PWB_CHECK(!grabbed.isNull());
        PWB_CHECK(grabbed.width() > 0 && grabbed.height() > 0);
        const QString png_path =
            QDir::current().filePath("well_log_viewer_test.png");
        PWB_CHECK(grabbed.save(png_path, "PNG"));
        PWB_CHECK(QFile(png_path).size() > 0);
        std::printf("saved render: %s (%dx%d)\n", png_path.toStdString().c_str(),
                    grabbed.width(), grabbed.height());
    }

    // 5c. Unicode path: same LAS under a non-ASCII filename still loads.
    {
        QTemporaryDir temp;
        PWB_CHECK(temp.isValid());
        const QString sub = QStringLiteral("测井-archives");
        PWB_CHECK(QDir(temp.path()).mkpath(sub));
        const QString unicode_path = QDir(temp.path()).filePath(
            sub + QStringLiteral("/Well No.7 — ünicode名.Las"));
        PWB_CHECK(QFile::copy(las_path, unicode_path));
        WellLogHostWidget unicode_host;
        QString unicode_error;
        PWB_CHECK_MSG(unicode_host.load_las(unicode_path, &unicode_error),
                      unicode_error.toStdString().c_str());
        PWB_CHECK(unicode_host.has_document());
    }

    // 5d. Negative loads: missing file / malformed content must fail with a
    // non-empty error, never crash, and leave a previously loaded document
    // intact.
    {
        QString error;
        PWB_CHECK(!host.load_las(QStringLiteral("/nonexistent/ghost.Las"), &error));
        PWB_CHECK(!error.isEmpty());
        PWB_CHECK(host.has_document()); // previous document survived
        error.clear();

        QTemporaryDir temp;
        QFile garbage(temp.filePath("garbage.Las"));
        PWB_CHECK(garbage.open(QIODevice::WriteOnly));
        garbage.write("this is not a LAS file at all\n\x01\x02\x03\n");
        garbage.close();
        PWB_CHECK(!host.load_las(garbage.fileName(), &error));
        PWB_CHECK(!error.isEmpty());
        PWB_CHECK(host.has_document());
        PWB_CHECK(!host.document_id_text().isEmpty());

        QFile empty(temp.filePath("empty.Las"));
        PWB_CHECK(empty.open(QIODevice::WriteOnly));
        empty.close();
        error.clear();
        PWB_CHECK(!host.load_las(empty.fileName(), &error));
        PWB_CHECK(!error.isEmpty());
    }

    // 5e. In-place reload on the SAME widget: full replacement — the engine
    // derives document ids deterministically from the source identity, so
    // reloading the same file keeps the id; what must hold is that the
    // reload succeeds and the view still renders.
    {
        QString reload_error;
        PWB_CHECK_MSG(host.load_las(las_path, &reload_error),
                      reload_error.toStdString().c_str());
        PWB_CHECK(host.has_document());
        PWB_CHECK(!host.document_id_text().isEmpty());
        PWB_CHECK(process_until([&host] {
            const QImage grabbed = host.view()->grabFramebuffer();
            return !grabbed.isNull() && distinct_colors(grabbed) > 1;
        }, 15000));
    }

    // 6. Close robustness: 20 full load/show/close cycles in FRESH widgets
    // (each iteration is a complete session + GL context teardown — no hang,
    // no dangling callback can survive this loop).
    for (int round = 0; round < 20; ++round) {
        WellLogHostWidget cycle;
        cycle.resize(420, 600);
        QString cycle_error;
        PWB_CHECK_MSG(cycle.load_las(las_path, &cycle_error),
                      cycle_error.toStdString().c_str());
        cycle.show();
        PWB_CHECK(process_until([&cycle] {
            return cycle.view()->capability_report().initialization_complete;
        }, 15000));
        QApplication::processEvents(QEventLoop::AllEvents, 20);
    } // full teardown each round

    std::printf("science.viewer.well_log: real WLE adapter rendered A1.Las, "
                "selection/range/PNG/unicode/negatives + 20x open-close "
                "verified\n");
    return 0;
}
