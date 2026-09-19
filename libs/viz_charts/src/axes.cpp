#include <pwb/viz_charts/axes.hpp>

#include <algorithm>
#include <cmath>

namespace pwb::viz_charts {

double nice_number(double value, bool round_flag) {
    if (value == 0.0) {
        return 0.0;
    }
    const double sign = value < 0 ? -1.0 : 1.0;
    value = std::fabs(value);
    const int exponent = static_cast<int>(std::floor(std::log10(value)));
    const double fraction = value / std::pow(10.0, exponent);

    double nice_fraction = 10.0;
    if (round_flag) {
        if (fraction < 1.5) {
            nice_fraction = 1.0;
        } else if (fraction < 3.0) {
            nice_fraction = 2.0;
        } else if (fraction < 7.0) {
            nice_fraction = 5.0;
        }
    } else {
        if (fraction <= 1.0) {
            nice_fraction = 1.0;
        } else if (fraction <= 2.0) {
            nice_fraction = 2.0;
        } else if (fraction <= 5.0) {
            nice_fraction = 5.0;
        }
    }
    return sign * nice_fraction * std::pow(10.0, exponent);
}

std::pair<std::vector<double>, double> calculate_ticks(double vmin, double vmax,
                                                       int max_ticks) {
    if (max_ticks <= 1) {
        return {{vmin}, 1.0};
    }
    if (!(std::isfinite(vmin) && std::isfinite(vmax))) {
        return {{}, 1.0};
    }
    if (vmin > vmax) {
        std::swap(vmin, vmax);
    }
    if (vmin == vmax) {
        if (vmin == 0.0) {
            return {{0.0}, 1.0};
        }
        double step = nice_number(std::fabs(vmin) * 0.1, true);
        if (step == 0.0) {
            step = 1.0;
        }
        return {{vmin}, step};
    }

    const double range_val = nice_number(vmax - vmin, false);
    double step = nice_number(range_val / (max_ticks - 1), true);
    if (step == 0.0) {
        step = 1.0;
    }

    const double nice_min = std::floor(vmin / step) * step;
    const double nice_max = std::ceil(vmax / step) * step;

    std::vector<double> ticks;
    double current = nice_min;
    while (current <= nice_max + 0.5 * step) {
        double rounded_val = std::round(current / step) * step;
        const int precision =
            step > 0 ? std::max(0, -static_cast<int>(std::floor(std::log10(step)))) : 0;
        rounded_val = std::round(rounded_val * std::pow(10.0, precision + 2)) /
                      std::pow(10.0, precision + 2);
        ticks.push_back(rounded_val);
        current += step;
    }
    return {ticks, step};
}

std::string format_tick(double value, double step) {
    if (!std::isfinite(value)) {
        if (std::isnan(value)) {
            return "nan";
        }
        return value > 0 ? "inf" : "-inf";
    }
    if (!std::isfinite(step) || step <= 0.0) {
        step = value != 0.0 ? std::fabs(value) : 1.0;
    }
    const int decimals =
        std::min(12, std::max(0, -static_cast<int>(std::floor(std::log10(step)))));
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.*f", decimals, value);
    return buf;
}

}  // namespace pwb::viz_charts
