#include "runtime_io.hpp"

#include <atomic>
#include <fstream>
#include <system_error>

#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <unistd.h>
#endif

namespace pwb::prediction::detail {
namespace {

unsigned long process_id() {
#if defined(_WIN32)
    return static_cast<unsigned long>(::GetCurrentProcessId());
#else
    return static_cast<unsigned long>(::getpid());
#endif
}

std::string temporary_suffix() {
    static std::atomic<unsigned long long> counter{0};
    return "." + std::to_string(process_id()) + "."
           + std::to_string(counter.fetch_add(1));
}

}  // namespace

std::filesystem::path path_from_utf8(std::string_view text) {
#if defined(_WIN32)
    if (text.empty()) return std::filesystem::path();
    const int size = ::MultiByteToWideChar(
        CP_UTF8, MB_ERR_INVALID_CHARS, text.data(),
        static_cast<int>(text.size()), nullptr, 0);
    if (size > 0) {
        std::wstring wide(static_cast<std::size_t>(size), L'\0');
        ::MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(),
                              static_cast<int>(text.size()), wide.data(),
                              size);
        return std::filesystem::path(wide);
    }
    // Not valid UTF-8: fall back to the native narrow interpretation rather
    // than dropping the path.
#endif
    return std::filesystem::path(std::string(text));
}

std::optional<std::string> read_file_bytes(const std::filesystem::path& path,
                                           std::string* error) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) {
        if (error != nullptr) *error = "cannot open file";
        return std::nullopt;
    }
    stream.seekg(0, std::ios::end);
    const std::streamoff size = stream.tellg();
    stream.seekg(0, std::ios::beg);
    if (size < 0) {
        if (error != nullptr) *error = "cannot stat file size";
        return std::nullopt;
    }
    std::string bytes(static_cast<std::size_t>(size), '\0');
    if (size > 0) {
        stream.read(bytes.data(), size);
        if (!stream) {
            if (error != nullptr) *error = "short read";
            return std::nullopt;
        }
    }
    return bytes;
}

bool write_file_bytes(const std::filesystem::path& path,
                      std::string_view bytes, std::string* error) {
    std::error_code ec;
    std::filesystem::create_directories(path.parent_path(), ec);
    if (ec) {
        if (error != nullptr) *error = "cannot create directory: " + ec.message();
        return false;
    }
    const std::filesystem::path temporary =
        path.parent_path() / (path.filename().string() + temporary_suffix()
                              + ".tmp");
    {
        std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
        if (!stream) {
            if (error != nullptr) *error = "cannot open temp file";
            return false;
        }
        stream.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
        if (!stream) {
            stream.close();
            std::filesystem::remove(temporary, ec);
            if (error != nullptr) *error = "short write";
            return false;
        }
    }
    std::filesystem::rename(temporary, path, ec);
    if (ec) {
        std::filesystem::remove(temporary, ec);
        if (error != nullptr) *error = "cannot rename temp file: " + ec.message();
        return false;
    }
    return true;
}

}  // namespace pwb::prediction::detail
