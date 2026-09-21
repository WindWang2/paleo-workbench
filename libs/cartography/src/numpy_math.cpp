// CONV-27 internal — numpy-exact numeric primitives. See numpy_math.hpp.
#include "numpy_math.hpp"

#if defined(_MSC_VER)
#include <intrin.h>  // _umul128 for the 128-bit Lemire product
#endif

namespace pwb::cartography::numpy_math {

namespace {

// 64x64 -> 128 product split: returns the HIGH word, writes the LOW word.
// MSVC has no __uint128_t; _umul128 is the same widening multiply.
inline std::uint64_t mul64_split(std::uint64_t a, std::uint64_t b,
                                 std::uint64_t* low) {
#if defined(_MSC_VER)
    return _umul128(a, b, low);
#else
    const __uint128_t m = static_cast<__uint128_t>(a) * b;
    *low = static_cast<std::uint64_t>(m);
    return static_cast<std::uint64_t>(m >> 64);
#endif
}
constexpr std::uint32_t kInitA = 0x43b0d7e5u;
constexpr std::uint32_t kMultA = 0x931e8875u;
constexpr std::uint32_t kInitB = 0x8b51f9ddu;
constexpr std::uint32_t kMultB = 0x58f38dedu;
constexpr std::uint32_t kMixMultL = 0xca01f9ddu;
constexpr std::uint32_t kMixMultR = 0x4973f715u;
constexpr int kXShift = 16;  // 32-bit word / 2

std::uint32_t hashmix(std::uint32_t value, std::uint32_t& hash_const) {
    value ^= hash_const;
    hash_const *= kMultA;
    value *= hash_const;
    value ^= value >> kXShift;
    return value;
}

std::uint32_t mix(std::uint32_t x, std::uint32_t y) {
    std::uint32_t result = (kMixMultL * x - kMixMultR * y);
    result ^= result >> kXShift;
    return result;
}

// Smallest bit mask >= max_val (numpy _gen_mask).
std::uint64_t gen_mask(std::uint64_t max_val) {
    std::uint64_t mask = max_val;
    mask |= mask >> 1;
    mask |= mask >> 2;
    mask |= mask >> 4;
    mask |= mask >> 8;
    mask |= mask >> 16;
    mask |= mask >> 32;
    return mask;
}
}  // namespace

double pairwise_sum(const double* data, std::size_t n) {
    // numpy loops_utils.h pairwise_sum (PW_BLOCKSIZE = 128).
    constexpr std::size_t kBlockSize = 128;
    if (n < 8) {
        double res = 0.0;
        for (std::size_t i = 0; i < n; ++i) res += data[i];
        return res;
    }
    if (n <= kBlockSize) {
        double r[8];
        for (std::size_t i = 0; i < 8; ++i) r[i] = data[i];
        for (std::size_t i = 8; i < n - (n % 8); i += 8) {
            r[0] += data[i + 0];
            r[1] += data[i + 1];
            r[2] += data[i + 2];
            r[3] += data[i + 3];
            r[4] += data[i + 4];
            r[5] += data[i + 5];
            r[6] += data[i + 6];
            r[7] += data[i + 7];
        }
        double res = ((r[0] + r[1]) + (r[2] + r[3])) +
                     ((r[4] + r[5]) + (r[6] + r[7]));
        for (std::size_t i = n - (n % 8); i < n; ++i) res += data[i];
        return res;
    }
    std::size_t n2 = n / 2;
    n2 -= n2 % 8;
    return pairwise_sum(data, n2) + pairwise_sum(data + n2, n - n2);
}

// ---- SeedSequence ------------------------------------------------------------

SeedSequence::SeedSequence(const std::vector<std::uint32_t>& entropy)
    : entropy_(entropy) {
    pool_.assign(4, 0u);  // DEFAULT_POOL_SIZE = 4
    // mix_entropy: fold entropy (zero-padded) through hashmix, then mix all
    // pool words against each other.
    std::uint32_t hash_const = kInitA;
    for (std::size_t i = 0; i < pool_.size(); ++i) {
        if (i < entropy_.size()) {
            pool_[i] = hashmix(entropy_[i], hash_const);
        } else {
            pool_[i] = hashmix(0u, hash_const);
        }
    }
    for (std::size_t i_src = 0; i_src < pool_.size(); ++i_src) {
        for (std::size_t i_dst = 0; i_dst < pool_.size(); ++i_dst) {
            if (i_src != i_dst) {
                pool_[i_dst] =
                    mix(pool_[i_dst], hashmix(pool_[i_src], hash_const));
            }
        }
    }
    // No remaining-entropy loop: the factor/noise surfaces use scalar seeds
    // whose uint32 decomposition fits the pool (documented limitation).
}

std::vector<std::uint64_t> SeedSequence::generate_state(
    std::size_t n_words_u64) const {
    const std::size_t n_words_u32 = n_words_u64 * 2;
    std::vector<std::uint32_t> state32(n_words_u32, 0u);
    std::uint32_t hash_const = kInitB;
    for (std::size_t i_dst = 0; i_dst < n_words_u32; ++i_dst) {
        std::uint32_t data_val = pool_[i_dst % pool_.size()];  // cycle(pool)
        data_val ^= hash_const;
        hash_const *= kMultB;
        data_val *= hash_const;
        data_val ^= data_val >> kXShift;
        state32[i_dst] = data_val;
    }
    std::vector<std::uint64_t> state64(n_words_u64, 0u);
    for (std::size_t w = 0; w < n_words_u64; ++w) {
        // Little-endian view: <u4 -> <u8.
        state64[w] = static_cast<std::uint64_t>(state32[2 * w]) |
                     (static_cast<std::uint64_t>(state32[2 * w + 1]) << 32);
    }
    return state64;
}

// ---- Pcg64 -------------------------------------------------------------------

Pcg64::Pcg64(const std::vector<std::uint64_t>& state_words,
             const std::vector<std::uint64_t>& inc_words) {
    // pcg64_set_seed -> pcg_setseq_128_srandom_r(initstate, initseq):
    //   state = 0; inc = (initseq << 1) | 1; step; state += initstate; step.
    state_hi_ = 0;
    state_lo_ = 0;
    inc_hi_ = (inc_words[0] << 1) | (inc_words[1] >> 63);
    inc_lo_ = (inc_words[1] << 1) | 1u;
    step();
    state_hi_ += state_words[0];
    state_lo_ += state_words[1];
    if (state_lo_ < state_words[1]) ++state_hi_;  // 128-bit add carry
    step();
}

Pcg64 Pcg64::seeded(std::uint64_t seed) {
    // numpy: entropy int -> little-endian uint32 decomposition (int 0 -> {0}).
    std::vector<std::uint32_t> entropy;
    if (seed == 0) {
        entropy.push_back(0u);
    } else {
        std::uint64_t remaining = seed;
        while (remaining > 0) {
            entropy.push_back(static_cast<std::uint32_t>(remaining & 0xFFFFFFFFull));
            remaining >>= 32;
        }
    }
    SeedSequence sequence(entropy);
    std::vector<std::uint64_t> words = sequence.generate_state(4);
    return Pcg64({words[0], words[1]}, {words[2], words[3]});
}

void Pcg64::step() {
    // state = state * PCG_DEFAULT_MULTIPLIER_128 + inc (128-bit arithmetic).
    constexpr std::uint64_t kMulHi = 2549297995355413924ull;
    constexpr std::uint64_t kMulLo = 4865540595714422341ull;
    const std::uint64_t a0 = state_lo_ & 0xFFFFFFFFull;
    const std::uint64_t a1 = state_lo_ >> 32;
    const std::uint64_t b0 = kMulLo & 0xFFFFFFFFull;
    const std::uint64_t b1 = kMulLo >> 32;
    const std::uint64_t w0 = a0 * b0;
    const std::uint64_t t = a1 * b0 + (w0 >> 32);
    const std::uint64_t w1 = t & 0xFFFFFFFFull;
    const std::uint64_t w2 = t >> 32;
    const std::uint64_t w1b = w1 + a0 * b1;
    std::uint64_t lo = state_lo_ * kMulLo;
    std::uint64_t hi = a1 * b1 + w2 + (w1b >> 32);
    hi += state_hi_ * kMulLo + state_lo_ * kMulHi;
    lo += inc_lo_;
    if (lo < inc_lo_) ++hi;
    hi += inc_hi_;
    state_lo_ = lo;
    state_hi_ = hi;
}

std::uint64_t Pcg64::output_xsl_rr() const {
    const std::uint64_t xored = state_hi_ ^ state_lo_;
    const unsigned rot = static_cast<unsigned>(state_hi_ >> 58);
    return (xored >> rot) | (xored << ((-rot) & 63));
}

std::uint64_t Pcg64::next_uint64() { step(); return output_xsl_rr(); }

std::uint32_t Pcg64::next_uint32() {
    if (has_uint32_) {
        has_uint32_ = false;
        return uinteger_;
    }
    const std::uint64_t next = next_uint64();
    has_uint32_ = true;
    uinteger_ = static_cast<std::uint32_t>(next >> 32);
    return static_cast<std::uint32_t>(next & 0xFFFFFFFFull);
}

std::uint64_t Pcg64::random_interval(std::uint64_t max) {
    if (max == 0) return 0;
    std::uint64_t mask = max;
    mask |= mask >> 1;
    mask |= mask >> 2;
    mask |= mask >> 4;
    mask |= mask >> 8;
    mask |= mask >> 16;
    mask |= mask >> 32;
    if (max <= 0xFFFFFFFFull) {
        std::uint32_t value;
        do {
            value = next_uint32() & static_cast<std::uint32_t>(mask);
        } while (value > max);
        return value;
    }
    std::uint64_t value;
    do {
        value = next_uint64() & mask;
    } while (value > max);
    return value;
}

std::uint64_t Pcg64::random_bounded_uint64(std::uint64_t rng) {
    if (rng == 0) return 0;
    if (rng <= 0xFFFFFFFFull) {
        if (rng == 0xFFFFFFFFull) return next_uint32();
        // buffered_bounded_lemire_uint32(rng): rng inclusive.
        const std::uint32_t rng_excl =
            static_cast<std::uint32_t>(rng + 1);
        std::uint64_t m = static_cast<std::uint64_t>(next_uint32()) * rng_excl;
        std::uint32_t leftover = static_cast<std::uint32_t>(m);
        if (leftover < rng_excl) {
            const std::uint32_t threshold =
                static_cast<std::uint32_t>((0xFFFFFFFFull - rng) % rng_excl);
            while (leftover < threshold) {
                m = static_cast<std::uint64_t>(next_uint32()) * rng_excl;
                leftover = static_cast<std::uint32_t>(m);
            }
        }
        return m >> 32;
    }
    if (rng == 0xFFFFFFFFFFFFFFFFull) return next_uint64();
    // bounded_lemire_uint64(rng): rng inclusive.
    const std::uint64_t rng_excl = rng + 1;
    std::uint64_t m_low = 0;
    std::uint64_t m_high = mul64_split(next_uint64(), rng_excl, &m_low);
    std::uint64_t leftover = m_low;
    if (leftover < rng_excl) {
        const std::uint64_t threshold = (0xFFFFFFFFFFFFFFFFull - rng) % rng_excl;
        while (leftover < threshold) {
            m_high = mul64_split(next_uint64(), rng_excl, &m_low);
            leftover = m_low;
        }
    }
    return m_high;
}

std::vector<std::size_t> choice_indices_without_replacement(
    Pcg64& rng, std::size_t pop_size, std::size_t size) {
    // Generator.choice replace=False, p=None, shuffle=True, pop_size<=10000:
    // Floyd's variant with an open-addressing hash set, then _shuffle_int of
    // the selected block. set_size is the smallest power of two greater than
    // 1.2 * size (via _gen_mask), computed with the same double multiply.
    const std::uint64_t raw = static_cast<std::uint64_t>(1.2 * static_cast<double>(size));
    const std::uint64_t mask = gen_mask(raw);
    const std::uint64_t set_size = mask + 1;
    std::vector<std::uint64_t> hash_set(set_size, 0xFFFFFFFFFFFFFFFFull);
    std::vector<std::size_t> indices(size, 0);
    constexpr std::uint64_t kEmpty = 0xFFFFFFFFFFFFFFFFull;
    for (std::size_t j = pop_size - size; j < pop_size; ++j) {
        const std::uint64_t val = rng.random_bounded_uint64(j);
        std::uint64_t loc = val & mask;
        while (hash_set[loc] != kEmpty && hash_set[loc] != val) {
            loc = (loc + 1) & mask;
        }
        if (hash_set[loc] == kEmpty) {
            hash_set[loc] = val;
            indices[j - (pop_size - size)] = static_cast<std::size_t>(val);
        } else {
            loc = static_cast<std::uint64_t>(j) & mask;
            while (hash_set[loc] != kEmpty) {
                loc = (loc + 1) & mask;
            }
            hash_set[loc] = j;
            indices[j - (pop_size - size)] = j;
        }
    }
    // _shuffle_int(&bg, size, first=1): i in size-1 .. 1. NOTE: the choice
    // path's helper draws with random_bounded_uint64 (Lemire), unlike
    // Generator.shuffle which uses random_interval (masked rejection).
    for (std::size_t i = size; i-- > 1;) {
        const std::uint64_t j = rng.random_bounded_uint64(i);
        std::swap(indices[i], indices[static_cast<std::size_t>(j)]);
    }
    return indices;
}

}  // namespace pwb::cartography::numpy_math
