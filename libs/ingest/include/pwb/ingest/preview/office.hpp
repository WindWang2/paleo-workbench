// Office/archive preview — port of resources/preview_parsers/office_parsers:
// bounded central-directory validation, zip/pptx/dfb previews, and the
// structure-validating PNG/JPEG range finders (with a self-contained
// raw-deflate decoder and CRC-32).
#pragma once

#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "pwb/ingest/preview/models.hpp"

namespace pwb::ingest::preview {

struct ArchiveSafetyError : std::runtime_error {
    explicit ArchiveSafetyError(const std::string& message)
        : std::runtime_error(message) {}
};
struct BadZipError : std::runtime_error {  // zipfile.BadZipFile analog
    explicit BadZipError(const std::string& message)
        : std::runtime_error(message) {}
};

// Central-directory entries (after validation).
struct ZipEntry {
    std::string name;  // decoded (utf-8 when flag 0x800, else cp437)
    unsigned long local_offset = 0;
    unsigned long compressed_size = 0;
    unsigned long uncompressed_size = 0;
    unsigned short method = 0;
};

// Reads + validates a single-disk non-ZIP64 central directory (raises
// ArchiveSafetyError with the exact Python message strings).
std::vector<ZipEntry> read_central_directory(std::string_view bytes);

// Decompressed member content (stored or deflate). Raises BadZipError on
// local-header problems, inflate failure, or CRC mismatch.
std::string zip_read_member(std::string_view bytes, const ZipEntry& entry);

PreviewResult zip_preview(const ResourceRef& resource, std::string_view bytes,
                          int max_rows);
PreviewResult wlp_preview(const ResourceRef& resource);
PreviewResult pptx_preview(const ResourceRef& resource, std::string_view bytes);
PreviewResult dfb_preview(const ResourceRef& resource, std::string_view bytes,
                          const std::vector<std::pair<std::string, std::string>>&
                              sibling_dir_entries = {});

// _validated_png_range / _validated_jpeg_range over a raw buffer; return the
// end offset of the validated image starting at `start` (nullopt = reject).
std::optional<size_t> validated_png_range(std::string_view mapped, size_t start);
std::optional<size_t> validated_jpeg_range(std::string_view mapped, size_t start);

}  // namespace pwb::ingest::preview
