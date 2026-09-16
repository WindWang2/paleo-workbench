// data.workspace_codec — membership/stage/binding fallbacks and codec
// round-trip (test-plan.md §2, row 5; contracts.md §5).
#include "compare_json.hpp"
#include "pwb_test.hpp"

#include "pwb/workspace/state.hpp"

namespace {

using pwb::domain::Json;
using pwb::workspace::MappingWorkspaceState;

Json sample_workspace() {
    return Json::parse(R"({
        "schema_version": 1,
        "current_stage": "no_such_stage",
        "stage_states": {
            "facies_calibration": {
                "stage": "facies_calibration",
                "group_visibility": {"g1": true, "g2": null},
                "layer_opacity": {"l1": 0.5, "l2": null},
                "active_layer_id": "layer_a",
                "customized": true
            }
        },
        "memberships": {
            "layer_a": {"role": "", "source_version_id": "ver_1",
                        "source_asset_id": "asset_1"},
            "layer_b": {"role": "fault", "binding_kind": "catalog_version",
                        "source_version_id": "ver_2",
                        "source_asset_id": "asset_1"},
            "layer_c": {"role": "horizon",
                        "binding_kind": "content_fingerprint"}
        },
        "tree": {"order": ["layer_a"]},
        "artifact_maturity": {"m1": "frozen", "m2": "moldy"},
        "compilation_input_set": {"s1": "ver_9"},
        "future_key": {"nested": 1}
    })");
}

}  // namespace

PWB_TEST(stage_and_role_fallbacks) {
    pwb::domain::DiagnosticList diagnostics;
    MappingWorkspaceState state =
        MappingWorkspaceState::from_json(sample_workspace(), diagnostics);
    // Unknown current stage falls back (Python stage_state parity).
    PWB_CHECK(state.current_stage == "facies_calibration");
    // Empty role falls back; explicit role survives.
    PWB_CHECK(state.memberships.at("layer_a").role ==
              "legacy_unclassified");
    PWB_CHECK(state.memberships.at("layer_b").role == "fault");
    // Unknown/absent binding kind is stored verbatim as "".
    PWB_CHECK(state.memberships.at("layer_a").binding_kind.empty());
    PWB_CHECK(state.memberships.at("layer_b").binding_kind ==
              "catalog_version");
    // Pre-V13 pinned record reads as catalog_version (interpretation only).
    PWB_CHECK(pwb::workspace::effective_binding_kind(
                  state.memberships.at("layer_a")) == "catalog_version");
    PWB_CHECK(pwb::workspace::effective_binding_kind(
                  state.memberships.at("layer_c")) == "content_fingerprint");
}

PWB_TEST(stage_states_always_seeded) {
    pwb::domain::DiagnosticList diagnostics;
    MappingWorkspaceState state =
        MappingWorkspaceState::from_json(sample_workspace(), diagnostics);
    // Python __post_init__ parity: all three STAGE_ORDER stages present.
    PWB_CHECK(state.stage_states.size() == 3);
    PWB_CHECK(state.stage_states.count("constraint_factor") == 1);
    PWB_CHECK(state.stage_states.count("integrated_compilation") == 1);
}

PWB_TEST(maturity_vocab_drop_and_diagnostic) {
    pwb::domain::DiagnosticList diagnostics;
    MappingWorkspaceState state =
        MappingWorkspaceState::from_json(sample_workspace(), diagnostics);
    PWB_CHECK(state.artifact_maturity.count("m1") == 1);
    PWB_CHECK(state.artifact_maturity.count("m2") == 0);
    bool found = false;
    for (const auto& diagnostic : diagnostics) {
        if (diagnostic.code == "workspace_unknown_maturity") found = true;
    }
    PWB_CHECK(found);
}

PWB_TEST(tristate_and_opacity_rules) {
    pwb::domain::DiagnosticList diagnostics;
    MappingWorkspaceState state =
        MappingWorkspaceState::from_json(sample_workspace(), diagnostics);
    const auto& view = state.stage_states.at("facies_calibration");
    PWB_CHECK(view.group_visibility.at("g1").has_value());
    PWB_CHECK(*view.group_visibility.at("g1") == true);
    PWB_CHECK(!view.group_visibility.at("g2").has_value());
    PWB_CHECK(view.active_layer_id.has_value());
    PWB_CHECK(*view.active_layer_id == "layer_a");
    PWB_CHECK(view.customized);
    // Null opacity never reaches the file (Python to_dict parity).
    const Json dict = state.to_json();
    PWB_CHECK(dict["stage_states"]["facies_calibration"]["layer_opacity"]
                  .count("l2") == 0);
    PWB_CHECK(dict["stage_states"]["facies_calibration"]["layer_opacity"]
                  ["l1"] == 0.5);
}

PWB_TEST(extra_keys_preserved) {
    pwb::domain::DiagnosticList diagnostics;
    MappingWorkspaceState state =
        MappingWorkspaceState::from_json(sample_workspace(), diagnostics);
    const Json dict = state.to_json();
    PWB_CHECK(dict["future_key"]["nested"] == 1);
    PWB_CHECK(dict["tree"]["order"][0] == "layer_a");
    PWB_CHECK(dict["compilation_input_set"]["s1"] == "ver_9");
}

PWB_TEST(codec_roundtrip_stable) {
    pwb::domain::DiagnosticList first;
    MappingWorkspaceState state =
        MappingWorkspaceState::from_json(sample_workspace(), first);
    const Json once = state.to_json();
    pwb::domain::DiagnosticList second;
    MappingWorkspaceState again =
        MappingWorkspaceState::from_json(once, second);
    const auto diff = pwb_test::json_compare(once, again.to_json());
    PWB_CHECK(!diff.has_value());
}

PWB_TEST(catalog_bindings_filter) {
    pwb::domain::DiagnosticList diagnostics;
    MappingWorkspaceState state =
        MappingWorkspaceState::from_json(sample_workspace(), diagnostics);
    const auto bindings = state.catalog_bindings();
    // Effective-kind semantics (V13): explicit catalog_version (layer_b)
    // plus pinned-but-unlabeled pre-V13 records (layer_a); the
    // content_fingerprint binding (layer_c) is excluded.
    PWB_CHECK(bindings.size() == 2);
    PWB_CHECK(bindings[0].layer_id == "layer_a");
    PWB_CHECK(bindings[1].layer_id == "layer_b");
}
