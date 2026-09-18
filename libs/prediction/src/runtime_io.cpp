#include "runtime_io.hpp"

#include <fstream>
#include <system_error>

namespace pwb::prediction::detail {

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
        path.parent_path() / (path.filename().string() + ".tmp");
    {
        std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
        if (!stream) {
            if (error != nullptr) *error = "cannot open temp file";
            return false;
        }
        stream.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
        if (!stream) {
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
