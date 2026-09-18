#include "pwb/prediction/postprocess.hpp"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <set>
#include <sstream>

#include "pwb/ingest/py_compat.hpp"
#include "pwb/ingest/well_parsers.hpp"
#include "pwb/interchange/unicode.hpp"
#include "pwb/prediction/errors.hpp"
#include "python_compat.hpp"

namespace pwb::prediction {

namespace {

using detail::is_word_char;
using detail::keep_word_chars;
using detail::py_finite_number;
using detail::py_int;
using detail::py_isclose;
using detail::py_or;
using detail::py_path_name;
using detail::py_path_stem;
using detail::py_repr;
using detail::py_round6;
using detail::py_str;
using detail::py_strip;
using detail::py_truthy;

constexpr double kEpsilon = 1e-6;
constexpr const char* kUnspecifiedStratum = "未标定层位";

const Json kNull;

const Json& get(const Json& obj, const char* key) {
    if (!obj.is_object()) return kNull;
    const auto it = obj.find(key);
    return it == obj.end() ? kNull : *it;
}

// _bounds(item): (top, bottom) when both finite and bottom - top > eps.
std::optional<std::pair<double, double>> bounds(const Json& item) {
    const auto top = py_finite_number(get(item, "top"));
    const auto bottom = py_finite_number(get(item, "bottom"));
    if (!top || !bottom || *bottom - *top <= kEpsilon) return std::nullopt;
    return std::pair{*top, *bottom};
}

// _normalize_boundaries(boundaries): dedup by (round6(depth), stripped
// name), keep first; then collapse to one record per depth, keeping the
// first in (depth, name) sort order.
Json normalize_boundaries(const Json& boundaries) {
    std::vector<Json> deduped;
    std::set<std::pair<double, std::string>> seen;
    if (boundaries.is_array()) {
        for (const auto& boundary : boundaries) {
            if (!boundary.is_object()) continue;
            const auto depth = py_finite_number(get(boundary, "depth"));
            if (!depth) continue;
            const std::string name = py_strip(
                py_str(py_or(get(boundary, "name"), Json(kUnspecifiedStratum))));
            const std::pair key{py_round6(*depth), name};
            if (seen.insert(key).second) {
                deduped.push_back(Json{
                    {"name", name.empty() ? kUnspecifiedStratum : name},
                    {"depth", py_round6(*depth)},
                    {"source", py_str(py_or(get(boundary, "source"), Json("")))},
                });
            }
        }
    }
    std::sort(deduped.begin(), deduped.end(), [](const Json& a, const Json& b) {
        const auto da = a.at("depth").get<double>();
        const auto db = b.at("depth").get<double>();
        if (da != db) return da < db;
        return a.at("name").get_ref<const std::string&>() <
               b.at("name").get_ref<const std::string&>();
    });
    Json out = Json::array();
    std::set<double> seen_depths;
    for (const auto& b : deduped) {
        if (seen_depths.insert(b.at("depth").get<double>()).second) out.push_back(b);
    }
    return out;
}

// _split_bounds: cut strictly inside (top+eps, bottom-eps); keep segments
// thicker than eps.
std::vector<std::pair<double, double>> split_bounds(
    double top, double bottom, const Json& boundaries) {
    std::vector<double> points{top};
    for (const auto& b : boundaries) {
        const double d = b.at("depth").get<double>();
        if (top + kEpsilon < d && d < bottom - kEpsilon) points.push_back(d);
    }
    points.push_back(bottom);
    std::vector<std::pair<double, double>> out;
    for (size_t i = 0; i + 1 < points.size(); ++i) {
        if (points[i + 1] - points[i] > kEpsilon) {
            out.emplace_back(points[i], points[i + 1]);
        }
    }
    return out;
}

// _stratum_at: index/name of the deepest boundary at or below `depth`.
std::pair<long long, std::string> stratum_at(double depth, const Json& boundaries) {
    long long index = 0;
    std::string name = kUnspecifiedStratum;
    for (const auto& b : boundaries) {
        if (b.at("depth").get<double>() > depth + kEpsilon) break;
        ++index;
        name = py_str(b.at("name"));
    }
    return {index, name};
}

// _display_probability: clamp then whole-percent half-even, stored as the
// decimal (53% -> 0.53). int(f"{v:.0%}"[:-1]) == nearbyint(v*100): both
// round the same double half-even.
double display_probability(const Json& value) {
    const auto p = py_finite_number(value);
    if (!p) return 0.0;
    const double clamped = std::max(0.0, std::min(1.0, *p));
    return std::nearbyint(clamped * 100.0) / 100.0;
}

// _touches: |left.bottom - right.top| <= eps on the stored (rounded) bounds.
bool touches(const Json& left, const Json& right) {
    const auto lb = bounds(left);
    const auto rb = bounds(right);
    return lb && rb && std::fabs(lb->second - rb->first) <= kEpsilon;
}

// _well_key: Path(str(v or "")).stem.casefold() minus non-\w characters.
std::string well_key(const Json& value) {
    const std::string name = py_path_stem(py_str(py_or(value, Json(""))));
    return keep_word_chars(pwb::interchange::casefold_utf8(name));
}

}  // namespace

PostprocessResult postprocess_prediction_regions(
    const Json& regions, const Json& formation_boundaries) {
    const Json normalized = normalize_boundaries(formation_boundaries);

    std::vector<Json> source;
    if (regions.is_array()) {
        for (const auto& region : regions) {
            if (region.is_object() && bounds(region)) source.push_back(region);
        }
    }
    std::stable_sort(source.begin(), source.end(), [](const Json& a, const Json& b) {
        return *bounds(a) < *bounds(b);
    });

    struct SplitItem {
        Json item;
        long long layer_index;
        std::string layer_name;
    };
    std::vector<SplitItem> split;
    for (const auto& region : source) {
        const auto [top, bottom] = *bounds(region);
        for (const auto& [seg_top, seg_bottom] :
             split_bounds(top, bottom, normalized)) {
            Json item = region;
            item["top"] = py_round6(seg_top);
            item["bottom"] = py_round6(seg_bottom);
            auto [layer_index, layer_name] =
                stratum_at((seg_top + seg_bottom) / 2.0, normalized);
            if (!normalized.empty()) item["stratigraphic_unit"] = layer_name;
            split.push_back({std::move(item), layer_index, std::move(layer_name)});
        }
    }

    std::vector<SplitItem> merged;
    for (auto& entry : split) {
        const double probability = display_probability(get(entry.item, "probability"));
        const std::string facies = py_strip(py_str(py_or(get(entry.item, "facies"), Json(""))));
        if (!merged.empty()) {
            auto& prev = merged.back();
            const std::string prev_facies =
                py_strip(py_str(py_or(get(prev.item, "facies"), Json(""))));
            if (!facies.empty() && prev_facies == facies &&
                display_probability(get(prev.item, "probability")) == probability &&
                prev.layer_index == entry.layer_index &&
                touches(prev.item, entry.item)) {
                prev.item["bottom"] = entry.item["bottom"];
                prev.item["probability"] = probability;
                const Json& prev_count = prev.item.contains("merged_sample_count")
                    ? prev.item["merged_sample_count"] : Json(1);
                const Json& item_count = entry.item.contains("merged_sample_count")
                    ? entry.item["merged_sample_count"] : Json(1);
                prev.item["merged_sample_count"] =
                    py_int(py_or(prev_count, Json(1))) + py_int(py_or(item_count, Json(1)));
                continue;
            }
        }
        Json copied = entry.item;
        copied["probability"] = probability;
        merged.push_back({std::move(copied), entry.layer_index, std::move(entry.layer_name)});
    }

    Json records = Json::array();
    long long index = 0;
    for (auto& entry : merged) {
        entry.item["region_id"] =
            "inference_api_post_" + std::to_string(++index);
        records.push_back(std::move(entry.item));
    }
    Json summary = {
        {"applied", true},
        {"confidence_display_precision", "1%"},
        {"raw_region_count", static_cast<long long>(source.size())},
        {"split_region_count", static_cast<long long>(split.size())},
        {"postprocessed_region_count", static_cast<long long>(records.size())},
        {"formation_boundary_count", static_cast<long long>(normalized.size())},
    };
    return {std::move(records), std::move(summary)};
}

ResolvedBoundaries resolve_formation_boundaries(
    const Json& well_name, const Json& well_log, const Json& inputs) {
    const std::string target = well_key(well_name);
    Json boundaries = Json::array();
    Json diagnostics = Json::array();

    if (!inputs.is_object()) {
        // (inputs or {}).values(): truthy non-mapping -> AttributeError.
        if (py_truthy(inputs)) {
            throw AttributeError("'" + detail::py_type_name(inputs) +
                                 "' object has no attribute 'values'");
        }
    } else {
        for (const auto& [key, info] : inputs.items()) {
            if (!info.is_object()) {
                throw AttributeError("'" + detail::py_type_name(info) +
                                     "' object has no attribute 'get'");
            }
            if (py_str(py_or(get(info, "asset_type"), Json(""))) !=
                "well_stratification") {
                continue;
            }
            const std::string path_str = py_str(py_or(get(info, "path"), Json("")));
            const std::filesystem::path path(path_str);
            const Json& name_v = get(info, "name");
            const std::string label = py_truthy(name_v)
                ? py_str(name_v) : py_path_name(path_str);
            if (!std::filesystem::is_regular_file(path)) {
                diagnostics.push_back("井分层文件不可读取: " + label);
                continue;
            }
            // Python parse_well_tops reads utf-8 errors="replace"; the C++
            // ingest parser is equally tolerant, so the Python
            // "井分层解析失败 {name}: {Class}" branch is unreachable here
            // (21-decisions.md D8).
            std::ifstream in(path, std::ios::binary);
            std::ostringstream buf;
            buf << in.rdbuf();
            const auto text = pwb::ingest::decode_utf8(buf.str(), false);
            const auto rows = pwb::ingest::parse_well_tops_text(text.value_or(""));
            for (const auto& row : rows) {
                if (well_key(Json(row.well_name)) == target) {
                    boundaries.push_back(Json{
                        {"name", row.top_name.empty()
                                     ? std::string(kUnspecifiedStratum)
                                     : row.top_name},
                        {"depth", row.md},
                        {"source", "well_stratification"},
                    });
                }
            }
        }
    }

    // well_log is a JSON attribute bag: {"intervals": {"formation": [...]}}.
    // Non-object values behave like getattr() misses -> empty.
    Json formations = Json::array();
    if (well_log.is_object()) {
        const Json& intervals = get(well_log, "intervals");
        if (intervals.is_object() && get(intervals, "formation").is_array()) {
            formations = get(intervals, "formation");
        }
    }
    for (const auto& interval : formations) {
        const auto depth = py_finite_number(get(interval, "top"));
        if (!depth) continue;
        const Json& name_v = get(interval, "name");
        boundaries.push_back(Json{
            {"name", py_truthy(name_v) ? py_str(name_v)
                                       : std::string(kUnspecifiedStratum)},
            {"depth", *depth},
            {"source", "las_formation"},
        });
    }

    return {normalize_boundaries(boundaries), std::move(diagnostics)};
}

}  // namespace pwb::prediction
