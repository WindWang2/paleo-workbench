// Markdown rendering and JSON bounded preview — ports of
// document_parsers.markdown_to_html / markdown_rich_preview / json_preview.
#pragma once

#include <optional>
#include <string>
#include <string_view>

#include "pwb/ingest/preview/models.hpp"

namespace pwb::ingest::preview {

std::string markdown_to_html(std::string_view markdown);

// Python json.loads validity (NaN/Infinity accepted, strict strings);
// nullopt on any decode error (JSONDecodeError).
std::optional<std::string> json_validate(std::string_view text);

PreviewResult json_preview(const ResourceRef& resource, std::string_view bytes,
                           const PreviewSettings& settings);

PreviewResult markdown_rich_preview(const ResourceRef& resource,
                                    std::string_view bytes,
                                    const PreviewSettings& settings);

}  // namespace pwb::ingest::preview
