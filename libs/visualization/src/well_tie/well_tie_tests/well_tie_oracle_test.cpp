// VIZ-B — well-tie numeric kernel oracle replay. The fixture is frozen
// from the real Python reference (tools/oracle/generate_viz_b_well_tie_
// fixtures.py @ geo-viz-engine 08851951); non-finite values arrive as the
// tagged strings "inf"/"-inf"/"nan".

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/viz/well_tie/auto_tie.hpp>
#include <pwb/viz/well_tie/calibration.hpp>
#include <pwb/viz/well_tie/sonic_units.hpp>
#include <pwb/viz/well_tie/synthetic.hpp>
#include <pwb/viz/well_tie/tie_evaluator.hpp>
#include <pwb/viz/well_tie/wavelet.hpp>

#ifndef PWB_VIZ_B_WELL_TIE_FIXTURE
#error "PWB_VIZ_B_WELL_TIE_FIXTURE must be defined"
#endif

using pwb::domain::Json;

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

double read_num(const Json& v) {
    if (v.is_string()) {
        const std::string s = v.get<std::string>();
        if (s == "inf") return std::numeric_limits<double>::infinity();
        if (s == "-inf") return -std::numeric_limits<double>::infinity();
        if (s == "nan") return std::numeric_limits<double>::quiet_NaN();
    }
    return v.get<double>();
}

std::vector<double> read_nums(const Json& arr) {
    std::vector<double> out;
    for (const Json& v : arr) out.push_back(read_num(v));
    return out;
}

std::vector<float> read_floats(const Json& arr) {
    std::vector<float> out;
    for (const Json& v : arr) out.push_back(static_cast<float>(read_num(v)));
    return out;
}

// float32-amplitude parity: the C++ kernels return float vectors already.
bool same_float(const std::vector<float>& got, const Json& expected,
                const std::string& label) {
    if (got.size() != expected.size()) {
        check(false, label + " size " + std::to_string(got.size()) + " != " +
                         std::to_string(expected.size()));
        return false;
    }
    for (std::size_t i = 0; i < got.size(); ++i) {
        const double want = read_num(expected[i]);
        if (std::isnan(want)) {
            check(std::isnan(got[i]), label + " [" + std::to_string(i) + "]");
        } else {
            check(static_cast<double>(got[i]) == want,
                  label + " [" + std::to_string(i) + "] got " +
                      std::to_string(got[i]) + " want " +
                      std::to_string(want));
        }
    }
    return true;
}

bool same_double(const std::vector<double>& got, const Json& expected,
                 const std::string& label) {
    if (got.size() != expected.size()) {
        check(false, label + " size");
        return false;
    }
    for (std::size_t i = 0; i < got.size(); ++i) {
        const double want = read_num(expected[i]);
        if (std::isnan(want)) {
            check(std::isnan(got[i]), label + " nan");
        } else {
            check(got[i] == want, label + " [" + std::to_string(i) +
                                      "] got " + std::to_string(got[i]) +
                                      " want " + std::to_string(want));
        }
    }
    return true;
}

std::string tag_num(double v) {
    if (std::isnan(v)) return "nan";
    if (std::isinf(v)) return v > 0 ? "inf" : "-inf";
    // repr-ish via %.17g
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.17g", v);
    return buf;
}

void run_case(const Json& c) {
    const std::string id = c.at("id").get<std::string>();
    const std::string kind = c.at("kind").get<std::string>();
    if (kind == "wavelet_ricker") {
        const auto w = pwb::viz::well_tie::ricker_wavelet(
            c.at("n_samples").get<int>(), c.at("dt").get<double>(),
            c.at("peak_freq").get<double>());
        same_float(w, c.at("output"), id);
    } else if (kind == "wavelet_ormsby") {
        const auto w = pwb::viz::well_tie::ormsby_wavelet(
            c.at("n_samples").get<int>(), c.at("dt").get<double>(),
            c.at("f1").get<double>(), c.at("f2").get<double>(),
            c.at("f3").get<double>(), c.at("f4").get<double>());
        same_float(w, c.at("output"), id);
    } else if (kind == "reflectivity") {
        try {
            const auto rc = pwb::viz::well_tie::compute_reflectivity(
                read_nums(c.at("sonic")), read_nums(c.at("density")));
            same_float(rc, c.at("output"), id);
        } catch (const std::invalid_argument&) {
            check(false, id + " unexpected throw");
        }
    } else if (kind == "reflectivity_error") {
        bool threw = false;
        try {
            // 错误路径探针：只关心是否抛出，返回值无关。
            (void)pwb::viz::well_tie::compute_reflectivity(
                read_nums(c.at("sonic")), read_nums(c.at("density")));
        } catch (const std::invalid_argument&) {
            threw = true;
        }
        check(threw, id + " must throw");
        check(c.at("error").get<std::string>().rfind("ValueError:", 0) == 0,
              id + " reference error recorded");
    } else if (kind == "synthetic") {
        const auto syn = pwb::viz::well_tie::generate_synthetic(
            read_floats(c.at("reflectivity")), read_floats(c.at("wavelet")));
        same_float(syn, c.at("output"), id);
    } else if (kind == "synthetic_twt") {
        pwb::viz::well_tie::SyntheticTwtOptions options;
        options.wavelet_type = c.at("wavelet_type").get<std::string>();
        options.dt_ms = c.at("dt_ms").get<double>();
        options.peak_freq = c.at("peak_freq").get<double>();
        const auto syn = pwb::viz::well_tie::generate_synthetic_twt(
            read_floats(c.at("reflectivity")), options);
        same_float(syn, c.at("output"), id);
    } else if (kind == "synthetic_from_logs") {
        pwb::viz::well_tie::SyntheticFromLogsOptions options;
        if (c.contains("sonic_clip") && c.at("sonic_clip").is_null()) {
            options.sonic_clip = std::nullopt;
        }
        if (c.contains("half_length_s")) {
            options.half_length_s = c.at("half_length_s").get<double>();
        }
        const auto syn = pwb::viz::well_tie::synthetic_from_logs(
            read_nums(c.at("sonic")), read_nums(c.at("density")), options);
        same_float(syn, c.at("output"), id);
    } else if (kind == "cal_depth_to_twt") {
        const pwb::viz::well_tie::WellTieCalibration cal(
            read_nums(c.at("depths")), read_nums(c.at("twts")));
        std::vector<double> got;
        for (const double d : read_nums(c.at("probe"))) {
            got.push_back(cal.depth_to_twt(d));
        }
        same_double(got, c.at("output"), id);
    } else if (kind == "cal_twt_to_depth") {
        const pwb::viz::well_tie::WellTieCalibration cal(
            read_nums(c.at("depths")), read_nums(c.at("twts")));
        std::vector<double> got;
        for (const double t : read_nums(c.at("probe"))) {
            got.push_back(cal.twt_to_depth(t));
        }
        same_double(got, c.at("output"), id);
    } else if (kind == "cal_resample_to_twt") {
        const pwb::viz::well_tie::WellTieCalibration cal(
            read_nums(c.at("depths")), read_nums(c.at("twts")));
        const auto got = cal.resample_to_twt(
            read_nums(c.at("log_values")), c.at("dt_ms").get<double>(),
            c.at("t0_ms").get<double>());
        same_double(got, c.at("output"), id);
    } else if (kind == "cal_from_sonic") {
        const auto cal = pwb::viz::well_tie::WellTieCalibration::from_sonic(
            read_nums(c.at("depths")), read_nums(c.at("sonic")));
        same_double(cal.depths(), c.at("output_depths"), id + ".depths");
        same_double(cal.twt(), c.at("output_twt"), id + ".twt");
    } else if (kind == "cal_from_sonic_error" || kind == "cal_error") {
        bool threw = false;
        try {
            if (kind == "cal_from_sonic_error") {
                // 错误路径探针：只关心是否抛出，返回值无关。
                (void)pwb::viz::well_tie::WellTieCalibration::from_sonic(
                    read_nums(c.at("depths")), read_nums(c.at("sonic")));
            } else {
                pwb::viz::well_tie::WellTieCalibration(
                    read_nums(c.at("depths")), read_nums(c.at("twts")));
            }
        } catch (const std::invalid_argument&) {
            threw = true;
        }
        check(threw, id + " must throw");
        check(c.at("error").get<std::string>().rfind("ValueError:", 0) == 0,
              id + " reference error recorded");
    } else if (kind == "resample_seismic_grid") {
        const auto got = pwb::viz::well_tie::resample_to_seismic_grid(
            read_nums(c.at("values")), read_nums(c.at("src_twt")),
            c.at("dt_ms").get<double>(), c.at("t0_ms").get<double>(),
            c.at("n_samples").get<int>());
        same_double(got, c.at("output"), id);
    } else if (kind == "shift_depths") {
        const auto got = pwb::viz::well_tie::shift_depths(
            read_nums(c.at("depths")), c.at("shift").get<double>());
        same_double(got, c.at("output"), id);
    } else if (kind == "auto_tie") {
        const auto got = pwb::viz::well_tie::correlate_synthetic_to_trace(
            read_nums(c.at("synthetic")), read_nums(c.at("seismic")));
        check(got.shift_samples == c.at("shift").get<int>(),
              id + " shift got " + std::to_string(got.shift_samples) +
                  " want " + std::to_string(c.at("shift").get<int>()));
        const double want_r = read_num(c.at("r"));
        check(std::abs(got.correlation - want_r) <=
                  1e-12 * std::max(1.0, std::abs(want_r)),
              id + " r got " + tag_num(got.correlation) + " want " +
                  tag_num(want_r));
    } else if (kind == "tie_quality") {
        const auto got = pwb::viz::well_tie::evaluate_tie_quality(
            read_nums(c.at("synthetic")), read_nums(c.at("seismic")));
        const double want_r = read_num(c.at("r"));
        check(std::abs(got.r - want_r) <= 1e-12 * std::max(1.0, std::abs(want_r)),
              id + " r got " + tag_num(got.r) + " want " +
                  tag_num(want_r));
        check(got.lag == c.at("lag").get<int>(), id + " lag");
        // Compare the frozen HEAD slice (numpy pairwise vs naive
        // summation can differ in the tail beyond 1e-12 — declared
        // tolerance, scope.md).
        const std::size_t head = std::min<std::size_t>(
            got.residual.size(), c.at("residual_head").size());
        same_double(std::vector<double>(got.residual.begin(),
                                        got.residual.begin() +
                                            static_cast<std::ptrdiff_t>(head)),
                    c.at("residual_head"), id + ".residual");
        check(got.residual.size() == c.at("residual_len").get<int>(),
              id + " residual len got " + std::to_string(got.residual.size()) +
                  " want " + std::to_string(c.at("residual_len").get<int>()));
    } else if (kind == "sonic_units") {
        std::optional<std::string> unit;
        if (c.contains("unit") && !c.at("unit").is_null()) {
            unit = c.at("unit").get<std::string>();
        }
        const auto got = pwb::viz::well_tie::normalize_sonic_units(
            read_nums(c.at("values")), unit);
        same_double(got.values, c.at("output"), id);
        const std::string want_resolved = c.at("resolved").get<std::string>();
        check((got.resolved ==
               pwb::viz::well_tie::SonicUnit::us_per_m) ==
                  (want_resolved == "us/m"),
              id + " resolved");
        const bool want_warning_set =
            c.contains("warning") && !c.at("warning").is_null();
        check(got.warning.has_value() == want_warning_set,
              id + " warning presence");
        if (want_warning_set && got.warning) {
            check(*got.warning == c.at("warning").get<std::string>(),
                  id + " warning text: got '" + *got.warning + "' want '" +
                      c.at("warning").get<std::string>() + "'");
        }
    } else if (kind == "sonic_canonical") {
        std::optional<std::string> unit;
        if (c.contains("unit") && !c.at("unit").is_null()) {
            unit = c.at("unit").get<std::string>();
        }
        const auto got = pwb::viz::well_tie::canonical_sonic_unit(
            unit.value_or(""));
        // canonical is null for unknown units (Python None).
        if (c.at("canonical").is_null()) {
            check(!got.has_value(), id + " expected nullopt");
        } else {
            const std::string want = c.at("canonical").get<std::string>();
            if (want == "us/m") {
                check(got.has_value() &&
                          *got == pwb::viz::well_tie::SonicUnit::us_per_m,
                      id);
            } else if (want == "us/ft") {
                check(got.has_value() &&
                          *got == pwb::viz::well_tie::SonicUnit::us_per_ft,
                      id);
            } else {
                check(!got.has_value(),
                      id + " expected nullopt for '" + want + "'");
            }
        }
    } else if (kind == "constant") {
        check(c.at("us_ft_to_us_m").get<double>() ==
                  pwb::viz::well_tie::kUsFtToUsM, id);
    }
}

// Negative self-check: tamper with the fixture bytes and require the
// replay to FAIL (guards against a test that passes on anything).
bool negative_self_check(const Json& payload, const char* fixture_path) {
    Json tampered = payload;
    // Flip one numeric output deep inside the first wavelet case.
    for (Json& c : tampered.at("cases")) {
        if (c.at("kind").get<std::string>() == "wavelet_ricker") {
            c.at("output")[3] =
                c.at("output")[3].get<double>() + 0.5;
            break;
        }
    }
    const std::string text = tampered.dump();
    ++g_checks;
    bool any_fail_before = g_failures;
    for (const Json& c : tampered.at("cases")) {
        if (c.at("kind").get<std::string>() == "wavelet_ricker") {
            run_case(c);
            break;
        }
    }
    const bool caught = g_failures > any_fail_before;
    if (!caught) {
        ++g_failures;
        std::cerr << "FAIL: negative self-check did not catch tampering ("
                  << fixture_path << ")\n";
        return false;
    }
    // Caught: roll the deliberately induced failures back out so the
    // tamper probe does not pollute the exit code.
    g_failures = any_fail_before;
    return true;
}

}  // namespace

int main() {
    std::ifstream file(PWB_VIZ_B_WELL_TIE_FIXTURE);
    if (!file.is_open()) {
        std::cerr << "cannot open fixture " << PWB_VIZ_B_WELL_TIE_FIXTURE
                  << "\n";
        return 2;
    }
    Json payload;
    file >> payload;
    for (const Json& c : payload.at("cases")) {
        try {
            run_case(c);
        } catch (const std::exception& exc) {
            ++g_failures;
            std::cerr << "FAIL: case '" << c.at("id").get<std::string>()
                      << "' threw: " << exc.what() << "\n";
        }
    }
    // Real-well replay: synthetic_from_logs + from_sonic on the frozen
    // real LAS arrays (unit normalization is part of the fixture).
    for (const Json& w : payload.at("real_wells").at("wells")) {
        const std::vector<double> sonic =
            read_nums(w.at("sonic_us_per_m"));
        const std::vector<double> density = read_nums(w.at("density"));
        const auto syn = pwb::viz::well_tie::synthetic_from_logs(
            sonic, density);
        ++g_checks;
        check(syn.size() == w.at("synthetic_len").get<int>(),
              w.at("name").get<std::string>() + " synthetic len");
        std::vector<float> head(syn.begin(),
                                syn.begin() +
                                    std::min<std::size_t>(
                                        syn.size(),
                                        w.at("synthetic_from_logs_head")
                                            .size()));
        same_float(head, w.at("synthetic_from_logs_head"),
                   w.at("name").get<std::string>() + ".synthetic_head");
        const auto cal = pwb::viz::well_tie::WellTieCalibration::from_sonic(
            read_nums(w.at("depths")), sonic);
        std::vector<double> twt_head(cal.twt().begin(),
                                     cal.twt().begin() +
                                         std::min<std::size_t>(
                                             cal.twt().size(),
                                             w.at("from_sonic_twt_head")
                                                 .size()));
        same_double(twt_head, w.at("from_sonic_twt_head"),
                    w.at("name").get<std::string>() + ".twt_head");
        std::vector<double> twt_tail(
            cal.twt().end() -
                std::min<std::size_t>(cal.twt().size(),
                                      w.at("from_sonic_twt_tail").size()),
            cal.twt().end());
        same_double(twt_tail, w.at("from_sonic_twt_tail"),
                    w.at("name").get<std::string>() + ".twt_tail");
    }

    negative_self_check(payload, PWB_VIZ_B_WELL_TIE_FIXTURE);

    std::cout << "well_tie oracle: " << g_checks << " checks, "
              << g_failures << " failures\n";
    return g_failures == 0 ? 0 : 1;
}
