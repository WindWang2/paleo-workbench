#include <pwb/geomodel/measurements.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <stdexcept>
#include <string>

namespace pwb::geomodel {

namespace {

constexpr double kPi = 3.14159265358979323846;
// math.radians / np.degrees precompute the quotient and multiply once;
// a two-step deg*PI/180 rounds differently on ~30% of inputs.
constexpr double kDegToRad = kPi / 180.0;
constexpr double kRadToDeg = 180.0 / kPi;

void require_points(const std::vector<Vec3>& points, int minimum,
                    const std::string& oid) {
    if (static_cast<int>(points.size()) < minimum) {
        throw std::invalid_argument(
            oid + ": needs >= " + std::to_string(minimum) + " (x, y, z) points");
    }
    for (const auto& p : points) {
        if (!std::isfinite(p[0]) || !std::isfinite(p[1]) ||
            !std::isfinite(p[2])) {
            throw std::invalid_argument(oid + ": points must be finite");
        }
    }
}

std::string fmt(double value, const char* spec) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), spec, value);
    return buf;
}

// 3x3 symmetric Jacobi eigen solve; eigenvalues ascending in `lambda`,
// eigenvectors as COLUMNS of `vectors` (same convention as numpy eigh).
void jacobi_eigen(const double m[3][3], double lambda[3],
                  double vectors[3][3]) {
    double a[3][3] = {{m[0][0], m[0][1], m[0][2]},
                      {m[1][0], m[1][1], m[1][2]},
                      {m[2][0], m[2][1], m[2][2]}};
    double v[3][3] = {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
    for (int sweep = 0; sweep < 64; ++sweep) {
        double off = 0.0;
        for (int p = 0; p < 3; ++p) {
            for (int q = p + 1; q < 3; ++q) {
                off += a[p][q] * a[p][q];
            }
        }
        const double scale = std::fabs(a[0][0]) + std::fabs(a[1][1]) +
                             std::fabs(a[2][2]);
        if (off <= 1e-30 * scale * scale) {
            break;
        }
        for (int p = 0; p < 3; ++p) {
            for (int q = p + 1; q < 3; ++q) {
                if (std::fabs(a[p][q]) <=
                    1e-30 * (std::fabs(a[p][p]) + std::fabs(a[q][q]))) {
                    continue;
                }
                const double theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q]);
                const double t =
                    (theta >= 0 ? 1.0 : -1.0) /
                    (std::fabs(theta) + std::sqrt(theta * theta + 1.0));
                const double c = 1.0 / std::sqrt(t * t + 1.0);
                const double s = t * c;
                for (int k = 0; k < 3; ++k) {
                    const double akp = a[k][p];
                    const double akq = a[k][q];
                    a[k][p] = c * akp - s * akq;
                    a[k][q] = s * akp + c * akq;
                }
                for (int k = 0; k < 3; ++k) {
                    const double apk = a[p][k];
                    const double aqk = a[q][k];
                    a[p][k] = c * apk - s * aqk;
                    a[q][k] = s * apk + c * aqk;
                }
                for (int k = 0; k < 3; ++k) {
                    const double vkp = v[k][p];
                    const double vkq = v[k][q];
                    v[k][p] = c * vkp - s * vkq;
                    v[k][q] = s * vkp + c * vkq;
                }
            }
        }
    }
    int order[3] = {0, 1, 2};
    double diag[3] = {a[0][0], a[1][1], a[2][2]};
    std::sort(order, order + 3,
              [&](int x, int y) { return diag[x] < diag[y]; });
    for (int k = 0; k < 3; ++k) {
        lambda[k] = diag[order[k]];
        for (int r = 0; r < 3; ++r) {
            vectors[r][k] = v[r][order[k]];
        }
    }
}

}  // namespace

MeasurementResult point_coordinate(const Vec3& point, const std::string& crs,
                                   const std::string& unit) {
    const std::vector<Vec3> pts{point};
    require_points(pts, 1, "measure:point");
    MeasurementResult m;
    m.crs = crs;
    m.measurement_kind = "point";
    m.points = pts;
    m.unit = unit;
    m.extra_x = point[0];
    m.extra_y = point[1];
    m.extra_z = point[2];
    return m;
}

MeasurementResult distance(const Vec3& a, const Vec3& b,
                           const std::string& crs, const std::string& unit) {
    const std::vector<Vec3> pts{a, b};
    require_points(pts, 2, "measure:distance");
    const double dx = b[0] - a[0];
    const double dy = b[1] - a[1];
    const double dz = b[2] - a[2];
    MeasurementResult m;
    m.crs = crs;
    m.measurement_kind = "distance";
    m.points = pts;
    m.unit = unit;
    m.result = std::sqrt(dx * dx + dy * dy + dz * dz);
    return m;
}

MeasurementResult polyline_length(const std::vector<Vec3>& points,
                                  const std::string& crs,
                                  const std::string& unit) {
    require_points(points, 2, "measure:polyline");
    double total = 0.0;
    for (std::size_t k = 0; k + 1 < points.size(); ++k) {
        const double dx = points[k + 1][0] - points[k][0];
        const double dy = points[k + 1][1] - points[k][1];
        const double dz = points[k + 1][2] - points[k][2];
        total += std::sqrt(dx * dx + dy * dy + dz * dz);
    }
    MeasurementResult m;
    m.crs = crs;
    m.measurement_kind = "polyline";
    m.points = points;
    m.unit = unit;
    m.result = total;
    m.legs = static_cast<int>(points.size() - 1);
    return m;
}

MeasurementResult vertical_difference(const Vec3& a, const Vec3& b,
                                      const std::string& crs,
                                      const std::string& unit) {
    const std::vector<Vec3> pts{a, b};
    require_points(pts, 2, "measure:vert");
    MeasurementResult m;
    m.crs = crs;
    m.measurement_kind = "vertical_difference";
    m.points = pts;
    m.unit = unit;
    m.result = b[2] - a[2];
    m.dz = *m.result;
    return m;
}

std::optional<double> bilinear_z(const HorizonGrid& hor, double x, double y) {
    const double dy = hor.spacing_y;
    const double dx = hor.spacing_x;
    const double x0 = hor.origin_x;
    const double y0 = hor.origin_y;
    const double fj = dx != 0.0 ? (x - x0) / dx : 0.0;
    const double fi = dy != 0.0 ? (y - y0) / dy : 0.0;
    const int nI = hor.rows;
    const int nX = hor.cols;
    const int j0 = static_cast<int>(std::floor(fj));
    const int i0 = static_cast<int>(std::floor(fi));
    if (i0 < 0 || j0 < 0 || i0 > nI - 1 || j0 > nX - 1) {
        return std::nullopt;
    }
    // Clamp the upper corner so edge picks interpolate the last cell
    // instead of being misreported as holes. Python lets the index go to -1
    // on degenerate 1-row/1-column grids and relies on numpy wraparound
    // (g[-1] = last row/col); replicate that exactly.
    const int ic = std::min(i0, nI - 2);  // may be -1
    const int jc = std::min(j0, nX - 2);  // may be -1
    const double tj = fj - jc;
    const double ti = fi - ic;
    const auto wrap = [](int v, int n) { return v < 0 ? v + n : v; };
    const double c0 = hor.at(wrap(ic, nI), wrap(jc, nX));
    const double c1 = hor.at(wrap(ic, nI), wrap(jc + 1, nX));
    const double c2 = hor.at(wrap(ic + 1, nI), wrap(jc, nX));
    const double c3 = hor.at(wrap(ic + 1, nI), wrap(jc + 1, nX));
    if (!std::isfinite(c0) || !std::isfinite(c1) || !std::isfinite(c2) ||
        !std::isfinite(c3)) {
        return std::nullopt;
    }
    const double topmix = c0 * (1 - tj) + c1 * tj;
    const double botmix = c2 * (1 - tj) + c3 * tj;
    return topmix * (1 - ti) + botmix * ti;
}

MeasurementResult thickness_at(double x, double y, const HorizonGrid& top,
                               const HorizonGrid& base, const std::string& crs,
                               const std::string& unit) {
    if (top.vertical_domain != base.vertical_domain || top.unit != base.unit) {
        throw std::invalid_argument(
            "thickness: top/base must share vertical domain and unit");
    }
    const auto zt = bilinear_z(top, x, y);
    const auto zb = bilinear_z(base, x, y);
    if (!zt.has_value() || !zb.has_value()) {
        char buf[128];
        std::snprintf(buf, sizeof(buf),
                      "thickness at (%.2f, %.2f): point falls in a grid hole "
                      "(NaN) — thickness unknown",
                      x, y);
        throw std::invalid_argument(buf);
    }
    MeasurementResult m;
    m.crs = crs;
    m.measurement_kind = "thickness";
    m.points = {{x, y, *zt}, {x, y, *zb}};
    m.unit = unit.empty() ? top.unit : unit;
    m.result = std::fabs(*zb - *zt);
    m.top_id = top.object_id;
    m.base_id = base.object_id;
    m.signed_dz = *zb - *zt;
    return m;
}

MeasurementResult plane_orientation(const std::vector<Vec3>& points,
                                    const std::string& crs,
                                    const std::string& unit) {
    require_points(points, 3, "measure:plane");
    Vec3 centroid{0.0, 0.0, 0.0};
    for (const auto& p : points) {
        centroid[0] += p[0];
        centroid[1] += p[1];
        centroid[2] += p[2];
    }
    const double n = static_cast<double>(points.size());
    centroid[0] /= n;
    centroid[1] /= n;
    centroid[2] /= n;
    // Covariance (scatter) matrix of the centred picks; smallest-eigenvalue
    // eigenvector == numpy SVD vt[-1].
    double cov[3][3] = {{0, 0, 0}, {0, 0, 0}, {0, 0, 0}};
    for (const auto& p : points) {
        const double dc[3] = {p[0] - centroid[0], p[1] - centroid[1],
                              p[2] - centroid[2]};
        for (int r = 0; r < 3; ++r) {
            for (int cc = 0; cc < 3; ++cc) {
                cov[r][cc] += dc[r] * dc[cc];
            }
        }
    }
    // Zero scatter (all picks identical): numpy SVD of a zero matrix yields
    // the identity right-singular basis, i.e. the vertical normal with
    // dip 0 — mirror that instead of trusting an arbitrary eigenvector.
    const double scatter = std::max({std::fabs(cov[0][0]), std::fabs(cov[1][1]),
                                     std::fabs(cov[2][2])});
    double dip;
    double strike;
    double planarity;
    Vec3 normal;
    if (scatter == 0.0) {
        normal = {0.0, 0.0, 1.0};
        dip = 0.0;
        strike = 0.0;
        planarity = 0.0;  // s[0] <= 0 fallback
    } else {
        double lambda[3];
        double vectors[3][3];
        jacobi_eigen(cov, lambda, vectors);
        // smallest eigenvalue's eigenvector
        normal = {vectors[0][0], vectors[1][0], vectors[2][0]};
        if (normal[2] < 0) {
            normal = {-normal[0], -normal[1], -normal[2]};
        }
        dip = std::acos(std::clamp(std::fabs(normal[2]), 0.0, 1.0)) * kRadToDeg;
        strike = std::atan2(normal[1], normal[0]) * kRadToDeg;
        if (strike < 0) {
            strike += 180.0;
        }
        const double s0 = std::sqrt(std::max(lambda[2], 0.0));
        const double s1 = std::sqrt(std::max(lambda[1], 0.0));
        planarity = s0 > 0 ? s1 / s0 : 0.0;
    }

    MeasurementResult m;
    m.crs = crs;
    m.measurement_kind = "plane_orientation";
    m.points = points;
    m.unit = unit;
    m.result = dip;
    m.strike_deg = strike;
    m.dip_deg = dip;
    m.planarity_ratio = planarity;
    return m;
}

std::string format_result(const MeasurementResult& record) {
    const std::string& unit = record.unit;
    const std::string& kind = record.measurement_kind;
    if (kind == "point") {
        return "(" + fmt(record.extra_x, "%.2f") + ", " +
               fmt(record.extra_y, "%.2f") + ", " +
               fmt(record.extra_z, "%.2f") + ") " + unit;
    }
    if (kind == "distance") {
        return fmt(record.result.value_or(0.0), "%.3f") + " " + unit;
    }
    if (kind == "polyline") {
        return fmt(record.result.value_or(0.0), "%.3f") + " " + unit + " (" +
               std::to_string(record.legs) + " legs)";
    }
    if (kind == "vertical_difference") {
        const double r = record.result.value_or(0.0);
        const std::string sign = r >= 0 ? "+" : "";
        return sign + fmt(r, "%.3f") + " " + unit + " (vertical)";
    }
    if (kind == "thickness") {
        return fmt(record.result.value_or(0.0), "%.3f") + " " + unit +
               " (vertical thickness)";
    }
    if (kind == "plane_orientation") {
        return "strike " + fmt(record.strike_deg, "%.1f") + "° dip " +
               fmt(record.dip_deg, "%.1f") + "° (planarity " +
               fmt(record.planarity_ratio, "%.2f") + ")";
    }
    return fmt(record.result.value_or(0.0), "%g") + " " + unit;
}

}  // namespace pwb::geomodel
