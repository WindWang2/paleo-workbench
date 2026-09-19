// volume_access.cpp — InMemoryVolumeAccess (volume_access.py).
#include "pwb/geo3d_viz/joint/volume_access.hpp"

#include <algorithm>
#include <stdexcept>

namespace pwb::geo3d_viz::joint {

InMemoryVolumeAccess::InMemoryVolumeAccess(
    std::vector<float> data, std::array<std::int64_t, 3> shape)
    : data_(std::move(data)), shape_(shape) {
    const std::int64_t expected =
        shape_[0] > 0 && shape_[1] > 0 && shape_[2] > 0
            ? shape_[0] * shape_[1] * shape_[2]
            : -1;
    if (expected < 0 ||
        static_cast<std::size_t>(expected) != data_.size()) {
        throw std::invalid_argument(
            "volume data must be 3-D (il, xl, sample) matching the shape");
    }
}

std::vector<float> InMemoryVolumeAccess::slice_inline(
    std::int64_t il_index) const {
    const std::int64_t plane = shape_[1] * shape_[2];
    const std::size_t begin = static_cast<std::size_t>(il_index * plane);
    if (il_index < 0 || il_index >= shape_[0] ||
        begin + static_cast<std::size_t>(plane) > data_.size()) {
        throw std::out_of_range("slice_inline index out of range");
    }
    return std::vector<float>(
        data_.begin() + static_cast<std::ptrdiff_t>(begin),
        data_.begin() + static_cast<std::ptrdiff_t>(begin + plane));
}

std::vector<float> InMemoryVolumeAccess::slice_crossline(
    std::int64_t xl_index) const {
    if (xl_index < 0 || xl_index >= shape_[1]) {
        throw std::out_of_range("slice_crossline index out of range");
    }
    const std::int64_t ni = shape_[0];
    const std::int64_t nt = shape_[2];
    std::vector<float> out(static_cast<std::size_t>(ni * nt));
    for (std::int64_t il = 0; il < ni; ++il) {
        const std::size_t src = static_cast<std::size_t>(
            il * shape_[1] * nt + xl_index * nt);
        std::copy_n(data_.begin() + static_cast<std::ptrdiff_t>(src),
                    static_cast<std::size_t>(nt),
                    out.begin() + static_cast<std::ptrdiff_t>(il * nt));
    }
    return out;
}

std::vector<float> InMemoryVolumeAccess::slice_time(
    std::int64_t sample_index) const {
    if (sample_index < 0 || sample_index >= shape_[2]) {
        throw std::out_of_range("slice_time index out of range");
    }
    const std::int64_t ni = shape_[0];
    const std::int64_t nc = shape_[1];
    std::vector<float> out(static_cast<std::size_t>(ni * nc));
    for (std::int64_t il = 0; il < ni; ++il) {
        for (std::int64_t xl = 0; xl < nc; ++xl) {
            out[static_cast<std::size_t>(il * nc + xl)] =
                data_[static_cast<std::size_t>(il * nc * shape_[2] +
                                               xl * shape_[2] + sample_index)];
        }
    }
    return out;
}

}  // namespace pwb::geo3d_viz::joint
