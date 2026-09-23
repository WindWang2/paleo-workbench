// Role-band ordering — see layer_ordering.hpp. Vocabulary moved verbatim
// from pwb::workspace/layer_order.cpp (V14) when the order-key engine was
// retired with the second layer tree.
#include "pwb/ui_composite/layer_ordering.hpp"

namespace pwb::ui_composite {

const std::map<std::string, int>& role_bands() {
    static const std::map<std::string, int> bands = {
        // 020 selection/topology/QC overlays
        {"qc_warning", 20},
        {"qc_conflict", 21},
        // 030 map annotation
        {"map_annotation", 30},
        // 040 cartographic features
        {"map_symbol", 40},
        {"map_reference", 41},
        // 050 integrated interpretation
        {"integrated_facies", 50},
        {"integrated_boundary", 51},
        // 060 geological boundaries/symbols
        {"facies_boundary", 60},
        {"fault_constraint", 61},
        // 070 manual interpretation
        {"initial_facies_draft", 70},
        {"interpretation_annotation", 71},
        {"pending_review_area", 79},
        // 080 constraint lines
        {"provenance_direction", 80},
        {"provenance_line", 81},
        {"distribution_line", 82},
        {"paleo_shoreline", 83},
        {"interpolation_boundary", 84},
        {"mask_boundary", 85},
        // 090-100 factor pipeline order (render stack = pipeline downstream
        // on top, same order as factor_child_order)
        {"factor_input", 90},
        {"factor_grid", 92},
        {"factor_contour", 94},
        {"factor_classification", 96},
        {"factor_uncertainty", 98},
        {"factor_qc", 100},
        // 120 prediction layers
        {"well_facies_prediction", 120},
        {"well_facies_confidence", 122},
        {"seismic_facies_prediction", 124},
        {"seismic_facies_confidence", 126},
        // 130 initial facies
        {"initial_facies_source", 130},
        // 140 well/seismic footprint & analysis aids
        {"analysis_aid", 140},
        // 150 reference/basemap
        {"base_reference", 150},
        {"user_general", 155},
        {"legacy_unclassified", 158},
    };
    return bands;
}

int role_band(std::string_view role) {
    const auto& bands = role_bands();
    const auto it = bands.find(std::string(role));
    // Unknown role -> reference band; never throws.
    return it == bands.end() ? 150 : it->second;
}

int factor_role_rank(std::string_view role) {
    static const std::map<std::string, int> ranks = {
        {"factor_input", 0},       {"factor_grid", 1},
        {"factor_contour", 2},     {"factor_classification", 3},
        {"factor_uncertainty", 4}, {"factor_qc", 5},
    };
    const auto it = ranks.find(std::string(role));
    return it == ranks.end() ? 99 : it->second;  // unknown -> tail
}

BandSortKey band_sort_key(std::string_view role, long long sub_order,
                          std::string node_id) {
    return BandSortKey(role_band(role), sub_order, std::move(node_id));
}

}  // namespace pwb::ui_composite
