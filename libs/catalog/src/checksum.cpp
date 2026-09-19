#include "pwb/catalog/checksum.hpp"
#include "pwb/domain/sha256.hpp"

#include <array>
#include <cerrno>
#include <cstring>
#include <fstream>

namespace pwb::catalog {

domain::Result<std::string> sha256_file(const std::filesystem::path& path,
                                         std::size_t chunk_size,
                                         const CancelPoll& cancel) {
    if (chunk_size == 0) chunk_size = kChecksumChunkSize;
    std::ifstream handle(path, std::ios::binary);
    if (!handle) {
        return domain::DataError(
            domain::ErrorCode::IoError,
            "cannot open " + path.string() + ": " + std::strerror(ENOENT));
    }
    domain::Sha256 digest;
    std::string chunk(chunk_size, '\0');
    while (handle) {
        handle.read(chunk.data(), static_cast<std::streamsize>(chunk.size()));
        const std::streamsize got = handle.gcount();
        if (got <= 0) break;
        // Poll once per chunk, BEFORE the digest update: a cancelled hash
        // never contributes bytes (no partial digest contract).
        if (cancel && cancel()) {
            return domain::DataError(
                domain::ErrorCode::Cancelled,
                "hash cancelled: " + path.string());
        }
        digest.update(chunk.data(), static_cast<std::size_t>(got));
    }
    if (handle.bad()) {
        return domain::DataError(
            domain::ErrorCode::IoError,
            "read failure on " + path.string() + ": " + std::strerror(errno));
    }
    return digest.hex_digest();
}

std::optional<std::string> sha256_file_or_none(
    const std::filesystem::path& path) {
    auto result = sha256_file(path);
    if (result.is_ok()) return result.value();
    // Python swallows OSError only (missing / permissions); cancellation is
    // impossible here (no callback) and anything else is also an IO shape.
    if (result.error().code == domain::ErrorCode::Cancelled) return std::nullopt;
    return std::nullopt;
}

std::string sha256_text(const std::string& text) {
    std::string normalized;
    normalized.reserve(text.size());
    for (std::size_t i = 0; i < text.size(); ++i) {
        if (text[i] == '\r') {
            if (i + 1 < text.size() && text[i + 1] == '\n') continue;  // CRLF
            normalized.push_back('\n');                                // lone CR
        } else {
            normalized.push_back(text[i]);
        }
    }
    return domain::Sha256::of_bytes(normalized);
}

}  // namespace pwb::catalog
