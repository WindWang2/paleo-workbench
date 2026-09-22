// standalone_test.cpp — exact-integer resample block boundaries (#1463),
// verified with plain g++ (no Python / pybind11 needed):
//
//   g++ -std=c++20 -O2 -Wall -Wextra standalone_test.cpp -o resample_selftest
//   ./resample_selftest
//
// The old float32 boundary form (lo[i] = trunc(i * (float)s / (float)t))
// lost integer exactness once i * (s/t) exceeded 2^24: the identity
// resample read past the source buffer's last sample, and large-stride
// decimations silently skipped source samples. These tests pin the exact
// contract with closed-form (__int128) oracles instead of allocating
// multi-GB volumes — the (2^24+1)-sized identity case below needs two
// ~128 MiB index vectors, which is the whole point of testing the boundary
// math in isolation.

#include "resample_bounds.hpp"

#include <cstdio>
#include <cstdint>
#include <vector>

namespace {

int g_failures = 0;

void check(bool ok, const char* what) {
    if (!ok) {
        std::printf("[FAIL] %s\n", what);
        ++g_failures;
    }
}

// Closed-form oracle: lo[i] == floor(i * s / t), exact via 128-bit.
std::uint64_t closed_form_lo(std::uint64_t i, std::uint64_t s,
                             std::uint64_t t) {
    const unsigned __int128 product =
        static_cast<unsigned __int128>(i) * s;
    return static_cast<std::uint64_t>(product / t);
}

// Full property check of one (s, t) axis:
//   * lo[i] == floor(i*s/t) exactly (the float32 form broke past 2^24)
//   * hi[i] in [lo[i], s-1]  — never past the source edge
//   * t <= s (decimation/identity): blocks tile [0, s) without gaps;
//     t > s (upsampling): lo advances by at most 1 per target, so the
//     repeated single-sample blocks still cover every source index.
void verify_axis(std::uint64_t s, std::uint64_t t) {
    std::vector<std::size_t> lo, hi;
    if (!pwb::seismic_core::resample_block_bounds(s, t, lo, hi)) {
        check(false, "resample_block_bounds returned false");
        return;
    }
    check(lo.size() == t && hi.size() == t, "vector sizes");
    std::uint64_t covered_from = 0;  // expected start of block i
    for (std::uint64_t i = 0; i < t; ++i) {
        const std::uint64_t want_lo = closed_form_lo(i, s, t);
        check(lo[static_cast<std::size_t>(i)] == want_lo,
              "lo[i] == floor(i*s/t) exactly");
        check(hi[static_cast<std::size_t>(i)] >= lo[static_cast<std::size_t>(i)]
                  && hi[static_cast<std::size_t>(i)] < s,
              "hi within [lo, s-1]");
        if (s >= t) {
            check(lo[static_cast<std::size_t>(i)] == covered_from,
                  "blocks contiguous");
            covered_from = hi[static_cast<std::size_t>(i)] + 1;
        } else if (i + 1 < t) {
            check(lo[static_cast<std::size_t>(i + 1)]
                      - lo[static_cast<std::size_t>(i)]
                  <= 1,
                  "upsampling: lo advances by at most 1");
        }
        if (i + 1 == t) {
            check(hi[static_cast<std::size_t>(i)] == s - 1,
                  "last block ends at source edge");
        }
    }
    if (s >= t) {
        check(covered_from == s, "blocks cover the whole source axis");
    }
}

}  // namespace

int main() {
    // Small-size matrix: identity, up/down sampling, degenerate 1s, primes.
    for (std::uint64_t s = 1; s <= 33; ++s) {
        for (std::uint64_t t = 1; t <= 17; ++t) {
            verify_axis(s, t);
        }
    }
    verify_axis(100, 7);
    verify_axis(97, 89);
    verify_axis(1000, 3);
    verify_axis(3, 1000);

    // The float32 hazard zone (issue #1463): s beyond 2^24 with a small
    // target count. Tiny vectors, but every block boundary lands where
    // i * (s/t) exceeds 2^24 — the exact indices the old float32
    // truncation got wrong (it skipped source samples near the end).
    verify_axis((1ull << 24) + 1, 5);
    verify_axis((1ull << 24) + 3, 7);
    verify_axis((1ull << 25) + 11, 13);

    // Large stride, moderate target count (16 MiB index vectors): the last
    // block ends exactly at s - 1 in the hazard zone.
    verify_axis((1ull << 24) + 1, 1u << 20);

    // THE identity regression (axis length > 2^24): lo[i] must equal i for
    // every i, including odd i past 2^24 where float32(i) rounds UP. The
    // old code produced lo[t-1] == t+1 and read src[t+1] — past the end.
    {
        const std::uint64_t s = (1ull << 24) + 1;
        std::vector<std::size_t> lo, hi;
        check(pwb::seismic_core::resample_block_bounds(s, s, lo, hi),
              "identity bounds computed");
        bool all_identity = true;
        for (std::uint64_t i = 0; i < s; ++i) {
            if (lo[static_cast<std::size_t>(i)] != i
                || hi[static_cast<std::size_t>(i)] != i) {
                all_identity = false;
                break;
            }
        }
        check(all_identity, "identity resample: block i == [i, i] past 2^24");
        check(lo[static_cast<std::size_t>(s - 1)] == s - 1
                  && hi[static_cast<std::size_t>(s - 1)] == s - 1,
              "last identity block in bounds");
    }

    std::printf("%s: %d failure(s)\n", g_failures == 0 ? "PASS" : "FAIL",
                g_failures);
    return g_failures == 0 ? 0 : 1;
}
