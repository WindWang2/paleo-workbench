#include "pwb/prediction/input_contract.hpp"

#include <stdexcept>

#include "pwb/prediction/errors.hpp"
#include "python_compat.hpp"

namespace pwb::prediction {

namespace {

using detail::py_int;
using detail::py_or;
using detail::py_str;
using detail::py_strip;
using detail::py_truthy;

const Json kNull;

const Json& get(const Json& obj, const char* key) {
    if (!obj.is_object()) return kNull;
    const auto it = obj.find(key);
    return it == obj.end() ? kNull : *it;
}

// Iterate a schema list the way Python does: str was already wrapped to
// [str] by the caller; a dict yields its keys; an array yields elements;
// anything else is a TypeError ("'T' object is not iterable").
Json normalized_list(const Json& raw, const Json& fallback) {
    Json value = py_or(raw, fallback);
    if (value.is_string()) value = Json::array({value});
    Json out = Json::array();
    auto push = [&](const Json& item) {
        const std::string s = py_strip(py_str(item));
        if (!s.empty()) out.push_back(s);
    };
    if (value.is_array()) {
        for (const auto& item : value) push(item);
    } else if (value.is_object()) {
        // Iterating a dict yields its keys (strings).
        for (const auto& [key, val] : value.items()) push(Json(key));
    } else if (py_truthy(value)) {
        throw TypeError("'" + detail::py_type_name(value) +
                        "' object is not iterable");
    }
    return out;
}

}  // namespace

// dict(value) coercion: object -> copy; array -> pair conversion
// (dict elements merge as mappings, len-2 sequences become pairs, anything
// else fails with the CPython sequence-element error); string -> the
// element-length ValueError (chars are 1-element); other truthy values ->
// not-iterable TypeError.
Json dict_coerce(const Json& v) {
    if (v.is_object()) return v;
    if (v.is_string()) {
        throw ValueError(
            "dictionary update sequence element #0 has length 1; 2 is "
            "required");
    }
    if (v.is_array()) {
        Json out = Json::object();
        size_t i = 0;
        for (const auto& el : v) {
            const std::string idx = std::to_string(i++);
            if (el.is_object()) {
                for (const auto& [k, val] : el.items()) out[k] = val;
                continue;
            }
            const size_t n =
                el.is_array() ? el.size()
                              : (el.is_string() ? 1 : 0);
            if (el.is_array() && n == 2) {
                out[py_str(el[0])] = el[1];
            } else if (el.is_array() || el.is_string()) {
                throw ValueError("dictionary update sequence element #" + idx +
                                 " has length " + std::to_string(n) +
                                 "; 2 is required");
            } else {
                throw TypeError(
                    "cannot convert dictionary update sequence element #" +
                    idx + " to a sequence");
            }
        }
        return out;
    }
    throw TypeError("'" + detail::py_type_name(v) +
                    "' object is not iterable");
}

Json parse_input_schema(const Json& schema) {
    // schema = dict(schema or {}).
    Json sch = py_truthy(schema) ? dict_coerce(schema) : Json::object();
    const Json empty_list = Json::array();
    return Json{
        {"required_asset_types",
         normalized_list(get(sch, "required_asset_types"),
                         py_or(get(sch, "asset_types"), empty_list))},
        {"optional_asset_types",
         normalized_list(get(sch, "optional_asset_types"), empty_list)},
        {"required_curves",
         normalized_list(get(sch, "required_curves"),
                         py_or(get(sch, "curves"), empty_list))},
        {"require_target_horizon",
         py_truthy(get(sch, "require_target_horizon"))},
        {"require_correlation", py_truthy(get(sch, "require_correlation"))},
        {"require_horizon_interpretation",
         py_truthy(get(sch, "require_horizon_interpretation"))},
        {"require_fault_interpretation",
         py_truthy(get(sch, "require_fault_interpretation"))},
        {"min_wells", py_int(py_or(get(sch, "min_wells"), Json(0)))},
        {"raw", sch},
    };
}

}  // namespace pwb::prediction
