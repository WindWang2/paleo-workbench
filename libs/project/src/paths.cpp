#include "pwb/project/paths.hpp"

#if defined(_WIN32)
#include <windows.h>
#else
#include <fcntl.h>
#include <unistd.h>
#endif

#include <cstdlib>
#include <system_error>

namespace pwb::project {

namespace fs = std::filesystem;
using pwb::domain::DataError;
using pwb::domain::ErrorCode;
using pwb::domain::Result;

fs::path path_from_u8(std::string_view utf8) {
    if (utf8.empty()) return fs::path();
#if defined(_WIN32)
    const int wide_length = MultiByteToWideChar(
        CP_UTF8, MB_ERR_INVALID_CHARS, utf8.data(),
        static_cast<int>(utf8.size()), nullptr, 0);
    if (wide_length <= 0) return fs::path(utf8.begin(), utf8.end());
    std::wstring wide(static_cast<std::size_t>(wide_length), L'\0');
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, utf8.data(),
                        static_cast<int>(utf8.size()), wide.data(),
                        wide_length);
    return fs::path(std::move(wide));
#else
    // POSIX paths are byte strings; valid UTF-8 maps 1:1.
    return fs::path(std::string(utf8));
#endif
}

std::string path_to_u8(const fs::path& path) {
#if defined(_WIN32)
    const std::wstring wide = path.generic_wstring();
    if (wide.empty()) return std::string();
    const int utf8_length = WideCharToMultiByte(
        CP_UTF8, WC_ERR_INVALID_CHARS, wide.c_str(),
        static_cast<int>(wide.size()), nullptr, 0, nullptr, nullptr);
    if (utf8_length <= 0) return std::string();
    std::string utf8(static_cast<std::size_t>(utf8_length), '\0');
    WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide.c_str(),
                        static_cast<int>(wide.size()), utf8.data(),
                        utf8_length, nullptr, nullptr);
    return utf8;
#else
    return path.generic_string();
#endif
}

namespace {
std::string to_posix(const fs::path& path) { return path_to_u8(path); }
}  // namespace

fs::path artifact_dir_for(const fs::path& project_path) {
    std::string name = project_path.filename().generic_string();
    constexpr std::string_view suffix = ".paleo.json";
    if (name.size() >= suffix.size() &&
        name.compare(name.size() - suffix.size(), suffix.size(), suffix) == 0) {
        name.resize(name.size() - suffix.size());
    }
    fs::path base = project_path.parent_path();
    if (name.empty()) return base / "artifacts";
    return base / (name + ".artifacts");
}

fs::path project_dir_for(const fs::path& project_path) {
    std::error_code ec;
    fs::path resolved = fs::weakly_canonical(project_path, ec);
    if (ec) resolved = fs::absolute(project_path, ec);
    return resolved.parent_path();
}

fs::path catalog_dir_for(const fs::path& project_path) {
    return artifact_dir_for(project_path) / "metadata";
}

fs::path catalog_sqlite_for(const fs::path& project_path) {
    return catalog_dir_for(project_path) / "catalog.sqlite";
}

fs::path catalog_manifest_for(const fs::path& project_path) {
    return catalog_dir_for(project_path) / "catalog.json";
}

Relativized relativize_path(const fs::path& path,
                            const fs::path& project_path) {
    const fs::path project_dir = project_dir_for(project_path);
    std::error_code ec;
    fs::path resolved =
        path.is_absolute()
            ? fs::weakly_canonical(path, ec)
            : fs::weakly_canonical(project_dir / path, ec);
    if (ec) resolved = fs::absolute(path, ec);
    if (!project_dir.empty()) {
        const std::string relative =
            path_to_u8(resolved.lexically_relative(project_dir));
        if (!relative.empty() && relative != "." &&
            relative.rfind("..", 0) != 0) {
            return {relative, false};
        }
    }
    return {to_posix(resolved), true};
}

Result<std::string> resolve_project_path(const std::string& stored,
                                         const fs::path& project_path) {
    const auto first = stored.find_first_not_of(" \t\r\n");
    const auto last = stored.find_last_not_of(" \t\r\n");
    if (first == std::string::npos) {
        return DataError(ErrorCode::PathEscape,
                         "Empty path cannot be resolved against a project");
    }
    std::string trimmed = stored.substr(first, last - first + 1);
    if (trimmed == "~" || trimmed.rfind("~/", 0) == 0 ||
        trimmed.rfind("~\\", 0) == 0) {
#if defined(_WIN32)
        // Wide environment lookup → UTF-8 prefix (narrow getenv would be
        // ANSI-codepage bytes, not the UTF-8 the JSON layer expects).
        const wchar_t* profile = _wgetenv(L"USERPROFILE");
        if (profile != nullptr) {
            const std::string prefix =
                path_to_u8(fs::path(profile).lexically_normal());
            trimmed = prefix + trimmed.substr(1);
        }
#else
        const char* home = std::getenv("HOME");
        if (home != nullptr) {
            trimmed = path_to_u8(fs::path(home).lexically_normal()) +
                      trimmed.substr(1);
        }
#endif
    }
    fs::path candidate = path_from_u8(trimmed);
    std::error_code ec;
    if (candidate.is_absolute()) {
        return to_posix(fs::weakly_canonical(candidate, ec));
    }
    const fs::path project_dir = project_dir_for(project_path);
    fs::path resolved = fs::weakly_canonical(project_dir / candidate, ec);
    if (ec) resolved = (project_dir / candidate).lexically_normal();
    if (!is_within_directory(resolved, project_dir)) {
        return DataError(
            ErrorCode::PathEscape,
            "Relative path escapes project directory: '" + trimmed + "'");
    }
    return to_posix(resolved);
}

void fsync_directory(const fs::path& directory) {
#if defined(_WIN32)
    HANDLE handle = CreateFileW(
        directory.wstring().c_str(), GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
        OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, nullptr);
    if (handle == INVALID_HANDLE_VALUE) return;
    FlushFileBuffers(handle);
    CloseHandle(handle);
#else
    const int fd = ::open(directory.c_str(), O_RDONLY | O_DIRECTORY);
    if (fd < 0) return;
    ::fsync(fd);
    ::close(fd);
#endif
}

bool is_within_directory(const fs::path& path, const fs::path& directory) {
    const fs::path normalized = path.lexically_normal();
    const fs::path base = directory.lexically_normal();
    auto it = normalized.begin();
    for (const auto& part : base) {
        if (it == normalized.end() || *it != part) return false;
        ++it;
    }
    return true;
}

}  // namespace pwb::project
