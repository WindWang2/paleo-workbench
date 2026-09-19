// VIZ-D 井位散点核心 —— geoviz/previews/dat.py `_well_head_payload` 的
// C++ 逐语义移植（冻结 oracle；详见头文件契约）。
//
// 已记录的近似（其余逐行对齐 Python）：
//  * `_normalized_column` 的 casefold/isalnum 按 Unicode 类别；这里 ASCII
//    精确（大小写折叠 + [0-9a-z]），非 ASCII 码点一律保留（SMI 表头只有
//    ASCII 列名；中文名在 Python 里同样是 isalnum，仅罕见非 ASCII 标点
//    行为不同）。与 libs/ingest 的 py_split 先例一致。
//  * str.split() / \s 的 Unicode 空白集合取 CPython 实际会命中的子集
//    （ASCII 空白 + 常用 Unicode 空白，见 py_compat 的同款列表）。
//  * 正则 `\b`/`\d`：词字符按 ASCII [0-9A-Za-z_] + 任意非 ASCII 码点，
//    数字仅 ASCII（CRS 声明实际只有 "EPSG:xxxx" / 文本）。

#include <pwb/ui_pages_preview/well_head_scatter_core.hpp>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <map>
#include <set>
#include <string>
#include <utility>

#include <pwb/ingest/py_compat.hpp>
#include <pwb/ui_pages_preview/summary_chips.hpp>

namespace pwb::ui_pages_preview::xy_scatter {

namespace {

// ---- dat.py 常量 ----------------------------------------------------------

constexpr std::string_view kWellHeadMarker = "WellHead File From SMI";
constexpr std::size_t kMaxIssues = 20;             // len(issues) < 20
constexpr std::size_t kMaxHeaderLines = 256;       // _MAX_HEADER_LINES
constexpr std::size_t kMaxHeaderChars = 64 * 1024; // _MAX_HEADER_CHARS
constexpr std::string_view kSchemaError = "DAT 数据结构与资源类型不匹配";

// ---- 基础词法 --------------------------------------------------------------

bool is_ascii_space(char32_t cp) {
    return cp == U' ' || cp == U'\t' || cp == U'\n' || cp == U'\r' ||
           cp == U'\f' || cp == U'\v';
}

// CPython str.isspace() 实际会命中的非 ASCII 成员（与 py_compat 同款）。
bool is_unicode_space(char32_t cp) {
    switch (cp) {
        case 0x00A0: case 0x1680: case 0x2028: case 0x2029: case 0x202F:
        case 0x205F: case 0x3000:
            return true;
        default:
            return cp >= 0x2000 && cp <= 0x200A;
    }
}

bool is_split_space(char32_t cp) {
    return is_ascii_space(cp) || is_unicode_space(cp);
}

void append_code_point(std::string& out, char32_t cp) {
    if (cp < 0x80) {
        out.push_back(static_cast<char>(cp));
    } else if (cp < 0x800) {
        out.push_back(static_cast<char>(0xC0 | (cp >> 6)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    } else if (cp < 0x10000) {
        out.push_back(static_cast<char>(0xE0 | (cp >> 12)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    } else {
        out.push_back(static_cast<char>(0xF0 | (cp >> 18)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    }
}

std::size_t code_point_count(std::string_view s) {
    std::size_t count = 0;
    std::size_t i = 0;
    while (i < s.size()) {
        const auto cp = pwb::ingest::detail::utf8_code_point(s, i);
        i += cp ? cp->size : 1;  // 非法字节按 1 计（输入应为合法 UTF-8）
        ++count;
    }
    return count;
}

// Python str.split()：任意空白运行切分、无空串成员。
std::vector<std::string> whitespace_split(std::string_view s) {
    std::vector<std::string> out;
    std::size_t i = 0;
    while (i < s.size()) {
        while (i < s.size()) {
            const auto cp = pwb::ingest::detail::utf8_code_point(s, i);
            if (cp && is_split_space(cp->cp)) {
                i += cp->size;
            } else {
                break;
            }
        }
        if (i >= s.size()) {
            break;
        }
        std::string token;
        while (i < s.size()) {
            const auto cp = pwb::ingest::detail::utf8_code_point(s, i);
            if (cp && is_split_space(cp->cp)) {
                break;
            }
            if (cp) {
                append_code_point(token, cp->cp);
                i += cp->size;
            } else {
                token.push_back(s[i]);  // 非法字节原样保留
                ++i;
            }
        }
        out.push_back(std::move(token));
    }
    return out;
}

// Python shlex.split（posix=True, comments=False, whitespace_split=True）。
// 返回 nullopt 对应 ValueError：未闭合引号（"No closing quotation"）或
// 结尾孤立反斜杠（"No escaped character"）。与 libs/ingest preview 的
// shlex_split 同一状态机（该实现不外发，此处为本模块私有副本）。
std::optional<std::vector<std::string>> shlex_split(std::string_view text) {
    constexpr char kEscape = '\\';
    const auto is_ws = [](char c) {
        return c == ' ' || c == '\t' || c == '\r' || c == '\n';
    };

    std::vector<std::string> tokens;
    std::string token;
    char state = ' ';
    char escapedstate = ' ';
    bool quoted = false;
    std::size_t i = 0;
    while (true) {
        const bool has_char = i < text.size();
        const char c = has_char ? text[i] : '\0';
        if (has_char) {
            ++i;
        } else {
            if (state == '"' || state == '\'' || state == kEscape) {
                return std::nullopt;  // No closing quotation / No escaped character
            }
            if (state == 'a' && (!token.empty() || quoted)) {
                tokens.push_back(std::move(token));
            }
            break;
        }
        switch (state) {
            case ' ':
                if (is_ws(c)) {
                    if (!token.empty() || quoted) {
                        tokens.push_back(std::move(token));
                        token.clear();
                        quoted = false;
                    }
                } else if (c == '"' || c == '\'') {
                    state = c;
                } else if (c == kEscape) {
                    escapedstate = 'a';
                    state = kEscape;
                } else {
                    token.push_back(c);
                    state = 'a';
                }
                break;
            case '"':
            case '\'':
                quoted = true;
                if (c == state) {
                    state = 'a';
                } else if (c == kEscape && state == '"') {
                    escapedstate = state;
                    state = kEscape;
                } else {
                    token.push_back(c);
                }
                break;
            case kEscape:
                // POSIX：引号内只有引号字符本身和反斜杠可被转义。
                if ((escapedstate == '"' || escapedstate == '\'') &&
                    c != kEscape && c != escapedstate) {
                    token.push_back(kEscape);
                }
                token.push_back(c);
                state = escapedstate;
                break;
            default: // 'a'
                if (is_ws(c)) {
                    state = ' ';
                    if (!token.empty() || quoted) {
                        tokens.push_back(std::move(token));
                        token.clear();
                        quoted = false;
                    }
                } else if (c == '"' || c == '\'') {
                    state = c;
                } else if (c == kEscape) {
                    escapedstate = 'a';
                    state = kEscape;
                } else {
                    token.push_back(c);
                }
                break;
        }
    }
    return tokens;
}

// `_split_data_line` 的 shlex 错误文案判别：最后一个字符是孤立反斜杠 ⇒
// "No escaped character"，否则未闭合引号 ⇒ "No closing quotation"。
std::string shlex_error_for(std::string_view line) {
    const std::string stripped = pwb::ingest::py_strip(line);
    if (!stripped.empty() && stripped.back() == '\\') {
        return "No escaped character";
    }
    return "No closing quotation";
}

// `_split_data_line`：无引号走 str.split()，有引号走 shlex。nullopt +
// error 给出 ValueError 文案。
std::optional<std::vector<std::string>> split_data_line(std::string_view line,
                                                        std::string& error) {
    if (line.find('"') == std::string_view::npos &&
        line.find('\'') == std::string_view::npos) {
        return whitespace_split(line);
    }
    auto tokens = shlex_split(line);
    if (!tokens) {
        error = shlex_error_for(line);
    }
    return tokens;
}

// `_header_tokens`：奇数个 '"' → nullopt（"unclosed double quote in
// header"）；否则 lstrip("#") + strip() + split()。
std::optional<std::vector<std::string>> header_tokens(const std::string& line) {
    const std::size_t quotes = static_cast<std::size_t>(
        std::count(line.begin(), line.end(), '"'));
    if (quotes % 2 != 0) {
        return std::nullopt;
    }
    const std::size_t first = line.find_first_not_of('#');
    const std::string body =
        first == std::string::npos
            ? std::string()
            : pwb::ingest::py_strip(std::string_view(line).substr(first));
    return whitespace_split(body);
}

// `_normalized_column`：casefold → "'"→"prime" → 仅保留 isalnum。
std::string normalized_column(std::string_view column) {
    std::string out;
    std::size_t i = 0;
    while (i < column.size()) {
        const auto decoded = pwb::ingest::detail::utf8_code_point(column, i);
        if (!decoded) {
            ++i;  // 非法字节丢弃（输入应为合法 UTF-8）
            continue;
        }
        i += decoded->size;
        char32_t cp = decoded->cp;
        if (cp == U'\'') {
            out += "prime";
            continue;
        }
        if (cp >= U'A' && cp <= U'Z') {
            cp += 32;  // ASCII casefold（非 ASCII 原样，见文件头近似说明）
        }
        const bool ascii_alnum =
            (cp >= U'0' && cp <= U'9') || (cp >= U'a' && cp <= U'z');
        if (ascii_alnum || cp >= 0x80) {
            append_code_point(out, cp);
        }
    }
    return out;
}

// ---- CRS 规范化 ------------------------------------------------------------

std::string casefold_join(std::string_view value) {
    // " ".join(value.casefold().split())
    std::string joined;
    std::size_t i = 0;
    bool at_token_start = true;
    while (i < value.size()) {
        const auto cp = pwb::ingest::detail::utf8_code_point(value, i);
        if (cp && is_split_space(cp->cp)) {
            i += cp->size;
            at_token_start = true;
            continue;
        }
        if (at_token_start && !joined.empty()) {
            joined.push_back(' ');
        }
        at_token_start = false;
        if (cp) {
            char32_t folded = cp->cp;
            if (folded >= U'A' && folded <= U'Z') {
                folded += 32;
            }
            append_code_point(joined, folded);
            i += cp->size;
        } else {
            joined.push_back(value[i]);
            ++i;
        }
    }
    return joined;
}

// re.search(r"\bepsg\s*:\s*(\d+)\b") 的手工扫描（首个匹配）。
std::string canonical_explicit_crs(std::string_view value) {
    const std::string s = casefold_join(value);
    const auto is_word_byte = [](char c) {
        const unsigned char b = static_cast<unsigned char>(c);
        if (b >= 0x80) {
            return true;  // 非 ASCII 一律视作词字符（见文件头近似说明）
        }
        return (b >= '0' && b <= '9') || (b >= 'A' && b <= 'Z') ||
               (b >= 'a' && b <= 'z') || b == '_';
    };
    const auto is_digit_byte = [](char c) { return c >= '0' && c <= '9'; };
    for (std::size_t i = 0; i + 4 <= s.size(); ++i) {
        if (s.compare(i, 4, "epsg") != 0) {
            continue;
        }
        if (i != 0 && is_word_byte(s[i - 1])) {
            continue;  // \b 前沿失败
        }
        std::size_t j = i + 4;
        while (j < s.size() && s[j] == ' ') {
            ++j;
        }
        if (j >= s.size() || s[j] != ':') {
            continue;
        }
        ++j;
        while (j < s.size() && s[j] == ' ') {
            ++j;
        }
        if (j >= s.size() || !is_digit_byte(s[j])) {
            continue;
        }
        std::string digits;
        while (j < s.size() && is_digit_byte(s[j])) {
            digits.push_back(s[j]);
            ++j;
        }
        if (j < s.size() && is_word_byte(s[j])) {
            continue;  // \b 后沿失败
        }
        return "epsg:" + digits;
    }
    return s;
}

bool same_explicit_crs(std::string_view left, std::string_view right) {
    return canonical_explicit_crs(left) == canonical_explicit_crs(right);
}

// ---- 表头 / 元数据 ----------------------------------------------------------

// 通用 newline 迭代器：\n、\r\n、孤行 \r 都终止一行（universal newlines），
// 1 基物理行号含空行与注释行（enumerate(stream, start=1)）。
class LineReader {
public:
    explicit LineReader(std::string_view text) {
        // encoding="utf-8-sig"：跳过文件级 BOM。
        if (text.size() >= 3 && static_cast<unsigned char>(text[0]) == 0xEF &&
            static_cast<unsigned char>(text[1]) == 0xBB &&
            static_cast<unsigned char>(text[2]) == 0xBF) {
            text.remove_prefix(3);
        }
        text_ = text;
    }

    bool next(std::string_view& line, std::int64_t& number) {
        if (pos_ >= text_.size()) {
            return false;
        }
        std::size_t end = pos_;
        while (end < text_.size() && text_[end] != '\n' && text_[end] != '\r') {
            ++end;
        }
        line = text_.substr(pos_, end - pos_);
        number = ++line_number_;
        if (end >= text_.size()) {
            pos_ = end;
        } else if (text_[end] == '\r' && end + 1 < text_.size() &&
                   text_[end + 1] == '\n') {
            pos_ = end + 2;
        } else {
            pos_ = end + 1;
        }
        return true;
    }

private:
    std::string_view text_;
    std::size_t pos_{0};
    std::int64_t line_number_{0};
};

// `_retain_header_line`：条数/字符数（码点数）双上限，超限的行直接丢弃。
void retain_header_line(std::vector<std::string>& header,
                        std::size_t& header_chars, const std::string& line) {
    if (header.size() >= kMaxHeaderLines ||
        header_chars + code_point_count(line) > kMaxHeaderChars) {
        return;
    }
    header.push_back(line);
    header_chars += code_point_count(line);
}

// `_read_header`：收集 '#' 注释行直到第一条非注释行（空行不终止扫描）。
std::vector<std::string> read_header(std::string_view text) {
    std::vector<std::string> header;
    std::size_t header_chars = 0;
    LineReader reader(text);
    std::string_view raw;
    std::int64_t number = 0;
    while (reader.next(raw, number)) {
        const std::string line = pwb::ingest::py_strip(raw);
        if (line.empty()) {
            continue;
        }
        if (line[0] != '#') {
            break;
        }
        retain_header_line(header, header_chars, line);
    }
    return header;
}

// `_source_crs_declaration`。fail 时 error 给出 _DatSchemaError 文案。
bool source_crs_declaration(const std::vector<std::string>& header,
                            std::string& value, std::string& error) {
    std::vector<std::string> declarations;
    for (const std::string& line : header) {
        const std::size_t first = line.find_first_not_of('#');
        const std::string body =
            first == std::string::npos
                ? std::string()
                : pwb::ingest::py_strip(std::string_view(line).substr(first));
        const std::size_t colon = body.find(':');
        if (colon == std::string::npos) {
            continue;
        }
        const std::string key = normalized_column(body.substr(0, colon));
        if (key != "crs" && key != "sourcecrs") {
            continue;
        }
        const std::string declared =
            pwb::ingest::py_strip(body.substr(colon + 1));
        if (declared.empty()) {
            error = "empty SourceCRS declaration";
            return false;
        }
        declarations.push_back(declared);
    }
    if (declarations.empty()) {
        value.clear();
        return true;
    }
    for (std::size_t k = 1; k < declarations.size(); ++k) {
        if (!same_explicit_crs(declarations[k], declarations[0])) {
            error = "conflicting SourceCRS declarations";
            return false;
        }
    }
    value = declarations[0];
    return true;
}

// `_unit_declarations`。
bool unit_declarations(const std::vector<std::string>& header,
                       std::map<std::string, std::string>& units,
                       std::string& error) {
    for (const std::string& line : header) {
        const auto tokens = header_tokens(line);
        if (!tokens || tokens->size() != 2 || (*tokens)[1].empty() ||
            (*tokens)[1][0] != '.') {
            continue;
        }
        const std::size_t dots = (*tokens)[1].find_first_not_of('.');
        const std::string unit = normalized_column(
            dots == std::string::npos
                ? std::string_view()
                : std::string_view((*tokens)[1]).substr(dots));
        const std::string field = normalized_column((*tokens)[0]);
        const auto existing = units.find(field);
        if (existing != units.end() && existing->second != unit) {
            error = "conflicting field units";
            return false;
        }
        units[field] = unit;
    }
    return true;
}

// `_metadata_provenance`。
std::string metadata_provenance(const std::string& explicit_value,
                                const std::string& declared,
                                std::string_view missing) {
    if (!explicit_value.empty() && !declared.empty()) {
        return "asset+file";
    }
    if (!explicit_value.empty()) {
        return "asset";
    }
    if (!declared.empty()) {
        return "file";
    }
    return std::string(missing);
}

// `_merge_declared_metadata`。
bool merge_declared_metadata(const std::string& explicit_value,
                             const std::string& declared, std::string_view name,
                             std::string& merged, std::string& error) {
    const std::string trimmed_explicit = pwb::ingest::py_strip(explicit_value);
    const std::string trimmed_declared = pwb::ingest::py_strip(declared);
    if (!trimmed_explicit.empty() && !trimmed_declared.empty() &&
        !same_explicit_crs(trimmed_explicit, trimmed_declared)) {
        error = "conflicting " + std::string(name) + " declarations";
        return false;
    }
    merged = !trimmed_explicit.empty() ? trimmed_explicit : trimmed_declared;
    return true;
}

// ---- 井位列声明 ------------------------------------------------------------

const std::map<std::string, std::set<std::string>>& well_head_columns() {
    static const std::map<std::string, std::set<std::string>> columns = {
        {"name", {"name", "well", "wellname"}},
        {"x", {"x"}},
        {"y", {"y"}},
    };
    return columns;
}

const std::set<std::string>& well_head_extra_columns() {
    static const std::set<std::string> extras = {
        "bottomx", "bottomy", "datum", "elevation", "gl",
        "kb",      "td",      "totaldepth", "uwi",   "welltype",
    };
    return extras;
}

std::set<std::string> well_head_allowed_columns() {
    std::set<std::string> allowed = well_head_extra_columns();
    for (const auto& entry : well_head_columns()) {
        allowed.insert(entry.second.begin(), entry.second.end());
    }
    return allowed;
}

// `_column_mapping`（row_width=None 的井位用法）。error 非空表示
// _header_tokens 抛出的表头级错误（unclosed double quote）。
std::optional<std::map<std::string, int>> column_mapping(
    const std::vector<std::string>& header, std::string& error) {
    const std::set<std::string> allowed = well_head_allowed_columns();
    std::vector<std::map<std::string, int>> candidates;
    for (const std::string& line : header) {
        const auto tokens = header_tokens(line);
        if (!tokens) {
            error = "unclosed double quote in header";
            return std::nullopt;
        }
        std::vector<std::string> normalized;
        normalized.reserve(tokens->size());
        for (const std::string& token : *tokens) {
            normalized.push_back(normalized_column(token));
        }
        bool all_allowed = !normalized.empty();
        for (const std::string& column : normalized) {
            if (allowed.find(column) == allowed.end()) {
                all_allowed = false;
                break;
            }
        }
        if (!all_allowed) {
            continue;
        }
        std::map<std::string, int> mapping;
        for (const auto& entry : well_head_columns()) {
            std::vector<int> matches;
            for (std::size_t index = 0; index < normalized.size(); ++index) {
                if (entry.second.find(normalized[index]) != entry.second.end()) {
                    matches.push_back(static_cast<int>(index));
                }
            }
            if (matches.size() == 1) {
                mapping[entry.first] = matches[0];
            }
        }
        if (mapping.size() != well_head_columns().size()) {
            continue;
        }
        std::set<int> used;
        for (const auto& bound : mapping) {
            used.insert(bound.second);
        }
        if (used.size() != mapping.size()) {
            continue;
        }
        candidates.push_back(std::move(mapping));
    }
    if (candidates.empty()) {
        return std::nullopt;
    }
    for (std::size_t k = 1; k < candidates.size(); ++k) {
        if (candidates[k] != candidates[0]) {
            return std::nullopt;
        }
    }
    return candidates[0];
}

}  // namespace

// ---------------------------------------------------------------------------

WellHeadScatterResult build_well_head_scatter(
    std::string_view text, const WellHeadScatterOptions& options) {
    WellHeadScatterResult result;
    const std::int64_t max_points =
        std::max<std::int64_t>(1, options.max_points);

    const auto fail = [&result](std::string detail) {
        result.ok = false;
        result.error = kSchemaError;
        result.detail = std::move(detail);
        return result;
    };

    // 1) 表头 + 井位标记。
    const std::vector<std::string> header = read_header(text);
    bool has_marker = false;
    for (const std::string& line : header) {
        if (line.find(kWellHeadMarker) != std::string::npos) {
            has_marker = true;
            break;
        }
    }
    if (!has_marker) {
        return fail("missing well-head marker");
    }

    // 2) Name/X/Y 列映射。
    std::string error;
    const auto mapping = column_mapping(header, error);
    if (!mapping) {
        if (!error.empty()) {
            return fail(std::move(error));  // unclosed double quote in header
        }
        return fail("missing required Name/X/Y columns");
    }
    const std::size_t name_index =
        static_cast<std::size_t>(mapping->at("name"));
    const std::size_t x_index = static_cast<std::size_t>(mapping->at("x"));
    const std::size_t y_index = static_cast<std::size_t>(mapping->at("y"));

    // 3) 声明宽度唯一性（所有映射索引落界且全 token 合法的表头行）。
    const std::set<std::string> allowed = well_head_allowed_columns();
    std::set<int> declaration_widths;
    for (const std::string& line : header) {
        const auto tokens = header_tokens(line);
        if (!tokens) {
            return fail("unclosed double quote in header");
        }
        if (tokens->empty()) {
            continue;
        }
        bool indices_fit = true;
        if (name_index >= tokens->size() || x_index >= tokens->size() ||
            y_index >= tokens->size()) {
            indices_fit = false;
        }
        if (!indices_fit) {
            continue;
        }
        bool all_allowed = true;
        for (const std::string& token : *tokens) {
            if (allowed.find(normalized_column(token)) == allowed.end()) {
                all_allowed = false;
                break;
            }
        }
        if (all_allowed) {
            declaration_widths.insert(static_cast<int>(tokens->size()));
        }
    }
    if (declaration_widths.size() != 1) {
        return fail("ambiguous well-head column width");
    }
    const std::size_t row_width =
        static_cast<std::size_t>(*declaration_widths.begin());

    // 4) UWI 投票：零票或冲突票 ⇒ 无 UWI（标记行同宽也参与投票）。
    std::set<std::size_t> uwi_votes;
    for (const std::string& line : header) {
        const auto tokens = header_tokens(line);
        if (!tokens || tokens->size() != row_width) {
            continue;
        }
        std::vector<std::size_t> matches;
        for (std::size_t index = 0; index < tokens->size(); ++index) {
            if (normalized_column((*tokens)[index]) == "uwi") {
                matches.push_back(index);
            }
        }
        if (matches.size() == 1) {
            uwi_votes.insert(matches[0]);
        }
    }
    const bool has_uwi = uwi_votes.size() == 1;
    const std::size_t uwi_index = has_uwi ? *uwi_votes.begin() : 0;

    // 5) 文件声明元数据 + 资产显式元数据合并。
    std::string declared_crs;
    if (!source_crs_declaration(header, declared_crs, error)) {
        return fail(std::move(error));
    }
    std::map<std::string, std::string> units;
    if (!unit_declarations(header, units, error)) {
        return fail(std::move(error));
    }
    const auto x_unit = units.find("x");
    const auto y_unit = units.find("y");
    const std::string declared_x_unit =
        x_unit == units.end() ? std::string() : x_unit->second;
    const std::string declared_y_unit =
        y_unit == units.end() ? std::string() : y_unit->second;
    if (!declared_x_unit.empty() && !declared_y_unit.empty() &&
        declared_x_unit != declared_y_unit) {
        return fail("conflicting X/Y coordinate units");
    }
    const std::string declared_units =
        !declared_x_unit.empty() ? declared_x_unit : declared_y_unit;
    const std::string& asset_source_crs = options.source_crs;
    const std::string& asset_coordinate_units = options.coordinate_units;
    std::string merged_crs;
    if (!merge_declared_metadata(asset_source_crs, declared_crs, "SourceCRS",
                                 merged_crs, error)) {
        return fail(std::move(error));
    }
    std::string merged_units;
    if (!merge_declared_metadata(asset_coordinate_units, declared_units,
                                 "coordinate unit", merged_units, error)) {
        return fail(std::move(error));
    }
    std::optional<bool> comparison_matches_source;
    if (!merged_crs.empty() && !options.comparison_crs.empty()) {
        comparison_matches_source =
            same_explicit_crs(merged_crs, options.comparison_crs);
    }

    // 6) 行循环（source_row 为 1 基物理行号，含空行/注释行计数；
    //    record_id 是数据行 0 基序号，失败行也占号）。Python parse_row 的
    //    校验顺序：列宽 → 井名 → X → Y → UWI 提取。
    WellHeadScatter& payload = result.payload;
    const auto record_issue = [&payload](std::int64_t source_row,
                                         std::string_view reason) {
        if (payload.issues.size() < kMaxIssues) {
            payload.issues.push_back({source_row, std::string(reason)});
        } else {
            ++payload.omitted_issue_count;
        }
    };
    LineReader reader(text);
    std::string_view raw;
    std::int64_t number = 0;
    std::int64_t row_count = 0;
    bool resource_limit = false;
    while (reader.next(raw, number)) {
        const std::string line = pwb::ingest::py_strip(raw);
        if (line.empty() || line[0] == '#') {
            continue;
        }
        const std::int64_t record_id = row_count;
        ++row_count;
        const auto split = split_data_line(line, error);
        bool row_ok = false;
        double x_value = 0.0;
        double y_value = 0.0;
        if (!split) {
            record_issue(number, error);  // shlex ValueError 文案
        } else if (split->size() != row_width) {
            record_issue(number, "列数与声明不一致");
        } else if ((*split)[name_index].empty()) {
            record_issue(number, "井名为空");
        } else {
            const auto parsed_x =
                pwb::ingest::py_parse_float((*split)[x_index]);
            const auto parsed_y =
                pwb::ingest::py_parse_float((*split)[y_index]);
            if (!parsed_x.has_value() || !std::isfinite(*parsed_x)) {
                record_issue(number, "X 坐标不是有限数值");
            } else if (!parsed_y.has_value() || !std::isfinite(*parsed_y)) {
                record_issue(number, "Y 坐标不是有限数值");
            } else {
                row_ok = true;
                x_value = *parsed_x;
                y_value = *parsed_y;
            }
        }
        if (row_ok) {
            payload.names.push_back((*split)[name_index]);
            payload.x.push_back(x_value);
            payload.y.push_back(y_value);
            // Python：仅当声明唯一 UWI 列时 uwis 逐记录对齐 names，
            // 否则是空 tuple（不逐记录补空串）。
            if (has_uwi) {
                payload.uwis.push_back(
                    pwb::ingest::py_strip((*split)[uwi_index]));
            }
            payload.record_ids.push_back(record_id);
            payload.source_rows.push_back(number);
            if (static_cast<std::int64_t>(payload.names.size()) > max_points) {
                resource_limit = true;
                break;
            }
        }
    }

    if (resource_limit) {
        // Python: GeoVizError(RESOURCE_LIMIT, f"井位数据超过 {_MAX_POINTS:,}
        // 个有效记录的显示上限") —— 千分位逗号按实际上限格式化。
        result.ok = false;
        result.resource_limit = true;
        result.error = "井位数据超过 " +
                       thousands_grouped(static_cast<long long>(max_points)) +
                       " 个有效记录的显示上限";
        result.detail.clear();
        return result;
    }

    if (row_count == 0) {
        return fail("no data rows");
    }
    if (payload.names.empty()) {
        std::string detail = "no renderable well locations";
        std::string causes;
        for (std::size_t k = 0; k < payload.issues.size(); ++k) {
            if (k != 0) {
                causes += "; ";
            }
            causes += "source row " +
                      std::to_string(payload.issues[k].source_row) + ": " +
                      payload.issues[k].reason;
        }
        if (!causes.empty()) {
            detail += "; " + causes;
        }
        if (payload.omitted_issue_count > 0) {
            detail += "; " + std::to_string(payload.omitted_issue_count) +
                      " additional rows omitted";
        }
        return fail(std::move(detail));
    }

    payload.total_records = row_count;
    payload.valid_records = static_cast<std::int64_t>(payload.names.size());
    payload.source_crs = merged_crs;
    payload.coordinate_units = merged_units;
    payload.source_crs_provenance =
        metadata_provenance(asset_source_crs, declared_crs, "undeclared");
    payload.coordinate_units_provenance =
        metadata_provenance(asset_coordinate_units, declared_units, "unknown");
    payload.comparison_crs = options.comparison_crs;
    payload.comparison_matches_source = comparison_matches_source;

    result.ok = true;
    return result;
}

// ---------------------------------------------------------------------------

ScatterViewSpec make_scatter_view_spec(const WellHeadScatter& scatter,
                                       std::string title) {
    ScatterViewSpec spec;
    spec.title = std::move(title);
    const std::string unit_suffix =
        scatter.coordinate_units.empty()
            ? std::string()
            : " (" + scatter.coordinate_units + ")";
    spec.x_axis_label = "X" + unit_suffix;
    spec.y_axis_label = "Y" + unit_suffix;

    // XYScatterBackend.prepare 的告警顺序：跳过行 → SourceCRS → 坐标单位。
    if (scatter.skipped_count() != 0) {
        spec.warnings.push_back(
            std::to_string(scatter.skipped_count()) + " 行已跳过；有效 " +
            std::to_string(scatter.valid_records) + "/" +
            std::to_string(scatter.total_records));
    }
    if (scatter.source_crs.empty()) {
        spec.warnings.push_back("SourceCRS 未声明");
    } else if (scatter.comparison_matches_source.has_value() &&
               !*scatter.comparison_matches_source) {
        spec.warnings.push_back("SourceCRS " + scatter.source_crs +
                                " 与参考 CRS " + scatter.comparison_crs +
                                " 不同（未转换）");
    }
    if (scatter.coordinate_units.empty()) {
        spec.warnings.push_back("坐标单位未知");
    }
    for (std::size_t k = 0; k < spec.warnings.size(); ++k) {
        if (k != 0) {
            spec.warning += " · ";
        }
        spec.warning += spec.warnings[k];
    }

    spec.summary_rows.emplace_back("有效井数",
                                   std::to_string(scatter.names.size()));
    spec.summary_rows.emplace_back("源记录",
                                   std::to_string(scatter.total_records));
    return spec;
}

}  // namespace pwb::ui_pages_preview::xy_scatter
