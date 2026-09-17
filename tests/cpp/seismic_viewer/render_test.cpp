// seismic_viewer.render — numeric slice audit through SliceController against
// the frozen tiny_sgy oracle (read-only) and synthetic asymmetric geometries:
// three-axis planes, permuted strides, non-default origin/step, NaN/constant
// degeneracy, explicit ranges. Qt-free.

#include "sv_fixture_io.hpp"
#include "sv_test.hpp"

#include <atomic>
#include <chrono>
#include <cmath>
#include <mutex>
#include <thread>
#include <vector>

#include <pwb/seismic_viewer/slice_controller.hpp>

using namespace pwb::seismic_viewer;
using namespace std::chrono_literals;

namespace {

struct Sink {
    std::mutex mutex;
    std::vector<SliceResult> results;
    void operator()(const SliceResult& r) {
        std::lock_guard<std::mutex> lock(mutex);
        results.push_back(r);
    }
    [[nodiscard]] std::size_t size() {
        std::lock_guard<std::mutex> lock(mutex);
        return results.size();
    }
    [[nodiscard]] std::vector<SliceResult> snapshot() {
        std::lock_guard<std::mutex> lock(mutex);
        return results;
    }
};

template <typename Predicate>
bool wait_until(Predicate&& predicate, std::chrono::milliseconds timeout = 5000ms) {
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline) {
        if (predicate()) {
            return true;
        }
        std::this_thread::sleep_for(1ms);
    }
    return predicate();
}

// Submits one request and waits for its delivery; returns the result.
SliceResult render_one(SliceController& controller, Sink& sink, std::size_t expected,
                       pwb::viz::VolumeAxis axis, std::int64_t index,
                       std::optional<std::pair<double, double>> range = std::nullopt) {
    controller.submit(axis, index, range);
    PWB_CHECK(wait_until([&] { return sink.size() == expected; }));
    const SliceResult result = sink.snapshot().back();
    PWB_CHECK(result.axis == axis && result.index == index);
    return result;
}

} // namespace

TEST(tiny_sgy_three_axis_planes_match_python_oracle_bytes) {
    pwb::viz::VolumeGeometryV1 geometry;
    auto volume = sv_fixture_io::load_tiny_sgy(geometry);
    PWB_CHECK_MSG(volume != nullptr, "frozen tiny_sgy fixture must load");

    sv_fixture_io::Manifest manifest;
    PWB_CHECK(sv_fixture_io::parse_manifest(
        sv_fixture_io::read_text(sv_fixture_io::science_fixture_root() / "seismic" /
                                 "tiny_sgy" / "manifest.json"),
        manifest));
    const std::int64_t inline_index = 3;
    const std::int64_t crossline_index = 5;
    const std::int64_t sample_index = 16;

    const std::filesystem::path dir =
        sv_fixture_io::science_fixture_root() / "seismic" / "tiny_sgy";
    const std::vector<float> expected_inline =
        sv_fixture_io::read_f32(dir / "expected_inline.f32");
    const std::vector<float> expected_crossline =
        sv_fixture_io::read_f32(dir / "expected_crossline.f32");
    const std::vector<float> expected_sample =
        sv_fixture_io::read_f32(dir / "expected_sample.f32");
    PWB_CHECK(!expected_inline.empty() && !expected_crossline.empty() &&
              !expected_sample.empty());

    Sink sink;
    SliceController controller(std::move(volume), 4, [&](const SliceResult& r) { sink(r); });

    const SliceResult inline_plane =
        render_one(controller, sink, 1, pwb::viz::VolumeAxis::inline_, inline_index);
    PWB_CHECK(inline_plane.ok);
    PWB_CHECK(inline_plane.values == expected_inline);

    const SliceResult crossline_plane =
        render_one(controller, sink, 2, pwb::viz::VolumeAxis::crossline, crossline_index);
    PWB_CHECK(crossline_plane.ok);
    PWB_CHECK(crossline_plane.values == expected_crossline);

    const SliceResult sample_plane =
        render_one(controller, sink, 3, pwb::viz::VolumeAxis::sample, sample_index);
    PWB_CHECK(sample_plane.ok);
    PWB_CHECK(sample_plane.values == expected_sample);

    // Physical coordinate math against the manifest (origin/step/unit).
    PWB_CHECK(geometry.axis_value(pwb::viz::VolumeAxis::sample, 31) ==
              manifest.number("last_sample_ms", 62.0));
    PWB_CHECK(geometry.axis_value(pwb::viz::VolumeAxis::inline_, 0) ==
              manifest.number("iline_start", 1.0));
    PWB_CHECK(geometry.axis_value(pwb::viz::VolumeAxis::crossline, 7) ==
              manifest.number("xline_start", 1.0) +
                  7.0 * manifest.number("xline_step", 1.0));
}

TEST(tiny_sgy_inline_indexed8_matches_oracle_and_explicit_range_overrides) {
    pwb::viz::VolumeGeometryV1 geometry;
    auto volume = sv_fixture_io::load_tiny_sgy(geometry);
    PWB_CHECK(volume != nullptr);

    const std::filesystem::path dir =
        sv_fixture_io::science_fixture_root() / "seismic" / "tiny_sgy";
    const std::vector<float> expected_indexed_f32 =
        sv_fixture_io::read_f32(dir / "expected_inline_indexed8.f32");
    PWB_CHECK(!expected_indexed_f32.empty());
    std::vector<std::uint8_t> expected_indexed;
    expected_indexed.reserve(expected_indexed_f32.size());
    for (const float value : expected_indexed_f32) {
        expected_indexed.push_back(static_cast<std::uint8_t>(value));
    }

    Sink sink;
    SliceController controller(std::move(volume), 4, [&](const SliceResult& r) { sink(r); });
    const SliceResult plane =
        render_one(controller, sink, 1, pwb::viz::VolumeAxis::inline_, 3);
    PWB_CHECK(plane.ok);
    PWB_CHECK(plane.indexed.size() == expected_indexed.size());
    std::size_t mismatches = 0;
    for (std::size_t i = 0; i < plane.indexed.size(); ++i) {
        if (plane.indexed[i] != expected_indexed[i]) {
            ++mismatches;
        }
    }
    PWB_CHECK_MSG(mismatches == 0, "indexed8 bytes differ from the Python oracle");

    // Explicit range re-stretches the same plane (numbers = the manifest's
    // frozen auto stretch values, applied explicitly; the point is that the
    // reported range and bytes follow the request, not the cache).
    const SliceResult stretched =
        render_one(controller, sink, 2, pwb::viz::VolumeAxis::inline_, 3,
                   std::make_pair(-2.167734146118164, 2.459895610809326));
    PWB_CHECK(stretched.ok);
    PWB_CHECK(!stretched.degenerate);
    PWB_CHECK(std::abs(stretched.value_min + 2.167734146118164) < 1e-12);
    PWB_CHECK(std::abs(stretched.value_max - 2.459895610809326) < 1e-12);
}

TEST(asymmetric_permuted_geometry_planes_are_exact) {
    // 5 x 3 x 17, crossline-major permuted strides, non-default origin/step
    // (inline starts at 1 step 1; crossline starts at 10 step 2; sample dt 2).
    const std::int64_t n_il = 5, n_xl = 3, n_t = 17;
    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = {n_il, n_xl, n_t};
    geometry.strides = {n_t, n_il * n_t, 1}; // crossline-major permutation
    geometry.origin = {1.0, 10.0, 0.0};
    geometry.step = {1.0, 2.0, 2.0};
    geometry.unit = "ms";

    std::vector<float> storage(static_cast<std::size_t>(n_il * n_xl * n_t));
    const auto pattern = [&](std::int64_t i, std::int64_t j, std::int64_t k) {
        return static_cast<float>(10000 * i + 100 * j + k);
    };
    for (std::int64_t j = 0; j < n_xl; ++j) {
        for (std::int64_t i = 0; i < n_il; ++i) {
            for (std::int64_t k = 0; k < n_t; ++k) {
                storage[static_cast<std::size_t>(j * n_il * n_t + i * n_t + k)] =
                    pattern(i, j, k);
            }
        }
    }
    auto buffer = std::make_shared<const std::vector<float>>(std::move(storage));
    auto volume =
        pwb::viz::make_in_memory_volume(geometry, buffer->data(), buffer);

    Sink sink;
    SliceController controller(std::move(volume), 4, [&](const SliceResult& r) { sink(r); });

    // Inline plane 2: rows over crossline, columns over sample.
    const SliceResult inline_plane =
        render_one(controller, sink, 1, pwb::viz::VolumeAxis::inline_, 2);
    PWB_CHECK(inline_plane.rows == n_xl && inline_plane.cols == n_t);
    for (std::int64_t j = 0; j < n_xl; ++j) {
        for (std::int64_t k = 0; k < n_t; ++k) {
            PWB_CHECK(inline_plane.values[static_cast<std::size_t>(j * n_t + k)] ==
                      pattern(2, j, k));
        }
    }
    // Crossline plane 1: rows over inline, columns over sample.
    const SliceResult crossline_plane =
        render_one(controller, sink, 2, pwb::viz::VolumeAxis::crossline, 1);
    PWB_CHECK(crossline_plane.rows == n_il && crossline_plane.cols == n_t);
    for (std::int64_t i = 0; i < n_il; ++i) {
        for (std::int64_t k = 0; k < n_t; ++k) {
            PWB_CHECK(
                crossline_plane.values[static_cast<std::size_t>(i * n_t + k)] ==
                pattern(i, 1, k));
        }
    }
    // Sample plane 9: rows over inline, columns over crossline.
    const SliceResult sample_plane =
        render_one(controller, sink, 3, pwb::viz::VolumeAxis::sample, 9);
    PWB_CHECK(sample_plane.rows == n_il && sample_plane.cols == n_xl);
    for (std::int64_t i = 0; i < n_il; ++i) {
        for (std::int64_t j = 0; j < n_xl; ++j) {
            PWB_CHECK(sample_plane.values[static_cast<std::size_t>(i * n_xl + j)] ==
                      pattern(i, j, 9));
        }
    }

    // Non-default origin/step on every axis; negative-step axis stays ordered.
    PWB_CHECK(geometry.axis_value(pwb::viz::VolumeAxis::crossline, 2) == 14.0);
    PWB_CHECK(geometry.axis_value(pwb::viz::VolumeAxis::sample, 8) == 16.0);
    pwb::viz::VolumeGeometryV1 reversed = geometry;
    reversed.origin = {10.0, 0.0, 100.0};
    reversed.step = {-1.0, 1.0, -2.0};
    const auto [lo, hi] = reversed.axis_extent(pwb::viz::VolumeAxis::inline_);
    PWB_CHECK(lo == 6.0 && hi == 10.0);
}

TEST(nan_constant_and_all_invalid_planes_are_degenerate_and_visible) {
    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = {2, 2, 4};
    geometry.strides = {0, 0, 0};
    geometry.unit = "ms";

    { // constant plane
        std::vector<float> data(16, 3.5f);
        Sink sink;
        SliceController controller(
            pwb::viz::make_owning_volume(geometry, std::move(data)), 2,
            [&](const SliceResult& r) { sink(r); });
        const SliceResult plane =
            render_one(controller, sink, 1, pwb::viz::VolumeAxis::inline_, 0);
        PWB_CHECK(plane.ok);
        PWB_CHECK_MSG(plane.degenerate, "constant plane must be flagged");
        PWB_CHECK(!plane.diagnostic.empty());
        for (const std::uint8_t pixel : plane.indexed) {
            PWB_CHECK(pixel == 0); // frozen all-zero plane
        }
    }
    { // all non-finite plane
        std::vector<float> data(16, std::nanf(""));
        Sink sink;
        SliceController controller(
            pwb::viz::make_owning_volume(geometry, std::move(data)), 2,
            [&](const SliceResult& r) { sink(r); });
        const SliceResult plane =
            render_one(controller, sink, 1, pwb::viz::VolumeAxis::inline_, 1);
        PWB_CHECK(plane.ok);
        PWB_CHECK_MSG(plane.degenerate, "all-invalid plane must be flagged");
        PWB_CHECK(!plane.diagnostic.empty());
    }
    { // mixed NaN: finite stretch ignores NaN, NaN renders index 0
        std::vector<float> data{0.0f, 1.0f, 2.0f, 4.0f, std::nanf(""),
                                0.0f, 0.0f, 0.0f, 0.0f, 0.0f,
                                0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
        PWB_CHECK(data.size() == 16);
        Sink sink;
        SliceController controller(
            pwb::viz::make_owning_volume(geometry, std::move(data)), 2,
            [&](const SliceResult& r) { sink(r); });
        const SliceResult plane =
            render_one(controller, sink, 1, pwb::viz::VolumeAxis::inline_, 0);
        PWB_CHECK(plane.ok && !plane.degenerate);
        PWB_CHECK(plane.value_min == 0.0 && plane.value_max == 4.0);
        PWB_CHECK(plane.indexed[0] == 0);
        PWB_CHECK(plane.indexed[1] == 63);  // 1.0 * 255/4 = 63.75 trunc
        PWB_CHECK(plane.indexed[2] == 127); // 127.5 trunc
        PWB_CHECK(plane.indexed[3] == 255);
        PWB_CHECK(plane.indexed[4] == 0);   // NaN -> 0 (frozen oracle rule)
    }
}

TEST(explicit_range_quantization_and_guards) {
    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = {1, 1, 3};
    geometry.strides = {0, 0, 0};
    geometry.unit = "ms";
    Sink sink;
    SliceController controller(
        pwb::viz::make_owning_volume(geometry, std::vector<float>{-10.0f, 0.0f, 10.0f}),
        2, [&](const SliceResult& r) { sink(r); });
    const SliceResult plane = render_one(controller, sink, 1,
                                         pwb::viz::VolumeAxis::inline_, 0,
                                         std::make_pair(-10.0, 10.0));
    PWB_CHECK(plane.ok && !plane.degenerate);
    PWB_CHECK(plane.indexed.size() == 3);
    PWB_CHECK(plane.indexed[0] == 0);
    PWB_CHECK(plane.indexed[1] == 127); // 127.5 truncates toward zero
    PWB_CHECK(plane.indexed[2] == 255);

    // Degenerate explicit range (min == max) is visible, not a white plane.
    const SliceResult degenerate = render_one(controller, sink, 2,
                                              pwb::viz::VolumeAxis::inline_, 0,
                                              std::make_pair(1.0, 1.0));
    PWB_CHECK(degenerate.ok);
    PWB_CHECK(degenerate.degenerate);
    for (const std::uint8_t pixel : degenerate.indexed) {
        PWB_CHECK(pixel == 0);
    }
}

#include "sv_test_main.inc"
