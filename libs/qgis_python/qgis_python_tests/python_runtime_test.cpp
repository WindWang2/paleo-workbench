// qgis_python.runtime — Phase A oracle (Prompt 7).
//
// Covers the bootstrap guarantees of
// docs/development/qgis-native-python-runtime/03-qgispython-bootstrap.md §8:
//   * library found/loaded, or a clean diagnostic when it is not;
//   * Python is initialised exactly once;
//   * shutdown is idempotent;
//   * QgsPythonRunner is installed and usable;
//   * a missing runtime degrades instead of crashing (gate #10).
//
// The suite is honest about the environment: when the runtime is unavailable it
// asserts the *degradation* contract and reports SKIPPED for the positive
// assertions instead of pretending they ran.

#include <cstdio>
#include <string>

#include <QString>

#include <qgspythonrunner.h>

#include <pwb/qgis_python/python_runtime.hpp>

using pwb::qgis_python::PythonCapability;
using pwb::qgis_python::PythonRuntime;

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

void skip(const std::string& what) {
    std::printf("SKIP %s\n", what.c_str());
}

}  // namespace

int main() {
    PythonRuntime& runtime = PythonRuntime::instance();

    // 1. Initialise once. A second call must not start a second interpreter.
    QString error;
    const bool first = runtime.initialize(nullptr, &error);
    const bool second = runtime.initialize(nullptr, &error);
    check(first == second, "initialize() is idempotent (no second interpreter)");
    check(runtime.isInitialized(), "runtime reports initialised");

    // 2. Runner installation follows initPython() and only exists when enabled.
    if (runtime.isEnabled()) {
        check(QgsPythonRunner::isValid(), "QgsPythonRunner has an instance");

        QString result;
        const bool ok = QgsPythonRunner::eval(QStringLiteral("1 + 1"), result);
        check(ok, "QgsPythonRunner::eval executes");
        check(result.trimmed() == QStringLiteral("2"),
              "QgsPythonRunner::eval returns the value");

        const PythonCapability capability = runtime.capability();
        check(capability.runtimeAvailable, "capability: runtime available");
        check(capability.pythonEnabled, "capability: python enabled");
        check(!capability.qgisVersion.isEmpty(),
              "capability: QGIS version reported");
        check(capability.usable(), "capability: runtime usable");

        if (capability.bindingsAvailable) {
            QString projectRepr;
            const bool same = runtime.evalString(
                QStringLiteral("__import__('qgis.core',fromlist=['x'])"
                               ".QgsProject.instance()"),
                &projectRepr);
            check(same, "PyQGIS can reach QgsProject.instance()");
        } else {
            skip("PyQGIS smoke (bindings not installed for this build)");
        }
    } else {
        // Degradation contract: no crash, no throw, an honest diagnostic.
        check(!QgsPythonRunner::isValid(),
              "runner stays invalid when Python is disabled");
        check(!error.isEmpty(), "a reason is reported when Python is disabled");

        QString ignored;
        check(!runtime.runString(QStringLiteral("print(1)"), &ignored),
              "runString() reports failure when the runtime is absent");
        skip("positive PyQGIS assertions (runtime not enabled)");
    }

    // 3. Shutdown is idempotent.
    runtime.shutdown();
    runtime.shutdown();
    check(!runtime.isInitialized(), "shutdown() clears the initialised state");
    check(!QgsPythonRunner::isValid(), "shutdown() removes the runner");

    std::printf("qgis_python.runtime: %d checks, %d failures\n", g_checks,
                g_failures);
    return g_failures == 0 ? 0 : 1;
}
