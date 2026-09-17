// seismic_viewer.controller — scheduling semantics with controlled-delay
// sources and explicit barriers: coalescing, generation/epoch staleness,
// serialized reads, bounded cache, failure recovery, shutdown quietness.
// The doubles only delay/observe; every byte comes from the real backend.

#include "sv_test.hpp"
#include "sv_test_sources.hpp"

#include <atomic>
#include <chrono>
#include <mutex>
#include <thread>
#include <vector>

#include <pwb/seismic_viewer/slice_controller.hpp>

using namespace pwb::seismic_viewer;
using namespace std::chrono_literals;

namespace {

struct SinkCollector {
    std::mutex mutex;
    std::vector<SliceResult> results;

    void operator()(const SliceResult& result) {
        std::lock_guard<std::mutex> lock(mutex);
        results.push_back(result);
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

pwb::viz::VolumeGeometryV1 tiny_geometry() {
    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = {8, 8, 32};
    geometry.strides = {0, 0, 0};
    geometry.origin = {1.0, 1.0, 0.0};
    geometry.step = {1.0, 1.0, 2.0};
    geometry.unit = "ms";
    return geometry;
}

// Uniquely invertible pattern: value(i, j, k) = 10000*i + 100*j + k.
float pattern_value(std::int64_t i, std::int64_t j, std::int64_t k) {
    return static_cast<float>(10000 * i + 100 * j + k);
}

std::vector<float> pattern_data() {
    const pwb::viz::VolumeGeometryV1 geometry = tiny_geometry();
    std::vector<float> data(static_cast<std::size_t>(geometry.shape[0] *
                                                    geometry.shape[1] *
                                                    geometry.shape[2]));
    for (std::int64_t i = 0; i < geometry.shape[0]; ++i) {
        for (std::int64_t j = 0; j < geometry.shape[1]; ++j) {
            for (std::int64_t k = 0; k < geometry.shape[2]; ++k) {
                data[static_cast<std::size_t>((i * geometry.shape[1] + j) *
                                              geometry.shape[2] + k)] =
                    pattern_value(i, j, k);
            }
        }
    }
    return data;
}

std::shared_ptr<pwb::viz::ISeismicVolume> pattern_source() {
    return pwb::viz::make_owning_volume(tiny_geometry(), pattern_data());
}

} // namespace

TEST(delivers_fresh_plane_from_real_backend) {
    SinkCollector sink;
    SliceController controller(pattern_source(), 4,
                               [&](const SliceResult& r) { sink(r); });
    controller.submit(pwb::viz::VolumeAxis::inline_, 3, std::nullopt);
    PWB_CHECK(wait_until([&] { return sink.size() == 1; }));

    const SliceResult result = sink.snapshot().front();
    PWB_CHECK(result.ok);
    PWB_CHECK(!result.degenerate);
    PWB_CHECK(result.axis == pwb::viz::VolumeAxis::inline_);
    PWB_CHECK(result.index == 3);
    PWB_CHECK(result.rows == 8 && result.cols == 32);
    PWB_CHECK(result.values.size() == 8 * 32);
    PWB_CHECK(result.indexed.size() == 8 * 32);
    // Byte identity with the expected canonical plane (pattern formula).
    for (std::int64_t j = 0; j < 8; ++j) {
        for (std::int64_t k = 0; k < 32; ++k) {
            PWB_CHECK(result.values[static_cast<std::size_t>(j * 32 + k)] ==
                      pattern_value(3, j, k));
        }
    }
    const ControllerStats stats = controller.stats();
    PWB_CHECK(stats.submitted == 1 && stats.delivered == 1);
    PWB_CHECK(stats.discarded_stale == 0 && stats.read_failures == 0);
}

TEST(fast_drags_coalesce_into_bounded_reads) {
    // Deterministic window: the first read ENTERS its delay, then 29 rapid
    // submits land while it sleeps — they must merge into ONE queued request.
    auto observing = std::make_shared<sv_test_sources::ObservingVolume>(
        pattern_source(), std::chrono::milliseconds(200));
    SinkCollector sink;
    SliceController controller(observing, 4, [&](const SliceResult& r) { sink(r); });

    controller.submit(pwb::viz::VolumeAxis::sample, 0, std::nullopt);
    PWB_CHECK(wait_until([&] { return observing->reads_entered() >= 1; }));
    for (std::int64_t index = 1; index <= 29; ++index) {
        controller.submit(pwb::viz::VolumeAxis::sample, index, std::nullopt);
    }
    PWB_CHECK(wait_until([&] {
        const auto results = sink.snapshot();
        return !results.empty() && results.back().index == 29 && results.back().ok;
    }));

    const ControllerStats stats = controller.stats();
    PWB_CHECK(stats.submitted == 30);
    PWB_CHECK_MSG(stats.executed <= 3,
                  "in-window submits must merge into very few reads");
    PWB_CHECK_MSG(stats.coalesced >= 26, "coalescing counter must show the merges");
    PWB_CHECK(stats.delivered <= 3); // at most: superseded-first + mid + newest
    PWB_CHECK(stats.discarded_stale >= 1);
    // Bounded work per interaction: one queued + one in-flight, serialized.
    PWB_CHECK(observing->overlapped_reads() == 0);
}

TEST(late_result_cannot_overwrite_new_source) {
    // Source A's read is slow and in flight when the host swaps to source B:
    // A's result must be discarded on epoch mismatch; B's fresh plane wins.
    auto slow_a = std::make_shared<sv_test_sources::ObservingVolume>(
        pattern_source(), std::chrono::milliseconds(150));
    auto b = std::make_shared<sv_test_sources::ObservingVolume>(
        pattern_source(), std::chrono::milliseconds(1));

    SinkCollector sink;
    SliceController controller(slow_a, 4, [&](const SliceResult& r) { sink(r); });
    const std::uint64_t epoch_before = controller.epoch();

    controller.submit(pwb::viz::VolumeAxis::inline_, 3, std::nullopt);
    PWB_CHECK(wait_until([&] { return slow_a->reads_entered() >= 1; }));

    controller.set_source(b); // source swap: epoch bump, queue+cache cleared
    PWB_CHECK(controller.epoch() == epoch_before + 1);
    PWB_CHECK(controller.cache_size() == 0);
    controller.submit(pwb::viz::VolumeAxis::inline_, 5, std::nullopt);

    PWB_CHECK(wait_until([&] {
        const auto results = sink.snapshot();
        return !results.empty() && results.back().index == 5 && results.back().ok &&
               results.back().epoch == epoch_before + 1;
    }));
    // A's in-flight read finishes during the wait above, but its result never
    // reaches the sink: every delivered plane carries the NEW epoch.
    for (const SliceResult& result : sink.snapshot()) {
        PWB_CHECK_MSG(result.epoch == epoch_before + 1,
                      "no old-epoch result may be delivered after a swap");
    }
    PWB_CHECK(controller.stats().discarded_stale >= 1);
    // The delivered plane is genuinely B's data (pattern formula at i=5).
    const SliceResult delivered = sink.snapshot().back();
    for (std::int64_t j = 0; j < 8; ++j) {
        for (std::int64_t k = 0; k < 32; ++k) {
            PWB_CHECK(delivered.values[static_cast<std::size_t>(j * 32 + k)] ==
                      pattern_value(5, j, k));
        }
    }
}

TEST(reads_are_strictly_serialized) {
    auto observing = std::make_shared<sv_test_sources::ObservingVolume>(
        pattern_source(), std::chrono::milliseconds(8));
    SinkCollector sink;
    SliceController controller(observing, 4, [&](const SliceResult& r) { sink(r); });
    for (std::int64_t index = 0; index < 32; ++index) {
        controller.submit(pwb::viz::VolumeAxis::sample, index, std::nullopt);
    }
    PWB_CHECK(wait_until([&] {
        const auto results = sink.snapshot();
        return !results.empty() && results.back().index == 31 && results.back().ok;
    }, 8000ms));
    PWB_CHECK(observing->reads_entered() == observing->total_reads()); // none stuck
    PWB_CHECK_MSG(observing->overlapped_reads() == 0,
                  "read_slice calls must never overlap (single worker)");
}

TEST(failures_are_visible_then_recoverable) {
    std::atomic<bool> fail{true};
    auto flaky =
        std::make_shared<sv_test_sources::FlakyVolume>(pattern_source(), &fail);
    SinkCollector sink;
    SliceController controller(flaky, 4, [&](const SliceResult& r) { sink(r); });

    controller.submit(pwb::viz::VolumeAxis::inline_, 2, std::nullopt);
    PWB_CHECK(wait_until([&] { return sink.size() == 1; }));
    {
        const SliceResult failed = sink.snapshot().front();
        PWB_CHECK(!failed.ok);
        PWB_CHECK(!failed.diagnostic.empty());
        PWB_CHECK(failed.values.empty());
    }

    fail.store(false); // backend recovers; the controller keeps serving
    controller.submit(pwb::viz::VolumeAxis::inline_, 2, std::nullopt);
    PWB_CHECK(wait_until([&] { return sink.size() == 2; }));
    PWB_CHECK(sink.snapshot().back().ok);
    PWB_CHECK(controller.stats().read_failures == 1);
    PWB_CHECK(controller.stats().delivered == 2); // failures are delivered too
}

TEST(null_and_empty_sources_fail_with_diagnostics) {
    SinkCollector sink;
    SliceController controller(nullptr, 4, [&](const SliceResult& r) { sink(r); });
    controller.submit(pwb::viz::VolumeAxis::inline_, 0, std::nullopt);
    PWB_CHECK(wait_until([&] { return sink.size() == 1; }));
    PWB_CHECK(!sink.snapshot().front().ok);
    PWB_CHECK(sink.snapshot().front().diagnostic.find("no source") != std::string::npos);

    pwb::viz::VolumeGeometryV1 empty_geometry;
    empty_geometry.shape = {0, 8, 32};
    auto empty = pwb::viz::make_owning_volume(empty_geometry, {});
    controller.set_source(std::move(empty));
    controller.submit(pwb::viz::VolumeAxis::inline_, 0, std::nullopt);
    PWB_CHECK(wait_until([&] { return sink.size() == 2; }));
    PWB_CHECK(!sink.snapshot().back().ok);
    PWB_CHECK(sink.snapshot().back().diagnostic.find("empty") != std::string::npos);

    // Out-of-bounds index on a valid volume.
    controller.set_source(pattern_source());
    controller.submit(pwb::viz::VolumeAxis::inline_, 99, std::nullopt);
    PWB_CHECK(wait_until([&] { return sink.size() == 3; }));
    PWB_CHECK(!sink.snapshot().back().ok);
    PWB_CHECK(sink.snapshot().back().diagnostic.find("bounds") != std::string::npos);
}

TEST(plane_cache_is_bounded_and_hits_repeat_reads) {
    SinkCollector sink;
    SliceController controller(pattern_source(), 2,
                               [&](const SliceResult& r) { sink(r); });
    std::size_t expected_deliveries = 0;
    const auto run = [&](std::int64_t index) {
        controller.submit(pwb::viz::VolumeAxis::sample, index, std::nullopt);
        ++expected_deliveries;
        PWB_CHECK(wait_until([&] { return sink.size() == expected_deliveries; }));
        PWB_CHECK(sink.snapshot().back().index == index);
    };
    run(0);
    run(1);
    run(0); // cache hit
    run(0); // cache hit
    const ControllerStats stats = controller.stats();
    PWB_CHECK(stats.executed == 2); // planes 0 and 1 read exactly once each
    PWB_CHECK(stats.cache_hits == 2);
    PWB_CHECK(stats.cache_planes_peak <= 2);
    PWB_CHECK(controller.cache_size() <= 2);

    // Cycling 10 more distinct planes through a 2-plane LRU never grows it.
    for (std::int64_t index = 2; index < 12; ++index) {
        run(index);
    }
    PWB_CHECK(controller.cache_size() <= 2);
    PWB_CHECK(controller.stats().cache_planes_peak <= 2);
}

TEST(shutdown_is_quiet_after_it_completes) {
    // Contract: once request_shutdown() RETURNS, the sink never fires again.
    // (An in-flight result may still be delivered DURING the join — that is
    // before shutdown completes — and the widget bridge drops it safely.)
    auto observing = std::make_shared<sv_test_sources::ObservingVolume>(
        pattern_source(), std::chrono::milliseconds(60));
    SinkCollector sink;
    SliceController controller(observing, 4, [&](const SliceResult& r) { sink(r); });
    controller.submit(pwb::viz::VolumeAxis::inline_, 4, std::nullopt);
    PWB_CHECK(wait_until([&] { return observing->reads_entered() >= 1; }));
    controller.request_shutdown(); // joins the worker (in-flight read runs out)
    const std::size_t calls_after_shutdown = sink.size();
    std::this_thread::sleep_for(200ms);
    PWB_CHECK(sink.size() == calls_after_shutdown);
} // destructor on an already-shutdown controller: quiet + quick

TEST(explicit_range_reruns_colorization_not_reads) {
    SinkCollector sink;
    SliceController controller(pattern_source(), 4,
                               [&](const SliceResult& r) { sink(r); });
    controller.submit(pwb::viz::VolumeAxis::inline_, 1, std::nullopt);
    PWB_CHECK(wait_until([&] { return sink.size() == 1; }));
    const double auto_min = sink.snapshot().front().value_min;
    const double auto_max = sink.snapshot().front().value_max;
    PWB_CHECK(auto_min < auto_max);

    // Same plane, explicit range: served from the plane cache — no new read.
    controller.submit(pwb::viz::VolumeAxis::inline_, 1, std::make_pair(-10.0, 10.0));
    PWB_CHECK(wait_until([&] { return sink.size() == 2; }));
    const SliceResult stretched = sink.snapshot().back();
    PWB_CHECK(stretched.ok);
    PWB_CHECK(stretched.value_min == -10.0 && stretched.value_max == 10.0);
    PWB_CHECK(controller.stats().executed == 1);
    PWB_CHECK(controller.stats().cache_hits == 1);
}

#include "sv_test_main.inc"
