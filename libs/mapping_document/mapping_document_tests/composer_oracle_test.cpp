// V14-COMPILATION-PUBLISH — composer oracle replay.
//
// Replays tools/oracle/generate_composer_fixtures.json (produced by the
// FROZEN Python reference paleo_workbench/mapping/composer/{templates,
// renderer,export}.py) against the native kernels:
//   * composer_templates — the 9-template library + instantiate_template;
//   * composer_renderer — render_composition_to_svg over 57 corpus cases
//     covering every element type, all chart shapes, dict-layer main maps
//     and the honest-placeholder branches;
//   * composer_export — the physical-size re-anchored SVG.
//
// Python's hash()-derived SVG ids are process-random; both sides normalise
// them to stable placeholders before comparing, and the test additionally
// asserts the native ids are stable across repeated renders (they must be
// deterministic, unlike Python's).

#include <pwb/mapping_document/composer_export.hpp>
#include <pwb/mapping_document/composer_renderer.hpp>
#include <pwb/mapping_document/composer_templates.hpp>
#include <pwb/mapping_document/composition.hpp>
#include <pwb/domain/json.hpp>

#include <cstdio>
#include <fstream>
#include <iostream>
#include <regex>
#include <sstream>
#include <string>
#include <vector>

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::cerr << "FAIL: " << what << "\n";
    }
}

pwb::domain::Json load_fixture() {
    std::ifstream in(PWB_COMPOSER_FIXTURE);
    if (!in) {
        std::cerr << "FAIL: cannot open fixture " << PWB_COMPOSER_FIXTURE << "\n";
        ++g_failures;
        return pwb::domain::Json::object();
    }
    std::ostringstream buffer;
    buffer << in.rdbuf();
    try {
        return pwb::domain::Json::parse(buffer.str());
    } catch (const std::exception& ex) {
        std::cerr << "FAIL: fixture parse error: " << ex.what() << "\n";
        ++g_failures;
        return pwb::domain::Json::object();
    }
}

// The fixture's normalisation rules (mirrors the generator).
std::string normalize_svg(const std::string& svg) {
    static const std::vector<std::pair<std::regex, std::string>> kRules = {
        {std::regex("cbar_[0-9]+"), "cbar_H"},
        {std::regex("grad_([0-9]+)_[0-9]+"), "grad_$1_H"},
        {std::regex("lith_[0-9]+"), "lith_H"},
    };
    std::string out = svg;
    for (const auto& [pattern, replacement] : kRules) {
        out = std::regex_replace(out, pattern, replacement);
    }
    return out;
}

std::string sha256_hex(const std::string& text);

std::string as_string(const pwb::domain::Json& value, const std::string& fallback = "") {
    return value.is_string() ? value.get<std::string>() : fallback;
}

// ---------------------------------------------------------------------------
// Template library parity
// ---------------------------------------------------------------------------

void check_template_library(const pwb::domain::Json& fixture) {
    const auto& templates = fixture.at("templates");
    // Entries with a "doc" are materialised documents; the rest are the
    // library declarations.
    std::size_t library_entries = 0;
    std::size_t doc_entries = 0;
    for (const auto& entry : templates) {
        if (!entry.is_object()) continue;
        if (entry.contains("doc")) {
            ++doc_entries;
            const std::string name = as_string(entry.at("template_id"));
            const auto& doc_json = entry.at("doc");
            auto doc = pwb::mapping_document::parse_composition(doc_json);
            check(doc.elements.size() == doc_json.at("elements").size(),
                  name + ": element count round-trips");
            check(doc.width_mm == doc_json.at("width_mm").get<double>(),
                  name + ": width_mm round-trips");
            check(doc.height_mm == doc_json.at("height_mm").get<double>(),
                  name + ": height_mm round-trips");
            check(doc.title == as_string(doc_json.at("title")),
                  name + ": title round-trips");
            check(doc.dpi == doc_json.at("dpi").get<double>(), name + ": dpi round-trips");
            // metadata template_id / template_category (instantiate_template).
            if (doc.metadata.is_object()) {
                check(doc.metadata.contains("template_id"),
                      name + ": metadata carries template_id");
                check(doc.metadata.contains("template_category"),
                      name + ": metadata carries template_category");
            }
            continue;
        }
        ++library_entries;
        const std::string id = as_string(entry.at("template_id"));
        const auto* tpl = pwb::mapping_document::find_composer_template(id);
        check(tpl != nullptr, "template exists: " + id);
        if (tpl == nullptr) continue;
        check(tpl->label == as_string(entry.at("label")), id + ": label parity");
        check(tpl->description == as_string(entry.at("description")),
              id + ": description parity");
        check(tpl->category == as_string(entry.at("category")), id + ": category parity");
        check(tpl->paper_size == as_string(entry.at("paper_size")),
              id + ": paper_size parity");
        check(tpl->orientation == as_string(entry.at("orientation")),
              id + ": orientation parity");
        check(tpl->element_definitions.size() ==
                  entry.at("element_definitions").size(),
              id + ": element definition count parity");
        // Geometry + properties of every definition, in order.
        const auto& defs = entry.at("element_definitions");
        for (std::size_t i = 0; i < defs.size() && i < tpl->element_definitions.size();
             ++i) {
            const auto& expected = defs[i];
            const auto& actual = tpl->element_definitions[i];
            const std::string at = id + "[" + std::to_string(i) + "]";
            check(actual.element_type == as_string(expected.at("element_type")),
                  at + ": element_type parity");
            check(actual.x_mm == expected.at("x_mm").get<double>(), at + ": x parity");
            check(actual.y_mm == expected.at("y_mm").get<double>(), at + ": y parity");
            check(actual.width_mm == expected.at("width_mm").get<double>(),
                  at + ": width parity");
            check(actual.height_mm == expected.at("height_mm").get<double>(),
                  at + ": height parity");
            check(actual.z_index == expected.at("z_index").get<long long>(),
                  at + ": z parity");
            check(actual.properties == expected.at("properties"),
                  at + ": properties parity");
        }
    }
    check(library_entries == 9, "nine built-in templates (got " +
                                    std::to_string(library_entries) + ")");
    check(doc_entries == 11, "eleven materialised template documents (got " +
                                 std::to_string(doc_entries) + ")");
}

// ---------------------------------------------------------------------------
// Renderer parity
// ---------------------------------------------------------------------------

void check_render_cases(const pwb::domain::Json& fixture) {
    pwb::mapping_document::ComposerRenderSeams seams;
    // Palette seam: the fixture freezes the Python ramp stops so the
    // named-ramp colorbar cases render identically.
    const auto& palettes = fixture.at("palettes");
    seams.palette_stops = [&palettes](const std::string& name,
                                      pwb::mapping_document::
                                          ComposerRenderSeams::ColorStops& stops) {
        auto it = palettes.find(name);
        if (it == palettes.end() || !it->is_object()) return false;
        const auto& raw = it->at("stops");
        for (const auto& stop : raw) {
            stops.emplace_back(stop.at(0).get<double>(), stop.at(1).get<std::string>());
        }
        return !stops.empty();
    };

    std::size_t cases = 0;
    for (const auto& entry : fixture.at("render_cases")) {
        if (!entry.is_object()) continue;
        ++cases;
        const std::string name = as_string(entry.at("name"));
        const auto doc = pwb::mapping_document::parse_composition(entry.at("doc"));
        const std::string actual = normalize_svg(
            pwb::mapping_document::render_composition_to_svg(doc, seams));
        const std::string expected = normalize_svg(as_string(entry.at("svg")));
        if (actual != expected) {
            // Report the first differing line for a readable failure.
            std::istringstream a(actual);
            std::istringstream e(expected);
            std::string al;
            std::string el;
            int line = 0;
            while (std::getline(a, al) && std::getline(e, el)) {
                ++line;
                if (al != el) {
                    std::cerr << "FAIL: render case " << name << " line " << line
                              << "\n  expected: " << el
                              << "\n  actual:   " << al << "\n";
                    break;
                }
            }
            ++g_failures;
        }
        ++g_checks;
    }
    check(cases == fixture.at("render_cases").size(),
          "every render case replayed (got " + std::to_string(cases) + ")");

    // Deterministic ids: two renders of the same document are byte-equal
    // (Python's hash()-derived ids are NOT — documented divergence).
    for (const auto& entry : fixture.at("render_cases")) {
        if (!entry.is_object() || as_string(entry.at("name")) != "colorbar_named_ramp") {
            continue;
        }
        const auto doc = pwb::mapping_document::parse_composition(entry.at("doc"));
        const std::string first =
            pwb::mapping_document::render_composition_to_svg(doc, seams);
        const std::string second =
            pwb::mapping_document::render_composition_to_svg(doc, seams);
        check(first == second, "renderer ids are deterministic across calls");
    }
}

// ---------------------------------------------------------------------------
// Export parity (physical-size re-anchoring)
// ---------------------------------------------------------------------------

void check_export_cases(const pwb::domain::Json& fixture) {
    std::size_t cases = 0;
    for (const auto& entry : fixture.at("export_cases")) {
        if (!entry.is_object()) continue;
        ++cases;
        const std::string name = as_string(entry.at("name"));
        const auto doc = pwb::mapping_document::parse_composition(entry.at("doc"));
        const std::string actual =
            normalize_svg(pwb::mapping_document::composition_export_svg(doc));
        const std::string expected = normalize_svg(as_string(entry.at("physical_svg")));
        check(actual == expected, "export physical SVG parity: " + name);

        // The re-anchored root must carry mm width/height and keep the mm
        // viewBox (the physical-size contract).
        check(actual.find("viewBox=\"0 0 " + std::to_string(static_cast<long long>(
                                                   doc.width_mm))) != std::string::npos ||
                  actual.find("viewBox=\"0 0 ") != std::string::npos,
              name + ": viewBox preserved");
        check(actual.find("mm\"") != std::string::npos,
              name + ": physical mm anchors present");
    }
    check(cases == 2, "two export cases replayed (got " + std::to_string(cases) + ")");
}

// ---------------------------------------------------------------------------
// Template instantiation parity against the frozen materialised documents
// ---------------------------------------------------------------------------

void check_instantiation(const pwb::domain::Json& fixture) {
    // The materialised template documents in the fixture were produced by
    // Python's instantiate_template; the native instantiation must match
    // element-for-element (ids differ by design — the fixture's ids are
    // counter-based, the native factory default is counter-based too, but
    // the comparison ignores ids).
    std::size_t compared = 0;
    for (const auto& entry : fixture.at("templates")) {
        if (!entry.is_object() || !entry.contains("doc")) continue;
        const std::string name = as_string(entry.at("template_id"));
        std::string template_id = name;
        // The generator names them "template_<id>" / "template_override" /
        // "template_falsy_overrides".
        std::optional<std::string> title_override;
        std::optional<std::string> paper_override;
        std::optional<std::string> orientation_override;
        std::optional<double> dpi_override;
        if (name == "template_override") {
            template_id = "contour";
            title_override = "等值线定制";
            paper_override = "A3";
            orientation_override = "portrait";
            dpi_override = 600.0;
        } else if (name == "template_falsy_overrides") {
            template_id = "heatmap";
            title_override = "";
            paper_override = "";
            orientation_override = "";
            dpi_override = 0.0;
        } else if (name.rfind("template_", 0) == 0) {
            template_id = name.substr(std::string("template_").size());
        } else {
            continue;
        }
        const auto& doc_json = entry.at("doc");
        pwb::mapping_document::CompositionFactory factory;
        auto actual = pwb::mapping_document::instantiate_composer_template(
            factory, template_id, title_override, paper_override,
            orientation_override, dpi_override);
        const auto& expected = doc_json;
        check(actual.elements.size() == expected.at("elements").size(),
              name + ": instantiated element count");
        check(actual.title == as_string(expected.at("title")),
              name + ": instantiated title");
        check(actual.width_mm == expected.at("width_mm").get<double>(),
              name + ": instantiated width");
        check(actual.height_mm == expected.at("height_mm").get<double>(),
              name + ": instantiated height");
        check(actual.dpi == expected.at("dpi").get<double>(),
              name + ": instantiated dpi");
        check(actual.metadata == expected.at("metadata"),
              name + ": instantiated metadata");
        for (std::size_t i = 0;
             i < actual.elements.size() && i < expected.at("elements").size(); ++i) {
            const auto& a = actual.elements[i];
            const auto& e = expected.at("elements")[i];
            const std::string at = name + "[" + std::to_string(i) + "]";
            check(a.element_type == as_string(e.at("element_type")),
                  at + ": instantiated element_type");
            check(a.x_mm == e.at("x_mm").get<double>(), at + ": instantiated x");
            check(a.y_mm == e.at("y_mm").get<double>(), at + ": instantiated y");
            check(a.width_mm == e.at("width_mm").get<double>(),
                  at + ": instantiated width");
            check(a.height_mm == e.at("height_mm").get<double>(),
                  at + ": instantiated height");
            check(a.z_index == e.at("z_index").get<long long>(),
                  at + ": instantiated z");
            check(a.properties == e.at("properties"), at + ": instantiated properties");
        }
        ++compared;
    }
    check(compared == 11, "11 instantiations compared (got " + std::to_string(compared) +
                              ")");

    // Unknown template id → std::invalid_argument (Python KeyError parity).
    bool threw = false;
    try {
        pwb::mapping_document::CompositionFactory factory;
        pwb::mapping_document::instantiate_composer_template(factory, "no_such_template");
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    check(threw, "unknown template id throws invalid_argument");

    // Shared geometry helper parity (_base_map_frames).
    const auto frames = pwb::mapping_document::template_base_map_frames(297.0, 210.0);
    check(frames[0] == 12.0, "base map margin");
    check(frames[1] == 24.0, "base map top");
    check(frames[2] == 297.0 - 24.0 - 88.0, "base map width");
    check(frames[3] == 210.0 - 24.0 - 34.0, "base map height");
}

}  // namespace

int main() {
    const auto fixture = load_fixture();
    if (fixture.is_null() || !fixture.is_object()) {
        std::cerr << "FAIL: fixture unavailable\n";
        return 1;
    }
    check(as_string(fixture.at("schema")) == "composer-oracle-v14-1",
          "fixture schema version");
    check_template_library(fixture);
    check_instantiation(fixture);
    check_render_cases(fixture);
    check_export_cases(fixture);

    std::cout << (g_checks - g_failures) << "/" << g_checks << " checks passed\n";
    if (g_failures != 0) {
        std::cerr << g_failures << " FAILURES\n";
        return 1;
    }
    std::cout << "composer oracle replay: PASS\n";
    return 0;
}
