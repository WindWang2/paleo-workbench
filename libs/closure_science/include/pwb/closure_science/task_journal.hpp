// pwb::closure_science — prediction task journal (restore + identity).
//
// The prediction pages keep their displayed tasks across sessions in the
// Python product via the project document. The native binding persists the
// materialized tasks in a journal file beside the project's artifacts tree
// with an identity token derived from the project file path:
//   * restore: on reopen the binding reads the journal and re-displays the
//     recorded tasks (the catalog run + version remain the provenance);
//   * late-arrival guard: completions carry the project token they were
//     started under. After a rebind to a different project the old
//     project's completion is rejected — a stale worker cannot pollute the
//     new project's journal.
// Writes are atomic (temp + rename) and token-checked (IdentityMismatch).
#pragma once

#include <pwb/domain/errors.hpp>
#include <pwb/domain/json.hpp>

#include <filesystem>
#include <mutex>
#include <string>
#include <vector>

namespace pwb::closure_science {

using domain::Json;

class PredictionTaskJournal {
public:
    // token = sha256 of the lexically-normalized project file path.
    [[nodiscard]] static std::string token_for_project_path(
        const std::filesystem::path& project_file);

    PredictionTaskJournal(std::filesystem::path path,
                          std::string project_token);

    [[nodiscard]] const std::string& token() const { return token_; }

    // Recorded tasks in insertion order (empty when absent/corrupt-empty).
    // A corrupt journal is surfaced as an error, never silently reset.
    [[nodiscard]] domain::Result<std::vector<Json>> load() const;

    // Appends one task (atomic rewrite; token mismatch is an error).
    [[nodiscard]] domain::DataError record(Json task);

    // Drops all recorded tasks (fresh project state, e.g. after the user
    // clears tasks); token-checked like record().
    [[nodiscard]] domain::DataError clear();

private:
    std::filesystem::path path_;
    std::string token_;
    mutable std::mutex mutex_;
};

}  // namespace pwb::closure_science
