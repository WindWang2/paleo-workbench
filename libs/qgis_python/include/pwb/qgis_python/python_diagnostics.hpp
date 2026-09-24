#pragma once

// Read-only Python environment diagnostics (Prompt 7, Phase L).
//
// Produces a JSON report for the "Environment Diagnostics" action. Rules:
//   - read-only: no imports with side effects, no installs, no writes;
//   - environment variables are sanitised (allow-listed keys only);
//   - no secrets: nothing that looks like a token/key/secret/credential is
//     emitted, and PATH-like values are truncated (see 09 §6).

#include <QString>

namespace pwb::qgis_python {

class PythonRuntime;

class PythonDiagnostics {
public:
    // Never throws; returns a valid (possibly minimal) JSON document even when
    // the runtime is absent.
    static QString reportJson();

    // Human-readable one-screen variant for the diagnostics dialog.
    static QString reportText();

private:
    static QString pythonScalar(const QString& expression);
};

}  // namespace pwb::qgis_python
