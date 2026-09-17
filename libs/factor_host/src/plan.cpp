#include <pwb/factor_host/plan.hpp>

#include <pwb/domain/sha256.hpp>
#include <pwb/factor_host/fingerprint.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <tuple>

namespace pwb::factor_host {

namespace {

void append_le_u64(std::string& out, std::uint64_t value) {
    for (int i = 0; i < 8; ++i) {
        out.push_back(static_cast<char>((value >> (8 * i)) & 0xFF));
    }
}

void append_le_f64(std::string& out, double value) {
    std::uint64_t bits = 0;
    static_assert(sizeof(bits) == sizeof(value), "64-bit double required");
    std::memcpy(&bits, &value, sizeof(bits));
    append_le_u64(out, bits);
}

std::string sha256_hex_prefix(const std::string& bytes, std::size_t keep) {
    std::string hex = pwb::domain::Sha256::of_bytes(bytes);
    hex.resize(keep);
    return hex;
}

std::string format_g(double value, int precision) {
    char buf[64];
    std::snprintf(buf, sizeof buf, "%.*g", precision, value);
    return buf;
}

std::vector<Polyline> polylines_from_json(const Json& value) {
    std::vector<Polyline> out;
    if (!value.is_array()) return out;
    for (const Json& poly : value) {
        if (!poly.is_array()) continue;
        Polyline line;
        for (const Json& p : poly) {
            if (!p.is_array() || p.size() < 2) continue;
            const auto px = finite_double(p.at(0));
            const auto py = finite_double(p.at(1));
            if (!px || !py) continue;
            line.emplace_back(*px, *py);
        }
        out.push_back(std::move(line));
    }
    return out;
}

}  // namespace

std::string xy_signature(const std::vector<double>& x,
                         const std::vector<double>& y) {
    std::string bytes;
    append_le_u64(bytes, static_cast<std::uint64_t>(x.size()));
    for (double v : x) append_le_f64(bytes, v);
    for (double v : y) append_le_f64(bytes, v);
    return sha256_hex_prefix(bytes, 24);
}

std::string fault_signature(const std::vector<Polyline>& polylines) {
    if (polylines.empty()) return "none";
    std::string joined;
    bool first_poly = true;
    for (const Polyline& poly : polylines) {
        if (!first_poly) joined += "|";
        first_poly = false;
        bool first_pt = true;
        for (const auto& [px, py] : poly) {
            if (!first_pt) joined += ",";
            first_pt = false;
            joined += format_g(px, 9);
            joined += ":";
            joined += format_g(py, 9);
        }
    }
    return sha256_hex_prefix(joined, 16);
}

std::string PlanKey::digest() const {
    std::string raw = method + "|" + xy_sig + "|" + std::to_string(grid_n) +
                      "|" + format_g(power, 12) + "|" + fault_sig + "|" +
                      format_g(azimuth_deg, 12) + "|" +
                      format_g(semi_major, 12) + "|" + format_g(semi_minor, 12);
    return sha256_hex_prefix(raw, 32);
}

std::vector<double> linspace(double start, double stop, int n) {
    // numpy.linspace: y = arange(num) * step + start; y[-1] = stop.
    std::vector<double> out(static_cast<std::size_t>(std::max(n, 0)));
    if (out.empty()) return out;
    const double step = (stop - start) / static_cast<double>(n - 1);
    for (std::size_t i = 0; i < out.size(); ++i) {
        out[i] = static_cast<double>(i) * step + start;
    }
    out.back() = stop;
    return out;
}

std::pair<std::vector<double>, std::vector<double>> grid_axes_from_samples(
    const std::vector<double>& x, const std::vector<double>& y, int grid_n) {
    const int n = std::max(2, grid_n);
    if (x.empty()) {
        return {linspace(0.0, 1.0, n), linspace(0.0, 1.0, n)};
    }
    const auto [x_min, x_max] =
        std::minmax_element(x.begin(), x.end());
    const auto [y_min, y_max] = std::minmax_element(y.begin(), y.end());
    const double pad_x = std::max((*x_max - *x_min) * 0.05, 1e-6);
    const double pad_y = std::max((*y_max - *y_min) * 0.05, 1e-6);
    return {linspace(*x_min - pad_x, *x_max + pad_x, n),
            linspace(*y_min - pad_y, *y_max + pad_y, n)};
}

Json InterpolationPlan::to_json() const {
    Json out = Json::object();
    Json key_json = Json::object();
    key_json["method"] = key.method;
    key_json["xy_sig"] = key.xy_sig;
    key_json["grid_n"] = key.grid_n;
    key_json["power"] = key.power;
    key_json["fault_sig"] = key.fault_sig;
    key_json["azimuth_deg"] = key.azimuth_deg;
    key_json["semi_major"] = key.semi_major;
    key_json["semi_minor"] = key.semi_minor;
    out["key"] = std::move(key_json);
    out["source_x"] = source_x;
    out["source_y"] = source_y;
    out["grid_x"] = grid_x;
    out["grid_y"] = grid_y;
    if (fault_polylines.empty()) {
        out["fault_polylines"] = Json();
    } else {
        Json polys = Json::array();
        for (const Polyline& poly : fault_polylines) {
            Json pts = Json::array();
            for (const auto& [px, py] : poly) {
                pts.push_back(Json::array({px, py}));
            }
            polys.push_back(std::move(pts));
        }
        out["fault_polylines"] = std::move(polys);
    }
    out["geometry_id"] = geometry_id;
    return out;
}

InterpolationPlan InterpolationPlan::from_json(const Json& value) {
    InterpolationPlan plan;
    const Json& key_json = value.at("key");
    plan.key.method = key_json.at("method").get<std::string>();
    plan.key.xy_sig = key_json.at("xy_sig").get<std::string>();
    plan.key.grid_n = key_json.at("grid_n").get<int>();
    plan.key.power = key_json.at("power").get<double>();
    plan.key.fault_sig = key_json.at("fault_sig").get<std::string>();
    plan.key.azimuth_deg = key_json.at("azimuth_deg").get<double>();
    plan.key.semi_major = key_json.at("semi_major").get<double>();
    plan.key.semi_minor = key_json.at("semi_minor").get<double>();
    plan.source_x = value.at("source_x").get<std::vector<double>>();
    plan.source_y = value.at("source_y").get<std::vector<double>>();
    plan.grid_x = value.at("grid_x").get<std::vector<double>>();
    plan.grid_y = value.at("grid_y").get<std::vector<double>>();
    const Json& polys = value.at("fault_polylines");
    if (!polys.is_null()) {
        plan.fault_polylines = polylines_from_json(polys);
    }
    plan.geometry_id = value.at("geometry_id").get<std::string>();
    return plan;
}

std::tuple<std::vector<double>, std::vector<double>, std::vector<double>>
extract_xy_values(const Json& sample_points) {
    std::vector<double> xs;
    std::vector<double> ys;
    std::vector<double> zs;
    if (!sample_points.is_array()) return {xs, ys, zs};
    for (const Json& pt : sample_points) {
        if (!pt.is_object()) continue;
        const Json* x_raw = nullptr;
        const Json* y_raw = nullptr;
        if (pt.contains("x") && pt.contains("y")) {
            x_raw = &pt.at("x");
            y_raw = &pt.at("y");
        } else if (pt.contains("lng") && pt.contains("lat")) {
            x_raw = &pt.at("lng");
            y_raw = &pt.at("lat");
        } else {
            continue;
        }
        const Json* z_raw = nullptr;
        if (pt.contains("value")) z_raw = &pt.at("value");
        else if (pt.contains("z")) z_raw = &pt.at("z");
        else if (pt.contains("v")) z_raw = &pt.at("v");
        const auto x = x_raw != nullptr ? finite_double(*x_raw) : std::nullopt;
        const auto y = y_raw != nullptr ? finite_double(*y_raw) : std::nullopt;
        const auto z = z_raw != nullptr ? finite_double(*z_raw) : std::nullopt;
        if (!x || !y || !z) continue;
        xs.push_back(*x);
        ys.push_back(*y);
        zs.push_back(*z);
    }
    return {std::move(xs), std::move(ys), std::move(zs)};
}

InterpolationPlan build_idw_plan(const Json& sample_points, int grid_n,
                                 double power,
                                 const std::vector<Polyline>* fault_polylines) {
    auto [x, y, z] = extract_xy_values(sample_points);
    if (z.size() < 2) {
        throw std::invalid_argument("插值至少需要 2 个有效采样点");
    }
    auto [gx, gy] = grid_axes_from_samples(x, y, grid_n);
    std::vector<Polyline> breaks;
    if (fault_polylines != nullptr) breaks = *fault_polylines;

    InterpolationPlan plan;
    plan.key.method = "idw";
    plan.key.xy_sig = xy_signature(x, y);
    plan.key.grid_n = grid_n;
    plan.key.power = power;
    plan.key.fault_sig = fault_signature(breaks);
    plan.source_x = std::move(x);
    plan.source_y = std::move(y);
    plan.grid_x = std::move(gx);
    plan.grid_y = std::move(gy);
    plan.fault_polylines = std::move(breaks);
    plan.geometry_id = plan.key.xy_sig + ":" + std::to_string(plan.key.grid_n);
    return plan;
}

std::vector<double> extract_values_aligned(const Json& sample_points,
                                           const InterpolationPlan& plan) {
    auto [x, y, z] = extract_xy_values(sample_points);
    if (x.size() != plan.source_x.size() || y.size() != plan.source_y.size()) {
        throw std::invalid_argument(
            "sample geometry does not match interpolation plan");
    }
    constexpr double kRtol = 1e-5;
    constexpr double kAtol = 1e-8;  // numpy.allclose defaults
    for (std::size_t i = 0; i < x.size(); ++i) {
        const double dx = std::fabs(x[i] - plan.source_x[i]);
        const double dy = std::fabs(y[i] - plan.source_y[i]);
        if (!(dx <= kAtol + kRtol * std::fabs(plan.source_x[i])) ||
            !(dy <= kAtol + kRtol * std::fabs(plan.source_y[i]))) {
            throw std::invalid_argument(
                "sample geometry does not match interpolation plan");
        }
    }
    return z;
}

std::shared_ptr<const InterpolationPlan> PlanCache::get(
    const std::string& geometry_key) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto it = items_.begin(); it != items_.end(); ++it) {
        if (it->first == geometry_key) {
            auto plan = it->second;
            items_.erase(it);  // move_to_end
            items_.emplace_back(geometry_key, std::move(plan));
            return items_.back().second;
        }
    }
    return nullptr;
}

void PlanCache::put(const std::string& geometry_key,
                    std::shared_ptr<const InterpolationPlan> plan) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto it = items_.begin(); it != items_.end(); ++it) {
        if (it->first == geometry_key) {
            items_.erase(it);
            break;
        }
    }
    items_.emplace_back(geometry_key, std::move(plan));
    while (items_.size() > kMaxEntries) {
        items_.erase(items_.begin());  // popitem(last=False)
    }
}

void PlanCache::clear() {
    std::lock_guard<std::mutex> lock(mutex_);
    items_.clear();
}

Json PlanCache::stats() const {
    std::lock_guard<std::mutex> lock(mutex_);
    Json out = Json::object();
    out["entries"] = static_cast<int>(items_.size());
    out["max_entries"] = static_cast<int>(kMaxEntries);
    return out;
}

}  // namespace pwb::factor_host
