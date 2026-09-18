// save_session_as (conv-26) — the Save As flow over one writable session:
// refuse an occupied target, stage the reversible artifact relocation,
// rebase the document's owned artifact paths, write the project file at
// the target through a fresh manager (portable payload relativized
// against the NEW directory), then commit or roll back the staging. On
// success the OLD session is spent — the caller opens a new
// WritableSession at the returned path (close/reopen semantics).
#pragma once

#include "pwb/data/session.hpp"

#include <filesystem>

namespace pwb::data {

namespace fs = std::filesystem;

struct SaveAsOutcome {
    fs::path new_project_file;
    int rebased_paths = 0;
    bool artifacts_relocated = false;
};

domain::Result<SaveAsOutcome> save_session_as(WritableSession& session,
                                              const fs::path& target_file);

}  // namespace pwb::data
