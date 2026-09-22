#pragma once

// pwb::seismic_io — overflow-checked unsigned arithmetic for shape/offset
// math (#1456). Hostile volume headers and caller-supplied windows must be
// REFUSED before any multiplication wraps, never after (a wrapped element
// count can look "plausible" and pass a size check, then corrupt a read).
//
// Scope: uint64 only — unsigned wraparound is well-defined, so these helpers
// may compute and then verify. Signed int64 arithmetic must never be used
// for sizes: convert to uint64 at the boundary (after a >= 0 check) first.
// Kept header-only/constexpr so descriptors and window specs can use it in
// noexcept inline accessors.

#include <cstdint>
#include <optional>

namespace pwb::seismic_io::checked {

// a * b, or nullopt when the true product exceeds 2^64 - 1.
[[nodiscard]] constexpr std::optional<std::uint64_t> mul(std::uint64_t a,
                                                         std::uint64_t b) {
    if (a == 0 || b == 0) return std::uint64_t{0};
    const std::uint64_t product = a * b;  // unsigned wrap is defined
    if (product / a != b) return std::nullopt;
    return product;
}

// a + b, or nullopt when the sum wraps.
[[nodiscard]] constexpr std::optional<std::uint64_t> add(std::uint64_t a,
                                                         std::uint64_t b) {
    const std::uint64_t sum = a + b;  // unsigned wrap is defined
    if (sum < a) return std::nullopt;
    return sum;
}

// a * b * c checked left-to-right, or nullopt on any wrap. Shape products
// are exactly this: three axis counts whose full product must be proven to
// fit BEFORE it is compared against a cap (issue #1456 — the old code
// compared the already-wrapped product).
[[nodiscard]] constexpr std::optional<std::uint64_t> mul3(std::uint64_t a,
                                                          std::uint64_t b,
                                                          std::uint64_t c) {
    const auto first = mul(a, b);
    if (!first.has_value()) return std::nullopt;
    return mul(*first, c);
}

// Product of three non-negative int64 axis counts as uint64. A negative
// axis is rejected (it is never a legal shape).
[[nodiscard]] constexpr std::optional<std::uint64_t> shape_product(
    std::int64_t a, std::int64_t b, std::int64_t c) {
    if (a < 0 || b < 0 || c < 0) return std::nullopt;
    return mul3(static_cast<std::uint64_t>(a), static_cast<std::uint64_t>(b),
                static_cast<std::uint64_t>(c));
}

}  // namespace pwb::seismic_io::checked
