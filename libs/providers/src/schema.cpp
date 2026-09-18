#include <pwb/providers/schema.hpp>

#include <cmath>

namespace pwb::providers {

namespace {

// _JSON_TYPES from execution.py.
bool is_known_json_type(const std::string& name) {
    return name == "object" || name == "array" || name == "string" ||
           name == "integer" || name == "number" || name == "boolean" ||
           name == "null";
}

bool type_matches(const std::string& expected, const Json& value) {
    bool ok;
    if (expected == "object") {
        ok = value.is_object();
    } else if (expected == "array") {
        ok = value.is_array();
    } else if (expected == "string") {
        ok = value.is_string();
    } else if (expected == "integer") {
        ok = value.is_number_integer();
    } else if (expected == "number") {
        ok = value.is_number();
    } else if (expected == "boolean") {
        ok = value.is_boolean();
    } else if (expected == "null") {
        ok = value.is_null();
    } else {
        return false;  // unknown type name never matches
    }
    if (!ok) return false;
    // Python parity: bool is never integer/number.
    if ((expected == "integer" || expected == "number") && value.is_boolean()) {
        return false;
    }
    return true;
}

// Python equality semantics for enum membership: bool == int == float by
// numeric value, strings exact, null only null, arrays/objects elementwise.
bool py_json_equal(const Json& a, const Json& b) {
    if (a.type() != b.type()) {
        const bool a_num = a.is_number() || a.is_boolean();
        const bool b_num = b.is_number() || b.is_boolean();
        if (a_num && b_num) {
            const double av = a.is_boolean() ? (a == true ? 1.0 : 0.0) : a.get<double>();
            const double bv = b.is_boolean() ? (b == true ? 1.0 : 0.0) : b.get<double>();
            return av == bv;
        }
        return false;
    }
    if (a.is_array()) {
        if (a.size() != b.size()) return false;
        for (std::size_t i = 0; i < a.size(); ++i) {
            if (!py_json_equal(a[i], b[i])) return false;
        }
        return true;
    }
    if (a.is_object()) {
        if (a.size() != b.size()) return false;
        for (auto it = a.begin(); it != a.end(); ++it) {
            if (!b.contains(it.key()) || !py_json_equal(it.value(), b[it.key()])) {
                return false;
            }
        }
        return true;
    }
    return a == b;
}

// Python `str(member)` for union member extraction: strings pass through,
// null → "None", bool → "True"/"False", numbers shortest form.
std::string python_str_member(const Json& value) {
    if (value.is_string()) return value.get<std::string>();
    return python_str(value);
}

void check(const Json& value, const Json& sub, const std::string& path,
           std::vector<std::string>& problems) {
    const Json expected = sub.contains("type") ? sub.at("type") : Json(nullptr);
    if (!expected.is_null()) {
        if (expected.is_array()) {
            // JSON Schema union (B3): valid when ANY known member matches; a
            // union whose members are all unknown names is a schema problem.
            std::vector<std::string> members;
            for (const auto& member : expected) {
                std::string name = python_str_member(member);
                if (!name.empty()) members.push_back(std::move(name));
            }
            std::vector<std::string> known;
            for (const auto& member : members) {
                if (is_known_json_type(member)) known.push_back(member);
            }
            bool matched = false;
            for (const auto& member : known) {
                if (type_matches(member, value)) {
                    matched = true;
                    break;
                }
            }
            if (!matched) {
                const std::string detail =
                    known.empty() ? " (no known JSON type in union)" : "";
                problems.push_back(path + ": expected one of " + python_repr(expected) +
                                   detail + ", got " + json_python_type_name(value));
                return;
            }
        } else {
            const std::string name = expected.is_string() ? expected.get<std::string>()
                                                          : python_str(expected);
            if (!is_known_json_type(name)) {
                // An unknown type string is reported, not trusted (B3).
                problems.push_back(path + ": unknown type " + python_repr(expected));
                return;
            }
            if (!type_matches(name, value)) {
                if ((name == "integer" || name == "number") && value.is_boolean()) {
                    problems.push_back(path + ": expected " + python_str(expected) +
                                       ", got boolean");
                } else {
                    problems.push_back(path + ": expected " + python_str(expected) +
                                       ", got " + json_python_type_name(value));
                }
                return;
            }
        }
    }

    if (sub.contains("enum")) {
        const Json& enum_values = sub.at("enum");
        if (enum_values.is_array()) {
            bool found = false;
            for (const auto& candidate : enum_values) {
                if (py_json_equal(candidate, value)) {
                    found = true;
                    break;
                }
            }
            if (!found) {
                problems.push_back(path + ": " + python_repr(value) + " not in enum " +
                                   python_repr(enum_values));
            }
        }
    }

    const bool numeric = !value.is_boolean() && (value.is_number_integer() ||
                                                 value.is_number_float());
    if (numeric) {
        if (sub.contains("minimum") && sub.at("minimum").is_number() &&
            value.get<double>() < sub.at("minimum").get<double>()) {
            problems.push_back(path + ": " + python_str(value) + " < minimum " +
                               python_str(sub.at("minimum")));
        }
        if (sub.contains("maximum") && sub.at("maximum").is_number() &&
            value.get<double>() > sub.at("maximum").get<double>()) {
            problems.push_back(path + ": " + python_str(value) + " > maximum " +
                               python_str(sub.at("maximum")));
        }
    }

    if (value.is_array()) {
        if (sub.contains("minItems") && sub.at("minItems").is_number_integer() &&
            value.size() < static_cast<std::size_t>(sub.at("minItems").get<long long>())) {
            problems.push_back(path + ": " + std::to_string(value.size()) +
                               " items < minItems " + python_str(sub.at("minItems")));
        }
        if (sub.contains("maxItems") && sub.at("maxItems").is_number_integer() &&
            value.size() > static_cast<std::size_t>(sub.at("maxItems").get<long long>())) {
            problems.push_back(path + ": " + std::to_string(value.size()) +
                               " items > maxItems " + python_str(sub.at("maxItems")));
        }
        if (sub.contains("items") && sub.at("items").is_object()) {
            const Json& items = sub.at("items");
            for (std::size_t i = 0; i < value.size(); ++i) {
                check(value[i], items, path + "[" + std::to_string(i) + "]", problems);
            }
        }
    }

    if (value.is_object()) {
        const Json empty_props = Json::object();
        const Json& properties = (sub.contains("properties") && sub.at("properties").is_object())
                                     ? sub.at("properties")
                                     : empty_props;
        if (sub.contains("required") && sub.at("required").is_array()) {
            for (const auto& key : sub.at("required")) {
                if (!key.is_string()) continue;
                if (!value.contains(key.get<std::string>())) {
                    problems.push_back(path + "." + key.get<std::string>() + ": required");
                }
            }
        }
        for (auto it = value.begin(); it != value.end(); ++it) {
            const std::string& key = it.key();
            const Json& item = it.value();
            const bool declared =
                properties.contains(key) && !properties.at(key).is_null();
            if (!declared) {
                if (sub.contains("additionalProperties") && sub.at("additionalProperties").is_boolean() &&
                    sub.at("additionalProperties") == false) {
                    problems.push_back(path + "." + key +
                                       ": not declared and additionalProperties false");
                }
                continue;
            }
            check(item, properties.at(key), path + "." + key, problems);
        }
    }
}

}  // namespace

std::string json_python_type_name(const Json& value) {
    if (value.is_null()) return "NoneType";
    if (value.is_boolean()) return "bool";
    if (value.is_number_integer()) return "int";
    if (value.is_number_float()) return "float";
    if (value.is_string()) return "str";
    if (value.is_array()) return "list";
    if (value.is_object()) return "dict";
    return "object";
}

std::string python_repr(const Json& value) {
    if (value.is_null()) return "None";
    if (value.is_boolean()) return value == true ? "True" : "False";
    if (value.is_number_integer()) return value.dump();
    if (value.is_number_float()) {
        // nlohmann dumps non-finite doubles as null; Python str/repr uses
        // inf/-inf/nan (parity for boundary messages).
        const double raw = value.get<double>();
        if (std::isnan(raw)) return "nan";
        if (std::isinf(raw)) return raw > 0 ? "inf" : "-inf";
        return value.dump();  // shortest round-trip, Python repr parity
    }
    if (value.is_string()) {
        const std::string s = value.get<std::string>();
        if (s.find('\'') != std::string::npos && s.find('"') == std::string::npos) {
            return "\"" + s + "\"";
        }
        return "'" + s + "'";
    }
    if (value.is_array()) {
        std::string out = "[";
        for (std::size_t i = 0; i < value.size(); ++i) {
            if (i != 0) out += ", ";
            out += python_repr(value[i]);
        }
        return out + "]";
    }
    if (value.is_object()) {
        std::string out = "{";
        bool first = true;
        for (auto it = value.begin(); it != value.end(); ++it) {
            if (!first) out += ", ";
            first = false;
            out += python_repr(Json(it.key())) + ": " + python_repr(it.value());
        }
        return out + "}";
    }
    return value.dump();
}

std::string python_str(const Json& value) {
    if (value.is_string()) return value.get<std::string>();
    return python_repr(value);
}

std::vector<std::string> validate_parameters(const Json& schema, const Json& parameters,
                                             const std::string& label) {
    std::vector<std::string> problems;
    const Json default_type = Json("object");
    const Json schema_type =
        schema.is_object() && schema.contains("type") ? schema.at("type") : default_type;
    if (schema_type.is_string() && schema_type == "object" && !parameters.is_object()) {
        problems.push_back(label + ": expected object");
        return problems;
    }
    check(parameters, schema, label, problems);
    return problems;
}

}  // namespace pwb::providers
