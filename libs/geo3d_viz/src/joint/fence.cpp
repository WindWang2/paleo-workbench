// fence.cpp — fence model + shared amplitude strip extraction
// (fence.py @ 08851951, #60–#61).
#include "pwb/geo3d_viz/joint/fence.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <numeric>
#include <random>
#include <stdexcept>

namespace pwb::geo3d_viz::joint {

namespace {

std::vector<double> cumulative_lengths(
    const std::vector<std::array<double, 2>>& verts,
    std::vector<double>* seg_len) {
    std::vector<double> cum{0.0};
    seg_len->clear();
    for (std::size_t i = 0; i + 1 < verts.size(); ++i) {
        const double len = std::hypot(verts[i + 1][0] - verts[i][0],
                                      verts[i + 1][1] - verts[i][1]);
        seg_len->push_back(len);
        cum.push_back(cum.back() + len);
    }
    return cum;
}

// searchsorted(cum, t, side="right") - 1, clamped to the last segment.
std::size_t segment_at(const std::vector<double>& cum, double t,
                       std::size_t n_segments) {
    std::size_t j = 0;
    // upper_bound = first element > t; "right" side index minus one.
    j = static_cast<std::size_t>(
        std::upper_bound(cum.begin(), cum.end(), t) - cum.begin());
    j = j == 0 ? 0 : j - 1;
    return std::min(j, n_segments - 1);
}

}  // namespace

FenceSection::FenceSection(std::string fence_name,
                           std::vector<std::array<double, 2>> vertices,
                           std::string fence_id)
    : name(std::move(fence_name)),
      vertices_xy(std::move(vertices)),
      id(std::move(fence_id)) {
    if (vertices_xy.size() < 2) {
        throw std::invalid_argument("fence needs at least 2 vertices");
    }
    if (id.empty()) {
        // uuid4().hex[:12] parity: random 12-hex id (never frozen in
        // oracles — tests pass explicit ids).
        static thread_local std::mt19937_64 rng{std::random_device{}()};
        static constexpr char kHex[] = "0123456789abcdef";
        std::uniform_int_distribution<std::size_t> pick(0, 15);
        std::string generated;
        generated.reserve(12);
        for (int i = 0; i < 12; ++i) {
            generated.push_back(kHex[pick(rng)]);
        }
        id = std::move(generated);
    }
}

std::vector<std::array<double, 2>> sample_fence_polyline(
    const std::vector<std::array<double, 2>>& vertices_xy,
    std::int64_t n_along) {
    std::vector<double> seg_len;
    const std::vector<double> cum = cumulative_lengths(vertices_xy, &seg_len);
    const double total = seg_len.empty() ? 1.0
                         : std::accumulate(seg_len.begin(), seg_len.end(), 0.0);
    const std::int64_t n = n_along < 2 ? 2 : n_along;
    std::vector<std::array<double, 2>> samples(
        static_cast<std::size_t>(n));
    for (std::int64_t i = 0; i < n; ++i) {
        const double t = total * static_cast<double>(i) /
                         static_cast<double>(n - 1);
        const std::size_t j =
            segment_at(cum, t, seg_len.size());
        const double len = seg_len[j] > 1e-12 ? seg_len[j] : 1.0;
        const double local = (t - cum[j]) / len;
        samples[static_cast<std::size_t>(i)] = {
            vertices_xy[j][0] +
                local * (vertices_xy[j + 1][0] - vertices_xy[j][0]),
            vertices_xy[j][1] +
                local * (vertices_xy[j + 1][1] - vertices_xy[j][1])};
    }
    return samples;
}

FenceExtraction extract_fence_strip(
    const IVolumeAccess& volume, const FenceSection& fence,
    const SurveySpec& survey, std::int64_t n_along,
    const std::optional<std::vector<double>>& sample_axis,
    const VolumeRegistration* registration) {
    const auto shape = volume.shape();
    const std::int64_t ni = shape[0];
    const std::int64_t nx = shape[1];
    const std::int64_t nt = shape[2];
    if (ni <= 0 || nx <= 0 || nt <= 0) {
        throw std::invalid_argument("volume must be 3-D or VolumeAccess with "
                                    "shape");
    }

    std::vector<double> seg_len;
    const std::vector<double> cum =
        cumulative_lengths(fence.vertices_xy, &seg_len);
    const double total = seg_len.empty()
                             ? 1.0
                             : std::accumulate(seg_len.begin(),
                                               seg_len.end(), 0.0);
    const std::int64_t n = n_along < 2 ? 2 : n_along;
    std::vector<double> targets(static_cast<std::size_t>(n));
    for (std::int64_t i = 0; i < n; ++i) {
        targets[static_cast<std::size_t>(i)] =
            total * static_cast<double>(i) / static_cast<double>(n - 1);
    }
    const std::vector<std::array<double, 2>> samples_xy =
        sample_fence_polyline(fence.vertices_xy, n);

    const std::vector<float>* dense = volume.dense_data();
    FenceExtraction extraction;
    extraction.fence_id = fence.id;
    extraction.amplitude.assign(static_cast<std::size_t>(n * nt), 0.0f);
    extraction.arc_length_m = targets;

    // Distinct-column cache for the slice path: consecutive fence samples
    // frequently clamp onto the same inline.
    std::map<std::int64_t, std::vector<float>> inline_cache;
    for (std::int64_t i = 0; i < n; ++i) {
        const auto [x, y] = samples_xy[static_cast<std::size_t>(i)];
        std::int64_t ii = 0;
        std::int64_t xi = 0;
        if (registration != nullptr) {
            const auto [vi, vx] = registration->xy_to_volume_idx(x, y);
            ii = static_cast<std::int64_t>(
                std::llround(std::max(0.0, std::min(static_cast<double>(ni - 1),
                                                    vi))));
            xi = static_cast<std::int64_t>(
                std::llround(std::max(0.0, std::min(static_cast<double>(nx - 1),
                                                    vx))));
        } else {
            const auto [il, xl] = survey.xy_to_il_xl(x, y);
            const double il_step =
                survey.iline_step != 0 ? static_cast<double>(survey.iline_step)
                                       : 1.0;
            const double xl_step =
                survey.xline_step != 0
                    ? static_cast<double>(survey.xline_step)
                    : 1.0;
            ii = static_cast<std::int64_t>(std::llround(
                (il - static_cast<double>(survey.iline_start)) / il_step));
            xi = static_cast<std::int64_t>(std::llround(
                (xl - static_cast<double>(survey.xline_start)) / xl_step));
            ii = std::max<std::int64_t>(0, std::min(ni - 1, ii));
            xi = std::max<std::int64_t>(0, std::min(nx - 1, xi));
        }
        float* row = extraction.amplitude.data() +
                     static_cast<std::size_t>(i * nt);
        if (dense != nullptr) {
            const std::size_t src = static_cast<std::size_t>(
                (ii * nx + xi) * nt);
            std::copy_n(dense->begin() + static_cast<std::ptrdiff_t>(src),
                        static_cast<std::size_t>(nt), row);
        } else {
            // Source-backed volume: one inline read per distinct column.
            auto cached = inline_cache.find(ii);
            if (cached == inline_cache.end()) {
                cached = inline_cache
                             .emplace(ii, volume.slice_inline(ii))
                             .first;
            }
            const std::vector<float>& line = cached->second;
            const std::size_t row_index =
                std::min<std::size_t>(
                    static_cast<std::size_t>(xi),
                    line.size() / static_cast<std::size_t>(nt) - 1);
            std::copy_n(line.begin() +
                            static_cast<std::ptrdiff_t>(
                                row_index * static_cast<std::size_t>(nt)),
                        static_cast<std::size_t>(nt), row);
        }
    }

    if (sample_axis.has_value()) {
        extraction.sample_axis = *sample_axis;
    } else {
        extraction.sample_axis.resize(static_cast<std::size_t>(nt));
        for (std::int64_t t = 0; t < nt; ++t) {
            extraction.sample_axis[static_cast<std::size_t>(t)] =
                static_cast<double>(t);
        }
    }
    return extraction;
}

std::vector<std::array<double, 2>> well_to_well_path(
    const std::vector<std::array<double, 2>>& well_xy) {
    if (well_xy.size() < 2) {
        throw std::invalid_argument("need at least two wells");
    }
    return well_xy;
}

}  // namespace pwb::geo3d_viz::joint
