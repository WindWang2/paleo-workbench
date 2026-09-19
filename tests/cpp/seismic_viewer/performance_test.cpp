// seismic_viewer.performance — measured, not asserted-into-existence:
// slice latency p50/p95 and interaction coalescing on a fixed medium volume
// (256 x 256 x 512 float32 = 128 MiB), plane-cache peak, memory high-water,
// and proof that fast interactions never copy the whole volume. The report
// prints the shape/config/numbers the ledger quotes; the asserts only pin
// structural invariants (bounded reads, bounded cache, per-read plane size).

#include "sv_test.hpp"
#include "sv_test_sources.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <pwb/seismic_viewer/slice_controller.hpp>

using namespace pwb::seismic_viewer;
using namespace std::chrono_literals;

namespace {

constexpr std::int64_t kNi = 256, kNx = 256, kNt = 512; // 128 MiB of floats
constexpr std::size_t kPlaneSize = static_cast<std::size_t>(kNi * kNt); // inline plane

template <typename Predicate>
bool wait_until(Predicate&& predicate, std::chrono::milliseconds timeout = 30000ms) {
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline) {
        if (predicate()) {
            return true;
        }
        std::this_thread::sleep_for(1ms);
    }
    return predicate();
}

std::string proc_status_value(const char* key) {
    std::ifstream status("/proc/self/status");
    std::string line;
    while (std::getline(status, line)) {
        if (line.rfind(key, 0) == 0) {
            const std::size_t colon = line.find(':');
            std::string value = line.substr(colon + 1);
            while (!value.empty() && (value.front() == ' ' || value.front() == '\t')) {
                value.erase(value.begin());
            }
            return value;
        }
    }
    return {};
}

double now_ms() {
    return std::chrono::duration<double, std::milli>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

double percentile(std::vector<double> samples, double fraction) {
    std::sort(samples.begin(), samples.end());
    const std::size_t index = std::min(
        samples.size() - 1,
        static_cast<std::size_t>(fraction * static_cast<double>(samples.size() - 1)));
    return samples[index];
}

std::vector<float> medium_volume_data() {
    std::vector<float> data(static_cast<std::size_t>(kNi * kNx * kNt));
    // Ricker-ish textured pattern: cheap to generate, non-degenerate, with a
    // few NaNs so the stretch exercises the finite-only path.
    for (std::size_t i = 0; i < data.size(); ++i) {
        const double x = static_cast<double>(i % 997);
        const double y = static_cast<double>((i / 8191) % 991);
        data[i] = static_cast<float>(std::sin(x * 0.11) * std::cos(y * 0.07));
    }
    for (std::size_t i = 0; i < data.size(); i += 100003) {
        data[i] = std::nanf("");
    }
    return data;
}

} // namespace

TEST(slice_latency_p50_p95_and_memory_high_water) {
    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = {kNi, kNx, kNt};
    geometry.strides = {0, 0, 0};
    geometry.origin = {1.0, 1.0, 0.0};
    geometry.step = {1.0, 1.0, 4.0};
    geometry.unit = "ms";

    const double rss_before_mb = [&] {
        const std::string value = proc_status_value("VmRSS");
        return value.empty() ? 0.0 : std::atof(value.c_str()) / 1024.0;
    }();
    auto volume =
        pwb::viz::make_owning_volume(geometry, medium_volume_data());
    const double rss_after_alloc_mb = [&] {
        const std::string value = proc_status_value("VmRSS");
        return value.empty() ? 0.0 : std::atof(value.c_str()) / 1024.0;
    }();

    struct TimedResult {
        SliceResult result;
        double submit_ms{0.0};
        double delivered_ms{0.0};
    };
    std::mutex mutex;
    std::vector<TimedResult> delivered;

    // BEGIN VIZ-D — prefetch warms neighbour planes; the frozen latency/
    // storm numbers measure COLD read paths, so disable it here.
    SliceController controller(std::move(volume), 4, [&](const SliceResult& r) {
        const double delivered_at = now_ms();
        std::lock_guard<std::mutex> lock(mutex);
        delivered.push_back(TimedResult{r, 0.0, delivered_at});
    });
    controller.set_prefetch_enabled(false);
    // END VIZ-D

    // 60 distinct inline planes: submit, remember the timestamp, wait for the
    // delivery that carries this generation. In-memory backend => timings
    // include read_slice + map_slice_to_indexed8 (no disk I/O).
    std::vector<double> latencies;
    for (std::int64_t index = 0; index < 60; ++index) {
        const double submitted_at = now_ms();
        controller.submit(pwb::viz::VolumeAxis::inline_, index, std::nullopt);
        PWB_CHECK(wait_until([&] {
            std::lock_guard<std::mutex> lock(mutex);
            return !delivered.empty() &&
                   delivered.back().result.index == index &&
                   delivered.back().result.ok;
        }));
        std::lock_guard<std::mutex> lock(mutex);
        delivered.back().submit_ms = submitted_at;
        latencies.push_back(delivered.back().delivered_ms - submitted_at);
    }
    PWB_CHECK(latencies.size() == 60);

    const double p50 = percentile(latencies, 0.50);
    const double p95 = percentile(latencies, 0.95);
    const std::string hwm = proc_status_value("VmHWM");
    std::printf(
        "perf: volume=%lldx%lldx%lld f32 (%.1f MiB) plane=%zu f32 (%.1f KiB)\n"
        "perf: hw_threads=%u build=%s io=none(in-memory)\n"
        "perf: slice submit->deliver p50=%.3f ms p95=%.3f ms (n=%zu, cache=4)\n"
        "perf: rss alloc delta=%.1f MiB, VmHWM=%s\n",
        static_cast<long long>(kNi), static_cast<long long>(kNx),
        static_cast<long long>(kNt),
        static_cast<double>(kNi * kNx * kNt * 4) / (1024.0 * 1024.0), kPlaneSize,
        static_cast<double>(kPlaneSize * 4) / 1024.0,
        std::thread::hardware_concurrency(),
#ifdef NDEBUG
        "Release",
#else
        "Debug",
#endif
        p50, p95, latencies.size(), rss_after_alloc_mb - rss_before_mb,
        hwm.c_str());

    // Structural invariants: every read moved exactly one plane.
    const ControllerStats stats = controller.stats();
    PWB_CHECK(stats.executed == 60); // distinct planes, no cache hits
    PWB_CHECK(stats.cache_planes_peak <= 4);
    PWB_CHECK(p95 > 0.0);
    // The volume allocation itself dominates; slicing adds bounded planes.
    PWB_CHECK(rss_after_alloc_mb - rss_before_mb >= 100.0); // the 128 MiB body
}

TEST(fast_interaction_storm_coalesces_and_stays_plane_bounded) {
    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = {kNi, kNx, kNt};
    geometry.strides = {0, 0, 0};
    geometry.origin = {1.0, 1.0, 0.0};
    geometry.step = {1.0, 1.0, 4.0};
    geometry.unit = "ms";
    auto volume =
        pwb::viz::make_owning_volume(geometry, medium_volume_data());
    // Delay stands in for a slower backend (chunked store): reads are real.
    auto observing = std::make_shared<sv_test_sources::ObservingVolume>(
        std::move(volume), std::chrono::milliseconds(20));

    std::mutex mutex;
    std::int64_t last_delivered_index = -1;
    // BEGIN VIZ-D — same cold-read measurement contract as above.
    SliceController controller(observing, 4, [&](const SliceResult& r) {
        std::lock_guard<std::mutex> lock(mutex);
        if (r.ok) {
            last_delivered_index = r.index;
        }
    });
    controller.set_prefetch_enabled(false);
    // END VIZ-D

    // 150 rapid index moves (a fast slider drag on a big volume).
    const auto drag_start = std::chrono::steady_clock::now();
    for (std::int64_t move = 0; move < 150; ++move) {
        controller.submit(pwb::viz::VolumeAxis::inline_, move % kNi, std::nullopt);
    }
    const double submit_span_ms =
        std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() -
                                                  drag_start)
            .count();
    PWB_CHECK(wait_until([&] {
        std::lock_guard<std::mutex> lock(mutex);
        return last_delivered_index == 149 % kNi;
    }));

    const ControllerStats stats = controller.stats();
    const std::uint64_t plane_elements = stats.executed * kPlaneSize;
    const std::uint64_t volume_elements =
        static_cast<std::uint64_t>(kNi) * kNx * kNt;
    std::printf(
        "perf: 150 moves in %.3f ms -> executed reads=%llu coalesced=%llu "
        "elements_read=%llu (volume=%llu)\n",
        submit_span_ms, static_cast<unsigned long long>(stats.executed),
        static_cast<unsigned long long>(stats.coalesced),
        static_cast<unsigned long long>(observing->elements_read()),
        static_cast<unsigned long long>(volume_elements));

    PWB_CHECK_MSG(stats.executed <= 40,
                  "150 rapid moves must collapse into few reads");
    PWB_CHECK_MSG(stats.coalesced >= 100, "most moves must merge");
    PWB_CHECK(observing->elements_read() == plane_elements); // plane-sized reads
    PWB_CHECK(observing->elements_read() < volume_elements); // never the body
    PWB_CHECK(stats.cache_planes_peak <= 4);
    PWB_CHECK(observing->overlapped_reads() == 0);
}

#include "sv_test_main.inc"
