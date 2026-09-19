// seismic_viewer.contracts — public interface self-containment, colormap
// registry invariants, unit-kind policy and selection-event vocabulary.

#include "sv_test.hpp"

#include <chrono>
#include <mutex>
#include <thread>
#include <vector>

#include <pwb/seismic_viewer/color_maps.hpp>
#include <pwb/seismic_viewer/seismic_slice_widget.hpp>
#include <pwb/seismic_viewer/slice_controller.hpp>
#include <pwb/seismic_viewer/slice_selection.hpp>

using namespace pwb::seismic_viewer;

TEST(colormap_registry_is_frozen) {
    const auto names = color_map_names();
    // BEGIN VIZ-D — the registry is now the colormap.py superset (V5
    // diff-set): the v3 trio keeps its frozen order at the front, the
    // colormap.py names follow; "heat" remains a C++-only extra. Exact
    // 256-entry LUT parity with the frozen Python builder is asserted in
    // viz_d.core (colormaps_match_frozen_python_luts).
    PWB_CHECK(names.size() == 9);
    PWB_CHECK(names[0] == "grayscale");
    PWB_CHECK(names[1] == "seismic");
    PWB_CHECK(names[2] == "seismic_r");
    PWB_CHECK(names[3] == "gray");
    PWB_CHECK(names[4] == "jet");
    PWB_CHECK(names[5] == "hsv");
    PWB_CHECK(names[6] == "viridis");
    PWB_CHECK(names[7] == "phase_wheel");
    PWB_CHECK(names[8] == "heat");
    // END VIZ-D
    for (const auto name : names) {
        const ColorLut lut = color_lut(name);
        PWB_CHECK_MSG(lut.size() == 256, "every colormap has 256 entries");
    }
}

TEST(colormap_endpoints_and_polarity) {
    const ColorLut gray = color_lut("grayscale");
    PWB_CHECK(gray[0] == (std::array<std::uint8_t, 3>{0, 0, 0}));
    PWB_CHECK(gray[255] == (std::array<std::uint8_t, 3>{255, 255, 255}));

    // Seismic polarity: low = blue, high = red, center ≈ white.
    const ColorLut seismic = color_lut("seismic");
    PWB_CHECK(seismic[0][2] > seismic[0][0]); // blue dominant at 0
    PWB_CHECK(seismic[255][0] > seismic[255][2]); // red dominant at 255
    PWB_CHECK(seismic[128][0] > 200 && seismic[128][1] > 200 && seismic[128][2] > 200);
    // Monotonic-ish green in heat ramp endpoints.
    const ColorLut heat = color_lut("heat");
    PWB_CHECK(heat[255] == (std::array<std::uint8_t, 3>{255, 255, 255}));
}

TEST(unknown_colormap_is_empty_not_a_throw) {
    PWB_CHECK(color_lut("viridis-not-in-v3").empty());
}

TEST(unit_kinds_never_cross_implicitly) {
    PWB_CHECK(unit_kind("ms") == UnitKind::time);
    PWB_CHECK(unit_kind("s") == UnitKind::time);
    PWB_CHECK(unit_kind("m") == UnitKind::length);
    PWB_CHECK(unit_kind("ft") == UnitKind::length);
    PWB_CHECK(unit_kind("km") == UnitKind::unknown);
    PWB_CHECK(unit_kind("") == UnitKind::unknown);
}

TEST(selection_event_vocabulary_defaults) {
    SliceSelectionEvent event;
    PWB_CHECK(event.origin.empty());
    PWB_CHECK(event.revision == 0);
    PWB_CHECK(event.axis == pwb::viz::VolumeAxis::inline_);
    PWB_CHECK(!event.has_point);
    PWB_CHECK(!event.has_time_range);
    PWB_CHECK(event.domain == pwb::viz::DepthDomainKind::time);
    PWB_CHECK(event.conversion == ConversionStatus::native);

    const LinearTimeDepth relation; // default {origin_ms=0, ms_per_m=1}
    PWB_CHECK(relation.origin_ms == 0.0 && relation.ms_per_m == 1.0);

    VolumeIdentity identity{"vol-1", 7};
    PWB_CHECK(identity.volume_id == "vol-1" && identity.version == 7);
}

TEST(controller_result_and_stats_vocabulary) {
    SliceResult result;
    PWB_CHECK(!result.ok && !result.degenerate);
    PWB_CHECK(result.values.empty() && result.indexed.empty());
    PWB_CHECK(result.diagnostic.empty());

    ControllerStats stats;
    PWB_CHECK(stats.submitted == 0 && stats.coalesced == 0 && stats.executed == 0 &&
              stats.delivered == 0 && stats.discarded_stale == 0 &&
              stats.read_failures == 0 && stats.cache_planes_peak == 0);
}

TEST(cache_capacity_is_at_least_one) {
    // A zero-cap request still yields a working controller with a 1-plane
    // cache (documented clamp); prove it end-to-end with two planes.
    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = {2, 2, 2};
    geometry.strides = {0, 0, 0};
    geometry.unit = "ms";
    std::vector<float> data(8, 0.0f);
    data[0] = -1.0f;
    data[7] = 1.0f;
    auto volume = pwb::viz::make_owning_volume(geometry, std::move(data));

    std::mutex mutex;
    std::vector<SliceResult> results;
    SliceController controller(std::move(volume), 0, [&](const SliceResult& r) {
        std::lock_guard<std::mutex> lock(mutex);
        results.push_back(r);
    });
    controller.submit(pwb::viz::VolumeAxis::inline_, 0, std::nullopt);
    controller.submit(pwb::viz::VolumeAxis::inline_, 1, std::nullopt);
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (std::chrono::steady_clock::now() < deadline) {
        std::lock_guard<std::mutex> lock(mutex);
        if (results.size() >= 2) {
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    PWB_CHECK(controller.cache_size() <= 1);
    PWB_CHECK(controller.epoch() == 0);
}

#include "sv_test_main.inc"
