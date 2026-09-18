#pragma once

// pwb::geomodel — advisor + lithology contract layer (CONV-22): faithful
// C++ ports of
//   * paleo_workbench/viz/geomodel/advisor.py  — deterministic borehole
//     consistency rules and coplanar-fault detection (records may be raw
//     dicts; number formatting in messages preserves int-vs-float like
//     Python str()).
//   * paleo_workbench/viz/geomodel/lithology.py — the four lithology
//     property tables, defaults, and sample_log_values (float32 array
//     semantics).
//
// Frozen against geomodel_contract_oracle.json.

#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/geomodel/domain_contract.hpp>  // TypeError / py_str helpers

namespace pwb::geomodel {

using pwb::domain::Json;

// advisor.check_boreholes — records arrive as JSON (dicts); non-dict
// entries raise TypeError ("Expected BoreholeRecord or dict, got
// <class 'int'>"). Returns the same dict shape as Python.
Json check_boreholes(const Json& records);

// advisor.check_coplanar_faults — same dict-input contract.
Json check_coplanar_faults(const Json& records);

// lithology tables (single home, mirroring the Python module constants).
const std::vector<std::pair<std::string, double>>& litho_gr();
const std::vector<std::pair<std::string, double>>& litho_sonic();
const std::vector<std::pair<std::string, double>>& litho_density();
const std::vector<std::pair<std::string, double>>& litho_ai();

constexpr double kDefaultGR = 60.0;
constexpr double kDefaultSonic = 180.0;
constexpr double kDefaultDensity = 2.4;
constexpr double kDefaultAI = 6000.0;

// All four tables + the four DEFAULT_* scalars, in the oracle's dict shape.
Json lithology_tables();

// lithology.sample_log_values — layers: [{top,bottom,lithology}...];
// depths: float array; table_name: "LITHO_GR" | "LITHO_SONIC" |
// "LITHO_DENSITY" | "LITHO_AI"; float32 assignment semantics.
Json sample_log_values(const Json& layers, const Json& depths,
                       const std::string& table_name, double dflt);

}  // namespace pwb::geomodel
