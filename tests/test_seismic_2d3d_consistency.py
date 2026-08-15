"""2D/3D seismic coordinate consistency invariants (synthetic ground truth).

The synthetic cube encodes each voxel's native index in its amplitude::

    value(i, j, k) = i * (n_xl * n_t) + j * n_t + k      (exact in float32)

so any transpose / off-by-one / LOD drift is decodable from the sample value
alone. Odd shapes and non-unit line-number steps are exercised deliberately —
they are where shape-ratio index approximations break.
"""

from __future__ import annotations

import numpy as np
import pytest

segyio = pytest.importorskip("segyio")

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from geoviz import (
    InMemoryVolumeAccess,
    VerticalDomain,
    select_depth_transform,
)
from geoviz_well_seismic_3d import (
    FenceSection,
    TimeDepthTable,
    WellHead,
    WellSeismicScene,
)
from geoviz_well_seismic_3d.segy_survey import survey_corners_from_segy
from paleo_workbench.viz.seismic_volume_source import (
    SeismicVolumeSource,
    get_shared_seismic_source,
    preview_strides,
)
from paleo_workbench.viz.source_backed_volume_access import (
    SourceBackedVolumeAccess,
)


# ---------------------------------------------------------------------------
# Synthetic ground-truth SEGY
# ---------------------------------------------------------------------------

ODD_SHAPES = [(101, 103, 205), (17, 31, 257), (127, 131, 257)]


def ground_truth_volume(shape):
    """value(i,j,k) = flat native index — unique, float32-exact, decodable."""
    n_il, n_xl, n_t = shape
    idx = np.arange(n_il * n_xl * n_t, dtype=np.float32)
    return idx.reshape(n_il, n_xl, n_t)


def decode_native(value, shape):
    n_il, n_xl, n_t = shape
    flat = int(round(float(value)))
    i, rem = divmod(flat, n_xl * n_t)
    j, k = divmod(rem, n_t)
    return i, j, k


def write_synthetic_segy(
    path,
    shape,
    *,
    iline_start=1000,
    iline_step=1,
    xline_start=2000,
    xline_step=1,
    dt_ms=4.0,
    t0_ms=0.0,
):
    n_il, n_xl, n_t = shape
    vol = ground_truth_volume(shape)
    spec = segyio.spec()
    spec.ilines = [iline_start + iline_step * i for i in range(n_il)]
    spec.xlines = [xline_start + xline_step * j for j in range(n_xl)]
    spec.samples = tuple(t0_ms + dt_ms * k for k in range(n_t))
    spec.format = 1  # IEEE float32
    with segyio.create(str(path), spec) as f:
        for i in range(n_il):
            for j in range(n_xl):
                f.header[i * n_xl + j] = {
                    segyio.TraceField.INLINE_3D: int(spec.ilines[i]),
                    segyio.TraceField.CROSSLINE_3D: int(spec.xlines[j]),
                    segyio.TraceField.FieldRecord: int(spec.ilines[i]),
                    segyio.TraceField.CDP: int(spec.xlines[j]),
                    # Regular 50m grid so the trace-scan survey fallback can
                    # derive real corner XY positions.
                    segyio.TraceField.SourceX: j * 50,
                    segyio.TraceField.SourceY: i * 50,
                }
                f.trace[i * n_xl + j] = vol[i, j, :]
    return vol


@pytest.fixture(scope="module")
def odd_segy(tmp_path_factory):
    """101x103x205, IL step 2 / XL step 3, dt 4ms (segyio samples start at 0)."""
    path = tmp_path_factory.mktemp("seismic_gt") / "odd_101_103_205.sgy"
    vol = write_synthetic_segy(
        path,
        (101, 103, 205),
        iline_step=2,
        xline_step=3,
    )
    return path, vol, (101, 103, 205)


@pytest.fixture()
def source(odd_segy):
    path = odd_segy[0]
    src = SeismicVolumeSource(path)
    yield src
    src.close()


# ---------------------------------------------------------------------------
# C1/C2 — one native voxel reads identically through every 2D orientation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ijt", [(7, 11, 13), (50, 51, 102), (100, 102, 204), (0, 0, 0)])
def test_source_orientations_agree_on_native_voxel(source, ijt):
    i, j, k = ijt
    meta = source.metadata()
    assert meta.shape == (101, 103, 205)
    a = source.read_inline(i)[j, k]
    b = source.read_crossline(j)[i, k]
    c = source.read_timeslice(k)[i, j]
    d = source.read_trace(i, j)[k]
    for value in (a, b, c, d):
        assert decode_native(value, meta.shape) == (i, j, k)


def test_orientation_line_numbers_not_indices(source):
    """read_inline takes a zero-based index; line numbers are start+step*idx."""
    meta = source.metadata()
    assert meta.iline_number(0) == 1000 and meta.iline_step == 2
    assert meta.xline_number(0) == 2000 and meta.xline_step == 3
    # Native inline 5 is line number 1010; its slice equals trace row reads.
    line = source.read_inline(5)
    assert decode_native(line[0, 0], meta.shape) == (5, 0, 0)
    assert decode_native(line[-1, -1], meta.shape) == (5, 102, 204)


# ---------------------------------------------------------------------------
# C3 — exact LOD ↔ native mapping (strides, not shape ratios)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "strides",
    [(1, 1, 2), (2, 3, 4), (3, 1, 1), (1, 2, 1), (5, 7, 3)],
)
def test_lod_index_round_trip_exact(odd_segy, strides):
    shape = odd_segy[2]
    preview_shape = tuple(-(-n // s) for n, s in zip(shape, strides))
    access = SourceBackedVolumeAccess.__new__(SourceBackedVolumeAccess)
    access._native_shape = shape
    access._shape = preview_shape
    access._strides = strides
    for axis, (n_native, stride) in enumerate(zip(shape, strides)):
        for logical in range(-(-n_native // stride)):
            native = access.logical_to_native(axis, logical)
            assert native == logical * stride
            assert access.native_to_logical(axis, native) == float(logical)
    # Mapping never leaves native bounds (last preview sample is in-volume).
    for axis, (n_native, stride) in enumerate(zip(shape, strides)):
        last = -(-n_native // stride) - 1
        assert access.logical_to_native(axis, last) <= n_native - 1


def test_stride_shape_mismatch_is_rejected(odd_segy):
    shape = odd_segy[2]
    access = SourceBackedVolumeAccess.__new__(SourceBackedVolumeAccess)
    access._native_shape = shape
    access._shape = (51, 52, 102)  # 205 samples / stride 2 gives 103, not 102
    with pytest.raises(ValueError):
        access._validated_strides((2, 2, 2))


@pytest.mark.parametrize("shape", ODD_SHAPES)
def test_display_slices_equal_strided_native(tmp_path, shape):
    """3D preview slice[ii] must equal the native slice strided by (sx, st)."""
    path = tmp_path / f"gt_{shape[0]}_{shape[1]}_{shape[2]}.sgy"
    write_synthetic_segy(path, shape)
    src = SeismicVolumeSource(path)
    try:
        strides = preview_strides(*shape, max_dim=16, max_budget=16 ** 3)
        vol = ground_truth_volume(shape)
        preview = vol[:: strides[0], :: strides[1], :: strides[2]]
        access = SourceBackedVolumeAccess.__new__(SourceBackedVolumeAccess)
        access._native_shape = shape
        access._shape = tuple(int(x) for x in preview.shape)
        access._strides = strides
        access._display = np.ascontiguousarray(preview, dtype=np.float32)
        access._lod_level = 0
        si, sx, st = strides
        for ii in (0, access._shape[0] // 2, access._shape[0] - 1):
            got = access.slice_inline(ii)
            want = src.read_inline(ii * si)[::sx, ::st]
            np.testing.assert_array_equal(got, want)
        for ti in (0, access._shape[2] // 2, access._shape[2] - 1):
            got = access.slice_time(ti)
            want = src.read_timeslice(ti * st)[::si, ::sx]
            np.testing.assert_array_equal(got, want)
    finally:
        src.close()


def test_sample_trace_before_display_maps_both_axes(source, odd_segy):
    """Fence sampling with no display brick maps IL and XL into native space."""
    shape = odd_segy[2]
    strides = (2, 3, 4)
    access = SourceBackedVolumeAccess(source)
    # No display attached: logical shape stays native, so use an explicit
    # preview-shaped clone to exercise the mapping path.
    preview_shape = tuple(-(-n // s) for n, s in zip(shape, strides))
    access2 = SourceBackedVolumeAccess.__new__(SourceBackedVolumeAccess)
    access2._native_shape = shape
    access2._shape = preview_shape
    access2._strides = strides
    access2._display = None
    access2._lod_level = -1
    access2._source = source
    access2._source_id = source.source_id
    ii, xi = preview_shape[0] // 2, preview_shape[1] // 2
    trace = access2.sample_trace(ii, xi)
    want = source.read_trace(ii * strides[0], xi * strides[1])
    np.testing.assert_array_equal(trace, want)


# ---------------------------------------------------------------------------
# Registration — survey coords ↔ preview indices through explicit strides
# ---------------------------------------------------------------------------

def _scene_with_survey_and_preview(odd_segy, strides, n_along_fence=True):
    path, vol, shape = odd_segy
    p1, p2, p3, meta = survey_corners_from_segy(path)
    scene = WellSeismicScene()
    scene.set_survey_from_corners(
        p1,
        p2,
        p3,
        n_samples=int(meta["n_samples"]),
        dt_ms=float(meta["dt_ms"]),
        t0_ms=float(meta.get("t0_ms", 0.0)),
        iline_step=meta.get("loader_iline_step"),
        xline_step=meta.get("loader_xline_step"),
        n_inlines=meta.get("loader_n_inlines"),
        n_crosslines=meta.get("loader_n_crosslines"),
    )
    preview = vol[:: strides[0], :: strides[1], :: strides[2]]
    access = InMemoryVolumeAccess(preview)
    access.strides = strides  # duck-typed, like SourceBackedVolumeAccess
    scene.set_volume_access(access)
    scene.set_preview_mode(True)
    return scene, access


def test_survey_counts_with_nonunit_line_steps(odd_segy):
    """IL step 2 / XL step 3 must yield 101x103 grid, not 201x307 bins."""
    path, _vol, shape = odd_segy
    p1, p2, p3, meta = survey_corners_from_segy(path)
    scene = WellSeismicScene()
    scene.set_survey_from_corners(
        p1, p2, p3,
        n_samples=int(meta["n_samples"]),
        dt_ms=float(meta["dt_ms"]),
        t0_ms=float(meta.get("t0_ms", 0.0)),
        iline_step=meta.get("loader_iline_step"),
        xline_step=meta.get("loader_xline_step"),
        n_inlines=meta.get("loader_n_inlines"),
        n_crosslines=meta.get("loader_n_crosslines"),
    )
    survey = scene.survey
    assert survey.n_inlines == 101
    assert survey.n_crosslines == 103
    assert survey.iline_step == 2 and survey.xline_step == 3
    assert survey.n_samples == 205 and survey.dt_ms == pytest.approx(4.0)
    # IL/XL ↔ XY round trip at every lattice point.
    for i in (0, 50, 100):
        il = survey.iline_start + i * survey.iline_step
        x, y = survey.il_xl_to_xy(il, 2000)
        il2, xl2 = survey.xy_to_il_xl(x, y)
        assert il2 == pytest.approx(il, abs=1e-6)
        assert xl2 == pytest.approx(2000, abs=1e-6)


@pytest.mark.parametrize("strides", [(1, 1, 1), (2, 3, 4), (3, 1, 2)])
def test_registration_time_axis_spans_full_survey(odd_segy, strides):
    """Preview time axis covers the FULL survey range with dt*stride spacing."""
    scene, _access = _scene_with_survey_and_preview(odd_segy, strides)
    reg = scene.registration
    survey = scene.survey
    t0, dt = survey.t0_ms, survey.dt_ms
    n_preview = reg.n_sample
    # Exact lattice: preview p represents native p*stride.
    for p in (0, n_preview // 2, n_preview - 1):
        assert reg.sample_idx_to_time_ms(p) == pytest.approx(
            t0 + p * strides[2] * dt
        )
        assert reg.time_ms_to_sample_idx(t0 + p * strides[2] * dt) == pytest.approx(p)
    # Full range invariant (C3): world extent does not shrink with LOD.
    t_max_native = t0 + (survey.n_samples - 1) * dt
    t_max_preview = reg.sample_idx_to_time_ms(reg.n_sample - 1)
    assert t_max_preview <= t_max_native
    assert t_max_preview >= t_max_native - strides[2] * dt


@pytest.mark.parametrize("strides", [(1, 1, 1), (2, 3, 4)])
def test_registration_il_xl_exact_on_lattice(odd_segy, strides):
    scene, _access = _scene_with_survey_and_preview(odd_segy, strides)
    reg = scene.registration
    survey = scene.survey
    for native_i in (0, 50, 100):
        il = survey.iline_start + native_i * survey.iline_step
        vi, _vx = reg.il_xl_to_volume_idx(il, 2000)
        assert vi * strides[0] == native_i
    for native_j in (0, 51, 102):
        xl = survey.xline_start + native_j * survey.xline_step
        _vi, vx = reg.il_xl_to_volume_idx(1000, xl)
        assert vx * strides[1] == native_j
    # Inverse round trip on the lattice.
    vi = 10.0
    il, xl = reg.volume_idx_to_il_xl(vi, 5.0)
    vi2, vx2 = reg.il_xl_to_volume_idx(il, xl)
    assert vi2 == pytest.approx(vi) and vx2 == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# C1/C3 — scene slices at a world location equal the source trace there
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("strides", [(1, 1, 1), (2, 3, 4)])
def test_scene_slice_voxel_equals_source_at_same_world_location(
    source, odd_segy, strides
):
    shape = odd_segy[2]
    scene, access = _scene_with_survey_and_preview(odd_segy, strides)
    survey = scene.survey
    reg = scene.registration
    # Test at preview lattice points: native = logical * stride.
    logical_points = [(5, 4, 4), (25, 17, 25), (50, 34, 51)]
    for (li, lj, lk) in logical_points:
        native_i, native_j, native_k = li * strides[0], lj * strides[1], lk * strides[2]
        # World position of the native voxel (XY via survey, time via axis).
        x, y = survey.il_xl_to_xy(
            survey.iline_start + native_i * survey.iline_step,
            survey.xline_start + native_j * survey.xline_step,
        )
        t_ms = survey.t0_ms + native_k * survey.dt_ms
        # What the 3D scene serves at that world position (C1).
        vi, vx, vt = scene.world_to_render_xyz(x, y, t_ms)
        ii, xj, tk = reg.clamp_indices(vi, vx, vt)
        assert (ii, xj, tk) == (li, lj, lk)
        slice_3d = scene.slice_inline(ii)
        value = slice_3d[xj, tk]
        assert decode_native(value, shape) == (native_i, native_j, native_k)
        # And the source trace at the same native voxel agrees.
        assert source.read_trace(native_i, native_j)[native_k] == value


# ---------------------------------------------------------------------------
# C9 — fence 2D/3D consistency (axis extent + per-column amplitude)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("strides", [(1, 1, 1), (2, 3, 4)])
def test_fence_axis_and_amplitude_consistency(source, odd_segy, strides):
    shape = odd_segy[2]
    scene, access = _scene_with_survey_and_preview(odd_segy, strides)
    survey = scene.survey
    # Diagonal fence through two known world points.
    x0, y0 = survey.il_xl_to_xy(1000, 2000)
    x1, y1 = survey.il_xl_to_xy(
        survey.iline_start + 100 * survey.iline_step,
        survey.xline_start + 102 * survey.xline_step,
    )
    fence = FenceSection(
        name="gt",
        vertices_xy=np.array([[x0, y0], [x1, y1]], dtype=np.float64),
    )
    scene.add_fence(fence)
    ext = scene.extract_active_fence(n_along=37)
    assert ext is not None
    # Vertical axis spans the FULL survey time range at dt*stride spacing —
    # the old preview-nt × native-dt bug compressed it by the stride factor.
    assert ext.sample_axis[0] == pytest.approx(survey.t0_ms)
    expected_last = survey.t0_ms + (ext.amplitude.shape[1] - 1) * strides[2] * survey.dt_ms
    assert ext.sample_axis[-1] == pytest.approx(expected_last)
    # Per-column amplitude equals the source trace at the fence XY.
    verts = fence.vertices_xy
    seg = verts[1] - verts[0]
    total = float(np.linalg.norm(seg))
    for col in (0, 18, 36):
        s = float(ext.arc_length_m[col])
        xy = verts[0] + seg * (s / total)
        il, xl = survey.xy_to_il_xl(xy[0], xy[1])
        native_i = int(round((il - survey.iline_start) / survey.iline_step))
        native_j = int(round((xl - survey.xline_start) / survey.xline_step))
        native_i = max(0, min(shape[0] - 1, native_i))
        native_j = max(0, min(shape[1] - 1, native_j))
        want = source.read_trace(native_i, native_j)[:: strides[2]]
        np.testing.assert_array_equal(ext.amplitude[col], want)


# ---------------------------------------------------------------------------
# C4/C5/C6 — TIME/DEPTH semantics (unified + fail-closed)
# ---------------------------------------------------------------------------

def test_depth_unavailable_without_transform(odd_segy):
    scene, _ = _scene_with_survey_and_preview(odd_segy, (2, 3, 4))
    assert scene.depth_available is False
    with pytest.raises(ValueError, match="no time-depth transform"):
        scene.set_vertical_domain(VerticalDomain.DEPTH)
    assert scene.vertical_domain is VerticalDomain.TIME


def test_domain_round_trip_time_depth_time(odd_segy):
    """TIME → DEPTH → TIME leaves every time sample stationary."""
    scene, _ = _scene_with_survey_and_preview(odd_segy, (2, 3, 4))
    reg = scene.registration
    times_before = [
        reg.sample_idx_to_time_ms(p) for p in range(reg.n_sample)
    ]
    scene.set_depth_transform(select_depth_transform(constant_v0=True, v0_m_s=2500.0))
    scene.set_vertical_domain(VerticalDomain.DEPTH)
    assert scene.vertical_domain is VerticalDomain.DEPTH
    tr = scene.depth_transform
    for t in times_before:
        d = tr.time_ms_to_depth_m(t)
        assert tr.depth_m_to_time_ms(d) == pytest.approx(t, rel=1e-9, abs=1e-6)
    scene.set_vertical_domain(VerticalDomain.TIME)
    times_after = [
        reg.sample_idx_to_time_ms(p) for p in range(reg.n_sample)
    ]
    assert times_after == times_before


def test_fence_extract_follows_scene_domain_2d3d_unified(odd_segy):
    scene, _ = _scene_with_survey_and_preview(odd_segy, (2, 3, 4))
    survey = scene.survey
    fence = FenceSection(
        name="d", vertices_xy=np.array([[0.0, 0.0], [1.0, 1.0]])
    )
    scene.add_fence(fence)
    time_ext = scene.extract_active_fence(n_along=8)
    scene.set_depth_transform(select_depth_transform(constant_v0=True))
    scene.set_vertical_domain(VerticalDomain.DEPTH)
    depth_ext = scene.extract_active_fence(n_along=8)  # what 2D shows now
    assert time_ext is not None and depth_ext is not None
    np.testing.assert_allclose(
        scene.depth_transform.time_ms_to_depth_m(time_ext.sample_axis),
        depth_ext.sample_axis,
    )
    np.testing.assert_array_equal(time_ext.amplitude, depth_ext.amplitude)


# ---------------------------------------------------------------------------
# C10 — slice indices stay physically stationary across LOD refinement
# ---------------------------------------------------------------------------

def test_slice_indices_stationary_across_lod_change(odd_segy):
    vol = odd_segy[1]
    strides_l0 = (4, 4, 4)
    strides_l1 = (2, 2, 2)
    scene, _ = _scene_with_survey_and_preview(odd_segy, strides_l0)
    survey = scene.survey
    reg0 = scene.registration
    scene.set_orthogonal_slice_indices(
        inline_index=reg0.n_inline // 2,
        crossline_index=reg0.n_crossline // 2,
    )
    il_num, xl_num = reg0.volume_idx_to_il_xl(
        scene.orthogonal_slice_state.inline_index,
        scene.orthogonal_slice_state.crossline_index,
    )
    # L1 refinement replaces the preview with finer strides.
    preview_l1 = vol[:: strides_l1[0], :: strides_l1[1], :: strides_l1[2]]
    access_l1 = InMemoryVolumeAccess(preview_l1)
    access_l1.strides = strides_l1
    scene.set_volume_access(access_l1)
    state = scene.orthogonal_slice_state
    il_num1, xl_num1 = scene.registration.volume_idx_to_il_xl(
        state.inline_index, state.crossline_index
    )
    assert il_num1 == pytest.approx(il_num, abs=survey.iline_step)
    assert xl_num1 == pytest.approx(xl_num, abs=survey.xline_step)


# ---------------------------------------------------------------------------
# C7 — well trajectory ↔ seismic registration (TIME domain, TD table)
# ---------------------------------------------------------------------------

def test_well_trajectory_registered_against_seismic_time_axis(odd_segy):
    strides = (2, 3, 4)
    scene, _ = _scene_with_survey_and_preview(odd_segy, strides)
    survey = scene.survey
    reg = scene.registration
    x, y = survey.il_xl_to_xy(
        survey.iline_start + 50 * survey.iline_step,
        survey.xline_start + 51 * survey.xline_step,
    )
    # TD: MD 0..200m maps to TWT 0..400ms (linear, monotonic; t0 is 0).
    td = TimeDepthTable(
        well_name="W1",
        time_ms=np.array([0.0, 200.0, 400.0]),
        md_m=np.array([0.0, 100.0, 200.0]),
    )
    scene.set_wells(
        [WellHead("W1", x, y, x, y, 200.0, id="source:w1")],
        td_tables={"source:w1": td},
    )
    traj = scene.well_trajectories()["source:w1"]
    assert traj.has_td is True
    # Trajectory head sits on the well's seismic position at t0 (preview idx).
    p0 = traj.points[0]
    vi, vx, vt = scene.world_to_render_xyz(p0[0], p0[1], p0[2])
    assert reg.clamp_indices(vi, vx, vt) == (25, 17, 0)
    # Trajectory bottom maps to the TD table's last time sample.
    t_last = traj.points[-1][2]
    assert t_last == pytest.approx(400.0)
    _vi, _vx, vt2 = scene.world_to_render_xyz(x, y, t_last)
    native_k = int(round(vt2 * reg.strides[2]))
    assert survey.t0_ms + native_k * survey.dt_ms == pytest.approx(400.0)


def test_depth_trajectory_never_uses_md_as_z(odd_segy):
    """In Depth, trajectory Z comes from TD+transform — never raw MD."""
    scene, _ = _scene_with_survey_and_preview(odd_segy, (2, 3, 4))
    survey = scene.survey
    x, y = survey.il_xl_to_xy(1000, 2000)
    td = TimeDepthTable(
        well_name="W1",
        time_ms=np.array([100.0, 300.0, 500.0]),
        md_m=np.array([0.0, 100.0, 200.0]),
    )
    scene.set_wells(
        [WellHead("W1", x, y, x, y, 200.0, id="source:w1")],
        td_tables={"source:w1": td},
    )
    scene.set_depth_transform(select_depth_transform(constant_v0=True, v0_m_s=2000.0))
    scene.set_vertical_domain(VerticalDomain.DEPTH)
    traj = scene.well_trajectories()["source:w1"]
    assert traj.has_td is True
    # z(t=100..500ms) = t*1e-3*V0/2 = 100..500 m — MD would be 0..200 m.
    assert traj.points[0][2] == pytest.approx(100.0)
    assert traj.points[-1][2] == pytest.approx(500.0)
    # A well without TD shows its head only, with an explicit warning.
    scene.set_wells([WellHead("W2", x, y, x, y, 200.0, id="source:w2")])
    traj2 = scene.well_trajectories()["source:w2"]
    assert traj2.has_td is False
    assert len(traj2.points) == 1
    assert traj2.warning


# ---------------------------------------------------------------------------
# C10 — second volume: no stale reads
# ---------------------------------------------------------------------------

def test_second_volume_has_no_stale_first_volume_state(odd_segy, tmp_path):
    vol = odd_segy[1]
    shape = odd_segy[2]
    path_b = tmp_path / "second.sgy"
    shape_b = (23, 29, 61)
    write_synthetic_segy(path_b, shape_b)
    src_a = SeismicVolumeSource(odd_segy[0])
    src_b = SeismicVolumeSource(path_b)
    try:
        access_a = SourceBackedVolumeAccess(src_a)
        access_b = SourceBackedVolumeAccess(src_b)
        assert access_a.slice_inline(10)[0, 0] != access_b.slice_inline(10)[0, 0]
        assert decode_native(access_a.slice_inline(10)[0, 0], shape) == (10, 0, 0)
        assert decode_native(access_b.slice_inline(10)[0, 0], shape_b) == (10, 0, 0)
        # Scene rebound to a coarser preview of the SAME survey must serve
        # that preview's strided data (no leftover L0-style fine reads).
        scene, _ = _scene_with_survey_and_preview(odd_segy, (1, 1, 1))
        strides_l2 = (4, 4, 4)
        preview_l2 = vol[::4, ::4, ::4]
        access_l2 = SourceBackedVolumeAccess(src_a)
        access_l2.set_display_data(
            preview_l2, lod_level=2, strides=strides_l2
        )
        scene.set_volume_access(access_l2)
        value = scene.slice_inline(5)[3, 7]
        assert decode_native(value, shape) == (20, 12, 28)
        # Cross-survey binds are rejected outright (fail-closed, no guess).
        with pytest.raises(ValueError):
            scene.set_volume_access(access_b)
    finally:
        src_a.close()
        src_b.close()


def test_td_table_rejects_non_monotonic_data():
    with pytest.raises(ValueError, match="strictly increasing"):
        TimeDepthTable(
            well_name="bad",
            time_ms=np.array([100.0, 300.0, 200.0]),
            md_m=np.array([0.0, 100.0, 200.0]),
        )
    with pytest.raises(ValueError, match="strictly increasing"):
        TimeDepthTable(
            well_name="bad2",
            time_ms=np.array([100.0, 200.0, 300.0]),
            md_m=np.array([0.0, 0.0, 200.0]),
        )


def _write_standard_geometry_segy(path, shape, *, text_header=True):
    """Standard INLINE_3D/CROSSLINE_3D geometry (loader standard path)."""
    n_il, n_xl, n_t = shape
    vol = ground_truth_volume(shape)
    spec = segyio.spec()
    spec.ilines = [1000 + i for i in range(n_il)]
    spec.xlines = [2000 + j for j in range(n_xl)]
    spec.samples = tuple(4.0 * k for k in range(n_t))
    spec.format = 1
    with segyio.create(str(path), spec) as f:
        if text_header:
            f.text[0] = (
                "First inline : 1000  Last inline : 1000\r\n"
                "First xline : 2000  Last xline : 2000\r\n"
                "xmin : 0.0 xmax : 0.0 ymin : 0.0 ymax : 0.0\r\n"
            ).encode("ascii")
        for i in range(n_il):
            for j in range(n_xl):
                f.header[i * n_xl + j] = {
                    segyio.TraceField.INLINE_3D: int(spec.ilines[i]),
                    segyio.TraceField.CROSSLINE_3D: int(spec.xlines[j]),
                    segyio.TraceField.FieldRecord: int(spec.ilines[i]),
                    segyio.TraceField.CDP: int(spec.xlines[j]),
                    segyio.TraceField.SourceX: j * 40,
                    segyio.TraceField.SourceY: i * 40,
                }
                f.trace[i * n_xl + j] = vol[i, j, :]
    return vol


@pytest.mark.parametrize("text_header", [True, False])
def test_standard_geometry_survey_not_transposed(tmp_path, text_header):
    """Standard-geometry SEGY corners must keep IL on the volume axis 0.

    Regression for the unconditional loader-axes swap: with real
    INLINE_3D/CROSSLINE_3D geometry the loader inline IS the text inline, so
    swapping text-header corners transposed the survey (square grids) or
    failed the span validation (non-square grids).
    """
    path = tmp_path / f"std_{text_header}.sgy"
    shape = (21, 29, 41)  # deliberately non-square
    _write_standard_geometry_segy(path, shape, text_header=text_header)
    p1, p2, p3, meta = survey_corners_from_segy(path)
    assert meta.get("loader_geometry_source") == "standard_189_193"
    scene = WellSeismicScene()
    scene.set_survey_from_corners(
        p1, p2, p3,
        n_samples=int(meta["n_samples"]),
        dt_ms=float(meta["dt_ms"]),
        t0_ms=float(meta.get("t0_ms", 0.0)),
        iline_step=meta.get("loader_iline_step"),
        xline_step=meta.get("loader_xline_step"),
        n_inlines=meta.get("loader_n_inlines"),
        n_crosslines=meta.get("loader_n_crosslines"),
    )
    survey = scene.survey
    assert survey.n_inlines == 21 and survey.n_crosslines == 29
    # The survey IL axis must track the volume IL axis (SourceY direction):
    # moving +1 inline moves +40 in Y and leaves X unchanged.
    x_a, y_a = survey.il_xl_to_xy(1000, 2000)
    x_b, y_b = survey.il_xl_to_xy(1001, 2000)
    assert x_b == pytest.approx(x_a, abs=1e-6)
    assert y_b - y_a == pytest.approx(40.0, abs=1e-3)
    x_c, y_c = survey.il_xl_to_xy(1000, 2001)
    assert x_c - x_a == pytest.approx(40.0, abs=1e-3)
    assert y_c == pytest.approx(y_a, abs=1e-3)


def _write_detected_geometry_segy(path, shape, *, text_header=None):
    """Non-standard geometry: FieldRecord/CDP grid, INLINE_3D zeroed out.

    The loader falls back to its detected fast/slow header pair (loader
    inline = the fast axis = CDP for this inline-sorted layout).
    """
    n_il, n_xl, n_t = shape
    vol = ground_truth_volume(shape)
    spec = segyio.spec()
    spec.ilines = list(range(n_il))
    spec.xlines = list(range(n_xl))
    spec.samples = tuple(4.0 * k for k in range(n_t))
    spec.format = 1
    with segyio.create(str(path), spec) as f:
        if text_header is not None:
            f.text[0] = text_header.encode("ascii")
        for i in range(n_il):
            for j in range(n_xl):
                f.header[i * n_xl + j] = {
                    segyio.TraceField.FieldRecord: 1000 + i,
                    segyio.TraceField.CDP: 2000 + j,
                    segyio.TraceField.SourceX: j * 40,
                    segyio.TraceField.SourceY: i * 40,
                }
                f.trace[i * n_xl + j] = vol[i, j, :]
    # Blank the standard geometry headers so the loader must fall back to
    # its detected fast/slow pair (FieldRecord/CDP here).
    with segyio.open(str(path), "r+", ignore_geometry=True) as f:
        for t in range(n_il * n_xl):
            f.header[t][segyio.TraceField.INLINE_3D] = 0
            f.header[t][segyio.TraceField.CROSSLINE_3D] = 0
    return vol


_VALID_TEXT = (
    "First inline : 1000  Last inline : 1020\r\n"
    "First xline : 2000  Last xline : 2028\r\n"
    "xmin : 0.0 xmax : 1120.0 ymin : 0.0 ymax : 800.0\r\n"
)


@pytest.mark.parametrize(
    "text",
    [_VALID_TEXT, None],
    ids=["valid-text-header", "no-text-header"],
)
def test_detected_geometry_survey_loads_and_aligns(tmp_path, text):
    """Detected (fast/slow header) files: text-header swap stays valid, and
    the trace scan reads the LOADER's header pair (not FieldRecord/CDP
    guesses) so the survey neither errors nor mixes axes."""
    path = tmp_path / f"det_{text is not None}.sgy"
    shape = (21, 29, 41)
    _write_detected_geometry_segy(path, shape, text_header=text)
    p1, p2, p3, meta = survey_corners_from_segy(path)
    assert meta.get("loader_geometry_source") == "detected_headers"
    scene = WellSeismicScene()
    scene.set_survey_from_corners(
        p1, p2, p3,
        n_samples=int(meta["n_samples"]),
        dt_ms=float(meta["dt_ms"]),
        t0_ms=float(meta.get("t0_ms", 0.0)),
        iline_step=meta.get("loader_iline_step"),
        xline_step=meta.get("loader_xline_step"),
        n_inlines=meta.get("loader_n_inlines"),
        n_crosslines=meta.get("loader_n_crosslines"),
    )
    survey = scene.survey
    # Loader axes: inline = CDP (text xline, 29 values), crossline = FR.
    assert survey.n_inlines == 29 and survey.n_crosslines == 21
    # Non-degenerate grid: both spacings non-zero, corners distinct in XY.
    assert abs(p2[2] - p1[2]) + abs(p2[3] - p1[3]) > 1.0
    assert abs(p3[2] - p2[2]) + abs(p3[3] - p2[3]) > 1.0
    # The CDP axis (survey inline) tracks +X: +1 inline moves +40 in X.
    il0, xl0 = survey.iline_start, survey.xline_start
    x_a, y_a = survey.il_xl_to_xy(il0, xl0)
    x_b, y_b = survey.il_xl_to_xy(il0 + survey.iline_step, xl0)
    assert x_b - x_a == pytest.approx(40.0, abs=1e-3)
    assert y_b == pytest.approx(y_a, abs=1e-3)
    # Loader axes are swapped for detected files: volume axis 0 is CDP.
    loader_oriented = ground_truth_volume(shape).transpose(1, 0, 2)
    access = InMemoryVolumeAccess(loader_oriented[::1, ::2, ::2])
    access.strides = (1, 2, 2)
    scene.set_volume_access(access)
    x, y = survey.il_xl_to_xy(il0, xl0)
    vi, vx = scene.registration.xy_to_volume_idx(x, y)
    assert scene.registration.clamp_indices(vi, vx, 0.0)[:2] == (0, 0)


def test_crossline_sorted_standard_geometry_survey_non_degenerate(tmp_path):
    """Crossline-major files must yield a real (non-collapsed) corner set."""
    path = tmp_path / "xl_sorted.sgy"
    n_il, n_xl, n_t = 21, 29, 41
    vol = ground_truth_volume((n_il, n_xl, n_t))
    spec = segyio.spec()
    spec.ilines = [1000 + i for i in range(n_il)]
    spec.xlines = [2000 + j for j in range(n_xl)]
    spec.samples = tuple(4.0 * k for k in range(n_t))
    spec.format = 1
    spec.sorting = segyio.TraceSortingFormat.CROSSLINE_SORTING
    with segyio.create(str(path), spec) as f:
        for j in range(n_xl):
            for i in range(n_il):
                tr = j * n_il + i
                f.header[tr] = {
                    segyio.TraceField.INLINE_3D: int(spec.ilines[i]),
                    segyio.TraceField.CROSSLINE_3D: int(spec.xlines[j]),
                    segyio.TraceField.FieldRecord: int(spec.ilines[i]),
                    segyio.TraceField.CDP: int(spec.xlines[j]),
                    segyio.TraceField.SourceX: j * 40,
                    segyio.TraceField.SourceY: i * 40,
                }
                f.trace[tr] = vol[i, j, :]
    p1, p2, p3, meta = survey_corners_from_segy(path)
    # P2 must sit on the last crossline of the first inline, not collapse
    # onto P1 (which produced zero bin spacing / degenerate grids).
    assert (p2[2], p2[3]) != (p1[2], p1[3])
    scene = WellSeismicScene()
    scene.set_survey_from_corners(
        p1, p2, p3,
        n_samples=int(meta["n_samples"]),
        dt_ms=float(meta["dt_ms"]),
        t0_ms=float(meta.get("t0_ms", 0.0)),
        iline_step=meta.get("loader_iline_step"),
        xline_step=meta.get("loader_xline_step"),
        n_inlines=meta.get("loader_n_inlines"),
        n_crosslines=meta.get("loader_n_crosslines"),
    )
    survey = scene.survey
    assert survey.n_inlines == 21 and survey.n_crosslines == 29
    x_a, y_a = survey.il_xl_to_xy(1000, 2000)
    x_b, y_b = survey.il_xl_to_xy(1001, 2000)
    assert y_b - y_a == pytest.approx(40.0, abs=1e-3)
    x_c, _ = survey.il_xl_to_xy(1000, 2001)
    assert x_c - x_a == pytest.approx(40.0, abs=1e-3)


def test_pending_slice_numbers_survive_until_registration(qtbot, tmp_path):
    """Persisted line numbers are applied only once a registration exists."""
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    scene = page._joint_host.scene
    if scene is None:
        pytest.skip("engine unavailable")
    # No volume yet -> registration None; a scene update must NOT consume
    # the pending numbers (that dropped them before the first bind).
    page._pending_slice_numbers = (1020.0, 2009.0)
    page._on_joint_scene_updated()
    assert page._pending_slice_numbers == (1020.0, 2009.0)
    # Bind a preview volume so a registration exists, then apply.
    strides = (2, 3, 4)
    preview = ground_truth_volume((101, 103, 205))[
        :: strides[0], :: strides[1], :: strides[2]
    ]
    p1, p2, p3, meta = survey_corners_from_segy(_odd_segy_path(tmp_path))
    scene.set_survey_from_corners(
        p1, p2, p3,
        n_samples=int(meta["n_samples"]),
        dt_ms=float(meta["dt_ms"]),
        t0_ms=float(meta.get("t0_ms", 0.0)),
        iline_step=meta.get("loader_iline_step"),
        xline_step=meta.get("loader_xline_step"),
        n_inlines=meta.get("loader_n_inlines"),
        n_crosslines=meta.get("loader_n_crosslines"),
    )
    access = InMemoryVolumeAccess(preview)
    access.strides = strides
    scene.set_volume_access(access)
    page._apply_pending_slice_numbers()
    assert page._pending_slice_numbers is None
    reg = scene.registration
    state = scene.orthogonal_slice_state
    il_num, xl_num = reg.volume_idx_to_il_xl(
        state.inline_index, state.crossline_index
    )
    # Lattice numbers round-trip exactly (1020 -> native 10 -> preview 5
    # with stride 2; 2009 -> native 3 -> preview 1 with stride 3).
    assert il_num == pytest.approx(1020.0, abs=1e-6)
    assert xl_num == pytest.approx(2009.0, abs=1e-6)


def _odd_segy_path(tmp_path):
    """Small odd-shape SEGY for the pending-numbers test (cached per call)."""
    path = tmp_path / "odd_small.sgy"
    if not path.exists():
        write_synthetic_segy(path, (101, 103, 205), iline_step=2, xline_step=3)
    return path
