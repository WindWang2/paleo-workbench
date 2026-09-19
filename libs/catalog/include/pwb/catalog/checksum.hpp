// Unified SHA-256 helpers (conv-31; catalog/checksum.py parity, ADR 0056).
//
// Streaming 1 MiB chunks; the cancel callback is polled once per chunk
// BEFORE the digest is updated, and a cancellation never yields a partial
// digest (the error carries the path, like ChecksumCancelled). Text hashing
// normalizes CRLF/CR to LF first (#998). sha256_file_or_none maps
// unreadable files (missing / permissions) to nullopt — every other error
// propagates.
#pragma once

#include "pwb/domain/errors.hpp"

#include <filesystem>
#include <functional>
#include <optional>
#include <string>

namespace pwb::catalog {

inline constexpr std::size_t kChecksumChunkSize = 1024 * 1024;  // 1 MiB

// catalog/checksum.py CHUNK_SIZE parity.
using CancelPoll = std::function<bool()>;

// Hex SHA-256 of *path* streamed in *chunk_size* blocks. Cancelled →
// Result error whose message is "hash cancelled: <path>" (byte-identical
// to the Python ChecksumCancelled text); IO failure → the errno message.
domain::Result<std::string> sha256_file(
    const std::filesystem::path& path,
    std::size_t chunk_size = kChecksumChunkSize,
    const CancelPoll& cancel = nullptr);

// sha256_file that maps OSError (missing / unreadable) to nullopt.
std::optional<std::string> sha256_file_or_none(
    const std::filesystem::path& path);

// SHA-256 of text with CRLF/CR → LF normalization (#998).
std::string sha256_text(const std::string& text);

}  // namespace pwb::catalog
