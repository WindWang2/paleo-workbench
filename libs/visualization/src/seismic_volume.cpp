#include <pwb/viz/seismic_volume.hpp>

#include <algorithm>
#include <cmath>
#include <cstring>

namespace pwb::viz {

namespace {

class InMemoryVolume final : public ISeismicVolume {
public:
    InMemoryVolume(VolumeGeometryV1 geometry, const float* data,
                   std::shared_ptr<const void> lifetime)
        : geometry_(std::move(geometry)), data_(data), lifetime_(std::move(lifetime)) {
    }

    [[nodiscard]] const VolumeGeometryV1& geometry() const override { return geometry_; }

    std::size_t read_slice(VolumeAxis axis, std::int64_t index, std::span<float> out) override {
        const std::size_t a = axis_index(axis);
        const std::int64_t dim = geometry_.shape[a];
        if (index < 0 || index >= dim) {
            return 0;
        }
        if (static_cast<std::int64_t>(out.size()) != slice_extent(geometry_, axis)) {
            return 0;
        }
        const std::array<std::int64_t, 3> strides = geometry_.effective_strides();
        const std::size_t row_axis = a == 0 ? 1 : 0; // first remaining axis
        const std::size_t col_axis = a == 2 ? 1 : 2; // second remaining axis
        const std::int64_t rows = geometry_.shape[row_axis];
        const std::int64_t cols = geometry_.shape[col_axis];
        const std::int64_t slice_stride = strides[a] * index;
        std::size_t written = 0;
        for (std::int64_t row = 0; row < rows; ++row) {
            const std::int64_t row_offset = slice_stride + strides[row_axis] * row;
            for (std::int64_t col = 0; col < cols; ++col) {
                out[written++] = data_[row_offset + strides[col_axis] * col];
            }
        }
        return written;
    }

    [[nodiscard]] std::shared_ptr<const void> lifetime() const override { return lifetime_; }

private:
    VolumeGeometryV1 geometry_;
    const float* data_;
    std::shared_ptr<const void> lifetime_;
};

} // namespace

std::unique_ptr<ISeismicVolume> make_in_memory_volume(VolumeGeometryV1 geometry,
                                                      const float* data,
                                                      std::shared_ptr<const void> lifetime) {
    geometry.ownership = VolumeOwnership::none; // borrowed view, never owning
    return std::make_unique<InMemoryVolume>(std::move(geometry), data, std::move(lifetime));
}

std::unique_ptr<ISeismicVolume> make_owning_volume(VolumeGeometryV1 geometry,
                                                   std::vector<float> data) {
    struct OwningBuffer {
        std::vector<float> values;
    };
    auto buffer = std::make_shared<OwningBuffer>(OwningBuffer{std::move(data)});
    geometry.strides = {0, 0, 0}; // packed C-order
    geometry.ownership = VolumeOwnership::owning;
    const float* raw = buffer->values.data();
    auto volume = std::make_unique<InMemoryVolume>(std::move(geometry), raw, buffer);
    return volume;
}

IndexedSlice map_slice_to_indexed8(std::span<const float> slice,
                                   const std::optional<std::pair<double, double>>& value_range) {
    IndexedSlice result;
    result.pixels.assign(slice.size(), 0);
    if (slice.empty()) {
        result.degenerate = true;
        return result;
    }

    float v_min = 0.0f;
    float v_max = 0.0f;
    if (value_range.has_value()) {
        v_min = static_cast<float>(value_range->first);
        v_max = static_cast<float>(value_range->second);
    } else {
        // Finite-only min/max stretch: every element contributes (no sampling).
        bool have_finite = false;
        for (const float value : slice) {
            if (std::isfinite(value)) {
                if (!have_finite) {
                    v_min = v_max = value;
                    have_finite = true;
                } else {
                    v_min = std::min(v_min, value);
                    v_max = std::max(v_max, value);
                }
            }
        }
        if (!have_finite) {
            result.degenerate = true;
            return result;
        }
    }

    // Degenerate check uses float32 semantics, matching the oracle
    // (`v_min < v_max` with isfinite guards).
    if (!(v_min < v_max) || !std::isfinite(v_min) || !std::isfinite(v_max)) {
        result.degenerate = true;
        return result;
    }

    const float inv_range = 255.0f / (v_max - v_min);
    for (std::size_t i = 0; i < slice.size(); ++i) {
        const float value = slice[i];
        if (!std::isfinite(value)) {
            result.pixels[i] = 0; // non-finite renders as 0
            continue;
        }
        float norm = (value - v_min) * inv_range;
        if (!(norm > 0.0f)) {
            norm = 0.0f; // NaN guard; negatives clamp
        } else if (norm > 255.0f) {
            norm = 255.0f;
        }
        result.pixels[i] = static_cast<std::uint8_t>(norm); // truncation toward zero
    }
    result.value_min = static_cast<double>(v_min);
    result.value_max = static_cast<double>(v_max);
    return result;
}

} // namespace pwb::viz
