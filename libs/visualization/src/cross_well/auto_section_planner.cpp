#include <pwb/viz/cross_well/auto_section_planner.hpp>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <limits>
#include <map>
#include <utility>

namespace pwb::viz::cross_well {

namespace {

// First principal component of the (already centred) 2-column matrix:
// the top eigenvector of the 2x2 scatter matrix
//   A = [ sum(dx*dx)  sum(dx*dy) ;
//         sum(dx*dy)  sum(dy*dy) ]
// computed with the symmetric 2x2 eigen decomposition (closed form —
// numerically equivalent to numpy's SVD first right singular vector).
// Sign is FIXED so the largest-|component| entry is positive.
std::pair<double, double> first_principal_axis(
    const std::vector<double>& dx, const std::vector<double>& dy) {
    double sxx = 0.0, syy = 0.0, sxy = 0.0;
    for (std::size_t i = 0; i < dx.size(); ++i) {
        sxx += dx[i] * dx[i];
        syy += dy[i] * dy[i];
        sxy += dx[i] * dy[i];
    }
    // Symmetric eigen decomposition: theta = 0.5 * atan2(2*sxy, sxx-syy);
    // the axis with the LARGER eigenvalue is the first component.
    const double theta =
        0.5 * std::atan2(2.0 * sxy, sxx - syy);
    double vx = std::cos(theta);
    double vy = std::sin(theta);
    // Eigenvalues for the two axes; pick the larger.
    const double lambda1 =
        0.5 * (sxx + syy) +
        0.5 * std::sqrt((sxx - syy) * (sxx - syy) + 4.0 * sxy * sxy);
    const double lambda2 =
        0.5 * (sxx + syy) -
        0.5 * std::sqrt((sxx - syy) * (sxx - syy) + 4.0 * sxy * sxy);
    if (lambda2 > lambda1) {
        vx = -std::sin(theta);
        vy = std::cos(theta);
    }
    // Deterministic sign: largest-|component| positive (tie: x wins).
    if (std::abs(vx) >= std::abs(vy) ? vx < 0.0 : vy < 0.0) {
        vx = -vx;
        vy = -vy;
    }
    return {vx, vy};
}

}  // namespace

SectionPlanMethod parse_plan_method(const std::string& method) {
    std::string lowered;
    const auto first = method.find_first_not_of(" \t\r\n");
    const auto last = method.find_last_not_of(" \t\r\n");
    const std::string body =
        first == std::string::npos ? "" : method.substr(first, last - first + 1);
    lowered.reserve(body.size());
    for (unsigned char c : body) {
        lowered.push_back(static_cast<char>(std::tolower(c)));
    }
    if (lowered == "pca") return SectionPlanMethod::kPca;
    if (lowered == "nearest_neighbor" || lowered == "nn" || lowered == "tsp") {
        return SectionPlanMethod::kNearestNeighbor;
    }
    throw PlannerError("Unknown planning method: " + method +
                       ". Use 'pca' or 'nearest_neighbor'.");
}

std::vector<std::size_t> plan_section_pca(
    const std::vector<WellCoord>& wells) {
    const std::size_t n = wells.size();
    if (n <= 2) {
        std::vector<std::size_t> identity(n);
        for (std::size_t i = 0; i < n; ++i) identity[i] = i;
        return identity;
    }
    double cx = 0.0, cy = 0.0;
    for (const WellCoord& w : wells) {
        cx += w.lng;
        cy += w.lat;
    }
    cx /= static_cast<double>(n);
    cy /= static_cast<double>(n);
    std::vector<double> dx(n), dy(n);
    for (std::size_t i = 0; i < n; ++i) {
        dx[i] = wells[i].lng - cx;
        dy[i] = wells[i].lat - cy;
    }
    const auto [vx, vy] = first_principal_axis(dx, dy);
    std::vector<double> projections(n);
    for (std::size_t i = 0; i < n; ++i) {
        projections[i] = dx[i] * vx + dy[i] * vy;
    }
    // Stable: ties break by original index (argsort hardening, scope.md).
    std::vector<std::size_t> order(n);
    for (std::size_t i = 0; i < n; ++i) order[i] = i;
    std::stable_sort(order.begin(), order.end(),
                     [&](std::size_t a, std::size_t b) {
                         return projections[a] < projections[b];
                     });
    return order;
}

std::vector<std::size_t> plan_section_nearest_neighbor(
    const std::vector<WellCoord>& wells) {
    const std::size_t n = wells.size();
    if (n <= 2) {
        std::vector<std::size_t> identity(n);
        for (std::size_t i = 0; i < n; ++i) identity[i] = i;
        return identity;
    }
    const std::vector<std::size_t> pca = plan_section_pca(wells);
    // name -> index in Python dict order (first-seen position kept,
    // duplicate names overwrite the VALUE in place — `parsed[name] =
    // ...` parity). Insertion order drives the exact-equidistant tie
    // break, exactly like Python's dict iteration.
    std::vector<std::pair<std::string, std::size_t>> by_name;
    for (std::size_t i = 0; i < n; ++i) {
        bool found = false;
        for (auto& [name, idx] : by_name) {
            if (name == wells[i].name) {
                idx = i;
                found = true;
                break;
            }
        }
        if (!found) by_name.emplace_back(wells[i].name, i);
    }
    const std::size_t start = pca.front();
    std::vector<std::size_t> path{start};
    std::vector<bool> visited(n, false);
    visited[start] = true;
    while (path.size() < by_name.size()) {
        const WellCoord& current = wells[path.back()];
        std::size_t nearest = n;
        double min_dist = std::numeric_limits<double>::infinity();
        for (const auto& [name, idx] : by_name) {
            (void)name;
            if (visited[idx]) continue;
            const double dist =
                (wells[idx].lng - current.lng) *
                    (wells[idx].lng - current.lng) +
                (wells[idx].lat - current.lat) *
                    (wells[idx].lat - current.lat);
            if (dist < min_dist) {
                min_dist = dist;
                nearest = idx;
            }
        }
        if (nearest == n) break;
        path.push_back(nearest);
        visited[nearest] = true;
    }
    return path;
}

std::vector<std::size_t> plan_section(const std::vector<WellCoord>& wells,
                                      const std::string& method) {
    switch (parse_plan_method(method)) {
        case SectionPlanMethod::kPca:
            return plan_section_pca(wells);
        case SectionPlanMethod::kNearestNeighbor:
            return plan_section_nearest_neighbor(wells);
    }
    throw PlannerError("unreachable");
}

}  // namespace pwb::viz::cross_well
