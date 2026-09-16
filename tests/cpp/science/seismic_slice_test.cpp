// science.seismic — three-axis slicing, asymmetric shapes/strides, bounds,
// missing values, color mapping, lifetime semantics and the frozen tiny.sgy
// oracle fixtures (test-plan G4).

#include "fixture_io.hpp"
#include "pwb_test.hpp"

#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <memory>
#include <vector>

#include <pwb/viz/seismic_volume.hpp>

using namespace pwb::viz;

namespace {

// Uniquely invertible sample pattern: value(i,j,k) encodes the coordinates.
inline float sample_value(std::int64_t i, std::int64_t j, std::int64_t k) {
    return static_cast<float>(10000 * i + 100 * j + k);
}

VolumeGeometryV1 c_order_geometry(std::array<std::int64_t, 3> shape) {
    VolumeGeometryV1 geometry;
    geometry.shape = shape;
    geometry.strides = {0, 0, 0}; // packed
    geometry.origin = {1.0, 10.0, 0.0}; // iline starts at 1, xline at 10
    geometry.step = {1.0, 2.0, 2.0};    // dt = 2 ms like tiny.sgy
    geometry.unit = "ms";
    geometry.missing_value = -999.25f;
    return geometry;
}

std::vector<float> filled(const VolumeGeometryV1& geometry) {
    std::vector<float> data(static_cast<std::size_t>(geometry.shape[0] * geometry.shape[1] *
                                                     geometry.shape[2]));
    for (std::int64_t i = 0; i < geometry.shape[0]; ++i) {
        for (std::int64_t j = 0; j < geometry.shape[1]; ++j) {
            for (std::int64_t k = 0; k < geometry.shape[2]; ++k) {
                const std::int64_t index =
                    (i * geometry.shape[1] + j) * geometry.shape[2] + k;
                data[static_cast<std::size_t>(index)] = sample_value(i, j, k);
            }
        }
    }
    return data;
}

} // namespace

TEST(three_axis_slices_match_expected_planes_c_order) {
    const VolumeGeometryV1 geometry = c_order_geometry({5, 3, 17});
    auto buffer = std::make_shared<const std::vector<float>>(filled(geometry));
    auto volume = make_in_memory_volume(geometry, buffer->data(), buffer);

    const std::int64_t n_il = 5, n_xl = 3, n_t = 17;
    std::vector<float> out(static_cast<std::size_t>(n_xl * n_t));
    for (const std::int64_t index : {std::int64_t{0}, n_il / 2, n_il - 1}) {
        PWB_CHECK(volume->read_slice(VolumeAxis::inline_, index, out) ==
                  static_cast<std::size_t>(n_xl * n_t));
        for (std::int64_t j = 0; j < n_xl; ++j) {
            for (std::int64_t k = 0; k < n_t; ++k) {
                PWB_CHECK(out[static_cast<std::size_t>(j * n_t + k)] ==
                          sample_value(index, j, k));
            }
        }
    }
    std::vector<float> crossline_out(static_cast<std::size_t>(n_il * n_t));
    for (const std::int64_t index : {std::int64_t{0}, n_xl - 1}) {
        PWB_CHECK(volume->read_slice(VolumeAxis::crossline, index, crossline_out) ==
                  static_cast<std::size_t>(n_il * n_t));
        for (std::int64_t i = 0; i < n_il; ++i) {
            for (std::int64_t k = 0; k < n_t; ++k) {
                PWB_CHECK(crossline_out[static_cast<std::size_t>(i * n_t + k)] ==
                          sample_value(i, index, k));
            }
        }
    }
    std::vector<float> time_out(static_cast<std::size_t>(n_il * n_xl));
    for (const std::int64_t index : {std::int64_t{0}, n_t / 2, n_t - 1}) {
        PWB_CHECK(volume->read_slice(VolumeAxis::sample, index, time_out) ==
                  static_cast<std::size_t>(n_il * n_xl));
        for (std::int64_t i = 0; i < n_il; ++i) {
            for (std::int64_t j = 0; j < n_xl; ++j) {
                PWB_CHECK(time_out[static_cast<std::size_t>(i * n_xl + j)] ==
                          sample_value(i, j, index));
            }
        }
    }
}

TEST(permuted_strides_crossline_major_matches_c_order_results) {
    const VolumeGeometryV1 geometry = c_order_geometry({5, 3, 17});
    const std::vector<float> c_order = filled(geometry);
    const std::int64_t n_il = 5, n_xl = 3, n_t = 17;

    // Crossline-major storage: (n_xl, n_il, n_t) layout, strides in elements.
    std::vector<float> permuted(static_cast<std::size_t>(c_order.size()));
    const std::array<std::int64_t, 3> permuted_strides = {n_t, n_il * n_t, 1};
    for (std::int64_t i = 0; i < n_il; ++i) {
        for (std::int64_t j = 0; j < n_xl; ++j) {
            for (std::int64_t k = 0; k < n_t; ++k) {
                permuted[static_cast<std::size_t>(j * n_il * n_t + i * n_t + k)] =
                    sample_value(i, j, k);
            }
        }
    }
    VolumeGeometryV1 permuted_geometry = geometry;
    permuted_geometry.strides = permuted_strides; // asymmetric, non-C-order
    auto permuted_buffer = std::make_shared<const std::vector<float>>(std::move(permuted));
    auto permuted_volume =
        make_in_memory_volume(permuted_geometry, permuted_buffer->data(), permuted_buffer);

    // Reference straight from the C-order buffer.
    auto c_buffer = std::make_shared<const std::vector<float>>(c_order);
    auto reference = make_in_memory_volume(geometry, c_buffer->data(), c_buffer);

    std::vector<float> from_permuted(static_cast<std::size_t>(n_xl * n_t));
    std::vector<float> from_reference(static_cast<std::size_t>(n_xl * n_t));
    for (std::int64_t i = 0; i < n_il; ++i) {
        PWB_CHECK(permuted_volume->read_slice(VolumeAxis::inline_, i, from_permuted) ==
                  from_permuted.size());
        PWB_CHECK(reference->read_slice(VolumeAxis::inline_, i, from_reference) ==
                  from_reference.size());
        PWB_CHECK(from_permuted == from_reference);
    }
    std::vector<float> permuted_plane(static_cast<std::size_t>(n_il * n_t));
    std::vector<float> reference_plane(static_cast<std::size_t>(n_il * n_t));
    for (std::int64_t j = 0; j < n_xl; ++j) {
        PWB_CHECK(permuted_volume->read_slice(VolumeAxis::crossline, j, permuted_plane) ==
                  permuted_plane.size());
        PWB_CHECK(reference->read_slice(VolumeAxis::crossline, j, reference_plane) ==
                  reference_plane.size());
        PWB_CHECK(permuted_plane == reference_plane);
    }
    std::vector<float> permuted_time(static_cast<std::size_t>(n_il * n_xl));
    std::vector<float> reference_time(static_cast<std::size_t>(n_il * n_xl));
    for (std::int64_t k = 0; k < n_t; ++k) {
        PWB_CHECK(permuted_volume->read_slice(VolumeAxis::sample, k, permuted_time) ==
                  permuted_time.size());
        PWB_CHECK(reference->read_slice(VolumeAxis::sample, k, reference_time) ==
                  reference_time.size());
        PWB_CHECK(permuted_time == reference_time);
    }
}

TEST(out_of_bounds_and_mismatched_spans_are_rejected_without_writes) {
    const VolumeGeometryV1 geometry = c_order_geometry({4, 4, 8});
    auto buffer = std::make_shared<const std::vector<float>>(filled(geometry));
    auto volume = make_in_memory_volume(geometry, buffer->data(), buffer);

    std::vector<float> out(16);
    std::vector<float> guard(16, -7.0f);
    for (const std::int64_t bad :
         {std::int64_t{-1}, std::int64_t{4}, std::int64_t{5},
          std::int64_t{100}}) {
        std::copy(guard.begin(), guard.end(), out.begin());
        PWB_CHECK(volume->read_slice(VolumeAxis::inline_, bad, out) == 0);
        PWB_CHECK(out == guard); // untouched on rejection
    }
    for (const std::int64_t bad : {std::int64_t{-1}, std::int64_t{4}}) {
        PWB_CHECK(volume->read_slice(VolumeAxis::crossline, bad, out) == 0);
    }
    // NOTE: the sample axis has 8 planes here, so 4 is in-bounds for it.
    for (const std::int64_t bad : {std::int64_t{-1}, std::int64_t{8}}) {
        PWB_CHECK(volume->read_slice(VolumeAxis::sample, bad, out) == 0);
    }
    // Wrong span size.
    std::vector<float> wrong(3);
    PWB_CHECK(volume->read_slice(VolumeAxis::inline_, 0, wrong) == 0);
}

TEST(missing_values_and_nan_flow_through_slices) {
    VolumeGeometryV1 geometry = c_order_geometry({3, 3, 4});
    std::vector<float> data = filled(geometry);
    data[0] = -999.25f;            // declared missing value
    data[5] = std::nanf("");       // NaN
    auto buffer = std::make_shared<const std::vector<float>>(std::move(data));
    auto volume = make_in_memory_volume(geometry, buffer->data(), buffer);

    std::vector<float> out(12);
    PWB_CHECK(volume->read_slice(VolumeAxis::inline_, 0, out) == 12);
    PWB_CHECK(out[0] == -999.25f);
    PWB_CHECK(std::isnan(out[5]));
}

TEST(geometry_maps_index_space_to_physical_axes) {
    const VolumeGeometryV1 geometry = c_order_geometry({5, 3, 17});
    PWB_CHECK(geometry.axis_value(VolumeAxis::inline_, 0) == 1.0);
    PWB_CHECK(geometry.axis_value(VolumeAxis::inline_, 4) == 5.0);
    PWB_CHECK(geometry.axis_value(VolumeAxis::crossline, 2) == 14.0); // 10 + 2*2
    PWB_CHECK(geometry.axis_value(VolumeAxis::sample, 3) == 6.0);     // 0 + 3*2 ms
    const auto [t0, t1] = geometry.axis_extent(VolumeAxis::sample);
    PWB_CHECK(t0 == 0.0 && t1 == 32.0);

    VolumeGeometryV1 negative = geometry;
    negative.origin = {10.0, 0.0, 100.0};
    negative.step = {-1.0, 1.0, -2.0}; // reverse-sampled axis
    PWB_CHECK(negative.axis_value(VolumeAxis::inline_, 0) == 10.0);
    PWB_CHECK(negative.axis_value(VolumeAxis::inline_, 4) == 6.0);
    const auto [lo, hi] = negative.axis_extent(VolumeAxis::inline_);
    PWB_CHECK(lo == 6.0 && hi == 10.0);
}

TEST(slice_lifetime_guard_keeps_storage_alive_and_reads_are_not_cached) {
    auto owner = std::make_shared<std::vector<float>>();
    *owner = filled(c_order_geometry({4, 4, 8}));
    std::weak_ptr<const std::vector<float>> watch = owner;
    {
        auto volume = make_in_memory_volume(c_order_geometry({4, 4, 8}), owner->data(), owner);
        std::vector<float> out(32);
        PWB_CHECK(volume->read_slice(VolumeAxis::inline_, 0, out) == 32);
        // Mutating the backing buffer must be visible on the next read:
        // read_slice reads through the view, it does not cache slice copies.
        (*owner)[0] = 12345.0f;
        PWB_CHECK(volume->read_slice(VolumeAxis::inline_, 0, out) == 32);
        PWB_CHECK(out[0] == 12345.0f);
        owner.reset(); // drop the caller's reference
        PWB_CHECK(!watch.expired()); // volume lifetime guard still owns it
        std::vector<float> sample_out(16);
        PWB_CHECK(volume->read_slice(VolumeAxis::sample, 0, sample_out) ==
                  16);
    }
    PWB_CHECK(watch.expired()); // released with the volume
}

TEST(owning_volume_manages_its_storage) {
    VolumeGeometryV1 geometry = c_order_geometry({4, 4, 8});
    std::vector<float> data = filled(geometry);
    auto volume = make_owning_volume(geometry, std::move(data));
    PWB_CHECK(volume->geometry().ownership == VolumeOwnership::owning);
    PWB_CHECK(volume->lifetime() != nullptr);
    std::vector<float> out(32);
    PWB_CHECK(volume->read_slice(VolumeAxis::inline_, 2, out) == 32);
    PWB_CHECK(out[0] == sample_value(2, 0, 0));
    PWB_CHECK(volume->chunk_plan().empty()); // in-memory backend has no chunks
}

TEST(indexed8_matches_oracle_semantics) {
    { // finite-only stretch, truncation, NaN -> 0
        const std::vector<float> slice = {0.0f, 1.0f, 2.0f, 4.0f, std::nanf("")};
        const IndexedSlice mapped = map_slice_to_indexed8(slice);
        PWB_CHECK(!mapped.degenerate);
        PWB_CHECK(mapped.value_min == 0.0 && mapped.value_max == 4.0);
        // v -> (v-0) * 255/4 truncated: 0, 63.75->63, 127.5->127, 255, nan->0
        PWB_CHECK(mapped.pixels[0] == 0);
        PWB_CHECK(mapped.pixels[1] == 63);
        PWB_CHECK(mapped.pixels[2] == 127);
        PWB_CHECK(mapped.pixels[3] == 255);
        PWB_CHECK(mapped.pixels[4] == 0);
    }
    { // explicit value range overrides the stretch
        const std::vector<float> slice = {-10.0f, 0.0f, 10.0f};
        const IndexedSlice mapped =
            map_slice_to_indexed8(slice, std::make_pair(-10.0, 10.0));
        PWB_CHECK(mapped.value_min == -10.0 && mapped.value_max == 10.0);
        PWB_CHECK(mapped.pixels[0] == 0);
        PWB_CHECK(mapped.pixels[1] == 127); // 127.5 truncates to 127
        PWB_CHECK(mapped.pixels[2] == 255);
    }
    { // constant slice is degenerate
        const std::vector<float> constant = {3.5f, 3.5f};
        const IndexedSlice mapped = map_slice_to_indexed8(constant);
        PWB_CHECK(mapped.degenerate);
        PWB_CHECK(mapped.value_min == 0.0 && mapped.value_max == 0.0);
        PWB_CHECK((mapped.pixels == std::vector<std::uint8_t>{0, 0}));
    }
    { // all-invalid slice is degenerate
        const std::vector<float> invalid = {std::nanf(""), std::nanf("")};
        const IndexedSlice mapped = map_slice_to_indexed8(invalid);
        PWB_CHECK(mapped.degenerate);
    }
}

TEST(tiny_sgy_fixture_slices_and_indexed8_match_python_oracle) {
    const std::filesystem::path dir = fixture_io::fixture_root() / "seismic" / "tiny_sgy";
    fixture_io::Manifest manifest;
    PWB_CHECK(fixture_io::parse_manifest(fixture_io::read_text(dir / "manifest.json"),
                                         manifest));
    const std::vector<double>& shape = manifest.arrays.at("shape");
    const std::int64_t n_il = static_cast<std::int64_t>(shape[0]);
    const std::int64_t n_xl = static_cast<std::int64_t>(shape[1]);
    const std::int64_t n_t = static_cast<std::int64_t>(shape[2]);
    // The fixture stores the volume crossline-major (permuted strides).
    const std::vector<float> payload = fixture_io::read_f32(dir / "volume_xl_major.f32");
    PWB_CHECK(payload.size() ==
              static_cast<std::size_t>(n_il * n_xl * n_t));

    VolumeGeometryV1 geometry;
    geometry.shape = {n_il, n_xl, n_t};
    geometry.strides = {n_t, n_il * n_t, 1}; // crossline-major
    geometry.origin = {manifest.number("iline_start", 1.0),
                       manifest.number("xline_start", 1.0), 0.0};
    geometry.step = {manifest.number("iline_step", 1.0),
                     manifest.number("xline_step", 1.0), manifest.number("dt_ms", 2.0)};
    geometry.unit = "ms";
    auto buffer = std::make_shared<const std::vector<float>>(payload);
    auto volume = make_in_memory_volume(geometry, buffer->data(), buffer);

    PWB_CHECK(geometry.axis_value(VolumeAxis::sample, n_t - 1) ==
              manifest.number("last_sample_ms", 62.0));

    // Byte-exact slice comparison for one plane per axis.
    const std::vector<float> expected_inline =
        fixture_io::read_f32(dir / "expected_inline.f32");
    const std::vector<float> expected_crossline =
        fixture_io::read_f32(dir / "expected_crossline.f32");
    const std::vector<float> expected_sample =
        fixture_io::read_f32(dir / "expected_sample.f32");
    std::vector<float> out(expected_inline.size());
    PWB_CHECK(volume->read_slice(VolumeAxis::inline_, 3, out) == out.size());
    PWB_CHECK(out == expected_inline);
    out.resize(expected_crossline.size());
    PWB_CHECK(volume->read_slice(VolumeAxis::crossline, 5, out) == out.size());
    PWB_CHECK(out == expected_crossline);
    out.resize(expected_sample.size());
    PWB_CHECK(volume->read_slice(VolumeAxis::sample, 16, out) == out.size());
    PWB_CHECK(out == expected_sample);

    // indexed8 color mapping against the Python oracle (inline plane 3).
    // The oracle file stores the indexed bytes as float32 values.
    const std::vector<float> expected_indexed_f32 =
        fixture_io::read_f32(dir / "expected_inline_indexed8.f32");
    std::vector<std::uint8_t> expected_indexed;
    expected_indexed.reserve(expected_indexed_f32.size());
    for (const float value : expected_indexed_f32) {
        expected_indexed.push_back(static_cast<std::uint8_t>(value));
    }
    std::vector<float> inline_plane(expected_inline.size());
    PWB_CHECK(volume->read_slice(VolumeAxis::inline_, 3, inline_plane) ==
              inline_plane.size());
    const IndexedSlice mapped =
        map_slice_to_indexed8(std::span<const float>(inline_plane));
    PWB_CHECK(mapped.pixels.size() == expected_indexed.size());
    std::size_t mismatches = 0;
    for (std::size_t i = 0; i < mapped.pixels.size(); ++i) {
        if (mapped.pixels[i] != static_cast<std::uint8_t>(expected_indexed[i])) {
            ++mismatches;
        }
    }
    if (mismatches != 0) {
        std::printf("indexed8 mismatches: %zu / %zu\n", mismatches, mapped.pixels.size());
    }
    PWB_CHECK_MSG(mismatches == 0, "indexed8 mismatch count != 0 (see stdout)");
}

#include "pwb_test_main.inc"
