#pragma once

// pwb::mapping — factor extraction kernel, a faithful C++ port of
// GeologicalMappingPipeline.extract_factors
// (paleo_workbench/mapping/geological_pipeline/pipeline.py, M6).
// Behavior is frozen against the Python implementation via committed oracle
// fixtures (tools/oracle/generate_extract_fixtures.py):
//   * coordinate key families (audit #1150) in project / xy / lnglat /
//     longitude-latitude / surface order; first complete pair wins; 0.0 is
//     legal; no cross-pairing; coordinates[0:2] as a last resort;
//   * value lookup: exact factor_name, "value", "val", casefolded aliases,
//     then nested attributes / properties / metadata (factor_name, "value",
//     aliases — Python has no nested "val");
//   * derived sand_ratio = 100*Hs/Ht and formation_thickness = base-top
//     with provenance markers;
//   * FACTOR_DEFAULTS units (factor_units.py); unit=nullopt uses the table,
//     unit="" is an explicit empty string.
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>

#include <optional>
#include <string>
#include <vector>

namespace pwb::mapping {

using pwb::domain::Json;

struct ExtractOptions {
    std::string target_horizon;
    std::optional<std::string> unit;  // nullopt → FACTOR_DEFAULTS; "" kept
    std::string crs;
};

struct FactorPoint {
    std::string name;
    double value = 0.0;
    std::string unit;
    std::string well_id;
    std::string well_name;
    double x = 0.0;
    double y = 0.0;
    std::string crs;
    std::string formation;
    std::string qc_flag = "ok";
    Json metadata = Json::object();
};

struct FactorDataset {
    std::string factor_name;
    std::string unit;
    std::string target_horizon;
    std::string crs;
    std::vector<FactorPoint> points;
    Json metadata = Json::object();  // extract diagnostics
};

// records: JSON array of objects (non-objects skipped).
FactorDataset extract_factors(const Json& records,
                              const std::string& factor_name,
                              const ExtractOptions& options = {});

}  // namespace pwb::mapping
