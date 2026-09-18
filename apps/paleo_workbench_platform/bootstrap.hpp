#pragma once

// bootstrap — the native entry orchestration (native-product closure,
// task B/C/D). Owns, in order:
//   1. the product log/diagnostics collector (before anything logs);
//   2. QgsApplication + QgisRuntime (single init/exit, CPP-A contract);
//   3. mode dispatch: --self-check / --headless-self-check / --capabilities
//      / --diagnostics / interactive shell;
//   4. the top-level exception gate — nothing thrown crosses
//      QgsApplication::exec() or main() unreported.
//
// Exit codes (documented contract, asserted by ctest):
//   0  requested mode completed successfully
//   1  self-check reported at least one failing check
//   2  startup/runtime fatal (QGIS init failure, unhandled exception)

namespace pwb::app {

class Bootstrap {
public:
    static int run(int argc, char** argv);
};

}  // namespace pwb::app
