#include "pwb/interchange/zip_archive.hpp"

#include <pwb/interchange/unicode.hpp>

#include <zlib.h>

#include <cstring>
#include <fstream>
#include <set>
#include <string>
#include <vector>

namespace pwb::interchange {
namespace {

constexpr unsigned long kFileSignature = 0x04034b50;     // PK\x03\x04
constexpr unsigned long kCentralSignature = 0x02014b50;  // PK\x01\x02
constexpr unsigned long kEndSignature = 0x06054b50;      // PK\x05\x06
constexpr unsigned long kZip64EndSignature = 0x06064b50; // PK\x06\x06
constexpr unsigned long kZip64LocatorSignature = 0x07064b50;

constexpr std::size_t kChunkSize = 1024 * 1024;  // 1 MiB, mirrors Python

unsigned short read_u16(const unsigned char* p) {
    return static_cast<unsigned short>(p[0] | (p[1] << 8));
}

unsigned int read_u32(const unsigned char* p) {
    return static_cast<unsigned long>(p[0]) | (static_cast<unsigned long>(p[1]) << 8) |
           (static_cast<unsigned long>(p[2]) << 16) | (static_cast<unsigned long>(p[3]) << 24);
}

unsigned long long read_u64(const unsigned char* p) {
    return static_cast<unsigned long long>(read_u32(p)) |
           (static_cast<unsigned long long>(read_u32(p + 4)) << 32);
}

void put_u16(std::string& out, unsigned short v) {
    out.push_back(static_cast<char>(v & 0xFF));
    out.push_back(static_cast<char>((v >> 8) & 0xFF));
}

void put_u32(std::string& out, unsigned long v) {
    out.push_back(static_cast<char>(v & 0xFF));
    out.push_back(static_cast<char>((v >> 8) & 0xFF));
    out.push_back(static_cast<char>((v >> 16) & 0xFF));
    out.push_back(static_cast<char>((v >> 24) & 0xFF));
}

void put_u64(std::string& out, unsigned long long v) {
    for (int i = 0; i < 8; ++i) out.push_back(static_cast<char>((v >> (8 * i)) & 0xFF));
}

// CPython zipfile decodes entry names as UTF-8 when flag bit 0x800 is set,
// otherwise as CP437. Table for the high half of CP437 (bytes 0x80..0xFF).
const char* const kCp437High[128] = {
    "\xC3\x87", "\xC3\xBC", "\xC3\xA9", "\xC3\xA2", "\xC3\xA4", "\xC3\xA0",
    "\xC3\xA5", "\xC3\xA7", "\xC3\xAA", "\xC3\xAB", "\xC3\xA8", "\xC3\xAF",
    "\xC3\xAE", "\xC3\xAC", "\xC3\x84", "\xC3\x85",
    "\xC3\x89", "\xC3\xA6", "\xC3\x86", "\xC3\xB4", "\xC3\xB6", "\xC3\xB2",
    "\xC3\xBB", "\xC3\xB9", "\xC3\xBF", "\xC3\x96", "\xC3\x9C", "\xC2\xA2",
    "\xC2\xA3", "\xC2\xA5", "\xE2\x82\xA7", "\xC6\x92",
    "\xC3\xA1", "\xC3\xAD", "\xC3\xB3", "\xC3\xBA", "\xC3\xB1", "\xC3\x91",
    "\xC2\xAA", "\xC2\xBA", "\xC2\xBF", "\xE2\x8C\x90", "\xC2\xAC", "\xC2\xBD",
    "\xC2\xBC", "\xC2\xA1", "\xC2\xAB", "\xC2\xBB",
    "\xE2\x96\x91", "\xE2\x96\x92", "\xE2\x96\x93", "\xE2\x94\x82",
    "\xE2\x94\xA4", "\xE2\x94\xA1", "\xE2\x94\xA2", "\xE2\x95\x96",
    "\xE2\x95\x95", "\xE2\x95\xA3", "\xE2\x95\x91", "\xE2\x95\x97",
    "\xE2\x95\x9D", "\xE2\x95\x9C", "\xE2\x95\x9B", "\xE2\x94\x90",
    "\xE2\x94\x94", "\xE2\x94\xB4", "\xE2\x94\xAC", "\xE2\x94\x9C",
    "\xE2\x94\x80", "\xE2\x94\xBC", "\xE2\x95\x9E", "\xE2\x95\x9F",
    "\xE2\x95\x9A", "\xE2\x95\x97", "\xE2\x95\xA0", "\xE2\x95\xA1",
    "\xE2\x95\xAC", "\xE2\x95\xA7", "\xE2\x95\xA8", "\xE2\x95\xA4",
    "\xE2\x95\xA5", "\xE2\x95\x99", "\xE2\x95\x98", "\xE2\x95\x92",
    "\xE2\x95\x93", "\xE2\x95\xAB", "\xE2\x95\xAA", "\xE2\x94\x98",
    "\xE2\x94\x8C", "\xE2\x96\x88", "\xE2\x96\x84", "\xE2\x96\x8C",
    "\xE2\x96\x90", "\xE2\x96\x80", "\xCE\xB1", "\xC3\x9F",
    "\xCE\x93", "\xCF\x80", "\xCE\xA3", "\xCF\x83", "\xC2\xB5", "\xCF\x84",
    "\xCE\xA6", "\xCE\x98", "\xCE\xA9", "\xCE\xB4", "\xE2\x88\x9E",
    "\xCF\x86", "\xCE\xB5", "\xE2\x88\xA9",
    "\xE2\x89\xA1", "\xC2\xB1", "\xE2\x89\xA5", "\xE2\x89\xA4",
    "\xE2\x8C\xA0", "\xE2\x8C\xA1", "\xC3\xB7", "\xE2\x89\x88",
    "\xC2\xB0", "\xE2\x88\x99", "\xC2\xB7", "\xE2\x88\x9A", "\xE2\x81\xBF",
    "\xC2\xB2", "\xE2\x96\xA0", "\xC2\xA0",
};

// CPython decodes flag-0x800 names with strict UTF-8: overlong forms,
// surrogates and code points above U+10FFFF raise UnicodeDecodeError (loud
// rejection). Mirror that here instead of accepting structurally-valid
// byte soup.
bool is_valid_utf8(std::string_view text) {
    std::size_t i = 0;
    while (i < text.size()) {
        const unsigned char b = static_cast<unsigned char>(text[i]);
        unsigned int cp = 0;
        std::size_t continuation = 0;
        if (b < 0x80) {
            i += 1;
            continue;
        } else if (b >= 0xC2 && b <= 0xDF) {
            continuation = 1;
            cp = b & 0x1F;
        } else if (b >= 0xE0 && b <= 0xEF) {
            continuation = 2;
            cp = b & 0x0F;
        } else if (b >= 0xF0 && b <= 0xF4) {
            continuation = 3;
            cp = b & 0x07;
        } else {
            return false;
        }
        if (i + continuation >= text.size()) return false;
        for (std::size_t k = 1; k <= continuation; ++k) {
            const unsigned char cb = static_cast<unsigned char>(text[i + k]);
            if ((cb & 0xC0) != 0x80) return false;
            cp = (cp << 6) | (cb & 0x3F);
        }
        // reject overlong encodings, surrogates and out-of-range code points
        if (continuation == 1 && cp < 0x80) return false;
        if (continuation == 2 && cp < 0x800) return false;
        if (cp >= 0xD800 && cp <= 0xDFFF) return false;
        if (cp > 0x10FFFF) return false;
        i += continuation + 1;
    }
    return true;
}

std::string decode_entry_name(const std::string& raw, unsigned short flags) {
    if (flags & 0x0800) {
        // Strict UTF-8 (CPython raises UnicodeDecodeError on invalid bytes —
        // a loud failure either way).
        if (!is_valid_utf8(raw)) throw ZipError("invalid utf-8 in zip entry name");
        return raw;
    }
    std::string out;
    out.reserve(raw.size());
    for (unsigned char byte : raw) {
        if (byte < 0x80) out.push_back(static_cast<char>(byte));
        else out += kCp437High[byte - 0x80];
    }
    return out;
}

// CPython _EndRecData semantics: rfind the EOCD signature once (the LAST
// occurrence in the tail window) and validate its comment length; any
// mismatch means "not a zip" — no fallback to earlier candidates.
std::size_t find_eocd(const std::string& tail, std::size_t tail_start,
                      unsigned long long file_size) {
    if (tail.size() < 22) return std::string::npos;
    for (std::size_t i = tail.size() - 22 + 1; i-- > 0;) {
        if (static_cast<unsigned char>(tail[i]) != 0x50 ||
            read_u32(reinterpret_cast<const unsigned char*>(&tail[i])) != kEndSignature) {
            continue;
        }
        const unsigned short comment_len = read_u16(
            reinterpret_cast<const unsigned char*>(&tail[i]) + 20);
        return tail_start + i + 22 + comment_len == file_size ? i : std::string::npos;
    }
    return std::string::npos;
}

}  // namespace

bool ZipEntryInfo::is_dir() const {
    return !name.empty() && name.back() == '/';
}

bool ZipEntryInfo::is_symlink_entry() const {
    return ((external_attr >> 16) & 0170000) == 0120000;  // S_IFMT / S_IFLNK
}

struct ZipReader::Impl {
    // One ZipReader per thread: read_entry seeks this shared stream, so
    // concurrent reads on one instance race by design (same as Python's
    // non-thread-safe ZipFile).
    std::ifstream file;
    // Captured at open so read_entry can reject offsets that point past
    // the file BEFORE any u64 offset arithmetic on them (a ZIP64 extra
    // field can carry offsets up to 2^64-1; adding 30 + name + extra to
    // such a value would wrap).
    unsigned long long file_size = 0;
    explicit Impl(const std::filesystem::path& path) : file(path, std::ios::binary) {}
};

ZipReader::ZipReader(const std::filesystem::path& path) : impl_(std::make_unique<Impl>(path)) {
    if (!impl_->file) throw ZipError("File is not a zip file");
    impl_->file.seekg(0, std::ios::end);
    const auto end_pos = impl_->file.tellg();
    if (end_pos < 0) throw ZipError("File is not a zip file");
    const unsigned long long file_size = static_cast<unsigned long long>(end_pos);
    impl_->file_size = file_size;

    const std::size_t window = static_cast<std::size_t>(
        file_size < 65557 ? file_size : 65557);
    std::string tail(window, '\0');
    impl_->file.seekg(static_cast<std::streamoff>(file_size - window));
    impl_->file.read(tail.data(), static_cast<std::streamsize>(window));
    if (static_cast<std::size_t>(impl_->file.gcount()) != window) {
        throw ZipError("File is not a zip file");
    }
    const std::size_t eocd_pos = find_eocd(tail, file_size - window, file_size);
    if (eocd_pos == std::string::npos) throw ZipError("File is not a zip file");
    const unsigned char* eocd = reinterpret_cast<const unsigned char*>(&tail[eocd_pos]);

    unsigned long long cd_offset = read_u32(eocd + 16);
    unsigned long long cd_size = read_u32(eocd + 12);
    unsigned long long entry_count = read_u16(eocd + 10);
    const unsigned long long eocd_offset = file_size - window + eocd_pos;

    if ((cd_offset == 0xFFFFFFFFULL || cd_size == 0xFFFFFFFFULL || entry_count == 0xFFFFULL) &&
        eocd_offset >= 20) {
        // ZIP64: locator sits directly before the EOCD.
        std::string locator(20, '\0');
        impl_->file.seekg(static_cast<std::streamoff>(eocd_offset - 20));
        impl_->file.read(locator.data(), 20);
        if (impl_->file.gcount() == 20 &&
            read_u32(reinterpret_cast<const unsigned char*>(locator.data())) ==
                kZip64LocatorSignature) {
            const unsigned long long zip64_eocd_offset =
                read_u64(reinterpret_cast<const unsigned char*>(locator.data()) + 8);
            std::string zip64_eocd(56, '\0');
            impl_->file.seekg(static_cast<std::streamoff>(zip64_eocd_offset));
            impl_->file.read(zip64_eocd.data(), static_cast<std::streamsize>(zip64_eocd.size()));
            if (impl_->file.gcount() == 56 &&
                read_u32(reinterpret_cast<const unsigned char*>(zip64_eocd.data())) ==
                    kZip64EndSignature) {
                const unsigned char* z64 =
                    reinterpret_cast<const unsigned char*>(zip64_eocd.data());
                entry_count = read_u64(z64 + 32);
                cd_size = read_u64(z64 + 40);
                cd_offset = read_u64(z64 + 48);
            }
        }
    }

    // Hostile containers must not force huge allocations: the central
    // directory has to fit inside the actual file.
    if (cd_offset > file_size || cd_size > file_size - cd_offset) {
        throw ZipError("Bad file (central directory out of bounds)");
    }
    if (entry_count > cd_size / 46) {
        throw ZipError("Bad file (entry count exceeds central directory)");
    }
    std::string cd(static_cast<std::size_t>(cd_size), '\0');
    if (cd_size > 0) {
        impl_->file.seekg(static_cast<std::streamoff>(cd_offset));
        impl_->file.read(cd.data(), static_cast<std::streamsize>(cd.size()));
        if (static_cast<std::size_t>(impl_->file.gcount()) != cd.size()) {
            throw ZipError("Bad file (truncated central directory)");
        }
    }

    std::size_t pos = 0;
    for (unsigned long long i = 0; i < entry_count; ++i) {
        if (pos + 46 > cd.size() ||
            read_u32(reinterpret_cast<const unsigned char*>(&cd[pos])) != kCentralSignature) {
            throw ZipError("Bad file (corrupt central directory)");
        }
        const unsigned char* rec = reinterpret_cast<const unsigned char*>(&cd[pos]);
        const unsigned short flags = read_u16(rec + 8);
        ZipEntryInfo info;
        info.method = read_u16(rec + 10);
        info.flags = flags;
        info.dos_time = read_u16(rec + 12);
        info.dos_date = read_u16(rec + 14);
        info.crc32 = read_u32(rec + 16);
        info.compressed_size = read_u32(rec + 20);
        info.size = read_u32(rec + 24);
        const unsigned short name_len = read_u16(rec + 28);
        const unsigned short extra_len = read_u16(rec + 30);
        const unsigned short comment_len = read_u16(rec + 32);
        info.external_attr = read_u32(rec + 38);
        info.local_header_offset = read_u32(rec + 42);
        // Checked bounds BEFORE any slice: the variable-length tail
        // (name + extra + comment) must fit inside the directory buffer
        // the fixed 46-byte header already proved valid. `cd.size() - pos`
        // cannot underflow (pos + 46 <= cd.size() above) and the left side
        // cannot overflow (three u16 fields), so this single comparison
        // replaces both substr calls' implicit truncation/throw behavior —
        // a truncated or hostile directory is a ZipError, never a
        // std::out_of_range escaping the package verification (#1469).
        if (static_cast<std::size_t>(46) + name_len + extra_len + comment_len >
            cd.size() - pos) {
            throw ZipError("Bad file (truncated central directory)");
        }
        std::string raw_name = cd.substr(pos + 46, name_len);
        // ZIP64 extra field 0x0001 carries the fields whose fixed slot is
        // 0xFFFFFFFF, in fixed order: size, compressed_size, offset.
        std::string extra = cd.substr(pos + 46 + name_len, extra_len);
        {
            std::size_t epos = 0;
            while (epos + 4 <= extra.size()) {
                const unsigned short field_id = read_u16(
                    reinterpret_cast<const unsigned char*>(&extra[epos]));
                const unsigned short field_len = read_u16(
                    reinterpret_cast<const unsigned char*>(&extra[epos + 2]));
                if (epos + 4 + field_len > extra.size()) break;
                if (field_id == 0x0001) {
                    const unsigned char* body =
                        reinterpret_cast<const unsigned char*>(&extra[epos + 4]);
                    std::size_t bpos = 0;
                    auto take64 = [&]() -> unsigned long long {
                        if (bpos + 8 > field_len) return 0;
                        const unsigned long long v = read_u64(body + bpos);
                        bpos += 8;
                        return v;
                    };
                    if (info.size == 0xFFFFFFFFULL) info.size = take64();
                    if (info.compressed_size == 0xFFFFFFFFULL) info.compressed_size = take64();
                    if (info.local_header_offset == 0xFFFFFFFFULL)
                        info.local_header_offset = take64();
                }
                epos += 4 + field_len;
            }
        }
        info.name = decode_entry_name(raw_name, flags);
        entries_.push_back(std::move(info));
        pos += 46 + static_cast<std::size_t>(name_len) + extra_len + comment_len;
    }
}

ZipReader::~ZipReader() = default;
ZipReader::ZipReader(ZipReader&&) noexcept = default;
ZipReader& ZipReader::operator=(ZipReader&&) noexcept = default;

const ZipEntryInfo* ZipReader::find(std::string_view name) const {
    for (const auto& entry : entries_) {
        if (entry.name == name) return &entry;
    }
    return nullptr;
}

void ZipReader::read_entry(const ZipEntryInfo& entry,
                           const std::function<void(std::string_view)>& sink) const {
    // Offsets come from container data (a ZIP64 extra field can declare
    // anything up to 2^64-1): reject past-EOF targets before the u64
    // addition below can wrap (#1469 hardening — the stream gcount checks
    // remain as the second line of defense).
    if (entry.local_header_offset > impl_->file_size) {
        throw ZipError("Bad file (local header offset out of bounds for " +
                       python_repr(entry.name) + ")");
    }
    std::string header(30, '\0');
    impl_->file.clear();
    impl_->file.seekg(static_cast<std::streamoff>(entry.local_header_offset));
    impl_->file.read(header.data(), 30);
    if (static_cast<std::size_t>(impl_->file.gcount()) != 30 ||
        read_u32(reinterpret_cast<const unsigned char*>(header.data())) != kFileSignature) {
        throw ZipError("Bad file (corrupt local header for " +
                       python_repr(entry.name) + ")");
    }
    const unsigned char* head = reinterpret_cast<const unsigned char*>(header.data());
    const unsigned short name_len = read_u16(head + 26);
    const unsigned short extra_len = read_u16(head + 28);
    const unsigned long long data_offset =
        entry.local_header_offset + 30 + name_len + extra_len;
    impl_->file.seekg(static_cast<std::streamoff>(data_offset));

    unsigned long running_crc = crc32(0L, Z_NULL, 0);
    unsigned long long produced = 0;

    if (entry.method == 0) {  // stored
        std::string chunk(kChunkSize, '\0');
        unsigned long long remaining = entry.compressed_size;
        while (remaining > 0) {
            const std::size_t want = static_cast<std::size_t>(
                remaining < kChunkSize ? remaining : kChunkSize);
            impl_->file.read(chunk.data(), static_cast<std::streamsize>(want));
            if (static_cast<std::size_t>(impl_->file.gcount()) != want) {
                throw ZipError("Bad file (truncated entry " +
                               python_repr(entry.name) + ")");
            }
            running_crc = crc32(running_crc, reinterpret_cast<const Bytef*>(chunk.data()),
                                static_cast<uInt>(want));
            produced += want;
            remaining -= want;
            sink(std::string_view(chunk.data(), want));
        }
    } else if (entry.method == 8) {  // deflate
        z_stream zs{};
        if (inflateInit2(&zs, -15) != Z_OK) throw ZipError("zlib init failed");
        struct ZGuard {
            z_stream* z;
            ~ZGuard() { inflateEnd(z); }
        } guard{&zs};

        std::string in_chunk(kChunkSize, '\0');
        std::string out_chunk(64 * 1024, '\0');
        unsigned long long remaining_in = entry.compressed_size;
        bool stream_ended = false;
        while (!stream_ended) {
            if (zs.avail_in == 0) {
                if (remaining_in == 0) break;  // input exhausted before Z_STREAM_END
                const std::size_t want = static_cast<std::size_t>(
                    remaining_in < kChunkSize ? remaining_in : kChunkSize);
                impl_->file.read(in_chunk.data(), static_cast<std::streamsize>(want));
                if (static_cast<std::size_t>(impl_->file.gcount()) != want) {
                    throw ZipError("Bad file (truncated entry " +
                                   python_repr(entry.name) + ")");
                }
                remaining_in -= want;
                zs.next_in = reinterpret_cast<Bytef*>(in_chunk.data());
                zs.avail_in = static_cast<uInt>(want);
            }
            zs.next_out = reinterpret_cast<Bytef*>(out_chunk.data());
            zs.avail_out = static_cast<uInt>(out_chunk.size());
            const int ret = inflate(&zs, Z_NO_FLUSH);
            if (ret != Z_OK && ret != Z_STREAM_END && ret != Z_BUF_ERROR) {
                throw ZipError("Bad file (corrupt deflate stream for " +
                               python_repr(entry.name) + ")");
            }
            const std::size_t got = out_chunk.size() - zs.avail_out;
            if (got > 0) {
                produced += got;
                if (produced > entry.size) {
                    // Decompression-bomb guard: never emit more than the
                    // central directory declares (Python's ZipExtFile caps
                    // reads at the same size).
                    throw ZipError("Bad file (decompressed size exceeds declared for " +
                                   python_repr(entry.name) + ")");
                }
                running_crc = crc32(running_crc,
                                    reinterpret_cast<const Bytef*>(out_chunk.data()),
                                    static_cast<uInt>(got));
                sink(std::string_view(out_chunk.data(), got));
            }
            if (ret == Z_STREAM_END) stream_ended = true;
            else if (ret == Z_BUF_ERROR && got == 0 && zs.avail_in == 0) break;
        }
        if (produced != entry.size) {
            throw ZipError("Bad file (decompressed size mismatch for " +
                           python_repr(entry.name) + ")");
        }
    } else {
        throw ZipError("That compression method is not supported");
    }

    if (running_crc != entry.crc32) {
        throw ZipError("Bad CRC-32 for file " + python_repr(entry.name));
    }
}

std::string ZipReader::read_entry_bytes(const ZipEntryInfo& entry) const {
    std::string out;
    out.reserve(static_cast<std::size_t>(entry.size));
    read_entry(entry, [&](std::string_view chunk) { out += chunk; });
    return out;
}

bool zip_is_zipfile(const std::filesystem::path& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) return false;
    file.seekg(0, std::ios::end);
    const auto end_pos = file.tellg();
    if (end_pos < 22) return false;
    const unsigned long long file_size = static_cast<unsigned long long>(end_pos);
    const std::size_t window = static_cast<std::size_t>(file_size < 65557 ? file_size : 65557);
    std::string tail(window, '\0');
    file.seekg(static_cast<std::streamoff>(file_size - window));
    file.read(tail.data(), static_cast<std::streamsize>(window));
    if (static_cast<std::size_t>(file.gcount()) != window) return false;
    return find_eocd(tail, file_size - window, file_size) != std::string::npos;
}

struct ZipWriter::Impl {
    std::ofstream file;
    struct Record {
        std::string name;
        unsigned long crc32 = 0;
        unsigned long long compressed_size = 0;
        unsigned long long size = 0;
        unsigned long long offset = 0;
        unsigned short method = 8;
        unsigned short flags = 0;
    };
    std::vector<Record> records;

    explicit Impl(const std::filesystem::path& path) : file(path, std::ios::binary) {}
};

ZipWriter::ZipWriter(const std::filesystem::path& path) : impl_(std::make_unique<Impl>(path)) {
    if (!impl_->file) throw ZipError("cannot open zip for writing: " + path.string());
}

ZipWriter::~ZipWriter() = default;

void ZipWriter::add_bytes(const std::string& arcname, std::string_view bytes) {
    if (impl_->records.size() >= 65535) {
        throw ZipError("too many zip entries (medium-scale limit is 65535)");
    }
    if (bytes.size() > 0xFFFFFFFFULL) {
        throw ZipError("zip entry above 4 GiB unsupported (medium-scale limit)");
    }
    if (arcname.size() > 0xFFFF) {
        // The name length slot is u16: a longer name would silently
        // truncate the count and emit a structurally corrupt container.
        throw ZipError("zip entry name above 65535 bytes");
    }

    Impl::Record record;
    record.name = arcname;
    record.flags = 0;
    for (unsigned char byte : arcname) {
        if (byte >= 0x80) { record.flags = 0x0800; break; }
    }
    record.size = bytes.size();
    record.crc32 = static_cast<unsigned long>(
        crc32(crc32(0L, Z_NULL, 0), reinterpret_cast<const Bytef*>(bytes.data()),
              static_cast<uInt>(bytes.size())));

    std::string payload;
    if (bytes.empty()) {
        // canonical empty deflate stream (what CPython/Info-ZIP emit)
        payload.assign("\x03\x00", 2);
    } else {
        z_stream zs{};
        if (deflateInit2(&zs, Z_DEFAULT_COMPRESSION, Z_DEFLATED, -15, 8,
                         Z_DEFAULT_STRATEGY) != Z_OK) {
            throw ZipError("zlib init failed");
        }
        struct ZGuard {
            z_stream* z;
            ~ZGuard() { deflateEnd(z); }
        } guard{&zs};
        zs.next_in = reinterpret_cast<Bytef*>(const_cast<char*>(bytes.data()));
        zs.avail_in = static_cast<uInt>(bytes.size());
        char buffer[64 * 1024];
        int ret = Z_OK;
        do {
            zs.next_out = reinterpret_cast<Bytef*>(buffer);
            zs.avail_out = sizeof(buffer);
            ret = deflate(&zs, Z_FINISH);
            payload.append(buffer, sizeof(buffer) - zs.avail_out);
        } while (ret != Z_STREAM_END);
    }
    record.compressed_size = payload.size();
    if (record.compressed_size > 0xFFFFFFFFULL) {
        throw ZipError("zip entry above 4 GiB unsupported (medium-scale limit)");
    }
    record.method = 8;

    record.offset = 0;  // filled below from current position
    impl_->file.seekp(0, std::ios::end);
    record.offset = static_cast<unsigned long long>(impl_->file.tellp());

    std::string header;
    put_u32(header, kFileSignature);
    put_u16(header, 20);                      // version needed
    put_u16(header, record.flags);
    put_u16(header, record.method);
    put_u16(header, 0);                       // time (fixed 00:00:00)
    put_u16(header, 0x0021);                  // date (fixed 1980-01-01)
    put_u32(header, record.crc32);
    put_u32(header, static_cast<unsigned long>(record.compressed_size));
    put_u32(header, static_cast<unsigned long>(record.size));
    put_u16(header, static_cast<unsigned short>(arcname.size()));
    put_u16(header, 0);                       // extra len
    header += arcname;
    impl_->file.write(header.data(), static_cast<std::streamsize>(header.size()));
    impl_->file.write(payload.data(), static_cast<std::streamsize>(payload.size()));
    if (!impl_->file) throw ZipError("zip write failed");
    impl_->records.push_back(std::move(record));
}

void ZipWriter::add_file(const std::filesystem::path& file, const std::string& arcname) {
    std::ifstream in(file, std::ios::binary);
    if (!in) throw ZipError("cannot read file for zipping: " + file.string());
    std::error_code size_ec;
    const auto file_size = std::filesystem::file_size(file, size_ec);
    if (!size_ec && file_size > 0xFFFFFFFFULL) {
        throw ZipError("zip entry above 4 GiB unsupported (medium-scale limit): " +
                       file.string());
    }
    // Medium-scale policy: payload is materialized once (bounded by the
    // 4 GiB entry guard), matching zip_package_dir's per-file flow.
    std::string bytes;
    std::string buffer(256 * 1024, '\0');
    while (in) {
        in.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        if (in.gcount() > 0) {
            bytes.append(buffer.data(), static_cast<std::size_t>(in.gcount()));
        }
    }
    if (in.bad()) {
        // A mid-file I/O error ends the loop silently and would zip a
        // CRC-consistent TRUNCATED entry (review CP3) — refuse instead.
        throw ZipError("read error mid-file (refusing truncated entry): " +
                       file.string());
    }
    add_bytes(arcname, bytes);
}

void ZipWriter::finish() {
    impl_->file.seekp(0, std::ios::end);
    const unsigned long long cd_offset = static_cast<unsigned long long>(impl_->file.tellp());
    std::string cd;
    for (const auto& record : impl_->records) {
        put_u32(cd, kCentralSignature);
        put_u16(cd, 20 | (3 << 8));  // version made by: unix, 2.0
        put_u16(cd, 20);             // version needed
        put_u16(cd, record.flags);
        put_u16(cd, record.method);
        put_u16(cd, 0);              // time
        put_u16(cd, 0x0021);         // date
        put_u32(cd, record.crc32);
        put_u32(cd, static_cast<unsigned long>(record.compressed_size));
        put_u32(cd, static_cast<unsigned long>(record.size));
        put_u16(cd, static_cast<unsigned short>(record.name.size()));
        put_u16(cd, 0);              // extra len
        put_u16(cd, 0);              // comment len
        put_u16(cd, 0);              // disk number start
        put_u16(cd, 0);              // internal attrs
        put_u32(cd, 0100644 << 16);  // external attrs: regular file 0644
        put_u32(cd, static_cast<unsigned long>(record.offset));
        cd += record.name;
    }
    const unsigned long long cd_size = cd.size();
    if (cd_offset + cd_size + 22 > 0xFFFFFFFFULL) {
        throw ZipError("zip above 4 GiB unsupported (medium-scale limit)");
    }
    impl_->file.write(cd.data(), static_cast<std::streamsize>(cd.size()));
    std::string eocd;
    put_u32(eocd, kEndSignature);
    put_u16(eocd, 0);
    put_u16(eocd, 0);
    put_u16(eocd, static_cast<unsigned short>(impl_->records.size()));
    put_u16(eocd, static_cast<unsigned short>(impl_->records.size()));
    put_u32(eocd, static_cast<unsigned long>(cd_size));
    put_u32(eocd, static_cast<unsigned long>(cd_offset));
    put_u16(eocd, 0);
    impl_->file.write(eocd.data(), static_cast<std::streamsize>(eocd.size()));
    impl_->file.flush();
    if (!impl_->file) throw ZipError("zip finalize failed");
    impl_->records.clear();
}

std::vector<std::string> safe_members(const ZipReader& archive, const std::string& what) {
    std::set<std::string> seen_casefold;
    std::set<std::string> seen_nfc;
    std::vector<std::string> names;
    names.reserve(archive.infolist().size());
    for (const auto& info : archive.infolist()) {
        if (info.is_symlink_entry()) {
            throw UnsafePathError(what + ": symlink entry rejected: " +
                                  python_repr(info.name));
        }
        const std::string canonical = safe_relative_path(info.name, what);
        check_collision(canonical, seen_casefold, seen_nfc);
        names.push_back(canonical);
    }
    return names;
}

std::vector<std::filesystem::path> extract_archive(const ZipReader& archive,
                                                   const std::filesystem::path& dest_root,
                                                   const std::string& what,
                                                   const CancelToken& cancel) {
    const std::vector<std::string> names = safe_members(archive, what);
    std::filesystem::create_directories(dest_root);
    const auto& entries = archive.infolist();
    std::vector<std::filesystem::path> written;
    for (std::size_t i = 0; i < entries.size(); ++i) {
        cancel.checkpoint();
        const ZipEntryInfo& info = entries[i];
        const std::filesystem::path target =
            ensure_within_root(dest_root, dest_root / names[i]);
        if (info.is_dir()) {
            std::filesystem::create_directories(target);
            continue;
        }
        std::filesystem::create_directories(target.parent_path());
        {
            std::ofstream out(target, std::ios::binary);
            if (!out) throw ZipError("cannot write extracted file: " + target.string());
            archive.read_entry(info, [&](std::string_view chunk) {
                out.write(chunk.data(), static_cast<std::streamsize>(chunk.size()));
                if (!out) throw ZipError("cannot write extracted file: " + target.string());
            });
        }
        written.push_back(target);
    }
    return written;
}

}  // namespace pwb::interchange
