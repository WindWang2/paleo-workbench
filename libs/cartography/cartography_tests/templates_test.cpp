// CONV-27 — template library test.
//
// The factor-map cases diff against the Python oracle (templates_oracle.json,
// generated from templates.create_geological_factor_map_template). The
// facies/prediction/constraint/comprehensive factories have no Python
// counterpart (D-4); they assert structural invariants and a stable
// parse(dump(x)) round-trip instead.
#include <pwb/cartography/templates.hpp>

#include "check.hpp"

#include <cmath>
#include <string>

using namespace pwb::cartography;
using cartography_test::check;
using cartography_test::check_json_eq;
using Json = pwb::domain::Json;

namespace {

const Json& fixture() {
    static const Json value =
        cartography_test::load_fixture(PWB_TEMPLATES_FIXTURE);
    return value;
}

TemplateMapInput map_alpha() {
    TemplateMapInput map;
    map.map_document_id = "map_alpha";
    map.map_document_title = "Prior Title";
    map.map_layer_count = 0;
    map.extent = {110.0, 35.0, 125.0, 45.0};
    return map;
}

void run_factor_parity() {
    const Json& want = fixture();
    TemplateRequest request;
    request.template_name = "factor_map";
    request.map = map_alpha();
    request.factor_name = "porosity";
    request.unit = "%";
    check_json_eq(
        pwb::mapping_document::dump_composition(
            geological_factor_map_template(request)),
        want["factor_default"], "templates factor_default");

    TemplateRequest titled = request;
    titled.title = "Custom Title";
    titled.factor_name = "permeability";
    titled.unit = "mD";
    check_json_eq(
        pwb::mapping_document::dump_composition(
            geological_factor_map_template(titled)),
        want["factor_titled"], "templates factor_titled");

    TemplateMapInput no_title = map_alpha();
    no_title.map_document_id = "map_beta";
    // MapDocument() keeps the dataclass default title "Paleogeographic
    // Map", so the factory uses it instead of the factor-name fallback.
    no_title.map_document_title = "Paleogeographic Map";
    no_title.extent = {0.0, 0.0, 1.0, 1.0};
    TemplateRequest portrait;
    portrait.template_name = "factor_map";
    portrait.map = no_title;
    portrait.factor_name = "thickness";
    portrait.orientation = "portrait";
    check_json_eq(
        pwb::mapping_document::dump_composition(
            geological_factor_map_template(portrait)),
        want["factor_portrait"], "templates factor_portrait");

    TemplateMapInput zero = no_title;
    zero.map_document_id = "map_zero";
    zero.extent = {7.0, 0.0, 7.0, 4.0};
    TemplateRequest degenerate;
    degenerate.template_name = "factor_map";
    degenerate.map = zero;
    degenerate.factor_name = "span0";
    check_json_eq(
        pwb::mapping_document::dump_composition(
            geological_factor_map_template(degenerate)),
        want["factor_degenerate_extent"], "templates factor_degenerate_extent");

    TemplateMapInput tiny_map = no_title;
    tiny_map.map_document_id = "map_tiny";
    tiny_map.extent = {0.0, 0.0, 5.0, 5.0};
    TemplateRequest tiny;
    tiny.template_name = "factor_map";
    tiny.map = tiny_map;
    tiny.factor_name = "tiny";
    check_json_eq(
        pwb::mapping_document::dump_composition(
            geological_factor_map_template(tiny)),
        want["factor_tiny_extent"], "templates factor_tiny_extent");

    TemplateMapInput huge_map = no_title;
    huge_map.map_document_id = "map_huge";
    huge_map.extent = {-1000.0, -500.0, 2500.0, 750.0};
    TemplateRequest huge;
    huge.template_name = "factor_map";
    huge.map = huge_map;
    huge.factor_name = "huge";
    check_json_eq(
        pwb::mapping_document::dump_composition(
            geological_factor_map_template(huge)),
        want["factor_huge_extent"], "templates factor_huge_extent");
}

// D-4: invariants shared by the C++-authored compositions.
void check_extension_composition(const Composition& doc,
                                 const std::string& what,
                                 std::size_t min_elements) {
    check(doc.elements.size() >= min_elements, what + " element count");
    check(doc.id == "comp_map_alpha", what + " composition id");
    check(std::fabs(doc.dpi - 300.0) < 1e-9, what + " dpi");
    // z-order ascending (stable sort contract) and unique ids.
    bool sorted = true;
    for (std::size_t i = 1; i < doc.elements.size(); ++i) {
        if (doc.elements[i - 1].z_index > doc.elements[i].z_index) sorted = false;
    }
    check(sorted, what + " z-order");
    // Round-trip through the CONV-02 parser keeps the payload.
    const Json dumped = pwb::mapping_document::dump_composition(doc);
    const Composition reparsed =
        pwb::mapping_document::parse_composition(dumped);
    check_json_eq(pwb::mapping_document::dump_composition(reparsed), dumped,
                  what + " roundtrip");
    // MAIN_MAP carries the composer stub, never a nested document.
    bool saw_stub = false;
    for (const ComposerElement& element : doc.elements) {
        if (element.element_type == "main_map") {
            const Json& stub = element.properties["map_document"];
            saw_stub = stub.is_object() &&
                       stub.value("__ref__", "") == "map_document";
        }
    }
    check(saw_stub, what + " map stub");
}

void run_extensions() {
    TemplateRequest request;
    request.template_name = "facies_map";
    request.map = map_alpha();
    request.factor_name = "三角洲";
    request.unit = "";
    const Composition facies = facies_map_template(request);
    check_extension_composition(facies, "templates facies", 6);
    bool has_subtitle = false;
    for (const ComposerElement& element : facies.elements) {
        if (element.id == "elem_subtitle") has_subtitle = true;
    }
    check(has_subtitle, "templates facies subtitle");

    request.template_name = "prediction_map";
    const Composition prediction = prediction_map_template(request);
    check_extension_composition(prediction, "templates prediction", 6);
    bool has_colorbar = false;
    for (const ComposerElement& element : prediction.elements) {
        if (element.id == "elem_colorbar" &&
            element.properties["title"] == "三角洲") {
            has_colorbar = true;
        }
    }
    check(has_colorbar, "templates prediction colorbar");

    request.template_name = "constraint_map";
    check_extension_composition(constraint_map_template(request),
                                "templates constraint", 6);
    request.template_name = "comprehensive_map";
    check_extension_composition(comprehensive_map_template(request),
                                "templates comprehensive", 6);
}

void run_catalog_and_dispatch() {
    const Json catalog = template_catalog();
    check(catalog.is_array() && catalog.size() == 5, "templates catalog size");
    std::vector<std::string> names;
    for (const Json& row : catalog) {
        names.push_back(row.at("name").get<std::string>());
    }
    check(names[0] == "factor_map", "templates catalog first");
    TemplateRequest request;
    request.map = map_alpha();
    for (const std::string& name : names) {
        request.template_name = name;
        const Composition doc = instantiate_template(request);
        check(doc.elements.size() >= 5, "templates instantiate " + name);
    }
    try {
        TemplateRequest bad = request;
        bad.template_name = "nope";
        instantiate_template(bad);
        check(false, "templates unknown (no exception)");
    } catch (const std::out_of_range&) {
        check(true, "templates unknown raised");
    }
}

}  // namespace

int main() {
    run_factor_parity();
    run_extensions();
    run_catalog_and_dispatch();
    return cartography_test::g_failures;
}
