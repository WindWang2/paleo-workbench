#pragma once

// Process-level QGIS runtime ownership (single init/exit, CPP-A contract).
// The vendored prefix path is injected at build time from the SDK admission
// (cmake/PwbQgisSdk.cmake) — no runtime guessing, no PATH dependency.

#include <string>

namespace pwb::qgis {

class QgisRuntime {
public:
    // setPrefixPath + init + initQgis; exactly once per process. A second
    // call is a programming error and aborts with a diagnostic.
    static void acquire();

    // exitQgis; exactly once, after every MapSession is gone. Idempotent
    // guard makes double-release a no-op (process-exit safety).
    static void release();

    static bool initialized();

    // Diagnostics for logs/tests: prefix path + QGIS version string.
    static const std::string& prefix_path();
    static std::string qgis_version();
};

}  // namespace pwb::qgis
