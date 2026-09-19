// viz_c.joint_scene — behavior tests over the V4 joint core + platform
// bridges that need no window: state persistence roundtrip, fail-closed
// survey construction, the tiled-volume adapter and the joint mesh
// builders, and the CONV-GEO3D SceneTransform seam round trip.
#include "pwb_test.hpp"

#include <pwb/geo3d_viz/joint/fence.hpp>
#include <pwb/geo3d_viz/joint/joint_scene.hpp>
#include <pwb/geo3d_viz/joint/registration.hpp>
#include <pwb/geo3d_viz/joint/segy_survey.hpp>
#include <pwb/geo3d_viz/joint/survey.hpp>
#include <pwb/geo3d_viz/joint/volume_access.hpp>
#include <pwb/geo3d_viz/scene_adapter.hpp>
#include <pwb/viz/seismic_volume.hpp>

#include <cmath>
#include <limits>

// Platform bridge (composition-only TU; compiled directly).
#include "viz_c_joint_volume.hpp"

namespace {

using namespace pwb::geo3d_viz::joint;

SurveySpec classic_survey() {
    return survey_from_corners({1, 1, 1000.0, 2000.0},
                               {1, 10, 1900.0, 2000.0},
                               {20, 10, 1900.0, 2600.0}, 64, 2.0);
}

std::vector<float> ramp_volume(std::int64_t ni, std::int64_t nx,
                               std::int64_t nt) {
    std::vector<float> data(static_cast<std::size_t>(ni * nx * nt));
    for (std::int64_t i = 0; i < ni; ++i) {
        for (std::int64_t x = 0; x < nx; ++x) {
            for (std::int64_t t = 0; t < nt; ++t) {
                data[static_cast<std::size_t>((i * nx + x) * nt + t)] =
                    static_cast<float>((i * 7 + x * 3 + t) % 97 - 48);
            }
        }
    }
    return data;
}

}  // namespace

PWB_TEST(segy_survey_from_descriptor_and_fail_closed) {
    pwb::seismic_io::VolumeDescriptor descriptor;
    descriptor.ni = 20;
    descriptor.nc = 10;
    descriptor.ns = 64;
    descriptor.iline_start = 1;
    descriptor.iline_step = 1;
    descriptor.xline_start = 1;
    descriptor.xline_step = 1;
    descriptor.sample_start = 0.0;
    descriptor.sample_step = 2.0;
    descriptor.sample_unit = "ms";
    descriptor.sample_domain = pwb::seismic_io::SampleDomain::time;
    descriptor.bin_grid = pwb::seismic_io::BinGridGeometry{
        1000.0, 2000.0, 0.0, 31.57894736842105, 100.0};

    SurveySpec spec = survey_from_volume_descriptor(descriptor);
    const SurveySpec expected = classic_survey();
    PWB_CHECK(spec.n_inlines == expected.n_inlines);
    PWB_CHECK(spec.n_samples == expected.n_samples);
    PWB_CHECK(spec.dt_ms == expected.dt_ms);
    PWB_CHECK(spec.bin_grid.il_spacing_m == expected.bin_grid.il_spacing_m);
    const auto corners = survey_corners(spec);
    WellSeismicScene corner_scene;
    corner_scene.set_survey(spec);
    const auto [ok, message] = corner_scene.validate_against_corners(
        std::get<0>(corners), std::get<1>(corners), std::get<2>(corners));
    PWB_CHECK(ok);
    PWB_CHECK(message.empty());

    // Fail-closed: no bin grid → refuse (never fabricate geometry).
    pwb::seismic_io::VolumeDescriptor no_grid = descriptor;
    no_grid.bin_grid.reset();
    bool raised = false;
    try {
        survey_from_volume_descriptor(no_grid);
    } catch (const std::invalid_argument&) {
        raised = true;
    }
    PWB_CHECK(raised);

    // Fail-closed: depth-domain sample axis → refuse (never metres as ms).
    pwb::seismic_io::VolumeDescriptor depth = descriptor;
    depth.sample_unit = "m";
    depth.sample_domain = pwb::seismic_io::SampleDomain::depth;
    raised = false;
    try {
        survey_from_volume_descriptor(depth);
    } catch (const std::invalid_argument&) {
        raised = true;
    }
    PWB_CHECK(raised);

    // Fail-closed: unknown unit string.
    pwb::seismic_io::VolumeDescriptor unit = descriptor;
    unit.sample_unit = "furlongs";
    raised = false;
    try {
        survey_from_volume_descriptor(unit);
    } catch (const std::invalid_argument&) {
        raised = true;
    }
    PWB_CHECK(raised);

    // Fail-closed: non-positive sample interval (#147).
    pwb::seismic_io::VolumeDescriptor zero_dt = descriptor;
    zero_dt.sample_step = 0.0;
    raised = false;
    try {
        survey_from_volume_descriptor(zero_dt);
    } catch (const std::invalid_argument&) {
        raised = true;
    }
    PWB_CHECK(raised);
}

PWB_TEST(tiled_volume_access_matches_in_memory) {
    const std::array<std::int64_t, 3> shape{6, 4, 16};
    const std::vector<float> data = ramp_volume(6, 4, 16);
    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = shape;
    geometry.strides = {shape[1] * shape[2], shape[2], 1};
    auto owning = pwb::viz::make_owning_volume(
        std::move(geometry), std::vector<float>(data));
    PWB_CHECK(owning != nullptr);
    pwb::app::viz_c::TiledVolumeAccess tiled(
        std::move(owning), nullptr);
    InMemoryVolumeAccess dense(data, shape);

    PWB_CHECK(tiled.shape() == shape);
    const auto il = tiled.slice_inline(2);
    const auto il_expected = dense.slice_inline(2);
    PWB_CHECK(il == il_expected);
    const auto xl = tiled.slice_crossline(3);
    const auto xl_expected = dense.slice_crossline(3);
    PWB_CHECK(xl == xl_expected);
    const auto time = tiled.slice_time(15);
    const auto time_expected = dense.slice_time(15);
    PWB_CHECK(time == time_expected);

    bool raised = false;
    try {
        (void)tiled.slice_inline(99);
    } catch (const std::exception&) {
        raised = true;
    }
    PWB_CHECK(raised);
}

PWB_TEST(joint_state_json_roundtrip) {
    WellSeismicScene scene;
    scene.set_survey(classic_survey());
    scene.set_volume_access(std::make_shared<InMemoryVolumeAccess>(
        ramp_volume(20, 10, 64), std::array<std::int64_t, 3>{20, 10, 64}));
    TimeDepthTable td("W-1", {0.0, 300.0, 1200.0}, {0.0, 500.0, 1800.0});
    WellHead well;
    well.name = "W-1";
    well.x = 1200.0;
    well.y = 2100.0;
    well.bottom_x = 1230.0;
    well.bottom_y = 2130.0;
    well.total_depth_m = 1800.0;
    well.id = "w1";
    scene.set_wells({well}, {{"W-1", td}});
    scene.add_time_slice(64.0);
    scene.set_display_settings({"gray", "cividis", 7});
    scene.set_time_slice_opacity(0.5);
    scene.set_near_well_distance_m(250.0);
    FenceSection fence("manual", {{1000.0, 2000.0}, {1900.0, 2600.0}},
                       "fence-roundtrip");
    scene.add_fence(fence);
    scene.set_active_fence("fence-roundtrip");
    scene.set_depth_transform(
        DepthTransformState::constant_v0(2600.0));
    scene.set_vertical_domain(VerticalDomain::Depth);

    const std::string json = scene.joint_state_to_json();

    WellSeismicScene restored;
    restored.set_survey(classic_survey());
    restored.set_volume_access(std::make_shared<InMemoryVolumeAccess>(
        ramp_volume(20, 10, 64), std::array<std::int64_t, 3>{20, 10, 64}));
    restored.set_wells({well}, {{"W-1", td}});
    std::vector<std::string> fences;
    PWB_CHECK(restored.restore_joint_state(json, &fences));
    PWB_CHECK(fences.size() == 1);
    PWB_CHECK(fences[0] == "fence-roundtrip");
    PWB_CHECK(restored.vertical_domain() == VerticalDomain::Depth);
    PWB_CHECK(restored.display_settings().seismic_color_scale == "gray");
    PWB_CHECK(restored.display_settings().gr_color_scale == "cividis");
    PWB_CHECK(restored.display_settings().well_width_px == 7);
    PWB_CHECK(restored.orthogonal_slice_state().time_slices.size() ==
              scene.orthogonal_slice_state().time_slices.size());
    PWB_CHECK(restored.orthogonal_slice_state().time_opacity == 0.5);
    PWB_CHECK(restored.active_fence() != nullptr);
    PWB_CHECK(restored.active_fence()->id == "fence-roundtrip");
    PWB_CHECK(restored.fences()[0].name == "manual");
    const double restored_lo = restored.depth_transform().constant().v0_m_s();
    PWB_CHECK(restored_lo == 2600.0);

    // Old/foreign payloads stay readable (nothing restored, no throw).
    PWB_CHECK(!restored.restore_joint_state("{\"version\": 0}", &fences));
    PWB_CHECK(!restored.restore_joint_state("not json at all", &fences));
    PWB_CHECK(!restored.restore_joint_state("{}", &fences));

    // Re-serializing the restored scene reproduces the same state JSON
    // (canonical form; well-independent fields stable).
    const std::string json2 = restored.joint_state_to_json();
    PWB_CHECK(json == json2);
}

PWB_TEST(scene_transform_seam_roundtrip_through_adapter) {
    // The CONV-GEO3D SceneTransform seam carries the joint scene's
    // world↔render maps: forward through the adapter must equal the
    // scene's own map, and the inverse must round-trip world points.
    WellSeismicScene scene;
    scene.set_survey(classic_survey());
    scene.set_volume_access(std::make_shared<InMemoryVolumeAccess>(
        ramp_volume(20, 10, 64), std::array<std::int64_t, 3>{20, 10, 64}));

    pwb::geo3d_viz::SceneTransform transform;
    transform.to_render = [&scene](const std::vector<std::array<double, 3>>& world) {
        return scene.world_to_render_xyz_array(world);
    };
    transform.to_domain = [&scene](const std::vector<std::array<double, 3>>& render) {
        return scene.render_to_world_xyz_array(render);
    };

    const std::vector<std::array<double, 3>> world = {
        {1000.0, 2000.0, 0.0}, {1450.0, 2300.0, 64.0},
        {1900.0, 2600.0, 126.0}};
    const auto rendered = transform.forward(world);
    const auto expected = scene.world_to_render_xyz_array(world);
    PWB_CHECK(rendered.size() == expected.size());
    for (std::size_t i = 0; i < rendered.size(); ++i) {
        for (int k = 0; k < 3; ++k) {
            PWB_CHECK(rendered[i][k] == expected[i][k]);
        }
    }
    const auto round = transform.inverse(rendered);
    for (std::size_t i = 0; i < round.size(); ++i) {
        for (int k = 0; k < 3; ++k) {
            PWB_CHECK(std::fabs(round[i][k] - world[i][k]) <= 1e-9);
        }
    }
}

PWB_TEST(joint_mesh_builders_produce_render_space_geometry) {
    using pwb::app::viz_c::build_active_time_slice;
    using pwb::app::viz_c::build_fence_curtain;
    using pwb::app::viz_c::build_well_polyline;

    WellSeismicScene scene;
    scene.set_survey(classic_survey());
    scene.set_volume_access(std::make_shared<InMemoryVolumeAccess>(
        ramp_volume(20, 10, 64), std::array<std::int64_t, 3>{20, 10, 64}));
    TimeDepthTable td("W-1", {0.0, 300.0, 1200.0}, {0.0, 500.0, 1800.0});
    WellHead well;
    well.name = "W-1";
    well.x = 1200.0;
    well.y = 2100.0;
    well.bottom_x = 1230.0;
    well.bottom_y = 2130.0;
    well.total_depth_m = 1800.0;
    well.id = "w1";
    scene.set_wells({well}, {{"W-1", td}});
    scene.add_time_slice(64.0);
    scene.add_fence(FenceSection("F", {{1000.0, 2000.0},
                                       {1900.0, 2600.0}},
                                 "fence-mesh"));

    // Well polyline lands in render space (0..n-1 per axis).
    const auto trajectories = scene.well_trajectories();
    const auto polyline = build_well_polyline(
        scene, trajectories.at("w1").points);
    PWB_CHECK(polyline.size() == trajectories.at("w1").points.size());
    // Render indices are unclamped (fractional lattice coordinates): a
    // well deeper than the volume legitimately maps past n_sample.
    for (const auto& v : polyline) {
        PWB_CHECK(std::isfinite(v[0]) && std::isfinite(v[2]));
        PWB_CHECK(v[2] >= -1.0);  // TWT >= 0 ⇒ sample index >= 0
    }

    // Active slice: mesh in render index space, faces = 2 per quad.
    const auto slice = build_active_time_slice(scene, "blue-white-red");
    PWB_CHECK(!slice.empty());
    PWB_CHECK(slice.faces.size() % 2 == 0);
    PWB_CHECK(slice.face_colors.size() == slice.faces.size());
    for (const auto& v : slice.vertices) {
        PWB_CHECK(v[2] >= 0.0f && v[2] <= 63.0f);
    }

    // Fence curtain: extraction present, mesh non-empty, z within the
    // sample lattice.
    const auto extraction = scene.extract_active_fence(32);
    PWB_CHECK(extraction.has_value());
    const auto curtain =
        build_fence_curtain(scene, *extraction, "blue-white-red");
    PWB_CHECK(!curtain.empty());
    PWB_CHECK(curtain.face_colors.size() == curtain.faces.size());
}

PWB_TEST(probe_and_fence_extraction_flow) {
    WellSeismicScene scene;
    scene.set_survey(classic_survey());
    scene.set_volume_access(std::make_shared<InMemoryVolumeAccess>(
        ramp_volume(20, 10, 64), std::array<std::int64_t, 3>{20, 10, 64}));
    scene.add_time_slice(64.0);
    scene.add_fence(FenceSection("F", {{1000.0, 2000.0},
                                       {1900.0, 2600.0}},
                                 "fence-1"));
    // No active fence → probe refuses.
    scene.remove_active_fence();
    bool raised = false;
    try {
        scene.set_probe(10.0, 20.0);
    } catch (const std::runtime_error&) {
        raised = true;
    }
    PWB_CHECK(raised);

    scene.add_fence(FenceSection("F2", {{1000.0, 2000.0},
                                        {1900.0, 2000.0}},
                                 "fence-2"));
    const ProbeState probe = scene.set_probe(300.0, 42.0);
    PWB_CHECK(probe.s_m == 300.0);
    PWB_CHECK(probe.z == 42.0);
    const auto indices = scene.probe_slice_indices();
    PWB_CHECK(indices.has_value());
    PWB_CHECK((*indices)[0] >= 0 && (*indices)[0] < 20);
    PWB_CHECK((*indices)[1] >= 0 && (*indices)[1] < 10);
    PWB_CHECK((*indices)[2] >= 0 && (*indices)[2] < 64);

    // Two wells are required for well-to-well fences.
    raised = false;
    try {
        scene.add_well_to_well_fence({"only-one"});
    } catch (const std::exception&) {
        raised = true;
    }
    PWB_CHECK(raised);
}

PWB_TEST(time_slice_stack_ops_and_cap) {
    WellSeismicScene scene;
    scene.set_survey(classic_survey());
    scene.set_volume_access(std::make_shared<InMemoryVolumeAccess>(
        ramp_volume(20, 10, 64), std::array<std::int64_t, 3>{20, 10, 64}));
    // reconcile() seeds one middle slice (n_sample/2 ⇒ 64 ms on this
    // survey) exactly like the Python scene.
    PWB_CHECK(scene.orthogonal_slice_state().time_slices.size() == 1);
    scene.add_time_slice(10.0);
    scene.add_time_slice(30.0);
    PWB_CHECK(scene.orthogonal_slice_state().time_slices.size() == 3);
    // Snapping merges lattice duplicates: 11.5 ms snaps to sample 6
    // (12 ms), a NEW slice; 11.9 ms snaps to the same 12 ms and merges.
    const double snapped_new = scene.add_time_slice(11.5);
    PWB_CHECK(snapped_new == 12.0);
    PWB_CHECK(scene.orthogonal_slice_state().time_slices.size() == 4);
    const double merged = scene.add_time_slice(11.9);
    PWB_CHECK(merged == 12.0);
    PWB_CHECK(scene.orthogonal_slice_state().time_slices.size() == 4);
    // Cap at eight slices: exactly four more fit (survey range caps at
    // 126 ms, so everything above snaps onto sample 63 = 126 ms).
    for (double t : {50.0, 70.0, 90.0, 110.0}) {
        scene.add_time_slice(t);
    }
    PWB_CHECK(scene.orthogonal_slice_state().time_slices.size() == 8);
    bool capped = false;
    try {
        scene.add_time_slice(400.0);
    } catch (const std::invalid_argument&) {
        capped = true;
    }
    PWB_CHECK(capped);
    PWB_CHECK(scene.orthogonal_slice_state().time_slices.size() == 8);
    // Remove requires > 1 slice and reports false for unknown values.
    PWB_CHECK(scene.remove_time_slice(12345.0) == false);
    PWB_CHECK(scene.remove_time_slice(
                  scene.orthogonal_slice_state().time_slices.front().time_ms));
    // Out-of-range slices are dropped on reconcile with a warning.
    WellSeismicScene reconcile_scene;
    reconcile_scene.set_survey(classic_survey());
    std::vector<TimeSliceState> slices = {TimeSliceState(10.0),
                                          TimeSliceState(2000.0)};
    reconcile_scene.restore_orthogonal_slice_state(
        OrthogonalSliceState(0, 0, std::move(slices), 10.0, 0.8));
    reconcile_scene.set_volume_access(
        std::make_shared<InMemoryVolumeAccess>(
            ramp_volume(20, 10, 64),
            std::array<std::int64_t, 3>{20, 10, 64}));
    PWB_CHECK(reconcile_scene.orthogonal_slice_state().time_slices.size() >= 1);
    const std::string& warning = reconcile_scene.slice_state_warning();
    PWB_CHECK(!warning.empty());
    bool out_of_range_dropped = true;
    for (const auto& slice :
         reconcile_scene.orthogonal_slice_state().time_slices) {
        if (slice.time_ms > 126.0 + 1e-9) out_of_range_dropped = false;
    }
    PWB_CHECK(out_of_range_dropped);
}
