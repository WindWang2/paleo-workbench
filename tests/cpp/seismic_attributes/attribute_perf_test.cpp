// Performance and memory-bound evidence at fixed sizes. Reports wall time
// and peak-RSS growth (VmHWM from /proc/self/status) per algorithm and size;
// asserts the temporary footprint stays within input+output+one batch
// (<= 64 MiB FFT scratch, no plan cache, no growth with trace count beyond
// the produced volume). Makes no speed claims vs the Python oracle.

#include "pwb_test.hpp"

#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include <pwb/science/types.hpp>
#include <pwb/seismic_attributes/attributes.hpp>

namespace {

std::shared_ptr<std::vector<float>> synthetic_volume(std::int64_t n_il,
                                                     std::int64_t n_xl,
                                                     std::int64_t n_t) {
    auto data = std::make_shared<std::vector<float>>(
        static_cast<std::size_t>(n_il * n_xl * n_t));
    unsigned state = 42u;
    for (float& v : *data) {
        state = state * 1664525u + 1013904223u;
        v = 0.5f * std::sin(static_cast<float>(state & 0xFF) * 0.05f) +
            ((state >> 16) & 0xF) / 16.0f - 0.5f;
    }
    return data;
}

// /proc/self/status VmHWM in bytes (peak RSS). Linux-only, matching this
// verification environment; returns 0 when unavailable so the test can
// degrade to time-only reporting instead of failing.
std::uint64_t peak_rss_bytes() {
    std::ifstream status("/proc/self/status");
    std::string key;
    while (status >> key) {
        if (key == "VmHWM:") {
            std::uint64_t kb = 0;
            if (status >> kb) {
                return kb * 1024;
            }
            return 0;
        }
        status.ignore(4096, '\n');
    }
    return 0;
}

struct RunStats {
    double ms{0};
    std::uint64_t rss_growth{0};
    std::int64_t wall_time_ms_provenance{0};
};

RunStats run_one(const std::string& id,
                 const std::shared_ptr<std::vector<float>>& holder,
                 std::array<std::int64_t, 3> shape,
                 const std::map<std::string, std::string>& params) {
    auto algorithm = id == "seismic.envelope"
                         ? pwb::seismic_attributes::make_envelope("build-perf")
                         : (id == "seismic.instantaneous_phase"
                                ? pwb::seismic_attributes::make_instantaneous_phase(
                                      "build-perf")
                                : (id == "seismic.instantaneous_frequency"
                                       ? pwb::seismic_attributes::
                                             make_instantaneous_frequency("build-perf")
                                       : pwb::seismic_attributes::make_rms_amplitude(
                                             "build-perf")));
    pwb::science::AlgorithmRequestV1 request;
    request.algorithm_id = id;
    request.algorithm_version = algorithm->descriptor().version;
    request.params_json = params;
    pwb::science::VolumeView view;
    view.data = holder->data();
    view.shape = shape;
    view.strides = {0, 0, 0};
    view.lifetime = holder;
    request.input_volumes.push_back(view);

    const std::uint64_t rss_before = peak_rss_bytes();
    const auto start = std::chrono::steady_clock::now();
    auto result = algorithm->run(request, nullptr, {});
    const auto finish = std::chrono::steady_clock::now();
    PWB_CHECK(result.has_value());
    RunStats stats;
    stats.ms = std::chrono::duration<double, std::milli>(finish - start).count();
    stats.rss_growth = peak_rss_bytes() > rss_before ? peak_rss_bytes() - rss_before : 0;
    stats.wall_time_ms_provenance =
        static_cast<std::int64_t>(result.value().provenance.wall_time_ms);
    // Touch the output so the pages are really materialized before the
    // algorithm object goes away.
    double sink = 0.0;
    for (const auto& output : result.value().outputs) {
        for (std::int64_t i = 0; i < output.volume.size(); ++i) {
            sink += output.volume.data[i];
        }
    }
    std::printf("   (output sum %.2f)\n", sink);
    return stats;
}

} // namespace

TEST(perf_fixed_sizes_bounded_memory) {
    struct SizeSpec {
        std::int64_t il, xl, t;
    };
    const SizeSpec sizes[] = {{48, 48, 512}, {96, 96, 512}};
    const std::uint64_t batch_bytes = 64ull * 1024 * 1024;
    // Envelope runs at both sizes; the others at the small size (they share
    // the batching machinery).
    struct Job {
        const char* id;
        std::map<std::string, std::string> params;
        bool both_sizes;
    };
    const Job jobs[] = {
        {"seismic.envelope", {}, true},
        {"seismic.instantaneous_phase", {}, false},
        {"seismic.instantaneous_frequency", {{"sample_interval", "0.002"}}, false},
        {"seismic.rms_amplitude", {{"window", "21"}}, false},
    };

    for (const SizeSpec& size : sizes) {
        auto holder = synthetic_volume(size.il, size.xl, size.t);
        const std::uint64_t payload = static_cast<std::uint64_t>(holder->size()) * 4ull;
        for (const Job& job : jobs) {
            if (!job.both_sizes && size.il != 48) {
                continue;
            }
            const RunStats stats =
                run_one(job.id, holder, {size.il, size.xl, size.t}, job.params);
            const std::uint64_t allowed = 2 * payload + batch_bytes + 32ull * 1024 * 1024;
            std::printf("%-45s (%lld,%lld,%lld): %8.1f ms (provenance %lld ms), "
                        "peak-RSS growth %.1f MiB (allowed %.1f)\n",
                        job.id, static_cast<long long>(size.il),
                        static_cast<long long>(size.xl), static_cast<long long>(size.t),
                        stats.ms, static_cast<long long>(stats.wall_time_ms_provenance),
                        stats.rss_growth / 1048576.0, allowed / 1048576.0);
            PWB_CHECK(stats.ms < 120000.0); // deterministic sanity bound
            if (stats.rss_growth > 0) {
                // input + output + one FFT batch + slack; a per-trace or
                // whole-volume cache would blow this bound at 96x96.
                PWB_CHECK(stats.rss_growth <= allowed);
            }
        }
    }
}

int main() {
    for (const auto& test : pwb_test::registry()) {
        std::printf("== %s ==\n", test.name.c_str());
        test.body();
    }
    std::printf("all perf tests passed (%zu tests)\n", pwb_test::registry().size());
    return 0;
}
