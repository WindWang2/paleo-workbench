#include <pwb/seismic_service/tiled_volume.hpp>

#include <algorithm>
#include <array>
#include <functional>
#include <string>
#include <utility>

namespace pwb::seismic_service {

using pwb::seismic_io::CancelFlag;
using pwb::seismic_io::PwbvolLayout;
using pwb::seismic_io::SegyLayout;
using pwb::seismic_io::TileCache;
using pwb::seismic_io::VolumeDescriptor;
using pwb::seismic_io::WindowSpec;
using pwb::viz::ChunkInfo;
using pwb::viz::ISeismicVolume;
using pwb::viz::VolumeAxis;
using pwb::viz::VolumeGeometryV1;
using pwb::viz::VolumeOwnership;

namespace {

// The two free axes of a plane, in the canonical output row/column order:
//   inline plane   -> rows = crossline, cols = sample
//   crossline plane-> rows = inline,    cols = sample
//   sample plane   -> rows = inline,    cols = crossline
std::pair<std::size_t, std::size_t> free_axes(VolumeAxis axis) {
    switch (axis) {
    case VolumeAxis::inline_:
        return {1, 2};
    case VolumeAxis::crossline:
        return {0, 2};
    case VolumeAxis::sample:
        return {0, 1};
    }
    return {0, 1};
}

class TiledSeismicVolume final : public ISeismicVolume {
public:
    TiledSeismicVolume(VolumeDescriptor descriptor,
                       std::shared_ptr<const void> layout_keepalive,
                       std::function<std::size_t(const WindowSpec&,
                                                 std::span<float>,
                                                 const CancelFlag&,
                                                 std::string*)> reader,
                       std::shared_ptr<TileCache> cache)
        : descriptor_(std::move(descriptor)),
          layout_keepalive_(std::move(layout_keepalive)),
          reader_(std::move(reader)),
          cache_(std::move(cache)) {
        geometry_.shape = {descriptor_.ni, descriptor_.nc, descriptor_.ns};
        geometry_.strides = {0, 0, 0};  // packed canonical layout
        geometry_.origin = {descriptor_.iline_start, descriptor_.xline_start,
                            descriptor_.sample_start};
        geometry_.step = {descriptor_.iline_step, descriptor_.xline_step,
                          descriptor_.sample_step};
        geometry_.unit = descriptor_.sample_unit;
        geometry_.missing_value = descriptor_.missing_value;
        geometry_.byte_order = descriptor_.byte_order;
        geometry_.ownership = VolumeOwnership::none;
    }

    [[nodiscard]] const VolumeGeometryV1& geometry() const override {
        return geometry_;
    }

    [[nodiscard]] const VolumeDescriptor& descriptor() const {
        return descriptor_;
    }

    std::size_t read_slice(VolumeAxis axis, std::int64_t index,
                           std::span<float> out) override {
        const std::array<std::int64_t, 3> shape = geometry_.shape;
        const std::size_t fixed = pwb::viz::axis_index(axis);
        if (index < 0 || index >= shape[fixed]) {
            return 0;
        }
        const auto [row_axis, col_axis] = free_axes(axis);
        const std::int64_t rows = shape[row_axis];
        const std::int64_t cols = shape[col_axis];
        if (out.size() != static_cast<std::size_t>(rows * cols)) {
            return 0;
        }

        const std::array<std::int64_t, 3> tile_shape = cache_->config().tile_shape;
        // Per-call flag: a cancelled plane read never poisons later reads.
        const CancelFlag cancel;

        // Iterate the plane's tiles; each tile is one cached window read and
        // a strided scatter into the canonical output plane.
        for (std::int64_t row_tile = 0; row_tile * tile_shape[row_axis] < rows;
             ++row_tile) {
            for (std::int64_t col_tile = 0;
                 col_tile * tile_shape[col_axis] < cols; ++col_tile) {
                std::array<std::int64_t, 3> tile{0, 0, 0};
                tile[row_axis] = row_tile;
                tile[col_axis] = col_tile;
                std::string error;
                const auto buffer = cache_->get_or_load(
                    tile,
                    [this, fixed, index, &cancel, &tile_shape, &tile](
                        std::string* load_error) {
                        std::array<std::int64_t, 3> load_origin{0, 0, 0};
                        load_origin[fixed] = index;
                        for (std::size_t a = 0; a < 3; ++a) {
                            if (a != fixed) {
                                load_origin[a] =
                                    tile[a] * tile_shape[a];
                            }
                        }
                        std::array<std::int64_t, 3> load_extent = tile_shape;
                        load_extent[fixed] = 1;  // the slice's own axis
                        for (std::size_t a = 0; a < 3; ++a) {
                            if (a != fixed) {
                                load_extent[a] = std::min(
                                    tile_shape[a],
                                    geometry_.shape[a] - load_origin[a]);
                            }
                        }
                        auto chunk = std::make_shared<TileCache::Buffer>();
                        chunk->resize(static_cast<std::size_t>(load_extent[0]
                                                               * load_extent[1]
                                                               * load_extent[2]));
                        WindowSpec window;
                        window.origin = load_origin;
                        window.extent = load_extent;
                        if (reader_(window, *chunk, cancel, load_error)
                            != chunk->size()) {
                            return std::shared_ptr<TileCache::Buffer>{};
                        }
                        return chunk;
                    },
                    &error);
                if (buffer == nullptr) {
                    return 0;
                }
                scatter_tile(axis, row_axis, col_axis, cols, tile_shape,
                             tile, *buffer, out);
            }
        }
        return out.size();
    }

    [[nodiscard]] std::vector<ChunkInfo> chunk_plan() const override {
        const std::array<std::int64_t, 3> tile_shape = cache_->config().tile_shape;
        std::vector<ChunkInfo> plan;
        std::array<std::int64_t, 3> counts{1, 1, 1};
        for (std::size_t a = 0; a < 3; ++a) {
            counts[a] = (geometry_.shape[a] + tile_shape[a] - 1) / tile_shape[a];
        }
        plan.reserve(static_cast<std::size_t>(counts[0] * counts[1] * counts[2]));
        for (std::int64_t a = 0; a < counts[0]; ++a) {
            for (std::int64_t b = 0; b < counts[1]; ++b) {
                for (std::int64_t c = 0; c < counts[2]; ++c) {
                    ChunkInfo info;
                    info.offset = {a * tile_shape[0], b * tile_shape[1],
                                   c * tile_shape[2]};
                    for (std::size_t d = 0; d < 3; ++d) {
                        info.extent[d] =
                            std::min(tile_shape[d], geometry_.shape[d]
                                                        - info.offset[d]);
                    }
                    info.layout = "tile-cache";
                    plan.push_back(std::move(info));
                }
            }
        }
        return plan;
    }

    [[nodiscard]] std::shared_ptr<const void> lifetime() const override {
        return layout_keepalive_;
    }

private:
    // Copies one tile buffer into the plane at the canonical positions.
    void scatter_tile(VolumeAxis axis, std::size_t row_axis,
                      std::size_t col_axis, std::int64_t cols,
                      const std::array<std::int64_t, 3>& tile_shape,
                      const TileCache::Key& tile, const TileCache::Buffer& buffer,
                      std::span<float> out) const {
        std::array<std::int64_t, 3> base{0, 0, 0};
        base[row_axis] = tile[row_axis] * tile_shape[row_axis];
        base[col_axis] = tile[col_axis] * tile_shape[col_axis];
        const std::array<std::int64_t, 3> shape = geometry_.shape;
        const std::int64_t tile_rows =
            std::min(tile_shape[row_axis], shape[row_axis] - base[row_axis]);
        const std::int64_t tile_cols =
            std::min(tile_shape[col_axis], shape[col_axis] - base[col_axis]);
        // Tile buffers are C-order over (0, 1, 2) restricted to the tile's
        // loaded extents; the loaded row stride equals the loaded col count.
        const std::int64_t buffer_cols =
            std::min(tile_shape[col_axis], shape[col_axis] - base[col_axis]);
        for (std::int64_t r = 0; r < tile_rows; ++r) {
            float* dst = out.data()
                + static_cast<std::size_t>((base[row_axis] + r) * cols
                                           + base[col_axis]);
            const float* src = buffer.data()
                + static_cast<std::size_t>(r * buffer_cols);
            std::copy(src, src + static_cast<std::size_t>(tile_cols), dst);
        }
        (void)axis;
    }

    VolumeDescriptor descriptor_;
    std::shared_ptr<const void> layout_keepalive_;
    std::function<std::size_t(const WindowSpec&, std::span<float>,
                              const CancelFlag&, std::string*)>
        reader_;
    std::shared_ptr<TileCache> cache_;
    VolumeGeometryV1 geometry_;
};

}  // namespace

std::shared_ptr<ISeismicVolume> make_tiled_volume(
    SegyLayout layout, std::shared_ptr<TileCache> cache) {
    VolumeDescriptor descriptor = layout.descriptor;
    auto keepalive = std::make_shared<SegyLayout>(std::move(layout));
    auto reader =
        [keepalive](const WindowSpec& window, std::span<float> out,
                    const CancelFlag& cancel, std::string* error) {
            return pwb::seismic_io::read_segy_window(*keepalive, window, out,
                                                     cancel, error);
        };
    return std::make_shared<TiledSeismicVolume>(
        std::move(descriptor), std::move(keepalive), std::move(reader),
        std::move(cache));
}

std::shared_ptr<ISeismicVolume> make_tiled_volume(
    PwbvolLayout layout, std::shared_ptr<TileCache> cache) {
    VolumeDescriptor descriptor = layout.descriptor;
    auto keepalive = std::make_shared<PwbvolLayout>(std::move(layout));
    auto reader =
        [keepalive](const WindowSpec& window, std::span<float> out,
                    const CancelFlag& cancel, std::string* error) {
            return pwb::seismic_io::read_pwbvol_window(*keepalive, window,
                                                       out, cancel, error);
        };
    return std::make_shared<TiledSeismicVolume>(
        std::move(descriptor), std::move(keepalive), std::move(reader),
        std::move(cache));
}

}  // namespace pwb::seismic_service
