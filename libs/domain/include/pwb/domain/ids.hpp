// Strongly-typed domain identifiers (CPP-201).
//
// Ids are string-carried value types with explicit construction: no implicit
// std::string conversion, so a VersionId can never silently stand in for an
// AssetId at a call site. The wire format follows the Python side
// (`{prefix}_{12 hex}`, see project/models.py `_id`).
#pragma once

#include <array>
#include <cstddef>
#include <functional>
#include <ostream>
#include <string>
#include <string_view>

namespace pwb::domain {

namespace detail {
struct IdTag {};
}  // namespace detail

template <typename Tag>
class StrongId {
public:
    StrongId() = default;
    explicit StrongId(std::string value) : value_(std::move(value)) {}
    explicit StrongId(std::string_view value)
        : value_(value.begin(), value.end()) {}

    const std::string& str() const noexcept { return value_; }
    bool empty() const noexcept { return value_.empty(); }
    explicit operator bool() const noexcept { return !value_.empty(); }

    friend bool operator==(const StrongId& a, const StrongId& b) {
        return a.value_ == b.value_;
    }
    friend bool operator!=(const StrongId& a, const StrongId& b) {
        return !(a == b);
    }
    friend bool operator<(const StrongId& a, const StrongId& b) {
        return a.value_ < b.value_;
    }

    friend std::ostream& operator<<(std::ostream& os, const StrongId& id) {
        return os << id.value_;
    }

private:
    std::string value_;
};

struct AssetIdTag : detail::IdTag {};
struct VersionIdTag : detail::IdTag {};
struct RunIdTag : detail::IdTag {};
struct LayerIdTag : detail::IdTag {};
struct EntityIdTag : detail::IdTag {};
struct OperationIdTag : detail::IdTag {};
struct WorkingIdTag : detail::IdTag {};
struct ProjectIdTag : detail::IdTag {};

using AssetId = StrongId<AssetIdTag>;
using VersionId = StrongId<VersionIdTag>;
using RunId = StrongId<RunIdTag>;
using LayerId = StrongId<LayerIdTag>;
using EntityId = StrongId<EntityIdTag>;
using OperationId = StrongId<OperationIdTag>;
using WorkingId = StrongId<WorkingIdTag>;
using ProjectId = StrongId<ProjectIdTag>;

// Storage-path safety gate (catalog/storage.py `is_safe_entity_id` / service
// `_is_safe_version_id`): ids interpolate into `{stage}/{asset}/{version}/`
// path segments, so anything traversal-shaped must be rejected BEFORE any
// directory is created. Non-empty, no leading dot, [A-Za-z0-9._-] only.
bool is_safe_storage_segment(std::string_view id);

// Generates `{prefix}{12 hex}` ids from a cryptographically-seeded source.
// Deterministic seeding is available for tests.
std::string make_id(std::string_view prefix);
void seed_id_generator_for_tests(std::uint64_t seed);

struct IdHash {
    template <typename Tag>
    std::size_t operator()(const StrongId<Tag>& id) const noexcept {
        return std::hash<std::string>{}(id.str());
    }
};

}  // namespace pwb::domain
