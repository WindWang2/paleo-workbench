// CONV-27 — oracle negative self-check + product API facade test.
//
// The negative half guards against a silently vacuous oracle: every frozen
// fixture is perturbed on one leaf and json_semantic_diff must report the
// difference (if fixture and code ever drift in lockstep, or the diff
// harness short-circuits to equality, this test fails).
// The positive half exercises the product API surface (D-8): validate_style,
// apply_style, and the preset/template catalogs.
#include <pwb/cartography/cartography.hpp>
#include <pwb/domain/json.hpp>

#include "check.hpp"

#include <cmath>
#include <string>

using namespace pwb::cartography;
using cartography_test::check;
using cartography_test::check_json_eq;
using Json = pwb::domain::Json;

namespace {

#ifndef PWB_CARTOGRAPHY_FIXTURE_DIR
#error "PWB_CARTOGRAPHY_FIXTURE_DIR must point at the frozen fixtures"
#endif

Json load_fixture(const std::string& name) {
    return cartography_test::load_fixture(
        (std::string(PWB_CARTOGRAPHY_FIXTURE_DIR) + "/" + name).c_str());
}

// Perturb the first scalar leaf found (depth-first) and return the mutated
// copy plus a description of the mutation.
Json perturb(const Json& value) {
    Json mutated = value;
    if (mutated.is_object()) {
        for (auto it = mutated.begin(); it != mutated.end(); ++it) {
            if (it->is_number_integer()) {
                mutated[it.key()] = it->get<long long>() + 1;
                return mutated;
            }
            if (it->is_number_float()) {
                mutated[it.key()] = it->get<double>() + 1.5;
                return mutated;
            }
            if (it->is_string() && it.key() != "error") {
                mutated[it.key()] = it->get<std::string>() + "#perturbed";
                return mutated;
            }
            if ((it->is_object() || it->is_array()) && !it->empty()) {
                Json inner = perturb(*it);
                if (inner != *it) {
                    mutated[it.key()] = inner;
                    return mutated;
                }
            }
        }
    } else if (mutated.is_array()) {
        for (std::size_t i = 0; i < mutated.size(); ++i) {
            Json inner = perturb(mutated[i]);
            if (inner != mutated[i]) {
                mutated[i] = inner;
                return mutated;
            }
            if (mutated[i].is_number_integer()) {
                mutated[i] = mutated[i].get<long long>() + 1;
                return mutated;
            }
            if (mutated[i].is_number_float()) {
                mutated[i] = mutated[i].get<double>() + 1.5;
                return mutated;
            }
            if (mutated[i].is_string()) {
                mutated[i] = mutated[i].get<std::string>() + "#perturbed";
                return mutated;
            }
        }
    }
    return mutated;
}

void run_negative() {
    const std::vector<std::string> fixtures = {
        "color_ramps_oracle.json", "map_styles_oracle.json",
        "scalar_style_oracle.json", "geological_symbols_oracle.json",
        "style_library_oracle.json", "templates_oracle.json",
        "qgis_style_oracle.json", "flatten_qgis_oracle.json"};
    for (const std::string& name : fixtures) {
        const Json original = load_fixture(name);
        const Json mutated = perturb(original);
        check(mutated != original, "negative " + name + " actually mutated");
        const pwb::domain::JsonDiff diff = pwb::domain::json_semantic_diff(
            Json::parse(original.dump()), Json::parse(mutated.dump()));
        check(!diff.equal, "negative " + name + " diff fires");
        // And the identity diff stays quiet.
        const pwb::domain::JsonDiff identity =
            pwb::domain::json_semantic_diff(Json::parse(original.dump()),
                                            Json::parse(original.dump()));
        check(identity.equal, "negative " + name + " identity quiet");
    }
}

void run_facade() {
    // validate_style: ok path, renderer typo, non-object payload.
    const Json preset = Json(style_library().front().second.to_dict());
    Json report = validate_style(preset);
    check(report["ok"] == true, "facade validate_style ok");
    check(report["normalized"] == preset, "facade validate_style normalized");
    report = validate_style(Json::parse(R"({"renderer": "steps"})"));
    check(report["ok"] == false, "facade validate_style renderer typo");
    report = validate_style(Json("not-an-object"));
    check(report["ok"] == false, "facade validate_style non-object");

    // apply_style (preset): style payload replaced, opacity folded.
    Json payload = Json::object();
    double opacity = 1.0;
    apply_style(payload, opacity, "preset", "contour");
    check(payload["stroke"] == "#f08c46", "facade apply preset contour");
    try {
        Json scratch = Json::object();
        double scratch_opacity = 1.0;
        apply_style(scratch, scratch_opacity, "preset", "does_not_exist");
        check(false, "facade apply preset unknown (no exception)");
    } catch (const std::out_of_range&) {
        check(true, "facade apply preset unknown raised");
    }

    // apply_style (library): the V1 opacity hint folds in.
    payload = Json::object();
    opacity = 1.0;
    apply_style(payload, opacity, "library", "reference.reference_basemap");
    check(std::fabs(opacity - 0.4) < 1e-12, "facade apply library opacity");
    check(payload.contains("style_binding"), "facade apply library binding");

    // Catalogs.
    check(style_preset_catalog().size() == 8, "facade preset catalog size");
    check(template_catalog().size() == 5, "facade template catalog size");
    check(list_color_ramps_api().size() >= 11, "facade ramp list size");
}

}  // namespace

int main() {
    run_negative();
    run_facade();
    return cartography_test::g_failures;
}
