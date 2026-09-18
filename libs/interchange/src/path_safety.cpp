// Faithful port of paleo_workbench/interchange/path_safety.py (pure half).
// Check order inside safe_relative_path is load-bearing: it decides which
// Python message the caller sees, so do not reorder.

#include <pwb/interchange/path_safety.hpp>

#include <pwb/interchange/unicode.hpp>

#include <array>
#include <cstddef>
#include <stdexcept>
#include <vector>

namespace pwb::interchange {

namespace {

// Python str.strip()/isspace() whitespace (full Unicode set, incl. the
// C0 file/group/record/unit separators U+001C..001F).
bool is_python_whitespace(char32_t cp) {
    if (cp <= 0x20) {
        return cp == 0x09 || cp == 0x0A || cp == 0x0B || cp == 0x0C
            || cp == 0x0D || (cp >= 0x1C && cp <= 0x20);
    }
    return cp == 0x85 || cp == 0xA0 || cp == 0x1680
        || (cp >= 0x2000 && cp <= 0x200A) || cp == 0x2028 || cp == 0x2029
        || cp == 0x202F || cp == 0x205F || cp == 0x3000;
}

bool is_all_whitespace(std::string_view text) {
    for (const char32_t cp : utf8_to_codepoints(text)) {
        if (!is_python_whitespace(cp)) {
            return false;
        }
    }
    return true;
}

bool is_blank_component(std::string_view part) {
    return is_all_whitespace(part);
}

std::string_view rstrip_space_dot(std::string_view part) {
    while (!part.empty() && (part.back() == ' ' || part.back() == '.')) {
        part.remove_suffix(1);
    }
    return part;
}

bool is_windows_reserved_stem(std::string_view stem_upper) {
    static constexpr std::array<std::string_view, 22> kReserved = {
        "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5",
        "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4",
        "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    };
    for (const auto& name : kReserved) {
        if (stem_upper == name) {
            return true;
        }
    }
    return false;
}

char ascii_upper(char ch) {
    return (ch >= 'a' && ch <= 'z') ? static_cast<char>(ch - 'a' + 'A') : ch;
}

bool has_reserved_character(std::string_view part) {
    for (const unsigned char ch : part) {
        if (ch < 0x20 || ch == '<' || ch == '>' || ch == ':' || ch == '"'
            || ch == '|' || ch == '?' || ch == '*') {
            return true;
        }
    }
    return false;
}

bool starts_with_drive(std::string_view normalized) {
    if (normalized.size() < 2) {
        return false;
    }
    const auto first = static_cast<unsigned char>(normalized[0]);
    const bool alpha = (first >= 'A' && first <= 'Z')
        || (first >= 'a' && first <= 'z');
    return alpha && normalized[1] == ':';
}

std::vector<std::string_view> split_path_parts(std::string_view posix) {
    // PurePosixPath semantics: empty and "." segments dropped, duplicates
    // collapse; ".." survives for the traversal check.
    std::vector<std::string_view> parts;
    std::size_t start = 0;
    while (start <= posix.size()) {
        const std::size_t slash = posix.find('/', start);
        const auto segment = posix.substr(
            start, slash == std::string_view::npos ? posix.size() - start
                                                   : slash - start);
        if (!segment.empty() && segment != ".") {
            parts.push_back(segment);
        }
        if (slash == std::string_view::npos) {
            break;
        }
        start = slash + 1;
    }
    return parts;
}

std::string_view stem_of(std::string_view part) {
    const std::size_t dot = part.find('.');
    return dot == std::string_view::npos ? part : part.substr(0, dot);
}

}  // namespace

std::string python_repr(std::string_view text) {
    // Python picks double quotes only when the text holds ' but not ".
    const bool single_quote = text.find('\'') != std::string_view::npos
        && text.find('"') == std::string_view::npos;
    const char quote = single_quote ? '"' : '\'';
    // unicodedata.isprintable() escapes Cc (handled byte-wise below), the
    // C1 range 0x80..0xA0, and Zs/Zl/Zp separators; Cf/Co/Cn pass through
    // raw (documented bound; oracle pool contains none).
    const auto escaped_separator = [](char32_t cp) {
        return cp == 0xA0 || cp == 0x1680 || (cp >= 0x2000 && cp <= 0x200A)
            || cp == 0x2028 || cp == 0x2029 || cp == 0x202F || cp == 0x205F
            || cp == 0x3000;
    };
    static constexpr char kHex[] = "0123456789abcdef";
    std::string out;
    out.push_back(quote);
    for (const char32_t cp : utf8_to_codepoints(text)) {
        switch (cp) {
            case U'\n': out += "\\n"; break;
            case U'\r': out += "\\r"; break;
            case U'\t': out += "\\t"; break;
            case U'\\': out += "\\\\"; break;
            default:
                if (cp == static_cast<char32_t>(quote)) {
                    out.push_back('\\');
                    out.push_back(quote);
                } else if (cp < 0x20 || (cp >= 0x7F && cp <= 0xA0)) {
                    // Python uses \xNN below 0x100 (controls, DEL, C1, \xa0).
                    out += "\\x";
                    out.push_back(kHex[(cp >> 4) & 0xF]);
                    out.push_back(kHex[cp & 0xF]);
                } else if (escaped_separator(cp)) {
                    if (cp <= 0xFFFF) {
                        out += "\\u";
                        for (int shift = 12; shift >= 0; shift -= 4) {
                            out.push_back(kHex[(cp >> shift) & 0xF]);
                        }
                    } else {
                        out += "\\U";
                        for (int shift = 28; shift >= 0; shift -= 4) {
                            out.push_back(kHex[(cp >> shift) & 0xF]);
                        }
                    }
                } else {
                    out.append(codepoints_to_utf8(std::u32string(1, cp)));
                }
        }
    }
    out.push_back(quote);
    return out;
}

std::string safe_relative_path(const std::string& name, const std::string& what) {
    if (name.empty() || is_all_whitespace(name)) {
        throw UnsafePathError(what + ": empty path");
    }
    if (name.find('\x00') != std::string::npos) {
        throw UnsafePathError(what + ": NUL byte in " + python_repr(name));
    }

    const std::string normalized = nfc_normalize_utf8(name);
    if (normalized != name) {
        // Reject rather than rewrite: two manifest entries must never differ
        // only by Unicode normalization form (silent duplicate names).
        throw UnsafePathError(what + ": non-NFC path " + python_repr(name));
    }

    const std::string posix = [&] {
        std::string replaced = normalized;
        for (char& ch : replaced) {
            if (ch == '\\') {
                ch = '/';
            }
        }
        return replaced;
    }();
    if ((!posix.empty() && posix.front() == '/') || starts_with_drive(normalized)) {
        throw UnsafePathError(what + ": absolute path not allowed: "
                              + python_repr(name));
    }

    const std::vector<std::string_view> parts = split_path_parts(posix);
    if (parts.empty()) {
        throw UnsafePathError(what + ": no components in " + python_repr(name));
    }
    for (const std::string_view part : parts) {
        if (part == "." || part == "..") {
            throw UnsafePathError(what + ": traversal component in "
                                  + python_repr(name));
        }
        if (is_blank_component(part)) {
            throw UnsafePathError(what + ": blank path component in "
                                  + python_repr(name));
        }
        if (part != rstrip_space_dot(part)) {
            // NTFS/FAT strip trailing dots/spaces: "file.txt." would silently
            // overwrite "file.txt" and "com1 " would target the COM1 device.
            throw UnsafePathError(what + ": trailing dot/space in "
                                  + python_repr(part));
        }
        if (codepoint_length(part) > kMaxComponentLen) {
            throw UnsafePathError(what + ": path component too long in "
                                  + python_repr(name));
        }
        std::string stem_upper;
        for (const char ch : stem_of(part)) {
            stem_upper.push_back(ascii_upper(ch));
        }
        if (is_windows_reserved_stem(stem_upper)) {
            throw UnsafePathError(what + ": Windows reserved name "
                                  + python_repr(part));
        }
        if (has_reserved_character(part)) {
            throw UnsafePathError(what + ": reserved character in "
                                  + python_repr(part));
        }
    }

    std::string rel;
    for (const std::string_view part : parts) {
        if (!rel.empty()) {
            rel.push_back('/');
        }
        rel.append(part);
    }
    if (codepoint_length(rel) > kMaxRelativeLen) {
        throw UnsafePathError(what + ": path too long: " + python_repr(name));
    }
    return rel;
}

void check_collision(const std::string& name,
                     std::set<std::string>& seen_casefold,
                     std::set<std::string>& seen_nfc) {
    if (seen_nfc.count(name) != 0) {
        throw UnsafePathError("duplicate entry after normalization: "
                              + python_repr(name));
    }
    const std::string folded = casefold_utf8(name);
    if (seen_casefold.count(folded) != 0) {
        throw UnsafePathError("case-insensitive collision: " + python_repr(name));
    }
    seen_nfc.insert(name);
    seen_casefold.insert(folded);
}

std::filesystem::path ensure_within_root(const std::filesystem::path& root,
                                         const std::filesystem::path& candidate) {
    std::error_code ec;
    const std::filesystem::path resolved_root =
        std::filesystem::weakly_canonical(root, ec);
    if (std::filesystem::is_symlink(candidate)) {
        throw UnsafePathError("symlink rejected: " + candidate.string());
    }
    const std::filesystem::path resolved =
        std::filesystem::weakly_canonical(candidate, ec);
    if (resolved != resolved_root) {
        // "root in resolved.parents": the resolved path must be strictly
        // inside the root (covers ".." survivors and symlinked dirs alike).
        // lexically_relative is component-based, so it is separator- and
        // platform-correct (the previous text-prefix check only recognized
        // '/' and rejected every nested path on Windows).
        const std::filesystem::path relative =
            resolved.lexically_relative(resolved_root);
        const std::string relative_text = relative.generic_string();
        const bool inside = !relative_text.empty()
            && relative_text != "."
            && relative_text.rfind("../", 0) != 0
            && relative_text != "..";
        if (!inside) {
            throw UnsafePathError("path escapes package root: "
                                  + candidate.string());
        }
    }
    return resolved;
}

std::string sanitize_filename(const std::string& stem, const std::string& fallback) {
    std::string cleaned = nfc_normalize_utf8(stem);
    std::string replaced;
    replaced.reserve(cleaned.size());
    for (const unsigned char ch : cleaned) {
        if (ch < 0x20 || ch == '<' || ch == '>' || ch == ':' || ch == '"'
            || ch == '|' || ch == '?' || ch == '*' || ch == '/' || ch == '\\') {
            replaced.push_back('_');
        } else {
            replaced.push_back(static_cast<char>(ch));
        }
    }
    cleaned = replaced;
    // strip(" .") — code-point level, but ' ' and '.' are single bytes.
    std::size_t begin = 0;
    std::size_t end = cleaned.size();
    while (begin < end && (cleaned[begin] == ' ' || cleaned[begin] == '.')) {
        ++begin;
    }
    while (end > begin && (cleaned[end - 1] == ' ' || cleaned[end - 1] == '.')) {
        --end;
    }
    cleaned = cleaned.substr(begin, end - begin);
    if (cleaned.empty()) {
        cleaned = fallback;
    }
    std::string stem_upper;
    for (const char ch : stem_of(cleaned)) {
        stem_upper.push_back(ascii_upper(ch));
    }
    if (is_windows_reserved_stem(stem_upper)) {
        cleaned = "_" + cleaned;
    }
    const std::u32string cps = utf8_to_codepoints(cleaned);
    if (cps.size() > kMaxComponentLen) {
        return codepoints_to_utf8(cps.substr(0, kMaxComponentLen));
    }
    return cleaned;
}

bool is_reserved_or_unsafe(const std::string& name) {
    try {
        safe_relative_path(name);
        return false;
    } catch (const UnsafePathError&) {
        return true;
    }
}

}  // namespace pwb::interchange
