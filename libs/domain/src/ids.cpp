#include "pwb/domain/ids.hpp"

#include <chrono>
#include <cmath>
#include <mutex>
#include <random>

namespace pwb::domain {

namespace {
std::mutex g_generator_mutex;
std::uint64_t g_seed = 0;
bool g_seeded = false;

std::mt19937_64& engine() {
    static std::mt19937_64 rng{
        std::random_device{}() ^
        static_cast<std::uint64_t>(
            std::chrono::steady_clock::now().time_since_epoch().count())};
    return rng;
}

const char* kHex = "0123456789abcdef";
}  // namespace

bool is_safe_storage_segment(std::string_view id) {
    if (id.empty() || id.front() == '.') return false;
    for (char c : id) {
        const bool alnum = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') ||
                           (c >= 'A' && c <= 'Z');
        if (!alnum && c != '.' && c != '_' && c != '-') return false;
    }
    return true;
}

void seed_id_generator_for_tests(std::uint64_t seed) {
    std::lock_guard<std::mutex> lock(g_generator_mutex);
    g_seed = seed;
    g_seeded = true;
}

std::string make_id(std::string_view prefix) {
    std::lock_guard<std::mutex> lock(g_generator_mutex);
    std::uint64_t bits = 0;
    if (g_seeded) {
        bits = g_seed;
        g_seed += 0x9E3779B97F4A7C15ULL;  // deterministic stride
    } else {
        bits = engine()();
    }
    std::string out(prefix);
    out.reserve(prefix.size() + 12);
    for (int i = 0; i < 12; ++i) {
        out.push_back(kHex[bits & 0xF]);
        bits >>= 4;
        if (i == 7 && g_seeded) {  // refresh bits from the stride sequence
            bits ^= g_seed * 0x2545F4914F6CDD1DULL;
            bits ^= bits >> 31;
        } else if (i == 7) {
            bits ^= engine()();
        }
    }
    return out;
}

}  // namespace pwb::domain
