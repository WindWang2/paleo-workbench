"""Tests for the seismic slice cache and colormap LUT (Issues #5, #6).

The async preloader tests that used to live here (#13, #16) were removed:
``geoviz_seismic.preloader`` was deleted as dead code in GVE 53127a9b, so
those cases could only ever skip.
"""
import numpy as np

from geoviz_seismic.colormap import ColormapManager
from geoviz_seismic.cache import RamSliceCache, SliceCacheKey


def test_colormap_manager_lut_bytes():
    lut = ColormapManager.get_colormap("seismic", 256)
    assert lut.shape == (256, 4)
    assert lut.dtype == np.uint8

    lut_bytes = lut.tobytes()
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
