#include <pwb/closure_science/task_journal.hpp>

#include <pwb/catalog/checksum.hpp>
#include <pwb/domain/diagnostics.hpp>

#include <cstdio>
#include <fstream>

namespace pwb::closure_science {

namespace {
inline constexpr int kJournalSchemaVersion = 1;

[[nodiscard]] std::filesystem::path normalize(
    const std::filesystem::path& path) {
    std::error_code ec;
    auto normalized = std::filesystem::weakly_canonical(path, ec);
    if (ec) normalized = path;
    return normalized.lexically_normal();
}
}  // namespace

std::string PredictionTaskJournal::token_for_project_path(
    const std::filesystem::path& project_file) {
    return catalog::sha256_text(normalize(project_file).generic_string());
}

PredictionTaskJournal::PredictionTaskJournal(std::filesystem::path path,
                                             std::string project_token)
    : path_(std::move(path)), token_(std::move(project_token)) {}

domain::Result<std::vector<Json>> PredictionTaskJournal::load() const {
    const std::lock_guard<std::mutex> lock(mutex_);
    std::error_code ec;
    if (!std::filesystem::exists(path_, ec) || ec) {
        return std::vector<Json>{};
    }
    std::ifstream stream(path_, std::ios::binary);
    if (!stream.good()) {
        return domain::DataError(domain::ErrorCode::IoError,
                                 "cannot read task journal: " + path_.string());
    }
    std::string content((std::istreambuf_iterator<char>(stream)),
                        std::istreambuf_iterator<char>());
    Json parsed;
    try {
        parsed = Json::parse(content);
    } catch (const std::exception&) {
        return domain::DataError(
            domain::ErrorCode::CorruptJson,
            "task journal is corrupt: " + path_.string());
    }
    if (!parsed.is_object() ||
        !parsed.contains("schema_version") ||
        parsed["schema_version"] != kJournalSchemaVersion ||
        !parsed.contains("tasks") || !parsed["tasks"].is_array()) {
        return domain::DataError(
            domain::ErrorCode::CorruptJson,
            "task journal has an unknown shape: " + path_.string());
    }
    const std::string recorded_token =
        parsed.contains("project_token") &&
                parsed["project_token"].is_string()
            ? parsed["project_token"].get<std::string>()
            : std::string();
    if (recorded_token != token_) {
        return domain::DataError(
            domain::ErrorCode::ConflictBaseVersion,
            "task journal belongs to a different project (token mismatch)");
    }
    std::vector<Json> tasks;
    for (const auto& task : parsed["tasks"]) {
        tasks.push_back(task);
    }
    return tasks;
}

domain::DataError PredictionTaskJournal::record(Json task) {
    const std::lock_guard<std::mutex> lock(mutex_);
    Json parsed = Json::object();
    std::error_code ec;
    if (std::filesystem::exists(path_, ec) && !ec) {
        std::ifstream stream(path_, std::ios::binary);
        if (!stream.good()) {
            return domain::DataError(domain::ErrorCode::IoError,
                                     "cannot read task journal: " +
                                         path_.string());
        }
        std::string content((std::istreambuf_iterator<char>(stream)),
                            std::istreambuf_iterator<char>());
        try {
            parsed = Json::parse(content);
        } catch (const std::exception&) {
            return domain::DataError(
                domain::ErrorCode::CorruptJson,
                "task journal is corrupt: " + path_.string());
        }
    }
    if (!parsed.is_object() || !parsed.contains("tasks") ||
        !parsed["tasks"].is_array()) {
        parsed = Json{{"schema_version", kJournalSchemaVersion},
                      {"project_token", token_},
                      {"tasks", Json::array()}};
    }
    if (parsed.value("project_token", std::string()) != token_) {
        return domain::DataError(
            domain::ErrorCode::ConflictBaseVersion,
            "task journal belongs to a different project (token mismatch)");
    }
    parsed["tasks"].push_back(std::move(task));

    std::filesystem::create_directories(path_.parent_path(), ec);
    const std::filesystem::path tmp = path_.parent_path() /
                                      ("." + path_.filename().string() +
                                       ".tmp");
    {
        std::ofstream stream(tmp, std::ios::binary | std::ios::trunc);
        if (!stream.good()) {
            return domain::DataError(domain::ErrorCode::IoError,
                                     "cannot write " + tmp.string());
        }
        const std::string content =
            domain::dump_json_python_compatible(parsed);
        stream.write(content.data(),
                     static_cast<std::streamsize>(content.size()));
        stream.flush();
        if (!stream.good()) {
            stream.close();
            std::filesystem::remove(tmp);
            return domain::DataError(domain::ErrorCode::IoError,
                                     "short write to " + tmp.string());
        }
    }
    std::filesystem::rename(tmp, path_, ec);
    if (ec) {
        std::filesystem::remove(tmp);
        return domain::DataError(domain::ErrorCode::IoError,
                                 "cannot finalize " + path_.string());
    }
    return domain::DataError(domain::ErrorCode::Ok, "");
}

domain::DataError PredictionTaskJournal::clear() {
    const std::lock_guard<std::mutex> lock(mutex_);
    std::error_code ec;
    if (!std::filesystem::exists(path_, ec) || ec) {
        return domain::DataError(domain::ErrorCode::Ok, "");
    }
    std::filesystem::remove(path_, ec);
    if (ec) {
        return domain::DataError(domain::ErrorCode::IoError,
                                 "cannot remove task journal: " +
                                     path_.string());
    }
    return domain::DataError(domain::ErrorCode::Ok, "");
}

}  // namespace pwb::closure_science
