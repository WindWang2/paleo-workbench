#include <pwb/viz_charts/colormaps.hpp>

#include <cmath>

namespace pwb::viz_charts {
namespace {

const std::vector<ColorStop> kViridis{
    {0.0, {68, 1, 84}},    {0.25, {59, 82, 139}},  {0.5, {33, 145, 140}},
    {0.75, {94, 201, 98}}, {1.0, {253, 231, 37}},
};
const std::vector<ColorStop> kCnpcStrat{
    {0.0, {100, 110, 120}}, {0.35, {160, 175, 155}},
    {0.7, {255, 220, 95}},  {1.0, {90, 175, 255}},
};
const std::vector<ColorStop> kCnpcFluid{
    {0.0, {40, 115, 255}}, {0.5, {50, 220, 100}}, {1.0, {255, 55, 55}},
};
const std::vector<ColorStop> kThermal{
    {0.0, {0, 0, 150}},   {0.33, {0, 200, 200}},
    {0.66, {220, 220, 0}}, {1.0, {255, 0, 0}},
};

}  // namespace

const std::vector<ColorStop>& colormap(std::string_view name) {
    if (name == "cnpc_strat") {
        return kCnpcStrat;
    }
    if (name == "cnpc_fluid") {
        return kCnpcFluid;
    }
    if (name == "thermal") {
        return kThermal;
    }
    // Unknown names fall back to viridis (Python COLORMAPS.get default).
    return kViridis;
}

Rgb sample_colormap(std::string_view name, double val, double vmin, double vmax) {
    const auto& cmap = colormap(name);
    if (vmax == vmin) {
        return cmap.front().color;
    }
    double fraction = (val - vmin) / (vmax - vmin);
    fraction = std::max(0.0, std::min(1.0, fraction));

    for (std::size_t i = 0; i + 1 < cmap.size(); ++i) {
        const auto& [t1, c1] = cmap[i];
        const auto& [t2, c2] = cmap[i + 1];
        if (t1 <= fraction && fraction <= t2) {
            const double t_range = t2 - t1;
            if (t_range == 0.0) {
                return c1;
            }
            const double w = (fraction - t1) / t_range;
            return Rgb{
                static_cast<int>(c1.r + w * (c2.r - c1.r)),
                static_cast<int>(c1.g + w * (c2.g - c1.g)),
                static_cast<int>(c1.b + w * (c2.b - c1.b)),
            };
        }
    }
    return cmap.back().color;
}

}  // namespace pwb::viz_charts
