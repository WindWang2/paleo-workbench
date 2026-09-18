#include "pwb/ingest/preview/well_log_xml_preview.hpp"

#include <algorithm>

#include "pwb/ingest/py_compat.hpp"
#include "pwb/ingest/xml_scanner.hpp"

namespace pwb::ingest::preview {

namespace {

// local_tag: strip "{ns}" prefix only; case preserved (lowered at use).
std::string local_tag(const std::string& tag) {
    auto brace = tag.rfind('}');
    return brace == std::string::npos ? tag : tag.substr(brace + 1);
}

std::string lowered(std::string_view s) {
    std::string out;
    out.reserve(s.size());
    for (char c : s) {
        out.push_back(c >= 'A' && c <= 'Z' ? static_cast<char>(c + 32) : c);
    }
    return out;
}

std::string stripped(const std::string* v) { return v ? py_strip(*v) : ""; }

bool in_list(const std::string& value,
             std::initializer_list<const char*> options) {
    for (auto* o : options) {
        if (value == o) return true;
    }
    return false;
}

}  // namespace

std::optional<PreviewResult> xml_well_log_preview(const ResourceRef& resource,
                                                  std::string_view bytes,
                                                  const PreviewSettings& settings) {
    std::unique_ptr<XmlNode> root;
    try {
        root = xml_parse(bytes);
    } catch (const XmlError&) {
        return std::nullopt;
    }
    int max_preview_rows = settings.table_max_rows;

    std::vector<std::tuple<std::string, std::string, std::string>> curve_infos;
    std::vector<std::string> data_headers;
    std::vector<std::vector<std::string>> data_rows;
    // parsed sheets: (name, headers, rows)
    std::vector<std::tuple<std::string, std::vector<std::string>,
                           std::vector<std::vector<std::string>>>>
        parsed_sheets;
    std::vector<std::vector<std::string>> all_rows;
    std::string well_name;
    bool well_name_set = false;

    // --- pass 1: root-direct Worksheets (SpreadsheetML) ---
    for (const auto& child : root->children) {
        if (local_tag(child->tag) != "Worksheet") continue;
        std::string sheet_name = "工作表";
        if (const std::string* v =
                child->attr("{urn:schemas-microsoft-com:office:spreadsheet}Name")) {
            sheet_name = *v;
        } else if (const std::string* v = child->attr("ss:Name")) {
            sheet_name = *v;
        }
        std::vector<std::vector<std::string>> sheet_rows;
        for (const auto& w_child : child->children) {
            if (local_tag(w_child->tag) != "Table") continue;
            for (const auto& r_elem : w_child->children) {
                if (local_tag(r_elem->tag) != "Row") continue;
                std::vector<std::string> row_vals;
                for (const auto& c_elem : r_elem->children) {
                    if (local_tag(c_elem->tag) != "Cell") continue;
                    std::string txt;
                    for (const auto& d_elem : c_elem->children) {
                        if (local_tag(d_elem->tag) == "Data") {
                            txt = py_strip(d_elem->text);
                            break;
                        }
                    }
                    if (txt.empty() && !c_elem->text.empty()) {
                        txt = py_strip(c_elem->text);
                    }
                    row_vals.push_back(txt);
                }
                if (!row_vals.empty()) {
                    sheet_rows.push_back(row_vals);
                    if (static_cast<int>(sheet_rows.size()) >= max_preview_rows + 1) {
                        break;
                    }
                }
            }
        }
        if (sheet_rows.size() > 1) {
            std::vector<std::string> s_headers;
            for (const auto& h : sheet_rows[0]) {
                std::string hs = py_strip(h);
                if (!hs.empty()) s_headers.push_back(hs);
            }
            std::vector<std::vector<std::string>> s_data_rows;
            for (size_t r = 1;
                 r < sheet_rows.size() &&
                 r <= static_cast<size_t>(max_preview_rows);
                 ++r) {
                std::vector<std::string> row(sheet_rows[r].begin(),
                                             sheet_rows[r].begin() +
                                                 std::min(sheet_rows[r].size(),
                                                          s_headers.size()));
                s_data_rows.push_back(std::move(row));
            }
            parsed_sheets.emplace_back(sheet_name, s_headers, s_data_rows);
            if (all_rows.empty() && sheet_name.find("测井曲线") != std::string::npos) {
                all_rows = sheet_rows;
            }
        }
    }

    if (all_rows.empty() && !parsed_sheets.empty()) {
        const auto& [s_name, s_h, s_r] = parsed_sheets[0];
        (void)s_name;
        data_headers = s_h;
        data_rows = s_r;
    } else if (!all_rows.empty() && all_rows.size() > 1) {
        for (const auto& h : all_rows[0]) {
            std::string hs = py_strip(h);
            if (!hs.empty()) data_headers.push_back(hs);
        }
        std::vector<std::vector<std::string>> raw_data_rows(all_rows.begin() + 1,
                                                            all_rows.end());
        if (!data_headers.empty() &&
            in_list(data_headers[0], {"井号", "Well", "WELL_NAME", "WELL"})) {
            for (const auto& r : raw_data_rows) {
                if (!r.empty() && !r[0].empty()) {
                    well_name = r[0];
                    well_name_set = true;
                    break;
                }
            }
        }
        for (size_t r = 0;
             r < raw_data_rows.size() &&
             r < static_cast<size_t>(settings.table_max_rows);
             ++r) {
            std::vector<std::string> row(raw_data_rows[r].begin(),
                                         raw_data_rows[r].begin() +
                                             std::min(raw_data_rows[r].size(),
                                                      data_headers.size()));
            data_rows.push_back(std::move(row));
        }
    }

    // --- pass 2: WITSML curveInfo/logData ---
    if (data_rows.empty()) {
        std::vector<const XmlNode*> elements;
        root->iter(elements);
        for (const XmlNode* elem : elements) {
            std::string tag = lowered(local_tag(elem->tag));
            if (!in_list(tag, {"logcurveinfo", "curveinfo", "curve"})) continue;
            std::string mnemonic, unit, desc;
            for (const auto& child : elem->children) {
                std::string ctag = lowered(local_tag(child->tag));
                if (in_list(ctag, {"mnemonic", "mnem", "name"})) {
                    mnemonic = py_strip(child->text);
                } else if (in_list(ctag, {"unit", "unitstring"})) {
                    unit = py_strip(child->text);
                } else if (in_list(ctag, {"curvedescription", "description", "desc"})) {
                    desc = py_strip(child->text);
                }
            }
            if (!mnemonic.empty()) curve_infos.emplace_back(mnemonic, unit, desc);
        }
        if (!curve_infos.empty() && data_headers.empty()) {
            for (const auto& c : curve_infos) data_headers.push_back(std::get<0>(c));
        }

        for (const XmlNode* elem : elements) {
            std::string tag = lowered(local_tag(elem->tag));
            if (tag != "logdata") continue;
            std::vector<std::string> lines;
            std::string text = py_strip(elem->text);
            if (!text.empty()) {
                // splitlines on the stripped text
                size_t pos = 0;
                while (pos <= text.size()) {
                    size_t eol = text.find('\n', pos);
                    size_t end = eol == std::string::npos ? text.size() : eol + 1;
                    std::string line = text.substr(pos, end - pos);
                    while (!line.empty() &&
                           (line.back() == '\n' || line.back() == '\r')) {
                        line.pop_back();
                    }
                    lines.push_back(line);
                    pos = end;
                    if (eol == std::string::npos) break;
                }
            }
            for (const auto& child : elem->children) {
                std::string ctag = lowered(local_tag(child->tag));
                if ((ctag == "data" || ctag == "row" || ctag == "line") &&
                    !child->text.empty()) {
                    std::string ctext = py_strip(child->text);
                    size_t pos = 0;
                    while (pos <= ctext.size()) {
                        size_t eol = ctext.find('\n', pos);
                        size_t end = eol == std::string::npos ? ctext.size() : eol + 1;
                        std::string line = ctext.substr(pos, end - pos);
                        while (!line.empty() &&
                               (line.back() == '\n' || line.back() == '\r')) {
                            line.pop_back();
                        }
                        lines.push_back(line);
                        pos = end;
                        if (eol == std::string::npos) break;
                    }
                }
            }
            for (auto& line : lines) {
                std::string l = py_strip(line);
                if (l.empty() || l[0] == '#') continue;
                // re.split(r"[\s,;]+", line): split on runs of ws/,/;
                std::vector<std::string> parts;
                size_t i = 0;
                while (i < l.size()) {
                    bool sep = l[i] == ',' || l[i] == ';' ||
                               static_cast<unsigned char>(l[i]) <= ' ';
                    if (sep) {
                        ++i;
                        continue;
                    }
                    size_t start = i;
                    while (i < l.size()) {
                        char c = l[i];
                        if (c == ',' || c == ';' ||
                            static_cast<unsigned char>(c) <= ' ') {
                            break;
                        }
                        ++i;
                    }
                    parts.push_back(l.substr(start, i - start));
                }
                if (!parts.empty()) data_rows.push_back(parts);
                if (static_cast<int>(data_rows.size()) >= settings.table_max_rows) {
                    break;
                }
            }
            if (!data_rows.empty()) break;
        }
    }

    // --- pass 3: record/datapoint/logdatapoint/point ---
    if (data_rows.empty()) {
        std::vector<const XmlNode*> elements;
        root->iter(elements);
        std::vector<std::vector<std::pair<std::string, std::string>>> rows_found;
        for (const XmlNode* elem : elements) {
            std::string tag = lowered(local_tag(elem->tag));
            if (!in_list(tag, {"record", "datapoint", "logdatapoint", "point"})) {
                continue;
            }
            std::vector<std::pair<std::string, std::string>> row_vals;
            for (const auto& child : elem->children) {
                std::string ctag = local_tag(child->tag);
                std::string val = py_strip(child->text);
                if (!val.empty()) {
                    // dict semantics: last value wins, first position kept
                    bool replaced = false;
                    for (auto& [k, v] : row_vals) {
                        if (k == ctag) {
                            v = val;
                            replaced = true;
                        }
                    }
                    if (!replaced) row_vals.emplace_back(ctag, val);
                }
            }
            if (!row_vals.empty()) rows_found.push_back(row_vals);
            if (static_cast<int>(rows_found.size()) >= settings.table_max_rows) break;
        }
        if (!rows_found.empty()) {
            if (data_headers.empty()) {
                for (const auto& [k, v] : rows_found[0]) {
                    (void)v;
                    data_headers.push_back(k);
                }
            }
            for (const auto& row : rows_found) {
                std::vector<std::string> filled;
                for (const auto& h : data_headers) {
                    std::string cell;
                    for (const auto& [k, v] : row) {
                        if (k == h) {
                            cell = v;
                            break;
                        }
                    }
                    filled.push_back(cell);
                }
                data_rows.push_back(std::move(filled));
            }
        }
    }

    if (data_headers.empty() && data_rows.empty()) return std::nullopt;

    // --- curve infos fallback from headers ---
    if (curve_infos.empty()) {
        for (const auto& h : data_headers) {
            std::string h_name = py_strip(h);
            std::string upper = lowered(h_name);
            std::string unit;
            if (in_list(upper, {"dept", "depth", "深度", "tvd", "tvdss"})) {
                unit = "m";
            } else if (upper.find("gr") != std::string::npos) {
                unit = "gAPI";
            } else if (upper.find("dt") != std::string::npos) {
                unit = "us/m";
            } else if (h_name.find("孔隙度") != std::string::npos ||
                       h_name.find("POR") != std::string::npos) {
                unit = "%";
            } else if (h_name.find("渗透率") != std::string::npos ||
                       h_name.find("PERM") != std::string::npos) {
                unit = "mD";
            }
            curve_infos.emplace_back(h_name, unit, h_name);
        }
    }

    if (!well_name_set) {
        well_name = split_path_parts(resource.path).stem;
        std::vector<const XmlNode*> elements;
        root->iter(elements);
        for (const XmlNode* elem : elements) {
            std::string tag = lowered(local_tag(elem->tag));
            if (in_list(tag, {"namewell", "wellname", "well", "name"}) &&
                !elem->text.empty()) {
                std::string val = py_strip(elem->text);
                // Python len(val) counts characters, not UTF-8 bytes
                size_t chars = 0;
                for (size_t i = 0; i < val.size();) {
                    auto cp = detail::utf8_code_point(val, i);
                    i += cp ? cp->size : 1;
                    ++chars;
                }
                if (!val.empty() && chars < 50) {
                    well_name = val;
                    break;
                }
            }
        }
    }

    PreviewResult r;
    r.mode = "well_log";
    r.title = resource.name;
    r.path = resource.path;
    r.revision = resource.revision;
    r.format = resource.format;
    r.status = resource.status;
    r.type_label = "测井数据";
    r.summary_rows.emplace_back("井名", well_name);
    r.summary_rows.emplace_back("曲线数", std::to_string(data_headers.size()));
    r.summary_rows.emplace_back("采样点", std::to_string(data_rows.size()));
    r.table_headers = {"曲线", "单位", "描述"};
    for (const auto& c : curve_infos) {
        r.table_rows.push_back({std::get<0>(c), std::get<1>(c), std::get<2>(c)});
    }
    r.data_headers = data_headers;
    r.data_rows = data_rows;
    if (parsed_sheets.size() > 1) {
        for (const auto& [name, h, rows] : parsed_sheets) {
            (void)h;
            (void)rows;
            r.sheets.push_back(name);
        }
    }
    r.visualization_available = true;
    return r;
}

}  // namespace pwb::ingest::preview
