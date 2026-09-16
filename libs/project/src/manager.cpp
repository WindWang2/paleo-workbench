#include "pwb/project/manager.hpp"

#include "pwb/domain/sha256.hpp"
#include "pwb/project/schema.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <fstream>
#include <sstream>

namespace pwb::project {

using pwb::domain::DataError;
using pwb::domain::Diagnostic;
using pwb::domain::ErrorCode;
using pwb::domain::Json;
using pwb::domain::Result;

namespace {

std::optional<std::string> read_text(const fs::path& file) {
    std::ifstream stream(file, std::ios::binary);
    if (!stream) return std::nullopt;
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    if (stream.bad()) return std::nullopt;
    return buffer.str();
}

bool file_exists(const fs::path& file) {
    std::error_code ec;
    return fs::is_regular_file(file, ec);
}

std::string now_or_fixed(const std::optional<std::string>& fixed) {
    return fixed.has_value() ? *fixed : domain::now_iso8601();
}

}  // namespace

fs::path project_backup_path(const fs::path& project_path) {
    return project_path.parent_path() /
           (project_path.filename().generic_string() + ".bak");
}

ProjectManager::ProjectManager(fs::path project_path)
    : project_path_(std::move(project_path)) {}

void ProjectManager::cleanup_stale_temps() {
    const std::string prefix = "." + project_path_.filename().generic_string();
    std::error_code ec;
    fs::path parent = project_path_.parent_path();
    if (!fs::is_directory(parent, ec)) return;
    for (const auto& entry : fs::directory_iterator(parent, ec)) {
        const std::string name = entry.path().filename().generic_string();
        if (!entry.is_regular_file(ec)) continue;
        if (name.rfind(prefix, 0) == 0 &&
            name.size() > 4 && name.compare(name.size() - 4, 4, ".tmp") == 0) {
            std::error_code remove_ec;
            fs::remove(entry.path(), remove_ec);
        }
    }
}

std::optional<std::string> ProjectManager::file_sha256(const fs::path& file) {
    return domain::Sha256::of_file(file);
}

Result<LoadedProject> ProjectManager::load_primary() {
    std::error_code ec;
    const bool exists = fs::is_regular_file(project_path_, ec);
    if (!exists) {
        if (ec) {
            // Transient/stat failure class — never fall back to .bak (#1229).
            return DataError(ErrorCode::IoError,
                             "project file temporarily unreadable: " + ec.message());
        }
        return DataError(ErrorCode::NotFound, "project file not found");
    }
    auto text = read_text(project_path_);
    if (!text) {
        return DataError(ErrorCode::IoError,
                         "project file exists but cannot be read (locked by "
                         "AV/sync/another instance?) — .bak fallback refused");
    }
    domain::DiagnosticList diagnostics;
    auto parsed = ProjectDocument::parse(*text, diagnostics);
    if (!parsed.is_ok()) {
        return DataError(ErrorCode::CorruptJson,
                         parsed.error().message);
    }
    LoadedProject loaded;
    loaded.document = std::move(parsed.value());
    loaded.document.diagnostics() = std::move(diagnostics);
    disk_sha256_ = domain::Sha256::of_bytes(*text);
    return loaded;
}

Result<LoadedProject> ProjectManager::recover_from_backup(
    const std::string& failure_class) {
    const fs::path backup = project_backup_path(project_path_);
    if (!file_exists(backup)) {
        return DataError(failure_class == "missing"
                             ? ErrorCode::NotFound
                             : ErrorCode::CorruptJson,
                         "primary project unusable and no .bak exists");
    }
    auto text = read_text(backup);
    if (!text) {
        return DataError(ErrorCode::CorruptJson, "backup unreadable");
    }
    domain::DiagnosticList diagnostics;
    auto parsed = ProjectDocument::parse(*text, diagnostics);
    if (!parsed.is_ok()) {
        // Backup ALSO invalid → fail honestly, main untouched.
        return DataError(ErrorCode::CorruptJson,
                         "backup also invalid: " + parsed.error().message);
    }

    // Quarantine the corrupt main (forensics), then restore the backup.
    std::optional<std::string> quarantine;
    if (file_exists(project_path_)) {
        const std::string stamp = now_or_fixed(fixed_clock_);
        std::string clean;
        for (char c : stamp) {
            if (c != ':' && c != '-') clean.push_back(c);
        }
        fs::path isolated = project_path_.parent_path() /
                            (project_path_.filename().generic_string() +
                             ".corrupt-" + clean);
        std::error_code ec;
        fs::rename(project_path_, isolated, ec);
        if (!ec) quarantine = pwb::project::path_to_u8(isolated);
    }
    std::error_code restore_ec;
    // os.replace semantics (manager.py): the .bak MOVES onto the main
    // path — the backup is consumed by the recovery.
    fs::rename(backup, project_path_, restore_ec);
    if (restore_ec) {
        fs::copy_file(backup, project_path_,
                      fs::copy_options::overwrite_existing, restore_ec);
    }
    if (restore_ec) {
        return DataError(ErrorCode::IoError,
                         "backup restore failed: " + restore_ec.message());
    }
    fsync_directory(project_path_.parent_path());

    LoadedProject loaded;
    loaded.document = std::move(parsed.value());
    loaded.document.diagnostics() = std::move(diagnostics);
    loaded.recovered = true;
    loaded.recovery_source = failure_class;
    loaded.quarantine = quarantine;
    // Persisted on the NEXT save (manager.py: model-only for now).
    Json record = Json::object();
    record["source"] = failure_class;
    record["recovered_at"] = now_or_fixed(fixed_clock_);
    record["error"] = failure_class == "missing" ? "FileNotFoundError"
                                                 : "ValidationError";
    record["quarantined"] = quarantine.has_value() ? *quarantine : nullptr;
    loaded.document.root()["meta"]["last_recovery"] = std::move(record);
    disk_sha256_ = domain::Sha256::of_bytes(*text);
    return loaded;
}

Result<LoadedProject> ProjectManager::load() {
    cleanup_stale_temps();
    auto primary = load_primary();
    if (primary.is_ok()) return primary;
    const ErrorCode code = primary.error().code;
    if (code == ErrorCode::NotFound) {
        // Interrupted-save window: main never landed, .bak holds the last
        // revision. Restore WITHOUT quarantine (the main is simply absent).
        return recover_from_backup("backup-interrupted-save");
    }
    if (code == ErrorCode::CorruptJson) {
        return recover_from_backup("backup-corrupt-main");
    }
    return primary;  // transient/unreadable → honest failure, no fallback
}

void make_sections_portable(Json& payload, const fs::path& project_path) {
    // resources
    if (payload.contains("resources") && payload["resources"].is_array()) {
        for (auto& resource : payload["resources"]) {
            if (!resource.is_object()) continue;
            if (!resource.contains("path") || !resource["path"].is_string())
                continue;
            const auto relativized = relativize_path(
                pwb::project::path_from_u8(resource["path"].get<std::string>()), project_path);
            resource["path"] = relativized.stored;
            resource["external"] = relativized.external;
        }
    }
    // export_artifacts
    if (payload.contains("export_artifacts") &&
        payload["export_artifacts"].is_array()) {
        for (auto& artifact : payload["export_artifacts"]) {
            if (!artifact.is_object()) continue;
            if (!artifact.contains("output_path") ||
                !artifact["output_path"].is_string())
                continue;
            const auto relativized = relativize_path(
                pwb::project::path_from_u8(artifact["output_path"].get<std::string>()),
                project_path);
            artifact["output_path"] = relativized.stored;
        }
    }
    // factor_map_tasks.grid_artifact_path
    if (payload.contains("factor_map_tasks") &&
        payload["factor_map_tasks"].is_array()) {
        for (auto& task : payload["factor_map_tasks"]) {
            if (!task.is_object()) continue;
            if (!task.contains("grid_artifact_path") ||
                !task["grid_artifact_path"].is_string())
                continue;
            const auto relativized = relativize_path(
                pwb::project::path_from_u8(task["grid_artifact_path"].get<std::string>()),
                project_path);
            task["grid_artifact_path"] = relativized.stored;
        }
    }
    // horizon_interpretations.artifact_path
    if (payload.contains("horizon_interpretations") &&
        payload["horizon_interpretations"].is_array()) {
        for (auto& item : payload["horizon_interpretations"]) {
            if (!item.is_object()) continue;
            if (!item.contains("artifact_path") ||
                !item["artifact_path"].is_string())
                continue;
            const auto relativized = relativize_path(
                pwb::project::path_from_u8(item["artifact_path"].get<std::string>()),
                project_path);
            item["artifact_path"] = relativized.stored;
        }
    }
    // paleomap_documents[].reference_layers[].source_path
    if (payload.contains("paleomap_documents") &&
        payload["paleomap_documents"].is_array()) {
        for (auto& doc : payload["paleomap_documents"]) {
            if (!doc.is_object() || !doc.contains("reference_layers") ||
                !doc["reference_layers"].is_array())
                continue;
            for (auto& layer : doc["reference_layers"]) {
                if (!layer.is_object()) continue;
                if (!layer.contains("source_path") ||
                    !layer["source_path"].is_string())
                    continue;
                const auto relativized = relativize_path(
                    pwb::project::path_from_u8(layer["source_path"].get<std::string>()),
                    project_path);
                layer["source_path"] = relativized.stored;
                layer["external"] = relativized.external;
            }
        }
    }
}

Json ProjectManager::build_portable_payload(
    const ProjectDocument& document) const {
    Json payload = document.root();
    make_sections_portable(payload, project_path_);
    return payload;
}

Result<SaveStats> ProjectManager::write_payload(const std::string& payload) {
    std::error_code ec;
    fs::create_directories(project_path_.parent_path(), ec);
    const fs::path backup = project_backup_path(project_path_);

    // tmp + fsync (name pattern `.<project>.*.tmp` so cleanup_stale_temps
    // — which globs that exact shape — always finds our leftovers)
    static std::atomic<unsigned> sequence{0};
    fs::path tmp = project_path_.parent_path() /
                   ("." + project_path_.filename().generic_string() +
                    "." +
                    std::to_string(
                        std::chrono::steady_clock::now()
                            .time_since_epoch()
                            .count()) +
                    "." + std::to_string(sequence.fetch_add(1)) + ".tmp");
    {
        std::ofstream stream(tmp, std::ios::binary | std::ios::trunc);
        if (!stream) {
            return DataError(ErrorCode::IoError,
                             "cannot create temp file for save");
        }
        stream.write(payload.data(),
                     static_cast<std::streamsize>(payload.size()));
        stream.flush();
        if (!stream) {
            std::error_code remove_ec;
            fs::remove(tmp, remove_ec);
            return DataError(ErrorCode::IoError, "temp file write failed");
        }
    }

    // main → .bak, then tmp → main (manager.py _write_payload order).
    bool old_moved = false;
    if (file_exists(project_path_)) {
        std::error_code rename_ec;
        fs::rename(project_path_, backup, rename_ec);
        if (rename_ec) {
            std::error_code remove_ec;
            fs::remove(tmp, remove_ec);
            return DataError(ErrorCode::IoError,
                             "cannot move current project to .bak: " +
                                 rename_ec.message());
        }
        old_moved = true;
    }
    std::error_code replace_ec;
    fs::rename(tmp, project_path_, replace_ec);
    if (replace_ec) {
        std::error_code remove_ec;
        fs::remove(tmp, remove_ec);
        if (old_moved && !file_exists(project_path_) &&
            file_exists(backup)) {
            std::error_code restore_ec;
            fs::rename(backup, project_path_, restore_ec);
        }
        return DataError(ErrorCode::IoError,
                         "cannot replace project file: " +
                             replace_ec.message());
    }
    fsync_directory(project_path_.parent_path());

    SaveStats stats;
    stats.wrote = true;
    stats.bytes_written = payload.size();
    return stats;
}

Result<SaveStats> ProjectManager::save(ProjectDocument& document) {
    if (document.read_only()) {
        return DataError(ErrorCode::FutureSchema,
                         "document is read-only (future schema) — save refused");
    }
    // Stale-write guard (#411/#1229): content hash change → refuse.
    if (disk_sha256_.has_value()) {
        const auto current = file_sha256(project_path_);
        if (current.has_value() && *current != *disk_sha256_) {
            return DataError(
                ErrorCode::ConflictBaseVersion,
                "project file changed on disk since this session loaded it "
                "(stale write refused)");
        }
    }

    const std::string updated_at = now_or_fixed(fixed_clock_);
    Json payload = build_portable_payload(document);
    payload["meta"]["updated_at"] = updated_at;
    payload["meta"]["project_root"] = ".";
    const std::string text =
        pwb::domain::dump_json_compact_header(payload);

    auto stats = write_payload(text);
    if (!stats.is_ok()) return stats;
    stats.value().updated_at = updated_at;
    document.touch_updated_at(updated_at);
    disk_sha256_ = domain::Sha256::of_bytes(text);
    return stats;
}

std::vector<ResolvedResource> resolve_resource_paths(
    const ProjectDocument& document, const fs::path& project_path) {
    std::vector<ResolvedResource> out;
    const Json* resources = document.find_section("resources");
    if (resources == nullptr || !resources->is_array()) return out;
    for (const auto& resource : *resources) {
        if (!resource.is_object()) continue;
        ResolvedResource entry;
        entry.id = resource.value("id", "");
        entry.stored = resource.value("path", "");
        entry.external = resource.value("external", false);
        if (entry.stored.empty()) {
            entry.error = "empty_path";
        } else {
            auto resolved = resolve_project_path(entry.stored, project_path);
            if (resolved.is_ok()) {
                entry.resolved = resolved.value();
                std::error_code ec;
                entry.exists = fs::is_regular_file(pwb::project::path_from_u8(entry.resolved), ec);
                if (!entry.exists) {
                    entry.error = "missing_file";
                }
            } else {
                entry.error = pwb::domain::to_string(resolved.error().code);
            }
        }
        out.push_back(std::move(entry));
    }
    return out;
}

}  // namespace pwb::project
