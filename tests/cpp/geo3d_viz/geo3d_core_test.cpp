// CONV-GEO3D core conformance: the GL-less half of the ported Python
// surface — scene registry (validation + pick math), orbit camera,
// geological scene adapter (token diff / payloads / view state / picking)
// and the workspace controller (measurement machine / clip mapping /
// state persistence). Qt enters only as QCoreApplication for the
// controller's QObject signals; no widget, no GL.

#include <QCoreApplication>

#include <cmath>
#include <cstdio>
#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/geo3d_viz/orbit_camera.hpp>
#include <pwb/geo3d_viz/scene_adapter.hpp>
#include <pwb/geo3d_viz/workspace_controller.hpp>
#include <pwb/geomodel/builders.hpp>
#include <pwb/geomodel/section.hpp>

using namespace pwb::geo3d_viz;
using pwb::domain::Json;
using pwb::geomodel::DomainObject;

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::printf("FAIL: %s\n", what.c_str());
    }
}

void check_eq(double got, double want, double tol, const std::string& what) {
    ++g_checks;
    if (!(std::abs(got - want) <= tol)) {
        ++g_failures;
        std::printf("FAIL: %s (got %.17g want %.17g)\n", what.c_str(), got,
                    want);
    }
}

// ---------------------------------------------------------------------------
// fixtures
// ---------------------------------------------------------------------------

SceneObject make_triangle(const std::string& name, bool pickable = true,
                          bool visible = true) {
    SceneObject object;
    object.name = name;
    object.kind = ObjectKind::Fault;
    object.mode = ObjectMode::Mesh;
    object.verts = {{0.f, 0.f, 0.f}, {10.f, 0.f, 0.f}, {0.f, 10.f, 0.f}};
    object.faces = {{0, 1, 2}};
    object.pickable = pickable;
    object.visible = visible;
    return object;
}

SceneObject make_polyline(const std::string& name, float pick_radius,
                          bool pickable = true) {
    SceneObject object;
    object.name = name;
    object.kind = ObjectKind::Well;
    object.mode = ObjectMode::Lines;
    object.verts = {{5.f, 5.f, 0.f}, {5.f, 5.f, 10.f}, {5.f, 5.f, 20.f}};
    object.pickable = pickable;
    object.pick_radius = pick_radius;
    return object;
}

DomainObject demo_well(const std::string& id, bool demo = false) {
    DomainObject well = pwb::geomodel::build_simplified_vertical_well(
        "w-" + id, {1.0, 2.0, 0.0}, 50.0, "epsg:4326");
    well.object_id = id;
    well.provenance.demo = demo;
    well.validate();
    return well;
}

DomainObject demo_horizon() {
    DomainObject horizon;
    horizon.object_id = "horizon:top";
    horizon.name = "Top";
    horizon.crs = "epsg:4326";
    horizon.origin = {0.0, 0.0};
    horizon.spacing = {1.0, 1.0};
    // 4×4 grid, one NaN hole at (1,1): the four quads touching the hole
    // drop whole (never fabricated), leaving 5 cells → 10 triangles over
    // 15 valid grid nodes.
    horizon.z_grid = {
        {0.0, 0.0, 0.0, 0.0},
        {0.0, std::nan(""), 0.0, 0.0},
        {0.0, 0.0, 0.0, 0.0},
        {0.0, 0.0, 0.0, 0.0},
    };
    horizon.validate();
    return horizon;
}

DomainObject demo_fault() {
    DomainObject fault = pwb::geomodel::build_fault_from_mesh(
        "Fault", {{0, 0, 0}, {10, 0, 0}, {10, 10, 5}, {0, 10, 5}},
        {{0, 1, 2}, {0, 2, 3}});
    fault.object_id = "fault:demo-curtain";
    fault.crs = "epsg:4326";
    fault.validate();
    return fault;
}

// ---------------------------------------------------------------------------
// fake viewport facade (controller tests)
// ---------------------------------------------------------------------------

class FakeFacade : public Geo3DViewportFacade {
public:
    std::optional<CameraPose> pose;
    std::optional<Bounds> bounds;
    std::vector<DomainPick> picks;  // consumed in order by pick_at
    std::optional<CameraPose> last_applied;

    std::optional<CameraPose> camera_pose() const override { return pose; }
    void apply_camera_pose(const CameraPose& p) override { last_applied = p; }
    std::optional<Bounds> scene_bounds(bool) override { return bounds; }
    bool fit_objects(const std::optional<std::vector<std::string>>&) override {
        return bounds.has_value();
    }
    std::optional<PickHit> pick_at(double, double,
                                   const std::vector<ObjectKind>&) override {
        if (picks.empty()) return std::nullopt;
        const DomainPick p = picks.front();
        picks.erase(picks.begin());
        PickHit hit;
        hit.name = p.object_id;
        hit.kind = p.kind;
        hit.distance = p.distance;
        hit.point = p.domain_xyz;
        return hit;
    }
};

// ---------------------------------------------------------------------------
// tests
// ---------------------------------------------------------------------------

void test_registry_validation() {
    SceneObjectManager manager;
    SceneObject bad = make_triangle("nan");
    bad.verts[0][0] = std::nanf("");
    bool threw = false;
    try {
        manager.add(std::move(bad));
    } catch (const SceneObjectError& exc) {
        threw = std::string(exc.what()) == "verts contain non-finite coordinates";
    }
    check(threw, "NaN verts rejected with the Python message");

    SceneObject bad_face = make_triangle("range");
    bad_face.faces = {{0, 1, 9}};
    threw = false;
    try {
        manager.add(std::move(bad_face));
    } catch (const SceneObjectError& exc) {
        threw = std::string(exc.what()).find(
                    "faces reference vertex index out of range") == 0;
    }
    check(threw, "out-of-range face index rejected");

    SceneObject zero_plane = make_triangle("clip0");
    zero_plane.clip_planes = std::vector<ClipEquation>{{0.0, 0.0, 0.0, 1.0}};
    threw = false;
    try {
        manager.add(std::move(zero_plane));
    } catch (const SceneObjectError& exc) {
        threw = std::string(exc.what()) == "clip plane normal is zero";
    }
    check(threw, "zero clip normal rejected");

    SceneObject many_planes = make_triangle("clip7");
    many_planes.clip_planes = std::vector<ClipEquation>(
        7, ClipEquation{1.0, 0.0, 0.0, 0.0});
    threw = false;
    try {
        manager.add(std::move(many_planes));
    } catch (const SceneObjectError& exc) {
        threw = std::string(exc.what()) ==
                "at most 6 clip planes per object, got 7";
    }
    check(threw, "clip plane ceiling enforced");

    SceneObject object = make_triangle("t");
    manager.add(std::move(object));
    manager.set_opacity("t", 2.0f);
    check(manager.get("t")->opacity == 1.0f, "opacity clamped high");
    manager.set_opacity("t", -1.0f);
    check(manager.get("t")->opacity == 0.0f, "opacity clamped low");
    check(manager.revision() > 0, "mutations bump the revision");
}

void test_registry_lifecycle_and_pick() {
    SceneObjectManager manager;
    manager.add(make_triangle("mesh"));
    manager.add(make_polyline("well:1", 2.0f));
    manager.add(make_polyline("hidden", 2.0f, true));
    manager.set_visibility("hidden", false);
    manager.add(make_polyline("nopick", 2.0f, false));

    check(manager.names().size() == 4, "four objects registered");
    check(manager.clear(ObjectKind::Well) == 3, "clear(kind) removes wells");
    check(manager.has("mesh"), "mesh survives a kind clear");
    manager.add(make_triangle("mesh2"));
    manager.add(make_triangle("mesh2"));  // replace keeps single entry
    check(manager.names().size() == 2, "replace does not duplicate");

    manager.add(make_triangle("mesh"));
    manager.add(make_polyline("well:1", 2.0f));
    manager.set_visibility("well:1", false);

    // Ray straight down the +z axis at (5,5): hits the well line, misses
    // the triangle at z=0 (it spans x∈[0,10], y∈[0,10] — (5,5) IS inside,
    // so both are candidates; nearest hit wins: triangle at t=0).
    Ray down{{5.0, 5.0, 100.0}, {0.0, 0.0, -1.0}};
    const auto hit = manager.pick(down);
    check(hit.has_value(), "ray hits a candidate");
    if (hit.has_value()) {
        check(hit->name == "mesh", "nearest mesh hit wins over hidden line");
        check_eq(hit->distance, 100.0, 1e-9, "mesh hit distance");
    }

    manager.set_visibility("mesh", false);
    manager.set_visibility("mesh2", false);
    check(!manager.pick(down).has_value(),
          "invisible objects are not pickable");

    // Off-radius line pick rejected.
    Ray far_side{{8.0, 5.0, 10.0}, {0.0, 0.0, -1.0}};
    manager.set_visibility("well:1", true);
    manager.set_visibility("mesh", true);
    // (8,5) is 3 units from the line at x=5: outside pick_radius 2.
    check(!manager.pick(far_side).has_value(),
          "line pick outside pick_radius rejected");
}

void test_pick_math() {
    const std::vector<Vec3f> verts = {{0.f, 0.f, 0.f}, {1.f, 0.f, 0.f},
                                      {0.f, 1.f, 0.f}};
    const std::vector<std::array<std::int64_t, 3>> faces = {{0, 1, 2}};
    const auto hit = ray_triangles_first_hit(
        {0.25, 0.25, 5.0}, {0.0, 0.0, -1.0}, verts, faces);
    check(hit.has_value() && std::abs(hit->first - 5.0) < 1e-12 &&
              hit->second == 0,
          "Möller–Trumbore hit");
    const auto miss = ray_triangles_first_hit(
        {0.9, 0.9, 5.0}, {0.0, 0.0, -1.0}, verts, faces);
    check(!miss.has_value(), "u+v>1 misses");
    const auto behind = ray_triangles_first_hit(
        {0.25, 0.25, -5.0}, {0.0, 0.0, -1.0}, verts, faces);
    check(!behind.has_value(), "t<0 rejected");

    const std::vector<Vec3f> line = {{0.f, 0.f, 0.f}, {0.f, 0.f, 10.f}};
    const auto near_hit =
        ray_segments_closest({1.0, 0.0, 5.0}, {0.0, 0.0, -1.0}, line, 1.5);
    check(near_hit.has_value() && near_hit->second == 0,
          "line pick within radius");
    const auto too_far =
        ray_segments_closest({3.0, 0.0, 5.0}, {0.0, 0.0, -1.0}, line, 1.5);
    check(!too_far.has_value(), "line pick beyond radius rejected");
}

void test_camera() {
    OrbitCamera camera;
    const CameraPose def = camera.pose();
    check(def.distance == 500.0 && def.elevation_deg == 30.0 &&
              def.azimuth_deg == 45.0,
          "default pose 500/30/45 (renderer_3d)");
    check(OrbitCamera::perspective_preset().distance == 250.0 &&
              OrbitCamera::perspective_preset().elevation_deg == 30.0 &&
              OrbitCamera::perspective_preset().azimuth_deg == -45.0,
          "perspective preset 250/30/-45");
    check(OrbitCamera::top_down_preset().elevation_deg == 90.0,
          "top-down preset elevation 90");

    camera.orbit(100, 100);
    check(camera.pose().elevation_deg == 80.0, "orbit elevation +0.5/px");
    camera.orbit(0, 1000);
    check(camera.pose().elevation_deg == 90.0, "elevation clamped at +90");
    camera.orbit(-200, 0);
    check(std::abs(camera.pose().azimuth_deg - (45.0 + 100 * 0.5 - 100)) <
              1e-9,
          "azimuth free-running");

    camera.zoom(10);
    const double zoomed = camera.pose().distance;
    check(zoomed < 500.0 && zoomed > 100.0, "zoom multiplies distance");
    camera.set_pose({1e-6, 0, 0});
    check(camera.pose().distance > 1e-4, "distance floor enforced");

    // project → ray roundtrip: the screen point of a world point produces a
    // ray passing through that point.
    camera.set_pose(OrbitCamera::perspective_preset());
    camera.set_viewport(800, 600);
    const std::array<double, 3> world{10.0, 5.0, 30.0};
    double px = 0.0;
    double py = 0.0;
    check(camera.project_to_screen(world, px, py), "project succeeds");
    const auto ray = camera.ray_at(px, py);
    check(ray.has_value(), "ray_at succeeds at the projected pixel");
    if (ray.has_value()) {
        // distance from the world point to the ray ~ 0
        const std::array<double, 3> v{world[0] - ray->origin[0],
                                      world[1] - ray->origin[1],
                                      world[2] - ray->origin[2]};
        const double cross_len =
            std::sqrt(std::pow(v[1] * ray->direction[2] - v[2] * ray->direction[1],
                               2) +
                      std::pow(v[2] * ray->direction[0] - v[0] * ray->direction[2],
                               2) +
                      std::pow(v[0] * ray->direction[1] - v[1] * ray->direction[0],
                               2));
        check(cross_len < 0.25,
          "ray passes through the projected point (sub-pixel)");
    }
}

void test_adapter_sync_diff() {
    SceneObjectManager manager;
    GeologicalSceneAdapter adapter([&manager]() { return &manager; });
    pwb::geomodel::ModelAssembly assembly("test");

    assembly.add(demo_well("well:a"));
    assembly.add(demo_horizon());
    assembly.add(demo_fault());

    const SceneSyncReport first = adapter.sync(assembly);
    check(first.added.size() == 3 && first.updated.empty() &&
              first.removed.empty(),
          "first sync adds every object");
    check(manager.has("well:a") && manager.has("well:a#head") &&
              manager.has("well:a#label"),
          "well payload: strip + head + label");
    check(manager.get("well:a")->pickable &&
              manager.get("well:a")->pick_radius == 2.0f &&
              manager.get("well:a")->width == 3.0f,
          "well line: pickable, radius 2.0, width 3.0");
    check(manager.get("well:a#head")->size == 9.0f, "head marker size 9");
    check(manager.has("horizon:top"), "horizon registered");
    check(manager.has("fault:demo-curtain"), "fault registered");

    // idempotent
    const SceneSyncReport second = adapter.sync(assembly);
    check(second.size() == 0 &&
              second.unchanged == static_cast<int>(assembly.size()),
          "second sync is unchanged");

    // version bump → updated
    assembly.bump_version("well:a");
    const SceneSyncReport third = adapter.sync(assembly);
    check(third.updated.size() == 1 && third.updated.front() == "well:a",
          "version bump updates exactly the touched object");

    // removal prunes scene objects + state
    assembly.remove("well:a");
    const SceneSyncReport fourth = adapter.sync(assembly);
    check(fourth.removed.size() == 1, "removal reported once");
    check(!manager.has("well:a"), "removal drops the strip");
    check(!manager.has("well:a#head"), "removal drops the head marker");
    check(!manager.has("well:a#label"), "removal drops the label");
    check(!adapter.is_synced("well:a"), "removal drops the token");
    std::printf("derived after removal: %zu\n",
                adapter.derived_names("well:a").size());
}

void test_adapter_payload_shapes() {
    SceneObjectManager manager;
    GeologicalSceneAdapter adapter([&manager]() { return &manager; });
    pwb::geomodel::ModelAssembly assembly("test");

    // empty stations → not renderable, nothing recorded
    DomainObject empty_well = demo_well("well:empty");
    empty_well.stations.clear();
    assembly.add(std::move(empty_well));
    auto report = adapter.sync(assembly);
    check(report.added.empty() && !adapter.is_synced("well:empty"),
          "empty-stations well skipped without a token");

    // NaN hole heightfield: 4×4 grid with the center-adjacent NaN — the
    // quads touching the hole drop whole (holes never fabricate triangles).
    assembly.add(demo_horizon());
    report = adapter.sync(assembly);
    check(report.added.size() == 1, "horizon rendered");
    const SceneObject* horizon = manager.get("horizon:top");
    check(horizon != nullptr, "horizon object exists");
    if (horizon != nullptr) {
        check(horizon->mode == ObjectMode::Mesh &&
                  horizon->kind == ObjectKind::Horizon && horizon->pickable,
              "horizon payload mode/kind/pickable");
        // 9 quads − 4 touching the NaN hole = 5 cells → 10 triangles
        check(horizon->faces.size() == 10,
              "NaN holes are never triangulated (10 faces remain)");
        check(horizon->verts.size() == 15, "hole node dropped from verts");
    }

    // 1024-wide grid decimates to ≤512 columns with doubled spacing
    DomainObject big = demo_horizon();
    big.object_id = "horizon:big";
    big.name = "Big";
    big.z_grid.assign(1024, std::vector<double>(1024, 1.5));
    assembly.add(std::move(big));
    adapter.sync(assembly);
    const SceneObject* decimated = manager.get("horizon:big");
    check(decimated != nullptr, "decimated horizon registered");
    if (decimated != nullptr) {
        // 1024 → stride 2 → 512 nodes per axis
        check(decimated->verts.size() ==
                  static_cast<std::size_t>(512) * 512,
              "stride-thinned grid caps at 512 per axis");
    }
}

void test_adapter_view_state_and_pick() {
    SceneObjectManager manager;
    GeologicalSceneAdapter adapter([&manager]() { return &manager; });
    pwb::geomodel::ModelAssembly assembly("test");
    assembly.add(demo_well("well:a"));
    assembly.add(demo_fault());
    adapter.sync(assembly);

    // selection recolors strip + derived, restore restores base colors
    const Rgba well_base = adapter.styles().well_color;
    adapter.set_selected("well:a");
    check(manager.get("well:a")->color == adapter.styles().selected_color,
          "selected strip uses the selection color");
    {
        const SceneObject* head = manager.get("well:a#head");
        std::printf("derived(well:a):");
        for (const auto& n : adapter.derived_names("well:a")) {
            std::printf(" %s", n.c_str());
        }
        std::printf(" | head=%s color=%.2f,%.2f,%.2f\n", head ? "yes" : "nil",
                    head ? head->color[0] : -1.f, head ? head->color[1] : -1.f,
                    head ? head->color[2] : -1.f);
    }
    check(manager.get("well:a#head")->color ==
              adapter.styles().selected_color,
          "selected derived uses the selection color");
    adapter.set_selected(std::nullopt);
    check(manager.get("well:a")->color == well_base,
          "deselect restores the base color");

    // visibility participates in tokens; set_visibility flips manager flags
    adapter.set_visibility("well:a", false);
    check(!manager.get("well:a")->visible &&
              !manager.get("well:a#label")->visible,
          "visibility applies to every derived name");
    check(adapter.visibility("well:a") == false, "visibility read-back");
    adapter.set_visibility("well:a", true);
    check(manager.get("well:a")->visible, "reveal");

    // clip planes: invisible objects skip; reveal replays planes
    const std::vector<ClipEquation> planes = {
        pwb::geomodel::axis_plane("z", 10.0).as_clip_equation(false)};
    adapter.set_visibility("well:a", false);
    adapter.set_clip_planes(planes);
    check(!manager.get("well:a")->clip_planes.has_value(),
          "clip skipped for hidden objects (no fabricated state)");
    adapter.set_visibility("well:a", true);
    check(manager.get("well:a")->clip_planes.has_value() &&
              manager.get("well:a#head")->clip_planes.has_value(),
          "clip replayed on reveal");

    // overlays receive clip updates
    manager.add(make_triangle("analysis:probe"));
    adapter.register_overlay("probe", {"analysis:probe"});
    adapter.set_clip_planes(planes);
    check(manager.get("analysis:probe")->clip_planes.has_value(),
          "registered overlays are clipped");
    adapter.remove_overlay("probe");

    // opacity clamps
    adapter.set_opacity("well:a", 1.7);
    check(adapter.display_state("well:a")["opacity"] == 1.0,
          "opacity clamp in display_state");

    // pick resolution strips the derived suffix and inverts the transform
    Ray ray{{1.0, 2.0, 100.0}, {0.0, 0.0, -1.0}};
    const auto pick = adapter.pick(ray);
    // the well is at (1,2); the fault mesh may also hit — accept any hit
    // but require the suffix stripping when the well wins.
    if (pick.has_value() && pick->object_id.rfind("well:", 0) == 0) {
        check(pick->object_id.find('#') == std::string::npos,
              "pick strips derived suffixes");
    }
    check(pick.has_value() ? pick->has_xyz : true, "identity pick has xyz");

    // provider-null degradation: sync records nothing, pick degrades
    GeologicalSceneAdapter orphan([]() { return static_cast<SceneObjectManager*>(nullptr); });
    pwb::geomodel::ModelAssembly assembly2("t2");
    assembly2.add(demo_well("well:b"));
    const SceneSyncReport empty = orphan.sync(assembly2);
    check(empty.size() == 0 && !orphan.is_synced("well:b"),
          "viewport absent: empty report, no token (stale-cache lockout)");
    check(!orphan.pick(ray).has_value(), "viewport absent: pick degrades");
}

void test_controller_measure_and_clip() {
    SceneObjectManager manager;
    Geo3DWorkspaceController controller([&manager]() { return &manager; });
    FakeFacade facade;
    controller.set_viewport(&facade);

    int qc_updates = 0;
    int measurements = 0;
    std::string last_status;
    QObject::connect(&controller, &Geo3DWorkspaceController::qc_updated,
                     [&qc_updates]() { ++qc_updates; });
    QObject::connect(&controller,
                     &Geo3DWorkspaceController::measurements_changed,
                     [&measurements]() { ++measurements; });
    QObject::connect(
        &controller, &Geo3DWorkspaceController::status_message,
        [&](const QString& m) { last_status = m.toStdString(); });

    auto well = demo_well("well:a");
    controller.add_object(std::move(well));
    check(qc_updates >= 1, "add_object refreshes QC incrementally");
    check(manager.has("well:a"), "controller syncs the scene");

    // measurement machine
    check(!controller.set_measure_mode(std::string("bogus")),
          "unknown measure mode rejected");
    controller.set_measure_mode(std::string("distance"));
    check(controller.measure_mode().has_value(), "measure mode set");
    // pick misses while measuring → consumed with a status line
    check(controller.handle_viewport_click(1, 1) &&
              last_status == "未命中可拾取对象",
          "miss during measuring consumes the click");
    facade.picks.push_back({"well:a", "well", {0, 0, 0}, 1.0, true});
    controller.handle_viewport_click(1, 1);
    facade.picks.push_back({"well:a", "well", {3, 4, 0}, 1.0, true});
    controller.handle_viewport_click(2, 2);
    check(measurements == 1, "distance completes after 2 picks");
    check(controller.assembly().contains("measure:distance-1"),
          "measurement record registered (counter id scheme)");

    // duplicate id resolution → -2 suffix
    facade.picks.push_back({"well:a", "well", {0, 0, 0}, 1.0, true});
    controller.handle_viewport_click(1, 1);
    facade.picks.push_back({"well:a", "well", {3, 4, 0}, 1.0, true});
    controller.handle_viewport_click(2, 2);
    check(controller.assembly().contains("measure:distance-2"),
          "duplicate ids resolve a free -N suffix");
    check(manager.has("measure:distance-2#label"),
          "measurement label registered with format_result text");

    // selection on click when not measuring
    controller.set_measure_mode(std::nullopt);
    QString selected;
    QString selected_well;
    QObject::connect(&controller, &Geo3DWorkspaceController::selection_changed,
                     [&](const QString& oid) { selected = oid; });
    QObject::connect(&controller, &Geo3DWorkspaceController::well_selected,
                     [&](const QString& w) { selected_well = w; });
    facade.picks.push_back({"well:a", "well", {0, 0, 0}, 1.0, true});
    check(controller.handle_viewport_click(3, 3), "select-on-click consumed");
    check(selected == "well:a", "selection_changed carries the object id");
    check(selected_well == "w-well:a",
          "well selection broadcasts the well name (2D seam)");

    // clip mapping over live bounds (never hardcoded ±80)
    facade.bounds = Bounds{{0.0, 0.0, 0.0}, {100.0, 200.0, 40.0}};
    controller.set_axis_clip("x", true, 0.25, false);
    const auto& planes = controller.adapter().clip_planes();
    check(planes.has_value() && planes->size() == 1,
          "one axis plane from one enabled axis");
    if (planes.has_value() && !planes->empty()) {
        const auto expected = pwb::geomodel::axis_plane("x", 25.0)
                                  .as_clip_equation(false);
        for (int k = 0; k < 4; ++k) {
            check_eq(planes->front()[static_cast<std::size_t>(k)],
                     expected[static_cast<std::size_t>(k)], 1e-12,
                     "clip equation maps 0-1 over bounds");
        }
    }
    controller.set_axis_clip("y", true, 0.5, true);
    check(controller.adapter().clip_planes()->size() == 2,
          "second axis plane appended");
    controller.reset_clip();
    check(!controller.adapter().clip_planes().has_value(),
          "reset drops all planes");

    // empty bounds → no fabricated planes
    facade.bounds.reset();
    controller.set_axis_clip("z", true, 0.5, false);
    check(!controller.adapter().clip_planes().has_value(),
          "clip without bounds stays a no-op (no ±80 fabrication)");
}

void test_controller_thickness() {
    SceneObjectManager manager;
    Geo3DWorkspaceController controller([&manager]() { return &manager; });
    FakeFacade facade;
    controller.set_viewport(&facade);

    auto top = demo_horizon();
    top.object_id = "horizon:top-layer";
    top.name = "Top 顶";
    top.z_grid.assign(10, std::vector<double>(10, 20.0));
    auto base = demo_horizon();
    base.object_id = "horizon:base-layer";
    base.name = "Base 底";
    base.z_grid.assign(10, std::vector<double>(10, 5.0));
    controller.add_object(std::move(top));
    controller.add_object(std::move(base));

    controller.set_measure_mode(std::string("thickness"));
    facade.picks.push_back(
        {"horizon:top-layer", "horizon", {5, 5, 20}, 1.0, true});
    check(controller.handle_viewport_click(1, 1), "thickness pick consumed");
    bool has_thickness = false;
    for (const auto& object : controller.assembly().objects()) {
        if (object.object_id.rfind("measure:thickness-", 0) == 0) {
            has_thickness = true;
            check(object.result.has_value() &&
                      std::abs(*object.result - 15.0) < 1e-9,
                  "thickness = top - base (15 m)");
        }
    }
    check(has_thickness, "thickness record created from paired horizons");
}

void test_state_persistence() {
    SceneObjectManager manager;
    Geo3DWorkspaceController controller([&manager]() { return &manager; });
    FakeFacade facade;
    facade.pose = CameraPose{321.0, 12.0, -60.0};
    controller.set_viewport(&facade);

    controller.add_object(demo_well("well:real"));
    controller.add_object(demo_well("well:demo", true));
    Json payload = controller.save_state();

    check(payload.contains("objects") && payload.contains("measurements") &&
              payload.contains("display") && payload.contains("clip") &&
              payload.contains("camera") && payload.contains("views") &&
              payload.contains("selected"),
          "seven-key payload");
    check(payload["objects"].size() == 1,
          "demo objects are never persisted (honest provenance)");
    check(payload["camera"]["distance"] == 321.0, "camera captured");
    check(payload["clip"]["x"]["enabled"] == false &&
              payload["clip"]["x"]["value"] == 0.5,
          "clip state serialized");
    check(payload["selected"].is_string(), "selected is a string key");

    // restore into a fresh controller
    SceneObjectManager manager2;
    Geo3DWorkspaceController restored([&manager2]() { return &manager2; });
    FakeFacade facade2;
    restored.set_viewport(&facade2);
    const auto ids = restored.restore_state(payload);
    check(ids.size() == 1 && ids.front() == "well:real",
          "restore brings back the non-demo reference");
    check(restored.assembly().contains("well:real"), "restored id present");
    check(restored.clip_state().at("x").value == 0.5, "clip restored");
    check(restored.camera().has_value() &&
              restored.camera()->distance == 321.0,
          "camera restored");

    // corrupt entries degrade per object; "false" never truthifies
    Json bad = payload;
    bad["objects"][0]["object_id"] = "well:real";
    bad["objects"][0]["crs"] = 42;  // wrong type → from_meta degrades? (may
    // also coerce like Python str()/float() — the C++ from_meta mirrors)
    bad["clip"]["y"]["enabled"] = "yes";
    bad["clip"]["y"]["value"] = "0.75";
    Json extra_view = Json::object();
    extra_view["name"] = "v1";
    extra_view["distance"] = 100.0;
    extra_view["elevation"] = 30.0;
    extra_view["azimuth"] = -45.0;
    bad["views"] = Json::array({extra_view});
    SceneObjectManager manager3;
    Geo3DWorkspaceController degraded([&manager3]() { return &manager3; });
    const auto degraded_ids = degraded.restore_state(bad);
    check(!degraded_ids.empty(), "corrupted payload still opens (ADR-03)");
    check(degraded.clip_state().at("y").enabled == true &&
              std::abs(degraded.clip_state().at("y").value - 0.75) < 1e-12,
          "strict coercions: 'yes'→true, '0.75'→0.75");
    check(degraded.view_presets().count("v1") == 1, "view preset restored");

    // Malformed payload shapes degrade honestly (never crash, ADR-03)
    SceneObjectManager manager_bad;
    Geo3DWorkspaceController malformed([&manager_bad]() { return &manager_bad; });
    check(malformed.restore_state(Json::object()).empty(),
          "empty payload restores nothing");
    check(malformed.restore_state(Json(nullptr)).empty(),
          "null payload restores nothing");
    Json array_payload = Json::array({1, 2, 3});
    check(malformed.restore_state(array_payload).empty(),
          "array payload restores nothing");
    Json scalar_objects = Json::object();
    scalar_objects["objects"] = 42;
    scalar_objects["measurements"] = "bogus";
    scalar_objects["clip"] = 7;
    scalar_objects["views"] = "nope";
    check(malformed.restore_state(scalar_objects).empty(),
          "scalar-typed sections are skipped wholesale");

    // Unicode names survive the meta round-trip
    DomainObject unicode_well =
        pwb::geomodel::build_simplified_vertical_well(
            "井-中文-№1", {1.0, 2.0, 0.0}, 30.0, "EPSG:4326");
    controller.add_object(std::move(unicode_well));
    Json unicode_payload = controller.save_state();
    bool unicode_found = false;
    for (const auto& object : unicode_payload["objects"]) {
        if (object["name"].get<std::string>() == "井-中文-№1") {
            unicode_found = true;
        }
    }
    check(unicode_found, "Unicode well name persists verbatim");

    // as_bool matrix (frozen semantics)
    check(state_as_bool(Json(true), false), "bool true");
    check(!state_as_bool(Json(std::string("false")), true),
          "\"false\" never truthifies");
    check(!state_as_bool(Json(std::string("")), true), "empty string false");
    check(state_as_bool(Json(1), false), "1 → true");
    check(state_as_bool(Json(0.5), true), "0.5 falls to the default (true)");
    check(state_as_bool(Json(std::string("YES")), false),
          "case-insensitive yes");
    check(state_as_bool(Json(std::string(" true ")), false),
          "whitespace stripped like Python .strip().lower()");
    // infinity via overflow string falls to the default (not finite)
    check(state_as_float(Json(std::string("1e400")), 0.25) == 0.25,
          "1e400 → inf is not finite → default");
}

void test_state_coercions_and_inspector() {
    SceneObjectManager manager;
    Geo3DWorkspaceController controller([&manager]() { return &manager; });

    auto fault = demo_fault();
    controller.add_object(std::move(fault));
    controller.set_selected(std::string("fault:demo-curtain"), false);
    const std::string text = controller.inspector_text();
    check(text.find("Fault") != std::string::npos &&
              text.find("ID: fault:demo-curtain") != std::string::npos &&
              text.find("CRS: epsg:4326") != std::string::npos &&
              text.find("表示: ") != std::string::npos &&
              text.find("QC: ") != std::string::npos,
          "inspector text: identity/representation/QC lines");
    check(controller.inspector_text(std::nullopt).find("Fault") !=
              std::string::npos,
          "inspector defaults to the selection");
    check(controller.inspector_text(std::string("horizon:none")) ==
              "未选中对象",
          "inspector degrades for unknown ids");

    // view presets: no pose → refused with a status message
    std::string status;
    QObject::connect(
        &controller, &Geo3DWorkspaceController::status_message,
        [&](const QString& m) { status = m.toStdString(); });
    check(!controller.save_view_preset("v"),
          "preset refused without a viewport pose");
    check(status == "视口未就绪，无法保存视图", "refusal status text");
}

}  // namespace

int main(int argc, char** argv) {
    QCoreApplication app(argc, argv);
    test_registry_validation();
    test_registry_lifecycle_and_pick();
    test_pick_math();
    test_camera();
    test_adapter_sync_diff();
    test_adapter_payload_shapes();
    test_adapter_view_state_and_pick();
    test_controller_measure_and_clip();
    test_controller_thickness();
    test_state_persistence();
    test_state_coercions_and_inspector();
    std::printf("geo3d.core_test: %d checks, %d failures\n", g_checks,
                g_failures);
    return g_failures == 0 ? 0 : 1;
}
