// CONV-27 — geological style library V1 oracle test.
#include <pwb/cartography/style_library.hpp>

#include "check.hpp"

#include <string>

using namespace pwb::cartography;
using cartography_test::check;
using cartography_test::check_json_eq;
using Json = pwb::domain::Json;

namespace {

const Json& fixture() {
    static const Json value =
        cartography_test::load_fixture(PWB_STYLE_LIBRARY_FIXTURE);
    return value;
}

void run_document() {
    check(kStyleLibrarySchemaVersion ==
              fixture()["schema_version"].get<long long>(),
          "style lib schema_version");
    std::vector<std::string> categories;
    for (const std::string& category : style_library_categories()) {
        categories.push_back(category);
    }
    check_json_eq(Json(categories), fixture()["categories"],
                  "style lib categories");
    check_json_eq(style_library_document(), fixture()["document"],
                  "style lib document");
    check(geological_style_library().size() == 12, "style lib entry count");
}

void run_lookups() {
    const Json& want = fixture()["lookups"];
    check_json_eq(style_entry_lookup("fault", "fault_major").to_dict(),
                  want["hit"], "style lib lookup hit");
    try {
        style_entry_lookup("fault", "nope");
        check(false, "style lib lookup miss (no exception)");
    } catch (const std::out_of_range& exc) {
        check(std::string(exc.what()) == want["miss"]["message"].get<std::string>(),
              "style lib lookup miss message");
    }
    try {
        style_entry_lookup("nope", "x");
        check(false, "style lib lookup miss_category (no exception)");
    } catch (const std::out_of_range& exc) {
        check(std::string(exc.what()) ==
                  want["miss_category"]["message"].get<std::string>(),
              "style lib lookup miss_category message");
    }
}

void run_apply() {
    const Json& want = fixture();
    Json payload = Json::object();
    double opacity = 1.0;
    apply_style_entry(payload, opacity,
                      style_entry_lookup("fault", "fault_major"));
    check_json_eq(payload, want["apply_plain"]["style"],
                  "style lib apply plain style");
    check(std::fabs(opacity - want["apply_plain"]["opacity"].get<double>()) <
              1e-12,
          "style lib apply plain opacity");

    payload = Json::object();
    opacity = 0.7;
    apply_style_entry(payload, opacity,
                      style_entry_lookup("reference", "reference_basemap"));
    check_json_eq(payload, want["apply_opacity_hint"]["style"],
                  "style lib apply hint style");
    check(std::fabs(opacity -
                    want["apply_opacity_hint"]["opacity"].get<double>()) <
              1e-12,
          "style lib apply hint opacity");

    payload = Json::object();
    opacity = 0.2;
    apply_style_entry(payload, opacity,
                      style_entry_lookup("reference", "reference_basemap"));
    check(std::fabs(opacity -
                    want["apply_opacity_min"]["opacity"].get<double>()) <
              1e-12,
          "style lib apply min opacity");
}

void run_load_errors() {
    const Json& want = fixture()["load_errors"]["bad_version"];
    try {
        parse_style_library_document(
            Json::parse(R"({"schema_version": 7, "styles": []})"));
        check(false, "style lib bad_version (no exception)");
    } catch (const std::invalid_argument& exc) {
        check(std::string(exc.what()) == want["message"].get<std::string>(),
              "style lib bad_version message");
    }
    // Round trip: parse(document) reproduces the 12 entries.
    const auto entries =
        parse_style_library_document(style_library_document());
    check(entries.size() == geological_style_library().size(),
          "style lib roundtrip count");
    Json reparsed = Json::array();
    for (const auto& entry : entries) reparsed.push_back(entry.second.to_dict());
    check_json_eq(reparsed, fixture()["document"]["styles"],
                  "style lib roundtrip styles");
}

}  // namespace

int main() {
    run_document();
    run_lookups();
    run_apply();
    run_load_errors();
    return cartography_test::g_failures;
}
