// UI-06 — tag_widgets.parse_multi_tag_input.
//
// Python semantics to mirror exactly:
//   _MULTI_TAG_SEPARATORS = re.compile(r"[,，;；\s]+")
//   for raw in split(text or ""):
//       name = raw.strip().lstrip("#").strip()[:128]
//       keep when non-empty and unseen (ordered dedup).
//
// Unicode notes: Python's \s matches the full Unicode whitespace set and
// strip() uses the same set; [:128] counts CHARACTERS (code points), not
// bytes. This file decodes UTF-8 code points to stay exact.
#include <pwb/ui_pages_data/tag_text.hpp>

#include <set>

namespace pwb::ui_pages_data {
namespace {

// Minimal UTF-8 decoder — malformed bytes pass through as single units.
struct Decoder {
    const std::string& s;
    std::size_t pos = 0;
    explicit Decoder(const std::string& src) : s(src) {}

    bool done() const { return pos >= s.size(); }

    // Next code point; `bytes` gets its encoding for passthrough.
    char32_t next(std::string& bytes) {
        const unsigned char c = static_cast<unsigned char>(s[pos]);
        int len = 1;
        char32_t cp = c;
        if (c >= 0xF0) { len = 4; cp = c & 0x07; }
        else if (c >= 0xE0) { len = 3; cp = c & 0x0F; }
        else if (c >= 0xC0) { len = 2; cp = c & 0x1F; }
        if (pos + len > s.size()) len = 1;  // truncated → passthrough byte
        for (int i = 1; i < len; ++i) {
            const unsigned char cc = static_cast<unsigned char>(s[pos + i]);
            if ((cc & 0xC0) != 0x80) { len = i; cp = c; break; }  // invalid
            cp = (cp << 6) | (cc & 0x3F);
        }
        bytes = s.substr(pos, len);
        pos += len;
        return cp;
    }
};

// Python str.isspace() set (what \s and strip() use).
bool is_py_space(char32_t cp) {
    switch (cp) {
        case 0x09: case 0x0A: case 0x0B: case 0x0C: case 0x0D:
        case 0x1C: case 0x1D: case 0x1E: case 0x1F:
        case 0x20: case 0x85: case 0xA0: case 0x1680:
        case 0x2000: case 0x2001: case 0x2002: case 0x2003: case 0x2004:
        case 0x2005: case 0x2006: case 0x2007: case 0x2008: case 0x2009:
        case 0x200A: case 0x2028: case 0x2029: case 0x202F: case 0x205F:
        case 0x3000:
            return true;
        default:
            return false;
    }
}

// Separator class: ASCII/full-width comma+semicolon and all whitespace.
bool is_separator(char32_t cp) {
    return cp == 0x2C /* , */ || cp == 0xFF0C /* ， */ ||
           cp == 0x3B /* ; */ || cp == 0xFF1B /* ； */ ||
           is_py_space(cp);
}

struct Token {
    std::string text;          // UTF-8 bytes (already trimmed)
    std::size_t chars = 0;     // code-point count
};

// str.strip(): remove leading/trailing whitespace (code-point aware).
Token trim(const std::vector<std::pair<char32_t, std::string>>& cps,
           std::size_t lo, std::size_t hi) {
    Token out;
    while (lo < hi && is_py_space(cps[lo].first)) ++lo;
    while (hi > lo && is_py_space(cps[hi - 1].first)) --hi;
    for (std::size_t i = lo; i < hi; ++i) {
        out.text += cps[i].second;
        ++out.chars;
    }
    return out;
}

// str.lstrip("#"): drop leading '#' characters only.
Token lstrip_hash(const std::vector<std::pair<char32_t, std::string>>& cps,
                  const Token& in) {
    // Re-scan: '#' is ASCII, one byte.
    std::size_t i = 0;
    while (i < in.text.size() && in.text[i] == '#') ++i;
    Token out{in.text.substr(i), in.chars - (i /* # is 1 cp each */)};
    return out;
}

Token truncate_chars(const Token& in, std::size_t max_chars) {
    if (in.chars <= max_chars) return in;
    Token out;
    Decoder dec(in.text);
    std::string bytes;
    while (!dec.done() && out.chars < max_chars) {
        dec.next(bytes);
        out.text += bytes;
        ++out.chars;
    }
    return out;
}

}  // namespace

std::vector<std::string> parse_multi_tag_input(const std::string& text) {
    // Decode once so token splits, trims and truncation count characters.
    std::vector<std::pair<char32_t, std::string>> cps;
    {
        Decoder dec(text);
        std::string bytes;
        while (!dec.done()) {
            cps.emplace_back(dec.next(bytes), bytes);
        }
    }

    std::vector<std::string> names;
    std::set<std::string> seen;
    std::size_t start = 0;
    const std::size_t n = cps.size();
    for (std::size_t i = 0; i <= n; ++i) {
        if (i < n && !is_separator(cps[i].first)) continue;
        // [start, i) is one raw token.
        Token tok = trim(cps, start, i);
        tok = lstrip_hash(cps, tok);
        // Second strip uses the same whitespace set on the lstrip result.
        {
            std::vector<std::pair<char32_t, std::string>> inner;
            Decoder dec(tok.text);
            std::string bytes;
            while (!dec.done()) inner.emplace_back(dec.next(bytes), bytes);
            tok = trim(inner, 0, inner.size());
        }
        tok = truncate_chars(tok, kMaxTagNameLength);
        if (!tok.text.empty() && seen.insert(tok.text).second) {
            names.push_back(std::move(tok.text));
        }
        start = i + 1;
    }
    return names;
}

}  // namespace pwb::ui_pages_data
