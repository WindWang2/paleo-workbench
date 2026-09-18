// Port of paleo_workbench/prediction/postprocess.py (CONV-21).
// Deterministic post-processing for persisted online facies predictions:
// adjacent compatible cells merge; formation tops are hard boundaries that
// a merge must never bridge. Frozen against the Python oracle
// (fixtures/prediction_contract_oracle.json).
#pragma once

#include <string>
#include <utility>
#include <vector>

#include "pwb/domain/json.hpp"

namespace pwb::prediction {

using pwb::domain::Json;

// (records, summary) — mirrors the Python tuple; `records` is a JSON array
// of region dicts, `summary` a JSON object with the six fixed keys.
struct PostprocessResult {
    Json records;
    Json summary;
};

// postprocess_prediction_regions(regions, *, formation_boundaries=None)
// regions: JSON array (or null); formation_boundaries: JSON array or null.
PostprocessResult postprocess_prediction_regions(
    const Json& regions, const Json& formation_boundaries);

// (boundaries, diagnostics) — boundaries: JSON array of
// {name, depth, source}; diagnostics: JSON array of strings.
struct ResolvedBoundaries {
    Json boundaries;
    Json diagnostics;
};

// resolve_formation_boundaries(well_name, *, well_log=None, inputs=None)
// well_log arrives as a JSON object whose keys play the role of the
// production object's attributes ({"intervals": {"formation": [...]}});
// inputs is a JSON object of {id: {asset_type, name, path}}.
ResolvedBoundaries resolve_formation_boundaries(
    const Json& well_name, const Json& well_log, const Json& inputs);

}  // namespace pwb::prediction
