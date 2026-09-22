#include <pwb/viz/well_tie/log_tie.hpp>
#include <pwb/viz/well_tie/calibration.hpp>
#include <pwb/viz/well_tie/sonic_units.hpp>
#include <pwb/viz/well_tie/synthetic.hpp>
#include <pwb/viz/well_tie/wavelet.hpp>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>

namespace pwb::viz::well_tie {
namespace {
LogTieCurve clean(LogTieCurve curve) {
    if (curve.depth_m.size() != curve.values.size())
        throw std::invalid_argument("Log depth/value size mismatch");
    std::vector<std::pair<double, double>> samples;
    for (std::size_t i = 0; i < curve.values.size(); ++i)
        if (std::isfinite(curve.depth_m[i]) && std::isfinite(curve.values[i]) && curve.values[i] > 0)
            samples.emplace_back(curve.depth_m[i], curve.values[i]);
    std::sort(samples.begin(), samples.end());
    curve.depth_m.clear();
    curve.values.clear();
    for (const auto& [depth, value] : samples) {
        if (!curve.depth_m.empty() && depth == curve.depth_m.back())
            throw std::invalid_argument("Duplicate log depths");
        curve.depth_m.push_back(depth);
        curve.values.push_back(value);
    }
    if (samples.size() < 3) throw std::invalid_argument("Insufficient finite positive log samples");
    return curve;
}
double interpolate(const std::vector<double>& x, const std::vector<double>& y, double t) {
    if (t < x.front() || t > x.back()) return std::numeric_limits<double>::quiet_NaN();
    auto hi = std::lower_bound(x.begin(), x.end(), t);
    if (hi == x.begin()) return y.front();
    if (hi == x.end()) return y.back();
    const auto j = static_cast<std::size_t>(hi - x.begin());
    const double f = (t - x[j - 1]) / (x[j] - x[j - 1]);
    return y[j - 1] * (1 - f) + y[j] * f;
}
}

LogTieResult tie_logs_to_seismic(const LogTieInput& in, const std::function<bool()>& cancelled) {
    if (!std::isfinite(in.dt_ms) || in.dt_ms <= 0 || !std::isfinite(in.t0_ms) ||
        !std::isfinite(in.frequency_hz) || in.frequency_hz <= 0 ||
        !std::isfinite(in.initial_shift_ms) || !std::isfinite(in.max_shift_ms) ||
        in.max_shift_ms < 0 || in.seismic.size() < 8)
        throw std::invalid_argument("Invalid seismic sampling or tie parameters");
    const auto check_cancelled = [&] {
        if (cancelled && cancelled()) throw std::runtime_error("Well tie cancelled");
    };
    check_cancelled();
    auto sonic = clean(in.sonic);
    auto density = clean(in.density);
    auto normalized = normalize_sonic_units(sonic.values, sonic.unit);
    sonic.values = std::move(normalized.values);
    std::string density_unit = density.unit;
    std::transform(density_unit.begin(), density_unit.end(), density_unit.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (density_unit == "kg/m3" || density_unit == "kg/m^3")
        for (auto& value : density.values) value *= 0.001;
    else if (!density_unit.empty() && density_unit != "g/cm3" && density_unit != "g/cm^3" && density_unit != "g/cc")
        throw std::invalid_argument("Unsupported density unit: " + density.unit);
    std::vector<double> depths, slowness, rho;
    for (std::size_t i = 0; i < sonic.values.size(); ++i) {
        const auto value = interpolate(density.depth_m, density.values, sonic.depth_m[i]);
        if (std::isfinite(value)) {
            depths.push_back(sonic.depth_m[i]);
            slowness.push_back(sonic.values[i]);
            rho.push_back(value);
        }
    }
    if (depths.size() < 3) throw std::invalid_argument("Sonic and density depth ranges do not overlap");
    const bool checkshot = !in.checkshot_depth_m.empty() || !in.checkshot_twt_ms.empty();
    if (checkshot) {
        if (in.checkshot_depth_m.size() != in.checkshot_twt_ms.size() || in.checkshot_depth_m.size() < 2)
            throw std::invalid_argument("Invalid checkshot anchors");
        for (std::size_t i = 0; i < in.checkshot_depth_m.size(); ++i)
            if (!std::isfinite(in.checkshot_depth_m[i]) || !std::isfinite(in.checkshot_twt_ms[i]) ||
                (i && (in.checkshot_depth_m[i] <= in.checkshot_depth_m[i-1] || in.checkshot_twt_ms[i] <= in.checkshot_twt_ms[i-1])))
                throw std::invalid_argument("Checkshot anchors must be finite and strictly increasing");
    }
    const auto calibration = checkshot
        ? WellTieCalibration(in.checkshot_depth_m, in.checkshot_twt_ms)
        : WellTieCalibration::from_sonic(depths, slowness);
    std::vector<double> twt, impedance;
    for (std::size_t i = 0; i < depths.size(); ++i) {
        if (depths[i] < calibration.depths().front() || depths[i] > calibration.depths().back()) continue;
        twt.push_back(calibration.depth_to_twt(depths[i]) + in.initial_shift_ms);
        impedance.push_back(1e6 / slowness[i] * rho[i]);
    }
    if (twt.size() < 3) throw std::invalid_argument("Logs outside calibrated depth range");
    std::vector<double> grid(in.seismic.size(), std::numeric_limits<double>::quiet_NaN());
    for (std::size_t i = 0; i < grid.size(); ++i)
        grid[i] = interpolate(twt, impedance, in.t0_ms + i * in.dt_ms);
    std::vector<float> reflectivity(grid.size(), 0.0f);
    std::vector<bool> valid(grid.size(), false);
    for (std::size_t i = 1; i < grid.size(); ++i) {
        if (!std::isfinite(grid[i-1]) || !std::isfinite(grid[i])) continue;
        // The interface is located at the later regular time sample.
        reflectivity[i] = static_cast<float>((grid[i] - grid[i-1]) / (grid[i] + grid[i-1]));
        valid[i] = true;
    }
    const double half_samples = std::ceil(64.0 / in.dt_ms);
    if (half_samples > 100000 || in.max_shift_ms / in.dt_ms > 1000000)
        throw std::invalid_argument("Tie sampling exceeds supported resource budget");
    const auto wavelet = ricker_wavelet(static_cast<int>(2 * half_samples + 1), in.dt_ms / 1000.0, in.frequency_hz);
    const auto synthetic = generate_synthetic(reflectivity, wavelet);
    LogTieResult result;
    result.synthetic.assign(synthetic.begin(), synthetic.end());
    if (normalized.warning) result.warning = *normalized.warning;
    if (!checkshot) result.warning += " Sonic integration starts at the first log sample; use checkshots for absolute TWT.";
    const auto support = static_cast<std::size_t>(std::count(valid.begin(), valid.end(), true));
    const auto minimum = std::max<std::size_t>(8, support / 2);
    double best = -std::numeric_limits<double>::infinity();
    const int bound = static_cast<int>(std::min<double>(std::floor(in.max_shift_ms / in.dt_ms), grid.size()-1));
    for (int lag = -bound; lag <= bound; ++lag) {
        check_cancelled();
        double sum_s=0, sum_t=0, sum_ss=0, sum_tt=0, sum_st=0;
        std::size_t n = 0;
        for (std::size_t i = 0; i < synthetic.size(); ++i) {
            const auto j = static_cast<long long>(i) + lag;
            if (!valid[i] || j < 0 || j >= static_cast<long long>(in.seismic.size()) || !std::isfinite(in.seismic[j])) continue;
            const double s=synthetic[i], t=in.seismic[j];
            sum_s+=s; sum_t+=t; sum_ss+=s*s; sum_tt+=t*t; sum_st+=s*t; ++n;
        }
        if (n < minimum) continue;
        const double vs=sum_ss-sum_s*sum_s/n, vt=sum_tt-sum_t*sum_t/n;
        if (vs <= 1e-20 || vt <= 1e-20) continue;
        const double r=std::clamp((sum_st-sum_s*sum_t/n)/std::sqrt(vs*vt),-1.0,1.0);
        if (r > best) {
            best=r; result.correlation=r; result.shift_ms=in.initial_shift_ms+lag*in.dt_ms; result.overlap_samples=n;
        }
    }
    if (!std::isfinite(best)) throw std::invalid_argument("Insufficient varying measured overlap for well tie");
    return result;
}
}  // namespace pwb::viz::well_tie
