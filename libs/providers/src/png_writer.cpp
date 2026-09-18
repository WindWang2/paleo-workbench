#include "png_writer.hpp"

#include <stdexcept>
#include <fstream>

namespace pwb::providers::png {

namespace {

const std::uint8_t kSignature[8] = {0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A};

std::uint32_t crc32(const std::uint8_t* data, std::size_t length) {
    static const std::uint32_t* table = [] {
        static std::uint32_t t[256];
        for (std::uint32_t n = 0; n < 256; ++n) {
            std::uint32_t c = n;
            for (int k = 0; k < 8; ++k) {
                c = (c & 1u) != 0u ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            }
            t[n] = c;
        }
        return t;
    }();
    std::uint32_t crc = 0xFFFFFFFFu;
    for (std::size_t i = 0; i < length; ++i) {
        crc = table[(crc ^ data[i]) & 0xFFu] ^ (crc >> 8);
    }
    return crc ^ 0xFFFFFFFFu;
}

void append_u32(std::vector<std::uint8_t>& out, std::uint32_t value) {
    out.push_back(static_cast<std::uint8_t>((value >> 24) & 0xFFu));
    out.push_back(static_cast<std::uint8_t>((value >> 16) & 0xFFu));
    out.push_back(static_cast<std::uint8_t>((value >> 8) & 0xFFu));
    out.push_back(static_cast<std::uint8_t>(value & 0xFFu));
}

// PNG chunk = length + type + data + CRC32(type+data).
void append_chunk(std::vector<std::uint8_t>& out, const char* type,
                  const std::uint8_t* data, std::size_t length) {
    append_u32(out, static_cast<std::uint32_t>(length));
    std::vector<std::uint8_t> crc_input;
    for (int i = 0; i < 4; ++i) {
        out.push_back(static_cast<std::uint8_t>(type[i]));
        crc_input.push_back(static_cast<std::uint8_t>(type[i]));
    }
    for (std::size_t i = 0; i < length; ++i) {
        out.push_back(data[i]);
        crc_input.push_back(data[i]);
    }
    append_u32(out, crc32(crc_input.data(), crc_input.size()));
}

std::uint32_t adler32(const std::uint8_t* data, std::size_t length) {
    std::uint32_t a = 1, b = 0;
    for (std::size_t i = 0; i < length; ++i) {
        a = (a + data[i]) % 65521u;
        b = (b + a) % 65521u;
    }
    return (b << 16) | a;
}

// zlib stream with stored deflate blocks (BTYPE=00): length-prefixed raw
// copies, ≤65535 bytes each, then the adler32 of the raw payload.
std::vector<std::uint8_t> zlib_store(const std::uint8_t* data, std::size_t length) {
    std::vector<std::uint8_t> out;
    out.push_back(0x78);  // CMF: deflate, 32K window
    out.push_back(0x01);  // FLG: check bits for {CMF,FLG}, no dict, fastest
    std::size_t offset = 0;
    while (offset < length) {
        const std::size_t block = std::min<std::size_t>(65535u, length - offset);
        const bool final_block = offset + block == length;
        out.push_back(static_cast<std::uint8_t>(final_block ? 1 : 0));
        const std::uint16_t n = static_cast<std::uint16_t>(block);
        out.push_back(static_cast<std::uint8_t>(n & 0xFFu));
        out.push_back(static_cast<std::uint8_t>((n >> 8) & 0xFFu));
        const std::uint16_t n_not = static_cast<std::uint16_t>(~n);
        out.push_back(static_cast<std::uint8_t>(n_not & 0xFFu));
        out.push_back(static_cast<std::uint8_t>((n_not >> 8) & 0xFFu));
        for (std::size_t i = 0; i < block; ++i) {
            out.push_back(data[offset + i]);
        }
        offset += block;
    }
    append_u32(out, adler32(data, length));
    return out;
}

}  // namespace

std::vector<std::uint8_t> encode_rgb(std::uint32_t width, std::uint32_t height,
                                     const std::uint8_t* rgb, std::size_t byte_count) {
    const std::size_t expected =
        static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 3u;
    if (width == 0 || height == 0 || rgb == nullptr || byte_count < expected) {
        throw std::runtime_error("png encode: invalid raster dimensions or buffer");
    }

    // Raw image scanlines, each prefixed with filter byte 0 (None).
    const std::size_t row_bytes = static_cast<std::size_t>(width) * 3u;
    std::vector<std::uint8_t> raw;
    raw.reserve((row_bytes + 1) * height);
    for (std::uint32_t y = 0; y < height; ++y) {
        raw.push_back(0);
        raw.insert(raw.end(), rgb + static_cast<std::size_t>(y) * row_bytes,
                   rgb + static_cast<std::size_t>(y) * row_bytes + row_bytes);
    }

    std::vector<std::uint8_t> out;
    out.insert(out.end(), kSignature, kSignature + 8);

    std::vector<std::uint8_t> ihdr;
    append_u32(ihdr, width);
    append_u32(ihdr, height);
    ihdr.push_back(8);  // bit depth
    ihdr.push_back(2);  // color type: truecolor RGB
    ihdr.push_back(0);  // compression: deflate
    ihdr.push_back(0);  // filter: adaptive (single pass here)
    ihdr.push_back(0);  // interlace: none
    append_chunk(out, "IHDR", ihdr.data(), ihdr.size());

    const std::vector<std::uint8_t> idat = zlib_store(raw.data(), raw.size());
    append_chunk(out, "IDAT", idat.data(), idat.size());
    append_chunk(out, "IEND", nullptr, 0);
    return out;
}

bool write_rgb(const std::filesystem::path& path, std::uint32_t width,
               std::uint32_t height, const std::uint8_t* rgb, std::size_t byte_count,
               std::string* error) {
    try {
        const std::vector<std::uint8_t> bytes = encode_rgb(width, height, rgb, byte_count);
        std::ofstream stream(path, std::ios::binary | std::ios::trunc);
        if (!stream) {
            if (error != nullptr) *error = "cannot open " + path.generic_string();
            return false;
        }
        stream.write(reinterpret_cast<const char*>(bytes.data()),
                     static_cast<std::streamsize>(bytes.size()));
        if (!stream) {
            if (error != nullptr) *error = "short write to " + path.generic_string();
            return false;
        }
        return true;
    } catch (const std::exception& exc) {
        if (error != nullptr) *error = exc.what();
        return false;
    }
}

}  // namespace pwb::providers::png
