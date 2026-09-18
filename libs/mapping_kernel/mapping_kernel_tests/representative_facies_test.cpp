// mapping_kernel.representative_facies — C++ port vs the frozen Python oracle
// (tools/oracle/generate_representative_facies_fixtures.py). Numbers compare
// with a 1e-9 relative tolerance: the C++ linspace/grid arithmetic is a
// faithful port, not bit-identical to numpy, so re-derived grid coordinates
// and their derived areas can differ in the last ulps. Types, strings, key
// sets and null-vs-value are exact: a float where Python froze an int
// (e.g. facies_id) is a failure.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/representative_facies.hpp>

using pwb::domain::Json;
using pwb::mapping::RepresentativeFacies;
using pwb::mapping::WellFaciesPoint;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

bool number_close(double got, double want) {
    const double tolerance = 1e-9 * std::max(1.0, std::fabs(want));
    return std::fabs(got - want) <= tolerance;
}

// Type-sensitive structural compare: int-vs-float is a type difference,
// floats compare with the tolerance above, object key SETS must match.
bool json_close(const Json& got, const Json& want, const std::string& path,
                std::string* reason) {
    if (want.is_null() != got.is_null()) {
        *reason = path + ": null-vs-value";
        return false;
    }
    if (want.is_null()) return true;
    if (want.is_boolean() || got.is_boolean()) {
        if (want.is_boolean() != got.is_boolean() ||
            want.get<bool>() != got.get<bool>()) {
            *reason = path + ": bool";
            return false;
        }
        return true;
    }
    if (want.is_string() || got.is_string()) {
        if (!want.is_string() || !got.is_string() ||
            want.get<std::string>() != got.get<std::string>()) {
            *reason = path + ": string";
            return false;
        }
        return true;
    }
    if (want.is_number() || got.is_number()) {
        if (!want.is_number() || !got.is_number() ||
            want.is_number_float() != got.is_number_float()) {
            *reason = path + ": number type (int vs float)";
            return false;
        }
        if (want.is_number_float()) {
            if (!number_close(got.get<double>(), want.get<double>())) {
                *reason = path + ": float value";
                return false;
            }
        } else if (want.get<long long>() != got.get<long long>()) {
            *reason = path + ": int value";
            return false;
        }
        return true;
    }
    if (want.is_array()) {
        if (!got.is_array() || want.size() != got.size()) {
            *reason = path + ": array size";
            return false;
        }
        for (std::size_t i = 0; i < want.size(); ++i) {
            if (!json_close(got[i], want[i],
                            path + "[" + std::to_string(i) + "]", reason)) {
                return false;
            }
        }
        return true;
    }
    if (want.is_object()) {
        if (!got.is_object() || want.size() != got.size()) {
            *reason = path + ": object size";
            return false;
        }
        for (auto it = want.begin(); it != want.end(); ++it) {
            const auto got_it = got.find(it.key());
            if (got_it == got.end()) {
                *reason = path + ": missing key " + it.key();
                return false;
            }
            if (!json_close(*got_it, *it, path + "." + it.key(), reason)) {
                return false;
            }
        }
        return true;
    }
    *reason = path + ": unsupported type";
    return false;
}

bool json_close(const Json& got, const Json& want, const std::string& path) {
    std::string reason;
    const bool ok = json_close(got, want, path, &reason);
    if (!ok) check(false, path + ": " + reason);
    return ok;
}

std::vector<WellFaciesPoint> points_from_json(const Json& arr) {
    std::vector<WellFaciesPoint> out;
    for (const auto& p : arr) {
        WellFaciesPoint point;
        point.x = p.at("x").get<double>();
        point.y = p.at("y").get<double>();
        point.facies = p.at("facies").get<std::string>();
        const auto well_id = p.find("well_id");
        if (well_id != p.end() && well_id->is_string()) {
            point.well_id = well_id->get<std::string>();
        }
        const auto well_name = p.find("well_name");
        if (well_name != p.end() && well_name->is_string()) {
            point.well_name = well_name->get<std::string>();
        }
        const auto probability = p.find("probability");
        if (probability != p.end() && probability->is_number()) {
            point.probability = probability->get<double>();
        }
        const auto task_id = p.find("task_id");
        if (task_id != p.end() && task_id->is_string()) {
            point.task_id = task_id->get<std::string>();
        }
        const auto thickness = p.find("thickness");
        if (thickness != p.end() && thickness->is_number()) {
            point.thickness = thickness->get<double>();
        }
        out.push_back(std::move(point));
    }
    return out;
}

Json point_to_json(const WellFaciesPoint& p) {
    Json out = Json::object();
    out["x"] = p.x;
    out["y"] = p.y;
    out["facies"] = p.facies;
    out["well_id"] = p.well_id;
    out["well_name"] = p.well_name;
    out["probability"] = p.probability ? Json(*p.probability) : Json();
    out["task_id"] = p.task_id;
    out["thickness"] = p.thickness ? Json(*p.thickness) : Json();
    return out;
}

Json features_to_json(const std::vector<std::pair<Json, Json>>& features) {
    Json out = Json::array();
    for (const auto& feature : features) {
        Json record = Json::object();
        record["geometry"] = feature.first;
        record["properties"] = feature.second;
        out.push_back(std::move(record));
    }
    return out;
}

Json points_to_json(const std::vector<WellFaciesPoint>& points) {
    Json out = Json::array();
    for (const auto& point : points) out.push_back(point_to_json(point));
    return out;
}

}  // namespace

int main() {
    const std::string fixture_path = PWB_REPRESENTATIVE_FACIES_FIXTURE;
    std::ifstream stream(fixture_path, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open %s\n", fixture_path.c_str());
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const Json oracle = Json::parse(buffer.str());

    // --- representative_facies ------------------------------------------
    {
        const auto& cases = oracle["representative_facies_cases"];
        int n = 0;
        for (const auto& c : cases) {
            ++n;
            const std::string id = c["id"].get<std::string>();
            const auto got = pwb::mapping::representative_facies(
                c["regions"], c["horizon"].get<std::string>());
            const auto& expected = c["expected"];
            if (expected.is_null()) {
                check(!got.has_value(), id + ": expected None");
                continue;
            }
            check(got.has_value(), id + ": expected a pick");
            if (!got.has_value()) continue;
            check(got->facies == expected[0].get<std::string>(),
                  id + ": facies");
            if (expected[1].is_null()) {
                check(!got->mean_probability.has_value(),
                      id + ": mean_p None");
            } else {
                check(got->mean_probability.has_value() &&
                          number_close(*got->mean_probability,
                                       expected[1].get<double>()),
                      id + ": mean_p");
            }
            check(number_close(got->thickness, expected[2].get<double>()),
                  id + ": thickness");
        }
        check(n == 25, "all 25 representative_facies cases exercised");
    }

    // --- task_regions -----------------------------------------------------
    {
        const auto& cases = oracle["task_region_cases"];
        int n = 0;
        for (const auto& c : cases) {
            ++n;
            json_close(pwb::mapping::task_regions(c["summary"]),
                       c["expected"], "task_regions/" + c["id"].get<std::string>());
        }
        check(n == 6, "all 6 task-region cases exercised");
    }

    // --- spatial_point_features ------------------------------------------
    {
        const auto& cases = oracle["spatial_point_cases"];
        int n = 0;
        for (const auto& c : cases) {
            ++n;
            const std::string id = c["id"].get<std::string>();
            const auto got = pwb::mapping::spatial_point_features(
                c["summary"], c["task_id"].get<std::string>());
            json_close(points_to_json(got), c["expected"],
                       "spatial_points/" + id);
        }
        check(n == 3, "all 3 spatial-point cases exercised");
    }

    // --- point_features ---------------------------------------------------
    {
        const auto& cases = oracle["point_feature_cases"];
        int n = 0;
        for (const auto& c : cases) {
            ++n;
            const std::string id = c["id"].get<std::string>();
            const auto got = pwb::mapping::point_features(
                points_from_json(c["points"]));
            json_close(features_to_json(got), c["expected"],
                       "point_features/" + id);
        }
        check(n == 3, "all 3 point-feature cases exercised");
    }

    // --- extent / clip-ring helpers ---------------------------------------
    {
        const auto& cases = oracle["extent_cases"];
        int n = 0;
        for (const auto& c : cases) {
            ++n;
            const std::string id = c["id"].get<std::string>();
            const std::string kind = c["kind"].get<std::string>();
            if (kind == "points") {
                const auto extent = pwb::mapping::extent_from_points(
                    points_from_json(c["points"]));
                json_close(Json(extent), c["expected"], "extent/" + id);
            } else {
                std::vector<pwb::mapping::Point> boundary;
                for (const auto& vertex : c["boundary"]) {
                    boundary.push_back({vertex[0].get<double>(),
                                        vertex[1].get<double>()});
                }
                if (kind == "workarea") {
                    const auto extent =
                        pwb::mapping::extent_from_workarea_boundary(boundary);
                    if (c["expected"].is_null()) {
                        check(!extent.has_value(), "extent/" + id + ": None");
                    } else {
                        check(extent.has_value(),
                              "extent/" + id + ": expected bbox");
                        if (extent.has_value()) {
                            json_close(Json(*extent), c["expected"],
                                       "extent/" + id);
                        }
                    }
                } else if (kind == "clip_ring") {
                    const auto ring =
                        pwb::mapping::clip_ring_from_boundary(boundary);
                    if (c["expected"].is_null()) {
                        check(ring.empty(), "clip_ring/" + id + ": None");
                    } else {
                        Json got = Json::array();
                        for (const auto& vertex : ring) {
                            got.push_back(
                                Json::array({vertex[0], vertex[1]}));
                        }
                        json_close(got, c["expected"], "clip_ring/" + id);
                    }
                }
            }
        }
        check(n == 6, "all 6 extent cases exercised");
    }

    // --- point_to_surface_features ----------------------------------------
    {
        const auto& cases = oracle["surface_cases"];
        int n = 0;
        for (const auto& c : cases) {
            ++n;
            const std::string id = c["id"].get<std::string>();
            const auto points = points_from_json(c["points"]);
            std::array<double, 4> extent{0.0, 0.0, 1.0, 1.0};
            if (!c["extent"].is_null()) {
                extent = {c["extent"][0].get<double>(),
                          c["extent"][1].get<double>(),
                          c["extent"][2].get<double>(),
                          c["extent"][3].get<double>()};
                // The frozen extent must be reproducible from the points via
                // the ported helper (Python derived it the same way).
                json_close(Json(pwb::mapping::extent_from_points(points)),
                           c["extent"], "surface_extent/" + id);
            }
            const std::string crs = c["crs"].is_null()
                                        ? std::string()
                                        : c["crs"].get<std::string>();
            const auto got = pwb::mapping::point_to_surface_features(
                points, extent, c["grid_n"].get<int>(), {}, crs);
            json_close(features_to_json(got), c["features"],
                       "surface/" + id);
        }
        check(n == 8, "all 8 surface cases exercised");
    }

    std::printf("%s: %d failure(s) over representative_facies oracle\n",
                g_failures == 0 ? "PASS" : "FAIL", g_failures);
    return g_failures == 0 ? 0 : 1;
}
