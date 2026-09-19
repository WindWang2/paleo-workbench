#include "pwb/ui_workers/synthetic_points.hpp"

#include <algorithm>
#include <cstring>

#include <pwb/domain/sha256.hpp>
#include "pwb/ui_workers/worker_common.hpp"

namespace pwb::ui_workers {

// ---------------------------------------------------------------------------
// SHA-512 (FIPS 180-4) — needed by Python's str-seed scheme
// (random.Random(str) -> int.from_bytes(seed + sha512(seed).digest())).
// ---------------------------------------------------------------------------

namespace {

constexpr std::uint64_t kSha512K[80] = {
    0x428a2f98d728ae22ULL, 0x7137449123ef65cdULL, 0xb5c0fbcfec4d3b2fULL,
    0xe9b5dba58189dbbcULL, 0x3956c25bf348b538ULL, 0x59f111f1b605d019ULL,
    0x923f82a4af194f9bULL, 0xab1c5ed5da6d8118ULL, 0xd807aa98a3030242ULL,
    0x12835b0145706fbeULL, 0x243185be4ee4b28cULL, 0x550c7dc3d5ffb4e2ULL,
    0x72be5d74f27b896fULL, 0x80deb1fe3b1696b1ULL, 0x9bdc06a725c71235ULL,
    0xc19bf174cf692694ULL, 0xe49b69c19ef14ad2ULL, 0xefbe4786384f25e3ULL,
    0x0fc19dc68b8cd5b5ULL, 0x240ca1cc77ac9c65ULL, 0x2de92c6f592b0275ULL,
    0x4a7484aa6ea6e483ULL, 0x5cb0a9dcbd41fbd4ULL, 0x76f988da831153b5ULL,
    0x983e5152ee66dfabULL, 0xa831c66d2db43210ULL, 0xb00327c898fb213fULL,
    0xbf597fc7beef0ee4ULL, 0xc6e00bf33da88fc2ULL, 0xd5a79147930aa725ULL,
    0x06ca6351e003826fULL, 0x142929670a0e6e70ULL, 0x27b70a8546d22ffcULL,
    0x2e1b21385c26c926ULL, 0x4d2c6dfc5ac42aedULL, 0x53380d139d95b3dfULL,
    0x650a73548baf63deULL, 0x766a0abb3c77b2a8ULL, 0x81c2c92e47edaee6ULL,
    0x92722c851482353bULL, 0xa2bfe8a14cf10364ULL, 0xa81a664bbc423001ULL,
    0xc24b8b70d0f89791ULL, 0xc76c51a30654be30ULL, 0xd192e819d6ef5218ULL,
    0xd69906245565a910ULL, 0xf40e35855771202aULL, 0x106aa07032bbd1b8ULL,
    0x19a4c116b8d2d0c8ULL, 0x1e376c085141ab53ULL, 0x2748774cdf8eeb99ULL,
    0x34b0bcb5e19b48a8ULL, 0x391c0cb3c5c95a63ULL, 0x4ed8aa4ae3418acbULL,
    0x5b9cca4f7763e373ULL, 0x682e6ff3d6b2b8a3ULL, 0x748f82ee5defb2fcULL,
    0x78a5636f43172f60ULL, 0x84c87814a1f0ab72ULL, 0x8cc702081a6439ecULL,
    0x90befffa23631e28ULL, 0xa4506cebde82bde9ULL, 0xbef9a3f7b2c67915ULL,
    0xc67178f2e372532bULL, 0xca273eceea26619cULL, 0xd186b8c721c0c207ULL,
    0xeada7dd6cde0eb1eULL, 0xf57d4f7fee6ed178ULL, 0x06f067aa72176fbaULL,
    0x0a637dc5a2c898a6ULL, 0x113f9804bef90daeULL, 0x1b710b35131c471bULL,
    0x28db77f523047d84ULL, 0x32caab7b40c72493ULL, 0x3c9ebe0a15c9bebcULL,
    0x431d67c49c100d4cULL, 0x4cc5d4becb3e42b6ULL, 0x597f299cfc657e2aULL,
    0x5fcb6fab3ad6faecULL, 0x6c44198c4a475817ULL,
};

inline std::uint64_t rotr64(std::uint64_t x, unsigned n) {
    return (x >> n) | (x << (64 - n));
}

}  // namespace

std::vector<std::uint8_t> sha512_bytes(const std::string& text) {
    std::uint64_t h[8] = {0x6a09e667f3bcc908ULL, 0xbb67ae8584caa73bULL,
                          0x3c6ef372fe94f82bULL, 0xa54ff53a5f1d36f1ULL,
                          0x510e527fade682d1ULL, 0x9b05688c2b3e6c1fULL,
                          0x1f83d9abfb41bd6bULL, 0x5be0cd19137e2179ULL};

    // Padded message: data + 0x80 + zeros + 128-bit length.
    const std::uint64_t bit_len =
        static_cast<std::uint64_t>(text.size()) * 8ULL;
    std::vector<std::uint8_t> msg(text.begin(), text.end());
    msg.push_back(0x80);
    while (msg.size() % 128 != 112) msg.push_back(0);
    for (int i = 0; i < 8; ++i) msg.push_back(0);  // high 64 bits = 0
    for (int i = 7; i >= 0; --i) {
        msg.push_back(static_cast<std::uint8_t>((bit_len >> (i * 8)) & 0xff));
    }

    for (std::size_t block = 0; block < msg.size(); block += 128) {
        std::uint64_t w[80];
        for (int i = 0; i < 16; ++i) {
            w[i] = 0;
            for (int j = 0; j < 8; ++j) {
                w[i] = (w[i] << 8) | msg[block + i * 8 + j];
            }
        }
        for (int i = 16; i < 80; ++i) {
            const std::uint64_t s0 = rotr64(w[i - 15], 1) ^
                                     rotr64(w[i - 15], 8) ^ (w[i - 15] >> 7);
            const std::uint64_t s1 = rotr64(w[i - 2], 19) ^
                                     rotr64(w[i - 2], 61) ^ (w[i - 2] >> 6);
            w[i] = w[i - 16] + s0 + w[i - 7] + s1;
        }
        std::uint64_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4],
                      f = h[5], g = h[6], hh = h[7];
        for (int i = 0; i < 80; ++i) {
            const std::uint64_t s1 =
                rotr64(e, 14) ^ rotr64(e, 18) ^ rotr64(e, 41);
            const std::uint64_t ch = (e & f) ^ (~e & g);
            const std::uint64_t t1 = hh + s1 + ch + kSha512K[i] + w[i];
            const std::uint64_t s0 =
                rotr64(a, 28) ^ rotr64(a, 34) ^ rotr64(a, 39);
            const std::uint64_t maj = (a & b) ^ (a & c) ^ (b & c);
            const std::uint64_t t2 = s0 + maj;
            hh = g;
            g = f;
            f = e;
            e = d + t1;
            d = c;
            c = b;
            b = a;
            a = t1 + t2;
        }
        h[0] += a; h[1] += b; h[2] += c; h[3] += d;
        h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
    }

    std::vector<std::uint8_t> digest(64);
    for (int i = 0; i < 8; ++i) {
        for (int j = 0; j < 8; ++j) {
            digest[i * 8 + j] =
                static_cast<std::uint8_t>((h[i] >> (56 - j * 8)) & 0xff);
        }
    }
    return digest;
}

// ---------------------------------------------------------------------------
// PyRandom — CPython random.Random parity.
//
// seed(str) v2: n = int.from_bytes(text + sha512(text), "big"), then
// init_by_array with n split into 32-bit limbs little-endian (CPython's
// _randommodule.c uses exactly the reference init_by_array).
// ---------------------------------------------------------------------------

namespace {

constexpr int kMtN = 624;
constexpr int kMtM = 397;
constexpr std::uint32_t kMatrixA = 0x9908b0dfU;
constexpr std::uint32_t kUpperMask = 0x80000000U;
constexpr std::uint32_t kLowerMask = 0x7fffffffU;

}  // namespace

PyRandom::PyRandom(const std::string& seed_text) {
    seed_bytes_to_int(seed_text);
}

void PyRandom::seed_bytes_to_int(const std::string& seed_text) {
    // n = int.from_bytes(seed_bytes + sha512(seed_bytes).digest(), "big")
    auto digest = sha512_bytes(seed_text);
    std::vector<std::uint8_t> bytes(seed_text.begin(), seed_text.end());
    bytes.insert(bytes.end(), digest.begin(), digest.end());
    // Limbs little-endian: limb[i] covers bytes[len-4-4i .. len-4i)
    // interpreted big-endian.
    const std::size_t n_limbs = (bytes.size() + 3) / 4;
    std::vector<std::uint32_t> key(n_limbs, 0);
    for (std::size_t i = 0; i < n_limbs; ++i) {
        std::uint32_t limb = 0;
        const std::size_t end = bytes.size() - i * 4;
        const std::size_t start = end >= 4 ? end - 4 : 0;
        for (std::size_t j = start; j < end; ++j) {
            limb = (limb << 8) | bytes[j];
        }
        key[i] = limb;
    }

    // init_genrand(19650218) + init_by_array(key).
    mt_[0] = 19650218U;
    for (int i = 1; i < kMtN; ++i) {
        mt_[i] = 1812433253U * (mt_[i - 1] ^ (mt_[i - 1] >> 30)) +
                 static_cast<std::uint32_t>(i);
    }
    index_ = kMtN;
    int i = 1, j = 0;
    const int key_length = static_cast<int>(key.size());
    for (int k = std::max(kMtN, key_length); k > 0; --k) {
        mt_[i] = (mt_[i] ^
                  ((mt_[i - 1] ^ (mt_[i - 1] >> 30)) * 1664525U)) +
                 key[j] + static_cast<std::uint32_t>(j);
        ++i;
        ++j;
        if (i >= kMtN) {
            mt_[0] = mt_[kMtN - 1];
            i = 1;
        }
        if (j >= key_length) j = 0;
    }
    for (int k = kMtN - 1; k > 0; --k) {
        mt_[i] = (mt_[i] ^
                  ((mt_[i - 1] ^ (mt_[i - 1] >> 30)) * 1566083941U)) -
                 static_cast<std::uint32_t>(i);
        ++i;
        if (i >= kMtN) {
            mt_[0] = mt_[kMtN - 1];
            i = 1;
        }
    }
    mt_[0] = kUpperMask;
}

void PyRandom::seed_bigint(long long value) {
    // int seed -> limbs little-endian of abs(value).
    std::vector<std::uint32_t> key;
    unsigned long long n = value < 0
                               ? static_cast<unsigned long long>(-value)
                               : static_cast<unsigned long long>(value);
    if (n == 0) key.push_back(0);
    while (n) {
        key.push_back(static_cast<std::uint32_t>(n & 0xffffffffULL));
        n >>= 32;
    }
    // Same init_by_array path (duplicated tail of seed_bytes_to_int).
    mt_[0] = 19650218U;
    for (int i = 1; i < kMtN; ++i) {
        mt_[i] = 1812433253U * (mt_[i - 1] ^ (mt_[i - 1] >> 30)) +
                 static_cast<std::uint32_t>(i);
    }
    index_ = kMtN;
    int i = 1, j = 0;
    const int key_length = static_cast<int>(key.size());
    for (int k = std::max(kMtN, key_length); k > 0; --k) {
        mt_[i] = (mt_[i] ^
                  ((mt_[i - 1] ^ (mt_[i - 1] >> 30)) * 1664525U)) +
                 key[j] + static_cast<std::uint32_t>(j);
        ++i;
        ++j;
        if (i >= kMtN) {
            mt_[0] = mt_[kMtN - 1];
            i = 1;
        }
        if (j >= key_length) j = 0;
    }
    for (int k = kMtN - 1; k > 0; --k) {
        mt_[i] = (mt_[i] ^
                  ((mt_[i - 1] ^ (mt_[i - 1] >> 30)) * 1566083941U)) -
                 static_cast<std::uint32_t>(i);
        ++i;
        if (i >= kMtN) {
            mt_[0] = mt_[kMtN - 1];
            i = 1;
        }
    }
    mt_[0] = kUpperMask;
}

std::uint32_t PyRandom::genrand_uint32() {
    if (index_ >= kMtN) {
        for (int kk = 0; kk < kMtN; ++kk) {
            const std::uint32_t y =
                (mt_[kk] & kUpperMask) | (mt_[(kk + 1) % kMtN] & kLowerMask);
            mt_[kk] = mt_[(kk + kMtM) % kMtN] ^ (y >> 1) ^
                      ((y & 1U) ? kMatrixA : 0U);
        }
        index_ = 0;
    }
    std::uint32_t y = mt_[index_++];
    y ^= (y >> 11);
    y ^= (y << 7) & 0x9d2c5680U;
    y ^= (y << 15) & 0xefc60000U;
    y ^= (y >> 18);
    return y;
}

double PyRandom::random() {
    const double a = static_cast<double>(genrand_uint32() >> 5);
    const double b = static_cast<double>(genrand_uint32() >> 6);
    return (a * 67108864.0 + b) * (1.0 / 9007199254740992.0);
}

// ---------------------------------------------------------------------------
// synthetic_sample_points — geoviz port.
// ---------------------------------------------------------------------------

std::vector<std::map<std::string, std::any>> synthetic_sample_points(
    int seed, const std::string& factor_type, int count) {
    PyRandom rng(std::to_string(seed) + ":" + factor_type);
    // sha256(factor_type.encode()).digest()[:4] big-endian % 20.
    const std::string hex = pwb::domain::Sha256::of_bytes(factor_type);
    std::uint32_t head = 0;
    for (int i = 0; i < 4; ++i) {
        const auto byte = static_cast<std::uint32_t>(
            std::stoul(hex.substr(static_cast<std::size_t>(i) * 2, 2),
                       nullptr, 16));
        head = (head << 8) | byte;
    }
    const double base = 10.0 + static_cast<double>(head % 20);

    std::vector<std::map<std::string, std::any>> out;
    out.reserve(static_cast<std::size_t>(count));
    for (int i = 0; i < count; ++i) {
        std::map<std::string, std::any> point;
        point["well"] = "A" + std::to_string(i + 1);
        point["x"] = py_round(114.0 + rng.random() * 0.3, 6);
        point["y"] = py_round(22.5 + rng.random() * 0.3, 6);
        point["value"] = py_round(base + rng.random() * 40.0, 3);
        out.push_back(std::move(point));
    }
    return out;
}

}  // namespace pwb::ui_workers
