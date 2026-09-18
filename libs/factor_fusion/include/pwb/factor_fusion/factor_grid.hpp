#pragma once

// Runtime carrier mirroring paleo_workbench.workflow.factor_grid_result
// .FactorGridResult — restricted to the surface factor_fusion touches
// (CONV-24 D2). grid_z / variance_grid keep float32 storage semantics
// (FactorGridResult normalises to a contiguous float32 buffer where every
// non-finite cell becomes NaN); axes are float64. algorithm_parameters is
// mutable JSON because fuse() writes class_thresholds / class_encoding back
// onto the produced grids.
//
// Qt-free, Python-free, numpy-free.

#include <pwb/domain/json.hpp>

#include <cmath>
#include <limits>
#include <optional>
#include <string>
#include <vector>

namespace pwb::factor_fusion {

using pwb::domain::Json;

struct FactorGrid {
    // Canonical grid: row-major height*width float32; NaN = nodata.
    std::vector<float> grid_z;
    int height = 0;
    int width = 0;
    std::vector<double> grid_x;  // width column coordinates
    std::vector<double> grid_y;  // height row coordinates

    // Identity / provenance.
    std::string factor_name;
    std::string algorithm_id;
    Json algorithm_parameters = Json::object();
    std::optional<std::string> crs;   // nullopt == source XY, undeclared
    std::optional<std::string> unit;  // nullopt == no declared unit
    std::optional<std::string> generator_version;
    std::optional<std::string> run_ref;
    std::vector<std::string> source_refs;

    // Optional algorithm output (kriging variance), float32, height*width.
    std::optional<std::vector<float>> variance_grid;
};

// float32-buffer semantics of FactorGridResult._to_float32_grid: cast every
// double to float; non-finite results become quiet NaN (inf included).
inline float to_grid_cell(double v) {
    const float f = static_cast<float>(v);
    return std::isfinite(f) ? f : std::numeric_limits<float>::quiet_NaN();
}

}  // namespace pwb::factor_fusion
