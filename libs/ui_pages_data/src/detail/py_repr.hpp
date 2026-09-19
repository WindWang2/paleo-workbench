// UI-06 internal — Python repr()/str() for JSON-compatible values.
// Shared by onboarding_report.cpp and wizard_model.cpp (issue/warning
// items go through str(item) in the Python source).
#pragma once

#include <cstdio>
#include <string>

#include <pwb/domain/json.hpp>

namespace pwb::ui_pages_data::detail {

inline std::string repr_string(const std::string& s) {
    // Python str repr: single quotes, escapes backslash/quote/newline/tab.
    std::string out = "'";
    for (char c : s) {
        if (c == '\\') out += "\\\\";
        else if (c == '\'') out += "\\'";
        else if (c == '\n') out += "\\n";
        else if (c == '\r') out += "\\r";
        else if (c == '\t') out += "\\t";
        else out += c;
    }
    return out + "'";
}

inline std::string py_repr(const domain::Json& v) {
    if (v.is_null()) return "None";
    if (v.is_boolean()) return v.get<bool>() ? "True" : "False";
    if (v.is_number_integer() || v.is_number_unsigned())
        return std::to_string(v.get<long long>());
    if (v.is_number_float()) {
        char buf[64];
        std::snprintf(buf, sizeof(buf), "%.17g", v.get<double>());
        return buf;
    }
    if (v.is_string()) return repr_string(v.get<std::string>());
    if (v.is_array()) {
        std::string out = "[";
        bool first = true;
        for (const auto& item : v) {
            if (!first) out += ", ";
            first = false;
            out += py_repr(item);
        }
        return out + "]";
    }
    if (v.is_object()) {
        std::string out = "{";
        bool first = true;
        for (const auto& [k, val] : v.items()) {
            if (!first) out += ", ";
            first = false;
            out += repr_string(k) + ": " + py_repr(val);
        }
        return out + "}";
    }
    return "";
}

// str(v) at top level: strings stay bare, everything else uses repr.
inline std::string py_str(const domain::Json& v) {
    if (v.is_string()) return v.get<std::string>();
    return py_repr(v);
}

}  // namespace pwb::ui_pages_data::detail
