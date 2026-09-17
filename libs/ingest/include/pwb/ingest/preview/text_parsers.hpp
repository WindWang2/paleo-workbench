// Text/table preview cores — port of resources/preview_parsers/table_parsers
// (text/dat/csv previews with the shlex POSIX tokenizer and the CPython csv
// state machine) plus the decode-with-fallback helper.
#pragma once

#include <optional>
#include <string>
#include <vector>

#include "pwb/ingest/preview/models.hpp"

namespace pwb::ingest::preview {

// decode_text_with_fallback: utf-8-sig strict, then replacement decode.
// (The Python GB18030 middle tier needs an ICU-class table; see D6.)
std::string decode_text_with_fallback(std::string_view bytes);

// shlex.split(s) POSIX semantics; nullopt on ValueError
// ("No closing quotation" / "No escaped character").
std::optional<std::vector<std::string>> shlex_split(std::string_view text);

// csv.reader row iteration (excel dialect: ',' delimiter, '"' quote,
// QUOTE_MINIMAL). Returns all rows; a trailing incomplete quoted field is
// still returned, matching the CPython reader at EOF.
std::vector<std::vector<std::string>> csv_reader(std::string_view text, char delimiter);

// text_preview core: bytes -> bounded chunk -> decoded text result fields.
PreviewResult text_preview(const ResourceRef& resource, std::string_view bytes,
                           const PreviewSettings& settings);

// dat_preview core (bounded whitespace-delimited list; falls back to text).
PreviewResult dat_preview(const ResourceRef& resource, std::string_view bytes,
                          const PreviewSettings& settings);

// table_preview core (csv/tsv).
PreviewResult table_preview(const ResourceRef& resource, std::string_view bytes,
                            char delimiter, const PreviewSettings& settings);

}  // namespace pwb::ingest::preview
