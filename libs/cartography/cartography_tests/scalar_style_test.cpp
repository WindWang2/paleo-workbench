// CONV-27 — scalar style spec + classification oracle test.
// Verifies the numpy-exact kernels (linspace, quantile _lerp, Fisher-Jenks
// with pairwise sums, the PCG64 sample draw) against the frozen oracle.
#include <pwb/cartography/scalar_style.hpp>

#include "numpy_math.hpp"

#include "check.hpp"

#include <cmath>
#include <string>
#include <vector>

using namespace pwb::cartography;
using cartography_test::check;
using cartography_test::check_breaks;
using cartography_test::check_json_eq;
using Json = pwb::domain::Json;

namespace {

const Json& fixture() {
    static const Json value =
        cartography_test::load_fixture(PWB_SCALAR_STYLE_FIXTURE);
    return value;
}

void run_specs() {
    const Json& want = fixture()["specs"];
    ScalarStyleSpec defaults;
    check_json_eq(defaults.to_dict(), want["defaults"], "scalar spec defaults");

    ScalarStyleSpec classified;
    classified.ramp_name = "porosity";
    classified.mode = "classified";
    classified.classification = "quantile";
    classified.n_classes = 4;
    classified.reverse = true;
    classified.opacity = 0.8;
    classified.unit_label = "%";
    classified.colorbar_title = "孔隙度";
    classified.colorbar_decimals = 1;
    check_json_eq(classified.to_dict(), want["classified_quantile"],
                  "scalar spec classified_quantile");

    ScalarStyleSpec explicit_spec;
    explicit_spec.mode = "classified";
    explicit_spec.classification = "explicit";
    explicit_spec.explicit_breaks = std::vector<double>{0.0, 1.5, 3.0};
    explicit_spec.manual_range = std::make_pair(0.0, 3.0);
    check_json_eq(explicit_spec.to_dict(), want["explicit"],
                  "scalar spec explicit");

    const Json& from = fixture()["spec_from_dict"];
    ScalarStyleSpec rt;
    rt.mode = "classified";
    rt.classification = "natural_breaks";
    rt.n_classes = 6;
    rt.reverse = true;
    rt.manual_range = std::make_pair(1.0, 9.0);
    check_json_eq(
        ScalarStyleSpec::from_dict(rt.to_dict()).to_dict(), from["roundtrip"],
        "scalar spec roundtrip");
    check_json_eq(ScalarStyleSpec::from_dict(Json::object()).to_dict(),
                  from["minimal"], "scalar spec minimal");
}

void expect_invalid(const std::string& what, const Json& want,
                    void (*build)(ScalarStyleSpec&)) {
    ScalarStyleSpec spec;
    try {
        build(spec);
        check(false, what + " (no exception)");
    } catch (const std::invalid_argument& exc) {
        check(std::string(exc.what()) ==
                  want["message"].get<std::string>(),
              what + " message");
    } catch (...) {
        check(false, what + " wrong exception type");
    }
}

void run_validation() {
    const Json& want = fixture()["validation_errors"];
    expect_invalid("scalar bad_mode", want["bad_mode"],
                   [](ScalarStyleSpec& s) { s.mode = "steps"; s.validate(); });
    expect_invalid("scalar bad_classification", want["bad_classification"],
                   [](ScalarStyleSpec& s) {
                       s.classification = "jenks";
                       s.validate();
                   });
    expect_invalid("scalar n_classes_low", want["n_classes_low"],
                   [](ScalarStyleSpec& s) { s.n_classes = 1; s.validate(); });
    expect_invalid("scalar n_classes_high", want["n_classes_high"],
                   [](ScalarStyleSpec& s) { s.n_classes = 257; s.validate(); });
    expect_invalid("scalar opacity", want["opacity"],
                   [](ScalarStyleSpec& s) { s.opacity = 1.5; s.validate(); });
    expect_invalid("scalar manual_range", want["manual_range"],
                   [](ScalarStyleSpec& s) {
                       s.manual_range = std::make_pair(2.0, 1.0);
                       s.validate();
                   });
    expect_invalid("scalar explicit_missing", want["explicit_missing"],
                   [](ScalarStyleSpec& s) {
                       s.classification = "explicit";
                       s.validate();
                   });
    expect_invalid("scalar explicit_unsorted", want["explicit_unsorted"],
                   [](ScalarStyleSpec& s) {
                       s.classification = "explicit";
                       s.explicit_breaks =
                           std::vector<double>{1.0, 1.0, 0.5};
                       s.validate();
                   });
}

std::vector<double> oracle_values() {
    return {0.0, 2.5, 5.0, 7.5, 10.0, 12.5, 15.0, 17.5, 20.0,
            3.3, 6.6, 9.9, 1.1, 13.7, std::nan(""), HUGE_VAL, -4.2};
}

void run_equal_interval() {
    const Json& want = fixture()["equal_interval"];
    // basic/negative freeze as {"breaks": [...], "labels": [...]}.
    auto unpack = [](const Json& entry) {
        return Json::array({entry.at("breaks"), entry.at("labels")});
    };
    check_breaks(equal_interval_breaks(0.0, 100.0, 5, 2),
                 unpack(want["basic"]), "scalar equal_interval basic");
    check_breaks(equal_interval_breaks(-40.0, -10.0, 3, 3),
                 unpack(want["negative"]), "scalar equal_interval negative");
    check_breaks(equal_interval_breaks(5.0, 7.0, 2, 2), want["n2"],
                 "scalar equal_interval n2");
    check_breaks(equal_interval_breaks(std::nan(""), 1.0, 2, 2),
                 want["nan_span"], "scalar equal_interval nan_span");
}

void run_quantile() {
    const Json& want = fixture()["quantile"];
    const std::vector<double> values = oracle_values();
    check_breaks(quantile_breaks(values, 4, 2), want["basic"],
                 "scalar quantile basic");
    check_breaks(quantile_breaks(std::vector<double>{2.0, 2.0, 2.0, 2.0}, 3, 2),
                 want["flat"], "scalar quantile flat");
    check_breaks(quantile_breaks(std::vector<double>{1.0, 2.0}, 5, 2),
                 want["two_values"], "scalar quantile two_values");
    check_breaks(quantile_breaks(values, 3, 2), want["with_nan"],
                 "scalar quantile with_nan");
    try {
        quantile_breaks(std::vector<double>{}, 3, 2);
        check(false, "scalar quantile empty (no exception)");
    } catch (const std::invalid_argument& exc) {
        check(std::string(exc.what()) == want["empty"]["message"].get<std::string>(),
              "scalar quantile empty message");
    }
}

void run_natural_breaks() {
    const Json& want = fixture()["natural_breaks"];
    const std::vector<double> values = oracle_values();
    check_breaks(natural_breaks(values, 3, 1000, 0, 2), want["small_data"],
                 "scalar natural_breaks small");
    check_breaks(
        natural_breaks(std::vector<double>{1.0, 5.0, 9.0}, 5, 1000, 0, 2),
        want["n_ge_size"], "scalar natural_breaks n_ge_size");
    std::vector<double> sampled_input;
    sampled_input.reserve(1500);
    for (int i = 0; i < 1500; ++i) {
        sampled_input.push_back(static_cast<double>(i % 97) +
                                std::fmod(i * 0.37, 3.1));
    }
    check_breaks(natural_breaks(sampled_input, 4, 200, 0, 2), want["sampled"],
                 "scalar natural_breaks sampled");
    std::vector<double> seeded_input;
    seeded_input.reserve(1200);
    for (int i = 0; i < 1200; ++i) {
        seeded_input.push_back(static_cast<double>((i * 7919) % 2003));
    }
    check_breaks(natural_breaks(seeded_input, 4, 1000, 0, 2),
                 want["sampled_default_seed"],
                 "scalar natural_breaks sampled_default_seed");
    try {
        natural_breaks(std::vector<double>{}, 3, 1000, 0, 2);
        check(false, "scalar natural_breaks empty (no exception)");
    } catch (const std::invalid_argument& exc) {
        check(std::string(exc.what()) == want["empty"]["message"].get<std::string>(),
              "scalar natural_breaks empty message");
    }
}

void run_frozen_samples() {
    // D-3: the C++ PCG64 + Floyd draw must reproduce numpy's sampled arrays
    // draw-for-draw (same selection AND same order).
    const Json& want = fixture()["frozen_samples"];
    struct Case {
        std::string name;
        std::vector<double> population;
        std::size_t size;
    };
    std::vector<double> pop_a;
    pop_a.reserve(1500);
    for (int i = 0; i < 1500; ++i) {
        pop_a.push_back(static_cast<double>(i % 97) +
                        std::fmod(i * 0.37, 3.1));
    }
    std::vector<double> pop_b;
    pop_b.reserve(1200);
    for (int i = 0; i < 1200; ++i) {
        pop_b.push_back(static_cast<double>((i * 7919) % 2003));
    }
    const std::vector<Case> cases = {
        {"a", pop_a, 200}, {"b", pop_b, 1000}};
    for (const Case& item : cases) {
        numpy_math::Pcg64 rng = numpy_math::Pcg64::seeded(0);
        std::vector<std::size_t> indices =
            numpy_math::choice_indices_without_replacement(
                rng, item.population.size(), item.size);
        std::vector<double> got;
        got.reserve(indices.size());
        for (std::size_t index : indices) {
            got.push_back(item.population[index]);
        }
        check_json_eq(Json(got), want[item.name]["values"],
                      "scalar frozen_sample " + item.name);
    }
}

void run_classify_breaks() {
    const Json& want = fixture()["classify_breaks"];
    const std::vector<double> values = oracle_values();
    ScalarStyleSpec spec;
    check_breaks(classify_breaks(spec, values, 0.0, 20.0, std::nullopt),
                 want["equal"], "scalar classify equal");
    ScalarStyleSpec manual;
    manual.manual_range = std::make_pair(-10.0, 10.0);
    check_breaks(classify_breaks(manual, values, 0.0, 20.0, std::nullopt),
                 want["manual_override"], "scalar classify manual");
    ScalarStyleSpec explicit_spec;
    explicit_spec.classification = "explicit";
    explicit_spec.explicit_breaks = std::vector<double>{0.0, 4.0, 8.0};
    check_breaks(classify_breaks(explicit_spec, values, 0.0, 20.0,
                                 std::nullopt),
                 want["explicit"], "scalar classify explicit");
}

void run_ramp_items() {
    const Json& want = fixture()["ramp_items"];
    const ColorRamp& ramp = get_color_ramp("porosity");
    ScalarStyleSpec spec;
    auto items = ramp_items_for_spec(spec, ramp, 0.0, 100.0, "continuous");
    check_json_eq(Json(items), want["continuous"], "scalar items continuous");

    ScalarStyleSpec reverse;
    reverse.reverse = true;
    items = ramp_items_for_spec(reverse, ramp, 0.0, 100.0, "continuous");
    check_json_eq(Json(items), want["continuous_reverse"],
                  "scalar items continuous_reverse");

    const auto breaks = equal_interval_breaks(0.0, 100.0, 4, 2);
    items = ramp_items_for_spec(spec, ramp, 0.0, 100.0, "classified",
                                breaks.breaks);
    check_json_eq(Json(items), want["classified"], "scalar items classified");

    items = ramp_items_for_spec(reverse, ramp, 0.0, 100.0, "classified",
                                breaks.breaks);
    check_json_eq(Json(items), want["classified_reverse"],
                  "scalar items classified_reverse");

    try {
        ramp_items_for_spec(spec, ramp, 5.0, 5.0, "continuous");
        check(false, "scalar items degenerate (no exception)");
    } catch (const std::invalid_argument& exc) {
        check(std::string(exc.what()) ==
                  want["degenerate_span"]["message"].get<std::string>(),
              "scalar items degenerate message");
    }
    try {
        ramp_items_for_spec(spec, ramp, 0.0, 100.0, "classified",
                            std::vector<double>{1.0});
        check(false, "scalar items missing_breaks (no exception)");
    } catch (const std::invalid_argument& exc) {
        check(std::string(exc.what()) == want["missing_breaks"]["message"].get<std::string>(),
              "scalar items missing_breaks message");
    }
}

}  // namespace

int main() {
    run_specs();
    run_validation();
    run_equal_interval();
    run_quantile();
    run_natural_breaks();
    run_frozen_samples();
    run_classify_breaks();
    run_ramp_items();
    return cartography_test::g_failures;
}
