#include <pwb/ui_pages_preview/preview_table.hpp>

#include <cctype>
#include <cstdlib>

namespace pwb::ui_pages_preview {

namespace {

std::string trim_copy(const std::string& value) {
    std::size_t first = value.find_first_not_of(" \t\n\r\f\v");
    if (first == std::string::npos) return "";
    std::size_t last = value.find_last_not_of(" \t\n\r\f\v");
    return value.substr(first, last - first + 1);
}

std::string upper_ascii(std::string value) {
    for (char& c : value) c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    return value;
}

// Python float() parse — stricter than strtod on prefixes, more permissive
// on digit underscores ("1_000" → 1000.0) and inf/infinity/nan spellings.
bool python_float_parse(const std::string& raw) {
    std::string value = trim_copy(raw);
    if (value.empty()) return false;

    // Underscores are legal only between two digits (Py3.6+ literal grammar).
    std::string cleaned;
    cleaned.reserve(value.size());
    for (std::size_t i = 0; i < value.size(); ++i) {
        const char c = value[i];
        if (c == '_') {
            if (i > 0 && i + 1 < value.size() &&
                std::isdigit(static_cast<unsigned char>(value[i - 1])) &&
                std::isdigit(static_cast<unsigned char>(value[i + 1]))) {
                continue;
            }
            return false;
        }
        cleaned += c;
    }
    if (cleaned.empty()) return false;

    // Reject prefixes Python rejects but strtod accepts: 0x 0X 0b 0B 0o 0O.
    std::size_t pos = (cleaned[0] == '+' || cleaned[0] == '-') ? 1 : 0;
    if (cleaned.size() > pos + 2 && cleaned[pos] == '0') {
        const char p = cleaned[pos + 1];
        if (p == 'x' || p == 'X' || p == 'b' || p == 'B' || p == 'o' || p == 'O') {
            return false;
        }
    }

    char* end = nullptr;
    std::strtod(cleaned.c_str(), &end);
    return end == cleaned.c_str() + cleaned.size();
}

}  // namespace

bool is_number(const std::string& value) {
    if (value == "NaN") return true;
    return python_float_parse(value);
}

std::string table_cell_text(const std::string& raw) {
    return trim_copy(raw);
}

int depth_column(const std::vector<std::string>& headers) {
    for (std::size_t i = 0; i < headers.size(); ++i) {
        const std::string upper = upper_ascii(headers[i]);
        if (upper == "DEPT" || upper == "DEPTH" || headers[i] == "深度") {
            return static_cast<int>(i);
        }
    }
    return -1;
}

bool is_curve_definition(const std::vector<std::string>& headers) {
    return headers.size() >= 3 &&
           (headers[0] == "曲线" || headers[0] == "Mnemonic");
}

TableTruncation table_truncation(std::size_t rows, std::size_t cols) {
    TableTruncation result;
    result.keep_rows = rows;
    if (cols > 0 && rows * cols > static_cast<std::size_t>(MAX_PREVIEW_CELLS)) {
        result.keep_rows = static_cast<std::size_t>(
            std::max<long long>(1, MAX_PREVIEW_CELLS / static_cast<long long>(cols)));
        result.truncated = true;
        result.message = "表格预览已截断：显示 " + std::to_string(result.keep_rows) +
                         "/" + std::to_string(rows) +
                         " 行（上限 " + std::to_string(MAX_PREVIEW_CELLS) + " 单元格）";
    }
    return result;
}

std::string table_to_tsv(const std::vector<std::string>& headers,
                         const std::vector<std::vector<std::string>>& rows) {
    std::string out;
    for (std::size_t c = 0; c < headers.size(); ++c) {
        if (c) out += '\t';
        out += headers[c];
    }
    for (const auto& row : rows) {
        out += '\n';
        for (std::size_t c = 0; c < headers.size(); ++c) {
            if (c) out += '\t';
            if (c < row.size()) out += row[c];
        }
    }
    return out;
}

CellKind cell_kind(const std::string& text, int column, int depth_col,
                   bool curve_def) {
    if (column == depth_col) return CellKind::depth;
    if (curve_def && column == 0) return CellKind::curve_tag;
    if (curve_def && column == 1) return CellKind::curve_unit;
    if (is_number(text)) {
        return text == "NaN" ? CellKind::nan_number : CellKind::number;
    }
    return CellKind::plain;
}

}  // namespace pwb::ui_pages_preview
