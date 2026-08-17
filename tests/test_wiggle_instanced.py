"""Unit tests for WiggleTraceRenderer texture allocation and OpenGL lifecycle (Issue #27)."""
from __future__ import annotations

import numpy as np
import pytest

from geoviz_seismic.wiggle_instanced import WiggleTraceTexture, WiggleTraceRenderer


def test_wiggle_trace_texture_initialization():
    texture = WiggleTraceTexture()
    assert texture.texture_id is None
    assert texture.num_traces == 0
    assert texture.num_samples == 0


def test_wiggle_trace_texture_update_slice():
    texture = WiggleTraceTexture()
    slice_data = np.random.randn(100, 500).astype(np.float32)

    # In mock/headless CPU environment, mock_gl allocates a non-zero texture_id
    texture.update_slice(slice_data, mock_gl=True)
    assert texture.num_traces == 100
    assert texture.num_samples == 500
    assert texture.texture_id is not None
    assert texture.texture_id > 0


def test_wiggle_trace_texture_reupload_cleanup():
    texture = WiggleTraceTexture()
    slice1 = np.random.randn(50, 200).astype(np.float32)
    texture.update_slice(slice1, mock_gl=True)
    first_id = texture.texture_id

    # Re-upload new slice
    slice2 = np.random.randn(80, 300).astype(np.float32)
    texture.update_slice(slice2, mock_gl=True)
    assert texture.num_traces == 80
    assert texture.num_samples == 300
    assert texture.texture_id is not None

    # Cleanup destroys resources
    texture.destroy(mock_gl=True)
    assert texture.texture_id is None
    assert texture.num_traces == 0
    assert texture.num_samples == 0


def test_renderer_facade_set_data():
    renderer = WiggleTraceRenderer()
    slice_data = np.random.randn(120, 400).astype(np.float32)
    renderer.set_data(slice_data, mock_gl=True)
    assert renderer.num_traces == 120
    assert renderer.num_samples == 400


def test_renderer_gain_and_clip_limit_validation():
    renderer = WiggleTraceRenderer()
    renderer.set_gain(2.5)
    assert renderer.gain == 2.5

    with pytest.raises(ValueError):
        renderer.set_gain(-1.0)

    renderer.set_clip_limit(1.5)
    assert renderer.clip_limit == 1.5

    with pytest.raises(ValueError):
        renderer.set_clip_limit(0.0)


def test_renderer_mode_a_uniforms_and_shader_sources():
    renderer = WiggleTraceRenderer()
    assert renderer.display_mode == "wiggle"
    assert "u_gain" in renderer.vertex_shader_code
    assert "u_clip_limit" in renderer.vertex_shader_code
    assert "u_seismic_tex" in renderer.vertex_shader_code
    assert "gl_InstanceID" in renderer.vertex_shader_code


def test_renderer_mode_b_positive_fill():
    renderer = WiggleTraceRenderer()
    renderer.set_display_mode("positive_fill")
    assert renderer.display_mode == "positive_fill"
    assert renderer.mode_int == 1

    renderer.set_positive_fill_color((1.0, 0.0, 0.0, 0.8))
    assert renderer.positive_fill_color == (1.0, 0.0, 0.0, 0.8)
    assert "u_positive_fill_color" in renderer.fragment_shader_code


def test_renderer_mode_c_dual_fill():
    renderer = WiggleTraceRenderer()
    renderer.set_display_mode("dual_fill")
    assert renderer.display_mode == "dual_fill"
    assert renderer.mode_int == 2

    renderer.set_positive_fill_color((1.0, 0.0, 0.0, 1.0))
    renderer.set_negative_fill_color((0.0, 0.0, 1.0, 1.0))
    assert renderer.positive_fill_color == (1.0, 0.0, 0.0, 1.0)
    assert renderer.negative_fill_color == (0.0, 0.0, 1.0, 1.0)
    assert "u_negative_fill_color" in renderer.fragment_shader_code


def test_renderer_mode_d_overlaid_vd():
    renderer = WiggleTraceRenderer()
    renderer.set_display_mode("overlaid_vd")
    assert renderer.display_mode == "overlaid_vd"
    assert renderer.mode_int == 3

    lut = np.zeros((256, 4), dtype=np.uint8)
    lut[:, 0] = 255  # Red channel
    renderer.set_colormap(lut, vmin=-2.0, vmax=2.0, mock_gl=True)
    assert renderer.vmin == -2.0
    assert renderer.vmax == 2.0
    assert "u_lut_tex" in renderer.fragment_shader_code


def test_renderer_adaptive_lod_switching():
    renderer = WiggleTraceRenderer()
    renderer.set_display_mode("positive_fill")

    # High trace density (1000 traces in 1000px viewport -> 1px/trace < 2px threshold)
    active_mode = renderer.update_viewport_lod(viewport_width_px=1000, visible_traces=1000)
    assert active_mode == "overlaid_vd"
    assert renderer.is_lod_fallback is True

    # Low trace density (100 traces in 1000px viewport -> 10px/trace >= 3px threshold)
    active_mode = renderer.update_viewport_lod(viewport_width_px=1000, visible_traces=100)
    assert active_mode == "positive_fill"
    assert renderer.is_lod_fallback is False


def test_renderer_adaptive_vector_export():
    renderer = WiggleTraceRenderer()

    # Small trace count < 500 triggers pure vector export
    export_spec_small = renderer.determine_export_policy(visible_traces=250, dpi=300)
    assert export_spec_small["export_mode"] == "vector"
    assert export_spec_small["raster_required"] is False

    # Large trace count >= 500 triggers High-DPI raster embedding
    export_spec_large = renderer.determine_export_policy(visible_traces=1200, dpi=300)
    assert export_spec_large["export_mode"] == "high_dpi_raster"
    assert export_spec_large["raster_required"] is True
    assert export_spec_large["dpi"] == 300


def test_renderer_nan_validation():
    renderer = WiggleTraceRenderer()
    with pytest.raises(ValueError):
        renderer.set_gain(float("nan"))

    with pytest.raises(ValueError):
        renderer.set_clip_limit(float("nan"))


def test_renderer_render_export():
    renderer = WiggleTraceRenderer()
    slice_data = np.random.randn(50, 100).astype(np.float32)
    renderer.set_data(slice_data, mock_gl=True)

    # gve 31b7f15d: this renderer has no offscreen OpenGL context, so an
    # offscreen raster export can only fabricate a blank PNG. The honest
    # contract is an explicit NotImplementedError; real raster export must
    # render into a visible QOpenGLWidget and grab its framebuffer.
    with pytest.raises(NotImplementedError, match="Offscreen high-DPI raster export"):
        renderer.render_export(dpi=300)







