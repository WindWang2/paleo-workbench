// CONV-20: pybind11 facade over the Qt-free pwb::mapping kernels.
//
// Exposes the three Python-facing entry points as top-level module
// `pwb_mapping_kernel` (consumed by the thin try/except facade in
// paleo_workbench/mapping/geological_pipeline/native_bind.py):
//
//   interpolate_factor(points, options) -> dict
//   extract_factors(records, factor_name, target_horizon="", unit=None, crs="") -> dict
//   nearest_neighbor_class_grid(points, extent, grid_n=80, clip_ring=None) -> dict
//
// This file is glue only: dicts/lists/scalars in, plain lists/dicts out
// (numpy stays on the Python side). Numeric behavior is frozen in the kernel
// headers (interpolator.hpp / extract.hpp / class_grid.hpp) against the
// committed Python oracles; the kernels' std::invalid_argument propagates to
// Python as ValueError with the exact frozen message text.

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/class_grid.hpp>
#include <pwb/mapping/extract.hpp>
#include <pwb/mapping/interpolator.hpp>

#include <array>
#include <string>
#include <utility>
#include <vector>

namespace py = pybind11;

using pwb::domain::Json;
using pwb::mapping::ClassGrid;
using pwb::mapping::ExtractOptions;
using pwb::mapping::FactorDataset;
using pwb::mapping::FactorGrid;
using pwb::mapping::FaciesPoint;
using pwb::mapping::FactorPoint;
using pwb::mapping::InterpolateOptions;
using pwb::mapping::SamplePoint;

#ifndef PWB_MAPPING_BIND_VERSION
#define PWB_MAPPING_BIND_VERSION "0.0.0-dev"
#endif

namespace {

// --- py -> Json: records arrive as arbitrary Python dicts -------------------
// A recursive converter (not json.dumps) keeps the int/float type distinction
// nlohmann enforces and carries NaN/inf doubles, which json.dumps would emit
// as a NaN literal the strict parser rejects.
Json to_json(py::handle obj) {
    if (obj.is_none()) return Json(nullptr);
    // bool before int: bool is an int subclass in Python.
    if (py::isinstance<py::bool_>(obj)) return Json(obj.cast<bool>());
    if (py::isinstance<py::int_>(obj)) {
        try {
            return Json(obj.cast<long long>());
        } catch (const py::cast_error&) {
            // Beyond int64: stay numeric like Python's float(x) would make
            // the value instead of failing the whole call. (A value beyond
            // double range still raises OverflowError here, like float().)
            return Json(obj.cast<double>());
        }
    }
    if (py::isinstance<py::float_>(obj)) return Json(obj.cast<double>());
    if (py::isinstance<py::str>(obj)) return Json(obj.cast<std::string>());
    if (py::isinstance<py::list>(obj) || py::isinstance<py::tuple>(obj)) {
        Json arr = Json::array();
        for (py::handle item : obj) arr.push_back(to_json(item));
        return arr;
    }
    if (py::isinstance<py::dict>(obj)) {
        Json out = Json::object();
        py::list items = obj.attr("items")();
        for (py::handle entry : items) {
            py::tuple kv = entry.cast<py::tuple>();
            out[py::str(kv[0]).cast<std::string>()] = to_json(kv[1]);
        }
        return out;
    }
    // Arbitrary objects: the kernels' numeric parsers reject their repr string
    // exactly like Python's float() rejects the object itself.
    return Json(py::repr(obj).cast<std::string>());
}

// --- Json -> py: extract diagnostics and per-point metadata -----------------
py::object from_json(const Json& value) {
    if (value.is_null()) return py::none();
    if (value.is_boolean()) return py::bool_(value.get<bool>());
    if (value.is_number_unsigned()) {
        return py::int_(value.get<unsigned long long>());
    }
    if (value.is_number_integer()) return py::int_(value.get<long long>());
    if (value.is_number_float()) return py::float_(value.get<double>());
    if (value.is_string()) return py::str(value.get<std::string>());
    if (value.is_array()) {
        py::list out;
        for (const Json& item : value) out.append(from_json(item));
        return out;
    }
    py::dict out;
    for (auto it = value.begin(); it != value.end(); ++it) {
        out[py::str(it.key())] = from_json(it.value());
    }
    return out;
}

py::object opt(const py::dict& d, const char* key) {
    if (d.contains(key)) return d[key].cast<py::object>();
    return py::none();
}

std::string get_str(const py::dict& d, const char* key, const char* fallback) {
    py::object v = opt(d, key);
    return v.is_none() ? std::string(fallback) : v.cast<std::string>();
}

double get_double(const py::dict& d, const char* key, double fallback) {
    py::object v = opt(d, key);
    return v.is_none() ? fallback : v.cast<double>();
}

int get_int(const py::dict& d, const char* key, int fallback) {
    py::object v = opt(d, key);
    return v.is_none() ? fallback : v.cast<int>();
}

py::dict factor_grid_to_dict(const FactorGrid& g) {
    py::dict statistics;
    statistics["min"] = g.statistics.min;
    statistics["max"] = g.statistics.max;
    statistics["mean"] = g.statistics.mean;
    statistics["std"] = g.statistics.std;
    statistics["valid_count"] = g.statistics.valid_count;
    statistics["total_count"] = g.statistics.total_count;

    py::dict out;
    out["grid_x"] = g.grid_x;
    out["grid_y"] = g.grid_y;
    out["grid_z"] = g.grid_z;
    out["variance_grid"] = g.variance_grid.empty()
        ? py::none()
        : py::cast(g.variance_grid);
    out["algorithm_id"] = g.algorithm_id;
    out["method"] = g.method;
    out["model"] = g.model;
    out["variogram_fit"] = g.variogram_fit;
    out["power"] = g.power;
    out["range"] = g.range;
    out["sill"] = g.sill;
    out["nugget"] = g.nugget;
    out["grid_n"] = g.grid_n;
    out["n_samples"] = g.n_samples;
    out["duplicates_merged"] = g.duplicates_merged;
    out["variogram_bins"] = g.variogram_bins;
    out["domain_masked_cells"] = g.domain_masked_cells;
    out["min_neighbors"] = g.min_neighbors;
    out["max_neighbors"] = g.max_neighbors.has_value()
        ? py::cast(*g.max_neighbors)
        : py::none();
    out["search_radius"] = g.search_radius.has_value()
        ? py::cast(*g.search_radius)
        : py::none();
    out["distance_policy"] = g.distance_policy;
    out["distance_policy_annotation"] = g.distance_policy_annotation;
    out["statistics"] = statistics;
    return out;
}

py::dict interpolate_factor_py(const py::sequence& points,
                               const py::dict& options) {
    std::vector<SamplePoint> pts;
    pts.reserve(py::len(points));
    for (py::handle handle : points) {
        const py::dict d = handle.cast<py::dict>();
        SamplePoint s;
        s.x = d["x"].cast<double>();
        s.y = d["y"].cast<double>();
        s.value = d["value"].cast<double>();
        py::object qc = opt(d, "qc_flag");
        if (!qc.is_none()) s.qc_flag = qc.cast<std::string>();
        pts.push_back(std::move(s));
    }

    InterpolateOptions o;
    o.method = get_str(options, "method", "idw");
    o.grid_n = get_int(options, "grid_n", 50);
    o.power = get_double(options, "power", 2.0);
    o.min_neighbors = get_int(options, "min_neighbors", 1);
    o.variogram_model = get_str(options, "variogram_model", "spherical");
    o.crs = get_str(options, "crs", "");
    o.distance_policy = get_str(options, "distance_policy", "planar");
    py::object max_neighbors = opt(options, "max_neighbors");
    if (!max_neighbors.is_none()) o.max_neighbors = max_neighbors.cast<int>();
    py::object search_radius = opt(options, "search_radius");
    if (!search_radius.is_none()) o.search_radius = search_radius.cast<double>();
    py::object boundary = opt(options, "boundary");
    if (!boundary.is_none()) {
        for (py::handle handle : boundary) {
            const py::sequence xy = handle.cast<py::sequence>();
            o.boundary.push_back(
                {xy[0].cast<double>(), xy[1].cast<double>()});
        }
    }

    return factor_grid_to_dict(
        pwb::mapping::interpolate_factor(pts, o));
}

py::dict extract_factors_py(const py::object& records,
                            const std::string& factor_name,
                            const std::string& target_horizon,
                            const py::object& unit,
                            const std::string& crs) {
    ExtractOptions o;
    o.target_horizon = target_horizon;
    if (!unit.is_none()) o.unit = unit.cast<std::string>();
    o.crs = crs;
    const FactorDataset ds =
        pwb::mapping::extract_factors(to_json(records), factor_name, o);

    py::list points;
    for (const FactorPoint& p : ds.points) {
        py::dict pd;
        pd["name"] = p.name;
        pd["value"] = p.value;
        pd["unit"] = p.unit;
        pd["well_id"] = p.well_id;
        pd["well_name"] = p.well_name;
        pd["x"] = p.x;
        pd["y"] = p.y;
        pd["crs"] = p.crs;
        pd["formation"] = p.formation;
        pd["qc_flag"] = p.qc_flag;
        pd["metadata"] = from_json(p.metadata);
        points.append(std::move(pd));
    }

    py::dict out;
    out["factor_name"] = ds.factor_name;
    out["unit"] = ds.unit;
    out["target_horizon"] = ds.target_horizon;
    out["crs"] = ds.crs;
    out["points"] = std::move(points);
    out["metadata"] = from_json(ds.metadata);
    return out;
}

py::dict nearest_neighbor_class_grid_py(const py::sequence& points,
                                        std::array<double, 4> extent,
                                        int grid_n,
                                        const py::object& clip_ring) {
    std::vector<FaciesPoint> pts;
    pts.reserve(py::len(points));
    for (py::handle handle : points) {
        const py::dict d = handle.cast<py::dict>();
        FaciesPoint f;
        f.x = d["x"].cast<double>();
        f.y = d["y"].cast<double>();
        f.facies = d["facies"].cast<std::string>();
        pts.push_back(std::move(f));
    }
    std::vector<pwb::mapping::Point> ring;
    if (!clip_ring.is_none()) {
        for (py::handle handle : clip_ring) {
            const py::sequence xy = handle.cast<py::sequence>();
            ring.push_back({xy[0].cast<double>(), xy[1].cast<double>()});
        }
    }

    const ClassGrid g =
        pwb::mapping::nearest_neighbor_class_grid(pts, extent, grid_n, ring);

    py::dict out;
    out["grid_x"] = g.grid_x;
    out["grid_y"] = g.grid_y;
    out["grid_z"] = g.grid_z;
    out["facies_names"] = g.facies_names;
    return out;
}

}  // namespace

PYBIND11_MODULE(pwb_mapping_kernel, m) {
    m.doc() = "Optional pybind11 facade over the pwb::mapping kernel "
              "(mapping_kernel C++ port, frozen against the Python oracles).";
    m.attr("__version__") = PWB_MAPPING_BIND_VERSION;
    m.def("interpolate_factor", &interpolate_factor_py,
          py::arg("points"), py::arg("options"),
          "IDW / Ordinary-Kriging (numpy-grid-OLS) grid from sample points.\n"
          "points: dicts with x, y, value, optional qc_flag. options: dict of\n"
          "InterpolationOptions fields. Raises ValueError on invalid input.");
    m.def("extract_factors", &extract_factors_py,
          py::arg("records"), py::arg("factor_name"),
          py::arg("target_horizon") = "", py::arg("unit") = py::none(),
          py::arg("crs") = "",
          "Extract typed factor points from raw record dicts (unit=None uses\n"
          "the FACTOR_DEFAULTS table; unit=\"\" is an explicit empty string).");
    m.def("nearest_neighbor_class_grid", &nearest_neighbor_class_grid_py,
          py::arg("points"), py::arg("extent"), py::arg("grid_n") = 80,
          py::arg("clip_ring") = py::none(),
          "Nearest-neighbor facies class grid (first-seen class ids, inclusive\n"
          "on-edge clip). Raises ValueError on empty points.");
}
