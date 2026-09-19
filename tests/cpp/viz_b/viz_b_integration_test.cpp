// VIZ-B — integration test (tests/cpp/viz_b): the real cross-well /
// well-tie end-to-end flow on the frozen real-well fixture:
//   load wells → section planner → DTW propagation (the REAL worker core,
//   no second DTW) → picks apply → save → reopen identity → composite +
//   report export readability → cancellation drop semantics → the well
//   tie numeric pipeline on real sonic/density logs.

#include <QApplication>
#include <QFile>
#include <QImage>
#include <QTemporaryDir>

#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/ui_workers/dtw_propagation.hpp>
#include <pwb/viz/cross_well/auto_section_planner.hpp>
#include <pwb/viz/cross_well/picks_model.hpp>
#include <pwb/viz/cross_well/qt/report_export.hpp>
#include <pwb/viz/cross_well/qt/section_canvas.hpp>
#include <pwb/viz/cross_well/section_geometry.hpp>
#include <pwb/viz/well_tie/auto_tie.hpp>
#include <pwb/viz/well_tie/calibration.hpp>
#include <pwb/viz/well_tie/sonic_units.hpp>
#include <pwb/viz/well_tie/synthetic.hpp>

#ifndef PWB_VIZ_B_CROSS_WELL_FIXTURE
#error "fixture macro missing"
#endif
#ifndef PWB_VIZ_B_WELL_TIE_FIXTURE
#error "well tie fixture macro missing"
#endif

using pwb::domain::Json;
using pwb::viz::cross_well::WellColumnData;
using pwb::viz::cross_well::WellCurve;

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& label) {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::cerr << "FAIL: " << label << "\n";
    }
}

std::vector<double> read_nums(const Json& arr) {
    std::vector<double> out;
    for (const Json& v : arr) {
        if (v.is_number()) {
            out.push_back(v.get<double>());
        } else if (v.is_string()) {
            const std::string s = v.get<std::string>();
            if (s == "nan") {
                out.push_back(std::numeric_limits<double>::quiet_NaN());
            } else if (s == "inf") {
                out.push_back(std::numeric_limits<double>::infinity());
            } else if (s == "-inf") {
                out.push_back(-std::numeric_limits<double>::infinity());
            }
        }
    }
    return out;
}

bool file_starts_with(const QString& path, const char* prefix) {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) return false;
    return file.read(static_cast<qint64>(std::strlen(prefix))) ==
           QByteArray(prefix);
}

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    QTemporaryDir temp;
    check(temp.isValid(), "temp dir");

    Json cw_payload;
    {
        std::ifstream file(PWB_VIZ_B_CROSS_WELL_FIXTURE);
        if (!file.is_open()) {
            std::cerr << "cannot open cross_well fixture\n";
            return 2;
        }
        file >> cw_payload;
    }
    Json wt_payload;
    {
        std::ifstream file(PWB_VIZ_B_WELL_TIE_FIXTURE);
        if (!file.is_open()) {
            std::cerr << "cannot open well_tie fixture\n";
            return 2;
        }
        file >> wt_payload;
    }

    // --- 1. load wells -------------------------------------------------
    std::vector<WellColumnData> wells;
    std::vector<pwb::viz::cross_well::WellCoord> coords;
    for (const Json& w : cw_payload.at("real_wells").at("wells")) {
        WellColumnData column;
        column.name = w.at("name").get<std::string>();
        coords.push_back({column.name, w.value("lng", 0.0),
                          w.value("lat", 0.0)});
        for (const Json& curve : w.at("curves")) {
            WellCurve wc;
            wc.name = curve.at("name").get<std::string>();
            wc.depths = read_nums(curve.at("depths"));
            wc.values = read_nums(curve.at("values"));
            column.curves.push_back(std::move(wc));
        }
        wells.push_back(std::move(column));
    }
    check(wells.size() >= 2, "wells loaded");

    // --- 2. planner orders the section deterministically ---------------
    const auto order = pwb::viz::cross_well::plan_section_pca(coords);
    const auto order_again = pwb::viz::cross_well::plan_section_pca(coords);
    check(order == order_again, "planner deterministic");
    check(order.size() == wells.size(), "planner permutation complete");

    // --- 3. DTW propagation through the REAL worker core ---------------
    pwb::ui_workers::DtwSceneSlice scene;
    const std::vector<std::string> preferred = {"GR", "SP", "RT"};
    for (const WellColumnData& well : wells) {
        pwb::ui_workers::DtwWellSlice slice;
        slice.name = well.name;
        if (auto curve = pwb::viz::cross_well::extract_curve(well.curves,
                                                            preferred)) {
            slice.depths = curve->depths;
            slice.values = curve->values;
        }
        scene.wells.push_back(std::move(slice));
    }
    // Reference depth: a real mid-range depth of the first well's curve.
    const std::vector<double>& ref_depths = *scene.wells[0].depths;
    const double ref_depth =
        ref_depths[ref_depths.size() / 2] + 120.0;  // a horizon offset
    std::vector<std::pair<std::string, double>> pairs;
    int progress_steps = 0;
    const int band = pwb::ui_workers::bounded_dtw_band(
        static_cast<int>(scene.wells[0].values->size()));
    pairs = pwb::ui_workers::compute_dtw_propagation(
        scene, scene.wells[0].name, ref_depth, band,
        pwb::ui_workers::dtw_engine_correlate,
        [&](int, int) { ++progress_steps; });
    check(progress_steps == static_cast<int>(wells.size()) - 1,
          "progress fired per non-ref well, got " +
              std::to_string(progress_steps));
    // The propagation must return a depth on the target well's actual
    // sample grid (never fabricated).
    for (const auto& [well, depth] : pairs) {
        bool on_grid = false;
        for (const WellColumnData& column : wells) {
            if (column.name != well) continue;
            for (const WellCurve& curve : column.curves) {
                for (double d : curve.depths) {
                    if (d == depth) {
                        on_grid = true;
                        break;
                    }
                }
            }
        }
        check(on_grid, "dtw depth on sample grid for " + well);
    }

    // --- 4. job-runtime path: spec + cancelled context -> dropped ------
    pwb::ui_workers::DtwPropagationInput input;
    input.scene = scene;
    input.ref_well = scene.wells[0].name;
    input.ref_depth = ref_depth;
    bool on_done_called = false;
    bool on_cancel_called = false;
    auto spec = pwb::ui_workers::make_dtw_propagation_job_spec(
        std::move(input),
        [&](const pwb::ui_workers::DtwPropagationResult&) {
            on_done_called = true;
        },
        [](const std::string&) {},
        [&]() { on_cancel_called = true; });
    check(spec.kind == "compute.dtw_propagation", "job kind");
    pwb::job::CancellationToken token;
    token.cancel();
    pwb::job::JobContext cancelled_context("viz-b-cancel-test", token);
    bool cancelled_thrown = false;
    try {
        spec.run(cancelled_context);
    } catch (const pwb::job::JobCancelled&) {
        cancelled_thrown = true;
    }
    check(cancelled_thrown && !on_done_called,
          "pre-cancelled job drops the result (no late writes)");
    (void)on_cancel_called;

    // --- 5. picks apply → save → reopen identity -----------------------
    pwb::viz::cross_well::HorizonPicksModel model;
    const std::string pick_id =
        model.add_pick("Integration-Horizon", wells[0].name, ref_depth);
    for (const auto& [well, depth] : pairs) {
        model.connect_picks(pick_id, well, depth);
    }
    pwb::viz::cross_well::PickConfidence confidence;
    for (const auto& [well, depth] : pairs) {
        (void)depth;
        confidence.set(well, 0.5);
    }
    model.set_pick_confidence(pick_id, confidence);
    const Json saved = model.to_json();
    const std::string path = temp.path().toStdString() + "/picks.json";
    { std::ofstream f(path); f << saved.dump(2); }
    pwb::viz::cross_well::HorizonPicksModel reopened;
    {
        std::ifstream in(path);
        Json loaded;
        in >> loaded;
        reopened.from_json(loaded);
    }
    check(reopened.to_json().dump() == saved.dump(), "reopen identity");
    const auto* reopened_pick = reopened.get_pick(pick_id);
    check(reopened_pick != nullptr &&
              reopened_pick->connected_wells().size() == 1 + pairs.size(),
          "reopen connected wells");

    // --- 6. export paths readable + carry identity ---------------------
    pwb::viz::cross_well::qt::SectionCanvas canvas;
    canvas.resize(1400, 640);
    canvas.set_wells(wells);
    canvas.set_models(nullptr, &model);
    const pwb::viz::cross_well::qt::SectionScene export_scene =
        canvas.build_scene();
    const QString composite_pdf = temp.filePath("composite.pdf");
    check(pwb::viz::cross_well::qt::export_section_composite(
              export_scene, composite_pdf, "pdf", 150, std::nullopt,
              QString("A4")),
          "composite pdf");
    check(file_starts_with(composite_pdf, "%PDF"), "composite pdf magic");
    const QString report_pdf = temp.filePath("report.pdf");
    pwb::viz::cross_well::qt::CrossWellReportOptions options;
    options.dpi = 96;
    check(pwb::viz::cross_well::qt::export_cross_well_report(
              export_scene, report_pdf, options),
          "report pdf");
    check(file_starts_with(report_pdf, "%PDF"), "report pdf magic");
    check(QFile(report_pdf).size() > 1000, "report pdf size");
    const QString section_svg = temp.filePath("section.svg");
    check(pwb::viz::cross_well::qt::export_section_composite(
              export_scene, section_svg, "svg", 96, 1600, std::nullopt),
          "composite svg");
    {
        QFile f(section_svg);
        f.open(QIODevice::ReadOnly);
        const QString text = QString::fromUtf8(f.readAll());
        check(text.contains("A4") && text.contains("A13"),
              "svg identity: well names");
        // Pick identity in the export is the coloured tie geometry +
        // curve track labels (picks carry no text label — Python parity).
        check(text.contains("GR"), "svg identity: curve track label");
    }

    // --- 7. well tie pipeline on the real logs -------------------------
    for (const Json& w : wt_payload.at("real_wells").at("wells")) {
        const std::vector<double> depths = read_nums(w.at("depths"));
        const std::vector<double> sonic =
            read_nums(w.at("sonic_us_per_m"));
        const std::vector<double> density = read_nums(w.at("density"));
        const auto calibration =
            pwb::viz::well_tie::WellTieCalibration::from_sonic(depths,
                                                                sonic);
        // from_sonic masks non-finite pairs: both masked axes must stay
        // aligned (twt may legitimately be shorter than the raw logs).
        check(calibration.twt().size() == calibration.depths().size() &&
                  calibration.twt().size() >= 2,
              w.at("name").get<std::string>() + " twt length");
        const auto synthetic =
            pwb::viz::well_tie::synthetic_from_logs(sonic, density);
        check(synthetic.size() + 1 == depths.size(),
              w.at("name").get<std::string>() + " synthetic length");
        // Resample onto a regular seismic grid and cross-correlate the
        // synthetic against itself shifted — the lag must be recovered.
        const std::vector<double> grid =
            pwb::viz::well_tie::resample_to_seismic_grid(
                std::vector<double>(synthetic.begin(), synthetic.end()),
                calibration.twt(), 4.0, calibration.twt().front() + 40.0,
                512);
        check(grid.size() == 512, "seismic grid size");
        std::vector<double> shifted(grid.size(), 0.0);
        const int offset = 24;
        for (std::size_t i = 0;
             i + static_cast<std::size_t>(offset) < grid.size(); ++i) {
            shifted[i + static_cast<std::size_t>(offset)] = grid[i];
        }
        const auto tied = pwb::viz::well_tie::correlate_synthetic_to_trace(
            grid, shifted);
        check(tied.shift_samples == offset && tied.correlation > 0.99,
              w.at("name").get<std::string>() +
                  " auto tie recovers lag, got " +
                  std::to_string(tied.shift_samples) + " r=" +
                  std::to_string(tied.correlation));
    }

    std::cout << "viz_b integration: " << g_checks << " checks, "
              << g_failures << " failures\n";
    return g_failures == 0 ? 0 : 1;
}
