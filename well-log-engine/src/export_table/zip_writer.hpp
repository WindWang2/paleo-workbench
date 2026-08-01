#pragma once

// Minimal in-memory ZIP writer for self-contained OOXML (.xlsx) output (#155
// XLSX backend). Produces a valid ZIP archive: per-entry local file header +
// deflated (or stored) data, then a central directory and end-of-central-
// directory record. Uses ZLIB for deflate compression and CRC-32. Only the
// subset OOXML readers (Excel/LibreOffice/the test's inflate readback) need.
//
// Entries are buffered in memory (an XLSX workbook is small relative to the
// row data, which is emitted compressed; for very large workbooks a streaming
// zip-to-file would be a follow-up). The row streams themselves are written
// per-entry, so the uncompressed worksheet text is never all held at once —
// each entry's producer streams into a deflate buffer.

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

#include <zlib.h>

namespace welllog {
namespace export_table {

struct ZipEntry {
  std::string name;          // e.g. "xl/worksheets/sheet1.xml"
  std::vector<unsigned char> data; // compressed (deflated) bytes
  std::uint32_t crc32{0};
  std::uint64_t uncompressed_size{0};
  std::uint16_t method{8}; // 8 = deflate, 0 = store
};

class ZipWriter {
public:
  ZipWriter() = default;

  // Adds an entry whose content is the raw bytes; compresses with deflate
  // (method 8) unless `store` is true (method 0). Returns false on a zlib
  // error.
  bool add_entry(const std::string &name, const std::string &content,
                 bool store = false);

  // Adds an entry from a producer that streams into an accumulating string
  // (used so a large worksheet can be built incrementally without holding the
  // whole workbook in one buffer before compression).
  bool add_entry_streamed(const std::string &name,
                          const std::function<bool(std::string &)> &producer);

  // Serializes the archive (local headers + data + central directory + EOCD)
  // into `out`.
  void serialize(std::string &out) const;

  [[nodiscard]] std::size_t size() const noexcept { return entries_.size(); }
  [[nodiscard]] const std::vector<ZipEntry> &entries() const noexcept {
    return entries_;
  }

private:
  std::vector<ZipEntry> entries_;
};

} // namespace export_table
} // namespace welllog
