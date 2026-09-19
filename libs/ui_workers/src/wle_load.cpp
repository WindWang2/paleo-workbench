// VIZ-A — WLE-backed production implementation of the WellLogLoadFn seam.
// Parsing behavior is byte-identical to WellLogHostWidget::load_las (same
// LasSourceAdapter call, no pre-normalization) so the dock, the preview and
// the worker report the same data/units/diagnostics for the same file.

#include "pwb/ui_workers/wle_load.hpp"

#include <cctype>
#include <fstream>
#include <memory>
#include <string_view>

#include <welllog/core/document.hpp>
#include <welllog/io/las.hpp>

namespace pwb::ui_workers {

namespace {

std::string_view trim(std::string_view text) {
    while (!text.empty() && (text.front() == ' ' || text.front() == '\t' ||
                             text.front() == '\r')) {
        text.remove_prefix(1);
    }
    while (!text.empty() && (text.back() == ' ' || text.back() == '\t' ||
                             text.back() == '\r')) {
        text.remove_suffix(1);
    }
    return text;
}

std::string upper_ascii(std::string_view text) {
    std::string out(text);
    for (char& c : out) {
        c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    }
    return out;
}

// ~W "WELL." scan (Python inspect parity: last-wins including empty
// overwrites, no inline '#' truncation — R15/R16). Stops at the ASCII
// section like the preview bridge; falls back to the file stem.
std::string scan_well_name(std::string_view text, const std::string& path) {
    enum class Section { none, version, well, curve };
    Section section = Section::none;
    std::string found;
    while (!text.empty()) {
        const auto line_end = text.find('\n');
        auto line = text.substr(0, line_end == std::string_view::npos
                                        ? text.size()
                                        : line_end);
        text = line_end == std::string_view::npos
                   ? std::string_view{}
                   : text.substr(line_end + 1);
        line = trim(line);
        if (line.empty() || line.front() == '#') continue;
        if (line.front() == '~') {
            const auto heading = upper_ascii(trim(line.substr(1)));
            if (heading.empty() || heading.front() == 'A') {
                break;  // header ends at the data section
            }
            if (heading.front() == 'W') {
                section = Section::well;
            } else if (heading.front() == 'V') {
                section = Section::version;
            } else if (heading.front() == 'C') {
                section = Section::curve;
            } else {
                section = Section::none;
            }
            continue;
        }
        if (section != Section::well) continue;
        const auto colon = line.find(':');
        std::string_view left =
            colon == std::string_view::npos ? line : line.substr(0, colon);
        const auto dot = left.find('.');
        if (dot == std::string_view::npos) continue;
        if (upper_ascii(trim(left.substr(0, dot))) != "WELL") continue;
        found = std::string(trim(left.substr(dot + 1)));  // last wins
    }
    if (!found.empty()) return found;
    auto slash = path.find_last_of("/\\");
    std::string name =
        slash == std::string::npos ? path : path.substr(slash + 1);
    auto dot = name.find_last_of('.');
    if (dot == std::string::npos || dot == 0) return name;
    return name.substr(0, dot);
}

bool has_las_extension(const std::string& path) {
    auto dot = path.find_last_of('.');
    if (dot == std::string::npos || dot + 4 != path.size()) return false;
    auto ext = upper_ascii(std::string_view(path).substr(dot + 1));
    return ext == "LAS";
}

#if PWB_UI_WORKERS_HAVE_XML_LOAD
bool has_xml_extension(const std::string& path) {
    auto dot = path.find_last_of('.');
    if (dot == std::string::npos || dot + 4 != path.size()) return false;
    auto ext = upper_ascii(std::string_view(path).substr(dot + 1));
    return ext == "XML";
}
#endif

}  // namespace

WellLogLoadFn make_wle_load_fn() {
    return [](const std::string& path,
              const std::function<bool()>& is_cancelled)
        -> std::optional<LoadedWellLog> {
        if (is_cancelled && is_cancelled()) {
            throw WellLogLoadCancelled{};
        }
#if PWB_UI_WORKERS_HAVE_XML_LOAD
        // XML 走 05 线的井曲线识别+解析核（真加载，载荷与 LAS 同型）。
        const bool is_las = has_las_extension(path);
        if (!is_las && !has_xml_extension(path)) {
            return std::nullopt;
        }
        std::ifstream in(path, std::ios::binary);
        if (!in) return std::nullopt;
        std::string bytes((std::istreambuf_iterator<char>(in)),
                          std::istreambuf_iterator<char>());
        if (in.bad()) return std::nullopt;
        if (!is_las) {
            return load_well_log_xml(bytes, path, is_cancelled);
        }
#else
        // 无 ingest 的核闭包配置：XML 保持 05 前的诚实消息路径
        //（Python 生产路径不受影响；见 ui_workers/CMakeLists 头注）。
        if (!has_las_extension(path)) {
            return std::nullopt;
        }
        std::ifstream in(path, std::ios::binary);
        if (!in) return std::nullopt;
        std::string bytes((std::istreambuf_iterator<char>(in)),
                          std::istreambuf_iterator<char>());
        if (in.bad()) return std::nullopt;
#endif
        welllog::BufferSourceReference source;
        source.uri = path;
        auto result =
            welllog::LasSourceAdapter::parse(std::string_view(bytes), source);
        if (is_cancelled && is_cancelled()) {
            throw WellLogLoadCancelled{};
        }
        if (!result.has_value()) return std::nullopt;

        WleDocumentPayload payload;
        payload.document = std::make_shared<const welllog::WellLogDocument>(
            std::move(result.value().document));
        payload.diagnostics = result.value().diagnostics.size();
        LoadedWellLog loaded;
        loaded.data = payload;
        loaded.well_name = scan_well_name(bytes, path);
        return loaded;
    };
}

}  // namespace pwb::ui_workers
