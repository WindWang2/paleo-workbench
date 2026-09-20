// pwb-bench — shared measurement helpers for the native benchmark harness
// (cpp-close wave line 14). Qt-free, C++20, Linux-oriented: RSS/IO counters
// read /proc/self/*; timing uses steady_clock. Every scenario reports raw
// samples so the ledger can recompute median/p95 offline — no hidden
// aggregation.
#pragma once

#include <pwb/domain/json.hpp>

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

namespace pwb::bench {

using pwb::domain::Json;
using Clock = std::chrono::steady_clock;

// ---------------------------------------------------------------------------
// Allocation counters. The bench binary overrides global operator new/delete
// (bench_common.cpp) so a scenario can count heap traffic as hard evidence
// for allocation hotspots (e.g. a per-voxel std::vector). Counting is
// process-wide and always on; callers snapshot a delta around the measured
// region.
// ---------------------------------------------------------------------------
struct AllocStats {
    std::uint64_t calls = 0;   // operator new / new[] calls (incl. aligned)
    std::uint64_t bytes = 0;   // requested bytes (not allocator overhead)
};

AllocStats alloc_stats();

// ---------------------------------------------------------------------------
// Process counters (Linux /proc; graceful zeros elsewhere).
// ---------------------------------------------------------------------------
struct IoCounters {
    std::uint64_t read_bytes = 0;    // /proc/self/io read_bytes (storage)
    std::uint64_t write_bytes = 0;   // /proc/self/io write_bytes
    std::uint64_t rchar = 0;         // bytes read incl. page cache
    std::uint64_t wchar = 0;
    std::uint64_t syscr = 0;         // read syscalls
    std::uint64_t syscw = 0;         // write syscalls
};

IoCounters io_counters();
double peak_rss_mib();             // VmHWM (high-water mark)
std::uint64_t io_read_bytes_now();

// ---------------------------------------------------------------------------
// Sample statistics over measured runs.
// ---------------------------------------------------------------------------
struct SampleStats {
    std::vector<double> samples_ms;  // in-run wall time per sample
    double median_ms = 0.0;
    double p95_ms = 0.0;             // nearest-rank p95
    double min_ms = 0.0;
    double max_ms = 0.0;
    double first_ms = 0.0;           // cold sample kept apart
};

SampleStats summarize(std::vector<double> samples_ms);

// Run `fn` `samples` times; returns per-sample ms plus alloc/IO deltas
// measured across the whole measured region (setup excluded — callers do
// fixture work before calling this).
struct Measured {
    SampleStats time;
    AllocStats allocs;
    IoCounters io;
};

template <typename Fn>
Measured measure(int samples, Fn&& fn) {
    Measured out;
    const AllocStats a0 = alloc_stats();
    const IoCounters i0 = io_counters();
    out.time.samples_ms.reserve(static_cast<std::size_t>(samples));
    for (int s = 0; s < samples; ++s) {
        const auto t0 = Clock::now();
        fn(s);
        const auto t1 = Clock::now();
        out.time.samples_ms.push_back(
            std::chrono::duration<double, std::milli>(t1 - t0).count());
    }
    const AllocStats a1 = alloc_stats();
    const IoCounters i1 = io_counters();
    out.allocs.calls = a1.calls - a0.calls;
    out.allocs.bytes = a1.bytes - a0.bytes;
    out.io.read_bytes = i1.read_bytes - i0.read_bytes;
    out.io.write_bytes = i1.write_bytes - i0.write_bytes;
    out.io.rchar = i1.rchar - i0.rchar;
    out.io.wchar = i1.wchar - i0.wchar;
    out.io.syscr = i1.syscr - i0.syscr;
    out.io.syscw = i1.syscw - i0.syscw;
    out.time = summarize(std::move(out.time.samples_ms));
    return out;
}

Json measured_to_json(const Measured& m);

// ---------------------------------------------------------------------------
// CLI args: "--key value" or "--flag". Unknown keys are accepted (scenarios
// read what they know); `has`/`get`/`get_int`/`get_size` do the typing.
// ---------------------------------------------------------------------------
struct Args {
    std::vector<std::string> positional;
    std::vector<std::pair<std::string, std::string>> values;
    std::vector<std::string> flags;

    bool has(const std::string& key) const;
    std::string get(const std::string& key, const std::string& dflt = "") const;
    long long get_int(const std::string& key, long long dflt) const;
    std::size_t get_size(const std::string& key, std::size_t dflt) const;
    // "a,b,c" -> three ints (tile/shape arguments).
    std::array<int, 3> get_triple(const std::string& key,
                                  std::array<int, 3> dflt) const;
};

Args parse_args(int argc, char** argv);

// Scenario registry: each bench_*.cpp contributes scenarios by name.
using ScenarioFn = Json (*)(const Args&);
using ScenarioMap = std::unordered_map<std::string, ScenarioFn>;

// Deterministic content generator for synthetic volumes/models:
// x -> [0,1) via a splitmix-style hash. Stable across runs and builds.
float synth_float(std::uint64_t index);
std::uint64_t fnv1a64(const void* data, std::size_t bytes,
                    std::uint64_t seed = 1469598103934665603ull);

}  // namespace pwb::bench
