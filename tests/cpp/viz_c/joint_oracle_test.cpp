// viz_c.joint_oracle — replay of the frozen Python oracle
// (tools/oracle/generate_viz_c_fixtures.py over geoviz_well_seismic_3d
// @ 08851951). Every value must match: exact float equality with a tiny
// relative fallback (same glibc libm on both sides makes exact the norm;
// 1e-12 absorbs cross-platform libm ULP noise for trig-derived values
// only). The tampered-fixture negative self-check must DETECT the
// perturbation.
#include "pwb_test.hpp"

#include <pwb/domain/json.hpp>
#include <pwb/geo3d_viz/joint/color_scales.hpp>
#include <pwb/geo3d_viz/joint/depth_transform.hpp>
#include <pwb/geo3d_viz/joint/fence.hpp>
#include <pwb/geo3d_viz/joint/joint_scene.hpp>
#include <pwb/geo3d_viz/joint/probe.hpp>
#include <pwb/geo3d_viz/joint/registration.hpp>
#include <pwb/geo3d_viz/joint/segy_survey.hpp>
#include <pwb/geo3d_viz/joint/survey.hpp>
#include <pwb/geo3d_viz/joint/volume_access.hpp>
#include <pwb/geo3d_viz/joint/well_geometry.hpp>

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <limits>
#include <sstream>

namespace {

namespace fs = std::filesystem;
using pwb::domain::Json;
using namespace pwb::geo3d_viz::joint;

int g_compared = 0;

bool same_float(double a, double b) {
    ++g_compared;
    if (a == b) return true;
    if (std::isnan(a) && std::isnan(b)) return true;  // NaN markers match
    const double scale = std::max({1.0, std::fabs(a), std::fabs(b)});
    return std::fabs(a - b) <= 1e-12 * scale;
}

double as_double(const Json& j) {
    if (j.is_string()) {
        const std::string s = j.get<std::string>();
        if (s == "nan") return std::numeric_limits<double>::quiet_NaN();
        if (s == "inf") return std::numeric_limits<double>::infinity();
        if (s == "-inf") return -std::numeric_limits<double>::infinity();
    }
    return j.get<double>();
}

Json load(const char* name) {
    const fs::path path = fs::path(VIZ_C_FIXTURE_DIR) / name;
    std::ifstream in(path);
    PWB_CHECK(in.good());
    std::stringstream buffer;
    buffer << in.rdbuf();
    Json parsed = Json::parse(buffer.str(), nullptr, false);
    PWB_CHECK(!parsed.is_discarded());
    return parsed;
}

void check_float(const Json& expected, double actual, const char* what) {
    const bool ok = same_float(as_double(expected), actual);
    if (!ok) {
        std::cout << "  mismatch (" << what << "): expected "
                  << std::setprecision(17) << as_double(expected)
                  << " got " << actual << "\n";
    }
    PWB_CHECK(ok);
}

// Python froze render maps as float32 arrays (.astype(np.float32)); the
// C++ scene keeps double, so parity is asserted at the float32 boundary.
void check_float32(const Json& expected, double actual, const char* what) {
    check_float(expected, static_cast<double>(static_cast<float>(actual)),
                what);
}

Corner corner_of(const Json& j, std::size_t index) {
    const Json& c = j[index];
    return {c[0].get<double>(), c[1].get<double>(), c[2].get<double>(),
            c[3].get<double>()};
}

}  // namespace

PWB_TEST(survey_corners_match_oracle) {
    const Json oracle = load("viz_c_joint_oracle.json");
    for (const Json& entry : oracle["survey"]["cases"]) {
        std::optional<std::int64_t> il_step;
        if (entry["kwargs"].contains("iline_step")) {
            il_step = entry["kwargs"]["iline_step"].get<std::int64_t>();
        }
        std::optional<std::int64_t> xl_step;
        if (entry["kwargs"].contains("xline_step")) {
            xl_step = entry["kwargs"]["xline_step"].get<std::int64_t>();
        }
        std::optional<std::int64_t> n_il;
        if (entry["kwargs"].contains("n_inlines")) {
            n_il = entry["kwargs"]["n_inlines"].get<std::int64_t>();
        }
        std::optional<std::int64_t> n_xl;
        if (entry["kwargs"].contains("n_crosslines")) {
            n_xl = entry["kwargs"]["n_crosslines"].get<std::int64_t>();
        }
        SurveySpec spec = survey_from_corners(
            corner_of(entry["corners"], 0), corner_of(entry["corners"], 1),
            corner_of(entry["corners"], 2),
            entry["kwargs"]["n_samples"].get<std::int64_t>(),
            entry["kwargs"]["dt_ms"].get<double>(),
            entry["kwargs"].value("t0_ms", 0.0), il_step, xl_step, n_il,
            n_xl);
        const Json& bg = entry["bin_grid"];
        check_float(bg["x_origin"], spec.bin_grid.x_origin, "x_origin");
        check_float(bg["y_origin"], spec.bin_grid.y_origin, "y_origin");
        check_float(bg["il_azimuth_deg"], spec.bin_grid.il_azimuth_deg,
                    "il_azimuth_deg");
        check_float(bg["il_spacing_m"], spec.bin_grid.il_spacing_m,
                    "il_spacing_m");
        check_float(bg["xl_spacing_m"], spec.bin_grid.xl_spacing_m,
                    "xl_spacing_m");
        PWB_CHECK(spec.iline_start ==
                  entry["iline_start"].get<std::int64_t>());
        PWB_CHECK(spec.iline_step ==
                  entry["iline_step"].get<std::int64_t>());
        PWB_CHECK(spec.xline_start ==
                  entry["xline_start"].get<std::int64_t>());
        PWB_CHECK(spec.xline_step ==
                  entry["xline_step"].get<std::int64_t>());
        PWB_CHECK(spec.n_inlines == entry["n_inlines"].get<std::int64_t>());
        PWB_CHECK(spec.n_crosslines ==
                  entry["n_crosslines"].get<std::int64_t>());
        PWB_CHECK(spec.n_samples == entry["n_samples"].get<std::int64_t>());
        check_float(entry["dt_ms"], spec.dt_ms, "dt_ms");
        const double xy[3][2] = {{0.0, 0.0}, {1500.25, -300.5},
                                 {-1e-3, 1e3}};
        for (int i = 0; i < 3; ++i) {
            const auto [il, xl] = spec.xy_to_il_xl(xy[i][0], xy[i][1]);
            const auto [x, y] = spec.il_xl_to_xy(il, xl);
            check_float(entry["xy_roundtrip"][i][0], x, "roundtrip x");
            check_float(entry["xy_roundtrip"][i][1], y, "roundtrip y");
        }
    }
    for (const Json& error : oracle["survey"]["errors"]) {
        PWB_CHECK(error["raised"].get<bool>());
    }
}

PWB_TEST(registration_matches_oracle) {
    const Json oracle = load("viz_c_joint_oracle.json");
    const Json& reg = oracle["registration"];
    SurveySpec spec = survey_from_corners(
        {1, 1, 1000.0, 2000.0}, {1, 10, 1900.0, 2000.0},
        {20, 10, 1900.0, 2600.0}, 64, 2.0);
    VolumeRegistration full(spec, 20, 10, 64);
    PWB_CHECK(full.strides()[0] == reg["full"]["strides"][0]);
    PWB_CHECK(full.strides()[1] == reg["full"]["strides"][1]);
    PWB_CHECK(full.strides()[2] == reg["full"]["strides"][2]);
    const double il_xl[3][2] = {{1, 1}, {20, 10}, {11.5, 3.25}};
    for (int i = 0; i < 3; ++i) {
        const auto [vi, vx] = full.il_xl_to_volume_idx(il_xl[i][0],
                                                       il_xl[i][1]);
        check_float(reg["full"]["idx"][i][0], vi, "idx il");
        check_float(reg["full"]["idx"][i][1], vx, "idx xl");
    }
    const double xy[2][2] = {{1000.0, 2000.0}, {1455.5, 2310.25}};
    for (int i = 0; i < 2; ++i) {
        const auto [vi, vx] = full.xy_to_volume_idx(xy[i][0], xy[i][1]);
        check_float(reg["full"]["xy_idx"][i][0], vi, "xy idx il");
        check_float(reg["full"]["xy_idx"][i][1], vx, "xy idx xl");
    }
    const double time_inputs[] = {0.0, 2.0, 63.0, 126.0, -4.0, 500.0};
    for (std::size_t i = 0; i < 6; ++i) {
        check_float(reg["full"]["time_idx"][i],
                    full.time_ms_to_sample_idx(time_inputs[i]),
                    "time idx known input");
    }
    const double sample_inputs[] = {0.0, 1.0, 31.5, 63.0};
    for (std::size_t i = 0; i < 4; ++i) {
        check_float(reg["full"]["sample_to_time"][i],
                    full.sample_idx_to_time_ms(sample_inputs[i]),
                    "sample->time");
    }
    const double idx_inputs[3][2] = {{0, 0}, {19, 9}, {5.5, 2.25}};
    for (int i = 0; i < 3; ++i) {
        const auto [il, xl] = full.volume_idx_to_il_xl(idx_inputs[i][0],
                                                       idx_inputs[i][1]);
        check_float(reg["full"]["idx_to_il_xl"][i][0], il, "idx->il");
        check_float(reg["full"]["idx_to_il_xl"][i][1], xl, "idx->xl");
    }
    const double clamp_inputs[3][3] = {{-3, 4, 2}, {100, -2, 70},
                                       {9, 4, 31.6}};
    for (int i = 0; i < 3; ++i) {
        const auto clamped =
            full.clamp_indices(clamp_inputs[i][0], clamp_inputs[i][1],
                               clamp_inputs[i][2]);
        PWB_CHECK(clamped[0] ==
                  reg["full"]["clamp"][i][0].get<std::int64_t>());
        PWB_CHECK(clamped[1] ==
                  reg["full"]["clamp"][i][1].get<std::int64_t>());
        PWB_CHECK(clamped[2] ==
                  reg["full"]["clamp"][i][2].get<std::int64_t>());
    }
    const double world_inputs[2][3] = {{1000, 2000, 0.0},
                                       {1900, 2600, 126.0}};
    for (int i = 0; i < 2; ++i) {
        const auto v = full.world_xyz_to_volume(
            world_inputs[i][0], world_inputs[i][1], world_inputs[i][2]);
        PWB_CHECK(v[0] ==
                  reg["full"]["world_xyz"][i][0].get<std::int64_t>());
        PWB_CHECK(v[1] ==
                  reg["full"]["world_xyz"][i][1].get<std::int64_t>());
        PWB_CHECK(v[2] ==
                  reg["full"]["world_xyz"][i][2].get<std::int64_t>());
    }

    VolumeRegistration preview =
        VolumeRegistration::from_survey_and_shape(spec, {10, 5, 32});
    PWB_CHECK(preview.strides()[0] ==
              reg["preview"]["strides"][0].get<std::int64_t>());
    PWB_CHECK(preview.strides()[2] ==
              reg["preview"]["strides"][2].get<std::int64_t>());
    const double preview_il_xl[3][2] = {{1, 1}, {11, 5}, {13, 7}};
    for (int i = 0; i < 3; ++i) {
        const auto [vi, vx] =
            preview.il_xl_to_volume_idx(preview_il_xl[i][0],
                                        preview_il_xl[i][1]);
        check_float(reg["preview"]["idx"][i][0], vi, "preview il");
        check_float(reg["preview"]["idx"][i][1], vx, "preview xl");
    }
    const double preview_time[] = {0.0, 4.0, 126.0};
    for (int i = 0; i < 3; ++i) {
        check_float(reg["preview"]["time_idx"][i],
                    preview.time_ms_to_sample_idx(preview_time[i]),
                    "preview time");
    }
    const double preview_sample[] = {0.0, 1.0, 31.0};
    for (int i = 0; i < 3; ++i) {
        check_float(reg["preview"]["sample_to_time"][i],
                    preview.sample_idx_to_time_ms(preview_sample[i]),
                    "preview sample");
    }
    VolumeRegistration explicit_strides(spec, 10, 5, 32, {2, 2, 2});
    PWB_CHECK(explicit_strides.strides()[0] ==
              reg["explicit_same_as_preview"][0].get<std::int64_t>());

    bool raised = false;
    try {
        VolumeRegistration(spec, 10, 5, 33, {2, 2, 2});
    } catch (const std::invalid_argument&) {
        raised = true;
    }
    PWB_CHECK(raised);
    raised = false;
    try {
        VolumeRegistration(spec, 21, 5, 32);
    } catch (const std::invalid_argument&) {
        raised = true;
    }
    PWB_CHECK(raised);
    raised = false;
    try {
        VolumeRegistration(spec, 10, 5, 32, {0, 1, 1});
    } catch (const std::invalid_argument&) {
        raised = true;
    }
    PWB_CHECK(raised);
}

PWB_TEST(depth_transform_matches_oracle) {
    const Json oracle = load("viz_c_joint_oracle.json");
    const Json& dt = oracle["depth_transform"];
    DepthTransformState states[] = {
        select_depth_transform(),
        select_depth_transform(true, 2400.0, false),
        select_depth_transform(false, 2800.5, true),
        DepthTransformState::well_tz_field(),
    };
    for (std::size_t i = 0; i < 4; ++i) {
        const Json& expected = dt["cases"][i];
        PWB_CHECK(states[i].available() ==
                  expected["available"].get<bool>());
        const auto& warning = states[i].approximate_warning();
        if (expected["warning"].is_null()) {
            PWB_CHECK(!warning.has_value());
        } else {
            PWB_CHECK(warning.has_value());
            PWB_CHECK(*warning == expected["warning"].get<std::string>());
        }
        if (expected.contains("t2d")) {
            const double t2d_inputs[] = {0.0, 100.0, 2500.5};
            for (int k = 0; k < 3; ++k) {
                check_float(expected["t2d"][k],
                            states[i].time_ms_to_depth_m(t2d_inputs[k]),
                            "t2d");
            }
            const double d2t_inputs[] = {0.0, 150.0, 3000.0};
            for (int k = 0; k < 3; ++k) {
                check_float(expected["d2t"][k],
                            states[i].depth_m_to_time_ms(d2t_inputs[k]),
                            "d2t");
            }
        }
    }
    bool raised = false;
    try {
        ConstantVelocityDepth velocity(0.0);
        (void)velocity;
    } catch (const std::invalid_argument&) {
        raised = true;
    }
    PWB_CHECK(raised);
}

PWB_TEST(td_table_and_geometry_match_oracle) {
    const Json oracle = load("viz_c_joint_oracle.json");
    const Json& geo = oracle["td_and_geometry"];
    TimeDepthTable td("W-1", {0.0, 200.0, 700.0, 1500.0},
                      {0.0, 250.0, 1000.0, 2000.0});
    const auto [lo, hi] = td.md_range();
    check_float(geo["td"]["md_range"][0], lo, "md lo");
    check_float(geo["td"]["md_range"][1], hi, "md hi");
    const double md_inputs[] = {-1.0, 0.0, 125.0, 250.0,
                                1500.0, 2000.0, 2500.0};
    for (std::size_t i = 0; i < 7; ++i) {
        check_float(geo["td"]["md_to_time"][i], td.md_to_time_ms(md_inputs[i]),
                    "md->time");
    }
    const double t_inputs[] = {-5.0, 0.0, 200.0, 900.0, 1500.0, 2000.0};
    for (std::size_t i = 0; i < 6; ++i) {
        check_float(geo["td"]["time_to_md"][i], td.time_ms_to_md(t_inputs[i]),
                    "time->md");
    }

    WellHead well;
    well.name = "W-1";
    well.x = 1200.0;
    well.y = 2100.0;
    well.bottom_x = 1230.0;
    well.bottom_y = 2130.0;
    well.total_depth_m = 2000.0;
    well.id = "w1";
    WellTrajectory3D traj =
        project_well_trajectory(well, VerticalDomain::Time, &td, 8);
    const Json& frozen = geo["trajectory_time"];
    PWB_CHECK(traj.points.size() ==
              static_cast<std::size_t>(frozen["n_points"].get<int>()));
    PWB_CHECK(traj.has_td == frozen["has_td"].get<bool>());
    PWB_CHECK(traj.warning.has_value() != frozen["warning"].is_null());
    for (int k = 0; k < 3; ++k) {
        check_float(frozen["head"][k], traj.points[0][k], "head");
        check_float(frozen["first"][k], traj.points[1][k], "first");
        check_float(frozen["last"][k], traj.points.back()[k], "last");
    }

    WellHead deep;
    deep.name = "W-deep";
    deep.total_depth_m = 4000.0;
    deep.id = "w2";
    TimeDepthTable short_td("W-deep", {0.0, 400.0}, {0.0, 1000.0});
    WellTrajectory3D truncated =
        project_well_trajectory(deep, VerticalDomain::Time, &short_td, 8);
    const Json& frozen_deep = geo["trajectory_time_deep_truncated"];
    PWB_CHECK(truncated.points.size() ==
              static_cast<std::size_t>(frozen_deep["n_points"].get<int>()));
    PWB_CHECK(truncated.warning.has_value());
    PWB_CHECK(*truncated.warning ==
              frozen_deep["warning"].get<std::string>());
    check_float(frozen_deep["last_md_z"], truncated.points.back()[2],
                "truncated last z");

    WellTrajectory3D no_td =
        project_well_trajectory(well, VerticalDomain::Time, nullptr);
    const Json& frozen_no_td = geo["trajectory_time_no_td"];
    PWB_CHECK(no_td.points.size() ==
              static_cast<std::size_t>(frozen_no_td["n_points"].get<int>()));
    PWB_CHECK(no_td.has_td == frozen_no_td["has_td"].get<bool>());
    PWB_CHECK(no_td.warning.has_value());
    PWB_CHECK(*no_td.warning ==
              frozen_no_td["warning"].get<std::string>());

    WellTrajectory3D depth_none = project_well_trajectory(
        well, VerticalDomain::Depth, &td, 8, nullptr);
    const Json& frozen_depth_none = geo["trajectory_depth_no_transform"];
    PWB_CHECK(depth_none.points.size() ==
              static_cast<std::size_t>(
                  frozen_depth_none["n_points"].get<int>()));
    PWB_CHECK(depth_none.warning.has_value());
    PWB_CHECK(*depth_none.warning ==
              frozen_depth_none["warning"].get<std::string>());

    DepthTransformState v0 = select_depth_transform(false, 2500.0, true);
    WellTrajectory3D depth_v0 = project_well_trajectory(
        well, VerticalDomain::Depth, &td, 8, &v0);
    const Json& frozen_depth_v0 = geo["trajectory_depth_v0"];
    PWB_CHECK(depth_v0.points.size() ==
              static_cast<std::size_t>(
                  frozen_depth_v0["n_points"].get<int>()));
    for (int k = 0; k < 3; ++k) {
        check_float(frozen_depth_v0["last"][k], depth_v0.points.back()[k],
                    "depth last");
    }

    std::vector<std::array<double, 3>> pierce_pts = {
        {0.0, 0.0, 0.0}, {10.0, 0.0, 100.0}, {10.0, 5.0, 200.0}};
    const struct {
        const char* key;
        double z;
        bool present;
    } pierce_cases[] = {
        {"at_100", 100.0, true},   {"at_50", 50.0, true},
        {"at_exact_200", 200.0, true}, {"outside", 500.0, false},
        {"below", -1.0, false},
    };
    for (const auto& pc : pierce_cases) {
        const auto hit = pierce_xy_at_z(pierce_pts, pc.z);
        PWB_CHECK(hit.has_value() == pc.present);
        if (hit.has_value()) {
            check_float(geo["pierce"][pc.key][0], hit->first, "pierce x");
            check_float(geo["pierce"][pc.key][1], hit->second, "pierce y");
        } else {
            PWB_CHECK(geo["pierce"][pc.key].is_null());
        }
    }

    std::vector<std::array<float, 3>> path = {{0, 0, 0}, {0, 0, 1},
                                              {0, 0, 2}, {0, 0, 3}};
    std::vector<float> curve = {0.0f, 1.0f, -1.0f, 0.5f};
    const auto overlay = offset_curve_along_trajectory(path, curve, 2.0f);
    PWB_CHECK(overlay.size() == 4);
    for (std::size_t i = 0; i < 4; ++i) {
        for (int k = 0; k < 3; ++k) {
            check_float32(geo["overlay"][i][k], overlay[i][k], "overlay");
        }
    }
    bool raised = false;
    try {
        offset_curve_along_trajectory(path, {0.0f, 1.0f});
    } catch (const std::invalid_argument&) {
        raised = true;
    }
    PWB_CHECK(raised);
}

PWB_TEST(fence_and_probe_match_oracle) {
    const Json oracle = load("viz_c_joint_oracle.json");
    const Json& fp = oracle["fence_probe"];
    SurveySpec spec = survey_from_corners(
        {1, 1, 1000.0, 2000.0}, {1, 10, 1900.0, 2000.0},
        {20, 10, 1900.0, 2600.0}, 64, 2.0);
    const std::int64_t ni = 20, nx = 10, nt = 64;
    std::vector<float> data(static_cast<std::size_t>(ni * nx * nt));
    for (std::int64_t i = 0; i < ni; ++i) {
        for (std::int64_t x = 0; x < nx; ++x) {
            for (std::int64_t t = 0; t < nt; ++t) {
                double value =
                    static_cast<double>((i * 7 + x * 3 + t) % 97) - 48.0;
                if (i == 0 && x == 0 && t == 0) {
                    value = std::numeric_limits<float>::quiet_NaN();
                } else if (i == 19 && x == 9 && t == 63) {
                    value = std::numeric_limits<float>::infinity();
                }
                data[static_cast<std::size_t>((i * nx + x) * nt + t)] =
                    static_cast<float>(value);
            }
        }
    }
    InMemoryVolumeAccess access(data, {ni, nx, nt});
    std::vector<std::array<double, 2>> vertices = {
        {1000.0, 2000.0}, {1900.0, 2000.0}, {1900.0, 2600.0}};
    const auto sampled = sample_fence_polyline(vertices, 5);
    PWB_CHECK(sampled.size() == fp["sample_polyline"].size());
    for (std::size_t i = 0; i < sampled.size(); ++i) {
        check_float(fp["sample_polyline"][i][0], sampled[i][0],
                    "polyline x");
        check_float(fp["sample_polyline"][i][1], sampled[i][1],
                    "polyline y");
    }

    FenceSection fence("F1", vertices, "fence-1");
    VolumeRegistration registration =
        VolumeRegistration::from_survey_and_shape(spec, {ni, nx, nt});
    std::vector<double> sample_axis(static_cast<std::size_t>(nt));
    for (std::int64_t t = 0; t < nt; ++t) {
        sample_axis[static_cast<std::size_t>(t)] =
            static_cast<double>(t) * 2.0;
    }
    FenceExtraction extraction = extract_fence_strip(
        access, fence, spec, 4, sample_axis, &registration);
    const Json& frozen = fp["extract"];
    PWB_CHECK(extraction.fence_id == frozen["fence_id"].get<std::string>());
    PWB_CHECK(extraction.n_along() == frozen["shape"][0].get<int>());
    PWB_CHECK(extraction.n_sample() == frozen["shape"][1].get<int>());
    for (int i = 0; i < 4; ++i) {
        check_float(frozen["arc_length"][i], extraction.arc_length_m[i],
                    "arc");
    }
    for (int k = 0; k < 8; ++k) {
        check_float(frozen["row0_first8"][k],
                    extraction.amplitude[static_cast<std::size_t>(k)],
                    "row0");
        check_float(frozen["row3_last8"][k],
                    extraction.amplitude[static_cast<std::size_t>(
                        3 * nt + (nt - 8 + k))],
                    "row3");
    }
    for (int k = 0; k < 4; ++k) {
        check_float(frozen["sample_axis_first4"][k],
                    extraction.sample_axis[static_cast<std::size_t>(k)],
                    "axis");
    }

    ProbeState probe = probe_from_fence_s(500.0, 100.0, vertices, &spec);
    check_float(fp["probe"]["s_m"], probe.s_m, "probe s");
    check_float(fp["probe"]["z"], probe.z, "probe z");
    check_float(fp["probe"]["x"], probe.x, "probe x");
    check_float(fp["probe"]["y"], probe.y, "probe y");
    check_float(fp["probe"]["il"], probe.il, "probe il");
    check_float(fp["probe"]["xl"], probe.xl, "probe xl");
    const auto indices = probe.slice_indices(&spec);
    PWB_CHECK(indices[0] ==
              fp["probe"]["slice_indices"][0].get<std::int64_t>());
    PWB_CHECK(indices[1] ==
              fp["probe"]["slice_indices"][1].get<std::int64_t>());
    PWB_CHECK(indices[2] ==
              fp["probe"]["slice_indices"][2].get<std::int64_t>());
    const auto no_survey = probe.slice_indices(nullptr);
    PWB_CHECK(no_survey[2] ==
              fp["probe"]["slice_indices_none"][2].get<std::int64_t>());

    bool raised = false;
    try {
        FenceSection bad("bad", {{{0.0, 0.0}}});
        (void)bad;
    } catch (const std::invalid_argument&) {
        raised = true;
    }
    PWB_CHECK(raised);
}

PWB_TEST(color_scales_match_oracle) {
    const Json oracle = load("viz_c_joint_oracle.json");
    const Json& cs = oracle["color_scales"];
    std::vector<float> amp = {
        -100.0f, -50.0f, -0.001f, 0.0f, 0.001f, 30.0f, 80.0f,
        std::numeric_limits<float>::quiet_NaN(),
        1e9f, -1e9f, 0.5f, 127.5f, 12.75f};
    const auto rgba = colorize_amplitude(amp);
    PWB_CHECK(rgba.size() == amp.size() * 4);
    for (std::size_t i = 0; i < rgba.size(); ++i) {
        if (rgba[i] != cs["amplitude_rgba"][i].get<int>()) {
            std::cout << "  amplitude rgba[" << i << "]: expected "
                      << cs["amplitude_rgba"][i].get<int>() << " got "
                      << static_cast<int>(rgba[i]) << "\n";
        }
        PWB_CHECK(rgba[i] ==
                  static_cast<std::uint8_t>(
                      cs["amplitude_rgba"][i].get<int>()));
    }
    std::vector<double> gr = {0.0, 0.25, 0.5, 0.75, 1.0, 0.125,
                              std::numeric_limits<double>::quiet_NaN(),
                              0.99999, -3.0, 4.0};
    const auto gr_rgba = colorize_gr(gr, {0.0, 1.0});
    for (std::size_t i = 0; i < gr_rgba.size(); ++i) {
        PWB_CHECK(gr_rgba[i] ==
                  static_cast<std::uint8_t>(cs["gr_rgba"][i].get<int>()));
    }
    const auto cividis = colorize_gr(gr, {0.0, 1.0}, "cividis");
    for (std::size_t i = 0; i < cividis.size(); ++i) {
        PWB_CHECK(cividis[i] ==
                  static_cast<std::uint8_t>(
                      cs["gr_rgba_cividis"][i].get<int>()));
    }
    const auto bad_range = colorize_gr({5.0}, {2.0, 2.0});
    for (std::size_t i = 0; i < bad_range.size(); ++i) {
        PWB_CHECK(bad_range[i] ==
                  static_cast<std::uint8_t>(
                      cs["gr_bad_range"][i].get<int>()));
    }
}

PWB_TEST(scene_maps_and_state_match_oracle) {
    const Json oracle = load("viz_c_joint_oracle.json");
    const Json& frozen = oracle["scene"];
    SurveySpec spec = survey_from_corners(
        {1, 1, 1000.0, 2000.0}, {1, 10, 1900.0, 2000.0},
        {20, 10, 1900.0, 2600.0}, 64, 2.0);
    const std::int64_t ni = 20, nx = 10, nt = 64;
    std::vector<float> data(static_cast<std::size_t>(ni * nx * nt));
    for (std::int64_t i = 0; i < ni; ++i) {
        for (std::int64_t x = 0; x < nx; ++x) {
            for (std::int64_t t = 0; t < nt; ++t) {
                data[static_cast<std::size_t>((i * nx + x) * nt + t)] =
                    static_cast<float>(
                        static_cast<double>((i * 11 + x * 5 + t * 2) % 89) -
                        44.0);
            }
        }
    }
    WellSeismicScene scene;
    scene.set_survey(spec);
    scene.set_volume_access(std::make_shared<InMemoryVolumeAccess>(
        data, std::array<std::int64_t, 3>{ni, nx, nt}));
    TimeDepthTable td("W-1", {0.0, 300.0, 1200.0}, {0.0, 500.0, 1800.0});
    WellHead well;
    well.name = "W-1";
    well.x = 1200.0;
    well.y = 2100.0;
    well.bottom_x = 1230.0;
    well.bottom_y = 2130.0;
    well.total_depth_m = 1800.0;
    well.id = "w1";
    scene.set_wells({well}, {{"W-1", td}});
    scene.add_time_slice(64.0);
    scene.add_time_slice(20.0);

    const std::vector<std::array<double, 3>> world = {
        {1000.0, 2000.0, 0.0}, {1450.0, 2300.0, 64.0},
        {1900.0, 2600.0, 126.0}, {1300.0, 2200.0, -10.0}};
    const auto render = scene.world_to_render_xyz_array(world);
    PWB_CHECK(render.size() == 4);
    for (std::size_t i = 0; i < 4; ++i) {
        for (int k = 0; k < 3; ++k) {
            check_float32(frozen["render"][i][k], render[i][k], "render");
        }
    }
    const auto back = scene.render_to_world_xyz_array(render);
    for (std::size_t i = 0; i < 4; ++i) {
        for (int k = 0; k < 3; ++k) {
            check_float32(frozen["render_back"][i][k], back[i][k],
                          "render back");
        }
    }

    const OrthogonalSliceState& state = scene.orthogonal_slice_state();
    PWB_CHECK(state.inline_index.has_value() ==
              frozen["slice_state"]["il"].is_number_integer());
    if (state.inline_index.has_value()) {
        PWB_CHECK(*state.inline_index ==
                  frozen["slice_state"]["il"].get<std::int64_t>());
    }
    PWB_CHECK(state.crossline_index.has_value() ==
              frozen["slice_state"]["xl"].is_number_integer());
    PWB_CHECK(state.time_slices.size() ==
              frozen["slice_state"]["slices"].size());
    for (std::size_t i = 0; i < state.time_slices.size(); ++i) {
        check_float(frozen["slice_state"]["slices"][i][0],
                    state.time_slices[i].time_ms, "slice time");
        PWB_CHECK(state.time_slices[i].visible ==
                  frozen["slice_state"]["slices"][i][1].get<bool>());
    }
    check_float(frozen["slice_state"]["active"],
                state.active_time_ms.value_or(0.0), "active");
    check_float(frozen["slice_state"]["opacity"], state.time_opacity,
                "opacity");
    PWB_CHECK(scene.slice_state_warning() ==
              frozen["slice_state"]["warning"].get<std::string>());

    const auto rs = scene.orthogonal_slice_render_state();
    PWB_CHECK(rs.has_value());
    if (rs.has_value()) {
        PWB_CHECK(std::get<0>(*rs) ==
                  frozen["render_state"]["il"].get<std::int64_t>());
        PWB_CHECK(std::get<1>(*rs) ==
                  frozen["render_state"]["xl"].get<std::int64_t>());
        PWB_CHECK(std::get<3>(*rs) ==
                  frozen["render_state"]["active"].get<std::int64_t>());
        check_float(frozen["render_state"]["opacity"], std::get<4>(*rs),
                    "rs opacity");
        PWB_CHECK(std::get<2>(*rs).size() ==
                  frozen["render_state"]["times"].size());
    }

    const double snap_inputs[] = {0.0, 3.9, 5.0, 126.0, 130.0, -3.0};
    for (std::size_t i = 0; i < 6; ++i) {
        check_float(frozen["snap"][i], scene.snap_time_ms(snap_inputs[i]),
                    "snap");
    }

    const auto ok = scene.validate_against_corners(
        {1, 1, 1000.0, 2000.0}, {1, 10, 1900.0, 2000.0},
        {20, 10, 1900.0, 2600.0});
    PWB_CHECK(ok.first == frozen["validate_corners"]["ok"].get<bool>());
    const auto bad = scene.validate_against_corners(
        {1, 1, 1000.0, 2000.0}, {1, 10, 1900.0, 2000.0},
        {20, 10, 2900.0, 2600.0});
    PWB_CHECK(bad.first == frozen["validate_corners"]["bad_ok"].get<bool>());

    bool refused = false;
    try {
        scene.set_vertical_domain(VerticalDomain::Depth);
    } catch (const std::invalid_argument&) {
        refused = true;
    }
    PWB_CHECK(refused == frozen["depth_refused"].is_string());

    const auto pierce = scene.pierce_points_on_active_time();
    PWB_CHECK(pierce.size() ==
              static_cast<std::size_t>(frozen["pierce"]["count"].get<int>()));
    if (!pierce.empty()) {
        check_float(frozen["pierce"]["first"][0], pierce[0].x, "pierce x");
        check_float(frozen["pierce"]["first"][1], pierce[0].y, "pierce y");
        check_float(frozen["pierce"]["first"][2], pierce[0].z, "pierce z");
    }
    bool fence_raised = false;
    try {
        scene.add_well_to_well_fence({"w1"});
    } catch (const std::invalid_argument&) {
        fence_raised = true;
    }
    PWB_CHECK(fence_raised ==
              frozen["fence_well_flow"]["single_well_raised"].is_string());

    WellSeismicScene scene2;
    scene2.set_survey(spec);
    const auto survey_only = scene2.world_to_render_xyz_array(world);
    for (std::size_t i = 0; i < 4; ++i) {
        for (int k = 0; k < 3; ++k) {
            check_float32(frozen["survey_only_render"][i][k],
                          survey_only[i][k], "survey only");
        }
    }
}

PWB_TEST(tampered_fixture_is_detected) {
    // Negative self-check: the tampered oracle must NOT match the C++
    // colorization — a comparator that passed here would be vacuous.
    const Json tampered = load("viz_c_joint_oracle_tampered.json");
    std::vector<float> amp = {
        -100.0f, -50.0f, -0.001f, 0.0f, 0.001f, 30.0f, 80.0f,
        std::numeric_limits<float>::quiet_NaN(),
        1e9f, -1e9f, 0.5f, 127.5f, 12.75f};
    const auto rgba = colorize_amplitude(amp);
    int mismatches = 0;
    for (std::size_t i = 0; i < rgba.size(); ++i) {
        if (rgba[i] !=
            static_cast<std::uint8_t>(
                tampered["color_scales"]["amplitude_rgba"][i].get<int>())) {
            ++mismatches;
        }
    }
    PWB_CHECK(mismatches > 0);
}

PWB_TEST(oracle_actually_compared_values) {
    // Guard against a silently-skipped comparator: the replay must have
    // compared a meaningful number of floats.
    PWB_CHECK(g_compared > 200);
}
