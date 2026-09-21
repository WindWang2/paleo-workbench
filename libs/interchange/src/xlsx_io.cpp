#include "xlsx_io.hpp"

#include <charconv>
#include <cstring>
#include <filesystem>
#include <stdexcept>

#include <pwb/ingest/xml_scanner.hpp>
#include <pwb/interchange/zip_archive.hpp>

namespace pwb::interchange::xlsx {

namespace {

[[noreturn]] void fail(const std::string& what) {
    throw std::runtime_error("xlsx: " + what);
}

// ElementTree "{uri}local" → "local" (OOXML default-ns tags).
std::string_view local(std::string_view tag) {
    const auto pos = tag.rfind('}');
    return pos == std::string_view::npos ? tag : tag.substr(pos + 1);
}

std::string read_member(const ZipReader& zip, const std::string& name) {
    const ZipEntryInfo* entry = zip.find(name);
    if (entry == nullptr) fail(std::string("missing ") + name);
    return zip.read_entry_bytes(*entry);
}

// XML text escaping for the writer (&, <, > in text; plus " in attributes).
std::string escape(std::string_view text, bool attr) {
    std::string out;
    out.reserve(text.size());
    for (const char c : text) {
        switch (c) {
        case '&': out += "&amp;"; break;
        case '<': out += "&lt;"; break;
        case '>': out += "&gt;"; break;
        case '"': out += attr ? "&quot;" : "\""; break;
        default: out += c;
        }
    }
    return out;
}

// pandas dtype vocabulary for one JSON cell → xlsx cell type.
// Numbers write raw (<v>), strings/bools as inlineStr/b.
std::string cell_xml(const domain::Json& value, const char* ref) {
    if (value.is_number()) {
        std::string num;
        if (value.is_number_integer() || value.is_number_unsigned()) {
            num = std::to_string(value.get<long long>());
        } else {
            double d = value.get<double>();
            char buf[64];
            auto [ptr, ec] =
                std::to_chars(buf, buf + sizeof(buf), d);
            num.assign(buf, ptr);
        }
        return std::string("<c r=\"") + ref + "\"><v>" + num + "</v></c>";
    }
    if (value.is_boolean()) {
        return std::string("<c r=\"") + ref +
               "\" t=\"b\"><v>" + (value.get<bool>() ? "1" : "0") +
               "</v></c>";
    }
    if (value.is_string()) {
        return std::string("<c r=\"") + ref + "\" t=\"inlineStr\"><is><t>" +
               escape(value.get<std::string>(), false) + "</t></is></c>";
    }
    // null → empty cell (pandas writes NaN/None as blank).
    return std::string("<c r=\"") + ref + "\"/>";
}

// A1-style column letters (1-based index).
std::string col_letter(std::size_t index) {
    std::string out;
    for (std::size_t n = index + 1; n > 0; n = (n - 1) / 26) {
        out.insert(out.begin(),
                   static_cast<char>('A' + (n - 1) % 26));
    }
    return out;
}

// "B12" → (row 12, col 1). Returns false on malformed refs.
bool parse_ref(std::string_view ref, std::size_t& row, std::size_t& col) {
    std::size_t i = 0;
    col = 0;
    while (i < ref.size() && ref[i] >= 'A' && ref[i] <= 'Z') {
        col = col * 26 + static_cast<std::size_t>(ref[i] - 'A' + 1);
        ++i;
    }
    if (i == 0 || i == ref.size()) return false;
    row = 0;
    for (; i < ref.size(); ++i) {
        if (ref[i] < '0' || ref[i] > '9') return false;
        row = row * 10 + static_cast<std::size_t>(ref[i] - '0');
    }
    if (col > 0) --col;
    return row > 0;
}

// pandas column dedup (read_* "mangle_dupe_cols"): a, a → a, a.1.
std::vector<std::string> mangle_columns(
    const std::vector<domain::Json>& header) {
    std::vector<std::string> cols;
    cols.reserve(header.size());
    std::unordered_map<std::string, int> seen;
    for (const auto& cell : header) {
        std::string name =
            cell.is_null() ? std::string("Unnamed: ") +
                                 std::to_string(cols.size())
                         : cell.is_string() ? cell.get<std::string>()
                                            : cell.dump();
        auto& count = seen[name];
        if (count++ > 0) name += "." + std::to_string(count - 1);
        cols.push_back(std::move(name));
    }
    return cols;
}

}  // namespace

Table read_xlsx(const std::filesystem::path& file) {
    ZipReader zip(file);

    // shared strings (optional — inlineStr cells need none).
    std::vector<std::string> shared;
    if (const ZipEntryInfo* ss = zip.find("xl/sharedStrings.xml")) {
        const auto root =
            ingest::xml_parse(zip.read_entry_bytes(*ss));
        if (root == nullptr) fail("unreadable sharedStrings.xml");
        std::vector<const ingest::XmlNode*> nodes;
        root->iter(nodes);
        for (const auto* node : nodes) {
            if (local(node->tag) == "si") shared.push_back(node->itertext());
        }
    }

    // First worksheet: sheets order in workbook.xml.
    std::string sheet_name = "Sheet1";
    std::string first_sheet = "xl/worksheets/sheet1.xml";
    {
        const auto wb = ingest::xml_parse(read_member(zip, "xl/workbook.xml"));
        if (wb == nullptr) fail("unreadable workbook.xml");
        std::vector<const ingest::XmlNode*> nodes;
        wb->iter(nodes);
        for (const auto* node : nodes) {
            if (local(node->tag) == "sheet") {
                const auto* name_attr = node->attr("name");
                if (name_attr != nullptr) sheet_name = *name_attr;
                const auto* rid = node->attr("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id");
                if (rid == nullptr) rid = node->attr("r:id");
                if (rid != nullptr) {
                    // Resolve rId → target via workbook rels.
                    const auto rels = ingest::xml_parse(
                        read_member(zip, "xl/_rels/workbook.xml.rels"));
                    if (rels != nullptr) {
                        std::vector<const ingest::XmlNode*> rel_nodes;
                        rels->iter(rel_nodes);
                        for (const auto* rel : rel_nodes) {
                            const auto* id = rel->attr("Id");
                            const auto* target = rel->attr("Target");
                            if (id != nullptr && target != nullptr &&
                                *id == *rid) {
                                first_sheet = "xl/" + *target;
                            }
                        }
                    }
                }
                break;
            }
        }
    }

    const auto sheet =
        ingest::xml_parse(read_member(zip, first_sheet));
    if (sheet == nullptr) fail("unreadable " + first_sheet);

    // Row-major cell grid (sparse refs expanded).
    std::vector<std::vector<domain::Json>> grid;
    std::vector<const ingest::XmlNode*> nodes;
    sheet->iter(nodes);
    for (const auto* node : nodes) {
        if (local(node->tag) != "row") continue;
        std::vector<domain::Json> row;
        for (const auto& cell : node->children) {
            if (local(cell->tag) != "c") continue;
            std::size_t col = row.size();
            if (const auto* ref = cell->attr("r")) {
                std::size_t r = 0, c = 0;
                if (parse_ref(*ref, r, c)) col = c;
            }
            while (row.size() <= col) row.emplace_back(nullptr);
            const std::string type =
                cell->attr("t") != nullptr ? *cell->attr("t") : "n";
            std::string v;
            std::string inline_text;
            for (const auto& sub : cell->children) {
                if (local(sub->tag) == "v") v = sub->itertext();
                if (local(sub->tag) == "is") inline_text = sub->itertext();
            }
            domain::Json value = nullptr;
            if (type == "s") {
                std::size_t idx = 0;
                const char* p = v.c_str();
                auto [end, ec] = std::from_chars(p, p + v.size(), idx);
                value = (ec == std::errc{} && idx < shared.size())
                            ? domain::Json(shared[idx])
                            : domain::Json(nullptr);
            } else if (type == "inlineStr") {
                value = inline_text;
            } else if (type == "str") {
                value = v;
            } else if (type == "b") {
                value = v == "1";
            } else if (type == "e") {
                value = v;  // error cells surface as their literal text
            } else if (!v.empty()) {
                double d = 0;
                const char* p = v.c_str();
                auto [end, ec] =
                    std::from_chars(p, p + v.size(), d);
                if (ec == std::errc{} && end == p + v.size()) {
                    // Keep int64 when integral and in range (pandas readback
                    // reports int64 for whole-number columns).
                    long long i = 0;
                    auto [ie, ic] = std::from_chars(p, p + v.size(), i);
                    value = (ic == std::errc{} && ie == p + v.size())
                                ? domain::Json(i)
                                : domain::Json(d);
                } else {
                    value = v;
                }
            }
            row[col] = std::move(value);
        }
        grid.push_back(std::move(row));
    }

    Table table;
    table.sheet_name = sheet_name;
    if (grid.empty()) return table;
    table.columns = mangle_columns(grid.front());
    table.rows.assign(grid.begin() + 1, grid.end());
    for (auto& row : table.rows) row.resize(table.columns.size(), nullptr);
    return table;
}

void write_xlsx(const std::filesystem::path& file,
                const std::vector<std::string>& columns,
                const std::vector<std::vector<domain::Json>>& rows,
                const std::optional<std::string>& index_name,
                const std::optional<std::vector<domain::Json>>& index_values,
                const std::string& sheet_name) {
    const bool with_index = index_values.has_value();
    if (with_index && index_values->size() != rows.size()) {
        throw std::runtime_error("xlsx: index/row count mismatch");
    }

    std::string sheet;
    sheet += "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
             "<worksheet xmlns=\"http://schemas.openxmlformats.org/"
             "spreadsheetml/2006/main\"><sheetData>";
    // Header row: pandas writes the index-name cell (blank when unnamed)
    // then the column labels.
    {
        std::string head = "<row r=\"1\">";
        std::size_t col = 0;
        if (with_index) {
            head += "<c r=\"A1\" t=\"inlineStr\"><is><t>" +
                    escape(index_name.value_or(""), false) +
                    "</t></is></c>";
            col = 1;
        }
        for (const auto& name : columns) {
            const std::string ref =
                col_letter(col) + "1";
            head += "<c r=\"" + ref + "\" t=\"inlineStr\"><is><t>" +
                    escape(name, false) + "</t></is></c>";
            ++col;
        }
        sheet += head + "</row>";
    }
    for (std::size_t r = 0; r < rows.size(); ++r) {
        std::string row_xml = "<row r=\"" + std::to_string(r + 2) + "\">";
        std::size_t col = 0;
        if (with_index) {
            const std::string ref = "A" + std::to_string(r + 2);
            row_xml += cell_xml((*index_values)[r], ref.c_str());
            col = 1;
        }
        const auto& row = rows[r];
        for (std::size_t c = 0; c < row.size(); ++c) {
            const std::string ref =
                col_letter(col + c) + std::to_string(r + 2);
            row_xml += cell_xml(row[c], ref.c_str());
        }
        sheet += row_xml + "</row>";
    }
    sheet += "</sheetData></worksheet>";

    ZipWriter zip(file);
    zip.add_bytes(
        "[Content_Types].xml",
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/"
        "content-types\">"
        "<Default Extension=\"rels\" ContentType=\"application/vnd."
        "openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        "<Override PartName=\"/xl/workbook.xml\" ContentType=\"application/"
        "vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>"
        "<Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType="
        "\"application/vnd.openxmlformats-officedocument.spreadsheetml."
        "worksheet+xml\"/>"
        "</Types>");
    zip.add_bytes(
        "_rels/.rels",
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/"
        "2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/"
        "officeDocument/2006/relationships/officeDocument\" Target=\"xl/"
        "workbook.xml\"/>"
        "</Relationships>");
    zip.add_bytes(
        "xl/workbook.xml",
        std::string(
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            "<workbook xmlns=\"http://schemas.openxmlformats.org/"
            "spreadsheetml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/"
            "officeDocument/2006/relationships\"><sheets><sheet name=\"") +
            escape(sheet_name, true) +
            "\" sheetId=\"1\" r:id=\"rId1\"/></sheets></workbook>");
    zip.add_bytes(
        "xl/_rels/workbook.xml.rels",
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/"
        "2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/"
        "officeDocument/2006/relationships/worksheet\" Target=\"worksheets/"
        "sheet1.xml\"/>"
        "</Relationships>");
    zip.add_bytes("xl/worksheets/sheet1.xml", sheet);
    zip.finish();
}

}  // namespace pwb::interchange::xlsx
