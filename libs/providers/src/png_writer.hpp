// Minimal deterministic PNG encoder (8-bit RGB) for the native thumbnail
// provider. No third-party dependency: the zlib stream uses stored
// (uncompressed) deflate blocks, so bytes are a pure function of the pixels
// — byte-identical output across runs and platforms. Valid PNG per spec
// (signature + IHDR + IDAT + IEND, CRC32 + adler32).
//
// Thumbnail-sized rasters only: stored blocks cost ~2.3x the raw size, an
// honest trade for determinism without vendoring zlib.
#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace pwb::providers::png {

// row-major RGB, 3 bytes per pixel; throws std::runtime_error on bad input.
std::vector<std::uint8_t> encode_rgb(std::uint32_t width, std::uint32_t height,
                                     const std::uint8_t* rgb, std::size_t byte_count);

// Convenience: encode + write; returns false and fills *error on I/O failure.
bool write_rgb(const std::filesystem::path& path, std::uint32_t width,
               std::uint32_t height, const std::uint8_t* rgb, std::size_t byte_count,
               std::string* error);

}  // namespace pwb::providers::png
