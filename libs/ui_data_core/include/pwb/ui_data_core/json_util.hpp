// Small helpers over pwb::domain::Json (nlohmann::ordered_json) that mirror
// the Python "dict or attribute" access patterns the UI-03 ports use.
#pragma once

#include "pwb/domain/json.hpp"

#include <cstdio>
#include <optional>
#include <string>
#include <string_view>

namespace pwb::ui_data_core {

// Python str.strip() — whitespace-trimmed copy (ASCII whitespace set).
inline std::string strip_copy(std::string_view value) {
    const auto begin = value.find_first_not_of(" \t\n\r\v\f");
    if (begin == std::string_view::npos) {
        return {};
    }
    const auto end = value.find_last_not_of(" \t\n\r\v\f");
    return std::string(value.substr(begin, end - begin + 1));
}

// dict.get(key, default) for a JSON object; non-object or missing → default.
inline std::string json_get_string(const domain::Json& object,
                                   std::string_view key,
                                   std::string_view fallback = "") {
    if (!object.is_object()) {
        return std::string(fallback);
    }
    const auto it = object.find(std::string(key));
    if (it == object.end() || it->is_null()) {
        return std::string(fallback);
    }
    if (it->is_string()) {
        return it->get<std::string>();
    }
    if (it->is_boolean()) {
        return it->get<bool>() ? "True" : "False";
    }
    if (it->is_number_integer() || it->is_number_unsigned()) {
        return std::to_string(it->get<long long>());
    }
    if (it->is_number_float()) {
        return it->dump();
    }
    return std::string(fallback);
}

// dict.get(key) → optional string (null/missing → nullopt).
inline std::optional<std::string> json_get_opt_string(const domain::Json& object,
                                                    std::string_view key) {
    if (!object.is_object()) {
        return std::nullopt;
    }
    const auto it = object.find(std::string(key));
    if (it == object.end() || it->is_null()) {
        return std::nullopt;
    }
    if (it->is_string()) {
        return it->get<std::string>();
    }
    if (it->is_boolean()) {
        return it->get<bool>() ? std::string("True") : std::string("False");
    }
    if (it->is_number_integer() || it->is_number_unsigned()) {
        return std::to_string(it->get<long long>());
    }
    if (it->is_number_float()) {
        return it->dump();
    }
    return std::nullopt;
}

// dict.get(key) → optional int (non-numeric → nullopt).
inline std::optional<long long> json_get_opt_int(const domain::Json& object,
                                                 std::string_view key) {
    if (!object.is_object()) {
        return std::nullopt;
    }
    const auto it = object.find(std::string(key));
    if (it == object.end() || it->is_null()) {
        return std::nullopt;
    }
    if (it->is_number_integer() || it->is_number_unsigned()) {
        return it->get<long long>();
    }
    if (it->is_number_float()) {
        return static_cast<long long>(it->get<double>());
    }
    if (it->is_boolean()) {
        return it->get<bool>() ? 1LL : 0LL;
    }
    return std::nullopt;
}

// dict.get(key) → optional double.
inline std::optional<double> json_get_opt_double(const domain::Json& object,
                                                 std::string_view key) {
    if (!object.is_object()) {
        return std::nullopt;
    }
    const auto it = object.find(std::string(key));
    if (it == object.end() || it->is_null()) {
        return std::nullopt;
    }
    if (it->is_number()) {
        return it->get<double>();
    }
    return std::nullopt;
}

// Python ``bool(value)`` truthiness over JSON: null → False, numbers → != 0,
// strings/collections → non-empty.
inline bool json_truthy(const domain::Json& value) {
    if (value.is_null()) {
        return false;
    }
    if (value.is_boolean()) {
        return value.get<bool>();
    }
    if (value.is_number()) {
        return value.get<double>() != 0.0;
    }
    if (value.is_string()) {
        return !value.get<std::string>().empty();
    }
    return !value.empty();  // arrays / objects: len() > 0
}

// bool(object.get(key, fallback)) — a present-but-null member is False in
// Python regardless of the default, and so is here.
inline bool json_get_bool(const domain::Json& object, std::string_view key,
                          bool fallback = false) {
    if (!object.is_object()) {
        return fallback;
    }
    const auto it = object.find(std::string(key));
    if (it == object.end()) {
        return fallback;
    }
    return json_truthy(*it);
}

// Whether the object carries a non-null member.
inline bool json_has(const domain::Json& object, std::string_view key) {
    return object.is_object() && object.find(std::string(key)) != object.end() &&
           !object.at(std::string(key)).is_null();
}

// Python str() of a JSON value for haystack/preview purposes.
inline std::string json_str(const domain::Json& value) {
    if (value.is_null()) {
        return "None";
    }
    if (value.is_boolean()) {
        return value.get<bool>() ? "True" : "False";
    }
    if (value.is_string()) {
        return value.get<std::string>();
    }
    return value.dump();
}

// Python repr() of a JSON value — used where Python interpolates a dict/list
// into a string (``str(parsed_summary)`` in the search haystack). Strings get
// Python's quote rules (' preferred, " when the text holds '), bools render
// True/False, null → None, containers get the [..]/{..} repr.
inline std::string python_repr(const domain::Json& value) {
    if (value.is_null()) {
        return "None";
    }
    if (value.is_boolean()) {
        return value.get<bool>() ? "True" : "False";
    }
    if (value.is_number_integer() || value.is_number_unsigned()) {
        return std::to_string(value.get<long long>());
    }
    if (value.is_number_float()) {
        return value.dump();
    }
    if (value.is_string()) {
        const std::string s = value.get<std::string>();
        const bool has_single = s.find('\'') != std::string::npos;
        const bool has_double = s.find('"') != std::string::npos;
        const char quote = (has_single && !has_double) ? '"' : '\'';
        std::string out;
        out.push_back(quote);
        for (const char c : s) {
            switch (c) {
                case '\\': out += "\\\\"; break;
                case '\n': out += "\\n"; break;
                case '\r': out += "\\r"; break;
                case '\t': out += "\\t"; break;
                default:
                    if (c == quote) {
                        out.push_back('\\');
                        out.push_back(c);
                    } else if (static_cast<unsigned char>(c) < 0x20 ||
                               static_cast<unsigned char>(c) == 0x7f) {
                        char buf[8];
                        std::snprintf(buf, sizeof(buf), "\\x%02x",
                                      static_cast<unsigned char>(c));
                        out += buf;
                    } else {
                        out.push_back(c);
                    }
            }
        }
        out.push_back(quote);
        return out;
    }
    if (value.is_array()) {
        std::string out = "[";
        bool first = true;
        for (const auto& elem : value) {
            if (!first) out += ", ";
            out += python_repr(elem);
            first = false;
        }
        out += "]";
        return out;
    }
    if (value.is_object()) {
        std::string out = "{";
        bool first = true;
        for (const auto& [key, elem] : value.items()) {
            if (!first) out += ", ";
            out += python_repr(domain::Json(key));
            out += ": ";
            out += python_repr(elem);
            first = false;
        }
        out += "}";
        return out;
    }
    return value.dump();
}

// Python str(value): strings pass through, everything else reprs.
inline std::string python_str(const domain::Json& value) {
    return value.is_string() ? value.get<std::string>() : python_repr(value);
}

// PurePosixPath(p).name — the last component ignoring "" and "." parts
// (std::filesystem::path("foo/").filename() is "" but Python's is "foo";
// PurePosixPath("a/./b").name is "b"; "/" → "").
inline std::string python_path_name(std::string_view path) {
    std::string name;
    std::size_t pos = 0;
    while (pos <= path.size()) {
        const auto slash = path.find('/', pos);
        const std::string_view part =
            slash == std::string_view::npos
                ? path.substr(pos)
                : path.substr(pos, slash - pos);
        if (!part.empty() && part != ".") {
            name = std::string(part);
        }
        if (slash == std::string_view::npos) {
            break;
        }
        pos = slash + 1;
    }
    return name;
}

}  // namespace pwb::ui_data_core
