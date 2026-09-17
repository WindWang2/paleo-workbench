// platform.factor_hud — conv-16 first cluster: the read-only factor
// statistics HUD (FactorStatsDock) against the frozen Python oracle.
//
// Oracle: tests/fixtures frozen by tools/oracle/generate_factor_hud_fixtures.py
// from the REAL paleo_workbench.workflow.factor_grid_result module
// (GridStatistics.from_grid / FactorGridResult.statistics) plus the real
// workstation ":g" row formatting (f"{min:g} ~ {max:g}", dash fallback for
// an all-nodata grid — the vocabulary tests/test_inspector_v7.py pins).
//
// Assertions per case:
//   * pwb::mapping::grid_statistics reproduces the frozen statistics
//     (the same numbers the dock must display), and
//   * FactorStatsDock renders exactly the frozen display strings
//     (因素 / 取值范围 / 均值 / 标准差 / 有效格元), and
//   * the dock is a hostable QDockWidget (attached to a QMainWindow under
//     the objectName the MainWindow CONV-16 wiring uses).

#include <cmath>
#include <cstdio>
#include <fstream>
#include <limits>
#include <sstream>
#include <string>
#include <vector>

#include <QApplication>
#include <QDockWidget>
#include <QMainWindow>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/interpolator.hpp>

#include "factor_stats_dock.hpp"

using pwb::app::FactorStatsDock;
using pwb::domain::Json;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

void check_text(const QString& got, const std::string& want,
                const std::string& what) {
    if (got.toStdString() != want) {
        std::fprintf(stderr, "FAIL %s: got \"%s\" want \"%s\"\n", what.c_str(),
                     got.toStdString().c_str(), want.c_str());
        ++g_failures;
    }
}

bool same_num(double got, const Json& want) {
    if (want.is_null()) return !std::isfinite(got);
    if (!std::isfinite(got)) return false;
    // Relative+floor tolerance: numpy switches to pairwise summation at
    // n>=8, so a pure absolute epsilon would false-red future larger grids.
    const double w = want.get<double>();
    return std::fabs(got - w) <= 1e-12 + 1e-9 * std::fabs(w);
}

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);

    std::ifstream stream(PWB_FACTOR_HUD_FIXTURE, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open oracle fixture\n");
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const Json oracle = Json::parse(buffer.str());

    // One dock drives every case (the HUD is stateless between updates).
    // Heap-allocated: addDockWidget reparents it into `host`, so Qt owns the
    // object from there on (a stack object would be destroyed twice).
    auto* dock = new FactorStatsDock();
    check(dock->objectName() == QLatin1String("factor-stats-dock"),
          "dock objectName");
    check(dock->windowTitle() == QStringLiteral("单因素统计"),
          "dock window title");

    // Hostable like the MainWindow CONV-16 wiring does (right dock area).
    QMainWindow host;
    host.addDockWidget(Qt::RightDockWidgetArea, dock);
    check(host.findChild<QDockWidget*>(QStringLiteral("factor-stats-dock")) ==
              dock,
          "dock attachable to a QMainWindow");

    int n = 0;
    for (const auto& c : oracle["cases"]) {
        ++n;
        const std::string id = c["id"].get<std::string>();
        std::vector<float> cells;
        for (const auto& v : c["cells"]) {
            cells.push_back(v.is_null()
                                ? std::numeric_limits<float>::quiet_NaN()
                                : static_cast<float>(v.get<double>()));
        }

        // Kernel statistics match the frozen Python numbers.
        const auto stats = pwb::mapping::grid_statistics(cells);
        const auto& want = c["stats"];
        check(stats.valid_count == want["valid_count"].get<int>(),
              id + " valid_count");
        check(stats.total_count == want["total_count"].get<int>(),
              id + " total_count");
        check(same_num(stats.min, want["min"]), id + " min");
        check(same_num(stats.max, want["max"]), id + " max");
        check(same_num(stats.mean, want["mean"]), id + " mean");
        check(same_num(stats.std, want["std"]), id + " std");

        // The HUD renders exactly the frozen Python display strings.
        dock->setStatistics(
            QString::fromUtf8(c["display"]["factor"].get<std::string>().c_str()),
            stats);
        check_text(dock->rowValue(QStringLiteral("因素")),
                   c["display"]["factor"].get<std::string>(), id + " 因素");
        check_text(dock->rowValue(QStringLiteral("取值范围")),
                   c["display"]["range"].get<std::string>(), id + " 取值范围");
        check_text(dock->rowValue(QStringLiteral("均值")),
                   c["display"]["mean"].get<std::string>(), id + " 均值");
        check_text(dock->rowValue(QStringLiteral("标准差")),
                   c["display"]["std"].get<std::string>(), id + " 标准差");
        check_text(dock->rowValue(QStringLiteral("有效格元")),
                   c["display"]["valid_count"].get<std::string>(),
                   id + " 有效格元");
    }

    // An empty factor name degrades to the dash, not an empty label.
    pwb::mapping::GridStatistics stats;
    stats.valid_count = 2;
    stats.total_count = 2;
    stats.min = 1.0;
    stats.max = 2.0;
    stats.mean = 1.5;
    stats.std = 0.5;
    dock->setStatistics(QString(), stats);
    check_text(dock->rowValue(QStringLiteral("因素")), "—", "empty factor name");

    // The fixture is frozen alongside this test; an emptied oracle.json must
    // not print a vacuous PASS.
    check(n == 11, "oracle case count drifted from the frozen fixture");
    if (g_failures != 0) {
        std::printf("FAIL platform.factor_hud (%d assertion(s) failed)\n",
                    g_failures);
        return 1;
    }
    std::printf("PASS platform.factor_hud (%d oracle cases)\n", n);
    return 0;
}
