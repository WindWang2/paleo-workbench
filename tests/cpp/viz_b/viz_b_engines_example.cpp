// VIZ-B — standalone real-engine example (no GUI shell required; the
// paint entries run on the offscreen platform).
//
// Exercises the full line-B chain on the frozen real-well fixture:
//   load (LAS-derived arrays) → PCA section planning → DTW propagation
//   (the real ui_workers kernel) → picks model → JSON round trip →
//   well-tie pipeline (sonic unit normalization → from_sonic → synthetic
//   → auto tie) → composite + publication report export.
//
// Usage: viz_b_engines_example <fixture.json> <output-dir> [well-tie-fixture]

#include <QApplication>
#include <QFile>
#include <QImage>

#include <cmath>
#include <filesystem>
#include <system_error>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_workers/dtw_propagation.hpp>
#include <pwb/viz/cross_well/auto_section_planner.hpp>
#include <pwb/viz/cross_well/picks_model.hpp>
#include <pwb/viz/cross_well/qt/report_export.hpp>
#include <pwb/viz/cross_well/qt/section_canvas.hpp>
#include <pwb/viz/cross_well/section_geometry.hpp>
#include <pwb/viz/well_tie/auto_tie.hpp>
#include <pwb/viz/well_tie/calibration.hpp>
#include <pwb/viz/well_tie/synthetic.hpp>

using pwb::domain::Json;
using pwb::viz::cross_well::WellColumnData;
using pwb::viz::cross_well::WellCoord;
using pwb::viz::cross_well::WellCurve;

namespace {

std::vector<double> read_nums(const Json& arr) {
    std::vector<double> out;
    for (const Json& v : arr) {
        if (v.is_number()) {
            out.push_back(v.get<double>());
        } else if (v.is_string() && v.get<std::string>() == "nan") {
            out.push_back(std::numeric_limits<double>::quiet_NaN());
        }
    }
    return out;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 3) {
        std::cerr << "usage: viz_b_engines_example <cross-well-fixture> "
                     "<output-dir> [well-tie-fixture]\n";
        return 64;
    }
    QApplication app(argc, argv);
    const std::string fixture_path = argv[1];
    const std::string output_dir = argv[2];
    const std::string tie_fixture =
        argc > 3 ? argv[3] : fixture_path;

    std::ifstream file(fixture_path);
    if (!file.is_open()) {
        std::cerr << "cannot open fixture " << fixture_path << "\n";
        return 2;
    }
    Json payload;
    file >> payload;

    std::vector<WellColumnData> wells;
    std::vector<WellCoord> coords;
    for (const Json& w : payload.at("real_wells").at("wells")) {
        WellColumnData column;
        column.name = w.at("name").get<std::string>();
        coords.push_back(
            {column.name, w.value("lng", 0.0), w.value("lat", 0.0)});
        for (const Json& curve : w.at("curves")) {
            WellCurve wc;
            wc.name = curve.at("name").get<std::string>();
            wc.depths = read_nums(curve.at("depths"));
            wc.values = read_nums(curve.at("values"));
            column.curves.push_back(std::move(wc));
        }
        wells.push_back(std::move(column));
    }
    std::cout << "[viz-b example] loaded " << wells.size() << " real wells\n";

    // Section planning.
    const auto order = pwb::viz::cross_well::plan_section(coords, "pca");
    std::vector<WellColumnData> arranged;
    for (std::size_t index : order) arranged.push_back(wells[index]);
    std::cout << "[viz-b example] section order:";
    for (const WellColumnData& well : arranged) {
        std::cout << ' ' << well.name;
    }
    std::cout << "\n";

    // DTW propagation through the real worker kernel.
    pwb::ui_workers::DtwSceneSlice scene;
    const std::vector<std::string> preferred = {"GR", "SP", "RT"};
    for (const WellColumnData& well : arranged) {
        pwb::ui_workers::DtwWellSlice slice;
        slice.name = well.name;
        if (auto curve = pwb::viz::cross_well::extract_curve(well.curves,
                                                            preferred)) {
            slice.depths = curve->depths;
            slice.values = curve->values;
        }
        scene.wells.push_back(std::move(slice));
    }
    const std::vector<double>& ref_depths = *scene.wells[0].depths;
    const double ref_depth = ref_depths[ref_depths.size() / 2] + 120.0;
    const int band = pwb::ui_workers::bounded_dtw_band(
        static_cast<int>(scene.wells[0].values->size()));
    const auto pairs = pwb::ui_workers::compute_dtw_propagation(
        scene, scene.wells[0].name, ref_depth, band,
        pwb::ui_workers::dtw_engine_correlate,
        [](int done, int total) {
            std::cout << "[viz-b example] dtw progress " << done << '/'
                      << total << "\n";
        });
    pwb::viz::cross_well::HorizonPicksModel picks;
    const std::string pick_id =
        picks.add_pick("Example-Horizon", arranged[0].name, ref_depth);
    // G3: the DTW chain used to ship only export booleans; a numeric
    // regression (NaN / off-domain pick) would leave the test green. The
    // fixture's propagation may legitimately produce zero picks (no
    // correlatable offset in the search band) — that is valid; any pick
    // that IS produced must be finite and positive.
    for (const auto& [well, depth] : pairs) {
        picks.connect_picks(pick_id, well, depth);
        std::cout << "[viz-b example] dtw pick " << well << " @ " << depth
                  << " m\n";
        if (!std::isfinite(depth) || depth <= 0.0) {
            std::cerr << "[viz-b example] NON-FINITE / non-positive pick @ "
                      << well << " -> " << depth << "\n";
            return 1;
        }
    }

    // Well tie pipeline on the tie fixture's real logs.
    std::ifstream tie_file(tie_fixture);
    if (tie_file.is_open()) {
        Json tie_payload;
        tie_file >> tie_payload;
        const Json& well =
            tie_payload.at("real_wells").at("wells").at(0);
        const std::vector<double> depths = read_nums(well.at("depths"));
        const std::vector<double> sonic =
            read_nums(well.at("sonic_us_per_m"));
        const std::vector<double> density = read_nums(well.at("density"));
        const auto calibration =
            pwb::viz::well_tie::WellTieCalibration::from_sonic(depths,
                                                                sonic);
        // from_sonic 丢弃非有限 (depth, sonic) 样本；合成记录必须建在同一
        // 过滤域上，resample 的 values/src_twt 才同域等长（此前原始域的
        // synthetic 配过滤域的 twt，错位插值被长度守卫拦下）。
        std::vector<double> kept_sonic;
        std::vector<double> kept_density;
        kept_sonic.reserve(sonic.size());
        for (std::size_t i = 0; i < depths.size(); ++i) {
            if (std::isfinite(depths[i]) && std::isfinite(sonic[i])) {
                kept_sonic.push_back(sonic[i]);
                kept_density.push_back(density[i]);
            }
        }
        const auto synthetic =
            pwb::viz::well_tie::synthetic_from_logs(kept_sonic, kept_density);
        // 合成记录定义在深度区间上（n-1 个采样）：src_twt 取相邻 twt 中点。
        const std::vector<double>& twt = calibration.twt();
        std::vector<double> src_twt(synthetic.size(), 0.0);
        for (std::size_t i = 0; i + 1 < twt.size() && i < synthetic.size();
             ++i) {
            src_twt[i] = (twt[i] + twt[i + 1]) / 2.0;
        }
        const std::vector<double> grid =
            pwb::viz::well_tie::resample_to_seismic_grid(
                std::vector<double>(synthetic.begin(), synthetic.end()),
                src_twt, 4.0, twt.front() + 40.0, 512);
        const auto tie = pwb::viz::well_tie::correlate_synthetic_to_trace(
            grid, grid);
        std::cout << "[viz-b example] well " << well.at("name").get<std::string>()
                  << ": twt[0..n]=" << calibration.twt().front() << ".."
                  << calibration.twt().back() << " ms, synthetic n="
                  << synthetic.size() << ", self-tie r=" << tie.correlation
                  << "\n";
    }

    // Exports (offscreen paint entries — the same code path the dock
    // uses on screen).
    pwb::viz::cross_well::qt::SectionCanvas canvas;
    canvas.set_wells(arranged);
    canvas.set_models(nullptr, &picks);
    const auto export_scene = canvas.build_scene();
    std::error_code ec;
    std::filesystem::create_directories(output_dir, ec);
    const QString dir = QString::fromStdString(output_dir);
    const bool pdf_ok = pwb::viz::cross_well::qt::export_section_composite(
        export_scene, dir + "/viz_b_section.pdf", "pdf", 150, std::nullopt,
        QString("A4"));
    pwb::viz::cross_well::qt::CrossWellReportOptions options;
    options.dpi = 96;
    const bool report_ok = pwb::viz::cross_well::qt::export_cross_well_report(
        export_scene, dir + "/viz_b_report.pdf", options);
    const bool png_ok = pwb::viz::cross_well::qt::export_cross_well_report(
        export_scene, dir + "/viz_b_report.png", options);
    std::cout << "[viz-b example] exports: pdf=" << pdf_ok
              << " report=" << report_ok << " png=" << png_ok << "\n";
    if (!pdf_ok || !report_ok || !png_ok) return 1;
    std::cout << "[viz-b example] OK\n";
    return 0;
}
