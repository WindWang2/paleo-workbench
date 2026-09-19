// UI-13 — pwb_ui_composite Qt-free core semantics smoke.
// Verifies the ported cores construct and answer basic contracts:
// map styles / roles / layer groups / snapping profiles / capture
// specs / stage vocabulary / map-tool state machines / vector layers
// + edit sessions / merge plans / CRS gate / topology service.
// Deeper parity tests land per-area as the slice matures.

#include <pwb/ui_composite/capture_spec.hpp>
#include <pwb/ui_composite/crs_gate.hpp>
#include <pwb/ui_composite/layer_groups.hpp>
#include <pwb/ui_composite/map_styles.hpp>
#include <pwb/ui_composite/map_tools.hpp>
#include <pwb/ui_composite/merge_plan.hpp>
#include <pwb/ui_composite/roles.hpp>
#include <pwb/ui_composite/snapping_profiles.hpp>
#include <pwb/ui_composite/stage_vocabulary.hpp>
#include <pwb/ui_composite/topology_service.hpp>
#include <pwb/ui_composite/vector_layer.hpp>

#include <cstdio>
#include <cstdlib>

namespace {

int failures = 0;

void check(bool ok, const char* what) {
    if (!ok) {
        ++failures;
        std::fprintf(stderr, "FAIL: %s\n", what);
    }
}

}  // namespace

int main() {
    using namespace pwb::ui_composite;

    // --- roles -------------------------------------------------------------
    check(!role_label(std::string(layer_role::kIntegratedFacies)).empty(), "role_label non-empty");
    check(role_is_editable(std::string(layer_role::kIntegratedFacies)),
          "integrated facies editable");

    // --- map styles ---------------------------------------------------------
    check(!style_library().empty(), "style_library non-empty");
    check(!default_style_for("polygon").to_dict().is_null(),
          "default polygon style dict");

    // --- layer groups ---------------------------------------------------------
    check(!system_group_templates().empty(),
          "system_group_templates non-empty");

    // --- snapping profiles -----------------------------------------------------
    const GeologicalCaptureSpec* spec =
        capture_spec_for_role(std::string(layer_role::kIntegratedFacies));
    check(spec != nullptr, "integrated facies capture spec exists");
    if (spec != nullptr && spec->snapping_profile != nullptr) {
        check(!profile_summary(*spec->snapping_profile).empty(),
              "profile_summary non-empty");
    }

    // --- stage vocabulary ---------------------------------------------------------
    check(!stage_context_action_ids(
              pwb::tool_policy::MappingStage::FaciesCalibration)
               .empty(),
          "facies-calibration stage actions non-empty");

    // --- vector layer + edit session ----------------------------------------------
    VectorLayer layer("lyr-1", "测试层", "EPSG:4490");
    check(layer.id() == "lyr-1", "layer id");
    VectorEditSession& session = layer.start_editing();
    Json polygon = {{"type", "Polygon"},
                    {"coordinates",
                     {{{0.0, 0.0}, {10.0, 0.0}, {10.0, 10.0},
                       {0.0, 10.0}, {0.0, 0.0}}}}};
    session.add_feature(VectorFeature("f-1", polygon, Json::object()));
    check(session.features().size() == 1, "session add_feature");
    check(layer.features().empty(),
          "working copy not committed yet");
    check(session.undo(), "session undo");
    check(session.features().empty(), "undo removes feature");
    check(session.redo(), "session redo");
    check(session.features().size() == 1, "redo restores feature");
    session.commit_changes();
    check(layer.features().size() == 1, "commit writes layer features");
    // _commit parity: commit detaches the session (layer.edit_session =
    // None) — callers must not touch the session object afterwards.
    check(layer.edit_session() == nullptr, "commit detaches session");
    VectorEditSession& second = layer.start_editing();
    second.add_feature(VectorFeature("f-2", polygon, Json::object()));
    check(second.features().size() == 2, "second session add_feature");
    second.rollback_changes();
    check(layer.edit_session() == nullptr, "rollback discards session");
    check(layer.features().size() == 1,
          "rollback restores committed state");

    // --- map tools -----------------------------------------------------------------
    MapToolController tools;
    auto pan = std::make_shared<PanTool>();
    tools.set_active_tool(pan);
    check(tools.active_tool() == pan.get(), "pan active");
    check(tools.active_tool_id() == "pan", "active tool id");
    // Native-session placeholder parity (M1): a capture tool armed with
    // session=nullptr must fail safely instead of dereferencing null.
    AddPointTool add_point(nullptr,
                           [](const MapPoint& p) { return p; },
                           Json::object(), nullptr);
    check(!add_point.mouse_press(MapPoint{5.0, 5.0}, "left", {}),
          "null-session point finish fails");
    check(!add_point.commit_geometry(
              Json{{"type", "Point"}, {"coordinates", {5.0, 5.0}}}),
          "null-session commit_geometry fails");

    // --- topology service -----------------------------------------------------------
    TopologyService topology;
    // No validator injected -> bridge-absent parity reports
    // validator_unavailable (not a silent zero).
    check(topology.refresh_error_count(layer) == 1,
          "missing validator reports unavailable");
    topology.set_validate_fn(
        [](const Json&) { return std::vector<std::string>{}; });
    check(topology.refresh_error_count(layer) == 0,
          "clean layer error_count 0");

    // --- merge plan ------------------------------------------------------------------
    check(polygon_area(polygon) > 0.0, "polygon_area positive");

    // --- CRS gate ----------------------------------------------------------------------
    CrsDomainCheck domain = validate_crs_domain("EPSG:4490", std::nullopt);
    check(domain.ok, "projected CRS without bounds ok");

    if (failures == 0) {
        std::puts("ui_composite.core: all checks passed");
        return EXIT_SUCCESS;
    }
    std::fprintf(stderr, "ui_composite.core: %d failures\n", failures);
    return EXIT_FAILURE;
}
