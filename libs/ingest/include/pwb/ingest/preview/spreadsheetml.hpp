// Bounded SpreadsheetML table preview — port of office_parsers.spreadsheetml
// _preview over the streaming XML scanner (iterparse + bounded-reader
// semantics, including partial-row survival on boundary truncation).
#pragma once

#include <optional>
#include <string>
#include <string_view>

#include "pwb/ingest/preview/models.hpp"

namespace pwb::ingest::preview {

// Returns nullopt when the document is not a SpreadsheetML Workbook (the
// caller falls through to other preview routes).
std::optional<PreviewResult> spreadsheetml_preview(const ResourceRef& resource,
                                                   std::string_view bytes,
                                                   long long max_text_bytes,
                                                   int max_rows, int max_columns);

}  // namespace pwb::ingest::preview
