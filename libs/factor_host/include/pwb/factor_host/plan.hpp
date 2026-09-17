#pragma once

// pwb::factor_host — reusable spatial plans for multi-factor interpolation,
// the data-structure slice of paleo_workbench/workflow/interpolation_plan.py
// (CONV-08): geometry identity (xy_signature / fault_signature / PlanKey),
// grid axes, build_idw_plan, extract_values_aligned, the session plan cache
// and a JSON round-trip (host-side addition — Python has no plan codec).
//
// The value-dependent IDW apply path (_idw_multi_chunked / apply_idw_plan*)
// and the LOS fault-mask engine stay on the Python side for now; the frozen
// oracle pins the geometry this slice owns.
// Qt-free, Python-free, numpy-free.

#include <pwb/domain/json.hpp>

#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace pwb::factor_host {

using pwb::domain::Json;

using Polyline = std::vector<std::pair<double, double>>;

// Stable content hash of source coordinates (order-preserving):
// sha256(uint64 LE count + x float64 LE bytes + y float64 LE bytes)[:24].
std::string xy_signature(const std::vector<double>& x,
                         const std::vector<double>& y);

// "none" for empty input, else sha256("x:y,x:y|x:y…")[:16] with %.9g.
std::string fault_signature(const std::vector<Polyline>& polylines);

struct PlanKey {
    std::string method;
    std::string xy_sig;
    int grid_n = 0;
    double power = 2.0;
    std::string fault_sig;
    double azimuth_deg = 0.0;
    double semi_major = 1.0;
    double semi_minor = 0.4;

    // sha256("method|xy_sig|grid_n|power:%.12g|fault_sig|az:%.12g|…")[:32]
    std::string digest() const;
};

// numpy-linspace semantics: y[i] = i*step + start with y[n-1] = stop.
std::vector<double> linspace(double start, double stop, int n);

// geo-viz _grid_axes padding (5% span, min pad 1e-6); empty samples →
// (0..1)² axes; grid_n clamped to ≥ 2.
std::pair<std::vector<double>, std::vector<double>> grid_axes_from_samples(
    const std::vector<double>& x, const std::vector<double>& y, int grid_n);

struct InterpolationPlan {
    PlanKey key;
    std::vector<double> source_x;
    std::vector<double> source_y;
    std::vector<double> grid_x;
    std::vector<double> grid_y;
    std::vector<Polyline> fault_polylines;  // empty = none
    std::string geometry_id;                // defaults to "{xy_sig}:{grid_n}"

    Json to_json() const;
    static InterpolationPlan from_json(const Json& value);
};

// (x, y, z) arrays from host sample_points records (x/y or lng/lat;
// value/z/v; non-finite entries skipped) — the geoviz extract_xy_values
// contract, ported locally so the plan slice stays engine-free.
std::tuple<std::vector<double>, std::vector<double>, std::vector<double>>
extract_xy_values(const Json& sample_points);

// Build a plain-IDW plan. Throws std::invalid_argument with the Python text
// when fewer than two valid samples survive.
InterpolationPlan build_idw_plan(const Json& sample_points, int grid_n = 50,
                                 double power = 2.0,
                                 const std::vector<Polyline>* fault_polylines =
                                     nullptr);

// Extract z values aligned with the plan's source XY (re-runs the validity
// filter); throws std::invalid_argument on geometry drift.
std::vector<double> extract_values_aligned(const Json& sample_points,
                                           const InterpolationPlan& plan);

// Session plan cache (geometry fingerprint → plan), bounded LRU like the
// Python _PLAN_CACHE (max 32 entries, move-to-end on hit).
class PlanCache {
public:
    std::shared_ptr<const InterpolationPlan> get(const std::string& geometry_key);
    void put(const std::string& geometry_key,
             std::shared_ptr<const InterpolationPlan> plan);
    void clear();
    Json stats() const;  // {"entries": n, "max_entries": 32}

private:
    static constexpr std::size_t kMaxEntries = 32;
    mutable std::mutex mutex_;
    // Back = most recently used. 32 entries make linear scan the simplest
    // correct implementation.
    std::vector<std::pair<std::string, std::shared_ptr<const InterpolationPlan>>>
        items_;
};

}  // namespace pwb::factor_host
