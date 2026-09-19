// Survey geometry from a real seismic volume descriptor — the C++ map of
// geoviz_well_seismic_3d/segy_survey.py @ 08851951.
//
// Mapping decision (recorded in the VIZ-C ledger): the Python module
// spends most of its lines recovering corners from text headers and
// re-deriving loader axes because the Python loader could not expose
// them. libs/seismic_io's inspect_segy (CONV-SEISMIC, oracle-frozen)
// already returns the authoritative bin grid (SourceGroupScalar applied
// per trace, V6 §9 contract), line starts/steps/counts and dt — so the
// C++ path builds SurveySpec directly from the descriptor and fails
// closed when the file carries no usable bin grid or a non-TWT sample
// axis. Nothing is guessed.
#pragma once

#include <stdexcept>
#include <string>
#include <tuple>

#include "fence.hpp"
#include "survey.hpp"
#include <pwb/seismic_io/volume_descriptor.hpp>

namespace pwb::geo3d_viz::joint {

// SurveySpec in volume axes: (n_inlines, n_crosslines) match the
// descriptor's (ni, nc); line starts/steps match its numbering.
// Throws std::invalid_argument when:
//  * the descriptor has no bin grid (geometry not calibrated — never
//    fabricate 1 m bins at the origin, V6 §9 P0);
//  * the sample axis is not TWT milliseconds (unknown units are never
//    treated as ms — fail-closed).
SurveySpec survey_from_volume_descriptor(
    const pwb::seismic_io::VolumeDescriptor& descriptor);

// The three survey corners in loader axes, for validate_against_corners
// and horizon alignment: p1 = first (il, xl), p2 = same inline + last
// crossline, p3 = last (il, xl). XY from the bin grid (exact corners of
// the grid lattice).
std::tuple<Corner, Corner, Corner> survey_corners(
    const SurveySpec& survey);

}  // namespace pwb::geo3d_viz::joint
