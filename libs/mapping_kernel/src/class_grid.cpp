#include <pwb/mapping/class_grid.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <unordered_map>

namespace pwb::mapping {
namespace {

bool on_segment(double x, double y, double x1, double y1, double x2, double y2,
                double epsilon) {
    const double cross = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1);
    const double segment_len = std::hypot(x2 - x1, y2 - y1);
    return std::fabs(cross) <= epsilon * std::max(1.0, segment_len)
           && std::min(x1, x2) - epsilon <= x
           && x <= std::max(x1, x2) + epsilon
           && std::min(y1, y2) - epsilon <= y
           && y <= std::max(y1, y2) + epsilon;
}

}  // namespace

bool point_in_ring_inclusive(double x, double y, const std::vector<Point>& ring,
                             double epsilon) {
    if (ring.size() < 3) return false;
    double previous_x = ring.back()[0];
    double previous_y = ring.back()[1];
    bool inside = false;
    for (const Point& p : ring) {
        const double current_x = p[0];
        const double current_y = p[1];
        if (on_segment(x, y, previous_x, previous_y, current_x, current_y,
                       epsilon)) {
            return true;
        }
        if ((current_y > y) != (previous_y > y)) {
            const double crossing_x =
                (previous_x - current_x) * (y - current_y)
                    / (previous_y - current_y)
                + current_x;
            if (x < crossing_x) inside = !inside;
        }
        previous_x = current_x;
        previous_y = current_y;
    }
    return inside;
}

ClassGrid nearest_neighbor_class_grid(
    const std::vector<FaciesPoint>& points,
    const std::array<double, 4>& extent,
    int grid_n,
    const std::vector<Point>& clip_ring) {
    if (points.empty()) {
        throw std::invalid_argument(
            "point-to-surface needs at least one well facies point");
    }
    ClassGrid out;
    std::unordered_map<std::string, int> index_of;
    std::vector<double> xs(points.size());
    std::vector<double> ys(points.size());
    std::vector<std::int16_t> classes(points.size());
    for (std::size_t i = 0; i < points.size(); ++i) {
        const auto it = index_of.find(points[i].facies);
        int cls;
        if (it == index_of.end()) {
            cls = static_cast<int>(out.facies_names.size());
            index_of.emplace(points[i].facies, cls);
            out.facies_names.push_back(points[i].facies);
        } else {
            cls = it->second;
        }
        xs[i] = points[i].x;
        ys[i] = points[i].y;
        classes[i] = static_cast<std::int16_t>(cls);
    }
    const int n = std::max(2, grid_n);
    out.grid_x = linspace(extent[0], extent[2], n);
    out.grid_y = linspace(extent[1], extent[3], n);
    const std::size_t m = static_cast<std::size_t>(n) * static_cast<std::size_t>(n);
    const std::size_t np = points.size();
    out.grid_z.resize(m);
    const bool clip = !clip_ring.empty();
    for (int row = 0; row < n; ++row) {
        const double y = out.grid_y[static_cast<std::size_t>(row)];
        for (int col = 0; col < n; ++col) {
            const double x = out.grid_x[static_cast<std::size_t>(col)];
            const std::size_t at =
                static_cast<std::size_t>(row) * static_cast<std::size_t>(n)
                + static_cast<std::size_t>(col);
            if (clip && !point_in_ring_inclusive(x, y, clip_ring)) {
                out.grid_z[at] = std::numeric_limits<float>::quiet_NaN();
                continue;
            }
            double best = std::numeric_limits<double>::infinity();
            std::size_t nearest = 0;
            for (std::size_t j = 0; j < np; ++j) {
                const double dx = x - xs[j];
                const double dy = y - ys[j];
                const double d2 = dx * dx + dy * dy;
                if (d2 < best) {
                    best = d2;
                    nearest = j;
                }
            }
            out.grid_z[at] =
                static_cast<float>(classes[nearest]);
        }
    }
    return out;
}

}  // namespace pwb::mapping
