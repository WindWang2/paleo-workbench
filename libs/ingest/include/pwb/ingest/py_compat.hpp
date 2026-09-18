// Python-compatibility primitives shared by the ingest parse cores.
// Each helper replicates one CPython behavior the frozen oracle depends on.
#pragma once

#include <optional>
#include <string>
#include <string_view>

namespace pwb::ingest::detail {

struct CodePoint {
    char32_t cp;
    size_t size;
};

// Decode one UTF-8 code point at s[i]; nullopt on ill-formed input.
std::optional<CodePoint> utf8_code_point(std::string_view s, size_t i);

}  // namespace pwb::ingest::detail

namespace pwb::ingest {

// Python float(): leading/trailing whitespace, optional sign, decimal or
// exponent mantissa, "inf"/"infinity"/"nan" (any case), PEP 515 underscores.
// Rejects hex, commas, empty. NaN/Infinity are VALID results (D14).
std::optional<double> py_parse_float(std::string_view text);

// Python str.strip() over the full Unicode whitespace set CPython uses
// (ASCII space/tab/newline/CR/FF/VT plus the common Unicode spaces).
std::string py_strip(std::string_view text);

// well_location_xml._key: strip namespace/ prefix, keep [0-9A-Za-z] and
// U+4E00..U+9FFF, drop everything else, ASCII-casefold the remainder.
std::string location_key_normalize(std::string_view tag);

// well_log_xml._local_name: strip namespace/ prefix, then strip() + ASCII
// casefold (CJK passes through unchanged).
std::string log_local_name(std::string_view tag);

// html.escape(line) with quote=True: & < > " ' -> &amp; &lt; &gt; &quot; &#x27;
std::string html_escape(std::string_view text);

// paleo_workbench.tokens.format_size (dfb/zip summary rows).
std::string format_size(long long size_bytes);

// Split a path into (parent_path, stem, suffix-lower) mirroring the pathlib
// surface classifier.py uses: suffix = last dot of the final component
// (leading dot files have no suffix); stem = component without suffix.
struct PathParts {
    std::string name;    // final component
    std::string stem;    // name minus suffix
    std::string suffix;  // ".ext" (raw case, as written)
};
PathParts split_path_parts(std::string_view path);

// Decode raw bytes as UTF-8 (optionally consuming a leading BOM).
// strict=true -> nullopt on any ill-formed sequence (Python
// "utf-8-sig" strict); strict=false -> U+FFFD replacement per maximal
// subpart (Python errors="replace"; see decision D6 for the GB18030 tier).
std::optional<std::string> decode_utf8_sig(std::string_view bytes, bool strict);

// Same decode without BOM stripping (plain Python "utf-8").
std::optional<std::string> decode_utf8(std::string_view bytes, bool strict);

}  // namespace pwb::ingest
