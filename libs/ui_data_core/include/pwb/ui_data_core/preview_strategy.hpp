// preview_strategy.py port — the safe-summary preview decision tree.
//
// PreviewState (frozen dataclass) + preview_for_resource /
// preview_for_artifact over the UI-03 asset DTOs. File reads go through a
// ByteReader seam so the oracle can run without touching the host FS and
// the port stays testable headless.
#pragma once

#include "pwb/ui_data_core/asset_view.hpp"

#include <filesystem>
#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_data_core {

inline constexpr long long kMaxPreviewBytes = 8192;
inline constexpr int kMaxPreviewLines = 20;

// preview_strategy.py format sets.
const std::vector<std::string>& strategy_text_formats();         // txt xml
const std::vector<std::string>& strategy_table_formats();        // csv dat
const std::vector<std::string>& strategy_pdf_formats();          // pdf
const std::vector<std::string>& strategy_markdown_formats();     // md markdown htm html
const std::vector<std::string>& strategy_json_formats();         // json geojson
const std::vector<std::string>& strategy_audio_formats();        // wav mp3 flac ogg m4a
const std::vector<std::string>& strategy_professional_formats(); // las sgy segy xlsx xls ppt pptx wlp dfb
bool strategy_in(std::string_view fmt, const std::vector<std::string>& set);

struct PreviewState {
    std::string mode;
    std::string title;
    std::vector<std::string> lines;
    std::optional<std::string> image_path;
    std::optional<std::string> document_path;
    std::string warning;

    bool operator==(const PreviewState&) const = default;
};

// Byte source for _read_preview_lines: (path) → bytes read (≤ max_bytes) or
// an error tag. Default: real filesystem read of the first max_bytes bytes.
struct PreviewFileRead {
    bool ok = false;
    std::string bytes;             // ≤ max_bytes of file content
    std::string error_name;        // e.g. "FileNotFoundError" / "OSError"
};
using PreviewFileReader =
    std::function<PreviewFileRead(const std::filesystem::path&, long long max_bytes)>;

PreviewFileReader default_preview_file_reader();

// Filesystem-existence seam (Path(path).exists(), OSError → false).
using PreviewExistsFn = std::function<bool(const std::filesystem::path&)>;
bool default_preview_exists(const std::filesystem::path& path);

// _display_path(path, base_path): absolute → verbatim; else
// (base_path.parent / path).resolve().as_posix(), unresolved join on error.
std::string strategy_display_path(const std::string& path,
                                  const std::filesystem::path* base_path);

// _summary_lines(name, path, fmt, size): "文件:/格式:/路径:" (+大小 when
// size has a value; int(size) failure → str(size)).
std::vector<std::string> strategy_summary_lines(
    const std::string& name, const std::string& path, const std::string& fmt,
    const domain::Json* size);

// _read_preview_lines → (lines, warning); reader seam injected.
std::pair<std::vector<std::string>, std::string> strategy_read_preview_lines(
    const std::string& path, const PreviewFileReader& reader,
    long long max_bytes = kMaxPreviewBytes, int max_lines = kMaxPreviewLines);

PreviewState preview_for_resource(
    const ResourceItem& resource,
    const std::filesystem::path* base_path = nullptr,
    const PreviewFileReader& reader = default_preview_file_reader(),
    const PreviewExistsFn& exists_fn = default_preview_exists);

PreviewState preview_for_artifact(
    const ExportArtifact& artifact,
    const std::filesystem::path* base_path = nullptr);

}  // namespace pwb::ui_data_core
