#include <pwb/viz/well_tie/wavelet.hpp>

#include <cmath>

// PWB-V14-DATA-LINEAGE: kPi is POSIX-only (MSVC lacks it without
// _USE_MATH_DEFINES before <cmath>); one file-local constant.
namespace {
constexpr double kPi = 3.14159265358979323846;
}  // namespace


namespace pwb::viz::well_tie {

namespace {

// Shared centre: t = arange(n) * dt - t[n/2] (integer division).
std::vector<double> centred_times(int n_samples, double dt) {
    std::vector<double> t(static_cast<std::size_t>(n_samples));
    const double centre = static_cast<double>(n_samples / 2) * dt;
    for (std::size_t i = 0; i < t.size(); ++i) {
        t[i] = static_cast<double>(i) * dt - centre;
    }
    return t;
}

// np.sinc — the NORMALIZED sinc: sin(pi x) / (pi x), sinc(0) = 1.
double np_sinc(double x) {
    if (x == 0.0) return 1.0;
    const double px = kPi * x;
    return std::sin(px) / px;
}

}  // namespace

std::vector<float> ricker_wavelet(int n_samples, double dt,
                                  double peak_freq) {
    const std::vector<double> t = centred_times(n_samples, dt);
    std::vector<float> w(t.size());
    for (std::size_t i = 0; i < t.size(); ++i) {
        const double p2 = std::pow(kPi * peak_freq * t[i], 2.0);
        w[i] = static_cast<float>((1.0 - 2.0 * p2) * std::exp(-p2));
    }
    return w;
}

std::vector<float> ormsby_wavelet(int n_samples, double dt, double f1,
                                  double f2, double f3, double f4) {
    const std::vector<double> t = centred_times(n_samples, dt);
    std::vector<double> w(t.size());
    const double high_denom = std::max(1e-6, f4 - f3);
    const double low_denom = std::max(1e-6, f2 - f1);
    double peak = 0.0;
    for (std::size_t i = 0; i < t.size(); ++i) {
        const double s4 = np_sinc(f4 * t[i]);
        const double s3 = np_sinc(f3 * t[i]);
        const double s2 = np_sinc(f2 * t[i]);
        const double s1 = np_sinc(f1 * t[i]);
        const double high =
            (f4 * f4 * s4 * s4 - f3 * f3 * s3 * s3) / high_denom;
        const double low =
            (f2 * f2 * s2 * s2 - f1 * f1 * s1 * s1) / low_denom;
        w[i] = kPi * (high - low);
        peak = std::max(peak, std::abs(w[i]));
    }
    if (peak > 0.0) {
        for (double& v : w) v /= peak;
    }
    std::vector<float> out(w.size());
    for (std::size_t i = 0; i < w.size(); ++i) out[i] = static_cast<float>(w[i]);
    return out;
}

}  // namespace pwb::viz::well_tie
