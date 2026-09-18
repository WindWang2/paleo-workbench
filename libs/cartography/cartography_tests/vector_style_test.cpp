// CONV-27 — vector/label style value type oracle test.
#include <pwb/cartography/vector_style.hpp>

#include "check.hpp"

#include <cmath>
#include <string>

using namespace pwb::cartography;
using cartography_test::check;
using cartography_test::check_json_eq;
using Json = pwb::domain::Json;

namespace {

const Json& fixture() {
    static const Json value = cartography_test::load_fixture(PWB_MAP_STYLES_FIXTURE);
    return value;
}

void run_presets() {
    const Json& want = fixture()["presets"];
    const auto& library = style_library();
    check(library.size() == want.size(), "map_styles preset count");
    for (const auto& entry : library) {
        auto it = want.find(entry.first);
        check(it != want.end(), "map_styles preset present " + entry.first);
        if (it != want.end()) {
            check_json_eq(entry.second.to_dict(), *it,
                          "map_styles preset " + entry.first);
        }
    }
}

void run_default_style_for() {
    const Json& want = fixture()["default_style_for"];
    for (auto it = want.begin(); it != want.end(); ++it) {
        check_json_eq(default_style_for(it.key()).to_dict(), *it,
                      "map_styles default_style_for " + it.key());
    }
}

void run_dash_pattern() {
    const Json& want = fixture()["dash_pattern"];
    for (const auto& pattern : {LinePattern::Solid, LinePattern::Dash,
                                LinePattern::Dot, LinePattern::DashDot,
                                LinePattern::Fault, LinePattern::Boundary}) {
        const std::string name = line_pattern_value(pattern);
        auto it = want.find(name);
        check(it != want.end(), "map_styles dash present " + name);
        if (it == want.end()) continue;
        const std::vector<double> got = dash_pattern(pattern);
        const std::vector<double> expected = it->get<std::vector<double>>();
        check(got.size() == expected.size(),
              "map_styles dash size " + name);
        for (std::size_t i = 0; i < got.size(); ++i) {
            check(std::fabs(got[i] - expected[i]) < 1e-12,
                  "map_styles dash value " + name);
        }
    }
}

void run_from_dict() {
    const Json& want = fixture()["vector_style_from_dict"];
    check_json_eq(VectorStyle::from_dict(Json::parse(R"({
        "fill": "#101010",
        "stroke": "#eeeeee",
        "stroke_width": "2.5",
        "line_pattern": "fault",
        "marker": "square",
        "marker_size": 9,
        "renderer": "categorized",
        "field": "facies_name",
        "categories": [["sand", "#f2d38a", "砂岩"], ["mud", "#9aa7b5"]],
        "ranges": [[0, 0.5, "#c9b8d8", "低"],
                   {"min": 0.5, "max": 1.0, "color": "#7fbf9e", "label": "高"},
                   ["bad", "range", "#ffffff"]],
        "fill_patterns": {"sand": "sandstone", "mud": "mudstone"},
        "labels": {"field": "name", "size": "11", "bold": true},
        "unknown_key": {"kept": false}
    })")).to_dict(),
        want["flat"], "map_styles.from_dict flat");
    check_json_eq(VectorStyle::from_dict(Json::parse(
                      R"({"categories": {"sand": "#f2d38a", "mud": "#9aa7b5"}})"))
                      .to_dict(),
                  want["qgis_map_categories"],
                  "map_styles.from_dict qgis_map_categories");
    check_json_eq(VectorStyle::from_dict(Json::parse(
                      R"({"stroke_width": "abc", "marker_size": null, "fill": ""})"))
                      .to_dict(),
                  want["invalid_numbers"], "map_styles.from_dict invalid");
    check_json_eq(VectorStyle::from_dict(Json::parse(
                      R"({"line_pattern": "dotted", "marker": "hexagon"})"))
                      .to_dict(),
                  want["unknown_patterns"], "map_styles.from_dict unknown");
    check_json_eq(VectorStyle::from_dict(Json()).to_dict(), want["not_mapping"],
                  "map_styles.from_dict null");
    check_json_eq(VectorStyle::from_dict(Json::object()).to_dict(),
                  want["empty"], "map_styles.from_dict empty");
    check_json_eq(VectorStyle::from_dict(Json::parse(
                      R"({"labels": {"color": null, "size": "bad", "halo_width": 2}})"))
                      .to_dict(),
                  want["labels_partial"], "map_styles.from_dict labels_partial");
}

void run_text_style() {
    const Json& want = fixture()["text_style_from_dict"];
    const Json input = Json::parse(R"({
        "field": "well_name", "size": 12, "color": "#000000",
        "bold": 1, "visible": true, "rotation_field": "deg"
    })");
    check_json_eq(TextStyle::from_dict(input).to_dict(), want,
                  "map_styles text_style_from_dict");
    check_json_eq(TextStyle{}.to_dict(), fixture()["text_style_default"],
                  "map_styles text_style_default");
}

void run_revision_stability() {
    // D-6: the C++ token is a stable FNV-1a-64, not Python's salted hash —
    // only stability and content sensitivity are asserted here.
    const Json style_a = Json::parse(R"({"fill": "#101010", "categories":
        [["a", "#111111", ""]], "labels": {"field": "n", "size": 9.0}})");
    const Json style_a_reordered = Json::parse(R"({"categories":
        [["a", "#111111", ""]], "labels": {"size": 9.0, "field": "n"},
        "fill": "#101010"})");
    const Json style_b = Json::parse(R"({"fill": "#202020", "categories":
        [["a", "#111111", ""]], "labels": {"field": "n", "size": 9.0}})");
    check(style_dict_revision(style_a) ==
              style_dict_revision(style_a_reordered),
          "map_styles revision key-order insensitive");
    check(style_dict_revision(style_a) != style_dict_revision(style_b),
          "map_styles revision content sensitive");
    check(style_dict_revision(Json::object()) ==
              style_dict_revision(Json::object()),
          "map_styles revision empty stable");
}

}  // namespace

int main() {
    run_presets();
    run_default_style_for();
    run_dash_pattern();
    run_from_dict();
    run_text_style();
    run_revision_stability();
    return cartography_test::g_failures;
}
