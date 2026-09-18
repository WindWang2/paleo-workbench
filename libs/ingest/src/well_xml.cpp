#include "pwb/ingest/well_xml.hpp"

#include <algorithm>
#include <cstring>
#include <memory>
#include <set>

#include "pwb/ingest/py_compat.hpp"
#include "pwb/ingest/xml_scanner.hpp"

namespace pwb::ingest {

namespace {

constexpr size_t kMaxRecords = 100000;
constexpr size_t kMaxElements = 200000;

// --- well_log_xml key sets -------------------------------------------------
const std::set<std::string>& spreadsheet_names() {
    static const std::set<std::string> names = {
        "\xE6\xB5\x8B\xE4\xBA\x95\xE6\x9B\xB2\xE7\xBA\xBF",  // 测井曲线
        "welllog",
        "well log",
        "log curves",
    };
    return names;
}

// --- well_location_xml key sets (candidates kept in source order, D5) ------
const std::vector<std::string>& name_keys() {
    static const std::vector<std::string> keys = {
        "well", "wellname", "wellid", "wellno", "uwi",
        "\xE4\xBA\x95\xE5\x90\x8D",                        // 井名
        "\xE4\xBA\x95\xE5\x8F\xB7",                        // 井号
        "\xE4\xBA\x95\xE5\x8F\xB7\xE5\x90\x8D\xE7\xA7\xB0" // 井号名称
    };
    return keys;
}
const std::vector<std::string>& x_keys() {
    static const std::vector<std::string> keys = {
        "x", "xcoord", "xcoordinate", "easting", "east",
        "\xE7\xBB\x8F\xE5\xBA\xA6",              // 经度
        "\xE4\xB8\x9C\xE5\x9D\x90\xE6\xA0\x87",  // 东坐标
        "x\xE5\x9D\x90\xE6\xA0\x87",             // x坐标
        "longitude", "lon",
    };
    return keys;
}
const std::vector<std::string>& y_keys() {
    static const std::vector<std::string> keys = {
        "y", "ycoord", "ycoordinate", "northing", "north",
        "\xE7\xBA\xAC\xE5\xBA\xA6",              // 纬度
        "\xE5\x8C\x97\xE5\x9D\x90\xE6\xA0\x87",  // 北坐标
        "y\xE5\x9D\x90\xE6\xA0\x87",             // y坐标
        "latitude", "lat",
    };
    return keys;
}
const std::vector<std::string>& z_keys() {
    static const std::vector<std::string> keys = {
        "z", "elevation", "elev", "kb",
        "\xE6\xB5\xB7\xE6\x8B\x94",                          // 海拔
        "\xE4\xBA\x95\xE5\x8F\xA3\xE9\xAB\x98\xE7\xA8\x8B",  // 井口高程
        "\xE9\xAB\x98\xE7\xA8\x8B",                          // 高程
    };
    return keys;
}
const std::vector<std::string>& uwi_keys() {
    static const std::vector<std::string> keys = {
        "uwi", "api", "wellid",
        "\xE4\xBA\x95\xE5\x8F\xB7",  // 井号
    };
    return keys;
}
const std::vector<std::string>& crs_keys() {
    static const std::vector<std::string> keys = {
        "crs", "srs", "srsname", "coordinatesystem",
        "\xE5\x9D\x90\xE6\xA0\x87\xE7\xB3\xBB",  // 坐标系
    };
    return keys;
}

bool contains(const std::vector<std::string>& keys, const std::string& key) {
    return std::find(keys.begin(), keys.end(), key) != keys.end();
}

}  // namespace

bool is_well_log_xml_bytes(std::string_view bytes) {
    std::unique_ptr<XmlNode> root;
    try {
        root = xml_parse(bytes);
    } catch (const XmlError&) {
        return false;
    }

    std::set<std::string> tags;
    bool has_log_element = false;
    bool has_log_curve_info = false;
    bool has_log_data = false;
    bool has_named_well_log_sheet = false;
    size_t index = 0;
    std::vector<const XmlNode*> elements;
    root->iter(elements);
    for (const XmlNode* element : elements) {
        if (index >= kMaxElements) break;
        ++index;
        std::string tag = log_local_name(element->tag);
        tags.insert(tag);
        has_log_element = has_log_element || tag == "log";
        has_log_curve_info =
            has_log_curve_info || tag == "logcurveinfo" || tag == "curveinfo";
        has_log_data = has_log_data || tag == "logdata";
        if (tag == "worksheet") {
            for (const auto& [key, value] : element->attrib) {
                (void)key;
                std::string name = py_strip(value);
                for (auto& ch : name) {
                    if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch + 32);
                }
                if (spreadsheet_names().count(name)) {
                    has_named_well_log_sheet = true;
                }
            }
        }
    }
    std::string root_tag = log_local_name(root->tag);
    // `"witsml" in root_tag` is a SUBSTRING test; `"witsml" in tags` is set
    // membership — both semantics live on one line in Python.
    bool is_witsml = root_tag.find("witsml") != std::string::npos ||
                     tags.count("witsml") > 0;
    return (has_log_element && has_log_curve_info && has_log_data) ||
           (is_witsml && has_log_curve_info && has_log_data) ||
           has_named_well_log_sheet;
}

namespace {

std::string first_value(const std::vector<std::string>& keys,
                        const std::vector<std::pair<std::string, std::string>>& values,
                        bool* found = nullptr) {
    for (const auto& key : keys) {
        for (const auto& [k, v] : values) {
            if (k == key) {
                std::string stripped = py_strip(v);
                if (!stripped.empty()) {
                    if (found) *found = true;
                    return stripped;
                }
            }
        }
    }
    if (found) *found = false;
    return "";
}

// Python iterates the SET members directly and takes the first non-empty
// value; with at most one key per family present (the frozen oracle's
// contract, D5) this fixed-priority scan is equivalent.
std::string name_from_values(
    const std::vector<std::pair<std::string, std::string>>& values,
    bool allow_plain_name) {
    std::string found_key;
    std::string name;
    for (const auto& key : name_keys()) {
        for (const auto& [k, v] : values) {
            if (k == key && !py_strip(v).empty()) {
                found_key = key;
                name = py_strip(v);
                break;
            }
        }
        if (!found_key.empty()) break;
    }
    if (name.empty() && allow_plain_name) {
        for (const auto& [k, v] : values) {
            if (k == "name" && !py_strip(v).empty()) {
                name = py_strip(v);
                break;
            }
        }
    }
    return name;
}

std::optional<double> float_or_none_str(const std::string& value) {
    return py_parse_float(value);
}

std::optional<XMLWellLocation> record_from_values(
    const std::vector<std::pair<std::string, std::string>>& values,
    const std::string& inherited_crs, bool allow_plain_name) {
    std::string name = name_from_values(values, allow_plain_name);

    std::string x_raw, y_raw;
    for (const auto& key : x_keys()) {
        bool hit = false;
        x_raw = first_value({key}, values, &hit);
        if (hit) break;
    }
    for (const auto& key : y_keys()) {
        bool hit = false;
        y_raw = first_value({key}, values, &hit);
        if (hit) break;
    }
    auto x = x_raw.empty() ? std::nullopt : float_or_none_str(x_raw);
    auto y = y_raw.empty() ? std::nullopt : float_or_none_str(y_raw);
    if (name.empty() || !x || !y) return std::nullopt;

    std::string z_raw = first_value(z_keys(), values);
    auto z = z_raw.empty() ? std::nullopt : float_or_none_str(z_raw);
    std::string uwi = first_value(uwi_keys(), values);
    std::string crs = first_value(crs_keys(), values);
    if (crs.empty()) crs = inherited_crs;

    XMLWellLocation record;
    record.name = std::move(name);
    record.x = *x;
    record.y = *y;
    record.z = z;
    record.uwi = std::move(uwi);
    record.source_crs = std::move(crs);
    return record;
}

std::string text_of_cell(const XmlNode& cell) {
    std::vector<const XmlNode*> descendants;
    cell.iter(descendants);
    for (const XmlNode* d : descendants) {
        if (location_key_normalize(d->tag) == "data" && !d->text.empty()) {
            return py_strip(d->text);
        }
    }
    return py_strip(cell.text);
}

std::vector<XMLWellLocation> spreadsheet_records(
    const XmlNode& root, const std::string& inherited_crs) {
    std::vector<XMLWellLocation> records;
    std::vector<const XmlNode*> elements;
    root.iter(elements);
    for (const XmlNode* element : elements) {
        if (location_key_normalize(element->tag) != "worksheet") continue;
        std::vector<std::vector<std::string>> rows;
        std::vector<const XmlNode*> inner;
        element->iter(inner);
        for (const XmlNode* row : inner) {
            if (location_key_normalize(row->tag) != "row") continue;
            std::vector<std::string> cells;
            for (const auto& cell : row->children) {
                if (location_key_normalize(cell->tag) == "cell") {
                    cells.push_back(text_of_cell(*cell));
                }
            }
            if (!cells.empty()) rows.push_back(std::move(cells));
        }
        if (rows.size() < 2) continue;
        std::vector<std::string> headers;
        for (const std::string& value : rows[0]) {
            headers.push_back(location_key_normalize(value));
        }
        bool has_name = false, has_x = false, has_y = false;
        for (const auto& header : headers) {
            if (header.empty()) continue;
            has_name = has_name || contains(name_keys(), header);
            has_x = has_x || contains(x_keys(), header);
            has_y = has_y || contains(y_keys(), header);
        }
        // SpreadsheetML must name the well column explicitly.
        if (!has_name || !has_x || !has_y) continue;
        for (size_t r = 1; r < rows.size(); ++r) {
            const auto& row = rows[r];
            std::vector<std::pair<std::string, std::string>> values;
            for (size_t c = 0; c < headers.size(); ++c) {
                const std::string& header = headers[c];
                if (header.empty() || c >= row.size()) continue;
                std::string cell = py_strip(row[c]);
                if (cell.empty()) continue;
                // duplicate headers: the later column overwrites
                bool replaced = false;
                for (auto& [k, v] : values) {
                    if (k == header) {
                        v = cell;
                        replaced = true;
                    }
                }
                if (!replaced) values.emplace_back(header, cell);
            }
            auto record = record_from_values(values, inherited_crs, false);
            if (record) {
                records.push_back(std::move(*record));
                if (records.size() >= kMaxRecords) return records;
            }
        }
    }
    return records;
}

}  // namespace

WellLocationExtraction extract_well_locations_xml_bytes(std::string_view bytes) {
    WellLocationExtraction out;
    std::unique_ptr<XmlNode> root;
    try {
        root = xml_parse(bytes, /*forbid_entities=*/true);
    } catch (const XmlError& e) {
        out.warnings.push_back("XML \xE4\xBA\x95\xE4\xBD\x8D\xE8\xA7\xA3\xE6\x9E\x90\xE5\xA4\xB1\xE8\xB4\xA5: " +
                               e.class_name);  // "XML 井位解析失败: "
        return out;
    }

    std::vector<std::pair<std::string, std::string>> root_values;
    for (const auto& [key, value] : root->attrib) {
        std::string stripped = py_strip(value);
        if (!stripped.empty()) {
            root_values.emplace_back(location_key_normalize(key), stripped);
        }
    }
    std::string inherited_crs = first_value(crs_keys(), root_values);

    auto records = spreadsheet_records(*root, inherited_crs);
    if (!records.empty()) {
        out.records = std::move(records);
        return out;
    }

    std::set<std::tuple<std::string, long long, long long>> seen;
    std::vector<const XmlNode*> elements;
    root->iter(elements);
    for (const XmlNode* element : elements) {
        const auto& children = element->children;
        if (children.empty()) continue;
        std::vector<std::pair<std::string, std::string>> values;
        for (const auto& child : children) {
            std::string text = py_strip(child->text);
            if (!text.empty()) {
                std::string normalized = location_key_normalize(child->tag);
                // dict comprehension: a later duplicate child key overwrites
                bool replaced = false;
                for (auto& [k, v] : values) {
                    if (k == normalized) {
                        v = text;
                        replaced = true;
                    }
                }
                if (!replaced) values.emplace_back(normalized, text);
            }
        }
        for (const auto& [key, value] : element->attrib) {
            std::string stripped = py_strip(value);
            if (!stripped.empty()) {
                std::string normalized = location_key_normalize(key);
                // attrib overrides same-key child text
                bool replaced = false;
                for (auto& [k, v] : values) {
                    if (k == normalized) {
                        v = stripped;
                        replaced = true;
                    }
                }
                if (!replaced) values.emplace_back(normalized, stripped);
            }
        }
        std::string tag = location_key_normalize(element->tag);
        bool is_well_element =
            tag.find("well") != std::string::npos ||
            tag.find("\xE4\xBA\x95") != std::string::npos;  // 井
        auto record = record_from_values(values, inherited_crs, is_well_element);
        if (!record) continue;
        // Python dedups on (name, x, y); doubles travel as bit patterns so
        // NaN (never equal in Python) keeps that behavior here too.
        static_assert(sizeof(double) == sizeof(long long), "layout");
        long long x_bits = 0, y_bits = 0;
        std::memcpy(&x_bits, &record->x, sizeof(double));
        std::memcpy(&y_bits, &record->y, sizeof(double));
        auto key = std::make_tuple(record->name, x_bits, y_bits);
        if (seen.count(key)) continue;
        seen.insert(key);
        out.records.push_back(std::move(*record));
        if (out.records.size() >= kMaxRecords) break;
    }
    return out;
}

bool is_well_location_xml_bytes(std::string_view bytes) {
    auto result = extract_well_locations_xml_bytes(bytes);
    return !result.records.empty();
}

size_t well_location_max_records() { return kMaxRecords; }
size_t well_log_xml_max_elements() { return kMaxElements; }

const std::vector<std::string>& well_log_spreadsheet_names() {
    static const std::vector<std::string> names = {
        "\xE6\xB5\x8B\xE4\xBA\x95\xE6\x9B\xB2\xE7\xBA\xBF",
        "welllog", "well log", "log curves",
    };
    return names;
}

}  // namespace pwb::ingest
