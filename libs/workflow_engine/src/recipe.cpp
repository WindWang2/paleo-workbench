// CONV-33 — faithful port of paleo_workbench/workflow/recipe.py.
//
// Portable *.paleo-workflow.json documents: the WorkflowSpec body plus
// metadata, with the structural security gate (forbidden keys / absolute
// paths) enforced at save AND load, fail-closed schema migration, atomic
// writes and the lifecycle helpers (from_spec / from_run / clone / diff /
// inspect). Byte-level discipline (E-3): save writes the exact
// json.dump(payload, ensure_ascii=False, indent=1) bytes with NO trailing
// newline; the load JSON-parse error reproduces the CPython
// json.JSONDecodeError detail (message + "line L column C (char N)"),
// including the 3.13+ "Illegal trailing comma" wording. Semantics frozen
// against tools/oracle/generate_workflow_recipe_fixtures.py.
#include "pwb/workflow_engine/recipe.hpp"

#include <algorithm>
#include <atomic>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <system_error>
#include <utility>

#if defined(_WIN32)
#include <process.h>
#else
#include <unistd.h>
#endif

namespace pwb::workflow_engine {
namespace {

// Python time.time() parity; tests inject a fixed Clock (D5).
double wall_clock_seconds() {
    return std::chrono::duration<double>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

long long current_pid() {
#if defined(_WIN32)
    return _getpid();
#else
    return ::getpid();
#endif
}

unsigned long next_tmp_counter() {
    static std::atomic<unsigned long> counter{0};
    return counter.fetch_add(1);
}

// recipe._FORBIDDEN_KEYS (L31): dict keys (lowercased+stripped) that must
// never carry a STRING value in a recipe document.
const std::set<std::string>& forbidden_keys() {
    static const std::set<std::string> keys = {
        "api_key", "apikey", "token", "secret", "password", "passwd",
        "credential", "sql", "query", "statement", "code", "script",
        "source", "eval", "exec", "shell", "command",
    };
    return keys;
}

char ascii_lower(char ch) {
    return (ch >= 'A' && ch <= 'Z') ? static_cast<char>(ch - 'A' + 'a')
                                    : ch;
}

// str.strip() over ASCII whitespace (space \t \n \v \f \r).
std::string py_strip(const std::string& text) {
    std::size_t begin = 0;
    std::size_t end = text.size();
    auto is_space = [](char ch) {
        return ch == ' ' || ch == '\t' || ch == '\n' || ch == '\v' ||
               ch == '\f' || ch == '\r';
    };
    while (begin < end && is_space(text[begin])) ++begin;
    while (end > begin && is_space(text[end - 1])) --end;
    return text.substr(begin, end - begin);
}

// Python repr() of a string: prefer single quotes (switch to double quotes
// when the text holds ' but no "), escape \\ \b \f \n \r \t and the active
// quote, \xNN for the remaining control characters. UTF-8 payload bytes
// pass through (CPython repr keeps printable non-ASCII verbatim).
std::string python_repr_string(const std::string& text) {
    const bool has_single = text.find('\'') != std::string::npos;
    const bool has_double = text.find('"') != std::string::npos;
    const char quote = (has_single && !has_double) ? '"' : '\'';
    std::string out(1, quote);
    for (const char raw : text) {
        const unsigned char ch = static_cast<unsigned char>(raw);
        switch (raw) {
        case '\\': out += "\\\\"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        case '\b': out += "\\b"; break;
        case '\f': out += "\\f"; break;
        default:
            if (raw == quote) {
                out += '\\';
                out += quote;
            } else if (ch < 0x20 || ch == 0x7f) {
                char buf[8];
                std::snprintf(buf, sizeof(buf), "\\x%02x",
                              static_cast<unsigned>(ch));
                out += buf;
            } else {
                out += raw;
            }
        }
    }
    out += quote;
    return out;
}

// Python repr() of a float: shortest round-trip digits, ".0" appended when
// integral (CONV-06 python_repr.cpp strategy, replicated locally because
// the detail header is not exported outside workflow_spec).
std::string py_repr_double(double value) {
    if (std::isnan(value)) return "nan";
    if (std::isinf(value)) return value > 0 ? "inf" : "-inf";
    char buffer[64] = {0};
    for (int precision = 1; precision <= 17; ++precision) {
        std::snprintf(buffer, sizeof(buffer), "%.*g", precision, value);
        if (std::strtod(buffer, nullptr) == value) {
            break;
        }
    }
    std::string text(buffer);
    if (text.find('.') == std::string::npos &&
        text.find('e') == std::string::npos &&
        text.find('E') == std::string::npos) {
        text += ".0";
    }
    return text;
}

// Python repr()/str() of a JSON value for the str() coercions in
// RecipeDocument.from_dict and migrate_recipe.
std::string py_repr_json(const Json& value) {
    switch (value.type()) {
    case Json::value_t::null:
        return "None";
    case Json::value_t::boolean:
        return value.get<bool>() ? "True" : "False";
    case Json::value_t::number_integer:
    case Json::value_t::number_unsigned:
        return std::to_string(value.get<long long>());
    case Json::value_t::number_float:
        return py_repr_double(value.get<double>());
    case Json::value_t::string:
        return python_repr_string(value.get<std::string>());
    case Json::value_t::array: {
        std::string out = "[";
        bool first = true;
        for (const auto& item : value) {
            if (!first) out += ", ";
            first = false;
            out += py_repr_json(item);
        }
        out += "]";
        return out;
    }
    case Json::value_t::object:
    default: {
        std::string out = "{";
        bool first = true;
        for (const auto& [key, item] : value.items()) {
            if (!first) out += ", ";
            first = false;
            out += python_repr_string(key) + ": " + py_repr_json(item);
        }
        out += "}";
        return out;
    }
    }
}

// Python str(x): strings pass through, everything else renders as repr().
std::string py_str_json(const Json& value) {
    if (value.is_string()) return value.get<std::string>();
    return py_repr_json(value);
}

// Python truthiness of a JSON value (`x or default` in from_dict).
bool py_truthy(const Json& value) {
    if (value.is_null()) return false;
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_string()) return !value.get<std::string>().empty();
    if (value.is_array() || value.is_object()) return !value.empty();
    return true;  // numbers
}

// recipe._ABSOLUTE_PATH_RE (L36): ^(/|\\\\|[A-Za-z]:[/\\]) — POSIX root,
// UNC (two leading backslashes) or a Windows drive root, matched against
// the STRIPPED value.
bool absolute_path_match(const std::string& stripped) {
    if (stripped.empty()) return false;
    if (stripped[0] == '/') return true;
    if (stripped.size() >= 2 && stripped[0] == '\\' && stripped[1] == '\\') {
        return true;
    }
    const char c0 = stripped[0];
    const bool letter =
        (c0 >= 'A' && c0 <= 'Z') || (c0 >= 'a' && c0 <= 'z');
    return letter && stripped.size() >= 3 && stripped[1] == ':' &&
           (stripped[2] == '/' || stripped[2] == '\\');
}

// recipe._check_forbidden (L86): recursive walk. NOTE the L90 subtlety —
// a forbidden key with a NON-string value is never flagged here; the
// subtree recurses normally (so a "token" string nested under a "sql" dict
// IS caught, one level deeper).
void check_forbidden(const Json& value, const std::string& path,
                     std::vector<std::string>& problems) {
    if (value.is_object()) {
        for (const auto& [key, sub] : value.items()) {
            std::string key_l;
            for (const char ch : py_strip(key)) key_l.push_back(ascii_lower(ch));
            if (forbidden_keys().count(key_l) != 0 && sub.is_string()) {
                problems.push_back(path + "." + key +
                                   ": forbidden recipe key (" + key_l + ")");
            } else {
                check_forbidden(sub, path + "." + key, problems);
            }
        }
    } else if (value.is_array()) {
        for (std::size_t i = 0; i < value.size(); ++i) {
            check_forbidden(value[i],
                            path + "[" + std::to_string(i) + "]", problems);
        }
    } else if (value.is_string()) {
        const std::string text = value.get<std::string>();
        // The $-exemption checks the RAW value, not the stripped one.
        if (absolute_path_match(py_strip(text)) &&
            (text.empty() || text[0] != '$')) {
            problems.push_back(
                path + ": absolute path " + python_repr_string(text) +
                " — recipes are portable; use workspace-relative paths or "
                "slot bindings");
        }
    }
}

std::string join_problems(const std::vector<std::string>& problems) {
    std::string out;
    for (std::size_t i = 0; i < problems.size(); ++i) {
        if (i != 0) out += "; ";
        out += problems[i];
    }
    return out;
}

// ------------------------------------------------------ CPython JSON detail --
// A byte-level re-implementation of the CPython json.JSONDecodeError
// detail ("message: line L column C (char N)") so load_recipe's refusal
// message matches Python byte-for-byte. The scanner mirrors the C scanner
// in Modules/_json.c: whitespace, strings (escapes/control chars),
// containers (including the 3.13+ "Illegal trailing comma" wording),
// numbers via the CPython number regex and the Extra-data tail check.
// Only error POSITIONS matter here — successful scans fall through to
// nlohmann for the actual parse.

struct ScanError {
    std::string message;
    std::size_t pos;
};

std::size_t scan_skip_ws(const std::string& s, std::size_t i) {
    while (i < s.size()) {
        const char c = s[i];
        if (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
            ++i;
        } else {
            break;
        }
    }
    return i;
}

bool scan_digits(const std::string& s, std::size_t& i) {
    if (i >= s.size() || s[i] < '0' || s[i] > '9') return false;
    while (i < s.size() && s[i] >= '0' && s[i] <= '9') ++i;
    return true;
}

bool scan_string(const std::string& s, std::size_t& i, ScanError& err) {
    const std::size_t open = i;  // s[open] == '"'
    std::size_t j = i + 1;
    while (true) {
        if (j >= s.size()) {
            err = {"Unterminated string starting at", open};
            return true;
        }
        const unsigned char c = static_cast<unsigned char>(s[j]);
        if (c == '"') {
            i = j + 1;
            return false;
        }
        if (c == '\\') {
            if (j + 1 >= s.size()) {
                err = {"Unterminated string starting at", open};
                return true;
            }
            const char e = s[j + 1];
            if (e == '"' || e == '\\' || e == '/' || e == 'b' || e == 'f' ||
                e == 'n' || e == 'r' || e == 't') {
                j += 2;
                continue;
            }
            if (e == 'u') {
                std::size_t k = j + 2;
                int hex = 0;
                while (hex < 4 && k < s.size() &&
                       std::isxdigit(static_cast<unsigned char>(s[k]))) {
                    ++k;
                    ++hex;
                }
                if (hex == 4) {
                    j = k;
                    continue;
                }
                err = {"Invalid \\uXXXX escape", j + 1};
                return true;
            }
            err = {"Invalid \\escape", j};
            return true;
        }
        if (c < 0x20) {
            err = {"Invalid control character at", j};
            return true;
        }
        ++j;
    }
}

bool scan_value(const std::string& s, std::size_t& i, ScanError& err);

// CPython number regex: -?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][-+]?\d+)?
// A failed match at a digit/'-' start (e.g. "-" or "-x") is "Expecting
// value" at the value start; partial matches ("01" -> "0", "5." -> "5")
// leave the tail for the delimiter checks, exactly like Python.
bool scan_number(const std::string& s, std::size_t& i, ScanError& err) {
    const std::size_t start = i;
    std::size_t j = i;
    if (j < s.size() && s[j] == '-') ++j;
    if (j >= s.size() || s[j] < '0' || s[j] > '9') {
        err = {"Expecting value", start};
        return true;
    }
    if (s[j] == '0') {
        ++j;
    } else {
        scan_digits(s, j);  // [1-9]\d* — first digit already validated
    }
    if (j < s.size() && s[j] == '.') {
        std::size_t k = j + 1;
        if (scan_digits(s, k)) j = k;  // \.\d+
    }
    if (j < s.size() && (s[j] == 'e' || s[j] == 'E')) {
        std::size_t k = j + 1;
        if (k < s.size() && (s[k] == '+' || s[k] == '-')) ++k;
        if (scan_digits(s, k)) j = k;
    }
    i = j;
    return false;
}

bool scan_object(const std::string& s, std::size_t& i, ScanError& err) {
    std::size_t j = scan_skip_ws(s, i + 1);
    if (j >= s.size()) {
        err = {"Expecting property name enclosed in double quotes", j};
        return true;
    }
    if (s[j] != '}') {
        while (true) {
            if (s[j] != '"') {
                err = {"Expecting property name enclosed in double quotes", j};
                return true;
            }
            if (scan_string(s, j, err)) return true;  // key
            j = scan_skip_ws(s, j);
            if (j >= s.size() || s[j] != ':') {
                err = {"Expecting ':' delimiter", j};
                return true;
            }
            j = scan_skip_ws(s, j + 1);
            if (scan_value(s, j, err)) return true;
            j = scan_skip_ws(s, j);
            if (j >= s.size()) {
                err = {"Expecting ',' delimiter", j};
                return true;
            }
            if (s[j] == '}') break;
            if (s[j] != ',') {
                err = {"Expecting ',' delimiter", j};
                return true;
            }
            const std::size_t comma = j;  // CPython reports the COMMA pos
            j = scan_skip_ws(s, j + 1);
            if (j >= s.size()) {
                err = {"Expecting property name enclosed in double quotes", j};
                return true;
            }
            if (s[j] == '}') {
                err = {"Illegal trailing comma before end of object", comma};
                return true;
            }
            // loop back: the key string check runs at the top
        }
    }
    i = j + 1;  // past '}'
    return false;
}

bool scan_array(const std::string& s, std::size_t& i, ScanError& err) {
    std::size_t j = scan_skip_ws(s, i + 1);
    if (j < s.size() && s[j] == ']') {
        i = j + 1;
        return false;
    }
    while (true) {
        if (scan_value(s, j, err)) return true;
        j = scan_skip_ws(s, j);
        if (j >= s.size()) {
            err = {"Expecting ',' delimiter", j};
            return true;
        }
        if (s[j] == ']') break;
        if (s[j] != ',') {
            err = {"Expecting ',' delimiter", j};
            return true;
        }
        const std::size_t comma = j;  // CPython reports the COMMA pos
        j = scan_skip_ws(s, j + 1);
        if (j < s.size() && s[j] == ']') {
            err = {"Illegal trailing comma before end of array", comma};
            return true;
        }
        // loop back: parse the next element (EOF -> "Expecting value")
    }
    i = j + 1;  // past ']'
    return false;
}

bool scan_value(const std::string& s, std::size_t& i, ScanError& err) {
    if (i >= s.size()) {
        err = {"Expecting value", i};
        return true;
    }
    const char c = s[i];
    if (c == '"') return scan_string(s, i, err);
    if (c == '{') return scan_object(s, i, err);
    if (c == '[') return scan_array(s, i, err);
    // CPython also accepts the Infinity/-Infinity/NaN literals (checked
    // before the number branch — "-Infinity" starts with '-'); the scanner
    // lets them through and the nlohmann parse behind it refuses (the
    // documented divergence path).
    static constexpr std::string_view kLiterals[] = {
        "Infinity", "-Infinity", "NaN", "true", "false", "null"};
    for (const std::string_view literal : kLiterals) {
        if (s.compare(i, literal.size(), literal.data()) == 0) {
            i += literal.size();
            return false;
        }
    }
    if (c == '-' || (c >= '0' && c <= '9')) return scan_number(s, i, err);
    err = {"Expecting value", i};
    return true;
}

// lineno = count('\n', 0, pos) + 1; colno = pos - rfind('\n', 0, pos)
// (rfind == -1 when absent), i.e. the CPython position formatting.
std::string format_scan_error(const std::string& s, const ScanError& err) {
    const std::size_t pos = std::min(err.pos, s.size());
    std::size_t line = 1;
    std::size_t last_nl = std::string::npos;
    for (std::size_t k = 0; k < pos; ++k) {
        if (s[k] == '\n') {
            ++line;
            last_nl = k;
        }
    }
    const std::size_t col =
        pos - (last_nl == std::string::npos ? 0 : last_nl + 1) + 1;
    return err.message + ": line " + std::to_string(line) + " column " +
           std::to_string(col) + " (char " + std::to_string(pos) + ")";
}

// Full-document scan; nullopt == the text is well-formed JSON as far as
// CPython is concerned (nlohmann then does the actual parse).
std::optional<std::string> cpython_json_detail(const std::string& text) {
    ScanError err;
    std::size_t i = scan_skip_ws(text, 0);
    if (scan_value(text, i, err)) {
        return format_scan_error(text, err);
    }
    i = scan_skip_ws(text, i);
    if (i != text.size()) {
        return format_scan_error(text, ScanError{"Extra data", i});
    }
    return std::nullopt;
}

// ------------------------------------------------------------ pathlib bits --
// PurePath.suffix: the last dotted part, '' when the name has no dot or is
// itself a dotfile (".json" has NO suffix in Python).
std::string py_path_suffix(const std::string& name) {
    const std::size_t at = name.rfind('.');
    if (at == std::string::npos || at == 0) return "";
    return name.substr(at);
}

// PurePath.stem: everything before the suffix (''.stem == '.json').
std::string py_path_stem(const std::string& name) {
    const std::size_t at = name.rfind('.');
    if (at == std::string::npos || at == 0) return name;
    return name.substr(0, at);
}

// Python == over JSON values for diff_recipes: int/float compare by value
// across the type line, dict equality is order-insensitive with exact key
// sets, and a MISSING key reads as None (dict.get semantics) so
// {"a": null} vs {} compares equal on the per-field walk (matching
// Python) even though the whole-dict comparison sees different key sets.
bool py_value_equal(const Json* left, const Json* right);
bool py_object_equal(const Json& left, const Json& right) {
    if (left.size() != right.size()) return false;
    for (const auto& [key, item] : left.items()) {
        const auto it = right.find(key);
        if (it == right.end()) return false;
        if (!py_value_equal(&item, &it.value())) return false;
    }
    return true;
}

bool py_value_equal(const Json* left, const Json* right) {
    const bool l_null = left == nullptr || left->is_null();
    const bool r_null = right == nullptr || right->is_null();
    if (l_null || r_null) return l_null && r_null;  // None == None
    if (left->is_boolean() || right->is_boolean()) {
        return left->type() == right->type() && *left == *right;
    }
    if (left->is_number() && right->is_number()) {
        // Python 1 == 1.0 — cross the int/float line by value.
        if (left->is_number_integer() && right->is_number_integer()) {
            return left->get<long long>() == right->get<long long>();
        }
        return left->get<double>() == right->get<double>();
    }
    if (left->type() != right->type()) return false;
    if (left->is_array()) {
        if (left->size() != right->size()) return false;
        for (std::size_t i = 0; i < left->size(); ++i) {
            if (!py_value_equal(&(*left)[i], &(*right)[i])) return false;
        }
        return true;
    }
    if (left->is_object()) return py_object_equal(*left, *right);
    return *left == *right;
}

// dict.get(k) view: nullptr when absent, pointer to (possibly null) value.
const Json* py_get(const Json& obj, const std::string& key) {
    const auto it = obj.find(key);
    return it == obj.end() ? nullptr : &it.value();
}

// recipe._slug (L324): lower, collapse [^a-z0-9._-]+ runs into "-",
// strip the dashes, fall back to "recipe".
std::string slugify(const std::string& name) {
    std::string lowered;
    lowered.reserve(name.size());
    for (const char ch : name) lowered.push_back(ascii_lower(ch));
    auto allowed = [](char ch) {
        return (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') ||
               ch == '.' || ch == '_' || ch == '-';
    };
    std::string slug;
    for (std::size_t i = 0; i < lowered.size();) {
        if (allowed(lowered[i])) {
            slug.push_back(lowered[i]);
            ++i;
            continue;
        }
        slug.push_back('-');  // one dash per disallowed RUN
        while (i < lowered.size() && !allowed(lowered[i])) ++i;
    }
    std::size_t begin = 0;
    std::size_t end = slug.size();
    while (begin < end && slug[begin] == '-') ++begin;
    while (end > begin && slug[end - 1] == '-') --end;
    slug = slug.substr(begin, end - begin);
    return slug.empty() ? std::string("recipe") : slug;
}

}  // namespace

// ------------------------------------------------------------ RecipeDocument --

Json RecipeDocument::to_dict() const {
    // Key order mirrors the Python dict literal (L57-66) exactly — the
    // save byte-format freezes this order.
    Json d;
    d["recipe_schema_version"] = schema_version;
    d["recipe_id"] = recipe_id;
    d["name"] = name;
    d["description"] = description;
    d["created_at"] = created_at.has_value() ? Json(*created_at)
                                             : Json(nullptr);
    d["source_run_id"] = source_run_id.has_value() ? Json(*source_run_id)
                                                   : Json(nullptr);
    d["tags"] = Json::array();
    for (const auto& tag : tags) d["tags"].push_back(tag);
    d["workflow"] = workflow.to_dict();
    return d;
}

RecipeDocument RecipeDocument::from_dict(const Json& data) {
    if (!data.is_object()) {
        // Python crashes with AttributeError on non-dict input; fail
        // closed instead (CONV-06 D5 precedent).
        throw workflow_spec::ModelError("recipe: expected an object");
    }
    Json migrated = migrate_recipe(data);
    RecipeDocument doc;
    doc.workflow = workflow_spec::WorkflowSpec::from_dict(
        migrated.at("workflow"));
    // str(data["recipe_id"]) — required (KeyError parity).
    const Json* recipe_id = py_get(migrated, "recipe_id");
    if (recipe_id == nullptr) {
        throw workflow_spec::ModelError("missing required key 'recipe_id'");
    }
    doc.recipe_id = py_str_json(*recipe_id);
    // str(data.get("name") or workflow.name)
    const Json* name = py_get(migrated, "name");
    doc.name = name != nullptr && py_truthy(*name) ? py_str_json(*name)
                                                   : doc.workflow.name;
    // str(data.get("description") or "")
    const Json* description = py_get(migrated, "description");
    doc.description = description != nullptr && py_truthy(*description)
                          ? py_str_json(*description)
                          : std::string();
    // data.get("created_at") — typed double field (frozen header); a
    // non-numeric value reads as absent (documented deviation).
    const Json* created_at = py_get(migrated, "created_at");
    if (created_at != nullptr && created_at->is_number()) {
        doc.created_at = created_at->get<double>();
    }
    // data.get("source_run_id")
    const Json* source_run_id = py_get(migrated, "source_run_id");
    if (source_run_id != nullptr && !source_run_id->is_null()) {
        doc.source_run_id = py_str_json(*source_run_id);
    }
    // tuple(data.get("tags") or ())
    const Json* tags = py_get(migrated, "tags");
    if (tags != nullptr && py_truthy(*tags)) {
        if (!tags->is_array()) {
            // Python's tuple(str) char-splitting quirk is not reproduced;
            // garbage fails closed (D5 precedent).
            throw workflow_spec::ModelError("tags: expected a list");
        }
        for (const auto& tag : *tags) {
            doc.tags.push_back(py_str_json(tag));
        }
    }
    // str(data.get("recipe_schema_version", RECIPE_SCHEMA_VERSION)) —
    // presence wins even when falsy.
    const Json* schema_version = py_get(migrated, "recipe_schema_version");
    doc.schema_version = schema_version != nullptr
                             ? py_str_json(*schema_version)
                             : std::string(kRecipeSchemaVersion);
    return doc;
}

// ------------------------------------------------------------ security gate --

std::vector<std::string> structural_problems(const Json& data) {
    std::vector<std::string> problems;
    check_forbidden(data, "recipe", problems);
    return problems;
}

// ----------------------------------------------------------------- migrate --

Json migrate_recipe(const Json& data) {
    if (!data.is_object()) {
        // Python: data.get(...) on a non-dict raises AttributeError; fail
        // closed (documented deviation).
        throw workflow_spec::ModelError("recipe: expected an object");
    }
    std::string version{kRecipeSchemaVersion};
    if (const Json* raw = py_get(data, "recipe_schema_version");
        raw != nullptr) {
        version = py_str_json(*raw);
    }
    if (version != "1.0") {
        throw RecipeError(
            "recipe schema version " + python_repr_string(version) +
            " is newer than this build supports (" +
            std::string(kRecipeSchemaVersion) +
            ") — upgrade paleo-workbench");
    }
    Json migrated = data;
    if (!migrated.contains("workflow")) {
        migrated["workflow"] = Json::object();  // setdefault: appended last
    }
    Json& workflow = migrated.at("workflow");
    if (!workflow.is_object()) {
        // Python: .setdefault on e.g. None raises AttributeError; refuse.
        throw workflow_spec::ModelError("workflow: expected an object");
    }
    if (!workflow.contains("schema_version")) {
        workflow["schema_version"] =
            std::string(workflow_spec::kWorkflowSchemaVersion);
    }
    return migrated;
}

// -------------------------------------------------------------- save/load --

std::vector<std::string> validate_recipe(
    const RecipeDocument& recipe, const workflow_spec::ActionCatalog& registry) {
    std::vector<std::string> problems = structural_problems(recipe.to_dict());
    for (const std::string& problem :
         workflow_spec::validate_workflow_spec(recipe.workflow, registry)) {
        problems.push_back(problem);
    }
    return problems;
}

std::filesystem::path save_recipe(const RecipeDocument& recipe,
                                  std::filesystem::path path,
                                  const SaveRecipeOptions& options) {
    // The structural security gate runs BEFORE anything is written.
    std::vector<std::string> problems = structural_problems(recipe.to_dict());
    if (!problems.empty()) {
        throw RecipeError(join_problems(problems));
    }
    if (options.registry != nullptr) {
        problems = workflow_spec::validate_workflow_spec(recipe.workflow,
                                                         *options.registry);
        if (!problems.empty()) {
            throw RecipeError(join_problems(problems));
        }
    }
    // .json suffix rewrite (L160): only when the name does not already
    // end with the full recipe suffix.
    const std::string name = path.filename().string();
    if (py_path_suffix(name) == ".json" &&
        !name.ends_with(std::string_view(kRecipeSuffix))) {
        const std::string renamed =
            py_path_stem(name) + std::string(kRecipeSuffix);
        const std::filesystem::path parent0 = path.parent_path();
        path = parent0.empty() ? std::filesystem::path(renamed)
                               : parent0 / renamed;
    }
    std::filesystem::path parent = path.parent_path();
    if (parent.empty()) parent = ".";  // Path("x").parent == Path(".")
    std::error_code ec;
    if (!std::filesystem::exists(parent, ec)) {
        std::filesystem::create_directories(parent, ec);  // parents=True
        if (ec) {
            throw RecipeError("cannot create directory " + parent.string() +
                              ": " + ec.message());
        }
    }
    // tempfile.mkstemp(dir=parent, prefix=".tmp-recipe-") stand-in: pid +
    // process-local counter keeps concurrent writers apart (store.cpp
    // precedent); the dot prefix keeps the file invisible to listings.
    const std::filesystem::path tmp =
        parent / (".tmp-recipe-" + std::to_string(current_pid()) + "-" +
                  std::to_string(next_tmp_counter()));
    try {
        {
            std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
            if (!out) {
                throw RecipeError("cannot open " + tmp.string() +
                                  " for writing");
            }
            // json.dump(payload, fh, ensure_ascii=False, indent=1) — NO
            // trailing newline (byte-frozen, E-3).
            out << recipe.to_dict().dump(1, ' ', false);
            out.flush();
            if (!out) {
                throw RecipeError("cannot write " + tmp.string());
            }
        }
        // os.replace: POSIX rename over an existing file is atomic.
        std::filesystem::rename(tmp, path, ec);
        if (ec) {
            throw RecipeError("cannot rename " + tmp.string() + " to " +
                              path.string() + ": " + ec.message());
        }
    } catch (...) {
        std::error_code unlink_ec;
        std::filesystem::remove(tmp, unlink_ec);  // best-effort, rethrow
        throw;
    }
    return path;
}

RecipeDocument load_recipe(const std::filesystem::path& path) {
    const std::string name = path.filename().string();
    std::error_code ec;
    if (!std::filesystem::exists(path, ec)) {
        throw RecipeError("recipe file " + python_repr_string(name) +
                          " does not exist");
    }
    std::string text;
    {
        std::ostringstream buffer;
        std::ifstream in(path, std::ios::binary);
        buffer << in.rdbuf();
        text = buffer.str();
    }
    // CPython-parity parse errors first (byte-frozen detail); inputs the
    // scanner accepts but nlohmann rejects (NaN/Infinity literals, "5."
    // floats) fall through to nlohmann's own wording — documented
    // divergence class.
    if (const std::optional<std::string> detail = cpython_json_detail(text)) {
        throw RecipeError("recipe " + python_repr_string(name) +
                          " is not valid JSON: " + *detail);
    }
    Json data;
    try {
        data = Json::parse(text);
    } catch (const std::exception& exc) {
        throw RecipeError("recipe " + python_repr_string(name) +
                          " is not valid JSON: " + exc.what());
    }
    const std::vector<std::string> problems = structural_problems(data);
    if (!problems.empty()) {
        throw RecipeError(join_problems(problems));
    }
    return RecipeDocument::from_dict(data);
}

// ------------------------------------------------------- lifecycle helpers --

RecipeDocument recipe_from_spec(const workflow_spec::WorkflowSpec& workflow,
                                const std::optional<std::string>& recipe_id,
                                const std::string& description,
                                const std::vector<std::string>& tags,
                                const Clock& clock) {
    RecipeDocument doc;
    // recipe_id or _slug(workflow.workflow_id) — empty string is falsy.
    doc.recipe_id = recipe_id.has_value() && !recipe_id->empty()
                        ? *recipe_id
                        : slugify(workflow.workflow_id);
    doc.name = workflow.name;
    doc.workflow = workflow;
    // description or workflow.description — empty string is falsy.
    doc.description = !description.empty() ? description
                                           : workflow.description;
    doc.created_at = clock ? clock() : wall_clock_seconds();
    doc.tags = tags;
    return doc;
}

RecipeDocument recipe_from_run(const workflow_spec::WorkflowRun& run,
                               const std::vector<std::string>& tags,
                               const Clock& clock) {
    const workflow_spec::WorkflowSpec& workflow = run.workflow;
    // Slot values become the slot defaults so the recipe re-runs with new
    // inputs by overriding them; every other slot field is carried.
    workflow_spec::WorkflowSpec migrated = workflow;
    migrated.slots.clear();
    for (const workflow_spec::SlotSpec& slot : workflow.slots) {
        workflow_spec::SlotSpec promoted = slot;
        if (run.slot_values.is_object()) {
            const Json* value = py_get(run.slot_values, slot.name);
            if (value != nullptr) {
                promoted.default_value = *value;
            }
        }
        migrated.slots.push_back(std::move(promoted));
    }
    RecipeDocument doc;
    doc.recipe_id = slugify(workflow.workflow_id);
    doc.name = workflow.name;
    doc.workflow = std::move(migrated);
    doc.description = workflow.description;
    doc.created_at = clock ? clock() : wall_clock_seconds();
    doc.source_run_id = run.run_id;
    doc.tags = tags;
    return doc;
}

RecipeDocument clone_recipe(const RecipeDocument& recipe,
                            const std::optional<std::string>& new_recipe_id,
                            const Clock& clock) {
    // Deep copy via the JSON document (Python round-trips through
    // json.dumps/loads; to_dict is JSON-clean so the copy is equivalent).
    Json data = recipe.to_dict();
    data["recipe_id"] =
        new_recipe_id.has_value() && !new_recipe_id->empty()
            ? *new_recipe_id
            : recipe.recipe_id + "-clone";
    data["created_at"] = Json(clock ? clock() : wall_clock_seconds());
    data["source_run_id"] = nullptr;
    return RecipeDocument::from_dict(data);
}

Json diff_recipes(const RecipeDocument& a, const RecipeDocument& b) {
    Json changes = Json::object();
    // Nodes (std::map keeps the sorted iteration Python's sorted() gives).
    std::map<std::string, Json> an;
    for (const auto& node : a.workflow.nodes) an[node.node_id] = node.to_dict();
    std::map<std::string, Json> bn;
    for (const auto& node : b.workflow.nodes) bn[node.node_id] = node.to_dict();
    Json added = Json::array();
    for (const auto& [id, dict] : bn) {
        (void)dict;
        if (an.find(id) == an.end()) added.push_back(id);
    }
    if (!added.empty()) changes["nodes_added"] = std::move(added);
    Json removed = Json::array();
    for (const auto& [id, dict] : an) {
        (void)dict;
        if (bn.find(id) == bn.end()) removed.push_back(id);
    }
    if (!removed.empty()) changes["nodes_removed"] = std::move(removed);
    Json changed = Json::object();
    for (const auto& [id, left] : an) {
        const auto it = bn.find(id);
        if (it == bn.end()) continue;
        const Json& right = it->second;
        if (py_object_equal(left, right)) continue;
        // fields = sorted(k for k in set(a) | set(b)
        //                 if a.get(k) != b.get(k))
        std::set<std::string> keys;
        for (const auto& [key, value] : left.items()) {
            (void)value;
            keys.insert(key);
        }
        for (const auto& [key, value] : right.items()) {
            (void)value;
            keys.insert(key);
        }
        Json fields = Json::array();
        for (const std::string& key : keys) {  // std::set == sorted
            if (!py_value_equal(py_get(left, key), py_get(right, key))) {
                fields.push_back(key);
            }
        }
        changed[id] = std::move(fields);
    }
    if (!changed.empty()) changes["nodes_changed"] = std::move(changed);
    // Slots (names only, no per-field detail).
    std::map<std::string, Json> a_slots;
    for (const auto& slot : a.workflow.slots) {
        a_slots[slot.name] = slot.to_dict();
    }
    std::map<std::string, Json> b_slots;
    for (const auto& slot : b.workflow.slots) {
        b_slots[slot.name] = slot.to_dict();
    }
    Json slots_added = Json::array();
    for (const auto& [name, dict] : b_slots) {
        (void)dict;
        if (a_slots.find(name) == a_slots.end()) slots_added.push_back(name);
    }
    if (!slots_added.empty()) changes["slots_added"] = std::move(slots_added);
    Json slots_removed = Json::array();
    for (const auto& [name, dict] : a_slots) {
        (void)dict;
        if (b_slots.find(name) == b_slots.end()) slots_removed.push_back(name);
    }
    if (!slots_removed.empty()) {
        changes["slots_removed"] = std::move(slots_removed);
    }
    Json slots_changed = Json::array();
    for (const auto& [name, left] : a_slots) {
        const auto it = b_slots.find(name);
        if (it != b_slots.end() && !py_object_equal(left, it->second)) {
            slots_changed.push_back(name);
        }
    }
    if (!slots_changed.empty()) {
        changes["slots_changed"] = std::move(slots_changed);
    }
    if (a.workflow.max_concurrency != b.workflow.max_concurrency) {
        changes["max_concurrency"] =
            Json::array({a.workflow.max_concurrency,
                         b.workflow.max_concurrency});
    }
    return changes;
}

Json inspect_recipe(const RecipeDocument& recipe) {
    Json out;
    out["recipe_id"] = recipe.recipe_id;
    out["name"] = recipe.name;
    out["description"] = recipe.description;
    out["schema_version"] = recipe.schema_version;
    out["source_run_id"] = recipe.source_run_id.has_value()
                               ? Json(*recipe.source_run_id)
                               : Json(nullptr);
    out["tags"] = Json::array();
    for (const auto& tag : recipe.tags) out["tags"].push_back(tag);
    out["workflow_id"] = recipe.workflow.workflow_id;
    out["nodes"] = Json::array();
    for (const auto& node : recipe.workflow.nodes) {
        Json n;
        n["node_id"] = node.node_id;
        n["action_id"] = node.action_id;
        n["depends_on"] = Json::array();
        for (const auto& dep : node.depends_on) n["depends_on"].push_back(dep);
        n["description"] = node.description;
        out["nodes"].push_back(std::move(n));
    }
    out["slots"] = Json::array();
    for (const auto& slot : recipe.workflow.slots) {
        out["slots"].push_back(slot.to_dict());
    }
    out["max_concurrency"] = recipe.workflow.max_concurrency;
    return out;
}

}  // namespace pwb::workflow_engine
