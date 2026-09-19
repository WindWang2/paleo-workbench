// UI-02 — Qt-free core behavior tests (no Qt link).
//
// Covers the cores ported into pwb_ui_widgets_core:
//   epoch_switching  (mapping_workspace/epoch_switching.py parity —
//                     consumed by components/stratigraphic_timeline_slider.py)
//   facies_patterns  (components/facies_palette_widget.py pattern/color)
//   facies_pick      (components/facies_eyedropper.py pick logic)
//   facies_taxonomy  (components/facies_palette_widget.py vocabulary)
//   hud_sampling     (components/constraint_factor_hud.py sampling)
//   qc_hub_core      (components/interactive_qc_hub.py pan/fix registry)
//   tree_sync        (qgis_stack/tree_sync.py payload parsing)

#include <cmath>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "pwb/ui_widgets/core/epoch_switching.hpp"
#include "pwb/ui_widgets/core/facies_patterns.hpp"
#include "pwb/ui_widgets/core/facies_pick.hpp"
#include "pwb/ui_widgets/core/facies_taxonomy.hpp"
#include "pwb/ui_widgets/core/hud_sampling.hpp"
#include "pwb/ui_widgets/core/qc_hub_core.hpp"
#include "pwb/ui_widgets/core/tree_sync.hpp"

#include "ui_widgets_test.hpp"

using namespace pwb::ui_widgets::core;

namespace {

// Python md5().hexdigest() parity fixture values are not needed — the
// contract is determinism + derivation from (name, feature_color).
std::string fake_md5(const std::string& s) {
    std::string out;
    for (char c : s) out += char('a' + (static_cast<unsigned char>(c) % 26));
    return out;
}

LayerSnapshot layer(std::string id, std::string epoch, bool visible = true,
                    std::string name = "", std::string role = "") {
    LayerSnapshot l;
    l.id = std::move(id);
    l.name = std::move(name);
    l.visible = visible;
    if (!epoch.empty()) l.metadata["epoch"] = std::move(epoch);
    if (!role.empty()) l.metadata["layer_role"] = std::move(role);
    return l;
}

}  // namespace

// ---------------------------------------------------------------- epoch ids
PWB_TEST(epoch_group_id_roundtrip) {
    CHECK_EQ(epoch_group_id("E1"), std::string("epoch.E1"));
    CHECK_EQ(epoch_group_id("K1 上"), std::string("epoch.K1_上"));
    CHECK_EQ(epoch_group_id("   "), std::string(""));
    CHECK(is_epoch_group("epoch.E1"));
    CHECK(!is_epoch_group("phase1.interpretation"));
    CHECK(!is_epoch_group(""));
    CHECK_EQ(epoch_key_of_group("epoch.K1_上").value_or("?"),
             std::string("K1 上"));
    CHECK(!epoch_key_of_group("phase1.x").has_value());
}

PWB_TEST(tag_only_classifier_fields) {
    // epoch > horizon > epoch-group (Python priority order).
    CHECK_EQ(tag_only_classifier(layer("l1", "E1")).value_or("?"), "E1");
    {
        LayerSnapshot l;
        l.id = "l2";
        l.metadata["horizon"] = "H2";
        CHECK_EQ(tag_only_classifier(l).value_or("?"), "H2");
    }
    {
        LayerSnapshot l;
        l.id = "l3";
        l.metadata["group"] = "epoch.E3";
        CHECK_EQ(tag_only_classifier(l).value_or("?"), "E3");
    }
    {
        LayerSnapshot l;
        l.id = "l4";
        CHECK(!tag_only_classifier(l).has_value());
    }
}

PWB_TEST(default_classifier_name_fallback) {
    const std::vector<EpochInfo> epochs = {
        {"E1", "第一期"}, {"E2", "第二期"}};
    const auto classify = default_epoch_classifier(epochs);

    // Name fallback requires length >= 2 key/label (single-char keys do
    // not substring-match — "A" ⊂ "BASE" guard).
    CHECK_EQ(classify(layer("a", "", true, "第二期相带")).value_or("?"), "E2");
    CHECK(!classify(layer("b", "", true, "unnamed")).has_value());
    // Explicit metadata tag wins over name.
    LayerSnapshot tagged = layer("c", "", true, "第一期相带");
    tagged.metadata["epoch"] = "E2";
    CHECK_EQ(classify(tagged).value_or("?"), "E2");
}

PWB_TEST(epoch_switch_plan_symmetric_diff) {
    const std::vector<LayerSnapshot> layers = {
        layer("old1", "E1", true),
        layer("old2", "E1", false),   // hidden member of old epoch: untouched
        layer("new1", "E2", false),   // hidden member of target: show
        layer("new2", "E2", true),    // already visible: untouched
        layer("free", "", true),      // unclassified: untouched
    };
    const std::string current = "E1";
    const EpochSwitchPlan plan =
        build_epoch_switch_plan(layers, &current, "E2");
    CHECK_EQ(plan.target, std::string("E2"));
    CHECK_EQ(plan.show.size(), 1);
    CHECK_EQ(plan.show[0], std::string("new1"));
    CHECK_EQ(plan.hide.size(), 1);
    CHECK_EQ(plan.hide[0], std::string("old1"));

    // Same-epoch target: empty plan (Python returns EpochSwitchPlan(target)).
    const EpochSwitchPlan noop =
        build_epoch_switch_plan(layers, &current, "E1");
    CHECK(!noop.has_changes());

    // No current epoch (first activation): still a full diff.
    const EpochSwitchPlan first =
        build_epoch_switch_plan(layers, nullptr, "E2");
    CHECK_EQ(first.show.size(), 1);
    CHECK_EQ(first.hide.size(), 1);
}

PWB_TEST(onion_layers_prev_epoch_facies_only) {
    const std::vector<EpochInfo> epochs = {
        {"E1", "一"}, {"E2", "二"}, {"E3", "三"}};
    const std::vector<LayerSnapshot> layers = {
        layer("f1", "E1", true, "", "initial_facies_draft"),
        layer("f2", "E1", true, "", "map_annotation"),  // not facies
        layer("f3", "E2", true, "", "initial_facies_draft"),
    };
    // current E2 -> prev E1, facies layers only.
    const auto onion = build_onion_layers(layers, epochs, "E2");
    CHECK_EQ(onion.size(), 1);
    CHECK_EQ(onion[0], std::string("f1"));
    // Oldest epoch has no previous.
    CHECK(build_onion_layers(layers, epochs, "E1").empty());
    // Unknown current -> empty.
    CHECK(build_onion_layers(layers, epochs, "E9").empty());
    CHECK_EQ(kOnionOpacity, 0.30);
}

// ------------------------------------------------------------ facies patterns
PWB_TEST(facies_pattern_id_mapping) {
    // Vocabulary mapping: "河流" -> "fluvial" (frozen pattern map);
    // unknown names are an honest nullopt (Python dict .get parity).
    const auto known = pattern_id_for_facies("河流");
    CHECK(known.has_value());
    CHECK_EQ(*known, std::string("fluvial"));
    CHECK_EQ(*pattern_id_for_facies("三角洲"), std::string("delta"));
    CHECK(!pattern_id_for_facies("definitely-not-a-facies").has_value());
    // path_for_facies only resolves when the mapped file exists under dir.
    CHECK(!pattern_path_for_facies("definitely-not-a-facies", "/tmp")
               .has_value());
    CHECK(!pattern_path_for_facies("河流", "/nonexistent-dir").has_value());
}

PWB_TEST(facies_category_color_deterministic) {
    // md5-derived deterministic hue per (name, feature_color): same input
    // -> same output; the seeded md5 keeps category colors stable across
    // sessions (Python parity).
    const std::string a =
        facies_category_color("曲流河", "#112233", fake_md5);
    const std::string b =
        facies_category_color("曲流河", "#112233", fake_md5);
    CHECK_EQ(a, b);
    CHECK(!a.empty());
    // Different seed -> derived (not equal in general — assert the call
    // produces a color-shaped string, not a crash).
    const std::string c =
        facies_category_color("三角洲", "#112233", fake_md5);
    CHECK(!c.empty());
    CHECK(!facies_class_fills().empty());
}

// ---------------------------------------------------------------- facies pick
PWB_TEST(facies_pick_identify_chain) {
    // Feature with facies attrs -> picked at deepest available level.
    FaciesIdentifyFn identify = [](double, double) {
        nlohmann::ordered_json f;
        f["layer_id"] = "L1";
        f["feature_id"] = "F9";
        f["layer_name"] = "相带层";
        f["attributes"] = {{"facies", "曲流河"}, {"sub_facies", "边滩"}};
        return std::vector<nlohmann::ordered_json>{f};
    };
    FaciesColorFn color_of = [](const std::string&) { return "#aabbcc"; };
    const auto result = pick_facies_at(10.0, 20.0, identify, color_of);
    CHECK(result.has_value());
    CHECK_EQ(result->facies, std::string("曲流河"));
    CHECK_EQ(result->sub_facies, std::string("边滩"));
    CHECK_EQ(result->layer_id, std::string("L1"));
    CHECK_EQ(result->feature_id, std::string("F9"));
    CHECK_EQ(result->color, std::string("#aabbcc"));
    CHECK_EQ(result->level, std::string("sub_facies"));

    // Empty identify -> miss (honest: pick_missed in the Qt shell).
    FaciesIdentifyFn empty = [](double, double) {
        return std::vector<nlohmann::ordered_json>{};
    };
    CHECK(!pick_facies_at(0.0, 0.0, empty, color_of).has_value());
}

// ------------------------------------------------------------ facies taxonomy
PWB_TEST(facies_field_aliases) {
    CHECK_EQ(resolve_facies_field("facies", {"facies_name", "x"}),
             std::string("facies_name"));
    CHECK_EQ(resolve_facies_field("facies", {"x", "facies"}),
             std::string("facies"));
    // No alias present -> "" (Python parity: honest miss, not a guess).
    CHECK_EQ(resolve_facies_field("micro_facies", {"a", "b"}),
             std::string(""));
}

PWB_TEST(taxonomy_names_chain_and_fallback) {
    // Tree: 相A {亚相A1, 亚相A2}, 相B {亚相B1}.
    nlohmann::ordered_json tree;
    tree["曲流河"]["边滩"] = nlohmann::json::object();
    tree["曲流河"]["心滩"] = nlohmann::json::object();
    tree["三角洲"]["前缘"] = nlohmann::json::object();
    FaciesTaxonomy tax(tree);

    const auto top = tax.names("facies");
    CHECK_EQ(top.size(), 2);
    const auto subs_a = tax.names("sub_facies", {"曲流河"});
    CHECK_EQ(subs_a.size(), 2);
    const auto subs_b = tax.names("sub_facies", {"三角洲"});
    CHECK_EQ(subs_b.size(), 1);
    // Incomplete/absent parent chain -> ALL names at the level (never
    // guess, never silently clear caller state).
    const auto subs_all = tax.names("sub_facies");
    CHECK_EQ(subs_all.size(), 3);
    CHECK(tax.has("边滩", "sub_facies", {"曲流河"}));
    CHECK(!tax.has("边滩", "sub_facies", {"三角洲"}));
}

PWB_TEST(taxonomy_from_geojson_orphans_skipped) {
    // level+parent_id chain; orphan (missing parent) is skipped.
    nlohmann::json features = nlohmann::json::array();
    nlohmann::json f1;
    f1["properties"] = {{"level", "facies"}, {"facies", "曲流河"},
                        {"id", "p1"}};
    nlohmann::json f2;
    f2["properties"] = {{"level", "sub_facies"}, {"facies", "边滩"},
                        {"id", "c1"}, {"parent_id", "p1"}};
    nlohmann::json orphan;
    orphan["properties"] = {{"level", "micro_facies"}, {"facies", "x"},
                            {"id", "c9"}, {"parent_id", "missing"}};
    features.push_back(f1);
    features.push_back(f2);
    features.push_back(orphan);
    FaciesTaxonomy tax = FaciesTaxonomy::from_geojson_features(features);
    CHECK(tax.has("曲流河", "facies"));
    CHECK(tax.has("边滩", "sub_facies", {"曲流河"}));
    CHECK(!tax.has("x", "micro_facies", {"曲流河", "边滩"}));
}

// -------------------------------------------------------------- hud sampling
PWB_TEST(axis_locate_bounds_and_direction) {
    const std::vector<double> asc = {0.0, 1.0, 2.0, 3.0};
    CHECK(axis_locate(asc, 1.5).has_value());
    CHECK_EQ(axis_locate(asc, 1.5).value(), 1);
    CHECK_EQ(axis_locate(asc, 0.0).value(), 0);
    CHECK(!axis_locate(asc, -0.5).has_value());
    CHECK(!axis_locate(asc, 3.5).has_value());
    // Descending axis supported (map north-up / south-up).
    const std::vector<double> desc = {3.0, 2.0, 1.0, 0.0};
    CHECK(axis_locate(desc, 1.5).has_value());
    // Degenerate axis -> nullopt.
    CHECK(!axis_locate({1.0}, 1.0).has_value());
}

PWB_TEST(bilinear_sample_center_exact) {
    GridView g;
    g.grid_x = {0.0, 1.0, 2.0};
    g.grid_y = {0.0, 1.0, 2.0};
    // z = x + 10*y -> bilinear must reproduce the plane exactly.
    g.grid_z = {0, 1, 2, 10, 11, 12, 20, 21, 22};
    const auto v = bilinear_sample(g, 1.5, 0.5);
    CHECK(v.has_value());
    CHECK(std::abs(*v - (1.5 + 10.0 * 0.5)) < 1e-9);
    // On-node sample returns the node.
    const auto node = bilinear_sample(g, 2.0, 2.0);
    CHECK(node.has_value());
    CHECK(std::abs(*node - 22.0) < 1e-9);
    // Out of range -> nullopt.
    CHECK(!bilinear_sample(g, -1.0, 0.0).has_value());
}

PWB_TEST(bilinear_nan_cell_is_honest_miss) {
    GridView g;
    g.grid_x = {0.0, 1.0};
    g.grid_y = {0.0, 1.0};
    g.grid_z = {0.0, std::nan(""), 1.0, 2.0};
    // Nearest-corner gate: (0.6,0.4) snaps to cell corner (1,0)=NaN ->
    // nullopt, no extrapolation.
    CHECK(!bilinear_sample(g, 0.6, 0.4).has_value());
    // Partial NaN elsewhere still interpolates around the gap (Python
    // parity: only the nearest-cell veto refuses, not any NaN in cell).
    const auto v = bilinear_sample(g, 0.4, 0.5);
    CHECK(v.has_value());
    CHECK(std::isfinite(*v));
}

PWB_TEST(slope_and_confidence_contracts) {
    GridView g;
    g.grid_x = {0.0, 1.0, 2.0};
    g.grid_y = {0.0, 1.0, 2.0};
    // Plane z = x -> gradient (1,0) -> slope = atan(1) = 45 deg.
    g.grid_z = {0, 1, 2, 0, 1, 2, 0, 1, 2};
    const auto slope = local_slope_degrees(g, 1.0, 1.0);
    CHECK(slope.has_value());
    CHECK(std::abs(*slope - 45.0) < 1e-6);
    // Edges use CLAMPED central differences (Python parity) — the plane
    // still yields 45 deg at the border, not a nullopt.
    const auto edge = local_slope_degrees(g, 0.0, 1.0);
    CHECK(edge.has_value());
    CHECK(std::abs(*edge - 45.0) < 1e-6);
    // Honest miss only when a stencil direction cannot sample at all
    // (degenerate axis -> nullopt, never a half answer).
    GridView degenerate;
    degenerate.grid_x = {0.0};
    degenerate.grid_y = {0.0, 1.0};
    degenerate.grid_z = {0.0, 1.0};
    CHECK(!local_slope_degrees(degenerate, 0.0, 0.5).has_value());

    // Variance-free grid -> no confidence (IDW path).
    CHECK(!confidence_from_variance(g, 1.0, 1.0).has_value());
    // sigma reference is a non-negative population stddev.
    CHECK(grid_sigma_reference(g) >= 0.0);

    // Uniform variance -> confidence defined and in (0,1].
    g.variance_grid = std::vector<double>(9, 0.25);
    const auto conf = confidence_from_variance(g, 1.0, 1.0, 1.0);
    CHECK(conf.has_value());
    CHECK(*conf > 0.0 && *conf <= 1.0);
}

PWB_TEST(nearest_well_tolerance_and_precedence) {
    const std::vector<WellLocation> wells = {
        {"W_far", {{100.0, 100.0}}, {}, {}},
        {"W_near", {{1.0, 0.0}}, {{9.0, 9.0}}, {}},
        {"W_plain", {}, {}, {{2.0, 0.0}}},
        {"W_none", {}, {}, {}},
    };
    // project coords beat surface/plain.
    const auto best = nearest_well(wells, 1.4, 0.0, 50.0);
    CHECK(best.has_value());
    CHECK_EQ(best->first, std::string("W_near"));
    // Beyond tolerance -> nullopt.
    CHECK(!nearest_well(wells, 1.4, 0.0, 0.1).has_value());
    // Well without coords is skipped entirely.
    const auto far = nearest_well(wells, 1.0, 0.0, 0.5);
    CHECK(far.has_value());
    CHECK(far->first != "W_none");
}

// ----------------------------------------------------------------- qc hub core
PWB_TEST(qc_padded_bbox_and_easing) {
    // pad=0 keeps the raw bbox through the (degenerate) max() arm.
    const auto raw = padded_bbox({0.0, 0.0, 10.0, 4.0}, 0.0);
    CHECK(std::abs(raw[0] - 0.0) < 1e-9);
    CHECK(std::abs(raw[2] - 10.0) < 1e-9);
    // Positive pad expands symmetrically around the center.
    const auto padded = padded_bbox({0.0, 0.0, 10.0, 4.0}, 0.1);
    CHECK(padded[0] < 0.0 && padded[2] > 10.0);
    CHECK(std::abs((padded[0] + padded[2]) / 2.0 - 5.0) < 1e-9);
    // Degenerate input -> the Python default (0,0,1,1).
    const auto bad = padded_bbox({1.0, 2.0}, 0.1);
    CHECK(std::abs(bad[2] - 1.0) < 1e-9);

    CHECK(std::abs(ease_in_out(0.0) - 0.0) < 1e-9);
    CHECK(std::abs(ease_in_out(0.5) - 0.5) < 1e-9);
    CHECK(std::abs(ease_in_out(1.0) - 1.0) < 1e-9);
    CHECK(ease_in_out(-1.0) == 0.0);
    CHECK(ease_in_out(2.0) == 1.0);
}

PWB_TEST(qc_quick_fix_registry) {
    const auto& registry = quick_fix_registry();
    CHECK(!registry.empty());
    const auto sliver = actions_for_rule("sliver_polygon");
    CHECK(!sliver.empty());
    CHECK_EQ(sliver[0].action_id, std::string("sliver_merge"));
    // Unknown rule -> empty list, not an error.
    CHECK(actions_for_rule("no_such_rule").empty());
}

// ------------------------------------------------------------------- tree sync
PWB_TEST(tree_change_legacy_parse) {
    const auto cs = parse_tree_change(
        R"({"visibility":{"l1":true,"l2":0},"order":["l1","l2"],
            "renames":{"l1":"新名"}})");
    CHECK(!cs.empty());
    CHECK(cs.visibility.at("l1"));
    CHECK(!cs.visibility.at("l2"));  // bool(0) -> false
    CHECK_EQ(cs.order.size(), 2);
    CHECK_EQ(cs.renames.at("l1"), std::string("新名"));

    // Empty/bad payloads -> empty set (Python parity: no throw).
    CHECK(parse_tree_change("").empty());
    CHECK(parse_tree_change("not json").empty());
    CHECK(parse_tree_change("[1,2]").empty());
    CHECK(parse_tree_change("{}").empty());
}

PWB_TEST(tree_events_schema2_parse) {
    const auto batch = parse_tree_events(
        R"({"schema":2,
            "events":[
              {"type":"visibility","node_type":"group","node_id":"g1","value":true},
              {"type":"rename","node_type":"layer","node_id":"l1","value":"L"},
              {"type":"visibility","node_id":"l2","value":0},
              {"type":"bogus","node_type":"layer","node_id":"x","value":1},
              {"type":"rename","node_type":"layer","node_id":"","value":"x"}
            ],
            "tree":[{"type":"group","id":"g1","children":[]}],
            "tree_revision":7})");
    CHECK_EQ(batch.events.size(), 3);  // bogus type + empty id dropped
    CHECK(batch.events[0].is_group());
    CHECK(batch.events[0].visibility_value);
    CHECK_EQ(batch.events[1].rename_value, std::string("L"));
    CHECK(!batch.events[2].is_group());          // node_type default "layer"
    CHECK(!batch.events[2].visibility_value);    // bool(0) -> false
    CHECK(batch.has_structure_change());
    CHECK_EQ(batch.revision, 7);
    // Convenience projections only carry GROUP nodes of that event type.
    CHECK_EQ(batch.group_visibility().size(), 1);
    CHECK(batch.group_visibility().at("g1"));
    CHECK(batch.group_renames().empty());

    // Legacy payload has no events/tree -> empty batch except changes.
    const auto legacy = parse_tree_events(R"({"visibility":{"a":true}})");
    CHECK(legacy.events.empty());
    CHECK(!legacy.has_structure_change());
    CHECK(!legacy.changes.empty());
    // Bad payload -> wholly empty.
    CHECK(parse_tree_events("!!").empty());
}

int main() { return pwb_test::run_all(); }
