"""TDD Benchmark Tests for Seismic 3D Viewport LOD Acceleration (Issue #5 / Refactor)."""
import time
import numpy as np
import pytest

from geoviz_seismic.renderer_3d import Renderer3DLODManager, DualGLVolumeItem


def test_seismic_3d_lod_manager_interaction_state():
    lod_mgr = Renderer3DLODManager(idle_debounce_ms=50.0)
    
    # Active camera interaction -> Level 2 LOD (2x downsampled)
    assert lod_mgr.get_render_lod(is_interacting=True, idle_ms=0.0) == 2
    assert lod_mgr.get_render_lod(is_interacting=True, idle_ms=10.0) == 2
    
    # Stopped interacting but idle time < 50ms -> Level 2 LOD
    assert lod_mgr.get_render_lod(is_interacting=False, idle_ms=30.0) == 2
    
    # Idle time >= 50ms -> Level 1 LOD (Full resolution)
    assert lod_mgr.get_render_lod(is_interacting=False, idle_ms=55.0) == 1


def test_dual_gl_volume_item_lod_sampling_performance():
    # 200x200x200 3D seismic volume
    volume_data = np.random.randn(200, 200, 200).astype(np.float32)
    
    item = DualGLVolumeItem(data=volume_data)
    
    # Benchmarking LOD level 2 (downsampled) vs LOD level 1 (full)
    t0 = time.perf_counter()
    lod2_data = item.get_lod_data(lod_level=2)
    t1 = time.perf_counter()
    
    lod2_time_ms = (t1 - t0) * 1000.0
    
    assert lod2_data.shape == (100, 100, 100)
    assert lod2_time_ms < 5.0  # Fast downsampling < 5ms
