#include "pwb/ingest/preview/las_wle_bridge.hpp"

#include <algorithm>
#include <cctype>
#include <limits>
#include <optional>
#include <string_view>
#include <utility>
#include <vector>

#include <welllog/io/las.hpp>

namespace pwb::ingest::preview {

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

// las.cpp first_token parity: the token ending at the first space/tab.
std::string_view first_token(std::string_view text) {
    text = trim(text);
    const auto end = text.find_first_of(" \t");
    return end == std::string_view::npos ? text : text.substr(0, end);
}

// Python las_preview._well_item parity: mnemonic is everything before the
// first '.', the value is the remainder of the pre-colon part, trimmed.
std::optional<std::pair<std::string, std::string>> well_item(
    std::string_view line) {
    const auto colon = line.find(':');
    std::string_view left =
        colon == std::string_view::npos ? line : line.substr(0, colon);
    const auto dot = left.find('.');
    if (dot == std::string_view::npos) return std::nullopt;
    std::string mnemonic(upper_ascii(trim(left.substr(0, dot))));
    std::string value(trim(left.substr(dot + 1)));
    return std::make_pair(std::move(mnemonic), std::move(value));
}

// Python las_preview._curve_header parity for mnemonic/description; the
// unit column uses WLE semantics (first token after the dot, las.cpp
// first_token) so the preview table can never disagree with the dock on
// units when legacy files carry trailing text in the unit field (R14).
std::optional<LasPreviewData::Curve> curve_header(std::string_view line) {
    const auto colon = line.find(':');
    std::string_view definition =
        colon == std::string_view::npos ? line : line.substr(0, colon);
    std::string_view description =
        colon == std::string_view::npos ? std::string_view{}
                                        : trim(line.substr(colon + 1));
    const auto dot = definition.find('.');
    if (dot == std::string_view::npos) return std::nullopt;
    const auto mnemonic = trim(definition.substr(0, dot));
    if (mnemonic.empty()) return std::nullopt;
    LasPreviewData::Curve curve;
    curve.mnemonic = std::string(mnemonic);
    curve.unit = std::string(first_token(definition.substr(dot + 1)));
    curve.description = std::string(description);
    return curve;
}

std::optional<std::size_t> find_depth_index(
    const std::vector<LasPreviewData::Curve>& curves) {
    for (std::size_t i = 0; i < curves.size(); ++i) {
        const auto mnemonic = upper_ascii(curves[i].mnemonic);
        if (mnemonic == "DEPT" || mnemonic == "DEPTH") return i;
    }
    return std::nullopt;
}

}  // namespace

LasPreviewData wle_las_preview_data(const std::string& bytes,
                                    const std::string& path) {
    LasPreviewData data;

    // Header pre-scan (Python inspect parity): skip lines that START with
    // '#' — no inline '#' truncation (the SDK applies its own inline rule
    // to its parse; the preview table mirrors Python, R15). WELL. is
    // last-wins including empty overwrites (Python inspect, R16).
    enum class Section { none, version, well, curve, ascii };
    Section section = Section::none;
    std::string_view text(bytes);
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
            if (heading.empty()) {
                section = Section::none;
            } else if (heading.front() == 'V') {
                section = Section::version;
            } else if (heading.front() == 'W') {
                section = Section::well;
            } else if (heading.front() == 'C') {
                section = Section::curve;
            } else if (heading.front() == 'A') {
                section = Section::ascii;
                break;  // header ends at the data section
            } else {
                section = Section::none;
            }
            continue;
        }
        if (section == Section::well) {
            if (auto item = well_item(line)) {
                if (item->first == "WELL") {
                    data.well_name = std::move(item->second);  // last wins
                }
            }
        } else if (section == Section::version) {
            // Python las_preview wrap detection (YES/Y/TRUE/1) — diagnostics
            // only; the SDK itself accepts YES/NO and both paths stay
            // byte-identical.
            if (auto item = well_item(line)) {
                if (item->first == "WRAP") {
                    const auto value = upper_ascii(item->second);
                    data.wrapped =
                        value == "YES" || value == "Y" || value == "TRUE" ||
                        value == "1";
                }
            }
        } else if (section == Section::curve) {
            if (auto curve = curve_header(line)) {
                data.curves.push_back(std::move(*curve));
            }
        }
    }

    if (data.curves.empty()) {
        // Python ValueError("LAS contains no curve headers").
        data.status = LasPreviewData::Status::no_curve_headers;
        return data;
    }

    // SDK parse — byte-identical to the dock path (no pre-normalization).
    welllog::BufferSourceReference source;
    source.uri = path;
    auto result = welllog::LasSourceAdapter::parse(
        std::string_view(bytes), source);
    if (!result.has_value()) {
        // Structural failure (VERS/WRAP invalid, no DEPT channel, mixed
        // depth direction, no accepted rows, oversized). Python inspect is
        // more liberal here; WLE is the production parser and the dock fails
        // these files too, so the preview reports the same failure class.
        data.status = LasPreviewData::Status::parse_error;
        data.parse_error_class = "ValueError";
        return data;
    }

    const welllog::WellLogDocument& document = result.value().document;
    if (document.sampling_axes().empty()) {
        data.status = LasPreviewData::Status::parse_error;
        data.parse_error_class = "ValueError";
        return data;
    }
    const auto& axis = document.sampling_axes().front();
    const auto row_count = axis.coordinates.length();
    data.row_count = static_cast<long long>(row_count);

    // Data table: first kLasPreviewDataRows rows; depth channel re-inserted
    // at its declared ~C position (document curves carry the non-depth
    // channels in declaration order).
    const std::size_t columns = data.curves.size();
    const auto depth_index = find_depth_index(data.curves);
    if (!depth_index.has_value()) {
        // Unreachable when the SDK parsed: it requires a DEPT/DEPTH channel.
        data.status = LasPreviewData::Status::parse_error;
        data.parse_error_class = "ValueError";
        return data;
    }
    const std::size_t rows = static_cast<std::size_t>(
        std::min<std::uint64_t>(row_count, kLasPreviewDataRows));
    data.values.assign(rows * columns, std::numeric_limits<double>::quiet_NaN());
    for (std::size_t row = 0; row < rows; ++row) {
        if (auto depth = axis.coordinates.value_as_double(row)) {
            data.values[row * columns + *depth_index] = *depth;
        }
    }
    std::size_t curve_column = 0;
    for (const auto& curve : document.curves()) {
        while (curve_column < columns && curve_column == *depth_index) {
            ++curve_column;
        }
        if (curve_column >= columns) break;
        for (std::size_t row = 0; row < rows; ++row) {
            if (auto value = curve.values.value_as_double(row)) {
                data.values[row * columns + curve_column] = *value;
            }
        }
        ++curve_column;
    }
    return data;
}

void install_wle_las_preview_provider() {
    set_las_preview_provider([](const std::string& bytes,
                                const std::string& path)
                                 -> std::optional<LasPreviewData> {
        return wle_las_preview_data(bytes, path);
    });
}

}  // namespace pwb::ingest::preview
