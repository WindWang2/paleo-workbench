#pragma once

// pwb::interchange — native ZIP container (conv-14b): the zip half of
// paleo_workbench/interchange/path_safety.py (safe_members / extract_archive)
// plus the read/write surface the package runtime needs (verify_zip_container,
// zip_package_dir). No Python, no subprocess: the container format
// (EOCD / central directory / local headers / raw-deflate via system zlib)
// is implemented here with CPython-zipfile-compatible name decoding
// (UTF-8 flag 0x800, else CP437) and CRC-32 validation on read.
//
// Write limits (documented medium-scale policy, ledgers/14b-decisions.md
// D14b-1): at most 65535 entries, entries and container below 4 GiB (no
// ZIP64 emit); the reader DOES understand ZIP64 records for compatibility.
// One ZipReader per thread: read_entry seeks a shared stream (Python's
// ZipFile has the same contract).

#include <pwb/interchange/contracts.hpp>
#include <pwb/interchange/path_safety.hpp>

#include <cstdint>
#include <filesystem>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace pwb::interchange {

// Container-level failures (bad zip, unsupported record, CRC mismatch).
struct ZipError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

struct ZipEntryInfo {
    std::string name;  // decoded per CPython zipfile rules
    unsigned long long compressed_size = 0;
    unsigned long long size = 0;  // uncompressed
    unsigned long crc32 = 0;      // central-directory CRC
    unsigned short method = 0;    // 0 stored, 8 deflate
    unsigned short flags = 0;     // general purpose bit flag (0x800 = UTF-8 name)
    unsigned short dos_time = 0;  // packed DOS time (writer: fixed 00:00:00)
    unsigned short dos_date = 0;  // packed DOS date (writer: fixed 1980-01-01)
    unsigned long external_attr = 0;
    unsigned long long local_header_offset = 0;

    bool is_dir() const;            // filename ends with '/' (ZipInfo.is_dir)
    bool is_symlink_entry() const;  // (external_attr >> 16) & 0o170000 == 0o120000
};

class ZipReader {
public:
    // Throws ZipError("File is not a zip file") when no valid EOCD exists
    // (same message as Python zipfile.BadZipFile for this case).
    explicit ZipReader(const std::filesystem::path& path);
    ~ZipReader();
    ZipReader(ZipReader&&) noexcept;
    ZipReader& operator=(ZipReader&&) noexcept;

    const std::vector<ZipEntryInfo>& infolist() const { return entries_; }
    const ZipEntryInfo* find(std::string_view name) const;

    // Stream entry payload to sink in bounded chunks (CRC-validated against
    // the central directory). Throws ZipError on any container damage.
    void read_entry(const ZipEntryInfo& entry,
                    const std::function<void(std::string_view)>& sink) const;
    std::string read_entry_bytes(const ZipEntryInfo& entry) const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    std::vector<ZipEntryInfo> entries_;
};

// zipfile.is_zipfile: EOCD scan with comment-length validation, no parsing.
bool zip_is_zipfile(const std::filesystem::path& path);

class ZipWriter {
public:
    explicit ZipWriter(const std::filesystem::path& path);
    ~ZipWriter();
    ZipWriter(const ZipWriter&) = delete;
    ZipWriter& operator=(const ZipWriter&) = delete;

    // Fixed timestamp (1980-01-01 00:00) so outputs are reproducible;
    // UTF-8 flag set for non-ASCII arcnames (CPython rule).
    void add_bytes(const std::string& arcname, std::string_view bytes);
    void add_file(const std::filesystem::path& file, const std::string& arcname);
    void finish();  // writes the central directory; required before close

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

// path_safety.safe_members: validate every member (symlink reject +
// safe_relative_path + casefold/NFC collision), return canonical names in
// infolist order. Any failure raises UnsafePathError — callers must abort
// the whole extraction, never skip an entry.
std::vector<std::string> safe_members(const ZipReader& archive,
                                      const std::string& what = "archive");

// path_safety.extract_archive: validation first (safe_members), writes
// second — a malicious archive never leaves a single byte on failure.
// Streams file payloads in 1 MiB chunks; cancel is checked per entry.
std::vector<std::filesystem::path> extract_archive(
    const ZipReader& archive, const std::filesystem::path& dest_root,
    const std::string& what = "package", const CancelToken& cancel = null_cancel());

}  // namespace pwb::interchange
