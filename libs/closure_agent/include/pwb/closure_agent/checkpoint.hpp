#pragma once

// Session checkpoint persistence — atomic JSON writes (tmp + fsync + rename)
// wrapped in a sha256 integrity envelope. A corrupted checkpoint is an
// explicit, inspectable failure: load() throws CheckpointCorruptError, it
// never silently degrades or fakes a resume (workflow_engine/store.hpp
// contract parity, session scope).

#include <pwb/domain/json.hpp>

#include <filesystem>
#include <stdexcept>
#include <string>
#include <vector>

namespace pwb::closure_agent {

using Json = pwb::domain::Json;

class CheckpointCorruptError : public std::runtime_error {
public:
    explicit CheckpointCorruptError(const std::string& message)
        : std::runtime_error(message) {}
};

class CheckpointStoreError : public std::runtime_error {
public:
    explicit CheckpointStoreError(const std::string& message)
        : std::runtime_error(message) {}
};

struct CheckpointRecord {
    std::string session_id;
    // "ckpt-<unix-seconds>-<process-global-seq>": unique per process,
    // time-ordered enough for listing; the payload checksum is the real
    // integrity anchor.
    std::string checkpoint_id;
    Json payload = Json::object();
    std::string checksum_sha256;  // over payload.dump()
    long long written_at_sec = 0;
};

// Envelope layout (stable schema): {"schema_version":"1.0","checkpoint_id",
// "session_id","written_at","checksum_sha256","payload"}.
inline constexpr const char* kCheckpointSchemaVersion = "1.0";

class SessionCheckpointStore {
public:
    // `directory` is created (recursive) on first save.
    explicit SessionCheckpointStore(std::filesystem::path directory);

    // Atomic durable write. The payload's canonical dump() is checksummed;
    // fsync covers the tmp file and the directory entry. Throws
    // CheckpointStoreError on any persistence failure (the session treats a
    // failed checkpoint write as fatal-for-the-turn, mirroring the workflow
    // engine's __checkpoint__ semantics — never an unguarded pass).
    CheckpointRecord save(const std::string& session_id, Json payload);

    // Load the newest record for a session; verifies the checksum BEFORE any
    // content is handed out. Missing session -> CheckpointStoreError;
    // checksum/parse mismatch -> CheckpointCorruptError.
    CheckpointRecord load(const std::string& session_id) const;

    // Checksum-only verification of a record read externally (tests, hosts).
    static CheckpointRecord parse_envelope(const std::string& raw);

    const std::filesystem::path& directory() const { return directory_; }

private:
    std::filesystem::path directory_;
};

}  // namespace pwb::closure_agent
