// science.viewer.well_log — real well-log-engine Qt adapter test (G5).
// Requires the actual WLE SDK and a real OpenGL context: no Qt-free fakes.
// Receives the LAS fixture path as argv[1] from the CMake test registration.

#include "../pwb_test.hpp"

#include "well_log_host_widget.hpp"

#include <QApplication>
#include <QElapsedTimer>
#include <QImage>
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
            const QImage grabbed = host.view()->grab();
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

    // 6. Clean close: explicit destruction order does not crash, and a
    // fresh host can load again afterwards (repeat open/close robustness).
    {
        WellLogHostWidget second;
        QString second_error;
        PWB_CHECK_MSG(second.load_las(las_path, &second_error),
                      second_error.toStdString().c_str());
    } // full teardown here

    std::printf("science.viewer.well_log: real WLE adapter rendered A1.Las, "
                "selection/range/close all verified\n");
    return 0;
}
