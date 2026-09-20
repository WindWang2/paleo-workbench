#include "bench_common.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iterator>
#include <new>
#include <sys/resource.h>
#include <sys/types.h>
#include <unistd.h>

// ---------------------------------------------------------------------------
// Global allocation counting (bench binary only — these overrides are not in
// any production library). Plain counters: the bench scenarios are
// single-threaded, and a torn read would only ever distort diagnostics, not
// results.
// ---------------------------------------------------------------------------
namespace {
std::uint64_t g_alloc_calls = 0;
std::uint64_t g_alloc_bytes = 0;

void count_alloc(std::size_t n) noexcept {
    ++g_alloc_calls;
    g_alloc_bytes += n;
}
}  // namespace

void* operator new(std::size_t n) {
    count_alloc(n);
    return std::malloc(n == 0 ? 1 : n);
}
void* operator new[](std::size_t n) {
    count_alloc(n);
    return std::malloc(n == 0 ? 1 : n);
}
void* operator new(std::size_t n, std::align_val_t a) {
    count_alloc(n);
    const std::size_t align = static_cast<std::size_t>(a);
    const std::size_t size = (n + align - 1) / align * align;
    return std::aligned_alloc(align, size == 0 ? align : size);
}
void* operator new[](std::size_t n, std::align_val_t a) {
    count_alloc(n);
    const std::size_t align = static_cast<std::size_t>(a);
    const std::size_t size = (n + align - 1) / align * align;
    return std::aligned_alloc(align, size == 0 ? align : size);
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }
void operator delete[](void* p, std::size_t) noexcept { std::free(p); }
void operator delete(void* p, std::align_val_t) noexcept { std::free(p); }
void operator delete[](void* p, std::align_val_t) noexcept { std::free(p); }
void operator delete(void* p, std::size_t, std::align_val_t) noexcept {
    std::free(p);
}
void operator delete[](void* p, std::size_t, std::align_val_t) noexcept {
    std::free(p);
}

namespace pwb::bench {

AllocStats alloc_stats() {
    return AllocStats{g_alloc_calls, g_alloc_bytes};
}

namespace {

std::string read_proc_file(const char* path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return {};
    return std::string(std::istreambuf_iterator<char>(in),
                       std::istreambuf_iterator<char>());
}

std::uint64_t parse_kb_field(const std::string& text, const char* key) {
    const std::size_t pos = text.find(key);
    if (pos == std::string::npos) return 0;
    const char* p = text.c_str() + pos + std::strlen(key);
    while (*p == ' ' || *p == '\t' || *p == ':') ++p;
    return std::strtoull(p, nullptr, 10);
}

}  // namespace

IoCounters io_counters() {
    IoCounters out;
#if defined(__linux__)
    const std::string text = read_proc_file("/proc/self/io");
    out.rchar = parse_kb_field(text, "rchar");
    out.wchar = parse_kb_field(text, "wchar");
    out.syscr = parse_kb_field(text, "syscr");
    out.syscw = parse_kb_field(text, "syscw");
    out.read_bytes = parse_kb_field(text, "read_bytes");
    out.write_bytes = parse_kb_field(text, "write_bytes");
#endif
    return out;
}

double peak_rss_mib() {
#if defined(__linux__)
    const std::string text = read_proc_file("/proc/self/status");
    const std::uint64_t kib = parse_kb_field(text, "VmHWM");
    if (kib != 0) return static_cast<double>(kib) / 1024.0;
#endif
    struct rusage usage {};
    if (::getrusage(RUSAGE_SELF, &usage) == 0) {
        // Linux reports ru_maxrss in KiB.
        return static_cast<double>(usage.ru_maxrss) / 1024.0;
    }
    return 0.0;
}

std::uint64_t io_read_bytes_now() { return io_counters().read_bytes; }

SampleStats summarize(std::vector<double> samples_ms) {
    SampleStats out;
    if (samples_ms.empty()) return out;
    out.first_ms = samples_ms.front();
    out.min_ms = *std::min_element(samples_ms.begin(), samples_ms.end());
    out.max_ms = *std::max_element(samples_ms.begin(), samples_ms.end());
    std::vector<double> sorted = samples_ms;
    std::sort(sorted.begin(), sorted.end());
    const std::size_t n = sorted.size();
    out.median_ms = (n % 2 == 1)
        ? sorted[n / 2]
        : (sorted[n / 2 - 1] + sorted[n / 2]) / 2.0;
    // Nearest-rank p95 (n>=1 always has a rank).
    const std::size_t rank =
        static_cast<std::size_t>(std::ceil(0.95 * static_cast<double>(n)));
    out.p95_ms = sorted[std::max<std::size_t>(rank, 1) - 1];
    out.samples_ms = std::move(samples_ms);
    return out;
}

Json measured_to_json(const Measured& m) {
    Json j = Json::object();
    Json samples = Json::array();
    for (const double v : m.time.samples_ms) samples.push_back(v);
    j["samples_ms"] = std::move(samples);
    j["median_ms"] = m.time.median_ms;
    j["p95_ms"] = m.time.p95_ms;
    j["min_ms"] = m.time.min_ms;
    j["max_ms"] = m.time.max_ms;
    j["first_ms"] = m.time.first_ms;
    j["sample_count"] = m.time.samples_ms.size();
    j["alloc_calls"] = m.allocs.calls;
    j["alloc_bytes"] = m.allocs.bytes;
    j["io_read_bytes"] = m.io.read_bytes;
    j["io_write_bytes"] = m.io.write_bytes;
    j["io_rchar"] = m.io.rchar;
    j["io_wchar"] = m.io.wchar;
    j["io_syscr"] = m.io.syscr;
    j["io_syscw"] = m.io.syscw;
    j["peak_rss_mib"] = peak_rss_mib();
    return j;
}

// ---------------------------------------------------------------------------

bool Args::has(const std::string& key) const {
    for (const auto& flag : flags) {
        if (flag == key) return true;
    }
    for (const auto& [k, v] : values) {
        if (k == key) return true;
    }
    return false;
}

std::string Args::get(const std::string& key, const std::string& dflt) const {
    for (const auto& [k, v] : values) {
        if (k == key) return v;
    }
    return dflt;
}

long long Args::get_int(const std::string& key, long long dflt) const {
    const std::string v = get(key, "");
    if (v.empty()) return dflt;
    return std::strtoll(v.c_str(), nullptr, 10);
}

std::size_t Args::get_size(const std::string& key, std::size_t dflt) const {
    const std::string v = get(key, "");
    if (v.empty()) return dflt;
    return static_cast<std::size_t>(std::strtoull(v.c_str(), nullptr, 10));
}

std::array<int, 3> Args::get_triple(const std::string& key,
                                    std::array<int, 3> dflt) const {
    const std::string v = get(key, "");
    if (v.empty()) return dflt;
    std::array<int, 3> out{};
    std::size_t pos = 0;
    for (int i = 0; i < 3; ++i) {
        const std::size_t comma = v.find(',', pos);
        const std::string part =
            v.substr(pos, comma == std::string::npos ? std::string::npos
                                                     : comma - pos);
        out[static_cast<std::size_t>(i)] =
            std::atoi(part.c_str());
        if (comma == std::string::npos) break;
        pos = comma + 1;
    }
    return out;
}

Args parse_args(int argc, char** argv) {
    Args out;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if (a.rfind("--", 0) == 0) {
            const std::string key = a.substr(2);
            if (i + 1 < argc && std::strncmp(argv[i + 1], "--", 2) != 0) {
                out.values.emplace_back(key, argv[++i]);
            } else {
                out.flags.push_back(key);
            }
        } else {
            out.positional.push_back(a);
        }
    }
    return out;
}

float synth_float(std::uint64_t index) {
    std::uint64_t z = index + 0x9e3779b97f4a7c15ull;
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ull;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebull;
    z ^= z >> 31;
    return static_cast<float>((z >> 8) & 0xffffffu) / 16777216.0f;
}

std::uint64_t fnv1a64(const void* data, std::size_t bytes, std::uint64_t seed) {
    const auto* p = static_cast<const unsigned char*>(data);
    std::uint64_t h = seed;
    for (std::size_t i = 0; i < bytes; ++i) {
        h ^= p[i];
        h *= 1099511628211ull;
    }
    return h;
}

}  // namespace pwb::bench
