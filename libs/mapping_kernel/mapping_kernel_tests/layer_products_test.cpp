// mapping_kernel.layer_products — CONV-03 feature packing vs the frozen
// Python oracle (layer_products_oracle.json, generated from the REAL
// generate_contour_layer / generate_facies_polygon_layer by
// tools/oracle/generate_layer_product_fixtures.py). Shapely repair is
// identity-patched in the freeze; clip-to-ring is out of scope (Python hard-
// requires shapely); styles/ids are UI data and not frozen.

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/layer_products.hpp>

using pwb::domain::Json;
using pwb::mapping::ContourLayerOptions;
using pwb::mapping::ContourLayerProduct;
using pwb::mapping::FaciesLayerOptions;
using pwb::mapping::FactorGrid;
using pwb::mapping::LayerGridContext;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

FactorGrid factor_from_json(const Json& g) {
    FactorGrid grid;
    for (const auto& x : g["x"]) grid.grid_x.push_back(x.get<double>());
    for (const auto& y : g["y"]) grid.grid_y.push_back(y.get<double>());
    grid.grid_z.reserve(grid.grid_x.size() * grid.grid_y.size());
    for (const auto& row : g["z"]) {
        for (const auto& v : row) {
            grid.grid_z.push_back(v.is_null()
                                      ? std::numeric_limits<float>::quiet_NaN()
                                      : static_cast<float>(v.get<double>()));
        }
    }
    return grid;
}

LayerGridContext context_from_json(const Json& c) {
    LayerGridContext ctx;
    ctx.factor_name = c["factor"].get<std::string>();
    ctx.unit = c["unit"].get<std::string>();
    ctx.crs = c["crs"].get<std::string>();
    return ctx;
}

ContourLayerOptions contour_options_from_json(const Json& params) {
    ContourLayerOptions options;
    if (!params["levels_in"].is_null()) {
        std::vector<double> levels;
        for (const auto& v : params["levels_in"]) {
            levels.push_back(v.get<double>());
        }
        options.levels = levels;
    }
    if (!params["interval"].is_null()) {
        options.interval = params["interval"].get<double>();
    }
    options.leveling_mode = params["leveling_mode"].get<std::string>();
    options.simplify_tolerance =
        params["simplify_tolerance"].get<double>();
    options.smooth_iterations = params["smooth_iterations"].get<int>();
    return options;
}

FaciesLayerOptions facies_options_from_json(const Json& params) {
    FaciesLayerOptions options;
    if (!params["thresholds_in"].is_null()) {
        std::vector<double> thresholds;
        for (const auto& v : params["thresholds_in"]) {
            thresholds.push_back(v.get<double>());
        }
        options.thresholds = thresholds;
    }
    if (!params["names_in"].is_null()) {
        std::vector<std::string> names;
        for (const auto& v : params["names_in"]) {
            names.push_back(v.get<std::string>());
        }
        options.facies_names = names;
    }
    if (!params["colors_in"].is_null()) {
        std::vector<std::string> colors;
        for (const auto& v : params["colors_in"]) {
            colors.push_back(v.get<std::string>());
        }
        options.colors = colors;
    }
    if (!params["min_area"].is_null()) {
        options.min_area = params["min_area"].get<double>();
    }
    return options;
}

// The fixture is the wire-format authority: Python-json non-negative ints
// parse as number_unsigned while freshly built C++ Json ints are
// number_integer (same dump text). Re-parse both sides once so the domain
// comparator sees identical in-memory shapes, then diff.
Json canonical(const Json& value) {
    return Json::parse(value.dump());
}

void diff(const Json& got_raw, const Json& want_raw, const std::string& what) {
    const Json got = canonical(got_raw);
    const Json want = canonical(want_raw);
    const auto d = pwb::domain::json_semantic_diff(got, want);
    if (!d.equal) {
        check(false, what + " at " + d.path + ": " + d.reason);
    }
}

void run_contour_case(const Json& c, const Json& grids) {
    const std::string id = c["id"].get<std::string>();
    const FactorGrid grid = factor_from_json(grids[c["grid"].get<std::string>()]);
    const auto ctx = context_from_json(c);
    const auto options = contour_options_from_json(c["params"]);
    const ContourLayerProduct got =
        pwb::mapping::generate_contour_layer_product(grid, ctx, options);

    Json levels = Json::array();
    for (const double v : got.levels) levels.push_back(v);
    diff(levels, c["levels"], id + " levels");
    Json interval = got.contour_interval.has_value()
                        ? Json(*got.contour_interval)
                        : Json();
    diff(interval, c["contour_interval"], id + " contour_interval");
    diff(got.contour_qc, c["contour_qc"], id + " contour_qc");

    check(got.features.size() == c["features"].size(),
          id + " feature count " + std::to_string(got.features.size())
              + " vs " + std::to_string(c["features"].size()));
    const std::size_t n =
        std::min(got.features.size(), c["features"].size());
    for (std::size_t i = 0; i < n; ++i) {
        diff(got.features[i], c["features"][i],
             id + " feature[" + std::to_string(i) + "]");
    }
}

void run_facies_case(const Json& c, const Json& grids) {
    const std::string id = c["id"].get<std::string>();
    const FactorGrid grid = factor_from_json(grids[c["grid"].get<std::string>()]);
    const auto ctx = context_from_json(c);
    const auto options = facies_options_from_json(c["params"]);
    const auto got = pwb::mapping::generate_facies_polygon_layer_product(
        grid, ctx, options);

    diff(got.polygon_qc, c["polygon_qc"], id + " polygon_qc");
    check(got.features.size() == c["features"].size(),
          id + " feature count " + std::to_string(got.features.size())
              + " vs " + std::to_string(c["features"].size()));
    const std::size_t n =
        std::min(got.features.size(), c["features"].size());
    for (std::size_t i = 0; i < n; ++i) {
        diff(got.features[i], c["features"][i],
             id + " feature[" + std::to_string(i) + "]");
    }
}

void run_mean_units(const Json& units) {
    // numpy float32 mask-mean kernel: pairwise float32 sum, float32 divide.
    for (const auto& u : units) {
        std::vector<float> values;
        for (const auto& v : u["values"]) {
            values.push_back(static_cast<float>(v.get<double>()));
        }
        const double mean =
            pwb::mapping::float32_mask_mean(values);
        check(u["mean"].get<double>() == mean,
              "mean_units n=" + std::to_string(u["n"].get<int>())
                  + " mean " + std::to_string(mean));
    }
}

}  // namespace

int main() {
    std::ifstream stream(PWB_LAYER_PRODUCTS_FIXTURE, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open fixture\n");
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const Json oracle = Json::parse(buffer.str());
    const Json& grids = oracle["grids"];

    int n_contour = 0;
    int n_facies = 0;
    for (const auto& c : oracle["cases"]) {
        if (c["kind"].get<std::string>() == "contour") {
            ++n_contour;
            run_contour_case(c, grids);
        } else {
            ++n_facies;
            run_facies_case(c, grids);
        }
    }
    run_mean_units(oracle["mean_units"]);

    check(n_contour == 29, "29 contour cases");
    check(n_facies == 30, "30 facies cases");

    // Empty colors would be a ZeroDivisionError in Python — fail closed.
    bool threw = false;
    try {
        FactorGrid grid = factor_from_json(grids["ramp8"]);
        pwb::mapping::FaciesLayerOptions options;
        options.colors = std::vector<std::string>{};
        (void)pwb::mapping::generate_facies_polygon_layer_product(
            grid, LayerGridContext{}, options);
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    check(threw, "empty colors rejected");

    std::printf("%s: %d failure(s) over %d contour + %d facies cases\n",
                g_failures == 0 ? "PASS" : "FAIL", g_failures, n_contour,
                n_facies);
    return g_failures == 0 ? 0 : 1;
}
