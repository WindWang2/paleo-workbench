// python_json.cpp — see include/pwb/closure_workflow/python_json.hpp.

#include <pwb/closure_workflow/python_json.hpp>

#include <pwb/factor_host/canonical_json.hpp>

#include <algorithm>
#include <cstdio>
#include <string>
#include <vector>

namespace pwb::closure_workflow {

namespace {

void append_escaped(std::string& out, const std::string& text) {
    out += '"';
    for (char raw : text) {
        const auto c = static_cast<unsigned char>(raw);
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\b': out += "\\b"; break;
            case '\f': out += "\\f"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    char buffer[8];
                    std::snprintf(buffer, sizeof buffer, "\\u%04x", c);
                    out += buffer;
                } else {
                    out += static_cast<char>(c);
                }
        }
    }
    out += '"';
}

void encode(std::string& out, const pwb::domain::Json& value,
            bool sort_keys) {
    if (value.is_null()) {
        out += "null";
    } else if (value.is_boolean()) {
        out += value.get<bool>() ? "true" : "false";
    } else if (value.is_number_integer()) {
        out += std::to_string(value.get<std::int64_t>());
    } else if (value.is_number_float()) {
        out += pwb::factor_host::python_repr_double(value.get<double>());
    } else if (value.is_string()) {
        append_escaped(out, value.get_ref<const std::string&>());
    } else if (value.is_array()) {
        out += '[';
        bool first = true;
        for (const auto& item : value) {
            if (!first) out += ", ";
            first = false;
            encode(out, item, sort_keys);
        }
        out += ']';
    } else if (value.is_object()) {
        std::vector<const std::string*> keys;
        keys.reserve(value.size());
        for (auto it = value.begin(); it != value.end(); ++it) {
            keys.push_back(&it.key());
        }
        if (sort_keys) {
            std::sort(keys.begin(), keys.end(),
                      [](const std::string* a, const std::string* b) {
                          return *a < *b;
                      });
        }
        out += '{';
        bool first = true;
        for (const std::string* key : keys) {
            if (!first) out += ", ";
            first = false;
            append_escaped(out, *key);
            out += ": ";
            encode(out, value.at(*key), sort_keys);
        }
        out += '}';
    }
}

}  // namespace

std::string python_dumps_sorted(const pwb::domain::Json& value) {
    std::string out;
    encode(out, value, true);
    return out;
}

std::string python_dumps(const pwb::domain::Json& value) {
    std::string out;
    encode(out, value, false);
    return out;
}

}  // namespace pwb::closure_workflow
