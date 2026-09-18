#include "python_repr.hpp"

#include <cmath>
#include <cstdio>
#include <cstdlib>

#include <pwb/workflow_spec/model.hpp>

namespace pwb::workflow_spec::detail {
namespace {

void append_py_repr(std::string& out, const domain::Json& value) {
    switch (value.type()) {
    case domain::Json::value_t::null:
        out += "None";
        return;
    case domain::Json::value_t::boolean:
        out += value.get<bool>() ? "True" : "False";
        return;
    case domain::Json::value_t::number_integer:
    case domain::Json::value_t::number_unsigned: {
        out += std::to_string(value.get<long long>());
        return;
    }
    case domain::Json::value_t::number_float:
        out += py_repr_double(value.get<double>());
        return;
    case domain::Json::value_t::string: {
        const std::string text = value.get<std::string>();
        // Python repr: prefer single quotes; switch to double quotes when
        // the text contains ' and no ".
        const bool has_single = text.find('\'') != std::string::npos;
        const bool has_double = text.find('"') != std::string::npos;
        const char quote = (has_single && !has_double) ? '"' : '\'';
        out += quote;
        for (const char ch : text) {
            switch (ch) {
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (ch == quote) {
                    out += '\\';
                    out += ch;
                } else if (static_cast<unsigned char>(ch) < 0x20 ||
                           static_cast<unsigned char>(ch) == 0x7f) {
                    char escape[8];
                    std::snprintf(escape, sizeof(escape), "\\x%02x",
                                  static_cast<unsigned char>(ch));
                    out += escape;
                } else {
                    out += ch;
                }
            }
        }
        out += quote;
        return;
    }
    case domain::Json::value_t::array: {
        out += '[';
        bool first = true;
        for (const auto& item : value) {
            if (!first) {
                out += ", ";
            }
            first = false;
            append_py_repr(out, item);
        }
        out += ']';
        return;
    }
    case domain::Json::value_t::object: {
        out += '{';
        bool first = true;
        for (const auto& [key, item] : value.items()) {
            if (!first) {
                out += ", ";
            }
            first = false;
            append_py_repr(out, domain::Json(key));
            out += ": ";
            append_py_repr(out, item);
        }
        out += '}';
        return;
    }
    default:
        out += "<?>";
        return;
    }
}

}  // namespace

std::string py_repr(const domain::Json& value) {
    std::string out;
    append_py_repr(out, value);
    return out;
}

std::string py_str_number(const domain::Json& value) {
    if (value.is_number_integer() || value.is_number_unsigned()) {
        return std::to_string(value.get<long long>());
    }
    return py_repr_double(value.get<double>());
}

std::string py_type_name(const domain::Json& value) {
    switch (value.type()) {
    case domain::Json::value_t::null:
        return "NoneType";
    case domain::Json::value_t::boolean:
        return "bool";
    case domain::Json::value_t::number_integer:
    case domain::Json::value_t::number_unsigned:
        return "int";
    case domain::Json::value_t::number_float:
        return "float";
    case domain::Json::value_t::string:
        return "str";
    case domain::Json::value_t::array:
        return "list";
    case domain::Json::value_t::object:
        return "dict";
    default:
        return "<?>";
    }
}

std::string py_str_scalar(const domain::Json& value) {
    std::string out;
    append_py_repr(out, value);
    // Python str() and repr() coincide for every JSON scalar except str
    // itself, which str() leaves unquoted.
    if (value.is_string()) {
        return value.get<std::string>();
    }
    return out;
}

std::string py_repr_double(double value) {
    if (std::isnan(value)) {
        return "nan";
    }
    if (std::isinf(value)) {
        return value > 0 ? "inf" : "-inf";
    }
    // Shortest round-trip digits (Python repr strategy), then restore the
    // ".0" for integral values the way Python prints floats.
    char buffer[64] = {0};
    for (int precision = 1; precision <= 17; ++precision) {
        std::snprintf(buffer, sizeof(buffer), "%.*g", precision, value);
        if (std::strtod(buffer, nullptr) == value) {
            break;
        }
    }
    std::string text(buffer);
    const bool needs_plain_dot =
        text.find('.') == std::string::npos &&
        text.find('e') == std::string::npos &&
        text.find('E') == std::string::npos &&
        text.find("inf") == std::string::npos &&
        text.find("nan") == std::string::npos;
    if (needs_plain_dot) {
        text += ".0";
    }
    return text;
}

int json_to_int(const domain::Json& value, const char* field) {
    // Python int(x): integers pass, floats truncate toward zero. Booleans
    // are rejected at the JSON layer (bool is not a number in nlohmann).
    if (value.is_number_integer() || value.is_number_unsigned()) {
        return static_cast<int>(value.get<long long>());
    }
    if (value.is_number_float()) {
        return static_cast<int>(value.get<double>());
    }
    throw ModelError(std::string(field) + ": expected a number");
}

double json_to_double(const domain::Json& value, const char* field) {
    if (value.is_number()) {
        return value.get<double>();
    }
    throw ModelError(std::string(field) + ": expected a number");
}

bool json_to_bool(const domain::Json& value) {
    // bool(x) truthiness: null/0/""/empty containers are falsy.
    if (value.is_null()) return false;
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_number()) return value.get<double>() != 0.0;
    if (value.is_string()) return !value.get<std::string>().empty();
    return !value.empty();
}

const domain::Json& required_key(const domain::Json& data, const char* key) {
    const auto it = data.find(key);
    if (it == data.end()) {
        throw ModelError(std::string("missing required key '") + key + "'");
    }
    return *it;
}

}  // namespace pwb::workflow_spec::detail
