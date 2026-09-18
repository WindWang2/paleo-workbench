#pragma once

// pwb::seismic_service — the tiled ISeismicVolume backend.
//
// Bridges libs/seismic_io (descriptor + window reads + bounded LRU tile
// cache) into the frozen pwb::viz::ISeismicVolume contract the slice viewer
// consumes. The volume is NEVER fully materialised: every plane served to
// the viewer is assembled from cached tiles, so memory stays
// O(cache budget), not O(volume) — this is the native replacement of the
// Python chunked-store viewer path (geoviz_seismic.chunked over zarr).
//
// Threading: matches the SliceController contract — read_slice()/geometry()
// are called on exactly one worker thread; the tile cache itself is
// thread-safe, so concurrent volumes (one controller each) share nothing.

#include <memory>

#include <pwb/seismic_io/segy_layout.hpp>
#include <pwb/seismic_io/tile_cache.hpp>
#include <pwb/seismic_io/tile_read.hpp>
#include <pwb/viz/seismic_volume.hpp>

namespace pwb::seismic_service {

// Builds a tiled backend over an inspected SEG-Y survey. The layout (and
// everything it captures) must outlive the volume; the returned volume's
// lifetime() carries it, so shared_ptr lifetime management is enough.
[[nodiscard]] std::shared_ptr<pwb::viz::ISeismicVolume> make_tiled_volume(
    pwb::seismic_io::SegyLayout layout,
    std::shared_ptr<pwb::seismic_io::TileCache> cache);

// Same over an inspected PWBVOL1 payload.
[[nodiscard]] std::shared_ptr<pwb::viz::ISeismicVolume> make_tiled_volume(
    pwb::seismic_io::PwbvolLayout layout,
    std::shared_ptr<pwb::seismic_io::TileCache> cache);

}  // namespace pwb::seismic_service
