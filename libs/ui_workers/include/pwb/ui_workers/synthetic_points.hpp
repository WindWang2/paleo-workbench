#pragma once

// UI-04 — geoviz_plots.factor.interpolation.synthetic_sample_points port.
//
// Deterministic control points when no well-derived samples exist:
//   rng = random.Random(f"{seed}:{factor_type}")
//   digest = sha256(factor_type.encode()).digest()
//   base = 10.0 + (int.from_bytes(digest[:4], "big") % 20)
//   [{well: f"A{i+1}", x: round(114 + rng()*0.3, 6),
//     y: round(22.5 + rng()*0.3, 6),
//     value: round(base + rng()*40.0, 3)} for i in range(8)]
//
// Python's random.Random seeded from a str uses sha512(seed)->int +
// MT19937 init_by_array; this header exposes the seeded generator so the
// port is byte-for-byte reproducible (and oracle-frozen).

#include <any>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

namespace pwb::ui_workers {

// Python random.Random parity (version=2 str seeding + MT19937
// init_by_array + random() double).
class PyRandom {
public:
    explicit PyRandom(const std::string& seed_text);
    explicit PyRandom(long long seed_int) { seed_bigint(seed_int); }

    // random() — (a<<26 | b) / 2^53 with a = genrand()>>5, b = genrand()>>6.
    double random();

private:
    void seed_bigint(long long value);
    void seed_bytes_to_int(const std::string& seed_text);
    std::uint32_t genrand_uint32();

    std::uint32_t mt_[624];
    int index_ = 0;
};

// geoviz synthetic_sample_points — the real port. Returns the Python
// list[dict] shape (keys well/x/y/value) as vector<map<string,any>>.
// (factor_prepare.hpp re-declares this with the count=8 default; keep
// the default in ONE place.)
std::vector<std::map<std::string, std::any>> synthetic_sample_points(
    int seed, const std::string& factor_type, int count);

// sha512 digest of UTF-8 bytes (needed by the str-seed scheme; self-
// contained — the domain Sha256 covers only sha256).
std::vector<std::uint8_t> sha512_bytes(const std::string& text);

}  // namespace pwb::ui_workers
