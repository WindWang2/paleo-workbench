#pragma once

// self_check — the product self-check battery (native-product closure,
// task C). Runs the C++ product closure end to end without any Python
// runtime: environment, providers/CRS, pure kernels, offscreen UI shell,
// data roundtrip, render/export, project lifecycle, the seismic chain and
// the service registry audit. Every check is honest — a failure is
// reported, never skipped into success.

#include <QString>
#include <QVector>

namespace pwb::app {

class SelfCheck {
public:
    struct Result {
        QString name;
        bool passed = false;
        QString detail;  // failure diagnostics / pass summary
    };

    // Dev-tree fixture root (deployed trees pass an empty dir: the
    // fixture-gated checks report themselves as skipped-by-design and the
    // rest still runs).
    static QVector<Result> run(const QString& source_dir);

    static QString render(const QVector<Result>& results);
};

}  // namespace pwb::app
