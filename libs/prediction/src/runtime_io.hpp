// Internal (not installed) file helpers shared by the prediction runtime
// translation units. Kept out of the public headers: the runtime never
// exposes file handles or std::filesystem types across the API boundary.
#pragma once

#include <filesystem>
#include <optional>
#include <string>
#include <string_view>

namespace pwb::prediction::detail {

// UTF-8 -> native path. std::filesystem::path(std::string) interprets bytes
// as the ANSI code page on Windows, so a UTF-8 path carried through JSON
// would be mis-decoded there; this helper converts explicitly.
std::filesystem::path path_from_utf8(std::string_view text);

// Reads the whole file or returns nullopt and fills `error`. Size is not
// capped here: callers that need a cap must check before/after (the ONNX
// model gate does).
std::optional<std::string> read_file_bytes(const std::filesystem::path& path,
                                           std::string* error);

// Writes atomically (unique temp file in the same directory + rename) so a
// crash never leaves a half-written descriptor next to a good raw output.
bool write_file_bytes(const std::filesystem::path& path,
                      std::string_view bytes, std::string* error);

}  // namespace pwb::prediction::detail
