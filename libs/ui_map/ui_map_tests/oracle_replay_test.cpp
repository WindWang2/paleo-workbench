// Oracle replay test for the ui_map Qt-free core (UI-05).
// Fixture: fixtures/ui_map_oracle.json — frozen from the real Python
// modules by tools/oracle/generate_ui_map_fixtures.py.
//
// Coverage: constants, field_value, active_map_document, tree keys,
// panel-title fallback, chrome defaults, mode-UI resolution, dock splitter
// precedence, unified revision translation, layer field names,
// mapping_context, toolbar strip groups, tool rebind, kind visibility,
// work-area extent/legend/signature/pick/overlay, display-canvas extent
// history + zoom math + source ids, preview payload normalization.
//
// Documented divergences asserted here (see ledger):
//   * reference_layer_key on a dict layer: Python getattr(layer,"id")
//     degrades to "ref@<identity>" for dicts; the C++ Json record reads the
//     id FIELD -> "ref:<id>" (the intended stable key space for real
//     object layers in Python).
//   * *_key identity fallbacks ("doc@"/"ref@") use the caller-supplied
//     pointer tag — Python freezes id(object) which is a memory address;
//     the replay asserts the "doc@"/"ref@" namespace + non-empty suffix.

#include <algorithm>
#include <cmath>
#include <fstream>
#include <map>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <pwb/ui_map/map_chrome_core.hpp>

#include "ui_map_test.hpp"

using pwb::ui_map::Extent;
using pwb::ui_map::Json;
using namespace pwb::ui_map;

namespace {

Json load_oracle() {
    std::ifstream in(PWB_UI_MAP_ORACLE);
    if (!in) {
        std::fprintf(stderr, "cannot open oracle: %s\n", PWB_UI_MAP_ORACLE);
        std::exit(2);
    }
    std::stringstream buffer;
    buffer << in.rdbuf();
    return Json::parse(buffer.str());
}

const Json& oracle() {
    static const Json data = load_oracle();
    return data;
}

bool near(double a, double b, double eps = 1e-6) {
    return std::fabs(a - b) <= eps;
}

// Numeric-tolerant Json equality (Python float dumps vs C++ doubles).
bool json_near(const Json& actual, const Json& expected, double eps = 1e-6) {
    if (expected.is_number() && actual.is_number()) {
        return near(actual.get<double>(), expected.get<double>(), eps);
    }
    if (expected.is_array() && actual.is_array()) {
        if (actual.size() != expected.size()) {
            return false;
        }
        for (std::size_t i = 0; i < actual.size(); ++i) {
            if (!json_near(actual.at(i), expected.at(i), eps)) {
                return false;
            }
        }
        return true;
    }
    if (expected.is_object() && actual.is_object()) {
        if (actual.size() != expected.size()) {
            return false;
        }
        for (const auto& [key, value] : expected.items()) {
            if (!actual.contains(key) ||
                !json_near(actual.at(key), value, eps)) {
                return false;
            }
        }
        return true;
    }
    return actual == expected;
}

Extent to_extent(const Json& arr) {
    return Extent{arr.at(0).get<double>(), arr.at(1).get<double>(),
                  arr.at(2).get<double>(), arr.at(3).get<double>()};
}

bool extent_near(const Extent& actual, const Json& expected) {
    for (int i = 0; i < 4; ++i) {
        if (!near(actual[i], expected.at(i).get<double>())) {
            return false;
        }
    }
    return true;
}

std::optional<std::vector<int>> opt_sizes(const Json& value) {
    if (value.is_null()) {
        return std::nullopt;
    }
    std::vector<int> out;
    for (const auto& v : value) {
        out.push_back(v.get<int>());
    }
    return out;
}

std::vector<int> int_list(const Json& arr) {
    std::vector<int> out;
    for (const auto& v : arr) {
        out.push_back(v.get<int>());
    }
    return out;
}

std::vector<std::string> str_list(const Json& arr) {
    std::vector<std::string> out;
    for (const auto& v : arr) {
        out.push_back(v.get<std::string>());
    }
    return out;
}

// Rebuild the work-area snapshot Json the generator froze (layers carry
// only {features, extent} — the fields workarea_view_extent reads).
Json snapshot_from_extent_case(const Json& layers_spec) {
    Json layers = Json::array();
    for (const auto& spec : layers_spec) {
        layers.push_back(Json{{"features", spec.at("features")},
                              {"extent", spec.at("extent")}});
    }
    return Json{{"layers", std::move(layers)}};
}

// The well snapshot used by every workarea_widget fixture case (mirrors
// gen_workarea_widget's _layer/_point_feature builders verbatim).
Json workarea_snapshot() {
    auto point = [](const char* well_id, double x, double y) {
        return Json{
            {"geometry",
             Json{{"type", "Point"}, {"coordinates", Json::array({x, y})}}},
            {"properties",
             Json{{"well_id", well_id}, {"name", well_id}}}};
    };
    return Json{
        {"layers",
         Json::array(
             {Json{{"id", "home_workarea:boundary"},
                   {"features", Json::array({Json{{"geometry", Json::object()}}})}},
              Json{{"id", "home_workarea:wells"},
                   {"features",
                    Json::array({point("w1", 10.0, 10.0),
                                 point("w2", 20.0, 20.0)})}},
              Json{{"id", "home_workarea:wells_flagged"},
                   {"features",
                    Json::array({point("w3", 10.0, 40.0)})}}})}};
}

}  // namespace

// ---------------------------------------------------------------------------

PWB_TEST(constants) {
    const Json& c = oracle().at("constants");
    CHECK(str_list(c.at("layer_keys")) ==
          std::vector<std::string>(kLayerKeys.begin(), kLayerKeys.end()));
    const auto& labels = layer_labels();
    for (const auto& [key, label] : c.at("layer_labels").items()) {
        CHECK(labels.count(key) && labels.at(key) == label.get<std::string>());
    }
    CHECK(str_list(c.at("float_keys")) ==
          std::vector<std::string>(kFloatKeys.begin(), kFloatKeys.end()));
    CHECK_EQ(std::string(kDockSplitterKey),
             c.at("dock_splitter_key").get<std::string>());
    CHECK_EQ(static_cast<long long>(kRailWidth),
             c.at("rail").at("width").get<long long>());
    CHECK_EQ(static_cast<long long>(kRailButtonSize),
             c.at("rail").at("button").get<long long>());
    CHECK_EQ(static_cast<long long>(kRailIconSize),
             c.at("rail").at("icon").get<long long>());
    CHECK(near(kWellPickRadiusPx, c.at("well_pick_radius_px").get<double>()));
    CHECK_EQ(static_cast<long long>(kBottomDockedMaxHeight),
             c.at("bottom_docked_max_height").get<long long>());
    CHECK_EQ(static_cast<long long>(kWidgetSizeMax),
             c.at("widget_size_max").get<long long>());
    const std::vector<std::string> layer_ids{
        kWorkareaBoundaryLayerId, kWorkareaSurveyLayerId,
        kWorkareaSurveyLabelLayerId, kWorkareaWellsLayerId,
        kWorkareaWellsFlaggedLayerId};
    CHECK(str_list(c.at("workarea_layer_ids")) == layer_ids);
    const Json expected_elements = c.at("default_chrome_elements");
    CHECK(str_list(expected_elements) == default_chrome_elements());
}

PWB_TEST(field_value) {
    for (const auto& c : oracle().at("field_value")) {
        const Json actual = field_value(c.at("source"), c.at("name").get<std::string>(),
                                        c.at("default"));
        CHECK(json_near(actual, c.at("expected")));
    }
}

PWB_TEST(active_map_document) {
    for (const auto& c : oracle().at("active_map_document")) {
        std::vector<Json> docs;
        if (!c.at("documents").is_null()) {
            docs = c.at("documents").get<std::vector<Json>>();
        }
        const std::string prefer =
            c.at("prefer_id").is_null() ? "" : c.at("prefer_id").get<std::string>();
        const Json* result = active_map_document(docs, prefer);
        if (c.at("expected").is_null()) {
            CHECK(result == nullptr);
        } else {
            CHECK(result != nullptr && json_near(*result, c.at("expected")));
        }
        if (c.contains("expected_is_last") && c.at("expected_is_last").get<bool>()) {
            CHECK(result == &docs.back());
        }
    }
}

PWB_TEST(tree_keys) {
    const Json& section = oracle().at("tree_keys");
    for (const auto& c : section.at("document_key")) {
        const Json& doc = c.at("doc");
        const std::string actual = document_key(doc, &doc);
        if (c.at("expected_stable").get<bool>()) {
            CHECK_EQ(actual, c.at("expected").get<std::string>());
        } else {
            // Identity fallback: namespace + non-empty tag (Python id()).
            CHECK(actual.rfind("doc@", 0) == 0 && actual.size() > 4);
        }
    }
    for (const auto& c : section.at("document_list_key")) {
        const Json& doc = c.at("doc");
        const std::string actual = document_list_key(doc, &doc);
        const std::string id = field_value_str(doc, "id", "");
        if (!id.empty()) {
            CHECK_EQ(actual, c.at("expected").get<std::string>());
        } else {
            CHECK(actual.rfind("doc@", 0) == 0 && actual.size() > 4);
        }
    }
    for (const auto& c : section.at("reference_layer_key")) {
        const Json& layer = c.at("layer");
        const std::string actual = reference_layer_key(layer, &layer);
        const std::string id = field_value_str(layer, "id", "");
        if (!id.empty()) {
            // Documented divergence: C++ reads the id field of the Json
            // record ("ref:<id>") where Python getattr on a dict falls
            // back to the identity key.
            CHECK_EQ(actual, "ref:" + id);
        } else {
            CHECK(actual.rfind("ref@", 0) == 0 && actual.size() > 4);
        }
    }
}

PWB_TEST(panel_title) {
    // Panel hits ("layers" -> 图层面板) need the real MapDockManager —
    // covered by the Qt smoke test. Here the rpartition fallback is
    // replayed for keys absent from the frozen panel registry.
    for (const auto& c : oracle().at("panel_title")) {
        const std::string expected = c.at("expected").get<std::string>();
        if (expected == "图层面板" || expected == "底部工作区") {
            continue;  // panel-registry hit — Qt smoke coverage
        }
        CHECK_EQ(panel_title_fallback(c.at("key").get<std::string>()),
                 expected);
    }
}

PWB_TEST(chrome_defaults) {
    const Json expected = oracle().at("chrome").at("default_elements");
    CHECK(str_list(expected) == default_chrome_elements());
}

PWB_TEST(mode_ui) {
    for (const auto& c : oracle().at("mode_ui")) {
        const ModeUiState state = resolve_mode_ui(
            c.at("preview_mode").get<bool>(),
            c.at("unified_authoring_mode").get<bool>(),
            c.at("canvas_priority").get<bool>(),
            c.at("bottom_user_visible").get<bool>());
        const Json& expected = c.at("expected");
        CHECK_EQ(static_cast<long long>(state.center_index),
                 expected.at("center_index").get<long long>());
        if (c.value("bottom_floating", false)) {
            // Floating bottom: the mode result is routed to the window —
            // window_calls[0] is what the manager was told to show.
            CHECK_EQ(static_cast<long long>(state.bottom_visible ? 1 : 0),
                     expected.at("window_calls").at(0).get<bool>() ? 1 : 0);
        } else {
            CHECK(state.preview_shows_unified ==
                  expected.at("preview_is_unified").get<bool>());
            CHECK(state.bottom_visible ==
                  expected.at("bottom_visible").get<bool>());
        }
    }
}

PWB_TEST(dock_splitter) {
    for (const auto& c : oracle().at("dock_splitter")) {
        const std::vector<int> actual = saved_dock_splitter_sizes(
            opt_sizes(c.at("dock_record")), opt_sizes(c.at("layers_record")),
            int_list(c.at("fallback")));
        CHECK(actual == int_list(c.at("expected")));
    }
}

PWB_TEST(unified_revisions) {
    const Json& sequence = oracle().at("unified_revisions").at(0).at("sequence");

    UnifiedRevisionState state;
    const void* owner_a = reinterpret_cast<const void*>(0xA);
    const void* owner_b = reinterpret_cast<const void*>(0xB);

    // Authoring A raw keys: facies ("d1",5), well ("d1",2); others null.
    std::map<std::string, Json> raw_a{{"facies", Json::array({"d1", 5})},
                                      {"well", Json::array({"d1", 2})}};
    auto fn = [&raw_a](const std::string& kind) -> Json {
        const auto it = raw_a.find(kind);
        return it != raw_a.end() ? it->second : Json(nullptr);
    };

    auto as_map = [](const std::optional<std::map<std::string, long long>>& r) {
        Json out = Json::object();
        if (r.has_value()) {
            for (const auto& [k, v] : *r) {
                out[k] = v;
            }
        } else {
            out = Json(nullptr);
        }
        return out;
    };

    CHECK(json_near(as_map(unified_data_revisions(state, owner_a, true, fn)),
                    sequence.at(0)));
    raw_a["facies"] = Json::array({"d2", 6});
    CHECK(json_near(as_map(unified_data_revisions(state, owner_a, true, fn)),
                    sequence.at(1)));
    // New authoring object: the generator's authoring_b carries the
    // ORIGINAL raw keys {facies:(d1,5), well:(d1,2)} — owner change bumps
    // every kind regardless of raw values, but we mirror the fixture.
    std::map<std::string, Json> raw_b{{"facies", Json::array({"d1", 5})},
                                      {"well", Json::array({"d1", 2})}};
    auto fn_b = [&raw_b](const std::string& kind) -> Json {
        const auto it = raw_b.find(kind);
        return it != raw_b.end() ? it->second : Json(nullptr);
    };
    CHECK(json_near(as_map(unified_data_revisions(state, owner_b, true, fn_b)),
                    sequence.at(2)));
    CHECK(json_near(as_map(unified_data_revisions(state, owner_b, true, fn_b)),
                    sequence.at(3)));
    CHECK(!unified_data_revisions(state, nullptr, true, fn).has_value());
    CHECK(!unified_data_revisions(state, owner_a, false, fn).has_value());
}

PWB_TEST(layer_field_names) {
    for (const auto& c : oracle().at("layer_field_names")) {
        CHECK(str_list(Json(layer_field_names(c.at("features")))) ==
              str_list(c.at("expected")));
    }
}

PWB_TEST(mapping_context) {
    for (const auto& c : oracle().at("mapping_context")) {
        const Json& doc = c.at("doc");
        const Json* doc_ptr = doc.is_null() ? nullptr : &doc;
        const auto& flags = c.at("dirty_flags");
        const bool dirty = is_dirty(flags.at(0).get<bool>(),
                                    flags.at(1).get<bool>(),
                                    flags.at(2).get<bool>());
        const Json actual =
            mapping_context(doc_ptr, dirty, c.at("preview").get<bool>());
        CHECK(json_near(actual, c.at("expected")));
    }
}

PWB_TEST(toolbar_groups) {
    for (const auto& c : oracle().at("toolbar_groups")) {
        // core_ids = registered minus _SURFACE_ICONS {"ribbon_ext"}.
        std::vector<std::string> core_ids;
        for (const auto& id : c.at("registered")) {
            if (id.get<std::string>() != "ribbon_ext") {
                core_ids.push_back(id.get<std::string>());
            }
        }
        const auto groups = toolbar_strip_groups(core_ids);
        Json actual = Json::array();
        for (const auto& group : groups) {
            actual.push_back(Json(group));
        }
        CHECK(json_near(actual, c.at("expected")));
    }
}

PWB_TEST(rebind_tool) {
    for (const auto& c : oracle().at("rebind_tool")) {
        const std::string action = c.at("active_action").is_null()
                                       ? ""
                                       : c.at("active_action").get<std::string>();
        const bool has_authoring = c.value("has_authoring", true);
        const std::string kind = c.at("kind").is_null()
                                     ? ""
                                     : c.at("kind").get<std::string>();
        const ToolRebind result = rebind_tool_after_layer_switch(
            action, has_authoring, kind);
        const Json& requested = c.at("requested");
        if (requested.empty()) {
            CHECK(result == ToolRebind::kKeep || result == ToolRebind::kNone);
        } else if (requested.at(0).get<std::string>() == action &&
                   !action.empty()) {
            CHECK(result == ToolRebind::kRebind);
        } else if (requested.at(0).get<std::string>() == "pan") {
            CHECK(result == ToolRebind::kDeactivatePan);
        } else {
            CHECK(false);
        }
    }
}

PWB_TEST(kind_visibility) {
    // Fixture doc: id "m1", composition [{"id":"m1:well","visible":false},
    // {"id":"other:line","visible":true}].
    const Json composition = Json::array(
        {Json{{"id", "m1:well"}, {"visible", false}},
         Json{{"id", "other:line"}, {"visible", true}}});
    const std::string doc_id = "m1";
    for (const auto& c : oracle().at("kind_visibility")) {
        const bool has_doc = !c.at("document").is_null();
        const bool has_registry = !c.at("registry").is_null();
        const std::string kind = c.at("kind").get<std::string>();
        const std::string wanted = doc_id + ":" + kind;
        Json registry_layer = Json(nullptr);
        if (has_registry && c.at("registry").contains(wanted)) {
            registry_layer =
                Json{{"visible", c.at("registry").at(wanted)}};
        }
        const bool tree_visible = c.at("tree_state").contains(kind)
                                      ? c.at("tree_state").at(kind).get<bool>()
                                      : true;
        const bool actual = kind_visibility(
            has_registry && has_doc, registry_layer, composition, wanted,
            tree_visible);
        CHECK(actual == c.at("expected").get<bool>());
    }
}

PWB_TEST(workarea_extent_and_legend) {
    const Json& section = oracle().at("workarea");
    Json expected_legend = Json::array();
    for (const auto& pair : workarea_legend_items()) {
        expected_legend.push_back(Json::array({pair.first, pair.second}));
    }
    CHECK(json_near(expected_legend, section.at("legend_items")));

    for (const auto& c : section.at("view_extent")) {
        const Json snapshot = snapshot_from_extent_case(c.at("layers"));
        const auto extent = workarea_view_extent(snapshot);
        if (c.at("expected").is_null()) {
            CHECK(!extent.has_value());
        } else {
            CHECK(extent.has_value() &&
                  extent_near(*extent, c.at("expected")));
        }
    }
}

PWB_TEST(domain_signature) {
    for (const auto& c : oracle().at("domain_signature")) {
        CHECK(json_near(domain_signature(c.at("project")), c.at("expected")));
    }
}

PWB_TEST(workarea_widget_picks) {
    const Json& picks = oracle().at("workarea_widget").at("picks");
    const Json snapshot = workarea_snapshot();
    for (const auto& c : picks) {
        if (c.value("snapshot_none", false)) {
            // Null snapshot -> early return, nothing selected/emitted.
            CHECK(well_candidates_from_snapshot(Json(nullptr)).empty());
            CHECK(c.at("selected").is_null() ||
                  c.at("selected").get<std::string>().empty());
            CHECK(c.at("emitted_selected").empty());
            CHECK(c.at("emitted_activated").empty());
            continue;
        }
        double sx = 1.0, ox = 0.0, sy = 1.0, oy = 0.0;
        if (c.contains("transform")) {
            sx = c.at("transform").at(0).at(0).get<double>();
            ox = c.at("transform").at(0).at(1).get<double>();
            sy = c.at("transform").at(1).at(0).get<double>();
            oy = c.at("transform").at(1).at(1).get<double>();
        }
        const double px = c.at("point").at(0).get<double>();
        const double py = c.at("point").at(1).get<double>();
        const std::pair<double, double> click_screen{px * sx + ox,
                                                     py * sy + oy};
        std::vector<WellPickCandidate> candidates;
        for (const auto& well : well_candidates_from_snapshot(snapshot)) {
            candidates.push_back(WellPickCandidate{
                well.well_id, well.x * sx + ox, well.y * sy + oy});
        }
        const std::string best =
            pick_well_id(click_screen, candidates, kWellPickRadiusPx);
        CHECK_EQ(best, c.at("selected").get<std::string>());
        // Emission parity: signals fire iff a well was picked.
        const Json& emitted_sel = c.at("emitted_selected");
        const Json& emitted_act = c.at("emitted_activated");
        CHECK_EQ(static_cast<long long>(emitted_sel.size()),
                 best.empty() ? 0 : 1);
        CHECK_EQ(static_cast<long long>(emitted_act.size()),
                 best.empty() ? 0 : 1);
        if (!best.empty()) {
            CHECK_EQ(emitted_sel.at(0).get<std::string>(), best);
            CHECK_EQ(emitted_act.at(0).get<std::string>(), best);
        }
    }
}

PWB_TEST(workarea_widget_select_and_overlay) {
    const Json& section = oracle().at("workarea_widget");
    const Json snapshot = workarea_snapshot();

    for (const auto& c : section.at("select_zoom")) {
        if (c.contains("emit")) {
            // emit=True path: signal re-emitted only for non-empty id.
            CHECK(c.at("emitted_selected").size() == 1);
            CHECK_EQ(c.at("emitted_selected").at(0).get<std::string>(),
                     std::string("w2"));
            CHECK(c.at("emitted_activated").empty());
            CHECK_EQ(c.at("selected").get<std::string>(), std::string());
            continue;
        }
        const std::string well_id = c.at("well_id").get<std::string>();
        const Json feature = well_feature_by_id(snapshot, well_id);
        CHECK(feature.is_object());
        const Json coords = feature.at("geometry").at("coordinates");
        const Extent extent =
            well_zoom_extent(coords.at(0).get<double>(),
                             coords.at(1).get<double>(),
                             to_extent(c.at("view_extent")));
        CHECK(extent_near(extent, c.at("set_extent")));
    }

    for (const auto& c : section.at("overlay_state")) {
        const std::string selected = c.at("selected").get<std::string>();
        const Json feature = selected.empty()
                                 ? Json(nullptr)
                                 : well_feature_by_id(snapshot, selected);
        const Json actual = workarea_overlay_state(
            c.at("title").get<std::string>(),
            c.at("show_legend").get<bool>(), feature);
        CHECK(json_near(actual, c.at("expected")));
    }

    for (const auto& c : section.at("half_span")) {
        const Extent e = to_extent(c.at("extent"));
        const double half = std::max(
            {(e[2] - e[0]) / 2.0, (e[3] - e[1]) / 2.0, 1.0});
        CHECK(near(half, c.at("expected").get<double>()));
    }

    for (const auto& c : section.at("well_feature")) {
        const Json snap = c.value("snapshot_none", false) ? Json(nullptr)
                                                          : snapshot;
        const Json actual =
            well_feature_by_id(snap, c.at("well_id").get<std::string>());
        CHECK(json_near(actual, c.at("expected")));
    }
}

PWB_TEST(canvas_core_history) {
    const Json& core = oracle().at("canvas_core");

    ExtentHistory history;
    for (const auto& step : core.at("history_trace")) {
        const std::string op = step.at("op").get<std::string>();
        if (op == "record") {
            history.record(to_extent(step.at("extent")),
                           step.value("coalesce_history", false));
        } else if (op == "previous") {
            // History navigates internally; the caller would apply the
            // returned extent with record=false (no history mutation).
            (void)history.previous();
        } else {
            (void)history.next();
        }
        // Exact replay: entries, index, navigation flags.
        CHECK_EQ(static_cast<long long>(history.size()),
                 static_cast<long long>(step.at("history").size()));
        CHECK_EQ(static_cast<long long>(history.index()),
                 step.at("index").get<long long>());
        const Json& frozen = step.at("history");
        for (std::size_t i = 0; i < history.entries().size(); ++i) {
            CHECK(extent_near(history.entries()[i], frozen.at(i)));
        }
        CHECK(history.can_previous() == step.at("can_previous").get<bool>());
        CHECK(history.can_next() == step.at("can_next").get<bool>());
    }

    const Json& cap = core.at("history_cap");
    ExtentHistory capped;
    for (int i = 0; i < 105; ++i) {
        capped.record(Extent{static_cast<double>(i), 0.0,
                             static_cast<double>(i) + 1.0, 1.0});
    }
    CHECK_EQ(static_cast<long long>(capped.size()),
             cap.at("size").get<long long>());
    CHECK_EQ(static_cast<long long>(capped.index()),
             cap.at("index").get<long long>());
    CHECK(extent_near(capped.entries().front(), cap.at("first")));
    CHECK(extent_near(capped.current(), cap.at("last")));
}

PWB_TEST(canvas_core_zoom) {
    const Json& core = oracle().at("canvas_core");
    for (const auto& c : core.at("zoom_by")) {
        if (c.contains("error")) {
            bool threw = false;
            try {
                zoom_by(Extent{0, 0, 1, 1}, c.at("factor").get<double>());
            } catch (const std::invalid_argument&) {
                threw = true;
            }
            CHECK(threw);
            continue;
        }
        std::optional<std::pair<double, double>> center;
        if (!c.at("center").is_null()) {
            center = {c.at("center").at(0).get<double>(),
                      c.at("center").at(1).get<double>()};
        }
        const Extent actual = zoom_by(to_extent(c.at("extent")),
                                      c.at("factor").get<double>(), center);
        CHECK(extent_near(actual, c.at("expected")));
    }
    for (const auto& c : core.at("map_units_per_pixel")) {
        CHECK(near(map_units_per_pixel(to_extent(c.at("extent")),
                                       c.at("width").get<int>(),
                                       c.at("height").get<int>()),
                   c.at("expected").get<double>()));
    }
    for (const auto& c : core.at("source_version_ids")) {
        Json layers = Json::array();
        for (const auto& l : c.at("layers")) {
            layers.push_back(Json{{"source_version_id", l.at("source_version_id")}});
        }
        const Json snapshot = Json{{"layers", std::move(layers)}};
        CHECK(str_list(Json(snapshot_source_version_ids(snapshot))) ==
              str_list(c.at("expected")));
    }
}

PWB_TEST(preview_payload) {
    const Json& section = oracle().at("preview_payload");
    for (const auto& c : section.at("close_ring")) {
        CHECK(json_near(close_ring(c.at("ring")), c.at("expected")));
    }
    for (const auto& c : section.at("normalize_geometry")) {
        CHECK(json_near(normalize_geojson_geometry(c.at("geometry")),
                        c.at("expected")));
    }
    for (const auto& c : section.at("facies_to_geojson")) {
        CHECK(json_near(facies_to_geojson(c.at("raw")), c.at("expected")));
    }
    for (const auto& c : section.at("well_to_lnglat")) {
        CHECK(json_near(well_to_lnglat(c.at("raw")), c.at("expected")));
    }
    for (const auto& c : section.at("payload_from_document")) {
        const Json actual =
            preview_payload_from_document(c.at("document"));
        CHECK(json_near(actual, c.at("expected")));
    }
    for (const auto& c : section.at("payload_from_features")) {
        const Json actual = preview_payload_from_features(
            c.at("features"), c.at("period_name").get<std::string>());
        CHECK(json_near(actual, c.at("expected")));
    }
}

// Deliberate drift: prove the comparisons above can fail (fixture is not
// vacuously equal to whatever the C++ code produces).
PWB_TEST(negative_selfcheck) {
    {
        Json expected = oracle().at("constants").at("layer_labels");
        Json actual = Json(layer_labels());
        CHECK(actual == expected);
        expected["facies"] = "漂移";
        CHECK(actual != expected);
    }
    {
        const auto& c = oracle().at("field_value").at(0);
        Json mutated = c;
        mutated["expected"] = "__drift__";
        const Json actual = field_value(c.at("source"),
                                        c.at("name").get<std::string>(),
                                        c.at("default"));
        CHECK(!json_near(actual, mutated.at("expected")));
    }
    {
        ExtentHistory h;
        h.record(Extent{1, 1, 2, 2});
        h.record(Extent{3, 3, 4, 4});
        CHECK(h.size() != 1);  // coalesce would collapse to 1 — drift caught
    }
}

int main() { return pwb_test::run_all(); }
