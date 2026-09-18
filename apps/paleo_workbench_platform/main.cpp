// pwb-platform — the native Paleo Workbench product entry.
//
// Modes (see bootstrap.hpp for the exit-code contract):
//   (no args)              interactive window
//   --self-check           headless product self-check battery
//   --headless-self-check  like --self-check, forces offscreen platform
//   --capabilities         build+runtime capability matrix
//   --diagnostics          product diagnostics report
//
// The entry is deliberately thin: bootstrap owns the application lifecycle
// (log chain, QgsApplication/QgisRuntime init, mode dispatch, exception
// gate), AppContext owns the product services, MainWindow owns the shell.

#include "bootstrap.hpp"

int main(int argc, char** argv) {
    return pwb::app::Bootstrap::run(argc, argv);
}
