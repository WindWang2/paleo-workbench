// Internal helpers shared by the edit-commit and run-publish paths of
// CommitCoordinator (defined across commit_coordinator.cpp and
// run_coordinator.cpp). Not installed, not part of any public contract.
#pragma once

#include "pwb/domain/errors.hpp"
#include "pwb/domain/ids.hpp"
#include "pwb/domain/sha256.hpp"
#include "pwb/domain/stage.hpp"
#include "pwb/project/paths.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>

namespace pwb::data::detail {

namespace fs = std::filesystem;

inline std::optional<std::string> read_file_text(const fs::path& file) {
    std::ifstream stream(file, std::ios::binary);
    if (!stream) return std::nullopt;
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    if (stream.bad()) return std::nullopt;
    return buffer.str();
}

inline bool write_file_bytes(const fs::path& file, std::string_view bytes) {
    std::ofstream stream(file, std::ios::binary | std::ios::trunc);
    if (!stream) return false;
    stream.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    stream.flush();
    return static_cast<bool>(stream);
}

// Streams source → destination while hashing (place_managed_file parity,
// without the CAS/blob fast path — round 1 scope).
struct PlacedPayload {
    fs::path final_path;
    std::string rel_path;  // project-relative POSIX
    std::uintmax_t size = 0;
    std::string sha256;
};

inline domain::Result<PlacedPayload> place_payload(
    const fs::path& source, const fs::path& project_path,
    domain::DataStage stage, const domain::AssetId& asset_id,
    const domain::VersionId& version_id) {
    if (!domain::is_safe_storage_segment(asset_id.str()) ||
        !domain::is_safe_storage_segment(version_id.str())) {
        return domain::DataError(domain::ErrorCode::UnsafeId,
                                 "asset/version id unsafe as storage segment");
    }
    const fs::path artifacts = pwb::project::artifact_dir_for(project_path);
    const char* stage_dir =
        stage == domain::DataStage::Raw
            ? "raw"
            : (stage == domain::DataStage::Derived
                   ? "derived"
                   : (stage == domain::DataStage::Intermediate
                          ? "intermediate"
                          : "outputs"));
    const fs::path target_dir =
        artifacts / stage_dir / asset_id.str() / version_id.str();
    std::error_code ec;
    fs::create_directories(target_dir, ec);
    if (ec) {
        return domain::DataError(domain::ErrorCode::IoError,
                                 "cannot create payload dir: " + ec.message());
    }
    const fs::path target = target_dir / source.filename();
    if (fs::exists(target, ec)) {
        return domain::DataError(
            domain::ErrorCode::ImmutableVersion,
            "managed payload already exists: " +
                pwb::project::path_to_u8(target));
    }
    const fs::path tmp =
        target_dir / (".place-" + std::to_string(
                       std::chrono::steady_clock::now().time_since_epoch()
                           .count()));
    {
        std::ifstream in(source, std::ios::binary);
        if (!in) {
            return domain::DataError(
                domain::ErrorCode::InvalidArgument,
                "staged source unreadable: " + pwb::project::path_to_u8(source));
        }
        std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
        if (!out) {
            return domain::DataError(domain::ErrorCode::IoError,
                                     "cannot create payload tmp");
        }
        pwb::domain::Sha256 digest;
        std::string buffer(1 << 20, '\0');
        PlacedPayload placed;
        while (in) {
            in.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
            const std::streamsize got = in.gcount();
            if (got > 0) {
                out.write(buffer.data(), got);
                digest.update(buffer.data(), static_cast<std::size_t>(got));
                placed.size += static_cast<std::uintmax_t>(got);
            }
        }
        if (in.bad() || !out) {
            std::error_code remove_ec;
            fs::remove(tmp, remove_ec);
            return domain::DataError(domain::ErrorCode::IoError,
                                     "payload copy failed");
        }
        placed.sha256 = digest.hex_digest();
        placed.final_path = target;
        // Windows: an open handle (even read-only) blocks rename — the
        // streams must close before the atomic tmp → final move.
        out.close();
        in.close();
        fs::rename(tmp, target, ec);
        if (ec) {
            std::error_code remove_ec;
            fs::remove(tmp, remove_ec);
            return domain::DataError(
                domain::ErrorCode::IoError,
                "payload rename failed: " + ec.message());
        }
        placed.rel_path = pwb::project::path_to_u8(
            fs::weakly_canonical(target, ec).lexically_relative(
                pwb::project::project_dir_for(project_path)));
        if (ec || placed.rel_path.empty()) {
            placed.rel_path = pwb::project::path_to_u8(target);
        }
        return placed;
    }
}

}  // namespace pwb::data::detail
