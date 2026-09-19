// preview_strategy.py port — see preview_strategy.hpp.

#include "pwb/ui_data_core/preview_strategy.hpp"

#include "pwb/ui_data_core/json_util.hpp"

#include <algorithm>
#include <cctype>
#include <fstream>

namespace pwb::ui_data_core {

namespace {
const std::vector<std::string>& make_set(std::initializer_list<const char*> v) {
    static const std::vector<std::string> storage = [&v] {
        std::vector<std::string> out;
        for (const char* s : v) out.emplace_back(s);
        return out;
    }();
    return storage;
}
}  // namespace

const std::vector<std::string>& strategy_text_formats() {
    static const auto& s = make_set({"txt", "xml"});
    return s;
}
const std::vector<std::string>& strategy_table_formats() {
    static const auto& s = make_set({"csv", "dat"});
    return s;
}
const std::vector<std::string>& strategy_pdf_formats() {
    static const auto& s = make_set({"pdf"});
    return s;
}
const std::vector<std::string>& strategy_markdown_formats() {
    static const auto& s = make_set({"md", "markdown", "htm", "html"});
    return s;
}
const std::vector<std::string>& strategy_json_formats() {
    static const auto& s = make_set({"json", "geojson"});
    return s;
}
const std::vector<std::string>& strategy_audio_formats() {
    static const auto& s = make_set({"wav", "mp3", "flac", "ogg", "m4a"});
    return s;
}
const std::vector<std::string>& strategy_professional_formats() {
    static const auto& s = make_set(
        {"las", "sgy", "segy", "xlsx", "xls", "ppt", "pptx", "wlp", "dfb"});
    return s;
}
bool strategy_in(std::string_view fmt, const std::vector<std::string>& set) {
    return std::find(set.begin(), set.end(), fmt) != set.end();
}

// ---------------------------------------------------------------------------
// seams
// ---------------------------------------------------------------------------

bool default_preview_exists(const std::filesystem::path& path) {
    std::error_code ec;
    const bool exists = std::filesystem::exists(path, ec);
    return !ec && exists;
}

PreviewFileReader default_preview_file_reader() {
    return [](const std::filesystem::path& path,
              long long max_bytes) -> PreviewFileRead {
        PreviewFileRead out;
        errno = 0;
        std::ifstream stream(path, std::ios::binary);
        if (!stream) {
            // exc.__class__.__name__ fidelity for the common failures.
            switch (errno) {
                case ENOENT: out.error_name = "FileNotFoundError"; break;
                case EISDIR: out.error_name = "IsADirectoryError"; break;
                case EACCES: out.error_name = "PermissionError"; break;
                default: out.error_name = "OSError"; break;
            }
            return out;
        }
        out.bytes.resize(static_cast<std::size_t>(std::max<long long>(max_bytes, 0)));
        stream.read(out.bytes.data(), static_cast<std::streamsize>(out.bytes.size()));
        out.bytes.resize(static_cast<std::size_t>(stream.gcount()));
        if (stream.bad()) {
            out.bytes.clear();
            out.error_name = "OSError";
            return out;
        }
        out.ok = true;
        return out;
    };
}

// ---------------------------------------------------------------------------
// _display_path / _summary_lines
// ---------------------------------------------------------------------------

std::string strategy_display_path(const std::string& path,
                                  const std::filesystem::path* base_path) {
    const std::filesystem::path candidate(path);
    if (candidate.is_absolute() || base_path == nullptr) {
        return path;
    }
    const std::filesystem::path joined = base_path->parent_path() / candidate;
    std::error_code ec;
    const std::filesystem::path resolved = std::filesystem::weakly_canonical(joined, ec);
    if (ec) {
        return joined.generic_string();
    }
    return resolved.generic_string();
}

std::vector<std::string> strategy_summary_lines(
    const std::string& name, const std::string& path, const std::string& fmt,
    const domain::Json* size) {
    std::vector<std::string> lines = {
        "文件: " + name,
        "格式: " + fmt,
        "路径: " + path,
    };
    if (size != nullptr && !size->is_null()) {
        std::string formatted;
        if (size->is_boolean()) {
            formatted = format_size(size->get<bool>() ? 1 : 0);
        } else if (size->is_number_integer() || size->is_number_unsigned()) {
            formatted = format_size(size->get<long long>());
        } else if (size->is_number_float()) {
            // Python int(size) truncates floats; ValueError/TypeError falls
            // through to str(size).
            formatted = format_size(static_cast<long long>(size->get<double>()));
        } else if (size->is_string()) {
            // int(size): Python accepts "123"/" 12 " but rejects "abc"/"1.5".
            try {
                const std::string& s = size->get<std::string>();
                std::size_t pos = 0;
                const long long v = std::stoll(s, &pos);
                while (pos < s.size() && std::isspace(static_cast<unsigned char>(s[pos]))) {
                    ++pos;
                }
                if (pos != s.size()) {
                    formatted = s;
                } else {
                    formatted = format_size(v);
                }
            } catch (...) {
                formatted = size->get<std::string>();
            }
        } else {
            formatted = json_str(*size);
        }
        lines.push_back("大小: " + formatted);
    }
    return lines;
}

// ---------------------------------------------------------------------------
// _read_preview_lines
// ---------------------------------------------------------------------------

std::pair<std::vector<std::string>, std::string> strategy_read_preview_lines(
    const std::string& path, const PreviewFileReader& reader,
    long long max_bytes, int max_lines) {
    const PreviewFileRead read = reader(std::filesystem::path(path), max_bytes);
    if (!read.ok) {
        return {{}, std::filesystem::path(path).filename().generic_string() + ": " +
                        read.error_name};
    }
    // _looks_binary: NUL byte anywhere in the first max_bytes.
    if (read.bytes.find('\0') != std::string::npos) {
        return {{}, "内容看起来是二进制，使用安全摘要预览"};
    }
    // utf-8 decode with errors="replace" — U+FFFD substitution.
    std::string text;
    text.reserve(read.bytes.size());
    for (std::size_t i = 0; i < read.bytes.size();) {
        const unsigned char c = static_cast<unsigned char>(read.bytes[i]);
        std::size_t len = 0;
        if (c < 0x80) len = 1;
        else if ((c >> 5) == 0x6) len = 2;
        else if ((c >> 4) == 0xE) len = 3;
        else if ((c >> 3) == 0x1E) len = 4;
        bool valid = len > 0 && i + len <= read.bytes.size();
        if (valid) {
            for (std::size_t k = 1; k < len; ++k) {
                const unsigned char cc =
                    static_cast<unsigned char>(read.bytes[i + k]);
                if ((cc >> 6) != 0x2) {
                    valid = false;
                    break;
                }
            }
            if (valid && len == 2) {
                const unsigned cp = ((c & 0x1F) << 6) |
                                    (static_cast<unsigned char>(read.bytes[i + 1]) & 0x3F);
                valid = cp >= 0x80;
            } else if (valid && len == 3) {
                const unsigned cp =
                    ((c & 0x0F) << 12) |
                    ((static_cast<unsigned char>(read.bytes[i + 1]) & 0x3F) << 6) |
                    (static_cast<unsigned char>(read.bytes[i + 2]) & 0x3F);
                valid = cp >= 0x800 && !(cp >= 0xD800 && cp <= 0xDFFF);
            } else if (valid && len == 4) {
                const unsigned cp =
                    ((c & 0x07) << 18) |
                    ((static_cast<unsigned char>(read.bytes[i + 1]) & 0x3F) << 12) |
                    ((static_cast<unsigned char>(read.bytes[i + 2]) & 0x3F) << 6) |
                    (static_cast<unsigned char>(read.bytes[i + 3]) & 0x3F);
                valid = cp >= 0x10000 && cp <= 0x10FFFF;
            }
        }
        if (valid) {
            text.append(read.bytes, i, len);
            i += len;
        } else {
            text += "\xEF\xBF\xBD";  // U+FFFD
            i += 1;
        }
    }
    // str.splitlines(): \n \r \r\n \v \f \x1c-\x1e \x85 \u2028 \u2029.
    std::vector<std::string> raw_lines;
    std::string current;
    auto flush = [&]() {
        raw_lines.push_back(current);
        current.clear();
    };
    bool last_was_break = false;
    for (std::size_t i = 0; i < text.size(); ++i) {
        const char ch = text[i];
        bool is_break = false;
        if (ch == '\r') {
            is_break = true;
            if (i + 1 < text.size() && text[i + 1] == '\n') {
                ++i;
            }
        } else if (ch == '\n' || ch == '\v' || ch == '\f' ||
                   (ch >= '\x1c' && ch <= '\x1e')) {
            is_break = true;
        } else if (i + 1 < text.size() && ch == '\xC2' && text[i + 1] == '\x85') {
            is_break = true;  // U+0085 NEL
            ++i;
        } else if (i + 2 < text.size() && ch == '\xE2' && text[i + 1] == '\x80' &&
                   (text[i + 2] == '\xA8' || text[i + 2] == '\xA9')) {
            is_break = true;  // U+2028 / U+2029
            i += 2;
        }
        if (is_break) {
            flush();
            last_was_break = true;
        } else {
            current += ch;
            last_was_break = false;
        }
    }
    if (!last_was_break) {
        flush();
    }
    const bool truncated = static_cast<int>(raw_lines.size()) > max_lines;
    std::vector<std::string> lines(
        raw_lines.begin(),
        raw_lines.begin() + std::min<std::size_t>(raw_lines.size(),
                                                  static_cast<std::size_t>(max_lines)));
    const std::string warning =
        truncated ? "仅显示前 " + std::to_string(max_lines) + " 行" : "";
    return {std::move(lines), warning};
}

// ---------------------------------------------------------------------------
// preview_for_resource / preview_for_artifact
// ---------------------------------------------------------------------------

namespace {

std::string lower_ascii(std::string v) {
    for (auto& c : v) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return v;
}

}  // namespace

PreviewState preview_for_resource(const ResourceItem& resource,
                                  const std::filesystem::path* base_path,
                                  const PreviewFileReader& reader,
                                  const PreviewExistsFn& exists_fn) {
    const std::string path = strategy_display_path(resource.path, base_path);
    const std::string fmt = lower_ascii(resource.format);
    const domain::Json* size = nullptr;
    if (resource.parsed_summary.is_object() &&
        resource.parsed_summary.contains("size_bytes")) {
        size = &resource.parsed_summary.at("size_bytes");
    }
    const auto lines = strategy_summary_lines(resource.name, path, resource.format, size);

    const bool path_exists = exists_fn(std::filesystem::path(path));

    const bool needs_file =
        strategy_in(fmt, strategy_text_formats()) ||
        strategy_in(fmt, strategy_table_formats()) ||
        strategy_in(fmt, strategy_pdf_formats()) ||
        strategy_in(fmt, strategy_professional_formats()) ||
        strategy_in(fmt, strategy_markdown_formats()) ||
        strategy_in(fmt, strategy_json_formats());
    if (!path_exists && needs_file) {
        PreviewState out;
        out.mode = "metadata";
        out.title = resource.name;
        out.lines = lines;
        out.warning = "文件不存在";
        return out;
    }

    static const std::vector<std::string> image_types = {"image_reference"};
    static const std::vector<std::string> image_formats = {
        "png", "jpg", "jpeg", "tif", "tiff"};

    if (strategy_in(resource.type, image_types) ||
        strategy_in(resource.format, image_formats)) {
        PreviewState out;
        out.mode = "image";
        out.title = resource.name;
        out.lines = lines;
        out.image_path = path;
        return out;
    }
    if (fmt == "pdf") {
        PreviewState out;
        out.mode = "pdf";
        out.title = resource.name;
        out.lines = lines;
        out.document_path = path;
        return out;
    }
    if (strategy_in(fmt, strategy_audio_formats())) {
        return {"media", resource.name, lines, std::nullopt, std::nullopt, ""};
    }
    if (strategy_in(fmt, strategy_markdown_formats()) && path_exists) {
        return {"rich_text", resource.name, lines, std::nullopt, std::nullopt, ""};
    }
    if (strategy_in(fmt, strategy_json_formats()) && path_exists) {
        return {"json_tree", resource.name, lines, std::nullopt, std::nullopt, ""};
    }
    if (strategy_in(fmt, strategy_text_formats()) ||
        strategy_in(fmt, strategy_table_formats())) {
        auto [preview_lines, warning] = strategy_read_preview_lines(path, reader);
        PreviewState out;
        out.title = resource.name;
        if (!preview_lines.empty()) {
            out.mode = strategy_in(fmt, strategy_text_formats()) ? "text" : "table";
            out.lines = lines;
            out.lines.insert(out.lines.end(), preview_lines.begin(),
                             preview_lines.end());
            out.warning = warning;
            return out;
        }
        out.mode = "metadata";
        out.lines = lines;
        out.warning = warning.empty() ? "暂不支持预览" : warning;
        return out;
    }
    if (strategy_in(fmt, strategy_professional_formats()) &&
        resource.type != "well_log" && resource.type != "seismic") {
        PreviewState out;
        out.mode = "metadata";
        out.title = resource.name;
        out.lines = lines;
        out.warning = "此格式暂使用安全摘要预览";
        return out;
    }
    static const std::vector<std::string> table_types = {
        "spreadsheet", "tabular", "time_depth", "horizon", "well_stratification"};
    if (strategy_in(resource.type, table_types)) {
        return {"table", resource.name, lines, std::nullopt, std::nullopt, ""};
    }
    if (resource.type == "well_log") {
        PreviewState out;
        out.mode = "well_log";
        out.title = resource.name;
        out.lines = lines;
        out.lines.push_back("预览: 测井摘要");
        return out;
    }
    if (resource.type == "seismic") {
        PreviewState out;
        out.mode = "seismic";
        out.title = resource.name;
        out.lines = lines;
        out.lines.push_back("预览: 地震体元数据");
        return out;
    }
    static const std::vector<std::string> external_types = {
        "document", "reference_map", "well_reference"};
    if (strategy_in(resource.type, external_types)) {
        PreviewState out;
        out.mode = "metadata";
        out.title = resource.name;
        out.lines = lines;
        out.warning = "此类型使用外部工具预览";
        return out;
    }
    PreviewState out;
    out.mode = "metadata";
    out.title = resource.name;
    out.lines = lines;
    out.warning = "暂不支持预览";
    return out;
}

PreviewState preview_for_artifact(const ExportArtifact& artifact,
                                  const std::filesystem::path* base_path) {
    const std::string path = strategy_display_path(artifact.output_path, base_path);
    PreviewState out;
    out.mode = "artifact";
    out.title = "成果文件 · " + artifact.format;
    out.lines = {
        "格式: " + artifact.format,
        "路径: " + path,
        "关联: " + artifact.linked_id,
    };
    return out;
}

}  // namespace pwb::ui_data_core
