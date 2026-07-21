"""Tests for Seismic Cache, LUT Shader & Async Preloader (Issues #5, #6, #13, #16)."""
import time
import numpy as np
import pytest

from geoviz_seismic.colormap import ColormapManager
from geoviz_seismic.cache import DualLevelSeismicCache, SliceCacheKey, RamSliceCache
from geoviz_seismic.preloader import SeismicPreloadManager, DragTracker, PreloadPriority


def test_colormap_manager_lut_bytes():
    lut = ColormapManager.get_colormap("seismic", 256)
    assert lut.shape == (256, 4)
    assert lut.dtype == np.uint8
    
    lut_bytes = ColormapManager.get_lut_bytes("seismic")
    assert len(lut_bytes) == 256 * 4


def test_ram_slice_cache_byte_budget():
    # 1MB limit = 1024 * 1024 bytes
    cache = RamSliceCache(max_bytes=1024 * 1024)
    
    # Create 3 slices of 500KB each (500 * 1024 bytes)
    slice_data = np.zeros((500, 250), dtype=np.float32)  # 500 * 250 * 4 = 500,000 bytes
    
    key1 = SliceCacheKey(volume_id="vol1", slice_type="inline", position=10, downsample_factor=(1, 1, 1))
    key2 = SliceCacheKey(volume_id="vol1", slice_type="inline", position=11, downsample_factor=(1, 1, 1))
    key3 = SliceCacheKey(volume_id="vol1", slice_type="inline", position=12, downsample_factor=(1, 1, 1))
    
    cache.put(key1, slice_data)
    cache.put(key2, slice_data)
    
    assert cache.get(key1) is not None
    assert cache.get(key2) is not None
    
    # Putting key3 exceeds 1MB (3 * 500KB = 1.5MB), so key1 (LRU) should be evicted
    cache.put(key3, slice_data)
    
    assert cache.get(key1) is None
    assert cache.get(key2) is not None
    assert cache.get(key3) is not None


def test_drag_tracker_velocity():
    tracker = DragTracker()
    tracker.update(10, timestamp=1.0)
    v = tracker.update(20, timestamp=1.2)  # delta = +10 in 0.2s => velocity = 50 slices/s
    
    assert v == pytest.approx(50.0)
    assert tracker.is_moving_positive()


def test_preload_manager_token_invalidation():
    manager = SeismicPreloadManager()
    token1 = manager.next_generation()
    assert not token1.is_cancelled()
    
    token2 = manager.next_generation()
    assert token1.is_cancelled()
    assert not token2.is_cancelled()
