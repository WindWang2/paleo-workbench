#include "pwb/ingest/preview/office.hpp"

#include <algorithm>
#include <array>
#include <filesystem>
#include <map>
#include <set>

#include "pwb/ingest/py_compat.hpp"

namespace pwb::ingest::preview {

namespace {

unsigned long read_le16(std::string_view b, size_t off) {
    return static_cast<unsigned char>(b[off]) |
           (static_cast<unsigned char>(b[off + 1]) << 8);
}

unsigned long read_le32(std::string_view b, size_t off) {
    return static_cast<unsigned long>(read_le16(b, off)) |
           (static_cast<unsigned long>(read_le16(b, off + 2)) << 16);
}

unsigned long read_be32(std::string_view b, size_t off) {
    return (static_cast<unsigned long>(static_cast<unsigned char>(b[off])) << 24) |
           (static_cast<unsigned long>(static_cast<unsigned char>(b[off + 1])) << 16) |
           (static_cast<unsigned long>(static_cast<unsigned char>(b[off + 2])) << 8) |
           static_cast<unsigned long>(static_cast<unsigned char>(b[off + 3]));
}

unsigned long read_be16(std::string_view b, size_t off) {
    return (static_cast<unsigned long>(static_cast<unsigned char>(b[off])) << 8) |
           static_cast<unsigned long>(static_cast<unsigned char>(b[off + 1]));
}

// --- CRC-32 (zlib crc32 polynomial 0xEDB88320) ---
unsigned long crc32_update(unsigned long crc, std::string_view data) {
    static const std::array<unsigned long, 256> table = [] {
        std::array<unsigned long, 256> t{};
        for (unsigned long n = 0; n < 256; ++n) {
            unsigned long c = n;
            for (int k = 0; k < 8; ++k) {
                c = (c & 1) ? 0xEDB88320UL ^ (c >> 1) : c >> 1;
            }
            t[n] = c;
        }
        return t;
    }();
    unsigned long c = crc ^ 0xFFFFFFFFUL;
    for (char ch : data) {
        c = table[(c ^ static_cast<unsigned char>(ch)) & 0xFF] ^ (c >> 8);
    }
    return (c ^ 0xFFFFFFFFUL) & 0xFFFFFFFFUL;
}

// --- RFC 1951 raw-deflate decoder (stored / fixed / dynamic Huffman) ---
class BitReader {
public:
    BitReader(std::string_view data) : data_(data) {}
    bool bit() {
        if (byte_ >= data_.size()) { overflow_ = true; return 0; }
        bool b = (static_cast<unsigned char>(data_[byte_]) >> bit_) & 1;
        if (++bit_ == 8) { bit_ = 0; ++byte_; }
        return b;
    }
    unsigned long bits(int count) {
        unsigned long v = 0;
        for (int i = 0; i < count; ++i) v |= static_cast<unsigned long>(bit()) << i;
        return v;
    }
    void align_byte() {
        if (bit_) { bit_ = 0; ++byte_; }
    }
    bool overflow() const { return overflow_; }
    size_t byte_pos() const { return byte_; }

private:
    std::string_view data_;
    size_t byte_ = 0;
    int bit_ = 0;
    bool overflow_ = false;
};

struct Huffman {
    // canonical code lengths -> decode table (simple bit-by-bit walk)
    std::vector<unsigned short> counts;
    std::vector<unsigned short> symbols;

    static Huffman lengths(const std::vector<unsigned short>& lengths) {
        Huffman h;
        h.counts.assign(16, 0);
        for (unsigned short l : lengths) h.counts[l]++;
        h.counts[0] = 0;
        std::vector<unsigned short> offs(16, 0);
        for (int i = 1; i < 16; ++i) offs[i] = offs[i - 1] + h.counts[i - 1];
        h.symbols.assign(lengths.size(), 0);
        for (size_t s = 0; s < lengths.size(); ++s) {
            if (lengths[s]) h.symbols[offs[lengths[s]]++] = static_cast<unsigned short>(s);
        }
        return h;
    }

    int decode(BitReader& br) const {
        int code = 0, first = 0, index = 0;
        for (int len = 1; len < 16; ++len) {
            code |= br.bit();
            int count = counts[len];
            if (code - first < count) return symbols[index + (code - first)];
            index += count;
            first = (first + count) << 1;
            code <<= 1;
        }
        return -1;
    }
};

const unsigned short kLengthBase[29] = {3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17,
    19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258};
const unsigned short kLengthExtra[29] = {0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2,
    2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0};
const unsigned short kDistBase[30] = {1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49,
    65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145,
    8193, 12289, 16385, 24577};
const unsigned short kDistExtra[30] = {0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5,
    6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13};

bool inflate_block(std::string_view input, BitReader& br, std::string& out,
                   size_t max_out, bool& is_final);

bool inflate_stored(std::string_view input, BitReader& br, std::string& out,
                    size_t max_out) {
    br.align_byte();
    if (br.byte_pos() + 4 > input.size()) return false;
    unsigned long len = read_le16(input, br.byte_pos());
    unsigned long nlen = read_le16(input, br.byte_pos() + 2);
    if ((len ^ 0xFFFF) != nlen) return false;
    br.bits(32);  // consume LEN/NLEN
    if (br.byte_pos() + len > input.size()) return false;
    if (out.size() + len > max_out) len = static_cast<unsigned long>(max_out - out.size());
    out.append(input.substr(br.byte_pos(), len));
    for (unsigned long k = 0; k < len; ++k) br.bits(8);
    return true;
}

bool inflate_codes(std::string_view input, BitReader& br, const Huffman& lit,
                   const Huffman& dist, std::string& out, size_t max_out,
                   bool length_limited) {
    while (true) {
        int sym = lit.decode(br);
        if (sym < 0 || br.overflow()) return false;
        if (sym < 256) {
            if (out.size() >= max_out) return true;  // bounded read stop
            out.push_back(static_cast<char>(sym));
        } else if (sym == 256) {
            return true;
        } else {
            sym -= 257;
            if (sym >= 29) return false;
            unsigned long length = kLengthBase[sym] + br.bits(kLengthExtra[sym]);
            int dsym = dist.decode(br);
            if (dsym < 0 || dsym >= 30) return false;
            unsigned long distance = kDistBase[dsym] + br.bits(kDistExtra[dsym]);
            if (distance > out.size()) return false;
            if (out.size() >= max_out && length_limited) return true;
            for (unsigned long k = 0; k < length; ++k) {
                if (out.size() >= max_out) return true;
                out.push_back(out[out.size() - distance]);
            }
        }
    }
}

bool inflate_fixed(std::string_view input, BitReader& br, std::string& out,
                   size_t max_out) {
    std::vector<unsigned short> lengths(288, 0);
    for (int i = 0; i < 144; ++i) lengths[i] = 8;
    for (int i = 144; i < 256; ++i) lengths[i] = 9;
    for (int i = 256; i < 280; ++i) lengths[i] = 7;
    for (int i = 280; i < 288; ++i) lengths[i] = 8;
    Huffman lit = Huffman::lengths(lengths);
    std::vector<unsigned short> dlengths(30, 5);
    Huffman dist = Huffman::lengths(dlengths);
    return inflate_codes(input, br, lit, dist, out, max_out, true);
}

bool inflate_dynamic(std::string_view input, BitReader& br, std::string& out,
                     size_t max_out) {
    static const unsigned short kOrder[19] = {16, 17, 18, 0, 8, 7, 9, 6, 10, 5,
        11, 4, 12, 3, 13, 2, 14, 1, 15};
    unsigned long hlit = br.bits(5) + 257;
    unsigned long hdist = br.bits(5) + 1;
    unsigned long hclen = br.bits(4) + 4;
    if (hlit > 286 || hdist > 30) return false;
    std::vector<unsigned short> cl_lengths(19, 0);
    for (unsigned long i = 0; i < hclen; ++i) {
        cl_lengths[kOrder[i]] = static_cast<unsigned short>(br.bits(3));
    }
    Huffman cl = Huffman::lengths(cl_lengths);
    std::vector<unsigned short> lengths;
    lengths.reserve(hlit + hdist);
    while (lengths.size() < hlit + hdist) {
        int sym = cl.decode(br);
        if (sym < 0 || br.overflow()) return false;
        if (sym < 16) {
            lengths.push_back(static_cast<unsigned short>(sym));
        } else if (sym == 16) {
            if (lengths.empty()) return false;
            unsigned short prev = lengths.back();
            unsigned long rep = 3 + br.bits(2);
            for (unsigned long k = 0; k < rep; ++k) lengths.push_back(prev);
        } else if (sym == 17) {
            unsigned long rep = 3 + br.bits(3);
            for (unsigned long k = 0; k < rep; ++k) lengths.push_back(0);
        } else {
            unsigned long rep = 11 + br.bits(7);
            for (unsigned long k = 0; k < rep; ++k) lengths.push_back(0);
        }
    }
    if (lengths.size() != hlit + hdist) return false;
    Huffman lit = Huffman::lengths(
        std::vector<unsigned short>(lengths.begin(), lengths.begin() + hlit));
    Huffman dist = Huffman::lengths(std::vector<unsigned short>(
        lengths.begin() + static_cast<long>(hlit), lengths.end()));
    return inflate_codes(input, br, lit, dist, out, max_out, true);
}

bool inflate_block(std::string_view input, BitReader& br, std::string& out,
                   size_t max_out, bool& is_final) {
    is_final = br.bits(1) != 0;
    unsigned long type = br.bits(2);
    switch (type) {
        case 0: return inflate_stored(input, br, out, max_out);
        case 1: return inflate_fixed(input, br, out, max_out);
        case 2: return inflate_dynamic(input, br, out, max_out);
        default: return false;
    }
}

std::string cp437_to_utf8(std::string_view raw) {
    static const char* kHigh[128] = {
        "Ç", "ü", "é", "â", "ä", "à", "å", "ç", "ê", "ë", "è", "ï", "î", "ì",
        "Ä", "Å", "É", "æ", "Æ", "ô", "ö", "ò", "û", "ù", "ÿ", "Ö", "Ü", "¢",
        "£", "¥", "₧", "ƒ", "á", "í", "ó", "ú", "ñ", "Ñ", "ª", "º", "¿", "⌐",
        "¬", "½", "¼", "¡", "«", "»", "░", "▒", "▓", "│", "┤", "╡", "╢", "╖",
        "╕", "╣", "║", "╗", "╝", "╜", "╛", "┐", "└", "┴", "┬", "├", "─", "┼",
        "╞", "╟", "╚", "╔", "╩", "╦", "╠", "═", "╬", "╧", "╨", "╤", "╥", "╙",
        "╘", "╒", "╓", "╫", "╪", "┘", "┌", "█", "▄", "▌", "▐", "▀", "α", "ß",
        "Γ", "π", "Σ", "σ", "µ", "τ", "Φ", "Θ", "Ω", "δ", "∞", "φ", "ε", "∩",
        "≡", "±", "≥", "≤", "⌠", "⌡", "÷", "≈", "°", "∙", "·", "√", "ⁿ", "²",
        "■", "\u00A0"};
    std::string out;
    for (char ch : raw) {
        unsigned char c = static_cast<unsigned char>(ch);
        if (c < 0x80) {
            out.push_back(static_cast<char>(c));
        } else {
            out += kHigh[c - 0x80];
        }
    }
    return out;
}

PreviewResult message_result(const ResourceRef& res, std::string message,
                             std::vector<std::pair<std::string, std::string>>
                                 summary_rows = {}) {
    PreviewResult r;
    r.mode = "message";
    r.title = res.name;
    r.path = res.path;
    r.revision = res.revision;  // Python: _revision(path) / safe_stat
    r.format = res.format;
    r.status = res.status;
    r.type_label = res.type;
    r.message = message;
    r.warning = message;
    r.summary_rows = std::move(summary_rows);
    return r;
}

PreviewResult stat_revision_result(const ResourceRef& res, std::string mode) {
    PreviewResult r;
    r.mode = std::move(mode);
    r.title = res.name;
    r.path = res.path;
    r.revision = res.revision;
    r.format = res.format;
    r.status = res.status;
    r.type_label = res.type;
    return r;
}

}  // namespace

std::vector<ZipEntry> read_central_directory(std::string_view bytes) {
    size_t file_size = bytes.size();
    size_t tail_size = std::min<size_t>(file_size, 22 + 65535);
    std::string_view tail = bytes.substr(file_size - tail_size);

    // _find_eocd: last PK\x05\x06 whose comment length exactly reaches the end
    std::optional<size_t> eocd_position;
    {
        size_t position = tail.rfind("PK\x05\x06");
        while (position != std::string_view::npos) {
            if (position + 22 <= tail.size()) {
                unsigned long comment_length = read_le16(tail, position + 20);
                if (position + 22 + comment_length == tail.size()) {
                    eocd_position = position;
                    break;
                }
            }
            if (position == 0) break;
            // Python rfind(sig, 0, position): end bound = search earlier hits
            position = tail.rfind("PK\x05\x06", position - 1);
        }
    }
    if (!eocd_position) throw ArchiveSafetyError("EOCD 缺失或损坏");
    size_t absolute_eocd = file_size - tail_size + *eocd_position;

    unsigned long disk_number = read_le16(tail, *eocd_position + 4);
    unsigned long central_disk = read_le16(tail, *eocd_position + 6);
    unsigned long entries_on_disk = read_le16(tail, *eocd_position + 8);
    unsigned long total_entries = read_le16(tail, *eocd_position + 10);
    unsigned long central_size = read_le32(tail, *eocd_position + 12);
    unsigned long central_offset = read_le32(tail, *eocd_position + 16);

    if (disk_number != 0 || central_disk != 0 || entries_on_disk != total_entries) {
        throw ArchiveSafetyError("不支持 multi-disk ZIP");
    }
    if (entries_on_disk == 0xFFFF || total_entries == 0xFFFF ||
        central_size == 0xFFFFFFFF || central_offset == 0xFFFFFFFF) {
        throw ArchiveSafetyError("不支持 ZIP64");
    }
    if (total_entries > static_cast<unsigned long>(kMaxCentralEntries)) {
        throw ArchiveSafetyError("central entries 超过 10000");
    }
    if (central_size > static_cast<unsigned long>(kMaxCentralDirectoryBytes)) {
        throw ArchiveSafetyError("central directory 超过 4 MiB");
    }
    unsigned long central_end = central_offset + central_size;
    if (central_offset > file_size || central_end != absolute_eocd) {
        throw ArchiveSafetyError("central directory offset/size 越界");
    }
    std::string_view central = bytes.substr(central_offset, central_size);
    if (central.size() != central_size) {
        throw ArchiveSafetyError("central directory 截断");
    }

    size_t position = 0;
    unsigned long parsed_entries = 0;
    unsigned long utf8_name_bytes = 0;
    std::vector<ZipEntry> entries;
    while (position < central.size()) {
        if (position + 46 > central.size() ||
            central.compare(position, 4, "PK\x01\x02") != 0) {
            throw ArchiveSafetyError("central directory entry 损坏");
        }
        unsigned long flags = read_le16(central, position + 8);
        unsigned long compressed_size = read_le32(central, position + 20);
        unsigned long uncompressed_size = read_le32(central, position + 24);
        unsigned long name_length = read_le16(central, position + 28);
        unsigned long extra_length = read_le16(central, position + 30);
        unsigned long comment_length = read_le16(central, position + 32);
        unsigned long start_disk = read_le16(central, position + 34);
        unsigned long local_offset = read_le32(central, position + 42);
        size_t entry_end = position + 46 + name_length + extra_length + comment_length;
        if (entry_end > central.size()) {
            throw ArchiveSafetyError("central directory entry 越界");
        }
        if (compressed_size == 0xFFFFFFFF || uncompressed_size == 0xFFFFFFFF ||
            local_offset == 0xFFFFFFFF || start_disk == 0xFFFF) {
            throw ArchiveSafetyError("不支持 ZIP64 entry");
        }
        if (start_disk != 0 || local_offset >= central_offset) {
            throw ArchiveSafetyError("entry offset/disk 无效");
        }
        std::string_view raw_name = central.substr(position + 46, name_length);
        std::string decoded_name;
        if (flags & 0x800) {
            // UTF-8: verify well-formedness like Python's strict decode
            auto decoded = decode_utf8_sig(raw_name, /*strict=*/true);
            if (!decoded) throw ArchiveSafetyError("entry 名称编码无效");
            decoded_name = *decoded;
        } else {
            decoded_name = cp437_to_utf8(raw_name);
        }
        utf8_name_bytes += decoded_name.size();
        if (utf8_name_bytes > static_cast<unsigned long>(kMaxCentralNameBytes)) {
            throw ArchiveSafetyError("central 名称总量超过 1 MiB");
        }
        parsed_entries += 1;
        if (parsed_entries > static_cast<unsigned long>(kMaxCentralEntries)) {
            throw ArchiveSafetyError("central entries 超过 10000");
        }
        ZipEntry entry;
        entry.name = std::move(decoded_name);
        entry.local_offset = local_offset;
        entry.compressed_size = compressed_size;
        entry.uncompressed_size = uncompressed_size;
        entry.method = static_cast<unsigned short>(read_le16(central, position + 10));
        entries.push_back(std::move(entry));
        position = entry_end;
    }
    if (parsed_entries != total_entries) {
        throw ArchiveSafetyError("EOCD entry count 不一致");
    }
    return entries;
}

std::string zip_read_member(std::string_view bytes, const ZipEntry& entry) {
    size_t offset = entry.local_offset;
    if (offset + 30 > bytes.size() || bytes.compare(offset, 4, "PK\x03\x04") != 0) {
        throw BadZipError("Bad magic number for file header");
    }
    unsigned long name_length = read_le16(bytes, offset + 26);
    unsigned long extra_length = read_le16(bytes, offset + 28);
    size_t data_start = offset + 30 + name_length + extra_length;
    if (data_start + entry.compressed_size > bytes.size()) {
        throw BadZipError("Truncated file header");
    }
    std::string_view payload = bytes.substr(data_start, entry.compressed_size);
    std::string content;
    if (entry.method == 0) {
        content = std::string(payload);
    } else if (entry.method == 8) {
        BitReader br(payload);
        while (true) {
            bool is_final = false;
            if (!inflate_block(payload, br, content,
                               static_cast<size_t>(kMaxEmbeddedImageBytes) + 1,
                               is_final)) {
                throw BadZipError("Error decompressing data");
            }
            if (br.overflow()) throw BadZipError("Compressed data ended early");
            if (is_final || content.size() >=
                                static_cast<size_t>(kMaxEmbeddedImageBytes) + 1) {
                break;
            }
        }
    } else {
        throw BadZipError("That compression method is not supported");
    }
    unsigned long crc = 0;
    crc = crc32_update(crc, content);
    if (crc != read_le32(bytes, offset + 14)) {
        throw BadZipError("Bad CRC-32 for file");
    }
    return content;
}

PreviewResult zip_preview(const ResourceRef& resource, std::string_view bytes,
                          int max_rows) {
    std::vector<ZipEntry> entries;
    try {
        entries = read_central_directory(bytes);
    } catch (const ArchiveSafetyError& exc) {
        return message_result(resource, "ZIP 目录不安全: " + std::string(exc.what()));
    } catch (const std::exception&) {
        return message_result(resource, "ZIP 包格式错误，无法读取目录");
    }
    int visible_limit = std::min(max_rows, kMaxArchiveNames);
    std::vector<std::string> names;
    for (const auto& e : entries) names.push_back(e.name);
    std::sort(names.begin(), names.end());
    bool truncated = static_cast<int>(names.size()) > visible_limit;
    names.resize(std::min<size_t>(names.size(), static_cast<size_t>(visible_limit)));
    PreviewResult r = stat_revision_result(resource, "table");
    r.table_headers = {"ZIP 条目"};
    for (const auto& name : names) r.table_rows.push_back({name});
    r.truncated = truncated;
    r.warning = truncated
                    ? "ZIP 目录仅显示排序后的前 " + std::to_string(visible_limit) +
                          " 个条目，已截断"
                    : "";
    return r;
}

PreviewResult wlp_preview(const ResourceRef& resource) {
    return message_result(
        resource,
        "\xE6\x9A\x82\xE4\xB8\x8D\xE6\x94\xAF\xE6\x8C\x81 WLP \xE5\x86\x85"
        "\xE7\xBD\xAE\xE9\xA2\x84\xE8\xA7\x88");  // 暂不支持 WLP 内置预览
}

PreviewResult pptx_preview(const ResourceRef& resource, std::string_view bytes) {
    std::vector<ZipEntry> entries;
    try {
        entries = read_central_directory(bytes);
    } catch (const ArchiveSafetyError& exc) {
        return message_result(resource,
                              "PPTX ZIP 目录不安全: " + std::string(exc.what()));
    } catch (const std::exception&) {
        return message_result(resource, "PPTX 包格式错误，无法读取元数据");
    }
    try {
        std::set<std::string> slide_names;
        std::map<std::string, std::vector<ZipEntry>> grouped;
        for (const auto& entry : entries) {
            if (entry.name.empty() || entry.name.back() == '/') continue;
            if (entry.name.size() > 0 && entry.name[0] == '/') continue;
            // _SLIDE_NAME fullmatch: ppt/slides/slide[1-9][0-9]*\.xml
            static const std::string kPrefix = "ppt/slides/slide";
            static const std::string kSuffix = ".xml";
            if (entry.name.rfind(kPrefix, 0) == 0 &&
                entry.name.size() > kPrefix.size() + kSuffix.size() &&
                entry.name.compare(entry.name.size() - kSuffix.size(), kSuffix.size(),
                                   kSuffix) == 0) {
                std::string digits = entry.name.substr(
                    kPrefix.size(), entry.name.size() - kPrefix.size() - kSuffix.size());
                bool ok = !digits.empty() && digits[0] >= '1' && digits[0] <= '9';
                for (char d : digits) ok = ok && d >= '0' && d <= '9';
                if (ok) slide_names.insert(entry.name);
            }
            if (entry.name == "docProps/thumbnail.jpeg" ||
                entry.name == "docProps/thumbnail.png") {
                grouped[entry.name].push_back(entry);
            }
        }
        std::vector<std::pair<std::string, std::string>> summary;
        summary.emplace_back("幻灯片数", std::to_string(slide_names.size()));
        for (const auto& [name, matches] : grouped) {
            if (matches.size() > 1) {
                return message_result(
                    resource, "PPTX 包含重复缩略图条目，已拒绝读取", summary);
            }
        }
        const ZipEntry* thumbnail = nullptr;
        for (const char* preferred : {"docProps/thumbnail.jpeg", "docProps/thumbnail.png"}) {
            auto it = grouped.find(preferred);
            if (it != grouped.end()) {
                thumbnail = &it->second[0];
                break;
            }
        }
        if (!thumbnail) {
            return message_result(resource, "PPTX 未发现可用缩略图", summary);
        }
        if (static_cast<long long>(thumbnail->uncompressed_size) >
            kMaxEmbeddedImageBytes) {
            return message_result(resource, "PPTX 缩略图过大，已拒绝读取", summary);
        }
        std::string content = zip_read_member(bytes, *thumbnail);
        if (static_cast<long long>(content.size()) > kMaxEmbeddedImageBytes) {
            return message_result(resource, "PPTX 缩略图实际内容过大，已拒绝读取",
                                  summary);
        }
        PreviewResult r = stat_revision_result(resource, "image");
        r.summary_rows = summary;
        r.image_bytes = content;
        r.estimated_bytes = static_cast<long long>(content.size());
        return r;
    } catch (const std::exception&) {
        return message_result(resource, "PPTX 包格式错误，无法读取元数据");
    }
}

PreviewResult dfb_preview(const ResourceRef& resource, std::string_view bytes,
                          const std::vector<std::pair<std::string, std::string>>&
                              sibling_dir_entries) {
    namespace fs = std::filesystem;
    // _dfb_sibling: same-stem .png/.jpg/.jpeg sibling, rank png < jpg < jpeg,
    // key (rank, name.casefold(), name); operates on the parent directory.
    if (!sibling_dir_entries.empty()) {
        PathParts self = split_path_parts(resource.path);
        std::optional<std::tuple<int, std::string, std::string>> best;
        std::string best_name;
        static const std::map<std::string, int> rank = {
            {".png", 0}, {".jpg", 1}, {".jpeg", 2}};
        for (const auto& [name, content] : sibling_dir_entries) {
            PathParts parts = split_path_parts(name);
            std::string lower_suffix;
            for (char c : parts.suffix) {
                lower_suffix.push_back(c >= 'A' && c <= 'Z'
                                           ? static_cast<char>(c + 32)
                                           : c);
            }
            auto it = rank.find(lower_suffix);
            if (it == rank.end() || parts.stem != self.stem) continue;
            std::string folded;
            for (char c : parts.name) {
                folded.push_back(c >= 'A' && c <= 'Z' ? static_cast<char>(c + 32) : c);
            }
            auto key = std::make_tuple(it->second, folded, parts.name);
            if (!best || key < *best) {
                best = key;
                best_name = name;
            }
        }
        if (best) {
            for (const auto& [name, content] : sibling_dir_entries) {
                if (name != best_name) continue;
                if (static_cast<long long>(content.size()) > kMaxEmbeddedImageBytes) {
                    return message_result(
                        resource, "DFB 同名预览图超过 16 MiB，已拒绝读取");
                }
                PreviewResult r = stat_revision_result(resource, "image");
                r.path = (fs::path(resource.path).parent_path() / name)
                             .generic_string();
                r.revision.stat_size = static_cast<long long>(content.size());
                r.summary_rows.emplace_back(
                    "预览来源", split_path_parts(name).name);
                r.image_bytes = content;
                r.estimated_bytes = static_cast<long long>(content.size());
                return r;
            }
        }
    }

    long long size = static_cast<long long>(bytes.size());
    std::string image_bytes;
    bool found = false;
    if (size > 0) {
        // _find_embedded_image: PNG signatures first (all positions), then JPEG
        size_t start = 0;
        while ((start = bytes.find("\x89PNG\r\n\x1a\n", start)) !=
               std::string_view::npos) {
            auto end = validated_png_range(bytes, start);
            if (end) {
                image_bytes = std::string(bytes.substr(start, *end - start));
                found = true;
                break;
            }
            ++start;
        }
        if (!found) {
            start = 0;
            while ((start = bytes.find("\xff\xd8", start)) != std::string_view::npos) {
                auto end = validated_jpeg_range(bytes, start);
                if (end) {
                    image_bytes = std::string(bytes.substr(start, *end - start));
                    found = true;
                    break;
                }
                ++start;
            }
        }
    }
    if (!found) {
        PreviewResult r = message_result(
            resource, "未发现经过结构验证的 DFB 预览图像");
        r.summary_rows.emplace_back("文件大小", format_size(size));
        r.summary_rows.emplace_back("预览状态", "仅元数据");
        return r;
    }
    PreviewResult r = stat_revision_result(resource, "image");
    r.summary_rows.emplace_back("预览来源", "DFB 内嵌图像");
    r.image_bytes = image_bytes;
    r.estimated_bytes = static_cast<long long>(image_bytes.size());
    return r;
}

std::optional<size_t> validated_png_range(std::string_view mapped, size_t start) {
    size_t max_end = std::min(mapped.size(),
                              start + static_cast<size_t>(kMaxEmbeddedImageBytes));
    size_t position = start + 8;  // signature
    bool seen_ihdr = false;
    bool seen_idat = false;
    while (position + 12 <= max_end) {
        unsigned long length = read_be32(mapped, position);
        std::string_view chunk_type = mapped.substr(position + 4, 4);
        unsigned long chunk_end = position + 12 + length;
        bool letters = true;
        for (char c : chunk_type) {
            unsigned char u = static_cast<unsigned char>(c);
            letters = letters && ((u >= 65 && u <= 90) || (u >= 97 && u <= 122));
        }
        if (chunk_end > max_end || !letters) return std::nullopt;
        unsigned long expected_crc = read_be32(mapped, chunk_end - 4);
        unsigned long actual_crc = crc32_update(0, mapped.substr(position + 4, 4 + length));
        if (actual_crc != expected_crc) return std::nullopt;
        if (!seen_ihdr) {
            if (chunk_type != "IHDR" || length != 13) return std::nullopt;
            seen_ihdr = true;
        } else if (chunk_type == "IHDR") {
            return std::nullopt;
        }
        if (chunk_type == "IDAT") seen_idat = true;
        if (chunk_type == "IEND") {
            if (length != 0 || !seen_idat) return std::nullopt;
            return chunk_end;
        }
        position = chunk_end;
    }
    return std::nullopt;
}

std::optional<size_t> validated_jpeg_range(std::string_view mapped, size_t start) {
    size_t max_end = std::min(mapped.size(),
                              start + static_cast<size_t>(kMaxEmbeddedImageBytes));
    if (start + 2 > max_end || mapped.substr(start, 2) != "\xff\xd8") {
        return std::nullopt;
    }
    size_t position = start + 2;
    std::set<int> frame_components;
    bool frame_seen = false;
    bool seen_scan = false;
    auto sof_marker = [](int m) {
        return m == 0xC0 || m == 0xC1 || m == 0xC2 || m == 0xC3 || m == 0xC5 ||
               m == 0xC6 || m == 0xC7 || m == 0xC9 || m == 0xCA || m == 0xCB ||
               m == 0xCD || m == 0xCE || m == 0xCF;
    };
    while (position < max_end) {
        if (static_cast<unsigned char>(mapped[position]) != 0xFF) return std::nullopt;
        while (position < max_end &&
               static_cast<unsigned char>(mapped[position]) == 0xFF) {
            ++position;
        }
        if (position >= max_end) return std::nullopt;
        int marker = static_cast<unsigned char>(mapped[position]);
        position += 1;
        if (marker == 0xD9) {
            if (frame_seen && seen_scan) return position;
            return std::nullopt;
        }
        if (marker == 0x00 || marker == 0xD8 || (marker >= 0xD0 && marker <= 0xD7)) {
            return std::nullopt;
        }
        if (marker == 0x01) continue;  // TEM
        if (position + 2 > max_end) return std::nullopt;
        unsigned long segment_length = read_be16(mapped, position);
        if (segment_length < 2 ||
            position + segment_length > max_end) {
            return std::nullopt;
        }
        size_t body_start = position + 2;
        size_t segment_end = position + segment_length;
        if (sof_marker(marker)) {
            if (frame_seen || seen_scan || segment_length < 8) return std::nullopt;
            int precision = static_cast<unsigned char>(mapped[body_start]);
            unsigned long height = read_be16(mapped, body_start + 1);
            unsigned long width = read_be16(mapped, body_start + 3);
            int component_count = static_cast<unsigned char>(mapped[body_start + 5]);
            if (precision == 0 || precision > 16 || width == 0 || height == 0 ||
                component_count == 0 || component_count > 4 ||
                segment_length != 8 + 3 * static_cast<unsigned long>(component_count)) {
                return std::nullopt;
            }
            std::set<int> components;
            size_t component_position = body_start + 6;
            for (int i = 0; i < component_count; ++i) {
                int identifier = static_cast<unsigned char>(mapped[component_position]);
                int sampling = static_cast<unsigned char>(mapped[component_position + 1]);
                int quant = static_cast<unsigned char>(mapped[component_position + 2]);
                int horizontal = sampling >> 4;
                int vertical = sampling & 0x0F;
                if (components.count(identifier) || horizontal == 0 ||
                    horizontal > 4 || vertical == 0 || vertical > 4 || quant > 3) {
                    return std::nullopt;
                }
                components.insert(identifier);
                component_position += 3;
            }
            frame_components = components;
            frame_seen = true;
        }
        if (marker != 0xDA) {
            position = segment_end;
            continue;
        }
        if (!frame_seen || segment_length < 6) return std::nullopt;
        int scan_component_count = static_cast<unsigned char>(mapped[body_start]);
        if (scan_component_count == 0 ||
            scan_component_count > static_cast<int>(frame_components.size()) ||
            segment_length != 6 + 2 * static_cast<unsigned long>(scan_component_count)) {
            return std::nullopt;
        }
        std::set<int> scan_components;
        size_t component_position = body_start + 1;
        for (int i = 0; i < scan_component_count; ++i) {
            int identifier = static_cast<unsigned char>(mapped[component_position]);
            int table_selectors =
                static_cast<unsigned char>(mapped[component_position + 1]);
            if (!frame_components.count(identifier) ||
                scan_components.count(identifier) ||
                (table_selectors >> 4) > 3 || (table_selectors & 0x0F) > 3) {
                return std::nullopt;
            }
            scan_components.insert(identifier);
            component_position += 2;
        }
        int spectral_start = static_cast<unsigned char>(mapped[component_position]);
        int spectral_end = static_cast<unsigned char>(mapped[component_position + 1]);
        int approximation = static_cast<unsigned char>(mapped[component_position + 2]);
        if (spectral_start > 63 || spectral_end > 63 ||
            (approximation >> 4) > 13 || (approximation & 0x0F) > 13) {
            return std::nullopt;
        }
        seen_scan = true;
        position = segment_end;
        bool scan_has_entropy = false;
        while (position < max_end) {
            size_t marker_start = position;
            while (marker_start < max_end &&
                   static_cast<unsigned char>(mapped[marker_start]) != 0xFF) {
                ++marker_start;
            }
            if (marker_start >= max_end) return std::nullopt;
            if (marker_start > position) scan_has_entropy = true;
            position = marker_start + 1;
            while (position < max_end &&
                   static_cast<unsigned char>(mapped[position]) == 0xFF) {
                ++position;
            }
            if (position >= max_end) return std::nullopt;
            int next_marker = static_cast<unsigned char>(mapped[position]);
            if (next_marker == 0x00) {
                scan_has_entropy = true;
                position += 1;
                continue;
            }
            if (next_marker >= 0xD0 && next_marker <= 0xD7) {
                position += 1;
                continue;
            }
            if (next_marker == 0xD9) {
                if (!scan_has_entropy) return std::nullopt;
                return position + 1;
            }
            if (!scan_has_entropy) return std::nullopt;
            position = marker_start;
            break;
        }
    }
    return std::nullopt;
}

}  // namespace pwb::ingest::preview
