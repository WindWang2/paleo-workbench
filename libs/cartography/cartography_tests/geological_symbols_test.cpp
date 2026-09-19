// CONV-27 — geological symbol registry V2 oracle test.
#include <pwb/cartography/geological_symbols.hpp>

#include "check.hpp"

#include <string>

using namespace pwb::cartography;
using cartography_test::check;
using cartography_test::check_json_eq;
using Json = pwb::domain::Json;

namespace {

const Json& fixture() {
    static const Json value =
        cartography_test::load_fixture(PWB_GEOLOGICAL_SYMBOLS_FIXTURE);
    return value;
}

void run_library_document() {
    check(library_version() == fixture()["schema_version"],
          "symbols schema_version");
    check_json_eq(symbol_library_document(), fixture()["library"],
                  "symbols library document");
    check(geological_symbols().size() == 15, "symbols registry size");
}

void run_aliases() {
    const Json& want = fixture()["aliases"];
    const std::vector<std::string> inputs = {
        "facies_v1", "shoreline_v1", "facies_boundary_v1",
        "interpolation_boundary_v1", "fault_v2", "nope"};
    for (const std::string& input : inputs) {
        check(canonical_symbol_id(input) == want[input].get<std::string>(),
              "symbols alias " + input);
    }
}

void run_validate_binding() {
    const Json& want = fixture()["validate_binding"];
    auto run = [&](const std::string& key, const std::string& symbol,
                   const std::string& role, const std::string& geometry) {
        const auto got = validate_binding(symbol, role, geometry);
        const Json& expected = want[key];
        check(got.first == expected[0].get<bool>(),
              "symbols binding ok " + key);
        check(got.second == expected[1].get<std::string>(),
              "symbols binding reason " + key + ": " + got.second);
    };
    run("ok_fault", "fault_v2", "fault_constraint", "line");
    run("ok_polygon_carry", "map_extent", "interpolation_boundary", "vector");
    run("wrong_role", "fault_v2", "paleo_shoreline", "line");
    run("wrong_geometry", "fault_v2", "fault_constraint", "polygon");
    run("unknown_symbol", "ghost", "fault_constraint", "line");
    run("unknown_role", "fault_v2", "not_a_role", "line");
    run("alias_ok", "shoreline_v1", "paleo_shoreline", "line");
}

void run_binding_records() {
    const Json& want = fixture()["binding_records"];
    for (auto it = want.begin(); it != want.end(); ++it) {
        check_json_eq(binding_record(it.key()), *it,
                      "symbols binding_record " + it.key());
    }
    check_json_eq(binding_record("fault_v2",
                                 Json::parse(R"({"fault_type": ["normal", "reverse"]})")),
                  fixture()["binding_record_field_values"],
                  "symbols binding_record field_values");
}

void run_legacy_styles() {
    const Json& want = fixture()["legacy_styles"];
    check_json_eq(legacy_style_for_symbol("shoreline_v2"), want["plain"],
                  "symbols legacy plain");
    check_json_eq(
        legacy_style_for_symbol(Json::parse(R"("shoreline_v2")").get<std::string>(),
                                Json::parse(R"({"stroke": "#ff0000", "stroke_width": 3.0, "line_pattern": "dash"})")),
        want["overrides"], "symbols legacy overrides");
    try {
        legacy_style_for_symbol("shoreline_v2",
                                Json::parse(R"({"not_a_field": 1})"));
        check(false, "symbols legacy bad_override (no exception)");
    } catch (const std::invalid_argument&) {
        check(true, "symbols legacy bad_override raised");
    }
    try {
        legacy_style_for_symbol("shoreline_v2",
                                Json::parse(R"({"line_pattern": "zzz"})"));
        check(false, "symbols legacy bad_pattern (no exception)");
    } catch (const std::invalid_argument&) {
        check(true, "symbols legacy bad_pattern raised");
    }
}

void run_style_entries() {
    const Json& want = fixture()["style_entries"];
    for (auto it = want.begin(); it != want.end(); ++it) {
        check_json_eq(style_entry_for_symbol(it.key()).to_dict(), *it,
                      "symbols style_entry " + it.key());
    }
}

void run_symbols_for_role() {
    const Json& want = fixture()["symbols_for_role"];
    for (auto it = want.begin(); it != want.end(); ++it) {
        std::vector<std::string> got;
        for (const GeologicalSymbolDef* def : symbols_for_role(it.key())) {
            got.push_back(def->symbol_id);
        }
        check_json_eq(Json(got), *it, "symbols_for_role " + it.key());
    }
}

void run_errors_and_documents() {
    const Json& want = fixture()["unknown_symbol_error"];
    try {
        symbol_by_id("ghost");
        check(false, "symbols unknown (no exception)");
    } catch (const std::out_of_range& exc) {
        check(std::string(exc.what()) == want["message"].get<std::string>(),
              "symbols unknown message");
    }
    const Json& from = fixture()["library_from_dict"];
    const auto parsed = parse_symbol_library_document(
        symbol_library_document());
    check(static_cast<long long>(parsed.size()) == from["ok"],
          "symbols library roundtrip size");
    try {
        parse_symbol_library_document(
            Json::parse(R"({"schema_version": 99, "symbols": []})"));
        check(false, "symbols bad_version (no exception)");
    } catch (const std::invalid_argument& exc) {
        check(std::string(exc.what()) ==
                  from["bad_version"]["message"].get<std::string>(),
              "symbols bad_version message");
    }
    // Def-level round trip: every symbol re-parses to the same document.
    for (const auto& entry : geological_symbols()) {
        GeologicalSymbolDef def =
            GeologicalSymbolDef::from_dict(entry.second.to_dict());
        check_json_eq(def.to_dict(), entry.second.to_dict(),
                      "symbols def roundtrip " + entry.first);
    }
}

void run_v1_registration() {
    const Json& want = fixture()["v1_registration"];
    // Python registers into an explicit EMPTY copy dict; mirror that.
    std::vector<std::pair<std::string, StyleEntry>> library;
    const auto added = register_symbols_into_style_library(library);
    check_json_eq(Json(added), want["added"], "symbols v1 added");
    check(library.size() == added.size(), "symbols v1 library grew");
    const auto removed = unregister_symbols_from_style_library(library);
    check_json_eq(Json(removed), want["removed"], "symbols v1 removed");
    check(library.empty(), "symbols v1 residual empty");
    // And the 12 V1 built-ins are untouched by a fresh registration into a
    // full copy (idempotent key space check).
    std::vector<std::pair<std::string, StyleEntry>> full =
        geological_style_library();
    register_symbols_into_style_library(full);
    check(full.size() ==
              geological_style_library().size() + added.size(),
          "symbols v1 full copy grew");
    unregister_symbols_from_style_library(full);
    check(full.size() == geological_style_library().size(),
          "symbols v1 built-ins untouched");
}

}  // namespace

int main() {
    run_library_document();
    run_aliases();
    run_validate_binding();
    run_binding_records();
    run_legacy_styles();
    run_style_entries();
    run_symbols_for_role();
    run_errors_and_documents();
    run_v1_registration();
    return cartography_test::g_failures;
}
