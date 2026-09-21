#include "pwb/interchange/exporters.hpp"

#include <charconv>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <unordered_map>

#include <pwb/domain/json.hpp>
#include <pwb/domain/text.hpp>
#include <pwb/ingest/preview/text_parsers.hpp>
#include <pwb/interchange/atomic_file.hpp>
#include <pwb/interchange/unicode.hpp>
#include <pwb/seismic_io/segy_layout.hpp>

#include "xlsx_io.hpp"

namespace pwb::interchange {

using domain::Json;

namespace {

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

std::string read_text_file(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("无法读取: " + path.string());
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

void write_text(const fs::path& path, std::string_view text) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) throw std::runtime_error("无法写入: " + path.string());
    out.write(text.data(), static_cast<std::streamsize>(text.size()));
    if (!out) throw std::runtime_error("写入失败: " + path.string());
}

// Python repr(float) / pandas float cell formatting: shortest round-trip
// digits; integral floats keep ".0"; NaN → "" (csv) is handled by callers.
std::string py_float_repr(double value) {
    if (std::isnan(value)) return "nan";
    if (std::isinf(value)) return value < 0 ? "-inf" : "inf";
    char buf[64];
    auto [ptr, ec] = std::to_chars(buf, buf + sizeof(buf), value);
    std::string out(buf, ptr);
    if (out.find_first_of(".eE") == std::string::npos) out += ".0";
    // Python repr uses "e+NN"/"e-NN" with at least two exponent digits.
    const auto epos = out.find_first_of("eE");
    if (epos != std::string::npos) {
        std::string mant = out.substr(0, epos);
        std::string exp = out.substr(epos + 1);
        bool neg = !exp.empty() && exp.front() == '-';
        if (neg) exp.erase(exp.begin());
        if (exp.front() == '+') exp.erase(exp.begin());
        while (exp.size() < 2) exp.insert(exp.begin(), '0');
        out = mant + (neg ? "e-" : "e+") + exp;
    }
    return out;
}

// json.dumps(payload, ensure_ascii=False, indent=2) parity: nlohmann
// dump(2) matches Python's (',', ': ') separators + 2-space indent; the
// file gets no trailing newline either way.
void write_json_indented(const fs::path& path, const Json& payload) {
    write_text(path, payload.dump(2));
}

std::string lower_ext(const fs::path& path) {
    std::string ext = path.extension().string();
    if (!ext.empty() && ext.front() == '.') ext.erase(ext.begin());
    return domain::lower_ascii(ext);
}

// ---------------------------------------------------------------------------
// LAS parse (lasio parity for the export surface: ~C curve headers, ~W
// WELL/WN/UWI + NULL., ~A whitespace rows; WRAP: YES folds physical lines).
// ---------------------------------------------------------------------------

struct LasData {
    struct Curve {
        std::string mnemonic;
        std::string unit;
        std::string descr;
    };
    std::vector<Curve> curves;   // ~C order (depth channel included)
    std::string well_name;       // WELL/WN/UWI first non-empty
    double null_value = std::numeric_limits<double>::quiet_NaN();
    bool has_null = false;
    bool wrapped = false;
    // row-major samples, curves.size() columns; nulls already NaN
    std::vector<std::vector<double>> rows;
};

std::string_view trim_sv(std::string_view s) {
    const auto b = s.find_first_not_of(" \t\r\n");
    if (b == std::string_view::npos) return {};
    const auto e = s.find_last_not_of(" \t\r\n");
    return s.substr(b, e - b + 1);
}

std::string_view first_token(std::string_view s) {
    s = trim_sv(s);
    const auto e = s.find_first_of(" \t");
    return e == std::string_view::npos ? s : s.substr(0, e);
}

std::string upper_ascii(std::string_view s) {
    std::string out(s);
    for (char& c : out) c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    return out;
}

// "~W"-section item: MNEMONIC.value : descr → (MNEMONIC, value).
std::optional<std::pair<std::string, std::string>> las_item(
    std::string_view line) {
    const auto colon = line.find(':');
    const std::string_view left =
        colon == std::string_view::npos ? line : line.substr(0, colon);
    const auto dot = left.find('.');
    if (dot == std::string_view::npos) return std::nullopt;
    return std::make_pair(
        upper_ascii(trim_sv(left.substr(0, dot))),
        std::string(trim_sv(left.substr(dot + 1))));
}

LasData parse_las(std::string_view bytes) {
    enum class Section { none, version, well, curve, ascii, other };
    Section section = Section::none;
    bool saw_section = false;
    LasData data;
    std::vector<std::string> tokens;

    std::string_view rest(bytes);
    while (!rest.empty()) {
        const auto nl = rest.find('\n');
        const std::string_view raw =
            rest.substr(0, nl == std::string_view::npos ? rest.size() : nl);
        rest = nl == std::string_view::npos ? std::string_view{}
                                            : rest.substr(nl + 1);
        const std::string_view line = trim_sv(raw);
        if (line.empty() || line.front() == '#') continue;
        if (line.front() == '~') {
            saw_section = true;
            const auto heading = upper_ascii(trim_sv(line.substr(1)));
            if (heading.empty()) {
                section = Section::none;
            } else {
                switch (heading.front()) {
                case 'V': section = Section::version; break;
                case 'W': section = Section::well; break;
                case 'C': section = Section::curve; break;
                case 'A': section = Section::ascii; break;
                default: section = Section::other; break;
                }
            }
            continue;
        }
        switch (section) {
        case Section::version:
            if (auto item = las_item(line)) {
                if (item->first == "WRAP") {
                    const auto v = upper_ascii(first_token(item->second));
                    data.wrapped =
                        v == "YES" || v == "Y" || v == "TRUE" || v == "1";
                }
            }
            break;
        case Section::well:
            if (auto item = las_item(line)) {
                if (item->first == "NULL") {
                    double v = 0;
                    const char* p = item->second.c_str();
                    auto [end, ec] =
                        std::from_chars(p, p + item->second.size(), v);
                    if (ec == std::errc{}) {
                        data.null_value = v;
                        data.has_null = true;
                    }
                } else if (data.well_name.empty() &&
                           (item->first == "WELL" || item->first == "WN" ||
                            item->first == "UWI")) {
                    data.well_name = item->second;
                }
            }
            break;
        case Section::curve: {
            const auto colon = line.find(':');
            const std::string_view def =
                colon == std::string_view::npos ? line
                                                : line.substr(0, colon);
            const std::string_view descr =
                colon == std::string_view::npos
                    ? std::string_view{}
                    : trim_sv(line.substr(colon + 1));
            const auto dot = def.find('.');
            if (dot == std::string_view::npos) break;
            const std::string_view mnemonic = trim_sv(def.substr(0, dot));
            if (mnemonic.empty()) break;
            LasData::Curve c;
            c.mnemonic = std::string(mnemonic);
            c.unit = std::string(first_token(def.substr(dot + 1)));
            c.descr = std::string(descr);
            data.curves.push_back(std::move(c));
            break;
        }
        case Section::ascii: {
            // whitespace-token stream; WRAP folds physical lines.
            std::string_view s = line;
            while (!s.empty()) {
                const auto sp = s.find_first_of(" \t");
                tokens.emplace_back(s.substr(0, sp));
                s = sp == std::string_view::npos
                        ? std::string_view{}
                        : trim_sv(s.substr(sp));
            }
            break;
        }
        default: break;
        }
    }

    if (!saw_section)
        throw std::runtime_error(
            "'No ~ sections found. Is this a LAS file?'");
    if (data.curves.empty())
        throw std::runtime_error("LAS contains no curve headers");

    const std::size_t width = data.curves.size();
    data.rows.reserve(tokens.size() / width);
    for (std::size_t i = 0; i + width <= tokens.size(); i += width) {
        std::vector<double> row(width);
        for (std::size_t c = 0; c < width; ++c) {
            const std::string& tok = tokens[i + c];
            double v = std::numeric_limits<double>::quiet_NaN();
            const char* p = tok.c_str();
            auto [end, ec] = std::from_chars(p, p + tok.size(), v);
            if (ec != std::errc{} || end != p + tok.size())
                throw std::runtime_error("LAS data token 不可解析: " + tok);
            if (data.has_null && v == data.null_value)
                v = std::numeric_limits<double>::quiet_NaN();
            row[c] = v;
        }
        data.rows.push_back(std::move(row));
    }
    // lasio drops a trailing partial row silently — the width loop already
    // enforces that.
    return data;
}

// pandas df.to_csv(index=True): header "<index_name>,c1,c2,..." then
// "<index_value>,v1,v2,..." rows; NaN → empty; '\n' line endings.
void las_write_csv(const LasData& las, const fs::path& out) {
    std::string text;
    if (!las.curves.empty()) text += las.curves[0].mnemonic;
    for (std::size_t c = 1; c < las.curves.size(); ++c) {
        text += ',';
        text += las.curves[c].mnemonic;
    }
    text += '\n';
    for (const auto& row : las.rows) {
        for (std::size_t c = 0; c < row.size(); ++c) {
            if (c) text += ',';
            if (row[c] == row[c]) text += py_float_repr(row[c]);
        }
        text += '\n';
    }
    AtomicOutputFile atomic(out);
    write_text(atomic.temp_path(), text);
    atomic.commit();
}

// ---------------------------------------------------------------------------
// pandas-flavored table model for table_to_json / table_to_xlsx
// ---------------------------------------------------------------------------

// Default NA sentinel set (pandas 2.x read_csv defaults) — read_csv parity.
bool is_na_token(std::string_view s) {
    static const char* kNa[] = {
        "",      "#N/A",   "#N/A N/A", "#NA",   "-1.#IND", "-1.#QNAN",
        "-NaN",  "-nan",   "1.#IND",   "1.#QNAN", "<NA>",   "N/A",
        "NA",    "NULL",   "NaN",      "None",   "n/a",    "nan",
        "null",
    };
    for (const char* tok : kNa) {
        if (s == tok) return true;
    }
    return false;
}

bool parse_int64(std::string_view s, long long& out) {
    const char* p = s.data();
    auto [end, ec] = std::from_chars(p, p + s.size(), out);
    return ec == std::errc{} && end == p + s.size();
}

bool parse_double(std::string_view s, double& out) {
    // strtod-based (from_chars misses "inf"/"nan" spellings pandas accepts).
    std::string tmp(s);
    char* end = nullptr;
    out = std::strtod(tmp.c_str(), &end);
    return end == tmp.c_str() + tmp.size() && end != tmp.c_str();
}

// pandas dtype inference over one column of raw string cells: int64 only
// when NO NA present (NaN promotes to float64); else float64 when every
// non-NA cell parses; else object (verbatim strings, NA → null).
std::vector<Json> infer_column(const std::vector<std::string>& cells) {
    const std::size_t n = cells.size();
    std::vector<bool> is_na(n, false);
    std::vector<long long> ints(n, 0);
    std::vector<double> reals(n, 0.0);
    bool any_na = false, all_int = true, all_num = true;
    for (std::size_t i = 0; i < n; ++i) {
        const std::string& cell = cells[i];
        if (is_na_token(cell)) {
            is_na[i] = true;
            any_na = true;
            continue;
        }
        if (!parse_int64(cell, ints[i])) all_int = false;
        if (!parse_double(cell, reals[i])) all_num = false;
    }
    std::vector<Json> out(n);
    if (all_int && !any_na) {
        for (std::size_t i = 0; i < n; ++i) out[i] = ints[i];
    } else if (all_num) {
        for (std::size_t i = 0; i < n; ++i) {
            out[i] = is_na[i] ? Json(nullptr) : Json(reals[i]);
        }
    } else {
        for (std::size_t i = 0; i < n; ++i) {
            out[i] = is_na[i] ? Json(nullptr) : Json(cells[i]);
        }
    }
    return out;
}

// xlsx typed cells → the same per-column Json vector (read_excel parity:
// bool cols stay bool; numeric cols get the int64/float64 promotion).
std::vector<Json> coerce_xlsx_column(const std::vector<Json>& cells) {
    const std::size_t n = cells.size();
    bool any_na = false, all_bool = true, all_num = true, all_int = true;
    for (const auto& cell : cells) {
        if (cell.is_null()) {
            any_na = true;
            continue;
        }
        if (!cell.is_boolean()) all_bool = false;
        if (!cell.is_number()) all_num = false;
        else if (!(cell.is_number_integer() || cell.is_number_unsigned()))
            all_int = false;
    }
    std::vector<Json> out(n);
    if (all_bool) {
        for (std::size_t i = 0; i < n; ++i)
            out[i] = cells[i].is_null() ? Json(nullptr) : cells[i];
    } else if (all_num && all_int && !any_na) {
        for (std::size_t i = 0; i < n; ++i) out[i] = cells[i];
    } else if (all_num) {
        for (std::size_t i = 0; i < n; ++i) {
            out[i] = cells[i].is_null()
                         ? Json(nullptr)
                         : Json(cells[i].get<double>());
        }
    } else {
        for (std::size_t i = 0; i < n; ++i) out[i] = cells[i];
    }
    return out;
}

// to_json(orient="records", force_ascii=False) parity: [{col: val}, ...]
// compact separators, ints bare, floats repr, NaN → null.
Json records_json(const std::vector<std::string>& columns,
                  const std::vector<std::vector<Json>>& data) {
    Json out = Json::array();
    if (data.empty()) return out;
    const std::size_t n = data[0].size();
    for (std::size_t r = 0; r < n; ++r) {
        Json row = Json::object();
        for (std::size_t c = 0; c < columns.size(); ++c) {
            row[columns[c]] = data[c][r];
        }
        out.push_back(std::move(row));
    }
    return out;
}

// pandas to_json compact separators: {"a":1,"b":"x"}.
std::string dumps_compact(const Json& value) {
    std::string out;
    if (value.is_object()) {
        out += '{';
        bool first = true;
        for (auto it = value.begin(); it != value.end(); ++it) {
            if (!first) out += ',';
            first = false;
            out += '"';
            out += it.key();
            out += "\":";
            out += dumps_compact(it.value());
        }
        out += '}';
    } else if (value.is_array()) {
        out += '[';
        bool first = true;
        for (const auto& item : value) {
            if (!first) out += ',';
            first = false;
            out += dumps_compact(item);
        }
        out += ']';
    } else if (value.is_string()) {
        out = value.dump();  // JSON string escaping matches
    } else if (value.is_boolean()) {
        out = value.get<bool>() ? "true" : "false";
    } else if (value.is_null()) {
        out = "null";
    } else if (value.is_number_integer() || value.is_number_unsigned()) {
        out = std::to_string(value.get<long long>());
    } else {
        const double d = value.get<double>();
        out = (d == d) ? py_float_repr(d) : "null";
    }
    return out;
}

// read_csv parity subset: header row + dtype-inferred columns.
void read_csv_table(const fs::path& path, std::vector<std::string>& columns,
                    std::vector<std::vector<Json>>& data) {
    const auto grid = ingest::preview::csv_reader(read_text_file(path), ',');
    if (grid.empty()) {
        columns.clear();
        data.clear();
        return;
    }
    // mangle dupe headers (pandas "a", "a" → "a", "a.1"; empty → Unnamed: N)
    columns.clear();
    std::unordered_map<std::string, int> seen;
    for (std::size_t i = 0; i < grid.front().size(); ++i) {
        const std::string& name = grid.front()[i];
        std::string col =
            name.empty() ? "Unnamed: " + std::to_string(i) : name;
        auto& count = seen[col];
        if (count++ > 0) col += "." + std::to_string(count - 1);
        columns.push_back(std::move(col));
    }
    const std::size_t ncols = columns.size();
    std::vector<std::vector<std::string>> col_cells(ncols);
    for (std::size_t r = 1; r < grid.size(); ++r) {
        for (std::size_t c = 0; c < ncols; ++c) {
            col_cells[c].push_back(
                c < grid[r].size() ? grid[r][c] : std::string());
        }
    }
    data.clear();
    for (auto& cells : col_cells) data.push_back(infer_column(cells));
}

// xlsx → same column model (read_excel parity: first sheet, header row 0).
void read_xlsx_table(const fs::path& path,
                     std::vector<std::string>& columns,
                     std::vector<std::vector<Json>>& data) {
    const xlsx::Table table = xlsx::read_xlsx(path);
    columns = table.columns;
    const std::size_t ncols = columns.size();
    std::vector<std::vector<Json>> col_cells(ncols);
    for (const auto& row : table.rows) {
        for (std::size_t c = 0; c < ncols; ++c) {
            col_cells[c].push_back(c < row.size() ? row[c] : Json(nullptr));
        }
    }
    data.clear();
    for (auto& cells : col_cells) data.push_back(coerce_xlsx_column(cells));
}

// DataFrame → xlsx cell grid (column values in declared order).
void write_table_xlsx(const fs::path& out,
                      const std::vector<std::string>& columns,
                      const std::vector<std::vector<Json>>& data,
                      bool with_index) {
    const std::size_t n = data.empty() ? 0 : data[0].size();
    std::vector<std::vector<Json>> rows(n);
    std::vector<Json> index_values;
    for (std::size_t r = 0; r < n; ++r) {
        rows[r].reserve(columns.size());
        if (with_index) index_values.push_back(Json(static_cast<long long>(r)));
        for (const auto& col : data) rows[r].push_back(col[r]);
    }
    xlsx::write_xlsx(out, columns, rows,
                     with_index ? std::optional<std::string>("")
                                : std::nullopt,
                     with_index ? std::optional(index_values)
                                : std::nullopt);
}

// ---------------------------------------------------------------------------
// Image provider seam
// ---------------------------------------------------------------------------

ImagePngProvider& image_provider_slot() {
    static ImagePngProvider provider;
    return provider;
}

}  // namespace

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

std::string extension_for_label(std::string_view label) {
    static const std::unordered_map<std::string, std::string> kExt = {
        {"CSV", ".csv"},   {"JSON", ".json"},     {"XLSX", ".xlsx"},
        {"PNG", ".png"},   {"TXT", ".txt"},       {"GeoJSON", ".geojson"},
        {"SUMMARY", ".summary.json"}, {"INVENTORY", ".inventory.json"},
    };
    const auto it = kExt.find(std::string(label));
    return it == kExt.end() ? ".out" : it->second;
}

const std::vector<ConverterSpec>& converters() {
    static const std::vector<ConverterSpec> kConverters = {
        {"CSV", {"las"}, las_to_csv},
        {"XLSX", {"las"}, las_to_xlsx},
        {"JSON", {"las"}, las_to_json_summary},
        {"JSON", {"csv", "xlsx", "xls"}, table_to_json},
        {"XLSX", {"csv"}, table_to_xlsx},
        {"PNG", {"tif", "tiff", "png", "jpg", "jpeg", "bmp"}, image_to_png},
        {"TXT", {"txt", "md", "markdown", "json", "xml", "log", "dat"},
         text_to_txt},
        {"GeoJSON", {"geojson", "json"}, geojson_normalize},
        {"SUMMARY", {"sgy", "segy"}, seismic_to_summary_json},
    };
    return kConverters;
}

std::vector<std::pair<std::string, ConvertFn>> get_available_formats(
    std::string_view format) {
    std::string fmt(domain::lower_ascii(format));
    if (!fmt.empty() && fmt.front() == '.') fmt.erase(fmt.begin());
    std::unordered_set<std::string> seen;
    std::vector<std::pair<std::string, ConvertFn>> out;
    for (const auto& spec : converters()) {
        if (spec.inputs.count(fmt) && seen.insert(spec.label).second) {
            out.emplace_back(spec.label, spec.fn);
        }
    }
    return out;
}

void set_image_png_provider(ImagePngProvider provider) {
    image_provider_slot() = std::move(provider);
}

bool image_png_provider_installed() {
    return static_cast<bool>(image_provider_slot());
}

// ---------------------------------------------------------------------------
// Converters
// ---------------------------------------------------------------------------

void las_to_csv(const fs::path& input, const fs::path& output) {
    try {
        las_write_csv(parse_las(read_text_file(input)), output);
    } catch (const ExportError&) {
        throw;
    } catch (const std::exception& exc) {
        throw ExportError(std::string("LAS -> CSV 失败: ") + exc.what());
    }
}

void las_to_xlsx(const fs::path& input, const fs::path& output) {
    try {
        const LasData las = parse_las(read_text_file(input));
        std::vector<std::string> columns;
        for (std::size_t c = 1; c < las.curves.size(); ++c)
            columns.push_back(las.curves[c].mnemonic);
        std::vector<std::vector<Json>> rows(las.rows.size());
        std::vector<Json> index_values;
        for (std::size_t r = 0; r < las.rows.size(); ++r) {
            const auto& row = las.rows[r];
            index_values.push_back(
                row[0] == row[0] ? Json(row[0]) : Json(nullptr));
            for (std::size_t c = 1; c < row.size(); ++c) {
                rows[r].push_back(row[c] == row[c] ? Json(row[c])
                                                 : Json(nullptr));
            }
        }
        AtomicOutputFile atomic(output);
        xlsx::write_xlsx(atomic.temp_path(), columns, rows,
                         las.curves.empty()
                             ? std::nullopt
                             : std::optional<std::string>(
                                   las.curves[0].mnemonic),
                         index_values);
        atomic.commit();
    } catch (const ExportError&) {
        throw;
    } catch (const std::exception& exc) {
        throw ExportError(std::string("LAS -> XLSX 失败: ") + exc.what());
    }
}

void las_to_json_summary(const fs::path& input, const fs::path& output) {
    try {
        const LasData las = parse_las(read_text_file(input));
        Json curves = Json::array();
        for (const auto& c : las.curves) {
            curves.push_back(Json::object({{"mnemonic", c.mnemonic},
                                           {"unit", c.unit},
                                           {"descr", c.descr}}));
        }
        Json payload = Json::object();
        payload["source"] = input.string();
        payload["well_name"] =
            las.well_name.empty() ? input.stem().string() : las.well_name;
        payload["curve_count"] = las.curves.size();
        payload["curves"] = std::move(curves);
        AtomicOutputFile atomic(output);
        write_json_indented(atomic.temp_path(), payload);
        atomic.commit();
    } catch (const std::exception& exc) {
        throw ExportError(std::string("LAS -> JSON 摘要失败: ") + exc.what());
    }
}

void table_to_json(const fs::path& input, const fs::path& output) {
    try {
        const std::string ext = lower_ext(input);
        std::vector<std::string> columns;
        std::vector<std::vector<Json>> data;
        if (ext == "csv") {
            read_csv_table(input, columns, data);
        } else {
            read_xlsx_table(input, columns, data);
        }
        const Json records = records_json(columns, data);
        AtomicOutputFile atomic(output);
        write_text(atomic.temp_path(), dumps_compact(records));
        atomic.commit();
    } catch (const ExportError&) {
        throw;
    } catch (const std::exception& exc) {
        throw ExportError(std::string("表格 -> JSON 失败: ") + exc.what());
    }
}

void table_to_xlsx(const fs::path& input, const fs::path& output) {
    try {
        const std::string ext = lower_ext(input);
        std::vector<std::string> columns;
        std::vector<std::vector<Json>> data;
        if (ext == "csv") {
            read_csv_table(input, columns, data);
        } else if (ext == "xlsx" || ext == "xls") {
            read_xlsx_table(input, columns, data);
        } else {
            throw ExportError("不支持的表格格式: " + ext);
        }
        AtomicOutputFile atomic(output);
        write_table_xlsx(atomic.temp_path(), columns, data,
                         /*with_index=*/false);
        atomic.commit();
    } catch (const ExportError&) {
        throw;
    } catch (const std::exception& exc) {
        throw ExportError(std::string("表格 -> XLSX 失败: ") + exc.what());
    }
}

void image_to_png(const fs::path& input, const fs::path& output) {
    try {
        const auto& provider = image_provider_slot();
        if (!provider) {
            throw std::runtime_error(
                "图像解码不可用（宿主未安装图像提供者）");
        }
        AtomicOutputFile atomic(output);
        if (!provider(input, atomic.temp_path())) {
            throw std::runtime_error("图像解码失败");
        }
        atomic.commit();
    } catch (const ExportError&) {
        throw;
    } catch (const std::exception& exc) {
        throw ExportError(std::string("图像 -> PNG 失败: ") + exc.what());
    }
}

void text_to_txt(const fs::path& input, const fs::path& output) {
    try {
        // Python read_text(encoding="utf-8", errors="replace") → write_text
        const auto cps = utf8_to_codepoints(read_text_file(input));
        const std::string text = codepoints_to_utf8(cps);
        AtomicOutputFile atomic(output);
        write_text(atomic.temp_path(), text);
        atomic.commit();
    } catch (const std::exception& exc) {
        throw ExportError(std::string("文本 -> TXT 失败: ") + exc.what());
    }
}

void geojson_normalize(const fs::path& input, const fs::path& output) {
    try {
        const auto cps = utf8_to_codepoints(read_text_file(input));
        const std::string text = codepoints_to_utf8(cps);
        Json data = Json::parse(text);  // throws parse_error (ValueError-ish)
        if (!data.is_object()) {
            throw ExportError("GeoJSON 根节点必须是对象");
        }
        // Non-GeoJSON dict roots still normalize (Python pass-through).
        AtomicOutputFile atomic(output);
        write_json_indented(atomic.temp_path(), data);
        atomic.commit();
    } catch (const ExportError&) {
        throw;
    } catch (const std::exception& exc) {
        throw ExportError(std::string("GeoJSON 规范化失败: ") + exc.what());
    }
}

void seismic_to_summary_json(const fs::path& input, const fs::path& output) {
    try {
        std::string error;
        const auto layout = seismic_io::inspect_segy(input, &error);
        if (!layout.has_value()) {
            throw std::runtime_error(error.empty() ? "SEGY 检查失败" : error);
        }
        const auto& d = layout->descriptor;
        Json payload = Json::object();
        payload["source"] = input.string();
        payload["n_inlines"] = d.ni;
        payload["n_crosslines"] = d.nc;
        payload["n_samples"] = d.ns;
        payload["dt_ms"] = d.sample_step;
        payload["t0_ms"] = d.sample_start;
        payload["iline_start"] = d.iline_start;
        payload["iline_step"] = d.iline_step;
        payload["xline_start"] = d.xline_start;
        payload["xline_step"] = d.xline_step;
        AtomicOutputFile atomic(output);
        write_json_indented(atomic.temp_path(), payload);
        atomic.commit();
    } catch (const ExportError&) {
        throw;
    } catch (const std::exception& exc) {
        throw ExportError(std::string("SEGY -> 摘要 JSON 失败: ") + exc.what());
    }
}

}  // namespace pwb::interchange
