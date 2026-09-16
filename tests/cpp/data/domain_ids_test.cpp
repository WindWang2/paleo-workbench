// data.domain_ids — strong id types, storage-segment gate, id minting,
// ISO-8601 clock (test-plan.md §2, row 1).
#include "pwb_test.hpp"

#include "pwb/domain/diagnostics.hpp"
#include "pwb/domain/ids.hpp"

#include <type_traits>
#include <unordered_map>

namespace {

using pwb::domain::AssetId;
using pwb::domain::LayerId;
using pwb::domain::OperationId;
using pwb::domain::RunId;
using pwb::domain::VersionId;

}  // namespace

PWB_TEST(explicit_construction_only) {
    // No implicit conversion from std::string: mistyped ids fail at compile
    // time (checked here as a static contract, not just convention).
    static_assert(!std::is_convertible_v<std::string, AssetId>,
                  "AssetId must be explicit");
    static_assert(!std::is_convertible_v<std::string, VersionId>,
                  "VersionId must be explicit");
    AssetId asset(std::string("asset_abc123"));
    PWB_CHECK(asset.str() == "asset_abc123");
    VersionId version(std::string("ver_abc123"));
    PWB_CHECK(version.str() == "ver_abc123");
}

PWB_TEST(equality_and_ordering) {
    AssetId a(std::string("asset_1"));
    AssetId b(std::string("asset_1"));
    AssetId c(std::string("asset_2"));
    PWB_CHECK(a == b);
    PWB_CHECK(!(a != b));
    PWB_CHECK(a != c);
    PWB_CHECK(a < c);
    // Distinct id families never compare equal (different types entirely).
    LayerId layer(std::string("asset_1"));
    PWB_CHECK(layer.str() == a.str());
}

PWB_TEST(hashable_for_maps) {
    std::unordered_map<AssetId, int, pwb::domain::IdHash> table;
    table.emplace(AssetId(std::string("asset_1")), 7);
    const auto it = table.find(AssetId(std::string("asset_1")));
    PWB_CHECK(it != table.end());
    PWB_CHECK(it->second == 7);
}

PWB_TEST(safe_storage_segment_gate) {
    using pwb::domain::is_safe_storage_segment;
    PWB_CHECK(is_safe_storage_segment("ver_abc123"));
    PWB_CHECK(is_safe_storage_segment("asset_1.2-3_x"));
    PWB_CHECK(!is_safe_storage_segment(""));
    PWB_CHECK(!is_safe_storage_segment(".hidden"));
    PWB_CHECK(!is_safe_storage_segment("../escape"));
    PWB_CHECK(!is_safe_storage_segment("a/b"));
    PWB_CHECK(!is_safe_storage_segment("has space"));
    PWB_CHECK(!is_safe_storage_segment("snowman\xE2\x98\x83"));
}

PWB_TEST(mint_format_and_determinism) {
    pwb::domain::seed_id_generator_for_tests(12345ULL);
    const std::string first = pwb::domain::make_id("ver_");
    const std::string second = pwb::domain::make_id("ver_");
    PWB_CHECK(first.size() == std::string("ver_").size() + 12);
    PWB_CHECK(second.size() == first.size());
    PWB_CHECK(first != second);
    for (char c : first.substr(4)) {
        const bool hex = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
        PWB_CHECK(hex);
    }
    // Reseeding reproduces the sequence (deterministic fixtures/tests).
    pwb::domain::seed_id_generator_for_tests(12345ULL);
    PWB_CHECK(pwb::domain::make_id("ver_") == first);
}

PWB_TEST(iso8601_clock_shape) {
    const std::string now = pwb::domain::now_iso8601();
    // "YYYY-MM-DDTHH:MM:SS.ffffff+00:00" — 32 chars, six-digit fraction.
    PWB_CHECK(now.size() == 32);
    PWB_CHECK(now.substr(now.size() - 6) == "+00:00");
    PWB_CHECK(now[10] == 'T');
    PWB_CHECK(now[19] == '.');
    const std::string fixed = pwb::domain::fixed_iso8601_for_tests();
    PWB_CHECK(fixed == pwb::domain::fixed_iso8601_for_tests());
    PWB_CHECK(fixed.size() == 32);
}
