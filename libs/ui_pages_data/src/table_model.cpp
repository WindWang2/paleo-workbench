// UI-06 — data_asset_table column/search helpers + resource_table status.
#include <pwb/domain/text.hpp>  // lowercase_utf8 (#1391)
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
    // str.strip().lower() — strip ASCII+Unicode whitespace; #1391: lowering
    // is now the generated str.lower() table (lowercase_utf8), not
    // ASCII-only, so accented/Cyrillic/Greek names fold like Python.
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
    return pwb::domain::lowercase_utf8(text.substr(lo, hi - lo));
}

}  // namespace pwb::ui_pages_data
