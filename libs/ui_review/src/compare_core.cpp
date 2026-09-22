#include "pwb/ui_review/compare_core.hpp"

#include <algorithm>
#include <map>

namespace pwb::ui_review {

namespace {

using domain::Json;

std::string field_string(const Json& object, const char* key) {
    if (!object.is_object()) {
        return {};
    }
    const auto it = object.find(key);
    return it != object.end() && it->is_string() ? it->get<std::string>()
                                                 : std::string();
}

double field_double(const Json& object, const char* key, double fallback) {
    if (!object.is_object()) {
        return fallback;
    }
    const auto it = object.find(key);
    if (it == object.end() || !it->is_number()) {
        return fallback;
    }
    return it->get<double>();
}

}  // namespace

const char* compare_mode_label(CompareMode mode) {
    switch (mode) {
        case CompareMode::SideBySide: return "并排";
        case CompareMode::Overlay: return "叠加";
        case CompareMode::Difference: return "差异";
    }
    return "并排";  // unreachable, kept honest
}

std::optional<CompareMode> compare_mode_from_string(
    const std::string& value) {
    if (value == "side_by_side") return CompareMode::SideBySide;
    if (value == "overlay") return CompareMode::Overlay;
    if (value == "difference") return CompareMode::Difference;
    return std::nullopt;
}

std::vector<CompareBand> bands_from_interpretation(
    const Json& interp_ref, const Json& scientific) {
    std::vector<CompareBand> bands;
    // FormationTop rows: {well_id, well_name, marker, depth, status, ...}
    // under the artifact's scientific payload ("tops").
    const Json* tops = nullptr;
    if (scientific.is_object()) {
        const auto it = scientific.find("tops");
        if (it != scientific.end() && it->is_array()) {
            tops = &*it;
        }
    }
    if (tops == nullptr) {
        return bands;
    }
    const std::string interp_id = field_string(interp_ref, "id");
    const std::string interp_name = field_string(interp_ref, "name");
    const std::string domain_name = [&]() {
        const auto it = interp_ref.find("depth_domain");
        if (it != interp_ref.end() && it->is_string()) {
            return it->get<std::string>();
        }
        return std::string("MD");
    }();

    // Group active tops per well; bands form between consecutive depths.
    struct Top {
        std::string well_id;
        std::string well_name;
        std::string unit;
        double depth;
    };
    std::map<std::string, std::vector<Top>> per_well;
    for (const Json& top : *tops) {
        if (!top.is_object()) continue;
        const std::string status = field_string(top, "status");
        if (status == "rejected") continue;  // active interpretation only
        const std::string well_id = field_string(top, "well_id");
        const std::string well_name = field_string(top, "well_name");
        const std::string marker = field_string(top, "marker");
        const double depth = field_double(top, "depth", 0.0);
        // The grouping key falls back to the display name only when the
        // id is absent; the BAND keeps the raw id so it pairs with the
        // prediction side (same well identity vocabulary).
        const std::string key = well_id.empty() ? ("name:" + well_name)
                                                : ("id:" + well_id);
        per_well[key].push_back({well_id, well_name, marker, depth});
        (void)interp_id;
        (void)interp_name;
    }
    for (auto& [key, rows] : per_well) {
        (void)key;
        std::sort(rows.begin(), rows.end(),
                  [](const Top& a, const Top& b) { return a.depth < b.depth; });
        for (size_t i = 1; i < rows.size(); ++i) {
            if (rows[i].depth <= rows[i - 1].depth) continue;
            CompareBand band;
            band.well_id = rows[i - 1].well_id;
            band.well_name = rows[i - 1].well_name;
            band.unit = rows[i - 1].unit;  // the overlying boundary names it
            // Interpretation tops carry no facies/lithology class — the
            // klass stays empty and the UI shows 未标注 (never invented).
            band.top = rows[i - 1].depth;
            band.bottom = rows[i].depth;
            band.domain = domain_name;
            bands.push_back(std::move(band));
        }
    }
    return bands;
}

std::vector<CompareBand> bands_from_prediction(const Json& task) {
    std::vector<CompareBand> bands;
    const Json* regions = nullptr;
    if (task.is_object()) {
        const auto summary_it = task.find("result_summary");
        if (summary_it != task.end() && summary_it->is_object()) {
            const auto regions_it = summary_it->find("predicted_regions");
            if (regions_it != summary_it->end() && regions_it->is_array()) {
                regions = &*regions_it;
            }
        }
    }
    if (regions == nullptr) {
        return bands;
    }
    for (const Json& region : *regions) {
        if (!region.is_object()) continue;
        CompareBand band;
        band.well_id = field_string(region, "well_id");
        band.well_name = field_string(region, "well_name");
        band.unit = field_string(region, "stratigraphic_unit");
        if (band.unit.empty()) {
            band.unit = field_string(region, "horizon");
        }
        band.klass = field_string(region, "facies");
        band.taxonomy = band.klass.empty() ? "" : "facies";
        band.top = field_double(region, "top", 0.0);
        band.bottom = field_double(region, "bottom", 0.0);
        band.confidence = field_double(region, "probability", 0.0);
        bands.push_back(std::move(band));
    }
    return bands;
}

std::vector<BandPair> pair_bands(
    const std::vector<CompareBand>& interpretation,
    const std::vector<CompareBand>& prediction) {
    struct Acc {
        BandPair pair;
        bool interpreted_class_set = false;
        bool predicted_class_set = false;
    };
    std::map<std::string, Acc> table;
    auto accrue = [&table](const char* side, const CompareBand& band) {
        const std::string key = band.well_id + "|" + band.unit;
        Acc& acc = table[key];
        if (side[0] == 'i') {
            acc.pair.in_interpretation = true;
            acc.pair.interpreted_class = band.klass;
            acc.pair.well_id = band.well_id;
            acc.pair.well_name = band.well_name;
            acc.pair.unit = band.unit;
            acc.interpreted_class_set = !band.klass.empty();
            if (acc.pair.top == 0.0 && acc.pair.bottom == 0.0) {
                acc.pair.top = band.top;
                acc.pair.bottom = band.bottom;
            }
        } else {
            acc.pair.in_prediction = true;
            acc.pair.predicted_class = band.klass;
            acc.pair.well_id = band.well_id;
            acc.pair.well_name = band.well_name;
            acc.pair.unit = band.unit;
            acc.predicted_class_set = !band.klass.empty();
            acc.pair.top = band.top;
            acc.pair.bottom = band.bottom;
        }
    };
    for (const auto& band : interpretation) accrue("interpretation", band);
    for (const auto& band : prediction) accrue("prediction", band);

    std::vector<BandPair> pairs;
    for (auto& [key, acc] : table) {
        BandPair pair = acc.pair;
        pair.comparable =
            acc.pair.in_interpretation && acc.pair.in_prediction &&
            acc.interpreted_class_set && acc.predicted_class_set;
        if (pair.comparable) {
            // The (well, unit) pairing already implies the shared unit
            // interval — the match verdict is the class equality on it.
            pair.match =
                acc.pair.interpreted_class == acc.pair.predicted_class;
        }
        (void)key;
        pairs.push_back(std::move(pair));
    }
    return pairs;
}

CompareSummary summarize_pairs(const std::vector<BandPair>& pairs) {
    CompareSummary summary;
    for (const auto& pair : pairs) {
        if (pair.comparable) {
            if (pair.match) {
                ++summary.matched;
            } else {
                ++summary.mismatched;
            }
        } else if (pair.in_interpretation && pair.in_prediction) {
            ++summary.incomparable;
        } else if (pair.in_interpretation) {
            ++summary.interpretation_only;
        } else {
            ++summary.prediction_only;
        }
    }
    return summary;
}

}  // namespace pwb::ui_review
