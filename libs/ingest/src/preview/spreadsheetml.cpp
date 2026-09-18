#include "pwb/ingest/preview/spreadsheetml.hpp"

#include "pwb/ingest/xml_scanner.hpp"

namespace pwb::ingest::preview {

namespace {

constexpr const char* kNamespace = "urn:schemas-microsoft-com:office:spreadsheet";

std::string ns_qualified(const char* local) {
    return std::string("{") + kNamespace + "}" + local;
}

bool is_spreadsheet_element(const std::string& tag, const char* expected) {
    std::string prefix = std::string("{") + kNamespace + "}";
    return tag.rfind(prefix, 0) == 0 && tag.substr(prefix.size()) == expected;
}

// _attribute over start-attrs or a completed element: "{ns}Name" first,
// then the bare local name; empty values fall through (Python `or`).
const std::string* attribute(const std::vector<std::pair<std::string, std::string>>& attrib,
                             const char* local) {
    std::string qualified = ns_qualified(local);
    for (const auto& [k, v] : attrib) {
        if (k == qualified && !v.empty()) return &v;
    }
    for (const auto& [k, v] : attrib) {
        if (k == local && !v.empty()) return &v;
    }
    return nullptr;
}

// _positive_index: int() failure or <= 0 -> nullopt.
std::optional<int> positive_index(const std::string* value) {
    if (!value) return std::nullopt;
    const std::string& s = *value;
    size_t b = 0, e = s.size();
    while (b < e && (s[b] == ' ' || s[b] == '\t' || s[b] == '\n' || s[b] == '\r')) ++b;
    while (e > b && (s[e - 1] == ' ' || s[e - 1] == '\t')) --e;
    std::string trimmed = s.substr(b, e - b);
    if (trimmed.empty()) return std::nullopt;
    size_t i = 0;
    bool neg = false;
    if (trimmed[0] == '+' || trimmed[0] == '-') {
        neg = trimmed[0] == '-';
        i = 1;
    }
    if (i >= trimmed.size()) return std::nullopt;
    long long parsed = 0;
    for (; i < trimmed.size(); ++i) {
        if (trimmed[i] < '0' || trimmed[i] > '9') return std::nullopt;
        parsed = parsed * 10 + (trimmed[i] - '0');
        if (parsed > 1000000000) parsed = 1000000000;
    }
    if (neg) parsed = -parsed;
    if (parsed <= 0) return std::nullopt;
    return static_cast<int>(parsed);
}

// _cell_text: first "{ns}Data" descendant's itertext().
std::string cell_text(const XmlNode& cell) {
    std::vector<const XmlNode*> descendants;
    cell.iter(descendants);
    for (const XmlNode* d : descendants) {
        if (is_spreadsheet_element(d->tag, "Data")) return d->itertext();
    }
    return "";
}

PreviewResult message_result(const ResourceRef& res, std::string message) {
    PreviewResult r;
    r.mode = "message";
    r.title = res.name;
    r.path = res.path;
    r.revision = res.revision;  // Python: _revision(path)
    r.format = res.format;
    r.status = res.status;
    r.type_label = res.type;
    r.message = message;
    r.warning = message;
    return r;
}

}  // namespace

std::optional<PreviewResult> spreadsheetml_preview(const ResourceRef& resource,
                                                   std::string_view bytes,
                                                   long long max_text_bytes,
                                                   int max_rows, int max_columns) {
    long long source_size = static_cast<long long>(bytes.size());
    std::string_view capped = bytes.substr(0, static_cast<size_t>(max_text_bytes));
    bool artificial_eof =
        capped.size() == static_cast<size_t>(max_text_bytes) &&
        source_size > max_text_bytes;

    std::vector<std::vector<std::string>> rows;
    std::string sheet_name = "\xE5\xB7\xA5\xE4\xBD\x9C\xE8\xA1\xA8 1";  // 工作表 1
    bool root_checked = false;
    bool in_first_worksheet = false;
    bool in_first_table = false;
    bool first_worksheet_seen = false;
    bool truncated = false;
    bool malformed_structure = false;
    bool done = false;

    std::vector<std::string> current_row;
    bool row_open = false;
    int current_cell_position = 1;
    int current_row_position = 1;
    int next_row_position = 1;

    XmlScanner scanner;
    scanner.feed(capped);
    scanner.mark_end();

    auto finish = [&]() -> PreviewResult {
        if (!root_checked) {
            return message_result(resource,
                                  "SpreadsheetML XML \xE4\xB8\xBA\xE7\xA9\xBA");  // 为空
        }
        if (malformed_structure) {
            return message_result(
                resource,
                "SpreadsheetML XML \xE7\xB4\xA2\xE5\xBC\x95\xE6\xA0\xBC\xE5\xBC\x8F"
                "\xE9\x94\x99\xE8\xAF\xAF");  // 索引格式错误
        }
        if (!first_worksheet_seen) {
            return message_result(
                resource,
                "SpreadsheetML XML \xE6\xB2\xA1\xE6\x9C\x89\xE5\x8F\xAF\xE9\xA2\x84"
                "\xE8\xA7\x88\xE7\x9A\x84\xE5\xB7\xA5\xE4\xBD\x9C\xE8\xA1\xA8");  // 没有可预览的工作表
        }
        PreviewResult r;
        r.mode = "table";
        r.title = resource.name;
        r.path = resource.path;
        r.revision = resource.revision;
        r.format = resource.format;
        r.status = resource.status;
        r.type_label = resource.type;
        if (!rows.empty()) r.table_headers = rows[0];
        for (size_t i = 1; i < rows.size() && i <= static_cast<size_t>(max_rows); ++i) {
            r.table_rows.push_back(rows[i]);
        }
        r.sheets.push_back(sheet_name);
        r.truncated = truncated;
        r.warning =
            truncated
                ? "SpreadsheetML \xE8\xA1\xA8\xE6\xA0\xBC\xE9\xA2\x84\xE8\xA7\x88\xE5\xB7\xB2"
                  "\xE6\x8C\x89\xE8\xAF\xBB\xE5\x8F\x96\xE6\x88\x96\xE8\xA1\x8C\xE5\x88\x97"
                  "\xE4\xB8\x8A\xE9\x99\x90\xE6\x88\xAA\xE6\x96\xAD"
                : "";  // 表格预览已按读取或行列上限截断
        return r;
    };

    auto error_finish = [&](const std::string& cls) -> PreviewResult {
        // Boundary truncation only when the parser consumed the entire
        // capped buffer (Python's BoundedReader served the full limit and
        // expat hit the artificial EOF) — an error INSIDE the budget is a
        // real malformed document.
        bool ran_to_cap = scanner.consumed_bytes() >= capped.size();
        if (cls == "ParseError" && artificial_eof && first_worksheet_seen &&
            ran_to_cap) {
            truncated = true;
            return finish();
        }
        if (!root_checked && source_size == 0) {
            return message_result(resource,
                                  "SpreadsheetML XML \xE4\xB8\xBA\xE7\xA9\xBA");
        }
        return message_result(
            resource,
            "SpreadsheetML XML \xE6\xA0\xBC\xE5\xBC\x8F\xE9\x94\x99\xE8\xAF\xAF");  // 格式错误
    };

    auto handle_cell_end = [&](const XmlNode& cell) {
        const std::string* index_value = attribute(cell.attrib, "Index");
        auto cell_index = positive_index(index_value);
        if (!cell_index && index_value) malformed_structure = true;
        int desired_position = cell_index.value_or(current_cell_position);
        if (desired_position < current_cell_position) {
            malformed_structure = true;
            desired_position = current_cell_position;
        }
        if (desired_position <= max_columns) {
            while (static_cast<int>(current_row.size()) < desired_position - 1) {
                current_row.push_back("");
            }
            current_row.push_back(cell_text(cell));
        } else {
            truncated = true;
        }
        current_cell_position = desired_position + 1;
    };

    auto handle_row_end = [&]() -> bool {  // false = stop consuming
        while (next_row_position < current_row_position &&
               static_cast<int>(rows.size()) < max_rows + 1) {
            rows.emplace_back();
            next_row_position += 1;
        }
        if (next_row_position < current_row_position) {
            truncated = true;
            return false;
        }
        if (current_row.size() > static_cast<size_t>(max_columns)) {
            current_row.resize(static_cast<size_t>(max_columns));
        }
        rows.push_back(current_row);
        next_row_position = current_row_position + 1;
        current_row.clear();
        row_open = false;
        return true;
    };

    XmlScanner::Event event;
    XmlScanner::Attributes attrs;
    const XmlNode* node = nullptr;
    try {
        while (!done && scanner.next(event, attrs, node)) {
            if (event == XmlScanner::Event::Start) {
                if (!root_checked) {
                    root_checked = true;
                    if (!is_spreadsheet_element(attrs.tag, "Workbook")) {
                        return std::nullopt;
                    }
                }
                if (is_spreadsheet_element(attrs.tag, "Worksheet")) {
                    if (first_worksheet_seen) break;  // second worksheet start
                    first_worksheet_seen = true;
                    in_first_worksheet = true;
                    if (const std::string* name = attribute(attrs.attrib, "Name")) {
                        sheet_name = *name;
                    }
                    continue;
                }
                if (in_first_worksheet && is_spreadsheet_element(attrs.tag, "Table")) {
                    in_first_table = true;
                    continue;
                }
                if (in_first_worksheet && in_first_table &&
                    is_spreadsheet_element(attrs.tag, "Row")) {
                    if (static_cast<int>(rows.size()) >= max_rows + 1) {
                        truncated = true;
                        break;
                    }
                    current_row.clear();
                    row_open = true;
                    current_cell_position = 1;
                    const std::string* index_value = attribute(attrs.attrib, "Index");
                    auto row_index = positive_index(index_value);
                    if (!row_index && index_value) malformed_structure = true;
                    current_row_position = row_index.value_or(next_row_position);
                    if (current_row_position < next_row_position) {
                        malformed_structure = true;
                        current_row_position = next_row_position;
                    }
                    continue;
                }
                continue;
            }

            // --- End event ---
            if (node && is_spreadsheet_element(node->tag, "Worksheet")) {
                if (first_worksheet_seen) {
                    in_first_worksheet = false;
                    break;  // first worksheet end
                }
                continue;
            }
            if (!in_first_worksheet) continue;
            if (node && is_spreadsheet_element(node->tag, "Table")) {
                in_first_table = false;
                continue;
            }
            if (node && is_spreadsheet_element(node->tag, "Cell") && row_open) {
                handle_cell_end(*node);
                continue;
            }
            if (node && is_spreadsheet_element(node->tag, "Row") && row_open) {
                if (!handle_row_end()) break;
                continue;
            }
        }
    } catch (const XmlError& e) {
        return error_finish(e.class_name);
    }
    if (!done && scanner.failed()) {
        return error_finish(scanner.error().class_name);
    }
    return finish();
}

}  // namespace pwb::ingest::preview
