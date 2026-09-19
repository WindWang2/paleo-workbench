// viz_a.install_cover — compile/link/behavior cover for the app-side
// production wiring TU. The full platform app needs the vendored QGIS SDK
// (whose manifest may not configure on every host — see the gate script's
// step-7 record), so this target compiles apps/paleo_workbench_platform/
// viz_a_install.cpp directly against the real JobCenter and the WLE bridge
// targets and exercises the no-dock early-out. Wiring correctness at the
// worker/GUI level is covered by viz_a.wle_load and the job-bridge
// lifecycle contract; the menu interaction itself needs the platform app.

#include <QApplication>
#include <QMainWindow>

#include "job_center.hpp"

#include "viz_a_install.hpp"

#include <cstdio>

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    pwb::app::JobCenter jobs;
    // No well-log dock exists in this process: install must report false
    // after installing the process-wide preview provider (side effect is
    // asserted by the las_preview tests in their own process).
    if (pwb::app::viz_a::install(nullptr, &jobs)) {
        std::fprintf(stderr, "FAIL install without a window reported true\n");
        return 1;
    }
    QMainWindow window;
    if (pwb::app::viz_a::install(&window, &jobs)) {
        std::fprintf(stderr,
                     "FAIL install without the well-log dock reported true\n");
        return 1;
    }
    if (pwb::app::viz_a::install(&window, nullptr)) {
        std::fprintf(stderr, "FAIL install without a JobCenter reported true\n");
        return 1;
    }
    std::printf("viz_a.install_cover: OK\n");
    return 0;
}
