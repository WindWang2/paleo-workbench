// UI-06 — data_asset_table column/search helpers + resource_table status.
#include <pwb/ui_pages_data/table_model.hpp>

#include <set>

namespace pwb::ui_pages_data {

std::string_view status_color_token(std::string_view status) {
    // resource_table._status_token.
    if (status == "parsed") return "SUCCESS";
    if (status == "error") return "ERROR_RED";
    return "TEXT_SECONDARY";
}

std::vector<std::string>
ordered_column_keys(const std::vector<std::string>& requested) {
    // Python: requested = set(keys); ordered = [c.key for c in
    // COLUMN_DEFINITIONS if c.key in requested or c.required];
    // empty → ["name"].
    const std::set<std::string> want(requested.begin(), requested.end());
    std::vector<std::string> ordered;
    for (const auto& column : column_definitions()) {
        const std::string key(column.key);
        if (want.count(key) || column.required) ordered.push_back(key);
    }
    if (ordered.empty()) ordered.push_back("name");
    return ordered;
}

std::string normalize_search_text(const std::string& text) {
    // str.strip().lower() — strip ASCII+Unicode whitespace; lowercasing is
    // ASCII-exact here (CJK has no case; a full Unicode toLower is out of
    // scope for the Qt-free core — the Qt shell may use QString::toLower
    // for exotic input, noted in the ledger).
    std::size_t lo = 0, hi = text.size();
    auto ascii_space = [](unsigned char c) {
        return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\v' ||
               c == '\f';
    };
    // Multi-byte whitespace Python strip() removes: U+00A0 (C2 A0) and
    // U+3000 (E3 80 80) — the realistic non-ASCII cases here.
    auto multibyte_space_at = [&](std::size_t i) -> int {
        if (i + 1 < hi && text[i] == '\xC2' && text[i + 1] == '\xA0')
            return 2;
        if (i + 2 < hi && text[i] == '\xE3' && text[i + 1] == '\x80' &&
            text[i + 2] == '\x80')
            return 3;
        return 0;
    };
    auto multibyte_space_before = [&](std::size_t end) -> int {
        if (end >= 2 && text[end - 2] == '\xC2' && text[end - 1] == '\xA0')
            return 2;
        if (end >= 3 && text[end - 3] == '\xE3' && text[end - 2] == '\x80' &&
            text[end - 1] == '\x80')
            return 3;
        return 0;
    };
    while (lo < hi) {
        if (ascii_space(text[lo])) {
            ++lo;
            continue;
        }
        const int len = multibyte_space_at(lo);
        if (!len) break;
        lo += len;
    }
    while (hi > lo) {
        if (ascii_space(text[hi - 1])) {
            --hi;
            continue;
        }
        const int len = multibyte_space_before(hi);
        if (!len) break;
        hi -= len;
    }
    std::string out = text.substr(lo, hi - lo);
    for (auto& c : out) {
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c + 32);
    }
    return out;
}

}  // namespace pwb::ui_pages_data
