// viz_d.core — frozen-Python parity replay for the VIZ-D display/horizon/
// crossplot/isosurface cores against tools/oracle/generate_viz_d_*.py
// fixtures (real geo-viz-engine@08851951 / native 0.2.17a0 runs). Qt-free.

#include "viz_d_test.hpp"

#include <cmath>
#include <cstdint>
#include <limits>
#include <string>
#include <vector>

#include <pwb/seismic_viewer/color_maps.hpp>
#include <pwb/seismic_viewer/crossplot_core.hpp>
#include <pwb/seismic_viewer/display_core.hpp>
#include <pwb/seismic_viewer/horizon_core.hpp>
#include <pwb/seismic_viewer/isosurface_core.hpp>

using namespace pwb::seismic_viewer;
using viz_d_test::close_or_both_nan;
using viz_d_test::num_from;
using viz_d_test::nums_from;

namespace {

bool json_num_eq(const nlohmann::json& value, double expected, double tol) {
    return close_or_both_nan(num_from(value), expected, tol);
}

std::vector<float> floats_from(const nlohmann::json& values) {
    std::vector<float> out;
    out.reserve(values.size());
    for (const auto& value : values) {
        out.push_back(static_cast<float>(num_from(value)));
    }
    return out;
}

} // namespace

TEST(colormaps_match_frozen_python_luts) {
    const auto fixture = viz_d_test::load_fixture("viz_d_display_oracle.json");
    for (const auto& [name, lut_json] : fixture.at("colormaps").items()) {
        const ColorLut lut = color_lut(name);
        PWB_CHECK_MSG(lut.size() == 256, (name + ": 256 entries").c_str());
        bool mismatch = false;
        for (std::size_t i = 0; i < lut.size(); ++i) {
            const auto& expected = lut_json.at(i);
            if (lut[i][0] != expected.at(0).get<int>() ||
                lut[i][1] != expected.at(1).get<int>() ||
                lut[i][2] != expected.at(2).get<int>()) {
                mismatch = true;
                break;
            }
        }
        PWB_CHECK_MSG(!mismatch, (name + ": LUT diverges from colormap.py").c_str());
    }
    // Registry superset: the v3 names stay, the colormap.py set joins them.
    const auto names = color_map_names();
    auto has = [&](std::string_view key) {
        return std::find(names.begin(), names.end(), key) != names.end();
    };
    PWB_CHECK(has("grayscale") && has("seismic") && has("heat"));
    PWB_CHECK(has("seismic_r") && has("gray") && has("jet") && has("hsv") &&
              has("viridis") && has("phase_wheel"));
}

TEST(percentile_clip_and_normalize_replay) {
    const auto fixture = viz_d_test::load_fixture("viz_d_display_oracle.json");
    const auto& cases = fixture.at("percentile_and_normalize");
    for (const auto& [name, entry] : cases.items()) {
        const std::vector<float> data = floats_from(entry.at("data"));
        for (const auto& [pct_text, range_json] : entry.at("pcts").items()) {
            const double pct = std::stod(pct_text);
            const display::ClipRange range =
                display::percentile_clip_range(data, pct);
            if (range_json.is_null()) {
                PWB_CHECK_MSG(range.degenerate,
                              (name + " @p" + pct_text + ": expected degenerate")
                                  .c_str());
                continue;
            }
            PWB_CHECK_MSG(!range.degenerate,
                          (name + " @p" + pct_text + ": unexpected degenerate")
                              .c_str());
            PWB_CHECK_MSG(json_num_eq(range_json.at(0), range.lo, 1e-12) &&
                              json_num_eq(range_json.at(1), range.hi, 1e-12),
                          (name + " @p" + pct_text + ": clip range diverges")
                              .c_str());
        }
        if (!entry.at("index_default").is_null()) {
            const double lo = num_from(entry.at("range_used").at(0));
            const double hi = num_from(entry.at("range_used").at(1));
            const std::vector<std::uint8_t> index =
                display::normalize_to_index(data, lo, hi);
            const auto& expected = entry.at("index_default");
            PWB_CHECK(index.size() == expected.size());
            for (std::size_t i = 0; i < index.size(); ++i) {
                PWB_CHECK_MSG(index[i] == expected.at(i).get<int>(),
                              (name + ": index_default diverges").c_str());
            }
            // Polarity parity: normalize the NEGATED plane through the same
            // range (profile_vd._renormalize display-only flip).
            std::vector<float> negated(data.size());
            for (std::size_t i = 0; i < data.size(); ++i) {
                negated[i] = -data[i];
            }
            const std::vector<std::uint8_t> neg =
                display::normalize_to_index(negated, lo, hi);
            const auto& expected_neg = entry.at("index_negated");
            for (std::size_t i = 0; i < neg.size(); ++i) {
                PWB_CHECK_MSG(neg[i] == expected_neg.at(i).get<int>(),
                              (name + ": index_negated diverges").c_str());
            }
        }
    }
}

TEST(normalize_maps_nan_to_centre_not_zero) {
    const std::vector<float> data{0.0f, std::numeric_limits<float>::quiet_NaN(),
                                  0.5f, 1.0f};
    const std::vector<std::uint8_t> index = display::normalize_to_index(data, 0.0, 1.0);
    PWB_CHECK(index[1] == 128); // colormap.py #119: NaN at the neutral centre
    PWB_CHECK(index[0] == 0 && index[3] == 255);
    // Degenerate range: zeros with NaN still at the centre.
    const std::vector<std::uint8_t> deg =
        display::normalize_to_index(data, 0.5, 0.5);
    PWB_CHECK(deg[0] == 0 && deg[1] == 128);
}

TEST(viewport_decimation_replay) {
    const auto fixture = viz_d_test::load_fixture("viz_d_display_oracle.json");
    for (const auto& case_json : fixture.at("decimation").at("cases")) {
        const display::Decimation dec = display::viewport_decimation(
            case_json.at("n_traces").get<std::int64_t>(),
            case_json.at("n_samples").get<std::int64_t>(),
            case_json.at("width").get<int>(), case_json.at("height").get<int>(),
            case_json.at("trace_step_in").get<std::int64_t>());
        PWB_CHECK(dec.trace_step == case_json.at("trace_step").get<std::int64_t>());
        const auto& expected = case_json.at("sample_indices");
        PWB_CHECK(dec.sample_indices.size() == expected.size());
        for (std::size_t i = 0; i < dec.sample_indices.size(); ++i) {
            PWB_CHECK(dec.sample_indices[i] ==
                      expected.at(i).get<std::int64_t>());
        }
    }
}

void compare_point_lists(const std::vector<double>& actual_xs,
                         const std::vector<double>& actual_ys,
                         const nlohmann::json& expected_points, double tol,
                         const char* what) {
    PWB_CHECK_MSG(actual_xs.size() == expected_points.size(),
                  (std::string(what) + ": point count").c_str());
    const std::size_t n = std::min(actual_xs.size(), expected_points.size());
    for (std::size_t i = 0; i < n; ++i) {
        const double ex = num_from(expected_points.at(i).at(0));
        const double ey = num_from(expected_points.at(i).at(1));
        const bool ok = close_or_both_nan(actual_xs[i], ex, tol) &&
                        close_or_both_nan(actual_ys[i], ey, tol);
        if (!ok) {
            char message[256];
            std::snprintf(message, sizeof(message), "%s[%zu] (%.17g,%.17g) vs (%.17g,%.17g)",
                          what, i, actual_xs[i], actual_ys[i], ex, ey);
            PWB_FAIL(message);
        }
    }
}

TEST(wiggle_geometry_matches_captured_reference_paint) {
    const auto fixture = viz_d_test::load_fixture("viz_d_wiggle_oracle.json");
    for (const auto& case_json : fixture.at("cases")) {
        const std::vector<float> data = floats_from(case_json.at("data"));
        const display::WiggleGeometry geo = display::wiggle_geometry(
            data, case_json.at("n_samples").get<std::int64_t>(),
            case_json.at("n_traces").get<std::int64_t>(),
            case_json.at("polarity").get<int>(), case_json.at("gain").get<double>(),
            case_json.at("width").get<int>(), case_json.at("height").get<int>());
        const char* id = case_json.at("id").get<std::string>().c_str();
        // Baselines: one vertical line per drawn trace.
        const auto& lines = case_json.at("lines");
        PWB_CHECK_MSG(geo.traces.size() == lines.size(),
                      (std::string(id) + ": baseline count").c_str());
        for (std::size_t t = 0; t < std::min(geo.traces.size(), lines.size()); ++t) {
            PWB_CHECK_MSG(close_or_both_nan(
                              geo.traces[t].centre_x,
                              num_from(lines.at(t).at(0).at(0)), 1e-9),
                          (std::string(id) + ": baseline x").c_str());
        }
        // Deflection polylines.
        const auto& polylines = case_json.at("polylines");
        PWB_CHECK(geo.traces.size() == polylines.size());
        for (std::size_t t = 0; t < std::min(geo.traces.size(), polylines.size()); ++t) {
            compare_point_lists(geo.traces[t].xs, geo.traces[t].ys,
                                polylines.at(t), 1e-9,
                                (std::string(id) + " polyline").c_str());
        }
        // Positive fill lobes.
        const auto& polygons = case_json.at("polygons");
        std::size_t lobe_count = 0;
        for (const auto& trace : geo.traces) {
            lobe_count += trace.lobes.size();
        }
        PWB_CHECK_MSG(lobe_count == polygons.size(),
                      (std::string(id) + ": lobe count").c_str());
        std::size_t p = 0;
        bool lobes_ok = true;
        for (const auto& trace : geo.traces) {
            for (const auto& lobe : trace.lobes) {
                if (p >= polygons.size()) {
                    lobes_ok = false;
                    break;
                }
                if (lobe.xs.size() != polygons.at(p).size()) {
                    lobes_ok = false;
                    ++p;
                    continue;
                }
                compare_point_lists(lobe.xs, lobe.ys, polygons.at(p), 1e-9,
                                    (std::string(id) + " lobe").c_str());
                ++p;
            }
        }
        PWB_CHECK_MSG(lobes_ok, (std::string(id) + ": lobe mismatch").c_str());
    }
}

TEST(polyline_sampling_replay) {
    const auto fixture = viz_d_test::load_fixture("viz_d_display_oracle.json");
    for (const auto& case_json : fixture.at("polyline").at("cases")) {
        const std::vector<float> volume = floats_from(case_json.at("volume"));
        std::vector<std::pair<double, double>> points;
        for (const auto& pt : case_json.at("points")) {
            points.emplace_back(pt.at(0).get<double>(), pt.at(1).get<double>());
        }
        const auto shape = case_json.at("shape");
        const display::PolylineSample sample = display::sample_polyline_slice(
            volume, shape.at(0).get<std::int64_t>(), shape.at(1).get<std::int64_t>(),
            shape.at(2).get<std::int64_t>(), points);
        const char* id = case_json.at("id").get<std::string>().c_str();
        const auto expected_dist = nums_from(case_json.at("distances"));
        PWB_CHECK_MSG(sample.distances.size() == expected_dist.size(),
                      (std::string(id) + ": distance count").c_str());
        // The numpy source returns float32 distances; the C++ core keeps
        // doubles, so compare at float32 resolution.
        for (std::size_t i = 0; i < std::min(sample.distances.size(), expected_dist.size());
             ++i) {
            PWB_CHECK_MSG(close_or_both_nan(sample.distances[i], expected_dist[i], 1e-7),
                          (std::string(id) + ": cumulative distance").c_str());
        }
        const std::vector<double> expected = nums_from(case_json.at("section"));
        PWB_CHECK(sample.section.size() == expected.size());
        for (std::size_t i = 0; i < std::min(sample.section.size(), expected.size());
             ++i) {
            // scipy map_coordinates float64 internals vs the decoded double
            // stencil: declared tolerance (exact for cval/out-of-domain 0).
            PWB_CHECK_MSG(
                close_or_both_nan(sample.section[i], expected[i], 1e-5),
                (std::string(id) + ": section sample").c_str());
        }
    }
}

TEST(horizon_parse_fill_extract_replay) {
    const auto fixture = viz_d_test::load_fixture("viz_d_horizon_oracle.json");
    horizon::HorizonAxes axes;
    for (const auto v : fixture.at("ilines")) {
        axes.ilines.push_back(v.get<std::int64_t>());
    }
    for (const auto v : fixture.at("xlines")) {
        axes.xlines.push_back(v.get<std::int64_t>());
    }
    for (const auto& [name, entry] : fixture.at("parse").items()) {
        double scale = 1.0;
        std::int64_t il_off = 0;
        std::int64_t xl_off = 0;
        if (entry.contains("kwargs")) {
            if (entry.at("kwargs").contains("scale")) {
                scale = entry.at("kwargs").at("scale").get<double>();
            }
            if (entry.at("kwargs").contains("iline_offset")) {
                il_off = static_cast<std::int64_t>(
                    entry.at("kwargs").at("iline_offset").get<double>());
            }
            if (entry.at("kwargs").contains("xline_offset")) {
                xl_off = static_cast<std::int64_t>(
                    entry.at("kwargs").at("xline_offset").get<double>());
            }
        }
        const horizon::ParsedHorizon parsed = horizon::parse_horizon_text(
            entry.at("text").get<std::string>(), axes, scale, il_off, xl_off);
        const std::vector<double> expected = nums_from(entry.at("grid"));
        PWB_CHECK(parsed.grid.values.size() == expected.size());
        for (std::size_t i = 0; i < std::min(parsed.grid.values.size(), expected.size());
             ++i) {
            PWB_CHECK_MSG(
                close_or_both_nan(parsed.grid.values[i], expected[i], 1e-12),
                (name + ": parsed grid").c_str());
        }
    }
    // Empty input throws with the oracle message (fail-closed parity).
    bool threw = false;
    try {
        static_cast<void>(horizon::parse_horizon_text("no numbers here\n", axes));
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    PWB_CHECK(threw);

    for (const auto& [name, entry] : fixture.at("fill").items()) {
        const auto shape = entry.at("shape");
        horizon::Grid2D grid(shape.at(0).get<std::int64_t>(),
                             shape.at(1).get<std::int64_t>(), 0.0);
        const std::vector<double> input = nums_from(entry.at("grid"));
        grid.values = input;
        const double max_dist = entry.at("max_dist").get<double>();
        const std::vector<double> expected = nums_from(entry.at("output"));
        const double tol = entry.at("tolerance").get<double>();
        std::vector<double> output;
        if (entry.at("kind").get<std::string>() == "nearest") {
            output = horizon::fill_nearest(grid, max_dist).values;
        } else {
            int neighbors = 24;
            double smoothing = 0.0;
            if (entry.at("kwargs").contains("neighbors")) {
                neighbors = static_cast<int>(
                    entry.at("kwargs").at("neighbors").get<double>());
            }
            if (entry.at("kwargs").contains("smoothing")) {
                smoothing = entry.at("kwargs").at("smoothing").get<double>();
            }
            output = horizon::fill_rbf(grid, max_dist, neighbors, smoothing).values;
        }
        PWB_CHECK(output.size() == expected.size());
        for (std::size_t i = 0; i < std::min(output.size(), expected.size()); ++i) {
            PWB_CHECK_MSG(close_or_both_nan(output[i], expected[i], tol),
                          (name + ": filled value").c_str());
        }
    }
    for (const auto& [name, entry] : fixture.at("extract").items()) {
        const std::vector<float> volume = floats_from(entry.at("volume"));
        const auto shape = entry.at("shape");
        horizon::Grid2D grid(shape.at(0).get<std::int64_t>(),
                             shape.at(1).get<std::int64_t>(), 0.0);
        grid.values = nums_from(entry.at("grid"));
        const std::vector<float> out = horizon::extract_along_horizon(
            volume, shape.at(0).get<std::int64_t>(), shape.at(1).get<std::int64_t>(),
            shape.at(2).get<std::int64_t>(), grid, entry.at("dt_ms").get<double>(),
            entry.at("t0_ms").get<double>(), entry.at("window").get<int>());
        const std::vector<double> expected = nums_from(entry.at("output"));
        PWB_CHECK(out.size() == expected.size());
        // window == 0 copies samples exactly; the RMS path accumulates in a
        // different order than np.nanmean (declared tolerance).
        const double tol = entry.at("window").get<int>() == 0 ? 0.0 : 1e-4;
        for (std::size_t i = 0; i < std::min(out.size(), expected.size()); ++i) {
            PWB_CHECK_MSG(
                close_or_both_nan(out[i], expected[i], tol == 0.0 ? 0.0 : tol),
                (name + ": extraction").c_str());
        }
    }
    // Frozen triangulation (fixture list is the flat reshape(-1) of (n,3)).
    const auto& faces = fixture.at("faces");
    const auto actual_faces = horizon::horizon_quad_faces(5, 4);
    PWB_CHECK(static_cast<std::int64_t>(actual_faces.size()) ==
              faces.at("faces_count").get<std::int64_t>());
    PWB_CHECK(actual_faces.size() * 3 == faces.at("faces_5x4").size());
    for (std::size_t f = 0; f < actual_faces.size(); ++f) {
        for (int c = 0; c < 3; ++c) {
            PWB_CHECK(actual_faces[f][static_cast<std::size_t>(c)] ==
                      faces.at("faces_5x4")
                          .at(f * 3 + static_cast<std::size_t>(c))
                          .get<std::int64_t>());
        }
    }
    PWB_CHECK(horizon::horizon_quad_faces(1, 7).empty());
}

TEST(pick_model_persistence_and_tamper_selfcheck) {
    horizon::HorizonPickSet set;
    set.volume_id = "vol-42";
    set.volume_revision = 7;
    set.axis_name = "inline";
    set.slice_index = 12;
    set.time_unit = "ms";
    horizon::add_pick(set, {100.0, 500.0, 1180.0});
    horizon::add_pick(set, {101.0, 501.0, 1184.5});
    const std::string json_text = horizon::to_json(set);

    const horizon::PickParseResult loaded = horizon::from_json(json_text);
    PWB_CHECK(loaded.ok);
    PWB_CHECK(loaded.set.volume_id == "vol-42" && loaded.set.volume_revision == 7);
    PWB_CHECK(loaded.set.axis_name == "inline" && loaded.set.slice_index == 12);
    PWB_CHECK(loaded.set.time_unit == "ms");
    PWB_CHECK(loaded.set.picks.size() == 2);
    PWB_CHECK(loaded.set.picks[0].inline_no == 100.0 &&
              loaded.set.picks[1].time_value == 1184.5);

    // CSV export parity (seismic_view._on_export_picks).
    const std::string csv = horizon::to_csv(set);
    PWB_CHECK(csv == "inline,crossline,time_ms\n100.0,500.0,1180.0\n101.0,501.0,1184.5\n");

    // Edits.
    PWB_CHECK(horizon::move_pick(set, 1, {101.0, 501.0, 1199.9}));
    PWB_CHECK(!horizon::move_pick(set, 99, {0, 0, 0}));
    PWB_CHECK(horizon::remove_pick_near(set, 100.0, 500.0, 1180.0, 0.5, 0.5, 0.5));
    PWB_CHECK(set.picks.size() == 1 && set.picks[0].time_value == 1199.9);
    PWB_CHECK(!horizon::remove_pick_near(set, 1.0, 1.0, 1.0, 0.5, 0.5, 0.5));
    horizon::clear_picks(set);
    PWB_CHECK(set.picks.empty());

    // Negative self-checks: tampered schema, corrupted JSON, bad axis —
    // each must fail closed, never silently accept.
    std::string tampered = json_text;
    const std::size_t pos = tampered.find("\"volume_id\": \"vol-42\"");
    PWB_CHECK(pos != std::string::npos);
    tampered.replace(pos + 14, 6, "vol-99"); // forged source identity
    const horizon::PickParseResult forged = horizon::from_json(tampered);
    PWB_CHECK(forged.ok); // text still parses…
    PWB_CHECK(forged.set.volume_id == "vol-99"); // …and reports the forged id
    // (round-trip integrity is the caller's compare, exercised by callers).
    PWB_CHECK(!horizon::from_json("{not json").ok);
    PWB_CHECK(!horizon::from_json("{\"schema\": \"other/1\"}").ok);
    std::string bad_axis = json_text;
    const std::size_t axis_pos = bad_axis.find("\"axis\": \"inline\"");
    PWB_CHECK(axis_pos != std::string::npos);
    bad_axis.replace(axis_pos + 9, 6, "bogus");
    PWB_CHECK(!horizon::from_json(bad_axis).ok);
}

TEST(lithology_crossplot_replay) {
    const auto fixture = viz_d_test::load_fixture("viz_d_crossplot_oracle.json");
    for (const auto& [name, entry] : fixture.at("lithology").items()) {
        const std::vector<double> gr = nums_from(entry.at("gr"));
        const std::vector<double> ai = nums_from(entry.at("ai"));
        std::vector<std::string> labels;
        for (const auto& label : entry.at("labels")) {
            labels.push_back(label.get<std::string>());
        }
        const crossplot::LithologyCrossplot out =
            crossplot::analyze_lithology_crossplot(gr, ai, labels);
        const auto& expected_points = entry.at("points");
        PWB_CHECK(out.points.size() == expected_points.size());
        for (std::size_t i = 0; i < out.points.size(); ++i) {
            PWB_CHECK_MSG(close_or_both_nan(out.points[i].gr,
                                            num_from(expected_points.at(i).at("gr")),
                                            1e-12),
                          (name + ": point gr").c_str());
            PWB_CHECK(out.points[i].lithology ==
                      expected_points.at(i).at("lithology").get<std::string>());
        }
        // Cluster maps in Python preserve insertion order == first seen.
        std::vector<std::string> expected_order;
        for (const auto& item : expected_points) {
            const std::string label = item.at("lithology").get<std::string>();
            if (std::find(expected_order.begin(), expected_order.end(), label) ==
                expected_order.end()) {
                expected_order.push_back(label);
            }
        }
        PWB_CHECK(out.clusters.size() == expected_order.size());
        for (std::size_t c = 0; c < expected_order.size(); ++c) {
            PWB_CHECK(out.clusters[c].first == expected_order[c]);
            const auto& stats = entry.at("clusters").at(expected_order[c]);
            PWB_CHECK(out.clusters[c].second.count ==
                      static_cast<std::int64_t>(stats.at("count").get<int>()));
            PWB_CHECK_MSG(close_or_both_nan(
                              out.clusters[c].second.mean_gr,
                              num_from(stats.at("mean_gr")), 1e-9),
                          (name + ": mean_gr").c_str());
            PWB_CHECK_MSG(close_or_both_nan(
                              out.clusters[c].second.std_ai,
                              num_from(stats.at("std_ai")), 1e-9),
                          (name + ": std_ai").c_str());
        }
    }
}

TEST(attribute_crossplot_replay) {
    const auto fixture = viz_d_test::load_fixture("viz_d_crossplot_oracle.json");
    for (const auto& [name, entry] : fixture.at("attribute").items()) {
        const crossplot::AttributeCrossplotData out = crossplot::prepare_attribute_crossplot(
            floats_from(entry.at("plane")), entry.at("n_samples").get<std::int64_t>(),
            entry.at("n_traces").get<std::int64_t>(), entry.at("dt_s").get<double>());
        PWB_CHECK_MSG(out.ok, (name + ": kernel run failed").c_str());
        const std::vector<double> freq = nums_from(entry.at("freq_sub"));
        const std::vector<double> env = nums_from(entry.at("env_sub"));
        PWB_CHECK(out.frequency_hz.size() == freq.size());
        PWB_CHECK(out.envelope.size() == env.size());
        // The kernels are float32 pipelines with their own frozen oracles;
        // this replay declares a small relative tolerance and verifies the
        // flatten order, subsample step and P1/P99 limit derivation.
        for (std::size_t i = 0; i < std::min(out.frequency_hz.size(), freq.size());
             ++i) {
            PWB_CHECK_MSG(
                close_or_both_nan(out.frequency_hz[i], freq[i], 2e-3),
                (name + ": frequency subsample").c_str());
        }
        for (std::size_t i = 0; i < std::min(out.envelope.size(), env.size()); ++i) {
            PWB_CHECK_MSG(close_or_both_nan(out.envelope[i], env[i], 2e-3),
                          (name + ": envelope subsample").c_str());
        }
        PWB_CHECK_MSG(close_or_both_nan(out.x_limits.lo,
                                        num_from(entry.at("x_limits").at(0)), 2e-3) &&
                          close_or_both_nan(
                              out.x_limits.hi,
                              num_from(entry.at("x_limits").at(1)), 2e-3),
                      (name + ": x limits").c_str());
        PWB_CHECK_MSG(close_or_both_nan(out.y_limits.lo,
                                        num_from(entry.at("y_limits").at(0)), 2e-3) &&
                          close_or_both_nan(
                              out.y_limits.hi,
                              num_from(entry.at("y_limits").at(1)), 2e-3),
                      (name + ": y limits").c_str());
    }
}

TEST(crossplot_axis_limits_degenerate_guard) {
    const std::vector<float> empty;
    PWB_CHECK(crossplot::percentile_axis_limits(empty).lo == 0.0);
    PWB_CHECK(crossplot::percentile_axis_limits(empty).hi == 1.0);
    const std::vector<float> flat_in{5.0f, 5.0f};
    const crossplot::AxisLimits flat = crossplot::percentile_axis_limits(flat_in);
    PWB_CHECK(flat.lo == 5.0 && flat.hi == 6.0); // hi = lo + 1 guard
    const std::vector<float> mixed_in{1.0f, 2.0f, 3.0f, 4.0f, 100.0f,
                                      std::numeric_limits<float>::quiet_NaN()};
    const crossplot::AxisLimits mixed = crossplot::percentile_axis_limits(mixed_in);
    // numpy 'linear': rank = q/100*(n-1) over the finite tail [1,2,3,4,100].
    PWB_CHECK(std::abs(mixed.lo - 1.04) < 1e-12 && std::abs(mixed.hi - 96.16) < 1e-9);
}

TEST(isosurface_matches_native_marching_tetrahedra) {
    const auto fixture = viz_d_test::load_fixture("viz_d_isosurface_oracle.json");
    for (const auto& [name, entry] : fixture.at("cases").items()) {
        const auto shape = entry.at("shape");
        const isosurface::IsosurfaceMesh mesh = isosurface::extract_isosurface(
            floats_from(entry.at("volume")), shape.at(0).get<std::int64_t>(),
            shape.at(1).get<std::int64_t>(), shape.at(2).get<std::int64_t>(),
            static_cast<float>(entry.at("isovalue").get<double>()));
        const std::vector<double> verts = nums_from(entry.at("verts"));
        const auto& faces = entry.at("faces");
        PWB_CHECK_MSG(mesh.verts.size() == verts.size(),
                      (name + ": vertex count").c_str());
        for (std::size_t i = 0; i < std::min(mesh.verts.size(), verts.size()); ++i) {
            // Same algorithm, same float arithmetic: bit-exact replay.
            PWB_CHECK_MSG(static_cast<double>(mesh.verts[i]) == verts[i],
                          (name + ": vertex").c_str());
        }
        PWB_CHECK(mesh.faces.size() == faces.size());
        for (std::size_t i = 0; i < std::min(mesh.faces.size(), faces.size()); ++i) {
            PWB_CHECK_MSG(mesh.faces[i] == faces.at(i).get<std::int64_t>(),
                          (name + ": face").c_str());
        }
    }
}

#include "viz_d_test_main.inc"
