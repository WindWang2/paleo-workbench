// CONV-27 internal — numpy-exact numeric primitives for scalar_style.
//
// Reproducing the frozen Python oracle bit-for-bit requires more than IEEE
// arithmetic: numpy's reductions and RNG streams are part of the contract.
//
//  * pairwise_sum — numpy's float64 pairwise summation (loops_utils.h):
//    sequential below 8 elements, 8-way unrolled blocks up to
//    PW_BLOCKSIZE=128, recursive halves above. This is what
//    `ndarray.sum()` computes for contiguous float64 data, so the
//    Fisher-Jenks segment sums must use it, not a naive loop.
//  * SeedSequence / Pcg64 — numpy default_rng's seeding chain and bit
//    generator (SeedSequence pool mixing + PCG64 setseq/XSL-RR, with the
//    buffered uint32 half-stream). Streams are stable per NEP 19.
//  * random_interval / random_bounded_uint64 — the bounded-draw functions
//    used by Generator.shuffle (masked rejection) and Generator.choice
//    (buffered 32-bit Lemire), matching numpy/src/distributions.
//  * choice_indices_without_replacement — Generator.choice(...,
//    replace=False, p=None, shuffle=True) for pop_size <= 10000: Floyd's
//    variant with the open-addressing hash set, then a final _shuffle_int
//    of the selected block.
//
// Verified against frozen arrays generated with numpy 2.5.3.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace pwb::cartography::numpy_math {

// numpy float64 pairwise sum (contiguous, exactly the C loops numpy runs).
double pairwise_sum(const double* data, std::size_t n);

// numpy SeedSequence: uint32 pool mixing + generate_state(n uint64 words).
class SeedSequence {
public:
    // entropy is the little-endian uint32 decomposition of a non-negative
    // Python int (int 0 -> {0}).
    explicit SeedSequence(const std::vector<std::uint32_t>& entropy);
    std::vector<std::uint64_t> generate_state(std::size_t n_words_u64) const;

private:
    std::vector<std::uint32_t> pool_;  // pool_size = 4 (numpy default)
    std::vector<std::uint32_t> entropy_;
};

// numpy PCG64 (setseq_128 + XSL-RR output + buffered uint32 halves).
class Pcg64 {
public:
    Pcg64(const std::vector<std::uint64_t>& state_words,
          const std::vector<std::uint64_t>& inc_words);
    // default_rng(seed): SeedSequence(seed).generate_state(4) split into
    // state = words[0..1], inc = words[2..3] (big-word order per
    // pcg64_set_seed: s = (seed[0] << 64) | seed[1]).
    static Pcg64 seeded(std::uint64_t seed);

    std::uint64_t next_uint64();
    std::uint32_t next_uint32();  // buffered halves: low first, then high

    // random_interval(max): masked rejection in [0, max].
    std::uint64_t random_interval(std::uint64_t max);
    // random_bounded_uint64(off=0, rng) with Lemire paths (rng inclusive).
    std::uint64_t random_bounded_uint64(std::uint64_t rng);

private:
    void step();
    std::uint64_t output_xsl_rr() const;
    std::uint64_t state_hi_ = 0;
    std::uint64_t state_lo_ = 0;
    std::uint64_t inc_hi_ = 0;
    std::uint64_t inc_lo_ = 0;
    bool has_uint32_ = false;
    std::uint32_t uinteger_ = 0;
};

// Generator.choice(pop_size, size, replace=False, p=None, shuffle=True),
// pop_size <= 10000 (Floyd's variant): returns the selected indices in the
// exact order numpy would hand them to a.take().
std::vector<std::size_t> choice_indices_without_replacement(
    Pcg64& rng, std::size_t pop_size, std::size_t size);

}  // namespace pwb::cartography::numpy_math
