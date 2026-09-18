// CONV-27 — color ramp registry oracle test.
#include <pwb/cartography/color_ramps.hpp>

#include "check.hpp"

#include <cmath>
#include <string>
#include <vector>

using namespace pwb::cartography;
using cartography_test::check;
using cartography_test::check_json_eq;
using Json = pwb::domain::Json;

namespace {

const Json& fixture() {
    static const Json value = cartography_test::load_fixture(PWB_COLOR_RAMPS_FIXTURE);
    return value;
}

void run_builtin_documents() {
    const Json& want = fixture()["builtin_documents"];
    check_json_eq(Json(list_color_ramps()), Json(fixture()["list_ramps"]),
                  "color_ramps.list order");
    for (auto it = want.begin(); it != want.end(); ++it) {
        check_json_eq(get_color_ramp(it.key()).to_dict(), *it,
                      "color_ramps.document " + it.key());
    }
}

void run_evaluate_grid() {
    const Json& grid = fixture()["evaluate_grid"];
    // Non-finite sample points freeze as strings (standard JSON has no
    // NaN/Infinity tokens).
    std::vector<double> ts;
    for (const Json& t : grid["ts"]) {
        if (t.is_string()) {
            const std::string tag = t.get<std::string>();
            ts.push_back(tag == "NaN"     ? std::nan("")
                         : tag == "Infinity" ? HUGE_VAL
                                             : -HUGE_VAL);
        } else {
            ts.push_back(t.get<double>());
        }
    }
    const Json& values = grid["values"];
    for (auto it = values.begin(); it != values.end(); ++it) {
        const ColorRamp& ramp = get_color_ramp(it.key());
        const std::vector<std::string> want =
            it->get<std::vector<std::string>>();
        for (std::size_t i = 0; i < ts.size(); ++i) {
            const std::string got = ramp.evaluate(ts[i]);
            check(got == want[i],
                  "color_ramps.evaluate " + it.key() + " t=" +
                      std::to_string(i));
        }
    }
}

void run_evaluate_value() {
    const Json& want = fixture()["evaluate_value"];
    const ColorRamp& ramp = get_color_ramp("viridis");
    check(ramp.evaluate_value(0.25, 0.0, 100.0) ==
              want["normal"].get<std::string>(),
          "color_ramps.evaluate_value normal");
    check(ramp.evaluate_value(75.0, 0.0, 100.0) ==
              want["normal_2"].get<std::string>(),
          "color_ramps.evaluate_value normal_2");
    check(ramp.evaluate_value(5.0, 5.0, 5.0) ==
              want["degenerate"].get<std::string>(),
          "color_ramps.evaluate_value degenerate");
    check(ramp.evaluate_value(5.0, 5.0, 5.0000000001) ==
              want["degenerate_close"].get<std::string>(),
          "color_ramps.evaluate_value degenerate_close");
    check(ramp.evaluate_value(std::nan(""), 0.0, 1.0) ==
              want["nan_value"].get<std::string>(),
          "color_ramps.evaluate_value nan");
    check(ramp.evaluate_value(0.5, -HUGE_VAL, HUGE_VAL) ==
              want["inf_bounds"].get<std::string>(),
          "color_ramps.evaluate_value inf_bounds");
    check(ramp.evaluate_value(-10.0, 0.0, 1.0) ==
              want["below"].get<std::string>(),
          "color_ramps.evaluate_value below");
    check(ramp.evaluate_value(2.0, 0.0, 1.0) ==
              want["above"].get<std::string>(),
          "color_ramps.evaluate_value above");
}

void run_sample_tables() {
    const Json& tables = fixture()["sample_tables"];
    for (auto it = tables.begin(); it != tables.end(); ++it) {
        for (auto entry = it->begin(); entry != it->end(); ++entry) {
            const int count = std::stoi(entry.key());
            const std::vector<std::vector<long long>> want =
                entry->get<std::vector<std::vector<long long>>>();
            const auto got =
                get_color_ramp(it.key()).sample_table(count);
            check(got.size() == want.size(),
                  "color_ramps.table size " + it.key() + "/" + entry.key());
            for (std::size_t i = 0; i < got.size() && i < want.size(); ++i) {
                check(got[i][0] == want[i][0] && got[i][1] == want[i][1] &&
                          got[i][2] == want[i][2] && got[i][3] == want[i][3],
                      "color_ramps.table row " + it.key() + "/" + entry.key() +
                          "/" + std::to_string(i));
            }
        }
    }
}

void run_from_dict() {
    const Json& want = fixture()["from_dict"];
    check_json_eq(
        ColorRamp::from_dict(Json::parse(R"({
            "name": "Custom",
            "stops": [{"position": 0, "color": "#ff0000"},
                      {"position": 1, "color": "#00ff00"}],
            "nodata_color": "#11223344"
        })")).to_dict(),
        want["valid"], "color_ramps.from_dict valid");
    check_json_eq(ColorRamp::from_dict(Json::parse(R"({"name": "flat"})")).to_dict(),
                  want["empty_stops"], "color_ramps.from_dict empty_stops");
    check_json_eq(ColorRamp::from_dict(Json()).to_dict(), want["none"],
                  "color_ramps.from_dict none");
    check_json_eq(ColorRamp::from_dict(Json(42)).to_dict(), want["scalar"],
                  "color_ramps.from_dict scalar");
    check_json_eq(
        ColorRamp::from_dict(Json::parse(R"({"name": "x", "stops": [{"position": 0.5}]})"))
            .to_dict(),
        want["missing_color"], "color_ramps.from_dict missing_color");
    check_json_eq(
        ColorRamp::from_dict(Json::parse(R"({"name": "", "stops": []})")).to_dict(),
        want["falsy_name"], "color_ramps.from_dict falsy_name");
    check_json_eq(get_color_ramp("NOPE").to_dict(), want["unknown_lookup"],
                  "color_ramps.unknown lookup");
    check_json_eq(get_color_ramp("VIRIDIS").to_dict(), want["uppercase_lookup"],
                  "color_ramps.uppercase lookup");
}

void run_hex_parse() {
    // _hex_to_rgb frozen DIRECTLY per input (Python int(x,16) semantics:
    // multi-'#', optional signs, whitespace strip, gray fallback).
    const Json& want_entries = fixture()["hex_parse"];
    for (std::size_t i = 0; i < want_entries.size(); ++i) {
        const auto got =
            hex_to_rgba(want_entries[i]["input"].get<std::string>());
        const auto want = want_entries[i]["rgba"];
        check(got[0] == want[0].get<int>() && got[1] == want[1].get<int>() &&
                  got[2] == want[2].get<int>() && got[3] == want[3].get<int>(),
              "color_ramps.hex [" + std::to_string(i) + "] " +
                  want_entries[i]["input"].get<std::string>());
    }
}

void run_register() {
    const Json& want = fixture()["register"];
    ColorRamp custom;
    custom.name = "CustomRamp";
    custom.stops = {ColorStop{0.0, "#000000"}, ColorStop{1.0, "#ffffff"}};
    register_color_ramp(custom);
    check_json_eq(Json(list_color_ramps()), want["list_after"],
                  "color_ramps.register list_after");
    check_json_eq(get_color_ramp("customramp").to_dict(),
                  want["lookup_by_lower"], "color_ramps.register lower");
}

}  // namespace

int main() {
    run_builtin_documents();
    run_evaluate_grid();
    run_evaluate_value();
    run_sample_tables();
    run_from_dict();
    run_hex_parse();
    run_register();
    return cartography_test::g_failures;
}
