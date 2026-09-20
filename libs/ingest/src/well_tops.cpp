#include "pwb/ingest/well_parsers.hpp"

#include "pwb/ingest/py_compat.hpp"

namespace pwb::ingest {

namespace {

// str.split() with no separator: runs of Unicode whitespace.
// #1386: the whitespace predicate is the same one py_strip uses — ASCII
// is_py_space members plus the non-ASCII str.isspace() set — so a row
// separated by U+3000 (full-width space, what Excel/中文 editors emit)
// splits the same way Python does instead of collapsing to one token.
std::vector<std::string> py_split(std::string_view s) {
    auto is_space = [](char32_t cp) {
        return cp < 128 ? (cp == ' ' || cp == '\t' || cp == '\n' ||
                           cp == '\r' || cp == '\f' || cp == '\v')
                        : detail::cp_is_unicode_space(cp);
    };
    std::vector<std::string> out;
    size_t i = 0;
    while (i < s.size()) {
        while (i < s.size()) {
            auto cp = detail::utf8_code_point(s, i);
            if (!cp || !is_space(cp->cp)) break;
            i += cp->size;
        }
        if (i >= s.size()) break;
        size_t start = i;
        while (i < s.size()) {
            auto cp = detail::utf8_code_point(s, i);
            if (cp && is_space(cp->cp)) break;
            // An ill-formed byte is not a separator: consume one byte so a
            // truncated sequence can never wedge the loop (nullopt->size UB).
            i += cp ? cp->size : 1;
        }
        out.emplace_back(s.substr(start, i - start));
    }
    return out;
}

}  // namespace

std::vector<WellTop> parse_well_tops_text(std::string_view text) {
    std::vector<WellTop> tops;
    // str.splitlines(): \n, \r\n and lone \r all terminate a line
    size_t line_start = 0;
    auto handle_line = [&](std::string_view line) {
        std::string stripped = py_strip(line);
        if (stripped.empty() || stripped[0] == '#') return;
        std::vector<std::string> tokens = py_split(stripped);
        if (tokens.size() < 3) return;
        auto md = py_parse_float(tokens[2]);
        if (!md) return;
        WellTop top;
        top.well_name = tokens[0];
        top.top_name = tokens[1];
        top.md = *md;
        if (tokens.size() >= 7) {
            top.tvd = py_parse_float(tokens[6]);  // bad value -> nullopt
        }
        tops.push_back(std::move(top));
    };
    for (size_t i = 0; i <= text.size(); ++i) {
        if (i == text.size()) {
            if (i > line_start) handle_line(text.substr(line_start, i - line_start));
            break;
        }
        if (text[i] == '\n') {
            size_t end = i;
            size_t next = i + 1;
            if (end > line_start && text[end - 1] == '\r') --end;
            handle_line(text.substr(line_start, end - line_start));
            line_start = next;
        } else if (text[i] == '\r') {
            // lone \r unless followed by \n (handled above on the \n pass)
            if (i + 1 >= text.size() || text[i + 1] != '\n') {
                handle_line(text.substr(line_start, i - line_start));
                line_start = i + 1;
            }
        }
    }
    return tops;
}

}  // namespace pwb::ingest
