// 05 线 — 共享井身份实现（见头注释的设计口径）。

#include "pwb/ui_workers/well_identity.hpp"

namespace pwb::ui_workers {

namespace {

bool is_space_byte(char c) {
    return c == ' ' || c == '\t' || c == '\r' || c == '\n' || c == '\f' ||
           c == '\v';
}

char lower_byte(char c) {
    return c >= 'A' && c <= 'Z' ? static_cast<char>(c + 32) : c;
}

std::string to_hex128(std::uint64_t high, std::uint64_t low) {
    static const char* kDigits = "0123456789abcdef";
    std::string out;
    out.reserve(32);
    for (int shift = 60; shift >= 0; shift -= 4) {
        out.push_back(kDigits[(high >> shift) & 0xF]);
    }
    for (int shift = 60; shift >= 0; shift -= 4) {
        out.push_back(kDigits[(low >> shift) & 0xF]);
    }
    return out;
}

void fnv1a128_mix(std::uint64_t* high, std::uint64_t* low, unsigned char byte) {
    // 128 位 FNV-1a：prime = 2^88 + 2^8 + 0x3b（以 64 位半字两次乘模）。
    // 实现为对 high/low 各自独立的 64 位 FNV-1a 通道（盐不同）——身份 id
    // 只要求确定性 + 抗偶合碰撞，不要求密码学强度。
    const std::uint64_t kPrime = 1099511628211ULL;
    *high ^= (0x9E3779B97F4A7C15ULL ^ byte);
    *high *= kPrime;
    *low ^= (0xC2B2AE3D27D4EB4FULL ^ (byte + 0x5B));
    *low *= kPrime;
}

}  // namespace

std::string well_identity_key(const std::string& name) {
    std::size_t begin = 0;
    std::size_t end = name.size();
    while (begin < end && is_space_byte(name[begin])) ++begin;
    while (end > begin && is_space_byte(name[end - 1])) --end;
    std::string out;
    out.reserve(end - begin);
    bool pending_space = false;
    for (std::size_t i = begin; i < end; ++i) {
        const char c = name[i];
        if (is_space_byte(c)) {
            pending_space = !out.empty();
            continue;
        }
        if (pending_space) {
            out.push_back(' ');
            pending_space = false;
        }
        out.push_back(lower_byte(c));
    }
    return out;
}

std::string well_identity_id(const std::string& identity_key) {
    std::uint64_t high = 1469598103934665603ULL;
    std::uint64_t low = 14695981039346656037ULL;
    for (unsigned char byte : identity_key) {
        fnv1a128_mix(&high, &low, byte);
    }
    return "wi-" + to_hex128(high, low);
}

WellIdentityRegistry& WellIdentityRegistry::instance() {
    static WellIdentityRegistry registry;
    return registry;
}

std::optional<WellIdentity> WellIdentityRegistry::register_well(
    const std::string& name, const std::string& origin) {
    const std::string key = well_identity_key(name);
    if (key.empty()) return std::nullopt;
    const std::lock_guard<std::mutex> lock(mutex_);
    for (const WellIdentity& entry : entries_) {
        if (entry.key == key) return entry;  // first-register-wins
    }
    WellIdentity identity;
    identity.key = key;
    identity.name = name;
    identity.origin = origin;
    identity.well_id = well_identity_id(key);
    entries_.push_back(identity);
    return identity;
}

std::optional<WellIdentity> WellIdentityRegistry::find(
    const std::string& identity_key) const {
    const std::lock_guard<std::mutex> lock(mutex_);
    for (const WellIdentity& entry : entries_) {
        if (entry.key == identity_key) return entry;
    }
    return std::nullopt;
}

std::optional<WellIdentity> WellIdentityRegistry::find_by_name(
    const std::string& name) const {
    return find(well_identity_key(name));
}

std::vector<WellIdentity> WellIdentityRegistry::snapshot() const {
    const std::lock_guard<std::mutex> lock(mutex_);
    return entries_;
}

void WellIdentityRegistry::clear_for_tests() {
    const std::lock_guard<std::mutex> lock(mutex_);
    entries_.clear();
}

}  // namespace pwb::ui_workers
