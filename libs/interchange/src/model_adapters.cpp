// Faithful port of paleo_workbench/interchange/adapters/model_adapter.py
// (conv-14b). Problem messages, check order and Python float()/int() parsing
// semantics are the contract — frozen in interchange_archive_oracle.json.

#include "pwb/interchange/model_adapters.hpp"

#include <pwb/interchange/atomic_file.hpp>
#include <pwb/interchange/path_safety.hpp>
#include <pwb/interchange/unicode.hpp>

#include <array>
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <limits>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

#include <pwb/geomodel/export_contract.hpp>

namespace pwb::interchange {

namespace {

// --- Python text semantics ---------------------------------------------------

// str.strip() / str.split() whitespace (the full Python set).
bool is_py_space(char32_t c) {
    switch (c) {
        case U'\t': case U'\n': case U'\v': case U'\f': case U'\r':
        case U' ': case 0x1C: case 0x1D: case 0x1E: case 0x1F: case 0x85:
        case 0xA0: case 0x1680: case 0x2028: case 0x2029: case 0x202F:
        case 0x205F: case 0x3000:
            return true;
        default:
            return c >= 0x2000 && c <= 0x200A;
    }
}

// Universal newlines over decoded code points: \r\n / \r / \n all end a line.
std::vector<std::string> split_lines(const std::u32string& cps) {
    std::vector<std::string> lines;
    std::u32string current;
    for (std::size_t i = 0; i < cps.size(); ++i) {
        const char32_t c = cps[i];
        if (c == U'\n') {
            lines.push_back(codepoints_to_utf8(current));
            current.clear();
        } else if (c == U'\r') {
            lines.push_back(codepoints_to_utf8(current));
            current.clear();
            if (i + 1 < cps.size() && cps[i + 1] == U'\n') ++i;
        } else {
            current.push_back(c);
        }
    }
    lines.push_back(codepoints_to_utf8(current));
    return lines;
}

// Python open(..., encoding="utf-8", errors="replace"): invalid UTF-8 bytes
// become U+FFFD before line splitting.
std::vector<std::string> read_lines_replace(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("could not open file: " + path.string());
    std::string bytes((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    return split_lines(utf8_to_codepoints(bytes));  // invalid -> U+FFFD
}

std::string py_strip(const std::string& text) {
    const std::u32string cps = utf8_to_codepoints(text);
    std::size_t begin = 0;
    std::size_t end = cps.size();
    while (begin < end && is_py_space(cps[begin])) ++begin;
    while (end > begin && is_py_space(cps[end - 1])) --end;
    return codepoints_to_utf8(cps.substr(begin, end - begin));
}

std::vector<std::string> py_split(const std::string& text) {
    const std::u32string cps = utf8_to_codepoints(text);
    std::vector<std::string> tokens;
    std::size_t i = 0;
    while (i < cps.size()) {
        while (i < cps.size() && is_py_space(cps[i])) ++i;
        const std::size_t start = i;
        while (i < cps.size() && !is_py_space(cps[i])) ++i;
        if (i > start) tokens.push_back(codepoints_to_utf8(cps.substr(start, i - start)));
    }
    return tokens;
}

// Python int(str): optional sign, digits with single underscores allowed
// between digits (Unicode decimal digits are accepted by CPython but are out
// of the frozen corpus — documented in 14b-decisions).
long long py_int(const std::string& token) {
    const std::string stripped = py_strip(token);
    std::size_t begin = 0;
    bool negative = false;
    if (begin < stripped.size() && (stripped[begin] == '+' || stripped[begin] == '-')) {
        negative = stripped[begin] == '-';
        ++begin;
    }
    const bool has_digits = begin < stripped.size();
    for (std::size_t i = begin; i < stripped.size(); ++i) {
        const char c = stripped[i];
        if (c >= '0' && c <= '9') continue;
        if (c == '_' && i > begin && i + 1 < stripped.size() &&
            stripped[i - 1] >= '0' && stripped[i - 1] <= '9' &&
            stripped[i + 1] >= '0' && stripped[i + 1] <= '9') {
            continue;
        }
        throw std::invalid_argument("invalid literal for int() with base 10: " +
                                    python_repr(stripped));
    }
    if (!has_digits) {
        throw std::invalid_argument("invalid literal for int() with base 10: " +
                                    python_repr(stripped));
    }
    std::string digits;
    for (std::size_t i = begin; i < stripped.size(); ++i) {
        if (stripped[i] != '_') digits.push_back(stripped[i]);
    }
    errno = 0;
    char* end = nullptr;
    const long long value = std::strtoll(digits.c_str(), &end, 10);
    if (errno == ERANGE || end == nullptr || *end != '\0') {
        throw std::invalid_argument("invalid literal for int() with base 10: " +
                                    python_repr(stripped));
    }
    return negative ? -value : value;
}

// Python float(str): sign / digits / underscore-between-digits / exponent,
// inf+infinity+nan (case-insensitive); hex float literals are not accepted.
double py_float(const std::string& token) {
    const std::string stripped = py_strip(token);
    std::size_t begin = 0;
    const bool negative =
        !stripped.empty() && (stripped[0] == '+' || stripped[0] == '-');
    if (negative) begin = 1;
    const std::string body = stripped.substr(begin);
    std::string lowered;
    lowered.reserve(body.size());
    for (char c : body) {
        lowered.push_back(static_cast<char>(c >= 'A' && c <= 'Z' ? c - 'A' + 'a' : c));
    }
    if (lowered == "inf" || lowered == "infinity") {
        return stripped[0] == '-' ? -std::numeric_limits<double>::infinity()
                                  : std::numeric_limits<double>::infinity();
    }
    if (lowered == "nan") {
        return std::numeric_limits<double>::quiet_NaN();
    }
    // underscore rule: single underscores strictly between digits
    for (std::size_t i = 0; i < body.size(); ++i) {
        if (body[i] != '_') continue;
        const bool prev_digit = i > 0 && body[i - 1] >= '0' && body[i - 1] <= '9';
        const bool next_digit =
            i + 1 < body.size() && body[i + 1] >= '0' && body[i + 1] <= '9';
        if (!prev_digit || !next_digit) {
            throw std::invalid_argument("could not convert string to float: " +
                                        python_repr(stripped));
        }
    }
    std::string cleaned;
    for (char c : body) {
        if (c != '_') cleaned.push_back(c);
    }
    if (cleaned.size() > 2 && cleaned[0] == '0' &&
        (cleaned[1] == 'x' || cleaned[1] == 'X')) {
        throw std::invalid_argument("could not convert string to float: " +
                                    python_repr(stripped));
    }
    if (cleaned.empty()) {
        throw std::invalid_argument("could not convert string to float: " +
                                    python_repr(stripped));
    }
    errno = 0;
    char* end = nullptr;
    const double value = std::strtod(cleaned.c_str(), &end);
    if (end == nullptr || *end != '\0') {
        throw std::invalid_argument("could not convert string to float: " +
                                    python_repr(stripped));
    }
    return negative ? -value : value;
}

bool is_finite(double value) {
    return value == value && std::fabs(value) != HUGE_VAL;
}

void check_ids(const std::set<long long>& ids_seen, const std::string& what,
               std::vector<std::string>& problems) {
    if (!ids_seen.empty() &&
        *ids_seen.rbegin() != static_cast<long long>(ids_seen.size())) {
        problems.push_back(what + "编号不连续（max id " +
                           std::to_string(*ids_seen.rbegin()) + " vs count " +
                           std::to_string(ids_seen.size()) + "）");
    }
}

void report_missing_refs(const std::set<long long>& node_ids,
                         const std::vector<long long>& zone_refs,
                         std::vector<std::string>& problems) {
    if (zone_refs.empty()) return;
    std::vector<long long> missing;
    std::set<long long> unique(zone_refs.begin(), zone_refs.end());
    std::set_difference(unique.begin(), unique.end(), node_ids.begin(), node_ids.end(),
                        std::back_inserter(missing));
    if (missing.empty()) return;
    std::string sample = "[";
    const std::size_t cap = missing.size() < 3 ? missing.size() : 3;
    for (std::size_t i = 0; i < cap; ++i) {
        if (i > 0) sample += ", ";
        sample += std::to_string(missing[i]);
    }
    sample += "]";
    problems.push_back(std::to_string(missing.size()) +
                       " 个单元引用了未定义的节点（如 " + sample + "）");
}

bool starts_with(const std::string& text, const char* prefix) {
    const std::size_t n = std::strlen(prefix);
    return text.size() >= n && text.compare(0, n, prefix) == 0;
}

std::string py_upper_ascii(const std::string& text) {
    std::string out;
    out.reserve(text.size());
    for (char c : text) {
        out.push_back(c >= 'a' && c <= 'z' ? static_cast<char>(c - 'a' + 'A') : c);
    }
    return out;
}

// --- strict grammar scans ------------------------------------------------------

MeshFacts parse_flac3d_lines(const std::vector<std::string>& raw_lines) {
    MeshFacts facts;
    std::set<long long> node_ids;
    std::vector<long long> zone_refs;
    for (std::size_t index = 0; index < raw_lines.size(); ++index) {
        const long long lineno = static_cast<long long>(index) + 1;
        const std::string line = py_strip(raw_lines[index]);
        if (line.empty()) continue;
        const std::vector<std::string> tokens = py_split(line);
        if (tokens[0] == "G") {
            if (tokens.size() != 5) {
                facts.problems.push_back("行 " + std::to_string(lineno) +
                                         ": G 记录应为 'G id x y z'");
                continue;
            }
            long long node_id = 0;
            std::array<double, 3> coords{};
            try {
                node_id = py_int(tokens[1]);
                for (int k = 0; k < 3; ++k) coords[k] = py_float(tokens[2 + static_cast<std::size_t>(k)]);
            } catch (const std::exception&) {
                facts.problems.push_back("行 " + std::to_string(lineno) +
                                         ": G 记录数值错误");
                continue;
            }
            node_ids.insert(node_id);
            facts.gridpoints += 1;
            if (!std::all_of(coords.begin(), coords.end(),
                             [](double v) { return is_finite(v); })) {
                facts.problems.push_back("行 " + std::to_string(lineno) +
                                         ": 坐标非有限值");
            }
        } else if (tokens[0] == "Z") {
            if (tokens.size() < 3 || tokens[1] != "B8") {
                facts.problems.push_back("行 " + std::to_string(lineno) +
                                         ": 单元记录应为 'Z B8 id n1..n8'");
                continue;
            }
            std::vector<long long> refs;
            try {
                for (std::size_t k = 3; k < tokens.size(); ++k) {
                    refs.push_back(py_int(tokens[k]));
                }
            } catch (const std::exception&) {
                facts.problems.push_back("行 " + std::to_string(lineno) +
                                         ": 单元节点引用非整数");
                continue;
            }
            facts.zones += 1;
            zone_refs.insert(zone_refs.end(), refs.begin(), refs.end());
            if (refs.size() != 8) {
                facts.problems.push_back("行 " + std::to_string(lineno) +
                                         ": B8 单元应有 8 个节点引用，实际 " +
                                         std::to_string(refs.size()));
            }
        } else if (tokens[0] == "*") {
            continue;  // comment header written by the exporter
        }
    }
    report_missing_refs(node_ids, zone_refs, facts.problems);
    check_ids(node_ids, "节点", facts.problems);
    return facts;
}

MeshFacts parse_abaqus_lines(const std::vector<std::string>& raw_lines) {
    MeshFacts facts;
    std::string section;  // "" | "node" | "element"
    std::set<long long> node_ids;
    std::vector<long long> zone_refs;
    for (std::size_t index = 0; index < raw_lines.size(); ++index) {
        const long long lineno = static_cast<long long>(index) + 1;
        const std::string line = py_strip(raw_lines[index]);
        if (line.empty() || starts_with(line, "**")) continue;
        if (starts_with(line, "*")) {
            const std::string upper = py_upper_ascii(line);
            if (starts_with(upper, "*NODE")) {
                section = "node";
            } else if (starts_with(upper, "*ELEMENT")) {
                section = "element";
            } else if (starts_with(upper, "*END")) {
                section = "";
            }
            continue;
        }
        std::vector<std::string> parts;
        {
            std::size_t start = 0;
            while (true) {
                const std::size_t comma = line.find(',', start);
                if (comma == std::string::npos) {
                    parts.push_back(py_strip(line.substr(start)));
                    break;
                }
                parts.push_back(py_strip(line.substr(start, comma - start)));
                start = comma + 1;
            }
        }
        if (section == "node") {
            if (parts.size() != 4) {
                facts.problems.push_back("行 " + std::to_string(lineno) +
                                         ": *NODE 记录应为 'id, x, y, z'");
                continue;
            }
            long long node_id = 0;
            std::array<double, 3> coords{};
            try {
                node_id = py_int(parts[0]);
                for (int k = 0; k < 3; ++k) coords[k] = py_float(parts[1 + static_cast<std::size_t>(k)]);
            } catch (const std::exception&) {
                facts.problems.push_back("行 " + std::to_string(lineno) +
                                         ": *NODE 记录数值错误");
                continue;
            }
            node_ids.insert(node_id);
            facts.gridpoints += 1;
            if (!std::all_of(coords.begin(), coords.end(),
                             [](double v) { return is_finite(v); })) {
                facts.problems.push_back("行 " + std::to_string(lineno) +
                                         ": 坐标非有限值");
            }
        } else if (section == "element") {
            if (parts.size() != 9) {
                facts.problems.push_back("行 " + std::to_string(lineno) +
                                         ": C3D8 单元应有 8 个节点引用，实际 " +
                                         std::to_string(parts.size() - 1));
                continue;
            }
            std::vector<long long> refs;
            try {
                for (std::size_t k = 1; k < parts.size(); ++k) {
                    refs.push_back(py_int(parts[k]));
                }
            } catch (const std::exception&) {
                facts.problems.push_back("行 " + std::to_string(lineno) +
                                         ": 单元记录格式错误");
                continue;
            }
            facts.zones += 1;
            zone_refs.insert(zone_refs.end(), refs.begin(), refs.end());
        }
    }
    report_missing_refs(node_ids, zone_refs, facts.problems);
    check_ids(node_ids, "节点", facts.problems);
    return facts;
}

std::string join_strings(const std::vector<std::string>& parts, const std::string& sep) {
    std::string out;
    for (std::size_t i = 0; i < parts.size(); ++i) {
        if (i > 0) out += sep;
        out += parts[i];
    }
    return out;
}

// Python `min(nx, ny, nz) < 1 or nx*ny*nz > 8_000_000` — overflow-safe:
// Python relies on bignums, C++ bounds the product with division checks
// (any dim > cap with the others >= 1 forces the product over the cap, so
// the rejection set is identical).
bool grid_dims_valid(long long nx, long long ny, long long nz) {
    constexpr long long kMaxCells = 8000000;
    if (nx < 1 || ny < 1 || nz < 1) return false;
    if (nx > kMaxCells / ny) return false;
    if (nx * ny > kMaxCells / nz) return false;
    return true;
}

// Python int(options[k]) coercion.
long long option_int(const Json& value) {
    if (value.is_string()) return py_int(value.get<std::string>());
    if (value.is_boolean()) return value.get<bool>() ? 1 : 0;
    if (value.is_number_float()) {
        const double number = value.get<double>();
        // Python yields a bignum; the corpus never freezes this path, so the
        // C++ side fails loudly instead of invoking UB on the cast.
        if (!(number >= -9.2e18 && number <= 9.2e18)) {
            throw std::invalid_argument("Python int too large to convert to C++");
        }
        return static_cast<long long>(number);
    }
    if (value.is_number_integer()) return value.get<long long>();
    throw std::invalid_argument("int() argument must be a string, a bytes-like "
                                "object or a real number");
}

// Python float(options.get(key, fallback)) coercion.
double option_float(const Json& options, const char* key, double fallback) {
    if (!options.is_object() || !options.contains(key) || options.at(key).is_null()) {
        return fallback;
    }
    const Json& value = options.at(key);
    if (value.is_string()) return py_float(value.get<std::string>());
    if (value.is_boolean()) return value.get<bool>() ? 1.0 : 0.0;
    if (value.is_number()) return value.get<double>();
    throw std::invalid_argument("float() argument must be a string or a real number");
}

}  // namespace

MeshFacts parse_flac3d_text(std::string_view utf8_text) {
    return parse_flac3d_lines(split_lines(utf8_to_codepoints(utf8_text)));
}

MeshFacts parse_abaqus_text(std::string_view utf8_text) {
    return parse_abaqus_lines(split_lines(utf8_to_codepoints(utf8_text)));
}

MeshFacts parse_flac3d(const std::filesystem::path& path) {
    return parse_flac3d_lines(read_lines_replace(path));
}

MeshFacts parse_abaqus(const std::filesystem::path& path) {
    return parse_abaqus_lines(read_lines_replace(path));
}

// --- adapter -----------------------------------------------------------------

InspectionResult ModelAdapter::inspect(const std::filesystem::path& path) const {
    InspectionResult result;
    result.object_type = "model";
    std::error_code ec;
    const auto size = std::filesystem::file_size(path, ec);
    if (ec) {
        result.ok = false;
        result.errors.push_back("无法读取文件状态: " + ec.message());
        return result;
    }
    result.size_bytes = static_cast<long long>(size);
    MeshFacts facts;
    try {
        facts = parse(path);
    } catch (const std::exception& exc) {
        result.ok = false;
        result.errors.push_back(std::string("无法读取文件: ") + exc.what());
        return result;
    }
    if (facts.gridpoints == 0 && facts.zones == 0) {
        result.ok = false;
        result.errors.push_back("未识别到网格记录（不是本仓库写出的结构化网格）");
        return result;
    }
    result.metadata = Json::object();
    result.metadata["gridpoints"] = facts.gridpoints;
    result.metadata["zones"] = facts.zones;
    if (!facts.problems.empty()) {
        const std::size_t cap = facts.problems.size() < 16 ? facts.problems.size() : 16;
        for (std::size_t i = 0; i < cap; ++i) result.errors.push_back(facts.problems[i]);
        result.warnings.push_back("结构问题共 " + std::to_string(facts.problems.size()) +
                                  " 处");
    }
    return result;
}

ImportPlan ModelAdapter::plan_import(const std::filesystem::path& path,
                                     const InspectionResult& inspection, bool managed,
                                     const std::optional<std::string>& asset_name,
                                     Json options) const {
    // registry.FormatAdapter.plan_import default.
    ImportPlan plan;
    plan.format_id = format_id;
    plan.source_path = path.string();
    if (!inspection.ok) {
        plan.action = "unsupported";
    } else {
        plan.action = managed ? "managed_copy" : "link_external";
    }
    plan.asset_name = asset_name.value_or(path.filename().string());
    plan.warnings = inspection.warnings;
    plan.estimated_bytes = inspection.size_bytes;
    plan.metadata = inspection.metadata;
    plan.options = options.is_object() ? options : Json::object();
    // _StructuredModelAdapter.plan_import override.
    plan.action = "unsupported";
    plan.warnings.push_back("模型网格为导出专用格式：无导入路径");
    return plan;
}

void ModelAdapter::import_data() const {
    throw FormatNotSupportedError(format_id + ": 模型网格无导入路径（仅导出）");
}

ExportPlan ModelAdapter::plan_export(const std::filesystem::path& source_path,
                                     const std::filesystem::path& target_path,
                                     Json options) const {
    const std::string expected_suffix = "." + extensions[0];
    std::string actual_suffix = target_path.extension().string();
    for (char& c : actual_suffix) {
        c = c >= 'A' && c <= 'Z' ? static_cast<char>(c - 'A' + 'a') : c;
    }
    if (actual_suffix != expected_suffix) {
        throw FormatNotSupportedError(display_name + " 仅支持导出为 " + expected_suffix);
    }
    const Json plan_options = options.is_object() ? options : Json::object();
    std::vector<std::string> missing;
    for (const char* key : {"nx", "ny", "nz"}) {
        if (!plan_options.contains(key)) missing.push_back(key);
    }
    if (!missing.empty()) {
        throw FormatNotSupportedError("缺少网格维度参数: " + join_strings(missing, ", "));
    }
    const long long nx = option_int(plan_options.at("nx"));
    const long long ny = option_int(plan_options.at("ny"));
    const long long nz = option_int(plan_options.at("nz"));
    if (!grid_dims_valid(nx, ny, nz)) {
        throw FormatNotSupportedError("网格维度非法或超过导出规模上限");
    }
    ExportPlan plan;
    plan.format_id = format_id;
    plan.source_path = source_path.string();
    plan.target_path = target_path.string();
    plan.estimated_bytes =
        (nx + 1) * (ny + 1) * (nz + 1) * 64 + nx * ny * nz * 64;
    plan.options = plan_options;
    return plan;
}

std::filesystem::path ModelAdapter::export_data(const ExportPlan& plan,
                                                const CancelToken& cancel,
                                                ProgressCallback progress) const {
    (void)progress;
    cancel.checkpoint();
    const Json& options = plan.options;
    // Hand-built plans bypass plan_export: re-validate so a truncated
    // dimension can never silently produce a wrong grid (Python would die
    // loudly inside the writer/numpy allocation instead).
    const long long nx_ll = option_int(options.at("nx"));
    const long long ny_ll = option_int(options.at("ny"));
    const long long nz_ll = option_int(options.at("nz"));
    if (!grid_dims_valid(nx_ll, ny_ll, nz_ll)) {
        throw FormatNotSupportedError("网格维度非法或超过导出规模上限");
    }
    const int nx = static_cast<int>(nx_ll);
    const int ny = static_cast<int>(ny_ll);
    const int nz = static_cast<int>(nz_ll);
    const double dx = option_float(options, "dx", 10.0);
    const double dy = option_float(options, "dy", 10.0);
    const double dz = option_float(options, "dz", 10.0);

    const std::string text = write_grid(nx, ny, nz, dx, dy, dz);
    if (text.empty()) {
        throw std::runtime_error(display_name + " 导出失败（writer 返回 False）");
    }
    AtomicOutputFile output(plan.target_path);
    {
        std::ofstream out(output.temp_path(), std::ios::binary);
        if (!out) throw std::runtime_error("cannot write export temp: " +
                                           output.temp_path().string());
        out.write(text.data(), static_cast<std::streamsize>(text.size()));
        if (!out) {
            throw std::runtime_error("short write on export temp: " +
                                     output.temp_path().string());
        }
    }
    output.commit();
    return plan.target_path;
}

ExportVerification ModelAdapter::verify_output(const std::filesystem::path& target_path,
                                                const ExportPlan& plan) const {
    std::vector<VerificationCheck> checks;
    std::error_code ec;
    const bool is_file = std::filesystem::is_regular_file(target_path, ec);
    long long size = 0;
    if (is_file) size = static_cast<long long>(std::filesystem::file_size(target_path, ec));
    if (!is_file || size == 0) {
        return ExportVerification::failed({}, "输出缺失或为空");
    }
    MeshFacts facts;
    try {
        facts = parse(target_path);
    } catch (const std::exception& exc) {
        // Python would surface an OSError here; both are loud failures.
        return ExportVerification::failed({}, std::string("无法读取文件: ") + exc.what());
    }
    checks.push_back(VerificationCheck{
        "reparsable", facts.gridpoints > 0 && facts.zones > 0,
        std::to_string(facts.gridpoints) + " gridpoints / " +
            std::to_string(facts.zones) + " zones"});
    if (plan.options.is_object() && plan.options.contains("nx") &&
        plan.options.contains("ny") && plan.options.contains("nz")) {
        const long long nx = option_int(plan.options.at("nx"));
        const long long ny = option_int(plan.options.at("ny"));
        const long long nz = option_int(plan.options.at("nz"));
        if (!grid_dims_valid(nx, ny, nz)) {
            // Python would print a bignum expectation here; such plans are
            // unreachable through plan_export, so the C++ side reports a
            // loud failing check instead (documented: 14b-decisions D14b-14).
            const std::string bad = "预期 (超出导出规模上限)，实际 ";
            checks.push_back(
                VerificationCheck{"gridpoint_count", false,
                                  bad + std::to_string(facts.gridpoints)});
            checks.push_back(VerificationCheck{"zone_count", false,
                                               bad + std::to_string(facts.zones)});
        } else {
            const long long expected_gp = (nx + 1) * (ny + 1) * (nz + 1);
            const long long expected_zones = nx * ny * nz;
            checks.push_back(VerificationCheck{
                "gridpoint_count", facts.gridpoints == expected_gp,
                "预期 " + std::to_string(expected_gp) + "，实际 " +
                    std::to_string(facts.gridpoints)});
            checks.push_back(VerificationCheck{
                "zone_count", facts.zones == expected_zones,
                "预期 " + std::to_string(expected_zones) + "，实际 " +
                    std::to_string(facts.zones)});
        }
    }
    if (!facts.problems.empty()) {
        const std::size_t cap = facts.problems.size() < 4 ? facts.problems.size() : 4;
        std::vector<std::string> head(facts.problems.begin(),
                                      facts.problems.begin() + static_cast<long>(cap));
        return ExportVerification::failed(
            std::move(checks), "结构问题: " + join_strings(head, "; "));
    }
    for (const auto& check : checks) {
        if (!check.passed) return ExportVerification::failed(std::move(checks));
    }
    ExportVerification verified;
    verified.state = VerificationState::VERIFIED;
    verified.checks = std::move(checks);
    return verified;
}

FormatCapability Flac3dAdapter::capability() const {
    FormatCapability cap;
    cap.inspect = true;
    cap.can_export = true;
    cap.roundtrip_verify = true;
    cap.notes =
        "结构化六面体网格写出（export_to_flac3d）；无读取器，inspect 为结构扫描";
    return cap;
}

MeshFacts Flac3dAdapter::parse(const std::filesystem::path& path) const {
    return parse_flac3d(path);
}

std::string Flac3dAdapter::write_grid(int nx, int ny, int nz, double dx, double dy,
                                      double dz) const {
    return pwb::geomodel::legacy_export_to_flac3d(nx, ny, nz, dx, dy, dz);
}

FormatCapability AbaqusAdapter::capability() const {
    FormatCapability cap;
    cap.inspect = true;
    cap.can_export = true;
    cap.roundtrip_verify = true;
    cap.notes =
        "结构化六面体网格写出（export_to_abaqus）；无读取器，inspect 为结构扫描";
    return cap;
}

MeshFacts AbaqusAdapter::parse(const std::filesystem::path& path) const {
    return parse_abaqus(path);
}

std::string AbaqusAdapter::write_grid(int nx, int ny, int nz, double dx, double dy,
                                      double dz) const {
    return pwb::geomodel::legacy_export_to_abaqus(nx, ny, nz, dx, dy, dz);
}

// --- registry ------------------------------------------------------------------

void ModelAdapterRegistry::register_adapter(std::shared_ptr<ModelAdapter> adapter,
                                            bool replace) {
    if (adapter == nullptr || adapter->format_id.empty()) {
        throw std::invalid_argument("adapter must define format_id");
    }
    // Python replaces in place (dict assignment): the NEW adapter must win
    // lookups, never a stale duplicate.
    for (auto& existing : adapters_) {
        if (existing->format_id == adapter->format_id) {
            if (!replace) {
                throw std::invalid_argument("duplicate adapter format_id: " +
                                            adapter->format_id);
            }
            existing = std::move(adapter);
            return;
        }
    }
    adapters_.push_back(std::move(adapter));
}

const ModelAdapter* ModelAdapterRegistry::get(const std::string& format_id) const {
    for (const auto& adapter : adapters_) {
        if (adapter->format_id == format_id) return adapter.get();
    }
    return nullptr;
}

const ModelAdapter* ModelAdapterRegistry::adapter_for_extension(
    const std::string& extension) const {
    std::string lowered = extension;
    for (char& c : lowered) {
        c = c >= 'A' && c <= 'Z' ? static_cast<char>(c - 'A' + 'a') : c;
    }
    if (!lowered.empty() && lowered.front() == '.') lowered.erase(lowered.begin());
    for (const auto& adapter : adapters_) {
        for (const auto& ext : adapter->extensions) {
            if (ext == lowered) return adapter.get();
        }
    }
    return nullptr;
}

Json ModelAdapterRegistry::capability_matrix() const {
    Json rows = Json::array();
    for (const auto& adapter : adapters_) {
        const FormatCapability cap = adapter->capability();
        Json row = Json::object();
        row["format_id"] = adapter->format_id;
        row["display_name"] = adapter->display_name;
        row["extensions"] = adapter->extensions;
        row["read"] = cap.read;
        row["inspect"] = cap.inspect;
        row["import"] = cap.import_data;
        row["export"] = cap.can_export;
        row["roundtrip_verify"] = cap.roundtrip_verify;
        row["notes"] = cap.notes;
        rows.push_back(std::move(row));
    }
    return rows;
}

ModelAdapterRegistry build_model_adapter_registry() {
    ModelAdapterRegistry registry;
    registry.register_adapter(std::make_shared<Flac3dAdapter>());
    registry.register_adapter(std::make_shared<AbaqusAdapter>());
    return registry;
}

}  // namespace pwb::interchange
