// mapping_document.roundtrip — C++ document kernel vs the frozen Python oracle.
//
// For every frozen case the C++ kernel must: parse the input document, run
// the frozen mutation ops, and re-serialize to a payload that compares
// semantically equal to `cpp_expected` (pwb::domain::json_semantically_equal:
// objects compare by key set, arrays by order, int vs float is a type
// difference — so the kernel must reproduce Python's numeric shapes).

#include <cstdio>
#include <exception>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/mapping_document/composition.hpp>
#include <pwb/mapping_document/map_document.hpp>

using pwb::domain::Json;
using namespace pwb::mapping_document;

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

void expect_semantic_equal(const Json& got, const Json& want,
                           const std::string& what) {
    const pwb::domain::JsonDiff diff = pwb::domain::json_semantic_diff(got, want);
    check(diff.equal, what + " (" + diff.path + ": " + diff.reason + ")");
}

const Json& fixture() {
    static const Json* cached = [] {
        std::ifstream stream(PWB_MAPPING_DOCUMENT_FIXTURE, std::ios::binary);
        if (!stream.good()) {
            std::fprintf(stderr, "FAIL cannot open %s\n",
                         PWB_MAPPING_DOCUMENT_FIXTURE);
            std::exit(1);
        }
        std::ostringstream buffer;
        buffer << stream.rdbuf();
        return new Json(Json::parse(buffer.str()));
    }();
    return *cached;
}

// --- map document cases ----------------------------------------------------

void run_layer_probe(const MapDocument& doc, const std::string& name,
                     const Json& probe) {
    if (probe.contains("layer_types")) {
        Json got = Json::array();
        for (const auto& layer : doc.layers) got.push_back(layer.layer_type);
        expect_semantic_equal(got, probe.at("layer_types"), name + " layer_types");
    }
    if (probe.contains("input_version_ids")) {
        expect_semantic_equal(input_version_ids(doc), probe.at("input_version_ids"),
                              name + " input_version_ids");
    }
    if (probe.contains("active_layer_id")) {
        if (doc.has_active_layer) {
            expect_semantic_equal(Json(doc.active_layer_id),
                                  probe.at("active_layer_id"),
                                  name + " active_layer_id");
        } else {
            check(probe.at("active_layer_id").is_null(),
                  name + " active_layer_id expected null");
        }
    }
    if (probe.contains("extent")) {
        Json got = Json::array();
        for (double v : doc.extent) got.push_back(v);
        expect_semantic_equal(got, probe.at("extent"), name + " extent");
    }
    if (probe.contains("layer_ids")) {
        Json got = Json::array();
        for (const auto& layer : doc.layers) got.push_back(layer.id);
        expect_semantic_equal(got, probe.at("layer_ids"), name + " layer_ids");
    }
    if (probe.contains("run_id")) {
        const bool is_object = doc.metadata.is_object()
            && doc.metadata.contains("run_id");
        check(is_object
                  && doc.metadata.at("run_id") == probe.at("run_id"),
              name + " run_id");
    }
}

void run_layer_op(const MapDocument& base, const Json& op,
                  const std::string& name) {
    MapDocument doc = base;  // each op applies to a fresh read
    const std::string op_name = op.at("op").get<std::string>();
    if (op_name == "remove_layer") {
        const std::string victim = op.at("args")[0].get<std::string>();
        const bool present = find_layer(doc, victim) != nullptr;
        const std::optional<MapLayer> removed = remove_layer(doc, victim);
        check(present == removed.has_value(),
              name + " find_layer agrees with remove_layer");
        // Python returns the removed layer (or None): the frozen "returns"
        // field is the oracle for the return value itself.
        if (op.at("returns").is_null()) {
            check(!removed.has_value(), name + " remove_layer returned null");
        } else {
            check(removed.has_value(), name + " remove_layer returned a layer");
            if (removed.has_value()) {
                expect_semantic_equal(dump_layer(*removed), op.at("returns"),
                                      name + " removed layer payload");
            }
        }
    } else if (op_name == "reorder_layers") {
        std::vector<std::string> ids;
        for (const auto& id : op.at("args")[0]) ids.push_back(id.get<std::string>());
        reorder_layers(doc, ids);
    } else if (op_name == "add_layer") {
        MapLayer layer = parse_layer(op.at("args")[0]);
        std::optional<std::size_t> position;
        if (op.contains("position") && !op.at("position").is_null()) {
            position = op.at("position").get<std::size_t>();
        }
        add_layer(doc, std::move(layer), position);
    } else if (op_name == "recompute_extent") {
        recompute_extent(doc);
    } else {
        check(false, name + " unknown op " + op_name);
        return;
    }
    expect_semantic_equal(dump_map_document(doc), op.at("expect"),
                          name + " op " + op_name);
    if (op.contains("probes")) run_layer_probe(doc, name, op.at("probes"));
}

void run_map_document_cases() {
    const Json& cases = fixture()["map_document_cases"];
    for (const auto& c : cases) {
        const std::string name = c.at("id").get<std::string>();
        MapDocument doc;
        try {
            doc = parse_map_document(c.at("input"));
        } catch (const std::exception& ex) {
            check(false, name + " parse threw: " + ex.what());
            continue;
        }
        expect_semantic_equal(dump_map_document(doc), c.at("cpp_expected"),
                              name + " roundtrip");
        run_layer_probe(doc, name, c.at("probes"));
        for (const auto& op : c.at("ops")) run_layer_op(doc, op, name);
    }
    check(cases.size() >= 18, "at least 18 map-document cases exercised");
}

// --- composition cases -----------------------------------------------------

void run_composition_probe(Composition& doc, const std::string& name,
                           const Json& probe) {
    if (probe.contains("schema_version")) {
        check(doc.schema_version == probe.at("schema_version").get<long long>(),
              name + " schema_version");
    }
    if (probe.contains("element_count")) {
        check(doc.elements.size()
                  == static_cast<std::size_t>(probe.at("element_count").get<long long>()),
              name + " element_count");
    }
    if (probe.contains("element_ids_zorder")) {
        Json got = Json::array();
        for (const auto& e : doc.elements) got.push_back(e.id);
        expect_semantic_equal(got, probe.at("element_ids_zorder"),
                              name + " element_ids_zorder");
    }
    if (probe.contains("element_ids")) {  // template case: id list without sort claim
        Json got = Json::array();
        for (const auto& e : doc.elements) got.push_back(e.id);
        expect_semantic_equal(got, probe.at("element_ids"), name + " element_ids");
    }
    if (probe.contains("carried_raw_type")) {
        const ComposerElement* element =
            find_element(doc, probe.at("element_id").get<std::string>());
        check(element != nullptr && element->carried_raw_type,
              name + " carried_raw_type set");
    }
    if (probe.contains("locked")) {
        const ComposerElement* element =
            find_element(doc, probe.at("element_id").get<std::string>());
        check(element != nullptr && element->locked == probe.at("locked").get<bool>(),
              name + " locked probe");
    }
    if (probe.contains("composition_id")) {
        check(doc.id == probe.at("composition_id").get<std::string>(),
              name + " composition_id");
    }
    if (probe.contains("element_ids")) {
        Json got = Json::array();
        for (const auto& e : doc.elements) got.push_back(e.id);
        expect_semantic_equal(got, probe.at("element_ids"), name + " element_ids");
    }
}

void run_composition_op(const Composition& base, const Json& op,
                        const std::string& name) {
    Composition doc = base;
    const std::string op_name = op.at("op").get<std::string>();
    if (op_name == "add_element") {
        add_element(doc, parse_composer_element(op.at("args")[0]));
    } else if (op_name == "set_paper") {
        set_paper(doc, op.at("args")[0].get<std::string>(),
                  op.at("args")[1].get<std::string>());
    } else if (op_name == "set_paper_error") {
        bool threw = false;
        try {
            set_paper(doc, op.at("args")[0].get<std::string>(),
                      op.at("args")[1].get<std::string>());
        } catch (const std::invalid_argument& ex) {
            threw = true;
            check(std::string(ex.what()) == op.at("error").get<std::string>(),
                  name + " set_paper error message: " + ex.what());
        }
        check(threw, name + " set_paper_error threw");
        return;
    } else {
        check(false, name + " unknown op " + op_name);
        return;
    }
    expect_semantic_equal(dump_composition(doc), op.at("expect"),
                          name + " op " + op_name);
    if (op.contains("probes")) run_composition_probe(doc, name, op.at("probes"));
}

void run_composition_cases() {
    const Json& cases = fixture()["composition_cases"];
    for (const auto& c : cases) {
        const std::string name = c.at("id").get<std::string>();
        Composition doc;
        try {
            doc = parse_composition(c.at("input"));
        } catch (const std::exception& ex) {
            check(false, name + " parse threw: " + ex.what());
            continue;
        }
        expect_semantic_equal(dump_composition(doc), c.at("cpp_expected"),
                              name + " roundtrip");
        run_composition_probe(doc, name, c.at("probes"));
        for (const auto& op : c.at("ops")) run_composition_op(doc, op, name);
    }
    check(cases.size() >= 12, "at least 12 composition cases exercised");
}

// --- physical page fold ------------------------------------------------------

void run_pixel_cases() {
    for (const auto& c : fixture()["pixel_cases"]) {
        const std::string name = "pixel " + c.at("width_mm").dump() + "@"
            + c.at("dpi").dump();
        const double width_mm = c.at("width_mm").get<double>();
        const double dpi = c.at("dpi").get<double>();
        // The kernel must reproduce the exact Python evaluation order.
        const double raw = width_mm / 25.4 * dpi;
        check(raw == c.at("raw").get<double>(), name + " IEEE754 fold order");
        Composition doc;
        doc.width_mm = width_mm;
        doc.height_mm = c.at("height_mm").get<double>();
        const auto [wpx, hpx] = composition_page_pixels(doc, dpi);
        check(static_cast<long long>(c.at("width_px").get<long long>()) == wpx
                  && static_cast<long long>(c.at("height_px").get<long long>()) == hpx,
              name + " pixels");
    }
    check(fixture()["pixel_cases"].size() >= 6, "pixel cases exercised");
}

// --- paper-size table --------------------------------------------------------

void run_paper_sizes() {
    for (auto it = fixture()["paper_sizes"].begin();
         it != fixture()["paper_sizes"].end(); ++it) {
        Composition doc;
        set_paper(doc, it.key(), "portrait");
        const Json& want = it.value();
        check(doc.width_mm == want[0].get<double>()
                  && doc.height_mm == want[1].get<double>()
                  && doc.paper_size == it.key(),
              "paper " + it.key() + " portrait geometry");
    }
    check(fixture()["paper_sizes"].size() == 6, "6 paper sizes exercised");
}

}  // namespace

int main() {
    run_map_document_cases();
    run_composition_cases();
    run_pixel_cases();
    run_paper_sizes();
    std::printf("%s: %d failure(s) over %d checks\n",
                g_failures == 0 ? "PASS" : "FAIL", g_failures, g_checks);
    return g_failures == 0 ? 0 : 1;
}
