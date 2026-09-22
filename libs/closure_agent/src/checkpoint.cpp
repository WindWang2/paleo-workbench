// checkpoint.cpp — sha256-enveloped atomic session checkpoints (durable
// write discipline: tmp file flush-to-disk, rename, directory flush).
#include <pwb/closure_agent/checkpoint.hpp>

#include <pwb/domain/sha256.hpp>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#else
#include <fcntl.h>
#include <unistd.h>
#endif

#include <atomic>
#include <chrono>
#include <fstream>
#include <sstream>

namespace pwb::closure_agent {

namespace {

std::string checksum_of(const std::string& raw) {
    pwb::domain::Sha256 digest;
    digest.update(raw.data(), raw.size());
    return digest.hex_digest();
}

// Returns false when durability could not be established (open or flush
// failed) — save() reports that as CheckpointStoreError, never success.
bool fsync_path(const std::filesystem::path& path, bool directory) {
#ifdef _WIN32
    // MSVC has no O_DIRECTORY: directory-handle fsync does not exist on
    // Windows (the interchange atomic_file precedent — best-effort skip).
    if (directory) return true;
    const int fd = _wopen(path.c_str(), _O_RDONLY | _O_BINARY);
    if (fd < 0) return false;
    const bool ok = _commit(fd) == 0;  // CRT flush-to-disk == fsync
    _close(fd);
    return ok;
#else
    const int flags = directory ? (O_RDONLY | O_DIRECTORY) : O_RDONLY;
    const int fd = open(path.c_str(), flags);
    if (fd < 0) return false;
    const bool ok = fsync(fd) == 0;
    close(fd);
    return ok;
#endif
}

}  // namespace

SessionCheckpointStore::SessionCheckpointStore(std::filesystem::path directory)
    : directory_(std::move(directory)) {}

CheckpointRecord SessionCheckpointStore::save(const std::string& session_id,
                                              Json payload) {
    std::error_code ec;
    std::filesystem::create_directories(directory_, ec);
    if (ec) {
        throw CheckpointStoreError("checkpoint directory unavailable: " +
                                   directory_.string() + " (" + ec.message() + ")");
    }
    // Monotonic per-process checkpoint numbering (also unique across
    // stores via the timestamp suffix).
    static std::atomic<long long> counter{0};
    const long long sequence = counter.fetch_add(1, std::memory_order_acq_rel) + 1;
    const long long written_at =
        std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch())
            .count();

    CheckpointRecord record;
    record.session_id = session_id;
    record.payload = std::move(payload);
    record.written_at_sec = written_at;
    record.checkpoint_id = "ckpt-" + std::to_string(written_at) + "-" +
                           std::to_string(sequence);
    record.checksum_sha256 = checksum_of(record.payload.dump());

    Json envelope = Json::object();
    envelope["schema_version"] = kCheckpointSchemaVersion;
    envelope["checkpoint_id"] = record.checkpoint_id;
    envelope["session_id"] = record.session_id;
    envelope["written_at"] = record.written_at_sec;
    envelope["checksum_sha256"] = record.checksum_sha256;
    envelope["payload"] = record.payload;
    const std::string body = envelope.dump(1);

    const std::filesystem::path final_path = directory_ / (session_id + ".json");
    const auto process_id = [] {
#ifdef _WIN32
        return static_cast<long>(_getpid());
#else
        return static_cast<long>(::getpid());
#endif
    };
    const std::filesystem::path tmp_path =
        final_path.parent_path() /
        ("." + final_path.filename().string() + ".tmp-" +
         std::to_string(process_id()) + "-" + std::to_string(sequence));
    {
        std::ofstream out(tmp_path, std::ios::binary | std::ios::trunc);
        if (!out) {
            throw CheckpointStoreError("checkpoint tmp file unopenable: " +
                                       tmp_path.string());
        }
        out.write(body.data(), static_cast<std::streamsize>(body.size()));
        out.flush();
        if (!out) {
            throw CheckpointStoreError("checkpoint tmp write failed: " +
                                       tmp_path.string());
        }
    }
    if (!fsync_path(tmp_path, false)) {
        std::filesystem::remove(tmp_path, ec);
        throw CheckpointStoreError("checkpoint tmp fsync failed: " +
                                   tmp_path.string());
    }
    std::filesystem::rename(tmp_path, final_path, ec);
    if (ec) {
        std::filesystem::remove(tmp_path, ec);
        throw CheckpointStoreError("checkpoint rename failed: " + ec.message());
    }
    if (!fsync_path(directory_, true)) {
        throw CheckpointStoreError("checkpoint directory fsync failed: " +
                                   directory_.string());
    }
    return record;
}

CheckpointRecord SessionCheckpointStore::parse_envelope(const std::string& raw) {
    Json envelope = Json(nullptr);
    try {
        envelope = Json::parse(raw);
    } catch (const std::exception& exc) {
        throw CheckpointCorruptError(std::string("checkpoint is corrupted: ") +
                                     exc.what());
    }
    if (!envelope.is_object()) {
        throw CheckpointCorruptError(
            "checkpoint is corrupted: envelope is not an object");
    }
    const auto schema = envelope.find("schema_version");
    if (schema == envelope.end() || !schema->is_string() ||
        schema->get<std::string>() != kCheckpointSchemaVersion) {
        throw CheckpointCorruptError(
            "checkpoint is corrupted: unknown schema version");
    }
    const auto payload = envelope.find("payload");
    if (payload == envelope.end() || !payload->is_object()) {
        throw CheckpointCorruptError("checkpoint is corrupted: payload missing");
    }
    const auto checksum = envelope.find("checksum_sha256");
    if (checksum == envelope.end() || !checksum->is_string()) {
        throw CheckpointCorruptError("checkpoint is corrupted: checksum missing");
    }
    const std::string actual = checksum_of(payload->dump());
    if (actual != checksum->get<std::string>()) {
        throw CheckpointCorruptError(
            "checkpoint is corrupted: checksum mismatch (expected " +
            checksum->get<std::string>() + ", computed " + actual + ")");
    }
    CheckpointRecord record;
    const auto session = envelope.find("session_id");
    record.session_id =
        session != envelope.end() && session->is_string()
            ? session->get<std::string>()
            : std::string();
    const auto id = envelope.find("checkpoint_id");
    record.checkpoint_id =
        id != envelope.end() && id->is_string() ? id->get<std::string>()
                                                : std::string();
    const auto written = envelope.find("written_at");
    record.written_at_sec =
        written != envelope.end() && written->is_number_integer()
            ? written->get<long long>()
            : 0;
    record.checksum_sha256 = checksum->get<std::string>();
    record.payload = *payload;
    return record;
}

CheckpointRecord SessionCheckpointStore::load(const std::string& session_id) const {
    const std::filesystem::path path = directory_ / (session_id + ".json");
    std::error_code ec;
    if (!std::filesystem::exists(path, ec)) {
        throw CheckpointStoreError("no checkpoint for session " + session_id);
    }
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        throw CheckpointStoreError("checkpoint unopenable: " + path.string());
    }
    std::ostringstream buffer;
    buffer << in.rdbuf();
    return parse_envelope(buffer.str());
}

}  // namespace pwb::closure_agent
