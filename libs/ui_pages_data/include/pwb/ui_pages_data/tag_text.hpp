// UI-06 — tag input parsing (tag_widgets.py :: parse_multi_tag_input).
#pragma once

#include <string>
#include <vector>

namespace pwb::ui_pages_data {

// Max tag name length (characters, not bytes) — _MAX_TAG_NAME_LENGTH.
inline constexpr int kMaxTagNameLength = 128;

// Split a free-form multi-tag input into ordered, de-duplicated names.
// Separators: ASCII/full-width commas and semicolons plus any whitespace
// (incl. U+3000). Each token: strip → strip leading '#' → strip → truncate
// to 128 characters. Empty tokens dropped; first occurrence wins.
std::vector<std::string> parse_multi_tag_input(const std::string& text);

}  // namespace pwb::ui_pages_data
