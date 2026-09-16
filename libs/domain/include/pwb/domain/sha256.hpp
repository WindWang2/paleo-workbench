// Self-contained streaming SHA-256 (FIPS 180-4). No external crypto
// dependency: the data kernel only needs digests, and pulling OpenSSL into
// the vendored suite would violate the "no QGIS/GDAL/PROJ builds" budget.
// Byte-identical results to Python hashlib.sha256 for any input length.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <optional>
#include <string>
#include <string_view>

namespace pwb::domain {

class Sha256 {
public:
    Sha256() { reset(); }

    void reset();
    void update(const void* data, std::size_t size);
    void update(std::string_view text) {
        update(text.data(), text.size());
    }
    std::string hex_digest();

    // One-shot helpers.
    static std::string of_bytes(std::string_view bytes);
    static std::optional<std::string> of_file(const std::filesystem::path& file,
                                              std::size_t chunk = 1 << 20);

private:
    void process_block(const std::uint8_t* block);
    std::uint32_t state_[8];
    std::uint64_t total_bits_ = 0;
    std::array<std::uint8_t, 64> buffer_{};
    std::size_t buffered_ = 0;
};

}  // namespace pwb::domain
