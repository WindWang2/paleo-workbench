// mapping_document.edit_session — CONV-27 behavior layer vs the frozen
// Python oracle + C++-contract sections.
//
// Oracle replay (fixtures/map_document_edit_oracle.json, produced by
// tools/oracle/generate_map_document_edit_fixtures.py from the real Python
// product code):
//   * composition_cases: every op of a CompositionEditSession sequence is
//     replayed on the C++ session; after every op the revision, undo/redo
//     availability, undo/redo stack labels, command results and the full
//     document dump must equal the Python-recorded state;
//   * map_document_cases: MapDocument kernel ops replayed through the C++
//     session; document dumps compared per step (the session *history*
//     semantics are a C++ contract — Python has no map-document session);
//   * snapshot_cases: captures are projected from the frozen Python
//     document states and must stay stable across later mutations;
//   * io_feature_cases: document_io feature normalization round-trips.
//
// C++-contract sections (no Python equivalent; documented in
// docs/development/cpp-conversion-swarm-20/ledgers/27-decisions.md):
// composition set_paper/set_title/set_metadata undo, grouped edit +
// rollback, unified revision counters/dirty state, file IO atomic save +
// recovery table, service facades.

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

#if defined(__unix__) || defined(__APPLE__)
#include <unistd.h>
#endif

#include <pwb/domain/json.hpp>
#include <pwb/mapping_document/composition.hpp>
#include <pwb/mapping_document/composition_session.hpp>
#include <pwb/mapping_document/document_io.hpp>
#include <pwb/mapping_document/document_service.hpp>
#include <pwb/mapping_document/map_document.hpp>
#include <pwb/mapping_document/map_document_session.hpp>
#include <pwb/mapping_document/map_document_snapshot.hpp>

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
        std::ifstream stream(PWB_MAPPING_DOCUMENT_EDIT_FIXTURE, std::ios::binary);
        if (!stream.good()) {
            std::fprintf(stderr, "FAIL cannot open %s\n",
                         PWB_MAPPING_DOCUMENT_EDIT_FIXTURE);
            std::exit(1);
        }
        std::ostringstream buffer;
        buffer << stream.rdbuf();
        return new Json(Json::parse(buffer.str()));
    }();
    return *cached;
}

std::string optional_string(const Json& payload, const char* key,
                            const std::string& fallback = {}) {
    return payload.contains(key) && payload.at(key).is_string()
               ? payload.at(key).get<std::string>()
               : fallback;
}

Json dump(const Composition& doc) { return dump_composition(doc); }
Json dump(const MapDocument& doc) { return dump_map_document(doc); }

// ---------------------------------------------------------------------------
// Composition oracle replay
// ---------------------------------------------------------------------------

// Deterministic element-id generator mirroring the oracle's patched uuid4:
// 10 lowercase hex digits, restarting per case.
class CaseIds {
public:
    std::string next() {
        char buffer[32];
        std::snprintf(buffer, sizeof(buffer), "%010llx",
                      static_cast<unsigned long long>(next_++));
        return buffer;
    }

private:
    long long next_ = 1;
};

ElementSpec parse_spec(const Json& payload) {
    ElementSpec spec;
    const Json& geometry = payload.at("default_geometry");
    spec.default_geometry = {geometry[0].get<double>(), geometry[1].get<double>(),
                             geometry[2].get<double>(), geometry[3].get<double>()};
    spec.default_properties = payload.at("default_properties");
    return spec;
}

std::optional<double> opt_double(const Json& op, const char* key) {
    if (!op.contains(key) || op.at(key).is_null()) return std::nullopt;
    return op.at(key).get<double>();
}

// The dispatcher used both for replayed ops and the inner call of
// expect_error ops. Error ops rely on it throwing. *result (when non-null)
// receives the operation's return value (undo/redo bool, removed element,
// duplicate id, resolved-binding count) in the shapes the oracle froze.
void dispatch_composition_op(CompositionEditSession& session, Composition& document,
                             const Json& op, CaseIds& ids, Json* result) {
    (void)ids;
    const std::string kind = op.at("op").get<std::string>();
    if (kind == "add_element") {
        const ComposerElement element = session.add_element(
            op.at("element_type").get<std::string>(),
            opt_double(op, "x_mm"), opt_double(op, "y_mm"),
            opt_double(op, "width_mm"), opt_double(op, "height_mm"),
            op.contains("properties") && op.at("properties").is_object()
                ? op.at("properties")
                : Json());
        if (result != nullptr) *result = Json(element.id);
    } else if (kind == "insert_element") {
        session.insert_element(parse_composer_element(op.at("element")));
    } else if (kind == "remove_element") {
        const std::optional<ComposerElement> removed =
            session.remove_element(op.at("element_id").get<std::string>());
        if (result != nullptr) {
            *result = removed.has_value() ? dump_composer_element(*removed)
                                           : Json();
        }
    } else if (kind == "duplicate_element") {
        const std::optional<ComposerElement> clone =
            session.duplicate_element(op.at("element_id").get<std::string>());
        if (result != nullptr) {
            *result = clone.has_value() ? Json(clone->id) : Json();
        }
    } else if (kind == "move_element") {
        session.move_element(op.at("element_id").get<std::string>(),
                             op.at("x_mm").get<double>(), op.at("y_mm").get<double>());
    } else if (kind == "scale_element") {
        session.scale_element(op.at("element_id").get<std::string>(),
                              op.at("width_mm").get<double>(),
                              op.at("height_mm").get<double>());
    } else if (kind == "configure_element") {
        session.configure_element(op.at("element_id").get<std::string>(),
                                  op.at("properties"));
    } else if (kind == "set_locked") {
        session.set_locked(op.at("element_id").get<std::string>(),
                           op.at("locked").get<bool>());
    } else if (kind == "set_element_visible") {
        session.set_element_visible(op.at("element_id").get<std::string>(),
                                    op.at("visible").get<bool>());
    } else if (kind == "bring_to_front") {
        session.bring_to_front(op.at("element_id").get<std::string>());
    } else if (kind == "send_to_back") {
        session.send_to_back(op.at("element_id").get<std::string>());
    } else if (kind == "raise_element") {
        session.raise_element(op.at("element_id").get<std::string>());
    } else if (kind == "undo") {
        const bool undone = session.undo();
        if (result != nullptr) *result = Json(undone);
    } else if (kind == "redo") {
        const bool redone = session.redo();
        if (result != nullptr) *result = Json(redone);
    } else if (kind == "clear_history") {
        session.clear_history();
    } else if (kind == "bind_template") {
        const long long resolved = bind_template(document, op.at("context"));
        if (result != nullptr) {
            // Non-negative integers are emitted unsigned (Python int parity
            // in the domain comparator).
            *result = Json(static_cast<std::uint64_t>(resolved));
        }
    } else {
        check(false, "unknown composition op " + kind);
    }
}

void check_composition_state(CompositionEditSession& session,
                             const Composition& document, const Json& step,
                             const std::string& what) {
    check(session.revision() == step.at("revision").get<long long>(),
          what + " revision");
    check(session.can_undo() == step.at("can_undo").get<bool>(),
          what + " can_undo");
    check(session.can_redo() == step.at("can_redo").get<bool>(),
          what + " can_redo");
    Json labels = Json::array();
    for (const DocumentCommand* command : session.stack().undo_stack()) {
        labels.push_back(command->label());
    }
    expect_semantic_equal(labels, step.at("undo_labels"), what + " undo_labels");
    Json redo_labels = Json::array();
    for (const DocumentCommand* command : session.stack().redo_stack()) {
        redo_labels.push_back(command->label());
    }
    expect_semantic_equal(redo_labels, step.at("redo_labels"),
                          what + " redo_labels");
    expect_semantic_equal(dump(document), step.at("document"), what + " document");
}

void run_composition_case(const Json& case_payload) {
    const std::string name = case_payload.at("name").get<std::string>();
    Composition document = parse_composition(case_payload.at("initial"));
    CompositionFactory factory;
    std::unordered_map<std::string, ElementSpec> specs;
    const Json& specs_json = case_payload.at("specs");
    for (auto it = specs_json.begin(); it != specs_json.end(); ++it) {
        specs.emplace(it.key(), parse_spec(it.value()));
    }
    CaseIds ids;
    factory.set_element_id_generator([&ids]() { return ids.next(); });
    factory.set_spec_provider([&specs](const std::string& element_type) {
        auto found = specs.find(element_type);
        return found == specs.end() ? nullptr : &found->second;
    });
    CompositionEditSession session(document, std::move(factory));

    int step_index = 0;
    for (const Json& op : case_payload.at("ops")) {
        const std::string what = name + " op[" + std::to_string(step_index) + "]";
        const std::string kind = op.at("op").get<std::string>();
        const Json& step = case_payload.at("steps")[step_index];
        if (kind == "expect_error") {
            const std::string expected = op.at("error").get<std::string>();
            bool threw = false;
            try {
                dispatch_composition_op(session, document, op.at("call"), ids,
                                        nullptr);
            } catch (const ComposerError&) {
                threw = true;
                check(expected == "ComposerError", what + " got ComposerError");
            } catch (const UnknownElementError&) {
                threw = true;
                check(expected == "KeyError", what + " got UnknownElementError");
            } catch (const std::invalid_argument&) {
                threw = true;
                check(expected == "ValueError", what + " got invalid_argument");
            }
            check(threw, what + " expected " + expected + ", nothing thrown");
        } else {
            Json result;
            try {
                dispatch_composition_op(session, document, op, ids, &result);
            } catch (const std::exception& error) {
                check(false, what + " threw unexpectedly: " + error.what());
            }
            if (step.contains("result")) {
                expect_semantic_equal(result, step.at("result"),
                                      what + " result");
            }
        }
        check_composition_state(session, document, step, what);
        ++step_index;
    }
}

// ---------------------------------------------------------------------------
// Map document oracle replay (document states are the Python truth)
// ---------------------------------------------------------------------------

// The frozen payloads are full Python to_dict outputs (registry-baked
// default style, post_init extent recompute) — read them through the
// kernel's parse contract verbatim.
MapLayer layer_from_payload(const Json& payload) {
    return parse_layer(payload);
}

void dispatch_map_document_op(MapDocumentEditSession& session, MapDocument& document,
                              const Json& op) {
    const std::string kind = op.at("op").get<std::string>();
    if (kind == "add_layer") {
        session.add_layer(layer_from_payload(op.at("layer")),
                          op.contains("position") && !op.at("position").is_null()
                              ? std::optional<std::size_t>(
                                    op.at("position").get<std::size_t>())
                              : std::nullopt);
    } else if (kind == "remove_layer") {
        session.remove_layer(op.at("layer_id").get<std::string>());
    } else if (kind == "reorder_layers") {
        std::vector<std::string> ids;
        for (const Json& id : op.at("layer_ids")) ids.push_back(id.get<std::string>());
        session.reorder_layers(ids);
    } else if (kind == "recompute_extent") {
        recompute_extent(document);
    } else if (kind == "set_visible") {
        session.set_layer_visible(op.at("layer_id").get<std::string>(),
                                  op.at("visible").get<bool>());
    } else if (kind == "set_opacity") {
        session.set_layer_opacity(op.at("layer_id").get<std::string>(),
                                  op.at("opacity").get<double>());
    } else if (kind == "set_features") {
        session.set_layer_features(op.at("layer_id").get<std::string>(),
                                   op.at("features"));
    } else if (kind == "set_title") {
        session.set_title(op.at("title").get<std::string>());
    } else if (kind == "set_crs") {
        session.set_crs(op.at("crs").get<std::string>());
    } else if (kind == "set_active_layer") {
        session.set_active_layer(op.at("layer_id").get<std::string>());
    } else if (kind == "set_metadata") {
        session.set_metadata(op.at("key").get<std::string>(), op.at("value"));
    } else {
        check(false, "unknown map document op " + kind);
    }
}

void run_map_document_case(const Json& case_payload) {
    const std::string name = case_payload.at("name").get<std::string>();
    MapDocument document = parse_map_document(case_payload.at("initial"));
    MapDocumentEditSession session(document);
    int step_index = 0;
    for (const Json& op : case_payload.at("ops")) {
        const std::string what = name + " op[" + std::to_string(step_index) + "]";
        const Json& step = case_payload.at("steps")[step_index];
        try {
            dispatch_map_document_op(session, document, op);
        } catch (const std::exception& error) {
            check(false, what + " threw unexpectedly: " + error.what());
        }
        expect_semantic_equal(dump(document), step.at("document"),
                              what + " document");
        ++step_index;
    }
}

// ---------------------------------------------------------------------------
// Snapshot cases
// ---------------------------------------------------------------------------

Json project_snapshot(const MapDocumentSnapshot& snap) {
    Json out;
    out["document_id"] = snap.document_id;
    out["revision"] = snap.revision;
    out["title"] = snap.title;
    out["crs"] = snap.crs;
    Json extent = Json::array();
    for (double value : snap.extent) extent.push_back(value);
    out["extent"] = extent;
    out["has_active_layer"] = snap.has_active_layer;
    out["active_layer_id"] = snap.has_active_layer ? Json(snap.active_layer_id)
                                                   : Json();
    out["input_version_ids"] = snap.input_version_ids;
    out["provenance"] = snap.provenance;
    Json layers = Json::array();
    for (const SnapshotLayer& layer : snap.layers) {
        Json entry;
        entry["id"] = layer.id;
        entry["name"] = layer.name;
        entry["layer_type"] = layer.layer_type;
        Json layer_extent = Json::array();
        for (double value : layer.extent) layer_extent.push_back(value);
        entry["extent"] = layer_extent;
        entry["crs"] = layer.crs;
        entry["data_revision"] = layer.data_revision;
        entry["style_revision"] = layer.style_revision;
        entry["visible"] = layer.visible;
        entry["opacity"] = layer.opacity;
        entry["source_version_id"] = layer.source_version_id;
        entry["style"] = layer.style;
        entry["metadata"] = layer.metadata;
        entry["features"] = layer.features;
        entry["annotations"] = layer.annotations;
        layers.push_back(std::move(entry));
    }
    out["layers"] = layers;
    return out;
}

// Build the expected snapshot projection from a frozen Python document
// state (programmatic — no hand-written values).
MapDocumentSnapshot expected_snapshot_from(const Json& frozen_document,
                                           long long revision) {
    MapDocument document = parse_map_document(frozen_document);
    return capture_map_document_snapshot(document, revision);
}

void run_snapshot_case(const Json& case_payload) {
    const std::string name = case_payload.at("name").get<std::string>();
    MapDocument document = parse_map_document(case_payload.at("initial"));
    // Python constructed this document through MapDocument.add_layer, which
    // activates the first layer and recomputes the extent on every add; the
    // replay mirrors that construction path through the session.
    std::vector<MapLayer> layers = std::move(document.layers);
    document.layers.clear();
    MapDocumentEditSession session(document);
    for (const MapLayer& layer : layers) session.add_layer(layer);

    const Json& captures = case_payload.at("captures");
    const long long capture_revision = session.revision();
    const MapDocumentSnapshot capture0 =
        capture_map_document_snapshot(document, capture_revision);
    expect_semantic_equal(
        project_snapshot(capture0),
        project_snapshot(expected_snapshot_from(captures[0].at("document"),
                                                capture_revision)),
        name + " capture0 matches frozen state");

    // Replay the mutations; the first capture must stay stable and the
    // final document must match the last frozen state.
    int mutation_index = 0;
    for (const Json& op : case_payload.at("mutations")) {
        dispatch_map_document_op(session, document, op);
        ++mutation_index;
    }
    expect_semantic_equal(
        project_snapshot(expected_snapshot_from(
            captures[static_cast<std::size_t>(mutation_index)].at("document"),
            session.revision())),
        project_snapshot(capture_map_document_snapshot(document,
                                                       session.revision())),
        name + " final capture matches frozen state");
    check(!snapshots_equal(capture0,
                           capture_map_document_snapshot(document,
                                                         session.revision())),
          name + " mutated snapshot differs (negative control)");
    expect_semantic_equal(
        project_snapshot(capture0),
        project_snapshot(expected_snapshot_from(captures[0].at("document"),
                                                capture_revision)),
        name + " first capture unaffected by later mutations");
}

// ---------------------------------------------------------------------------
// document_io feature cases (oracle)
// ---------------------------------------------------------------------------

void run_io_feature_case(const Json& case_payload) {
    const std::string name = case_payload.at("name").get<std::string>();
    DocumentIoDiagnostics diagnostics;
    FeatureIdGenerator ids;
    const Json& record = case_payload.at("record");
    const Json features = features_from_document(record, &diagnostics, ids);
    expect_semantic_equal(features, case_payload.at("features"),
                          name + " features");
    check(!diagnostics.warnings.empty(),
          name + " malformed records produce diagnostics");
    Json reapplied = record;
    apply_features_to_document(reapplied, features, &diagnostics, ids);
    expect_semantic_equal(reapplied, case_payload.at("reapplied_record"),
                          name + " reapplied record");
}

// ---------------------------------------------------------------------------
// C++-contract sections
// ---------------------------------------------------------------------------

void run_cpp_contract_sections() {
    // -- composition set_paper / set_title / set_metadata undo --------------
    {
        Composition document = parse_composition(Json::object());
        CompositionEditSession session(document);
        session.set_paper("A4", "landscape");
        session.set_title("T1");
        session.set_metadata("author", Json("oracle"));
        check(session.revision() == 3, "composition-level ops bump revision");
        bool threw = false;
        try {
            session.set_paper("b5", "landscape");
        } catch (const std::invalid_argument&) {
            threw = true;
        }
        check(threw, "unknown paper size refused");
        check(session.revision() == 3,
              "refused set_paper leaves revision untouched");
        check(document.paper_size == "A4" && document.title == "T1",
              "refused set_paper leaves document untouched");
        check(session.undo() && session.undo() && session.undo(),
              "three undoable composition-level ops");
        check(document.title == "" && document.paper_size == "A4"
                  && document.orientation == "landscape"
                  && document.width_mm == 297.0 && document.height_mm == 210.0
                  && !document.metadata.contains("author"),
              "composition-level undo restores prior state");
        check(session.redo() && session.redo() && session.redo(),
              "composition-level redo");
        check(document.title == "T1" && document.width_mm == 297.0
                  && document.height_mm == 210.0
                  && document.metadata.at("author") == Json("oracle"),
              "composition-level redo re-applies");
    }

    // -- grouped edit + rollback (composition) -------------------------------
    {
        Composition document = parse_composition(Json::object());
        CompositionEditSession session(document);
        const long long before = session.revision();
        session.begin_group("assemble title block");
        session.add_element("legend", 1.0, 2.0);
        session.add_element("title", 3.0, 4.0);
        check(session.group_open(), "group open during edits");
        check(document.elements.size() == 2, "grouped edits applied live");
        session.end_group();
        check(!session.group_open(), "group closed");
        check(session.revision() == before + 2,
              "each nested command bumped the revision");
        check(session.can_undo() && session.stack().undo_stack().size() == 1
                  && session.stack().undo_stack()[0]->label()
                         == "assemble title block",
              "one history entry for the group");
        check(session.undo(), "group undo");
        check(document.elements.empty(), "group undo reverts all nested");
        check(session.redo(), "group redo");
        check(document.elements.size() == 2, "group redo re-applies all nested");

        // Rollback: partial edits revert, nothing enters history.
        const long long before_rollback = session.revision();
        session.begin_group("partial");
        session.add_element("legend", 0.0, 0.0);
        check(document.elements.size() == 3, "rollback case applied live");
        session.rollback_group();
        check(!session.group_open() && document.elements.size() == 2,
              "rollback reverts the partial edits");
        check(session.stack().undo_stack().size() == 1,
              "rollback leaves no history entry");
        check(session.revision() == before_rollback + 2,
              "rollback bumps the revision: one for the nested apply, one "
              "for the rollback itself (consumers must refresh)");
    }

    // -- map document revisions / dirty / unknown ids --------------------------
    {
        MapDocument document = parse_map_document(Json::object());
        MapDocumentEditSession session(document);
        check(!session.is_dirty(), "fresh session is clean");
        session.mark_saved();
        check(!session.is_dirty(), "mark_saved latches clean");

        MapLayer layer;
        layer.id = "lyr_1";
        layer.layer_type = "vector";
        session.add_layer(layer);
        check(session.is_dirty(), "add_layer dirties (layout)");
        check(session.revisions().layout == 1 && session.revisions().data == 0
                  && session.revisions().style == 0,
              "add_layer bumps layout only");
        session.mark_saved();

        session.set_layer_visible("lyr_1", false);
        check(session.revisions().style == 1, "visibility bumps style");
        check(document.layers[0].style_revision == 2,
              "layer style_revision bumped (set_visible contract)");
        check(session.is_dirty(), "style change dirties");
        session.undo();
        check(session.revisions().style == 2,
              "undo bumps the style counter again (monotonic)");
        check(session.is_dirty(), "undo of a saved change dirties");
        check(document.layers[0].visible == true,
              "undo restored visibility");

        bool threw = false;
        try {
            session.set_layer_visible("lyr_missing", true);
        } catch (const UnknownElementError&) {
            threw = true;
        }
        check(threw, "unknown layer id refused");
        MapLayer grid_layer;
        grid_layer.id = "lyr_grid";
        grid_layer.layer_type = "grid";
        session.add_layer(grid_layer);
        threw = false;
        try {
            session.set_layer_features("lyr_grid", Json::array());
        } catch (const std::invalid_argument&) {
            threw = true;
        }
        check(threw,
              "set_features on a non-vector-family layer refused");
        check(session.revisions().layout == 2, "additions bump layout");

        // set_features extent recompute (VectorMapLayer.set_features parity)
        Json features = Json::array();
        Json feature = Json::object();
        Json geometry = Json::object();
        geometry["type"] = "Point";
        Json coordinates = Json::array();
        coordinates.push_back(2.0);
        coordinates.push_back(3.0);
        geometry["coordinates"] = coordinates;
        feature["geometry"] = geometry;
        features.push_back(feature);
        session.set_layer_features("lyr_1", features);
        // A single point yields a padded, non-degenerate extent
        // (VectorMapLayer.recompute_extent contract).
        check(document.layers[0].extent[0] < 2.0
                  && document.layers[0].extent[2] > 2.0
                  && document.layers[0].extent[1] < 3.0
                  && document.layers[0].extent[3] > 3.0,
              "single-point extent padded degenerate axes");
        check(document.layers[0].data_revision == 2,
              "set_features bumped the layer data revision");
        check(session.revisions().data >= 1, "session data counter moved");
        session.undo();
        check(document.layers[0].features.empty(),
              "undo restored the empty feature payload");

        // reorder undo exactness
        MapLayer second;
        second.id = "lyr_2";
        session.add_layer(second);
        session.reorder_layers({"lyr_2", "lyr_1"});
        check(document.layers[0].id == "lyr_2", "reorder applied");
        session.undo();
        check(document.layers[0].id == "lyr_1", "reorder undo restored order");
        session.redo();
        check(document.layers[0].id == "lyr_2", "reorder redo re-applied");
    }

    // -- immutable snapshot stability -----------------------------------------
    {
        MapDocument document = parse_map_document(Json::object());
        MapDocumentEditSession session(document);
        MapLayer layer;
        layer.id = "lyr_s";
        layer.layer_type = "vector";
        Json style = Json::object();
        style["color"] = "#123456";
        layer.style = style;
        session.add_layer(layer);
        const MapDocumentSnapshot snap = capture_map_document_snapshot(
            document, session.revision());
        Json mutated_style = style;
        mutated_style["color"] = "#abcdef";
        session.set_layer_style("lyr_s", mutated_style);
        check(snap.layers.at(0).style == style,
              "captured style payload is a deep copy");
        check(!snapshots_equal(snap,
                               capture_map_document_snapshot(document, 99)),
              "mutated document produces a different snapshot");
    }

    // -- file IO: atomic save + recovery table (cpp-io-contract) ---------------
    {
        namespace fs = std::filesystem;
        fs::path dir = fs::temp_directory_path()
                       / ("pwb_conv27_io_" + std::to_string(::getpid()));
        fs::create_directories(dir);
        auto store = make_std_file_store();
        const std::string path = (dir / "composition.json").string();

        Composition doc = parse_composition(Json::object());
        doc.title = "Persisted";
        std::string error;
        check(save_composition_file(*store, path, doc, error),
              "atomic save (" + error + ")");
        Composition loaded;
        DocumentIoDiagnostics diagnostics;
        const LoadResult result =
            load_composition_file(*store, path, loaded, &diagnostics);
        check(result.status == LoadStatus::kOk, "load status ok");
        check(loaded.title == "Persisted", "round-trip content");

        // Unknown fields survive and are reported.
        Json payload = dump_composition(doc);
        payload["future_section"] = Json::object();
        std::string bytes = payload.dump();
        { std::ofstream out(path, std::ios::binary); out << pwb::domain::dump_json_python_compatible(payload); }
        Composition with_extras;
        DocumentIoDiagnostics extras_diagnostics;
        load_composition_file(*store, path, with_extras, &extras_diagnostics);
        check(!extras_diagnostics.warnings.empty(),
              "unknown top-level key reported");
        check(dump_composition(with_extras).contains("future_section"),
              "unknown key preserved in extras");

        // Interrupted save: only the backup exists.
        const std::string bak = path + ".bak";
        check(save_composition_file(*store, path, doc, error),
              "second save promotes the first to .bak");
        store->remove(path, error);
        Composition recovered;
        DocumentIoDiagnostics recovery_diagnostics;
        const LoadResult recovered_result =
            load_composition_file(*store, path, recovered, &recovery_diagnostics);
        check(recovered_result.status == LoadStatus::kRecoveredFromBackup,
              "interrupted save recovered from backup");
        check(recovery_diagnostics.recovery_source == "backup-interrupted-save",
              "recovery source recorded");
        check(recovered.title == "Persisted", "backup content loaded");

        // Corrupt main + good backup: quarantine + restore.
        { std::ofstream out(path, std::ios::binary); out << "{not json"; }
        const std::string main_before = [&] {
            std::string bytes;
            store->read(bak, bytes, error);
            return bytes;
        }();
        Composition recovered2;
        DocumentIoDiagnostics corrupt_diagnostics;
        const LoadResult corrupt_result =
            load_composition_file(*store, path, recovered2, &corrupt_diagnostics);
        check(corrupt_result.status == LoadStatus::kRecoveredCorrupt,
              "corrupt main recovered from backup");
        check(corrupt_diagnostics.recovery_source == "backup-corrupt-main",
              "corrupt recovery source recorded");
        std::string main_after;
        store->read(path, main_after, error);
        check(main_after == main_before, "main restored from backup bytes");
        bool quarantined_found = false;
        for (const fs::directory_entry& entry : fs::directory_iterator(dir)) {
            if (entry.path().string().find(".corrupt-") != std::string::npos) {
                quarantined_found = true;
            }
        }
        check(quarantined_found, "corrupt main quarantined");

        // Corrupt main + no backup: honest failure, main untouched.
        const std::string lone = (dir / "lone.json").string();
        { std::ofstream out(lone, std::ios::binary); out << "{broken"; }
        Composition lone_doc;
        DocumentIoDiagnostics lone_diagnostics;
        const LoadResult lone_result =
            load_composition_file(*store, lone, lone_doc, &lone_diagnostics);
        check(lone_result.status == LoadStatus::kCorrupt,
              "corrupt without backup fails honestly");
        std::string lone_bytes;
        store->read(lone, lone_bytes, error);
        check(lone_bytes == "{broken", "failed load left main untouched");

        fs::remove_all(dir);
    }

    // -- service facades -------------------------------------------------------
    {
        MapDocumentService service;
        Json payload = Json::object();
        payload["id"] = Json("map_service");
        payload["title"] = Json("Service Map");
        std::string error;
        check(service.load_json(payload, &error), "service load_json (" + error + ")");
        check(!service.is_dirty(), "loaded document clean");
        auto& session = service.session();
        MapLayer layer;
        layer.id = "lyr_service";
        session.add_layer(layer);
        check(service.is_dirty(), "edit dirties service document");
        check(service.snapshot().revision == session.revision(),
              "snapshot pins the session revision");
        namespace fs = std::filesystem;
        fs::path dir = fs::temp_directory_path()
                       / ("pwb_conv27_service_" + std::to_string(::getpid()));
        fs::create_directories(dir);
        std::string save_error;
        check(service.save_file((dir / "doc.json").string(), &save_error),
              "service save (" + save_error + ")");
        check(!service.is_dirty(), "save latched the saved revisions");
        MapDocumentService reloaded;
        const LoadStatus status =
            reloaded.load_file((dir / "doc.json").string());
        check(status == LoadStatus::kOk, "service reload");
        check(reloaded.document().layers.size() == 1,
              "reload preserved the layer");
        check(!reloaded.session().can_undo(), "reload reset the history");
        fs::remove_all(dir);
    }
}

}  // namespace

int main() {
    const Json& data = fixture();
    for (const Json& case_payload : data.at("composition_cases")) {
        run_composition_case(case_payload);
    }
    for (const Json& case_payload : data.at("map_document_cases")) {
        run_map_document_case(case_payload);
    }
    for (const Json& case_payload : data.at("snapshot_cases")) {
        run_snapshot_case(case_payload);
    }
    for (const Json& case_payload : data.at("io_feature_cases")) {
        run_io_feature_case(case_payload);
    }
    run_cpp_contract_sections();
    std::fprintf(stderr, "%d checks, %d failures\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}
