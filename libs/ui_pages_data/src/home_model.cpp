// UI-06 — home page pure helpers (home_page.py).
#include <pwb/ui_pages_data/home_model.hpp>

#include <cmath>

namespace pwb::ui_pages_data {

std::string pick_well(const std::vector<WellPickPoint>& points,
                      double click_x, double click_y, double radius) {
    // Python: best_dist starts at the radius; `dist <= best_dist` admits
    // boundary hits and lets a later equal-distance point overwrite.
    std::string best_id;
    double best_dist = radius;
    for (const auto& point : points) {
        const double dx = point.x - click_x;
        const double dy = point.y - click_y;
        const double dist = std::sqrt(dx * dx + dy * dy);
        if (dist <= best_dist) {
            best_dist = dist;
            best_id = point.well_id;
        }
    }
    return best_id;
}

bool start_guide_visible(long long total_resources, bool has_report) {
    return total_resources == 0 && !has_report;
}

long long sum_resource_counts(const pwb::domain::Json& resource_counts) {
    // `sum(int(v) for v in resource_counts.values())` in try/except → 0.
    if (!resource_counts.is_object()) return 0;
    long long total = 0;
    for (const auto& [_, v] : resource_counts.items()) {
        if (v.is_boolean()) {
            total += v.get<bool>() ? 1 : 0;
        } else if (v.is_number_integer() || v.is_number_unsigned()) {
            total += v.get<long long>();
        } else if (v.is_number_float()) {
            total += static_cast<long long>(v.get<double>());
        } else if (v.is_string()) {
            // int(" 3 ") works in Python; int("x") → except → total 0.
            try {
                const std::string& s = v.get_ref<const std::string&>();
                std::size_t used = 0;
                const long long n = std::stoll(s, &used);
                // Python int() allows surrounding whitespace only.
                for (std::size_t i = used; i < s.size(); ++i) {
                    if (s[i] != ' ' && s[i] != '\t' && s[i] != '\n' &&
                        s[i] != '\r' && s[i] != '\f' && s[i] != '\v') {
                        return 0;
                    }
                }
                total += n;
            } catch (...) {
                return 0;
            }
        } else {
            return 0;  // int(dict/list/None) → TypeError → total 0
        }
    }
    return total;
}

}  // namespace pwb::ui_pages_data
