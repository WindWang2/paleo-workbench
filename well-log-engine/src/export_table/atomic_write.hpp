#pragma once

// Atomic file-write helper (table-and-export.md §10). Writes producer output to
// a temp file beside the target, then std::filesystem::rename onto the target
// (atomic on POSIX). On any failure the temp file is removed. The producer
// streams into an ostream so a million-row table never builds one giant string
// in memory (constant-memory path, §5.2 / §10). Returns the path written or an
// Error carrying path + stage (never raw data).

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <string>
#include <system_error>

#include <welllog/core/result.hpp>

#if defined(_WIN32)
#include <process.h>
#else
#include <unistd.h>
#endif

namespace welllog {
namespace export_table {

// A producer streams the file body into `out`. Returns true on success, false
// to abort (the helper then removes the temp file and returns an error).
using StreamProducer = std::function<bool(std::ostream &out)>;

// Writes `producer`'s output to `target` atomically. `stage` labels the
// failure stage on the returned Error (e.g. "csv-write", "xml-rename").
[[nodiscard]] inline Result<std::filesystem::path>
write_file_atomic(const std::filesystem::path &target,
                  const StreamProducer &producer, std::string_view stage) {
  (void)stage; // labels the failure stage for caller-side logging (no Error
               // field carries it today; reserved).
  namespace fs = std::filesystem;
  std::error_code ec;
  const auto parent = target.parent_path();
  const auto dir = parent.empty() ? fs::current_path(ec) : parent;
  if (ec) {
    return Error{
        .code = ErrorCode::invalid_manifest,
        .severity = Severity::error,
        .entity_id = std::nullopt,
        .message = MessageKey::manifest_invalid,
        .arguments = {},
    };
  }
  // Temp file: target + ".<pid>.tmp" in the same directory (same filesystem →
  // rename is atomic).
  auto temp = target;
  temp += ".";
  temp += std::to_string(static_cast<std::uint64_t>(
#if defined(_WIN32)
      ::_getpid()
#else
      ::getpid()
#endif
      ));
  temp += ".tmp";
  {
    std::ofstream out(temp, std::ios::binary | std::ios::trunc);
    if (!out) {
      fs::remove(temp, ec);
      return Error{
          .code = ErrorCode::invalid_manifest,
          .severity = Severity::error,
          .entity_id = std::nullopt,
          .message = MessageKey::manifest_invalid,
          .arguments = {},
      };
    }
    try {
      if (!producer(out)) {
        out.close();
        fs::remove(temp, ec);
        return Error{
            .code = ErrorCode::invalid_manifest,
            .severity = Severity::error,
            .entity_id = std::nullopt,
            .message = MessageKey::manifest_invalid,
            .arguments = {},
        };
      }
    } catch (...) {
      out.close();
      fs::remove(temp, ec);
      return Error{
          .code = ErrorCode::resource_exhausted,
          .severity = Severity::error,
          .entity_id = std::nullopt,
          .message = MessageKey::resource_exhausted,
          .arguments = {},
      };
    }
    out.flush();
    if (!out) {
      fs::remove(temp, ec);
      return Error{
          .code = ErrorCode::invalid_manifest,
          .severity = Severity::error,
          .entity_id = std::nullopt,
          .message = MessageKey::manifest_invalid,
          .arguments = {},
      };
    }
  }
  fs::rename(temp, target, ec);
  if (ec) {
    fs::remove(temp, ec);
    return Error{
        .code = ErrorCode::invalid_manifest,
        .severity = Severity::error,
        .entity_id = std::nullopt,
        .message = MessageKey::manifest_invalid,
        .arguments = {},
    };
  }
  return target;
}

} // namespace export_table
} // namespace welllog
