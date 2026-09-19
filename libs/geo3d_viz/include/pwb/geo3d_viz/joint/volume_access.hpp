// Injectable volume access for joint-scene slicing — port of
// geoviz_well_seismic_3d/volume_access.py @ 08851951 (VolumeAccess
// protocol + InMemoryVolumeAccess). Later hosts add async/LOD backends
// behind the same interface without changing the scene.
#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <vector>

namespace pwb::geo3d_viz::joint {

// Minimal volume handle: shape + orthogonal slices. Slices are row-major
// float planes (slice_inline → nc*nt, slice_crossline → ni*nt,
// slice_time → ni*nc).
class IVolumeAccess {
public:
    virtual ~IVolumeAccess() = default;

    virtual std::array<std::int64_t, 3> shape() const = 0;
    virtual std::vector<float> slice_inline(std::int64_t il_index) const = 0;
    virtual std::vector<float> slice_crossline(std::int64_t xl_index) const = 0;
    virtual std::vector<float> slice_time(std::int64_t sample_index) const = 0;

    // Optional dense fast path (InMemoryVolumeAccess): nullptr for
    // source-backed volumes — extraction then uses the slice methods
    // without forcing a full-cube materialisation.
    virtual const std::vector<float>* dense_data() const { return nullptr; }

    // Optional per-axis downsample stride of the loaded cube relative to
    // the native survey grid (source-backed previews expose the exact
    // stride; absent = inference fallback).
    virtual std::optional<std::array<std::int64_t, 3>> strides() const {
        return std::nullopt;
    }
};

// CPU in-memory volume for tests and small demos. Layout: (il, xl,
// sample) row-major.
class InMemoryVolumeAccess : public IVolumeAccess {
public:
    explicit InMemoryVolumeAccess(std::vector<float> data,
                                  std::array<std::int64_t, 3> shape);

    std::array<std::int64_t, 3> shape() const override { return shape_; }
    std::vector<float> slice_inline(std::int64_t il_index) const override;
    std::vector<float> slice_crossline(std::int64_t xl_index) const override;
    std::vector<float> slice_time(std::int64_t sample_index) const override;
    const std::vector<float>* dense_data() const override { return &data_; }
    const std::vector<float>& data() const { return data_; }

private:
    std::vector<float> data_;
    std::array<std::int64_t, 3> shape_;
};

}  // namespace pwb::geo3d_viz::joint
