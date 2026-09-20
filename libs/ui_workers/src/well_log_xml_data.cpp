// 05 线 — XML 井曲线真加载数据核（移植，见头注释的冻结参考清单）。
// 行为逐条对齐参考源；与参考的容许分歧在文件尾部"分歧声明"。

#include "pwb/ui_workers/well_log_xml_data.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <limits>

#include <pwb/ingest/py_compat.hpp>
#include <pwb/ingest/xml_scanner.hpp>

namespace pwb::ui_workers {

namespace {

// resources/well_log_xml.py 语义：剥 "{"uri}" 与 ":" 前缀后 casefold。
std::string local_name_casefold(const std::string& tag) {
    std::string text = tag;
    auto brace = text.rfind('}');
    if (brace != std::string::npos) text = text.substr(brace + 1);
    auto colon = text.rfind(':');
    if (colon != std::string::npos) text = text.substr(colon + 1);
    // strip + casefold（casefold 对 ASCII 与 lower 同；中文不受影响）。
    std::string out = pwb::ingest::py_strip(text);
    std::transform(out.begin(), out.end(), out.begin(),
                   [](unsigned char c) {
                       return c >= 'A' && c <= 'Z' ? static_cast<char>(c + 32)
                                                   : c;
                   });
    return out;
}

// xml_preview.py 语义：仅剥 "{"uri}" 前缀；大小写在使用处 lower。
std::string clean_tag(const std::string& tag) {
    auto brace = tag.rfind('}');
    return brace == std::string::npos ? tag : tag.substr(brace + 1);
}

std::string lowered(const std::string& text) {
    std::string out = text;
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) {
        return c >= 'A' && c <= 'Z' ? static_cast<char>(c + 32) : c;
    });
    return out;
}

// Python float() 语法：首尾空白、正负号、数字间下划线、小数点、指数、
// inf/infinity/nan（大小写不敏感）。与其余参考共享的 stod 分歧记录于
// 尾部声明（这里宁可更贴 Python：strict 语法，接受下划线）。
bool py_float(const std::string& raw, double* out) {
    const std::string text = pwb::ingest::py_strip(raw);
    if (text.empty()) return false;
    std::size_t i = 0;
    bool negative = false;
    if (text[i] == '+' || text[i] == '-') {
        negative = text[i] == '-';
        ++i;
    }
    std::string rest = text.substr(i);
    std::string low = lowered(rest);
    if (low == "inf" || low == "infinity") {
        *out = negative ? -std::numeric_limits<double>::infinity()
                        : std::numeric_limits<double>::infinity();
        return true;
    }
    if (low == "nan") {
        *out = std::numeric_limits<double>::quiet_NaN();
        return true;
    }
    // [digits][_digits][.digits] | .digits，随后可选指数。
    auto is_digit = [](char c) { return c >= '0' && c <= '9'; };
    std::string mantissa;
    std::size_t j = 0;
    bool any_digit = false;
    while (j < rest.size()) {
        if (is_digit(rest[j])) {
            mantissa.push_back(rest[j]);
            any_digit = true;
            ++j;
        } else if (rest[j] == '_' && any_digit && j + 1 < rest.size() &&
                   is_digit(rest[j + 1])) {
            ++j;  // 下划线只在数字之间
        } else {
            break;
        }
    }
    if (j < rest.size() && rest[j] == '.') {
        mantissa.push_back('.');
        ++j;
        while (j < rest.size()) {
            if (is_digit(rest[j])) {
                mantissa.push_back(rest[j]);
                any_digit = true;
                ++j;
            } else if (rest[j] == '_' && !mantissa.empty() &&
                       mantissa.back() != '.' && j + 1 < rest.size() &&
                       is_digit(rest[j + 1])) {
                ++j;
            } else {
                break;
            }
        }
    }
    if (!any_digit) return false;
    if (j < rest.size() && (rest[j] == 'e' || rest[j] == 'E')) {
        mantissa.push_back('e');
        ++j;
        if (j < rest.size() && (rest[j] == '+' || rest[j] == '-')) {
            mantissa.push_back(rest[j]);
            ++j;
        }
        bool exp_digit = false;
        while (j < rest.size()) {
            if (is_digit(rest[j])) {
                mantissa.push_back(rest[j]);
                exp_digit = true;
                ++j;
            } else if (rest[j] == '_' && exp_digit && j + 1 < rest.size() &&
                       is_digit(rest[j + 1])) {
                ++j;
            } else {
                break;
            }
        }
        if (!exp_digit) return false;  // Python: "1e" → ValueError
    }
    if (j != rest.size()) return false;
    try {
        *out = negative ? -std::stod(mantissa) : std::stod(mantissa);
    } catch (const std::exception&) {
        return false;  // 越界 → Python OverflowError；按不可解析处理
    }
    return true;
}

// Python int(str)（ss:Index 用）：首尾空白 + 可选符号 + 全数字。
bool py_int(const std::string& raw, long* out) {
    const std::string text = pwb::ingest::py_strip(raw);
    if (text.empty()) return false;
    std::size_t i = text[0] == '+' || text[0] == '-' ? 1 : 0;
    if (i >= text.size()) return false;
    for (std::size_t k = i; k < text.size(); ++k) {
        if (text[k] < '0' || text[k] > '9') return false;
    }
    errno = 0;
    char* end = nullptr;
    const long value = std::strtol(text.c_str(), &end, 10);
    if (errno == ERANGE || end == nullptr || *end != '\0') return false;
    *out = value;
    return true;
}

std::string path_stem(const std::string& path) {
    auto slash = path.find_last_of("/\\");
    std::string name =
        slash == std::string::npos ? path : path.substr(slash + 1);
    auto dot = name.find_last_of('.');
    if (dot == std::string::npos || dot == 0) return name;
    return name.substr(0, dot);
}

// _unit_for_header（xml_preview.py 逐条）。
std::string unit_for_header(const std::string& h_name) {
    const std::string upper = lowered(h_name);
    const auto contains = [&upper](const std::string& needle) {
        return upper.find(needle) != std::string::npos;
    };
    const auto equals = [&upper](const char* option) {
        // 中文键按 UTF-8 字节比较；ASCII 键 upper 后比较。
        return upper == lowered(option);
    };
    if (equals("dept") || equals("depth") || h_name == "深度" ||
        equals("tvd") || equals("tvdss")) {
        return "m";
    }
    if (contains("gr")) return "gAPI";
    if (contains("dt")) return "us/m";
    // 注意：POR/PORO/PERM 与中文键一样对原名大小写敏感（Python 用
    // h_name，不是 h_upper）——与 GR/DT 的 upper 匹配刻意不同。
    if (h_name.find("孔隙度") != std::string::npos ||
        h_name.find("POR") != std::string::npos ||
        h_name.find("PORO") != std::string::npos) {
        return "%";
    }
    if (h_name.find("渗透率") != std::string::npos ||
        h_name.find("PERM") != std::string::npos) {
        return "mD";
    }
    return "";
}

// re.split(r"[\s,;]+", line)：保留边界空字段（strip 后仍可能有
// 前导/尾随分隔符）。
std::vector<std::string> split_log_line(const std::string& line) {
    auto is_sep = [](char c) {
        return c == ',' || c == ';' || static_cast<unsigned char>(c) <= ' ';
    };
    std::vector<std::string> parts;
    std::size_t i = 0;
    if (!line.empty() && is_sep(line[0])) parts.emplace_back();
    while (i < line.size()) {
        if (is_sep(line[i])) {
            ++i;
            continue;
        }
        std::size_t start = i;
        while (i < line.size() && !is_sep(line[i])) ++i;
        parts.push_back(line.substr(start, i - start));
        if (i < line.size()) {
            // 分隔段：看尾部是否还有分隔（尾随空字段）
            std::size_t k = i;
            while (k < line.size() && is_sep(line[k])) ++k;
            if (k == line.size()) parts.emplace_back();
            i = k;
        }
    }
    if (parts.empty()) parts.emplace_back();  // re.split 从不返回空列表
    return parts;
}

// Python str.strip().splitlines()。
std::vector<std::string> splitlines_of(const std::string& raw) {
    std::vector<std::string> lines;
    std::string text = pwb::ingest::py_strip(raw);
    if (text.empty()) return lines;
    std::size_t pos = 0;
    while (pos <= text.size()) {
        std::size_t eol = text.find('\n', pos);
        std::size_t end = eol == std::string::npos ? text.size() : eol;
        std::string line = text.substr(pos, end - pos);
        while (!line.empty() &&
               (line.back() == '\r' || line.back() == '\n')) {
            line.pop_back();
        }
        lines.push_back(line);
        if (eol == std::string::npos) break;
        pos = eol + 1;
    }
    return lines;
}

using XmlNode = pwb::ingest::XmlNode;

struct SheetData {
    std::string name;
    std::vector<std::vector<std::string>> rows;
};

// dict 赋值语义：同名后者覆盖值、保留首次插入位置。
void store_sheet(std::vector<SheetData>* sheets, SheetData sheet) {
    for (auto& existing : *sheets) {
        if (existing.name == sheet.name) {
            existing.rows = std::move(sheet.rows);
            return;
        }
    }
    sheets->push_back(std::move(sheet));
}

}  // namespace

bool is_well_log_xml_bytes(std::string_view bytes) {
    // 流式有界扫描（Python root.iter() 的 200k 上限语义）：Start 事件
    // 即判定，绝不全量物化元素树（内存 O(1)，P1-2 教训）。实体禁止 =
    // defusedxml 优先语义。
    pwb::ingest::XmlScanner scanner(/*forbid_entities=*/true);
    pwb::ingest::XmlScanner::Attributes attrs;
    const pwb::ingest::XmlNode* end_node = nullptr;
    constexpr std::size_t kMaxElements = 200000;
    bool has_log_element = false;
    bool has_log_curve_info = false;
    bool has_log_data = false;
    bool has_named_sheet = false;
    bool witsml_tag_exact = false;
    std::string root_tag;
    std::size_t index = 0;
    bool malformed = false;
    scanner.feed(bytes);
    while (true) {
        pwb::ingest::XmlScanner::Event event;
        if (!scanner.next(event, attrs, end_node)) {
            malformed = scanner.failed();
            break;
        }
        if (event == pwb::ingest::XmlScanner::Event::Start) {
            if (index == 0) root_tag = local_name_casefold(attrs.tag);
            const std::string tag = local_name_casefold(attrs.tag);
            ++index;
            has_log_element = has_log_element || tag == "log";
            has_log_curve_info = has_log_curve_info ||
                                 tag == "logcurveinfo" ||
                                 tag == "curveinfo";
            has_log_data = has_log_data || tag == "logdata";
            witsml_tag_exact = witsml_tag_exact || tag == "witsml";
            if (tag == "worksheet") {
                for (const auto& [key, value] : attrs.attrib) {
                    (void)key;
                    const std::string name = local_name_casefold(value);
                    if (name == "测井曲线" || name == "welllog" ||
                        name == "well log" || name == "log curves") {
                        has_named_sheet = true;
                    }
                }
            }
            if (index >= kMaxElements) break;  // 语义扫描有界（Python 同）
        }
    }
    // 良构性覆盖整个文档（Python ET.parse 全量解析语义）：语义已足或
    // 达到元素上限后仍排空到 EOF，尾部畸形一律 false。
    if (!malformed) {
        scanner.mark_end();
        pwb::ingest::XmlScanner::Event event;
        while (scanner.next(event, attrs, end_node)) {
        }
        malformed = scanner.failed();
    }
    if (malformed) return false;
    const bool is_witsml =
        root_tag.find("witsml") != std::string::npos || witsml_tag_exact;
    return (has_log_element && has_log_curve_info && has_log_data) ||
           (is_witsml && has_log_curve_info && has_log_data) ||
           has_named_sheet;
}

namespace {

// 工作表行提取（load_xml_preview 的 SpreadsheetML 半）。
std::vector<std::vector<std::string>> worksheet_rows(const XmlNode& sheet) {
    constexpr const char* kNsIndex =
        "{urn:schemas-microsoft-com:office:spreadsheet}Index";
    std::vector<std::vector<std::string>> rows;
    for (const auto& w_child : sheet.children) {
        if (clean_tag(w_child->tag) != "Table") continue;
        for (const auto& r_elem : w_child->children) {
            if (clean_tag(r_elem->tag) != "Row") continue;
            std::vector<std::string> r_vals;
            for (const auto& c_elem : r_elem->children) {
                if (clean_tag(c_elem->tag) != "Cell") continue;
                if (const std::string* idx_attr =
                        c_elem->attr(kNsIndex)) {
                    long target = 0;
                    if (py_int(*idx_attr, &target)) {
                        while (static_cast<long>(r_vals.size()) < target - 1) {
                            r_vals.emplace_back();
                        }
                    }
                } else if (const std::string* idx_attr2 =
                               c_elem->attr("ss:Index")) {
                    long target = 0;
                    if (py_int(*idx_attr2, &target)) {
                        while (static_cast<long>(r_vals.size()) < target - 1) {
                            r_vals.emplace_back();
                        }
                    }
                } else if (const std::string* idx_attr3 =
                               c_elem->attr("Index")) {
                    long target = 0;
                    if (py_int(*idx_attr3, &target)) {
                        while (static_cast<long>(r_vals.size()) < target - 1) {
                            r_vals.emplace_back();
                        }
                    }
                }
                std::string txt;
                for (const auto& d_elem : c_elem->children) {
                    if (clean_tag(d_elem->tag) == "Data") {
                        txt = pwb::ingest::py_strip(d_elem->text);
                        break;
                    }
                }
                if (txt.empty() && !c_elem->text.empty()) {
                    txt = pwb::ingest::py_strip(c_elem->text);
                }
                r_vals.push_back(std::move(txt));
            }
            if (!r_vals.empty()) rows.push_back(std::move(r_vals));
        }
    }
    return rows;
}

}  // namespace

WellLogXmlData parse_well_log_xml(std::string_view bytes,
                                  const std::string& path_name,
                                  int max_curves,
                                  std::size_t max_samples) {
    if (max_samples == 0) {
        // Python 参考在此为 ZeroDivisionError（stride 除零）；worker 边界
        // 一律按 ValueError 语义失败，绝不静默全量。
        throw std::invalid_argument("max_samples 必须为正");
    }
    std::unique_ptr<XmlNode> root;
    try {
        root = pwb::ingest::xml_parse(bytes, /*forbid_entities=*/false);
    } catch (const std::exception&) {
        throw std::invalid_argument("无法解析 XML 测井数据: " + path_name);
    }

    WellLogXmlData data;
    data.well_name = path_stem(path_name);

    // WITSML 井名：只认显式字段（namewell/wellname），通用 <name> 不替换。
    {
        std::vector<const XmlNode*> elements;
        root->iter(elements);
        for (const XmlNode* element : elements) {
            std::string tag = lowered(clean_tag(element->tag));
            if (tag == "namewell" || tag == "wellname") {
                std::string declared = pwb::ingest::py_strip(element->text);
                if (!declared.empty()) {
                    data.well_name = std::move(declared);
                    break;
                }
            }
        }
    }

    // 工作表（根的直接子节点；Python `for child in root`）。
    std::vector<SheetData> sheets;
    for (const auto& child : root->children) {
        if (clean_tag(child->tag) != "Worksheet") continue;
        SheetData sheet;
        if (const std::string* v = child->attr(
                "{urn:schemas-microsoft-com:office:spreadsheet}Name")) {
            sheet.name = *v;
        } else if (const std::string* v = child->attr("ss:Name")) {
            sheet.name = *v;
        } else {
            sheet.name = "Sheet";
        }
        sheet.rows = worksheet_rows(*child);
        if (!sheet.rows.empty()) store_sheet(&sheets, std::move(sheet));
    }

    std::vector<std::string> headers;
    std::vector<std::vector<std::string>> rows;

    const std::vector<std::vector<std::string>>* curve_sheet_rows = nullptr;
    for (const auto& sheet : sheets) {
        if (sheet.name.find("测井曲线") != std::string::npos) {
            curve_sheet_rows = &sheet.rows;
            break;
        }
    }
    const SheetData* first_sheet =
        sheets.empty() ? nullptr : &sheets.front();
    const std::vector<std::vector<std::string>>* source_rows =
        curve_sheet_rows != nullptr
            ? curve_sheet_rows
            : (first_sheet != nullptr ? &first_sheet->rows : nullptr);

    if (source_rows != nullptr && source_rows->size() > 1) {
        for (const std::string& h : source_rows->front()) {
            std::string hs = pwb::ingest::py_strip(h);
            if (!hs.empty()) headers.push_back(std::move(hs));
        }
        // Python: raw_rows = curve_sheet_rows[1:] —— 井名列扫描只看数据行
        //（含表头行会把字面 "井号" 当井名，P0-1 教训）。
        if (!headers.empty()) {
            const std::string& first = headers.front();
            if (first == "井号" || first == "Well" ||
                first == "WELL_NAME" || first == "WELL") {
                for (std::size_t ri = 1; ri < source_rows->size(); ++ri) {
                    const auto& r = (*source_rows)[ri];
                    if (!r.empty() && !r[0].empty()) {
                        data.well_name = r[0];
                        break;
                    }
                }
            }
        }
        for (std::size_t r = 1; r < source_rows->size(); ++r) {
            rows.emplace_back(
                source_rows->at(r).begin(),
                source_rows->at(r).begin() +
                    std::min(source_rows->at(r).size(), headers.size()));
        }
    }

    // WITSML / 文本行。
    if (rows.empty()) {
        std::vector<const XmlNode*> elements;
        root->iter(elements);
        for (const XmlNode* elem : elements) {
            const std::string tag = lowered(clean_tag(elem->tag));
            if (tag != "logcurveinfo" && tag != "curveinfo" && tag != "curve") {
                continue;
            }
            std::string mnemonic;
            for (const auto& child : elem->children) {
                const std::string ctag = lowered(clean_tag(child->tag));
                if (ctag == "mnemonic" || ctag == "mnem" || ctag == "name") {
                    mnemonic = pwb::ingest::py_strip(child->text);
                }
            }
            if (!mnemonic.empty()) headers.push_back(std::move(mnemonic));
        }
        for (const XmlNode* elem : elements) {
            if (lowered(clean_tag(elem->tag)) != "logdata") continue;
            std::vector<std::string> lines = splitlines_of(elem->text);
            for (const auto& child : elem->children) {
                const std::string ctag = lowered(clean_tag(child->tag));
                if ((ctag == "data" || ctag == "row" || ctag == "line") &&
                    !child->text.empty()) {
                    std::vector<std::string> child_lines =
                        splitlines_of(child->text);
                    lines.insert(lines.end(), child_lines.begin(),
                                 child_lines.end());
                }
            }
            for (auto& line : lines) {
                std::string l = pwb::ingest::py_strip(line);
                if (l.empty() || l[0] == '#') continue;
                std::vector<std::string> parts = split_log_line(l);
                if (!parts.empty()) rows.push_back(std::move(parts));
            }
            if (!rows.empty()) break;
        }
    }

    if (rows.empty()) {
        throw std::invalid_argument("无法解析 XML 测井数据: " + path_name);
    }

    // 深度列：表头名 → 首 10 行 ≥5 个可解析浮点的列 → 0。
    std::size_t depth_idx = static_cast<std::size_t>(-1);
    for (std::size_t idx = 0; idx < headers.size(); ++idx) {
        const std::string upper = lowered(headers[idx]);
        if (upper == "dept" || upper == "depth" || headers[idx] == "深度" ||
            upper == "tvd" || upper == "tvdss") {
            depth_idx = idx;
            break;
        }
    }
    if (depth_idx == static_cast<std::size_t>(-1) && headers.size() > 1) {
        for (std::size_t idx = 0; idx < headers.size(); ++idx) {
            std::size_t parsed = 0;
            for (std::size_t r = 0;
                 r < rows.size() && r < 10 && parsed < 5; ++r) {
                if (idx < rows[r].size()) {
                    double value = 0.0;
                    if (py_float(rows[r][idx], &value)) ++parsed;
                }
            }
            if (parsed >= 5) {
                depth_idx = idx;
                break;
            }
        }
    }
    if (depth_idx == static_cast<std::size_t>(-1)) depth_idx = 0;

    // 选中曲线列：跳过深度列与井名列，截断 max_curves。
    std::vector<std::size_t> selected;
    for (std::size_t i = 0; i < headers.size(); ++i) {
        if (i == depth_idx) continue;
        const std::string& h = headers[i];
        if (h == "井号" || h == "Well" || h == "WELL_NAME") continue;
        selected.push_back(i);
        if (static_cast<int>(selected.size()) >= max_curves) break;
    }

    data.total_rows = rows.size();
    const std::size_t stride =
        std::max<std::size_t>(1, (rows.size() + max_samples - 1) / max_samples);
    data.sample_stride = stride;

    auto depths = std::make_shared<std::vector<double>>();
    std::vector<std::shared_ptr<std::vector<double>>> values(
        selected.size());
    for (auto& v : values) {
        v = std::make_shared<std::vector<double>>();
    }
    for (std::size_t r_idx = 0; r_idx < rows.size(); ++r_idx) {
        if (r_idx % stride != 0 && r_idx != rows.size() - 1) continue;
        const auto& r = rows[r_idx];
        if (depth_idx >= r.size()) continue;
        double d_val = 0.0;
        if (!py_float(r[depth_idx], &d_val)) continue;
        if (std::isnan(d_val) || d_val <= -9000.0) continue;
        depths->push_back(d_val);
        for (std::size_t k = 0; k < selected.size(); ++k) {
            const std::size_t i = selected[k];
            double v_val = std::numeric_limits<double>::quiet_NaN();
            if (i < r.size()) {
                double f = 0.0;
                if (py_float(r[i], &f) && f > -9000.0) {
                    v_val = f;
                }
            }
            values[k]->push_back(v_val);
        }
    }
    if (depths->size() < 2) {
        throw std::invalid_argument("XML 测井数据采样点小于 2");
    }
    data.top_depth = *std::min_element(depths->begin(), depths->end());
    data.bottom_depth = *std::max_element(depths->begin(), depths->end());

    for (std::size_t k = 0; k < selected.size(); ++k) {
        WellLogXmlCurve curve;
        const std::size_t col = selected[k];
        curve.name =
            col < headers.size() ? headers[col]
                                 : "Curve_" + std::to_string(col);
        curve.unit = unit_for_header(curve.name);
        curve.depth = depths;
        curve.values = values[k];
        data.curves.push_back(std::move(curve));
    }

    // 区间表（全部工作表；Python 逐类判定）。
    for (const auto& sheet : sheets) {
        if (sheet.rows.size() <= 1) continue;
        std::vector<std::string> w_h;
        w_h.reserve(sheet.rows[0].size());
        for (const std::string& c : sheet.rows[0]) {
            w_h.push_back(pwb::ingest::py_strip(c));
        }
        auto index_of = [&](const char* const* names, std::size_t count) {
            for (std::size_t i = 0; i < w_h.size(); ++i) {
                for (std::size_t k = 0; k < count; ++k) {
                    if (w_h[i] == names[k]) return static_cast<long>(i);
                }
            }
            return -1L;
        };
        static const char* kTopNames[] = {"顶深", "顶TVD", "深度", "Top"};
        static const char* kBotNames[] = {"底深", "底TVD", "Bottom"};
        const long top_i = index_of(kTopNames, 4);
        const long bot_i = index_of(kBotNames, 3);
        const auto in_row = [&](long idx, const std::vector<std::string>& r) {
            return idx >= 0 && static_cast<std::size_t>(idx) < r.size();
        };
        auto cell = [&](long idx, const std::vector<std::string>& r) {
            return r[static_cast<std::size_t>(idx)];
        };

        // 1. 岩性
        if (sheet.name.find("岩性") != std::string::npos) {
            long name_i = -1;
            for (std::size_t i = 0; i < w_h.size(); ++i) {
                if (w_h[i].find("岩性") != std::string::npos) {
                    name_i = static_cast<long>(i);
                    break;
                }
            }
            if (top_i >= 0 && bot_i >= 0 && name_i >= 0) {
                for (std::size_t r = 1; r < sheet.rows.size(); ++r) {
                    const auto& row = sheet.rows[r];
                    if (!in_row(top_i, row) || !in_row(bot_i, row) ||
                        !in_row(name_i, row)) {
                        continue;
                    }
                    double t = 0.0;
                    double b = 0.0;
                    if (!py_float(cell(top_i, row), &t)) continue;
                    if (!py_float(cell(bot_i, row), &b)) continue;
                    std::string n = pwb::ingest::py_strip(cell(name_i, row));
                    if (!n.empty() && t < b) {
                        data.lithology.push_back({t, b, std::move(n)});
                    }
                }
            }
        }

        // 2. 地层/砂层/层序/分层/相
        const auto sheet_has_any = [&](const char* const* keys,
                                       std::size_t count) {
            for (std::size_t k = 0; k < count; ++k) {
                if (sheet.name.find(keys[k]) != std::string::npos) return true;
            }
            return false;
        };
        static const char* kStratKeys[] = {"地层", "砂层", "层序", "分层",
                                           "相"};
        static const char* kFormNames[] = {"层号", "层名", "组", "统"};
        if (sheet_has_any(kStratKeys, 5)) {
            const long form_i = index_of(kFormNames, 4);
            long facies_i = -1;
            for (std::size_t i = 0; i < w_h.size(); ++i) {
                if (w_h[i].find("相") != std::string::npos) {
                    facies_i = static_cast<long>(i);
                    break;
                }
            }
            if (top_i >= 0) {
                for (std::size_t r = 1; r < sheet.rows.size(); ++r) {
                    const auto& row = sheet.rows[r];
                    if (!in_row(top_i, row)) continue;
                    double t = 0.0;
                    if (!py_float(cell(top_i, row), &t)) continue;
                    double b = t + 1.0;
                    if (in_row(bot_i, row) && !cell(bot_i, row).empty()) {
                        if (!py_float(cell(bot_i, row), &b)) continue;
                    }
                    // Python: `if t_val < b_val:` 包住两条入列 —— NaN
                    // 比较恒假 → 丢弃（正向守卫，与 t>=b continue 在
                    // NaN 上语义相反，P1-3 教训）。
                    if (t < b) {
                        if (in_row(form_i, row) &&
                            !pwb::ingest::py_strip(cell(form_i, row))
                                 .empty()) {
                            data.formation.push_back(
                                {t, b,
                                 pwb::ingest::py_strip(cell(form_i, row))});
                        }
                        if (in_row(facies_i, row) &&
                            !pwb::ingest::py_strip(cell(facies_i, row))
                                 .empty()) {
                            data.facies.push_back(
                                {t, b,
                                 pwb::ingest::py_strip(cell(facies_i, row))});
                        }
                    }
                }
            }
        }

        // 3. 文本/取心/说明/备注
        static const char* kTextKeys[] = {"文本", "取心", "说明", "备注"};
        if (sheet_has_any(kTextKeys, 4)) {
            static const char* kTxtNames[] = {"文本", "描述", "说明", "进尺",
                                              "心长"};
            long txt_i = index_of(kTxtNames, 5);
            static const char* kTrackNames[] = {"道名", "类型"};
            long track_i = index_of(kTrackNames, 2);
            if (top_i >= 0) {
                for (std::size_t r = 1; r < sheet.rows.size(); ++r) {
                    const auto& row = sheet.rows[r];
                    if (!in_row(top_i, row)) continue;
                    double t = 0.0;
                    if (!py_float(cell(top_i, row), &t)) continue;
                    double b = t + 2.0;
                    if (in_row(bot_i, row) && !cell(bot_i, row).empty()) {
                        if (!py_float(cell(bot_i, row), &b)) continue;
                    }
                    std::string track_name =
                        in_row(track_i, row)
                            ? pwb::ingest::py_strip(cell(track_i, row))
                            : std::string();
                    std::string val = in_row(txt_i, row)
                                          ? pwb::ingest::py_strip(cell(txt_i,
                                                                       row))
                                          : std::string();
                    if (val.empty() && in_row(track_i, row) &&
                        track_i != txt_i) {
                        val = pwb::ingest::py_strip(cell(track_i, row));
                    }
                    if (!val.empty() && t < b) {
                        if (track_name.find("相") != std::string::npos) {
                            data.facies.push_back({t, b, std::move(val)});
                        } else {
                            data.text_desc.push_back({t, b, std::move(val)});
                        }
                    }
                }
            }
        }

        // 4. 标准层
        if (sheet.name.find("标准层") != std::string::npos) {
            static const char* kHNames[] = {"层名", "标准层", "文本"};
            long name_i = index_of(kHNames, 3);
            if (name_i >= 0 && top_i >= 0) {
                for (std::size_t r = 1; r < sheet.rows.size(); ++r) {
                    const auto& row = sheet.rows[r];
                    if (!in_row(top_i, row) || !in_row(name_i, row)) continue;
                    double t = 0.0;
                    if (!py_float(cell(top_i, row), &t)) continue;
                    std::string n = pwb::ingest::py_strip(cell(name_i, row));
                    if (!n.empty()) {
                        data.horizons.push_back({t, t + 1.0, std::move(n)});
                    }
                }
            }
        }
    }
    return data;
}

}  // namespace pwb::ui_workers

// 与冻结参考的容许分歧（逐条，均已在用例层锁定或按构造不可达）：
//  * float 解析自实现 Python 语法（下划线/inf/nan）。溢出字面量
//   （"1e999"）：Python float() 返回 inf（字符串解析不溢出），本实现
//    stod 抛出后按"不可解析"处理——深度值则跳行、曲线值落 NaN。真实
//    交付不含 ≥1e308 的字面量；如出现，差异由本声明锁定。
//  * int(ss:Index) 不接受数字间下划线（strtol；真实交付不含此形状）。
//  * casefold 以 ASCII lower 实现：参与比较的键集（ASCII + 中文键）不
//    受 Unicode 大小写折叠特例影响。
