#include <pwb/viz_charts/convex_hull.hpp>

#include <algorithm>
#include <cmath>

namespace pwb::viz_charts {
namespace {

// Lexicographic (x, then y) comparison — the np.lexsort((y, x)) primary key.
bool lex_less(const Point2& a, const Point2& b) {
    if (a.x != b.x) {
        return a.x < b.x;
    }
    return a.y < b.y;
}

double cross(const Point2& o, const Point2& a, const Point2& b) {
    return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
}

}  // namespace

std::vector<bool> point_in_polygon_mask(const std::vector<double>& x,
                                        const std::vector<double>& y,
                                        const std::vector<Point2>& poly) {
    const std::size_t n = x.size();
    std::vector<bool> inside(n, false);
    const std::size_t n_vert = poly.size();
    if (n_vert < 3) {
        return inside;
    }
    for (std::size_t p = 0; p < n; ++p) {
        const double px = x[p];
        const double py = y[p];
        bool flag = false;
        std::size_t j = n_vert - 1;
        for (std::size_t i = 0; i < n_vert; ++i) {
            const double xi = poly[i].x;
            const double yi = poly[i].y;
            const double xj = poly[j].x;
            const double yj = poly[j].y;
            const double den = (yj != yi) ? (yj - yi) : 1e-30;
            const bool straddles = (yi > py) != (yj > py);
            if (straddles &&
                px < (xj - xi) * (py - yi) / den + xi) {
                flag = !flag;
            }
            j = i;
        }
        inside[p] = flag;
    }
    return inside;
}

std::vector<Point2> compute_convex_hull(const std::vector<double>& x,
                                        const std::vector<double>& y) {
    std::vector<Point2> pts;
    pts.reserve(x.size());
    for (std::size_t i = 0; i < x.size() && i < y.size(); ++i) {
        if (!std::isnan(x[i]) && !std::isnan(y[i])) {
            pts.push_back({x[i], y[i]});
        }
    }
    if (pts.size() < 3) {
        return pts;
    }

    std::sort(pts.begin(), pts.end(), lex_less);
    // Degenerate input (all collinear / duplicated): the Python path hits
    // QhullError and returns the lexsorted selection; detect flatness the
    // same way (no strict turn anywhere) before running the chain.
    {
        bool has_turn = false;
        for (std::size_t i = 2; i < pts.size(); ++i) {
            if (std::fabs(cross(pts[i - 2], pts[i - 1], pts[i])) > 0.0) {
                has_turn = true;
                break;
            }
        }
        if (!has_turn) {
            return pts;  // already lexsorted
        }
    }

    // Andrew monotone chain, collinear points on the hull edges dropped
    // (Qhull's vertex output keeps only strict corners).
    std::vector<Point2> hull(2 * pts.size() + 1);
    std::size_t k = 0;
    for (const auto& p : pts) {
        while (k >= 2 && cross(hull[k - 2], hull[k - 1], p) <= 0.0) {
            --k;
        }
        hull[k++] = p;
    }
    const std::size_t lower = k + 1;
    for (auto it = pts.rbegin(); it != pts.rend(); ++it) {
        while (k >= lower && cross(hull[k - 2], hull[k - 1], *it) <= 0.0) {
            --k;
        }
        hull[k++] = *it;
    }
    hull.resize(k - 1);  // last point duplicates the first
    // Monotone chain starts at the lex-smallest point and walks CCW — the
    // same vertex cycle SciPy reports for 2D input.
    return hull;
}

}  // namespace pwb::viz_charts
