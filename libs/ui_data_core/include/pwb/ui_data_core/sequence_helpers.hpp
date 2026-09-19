// sequence_helpers.py port — ``field_value(source, name, default="")``.
//
// Python semantics: ``dict.get`` for mappings, ``getattr`` otherwise. In
// C++ the mapping case lands on domain::Json objects; the attribute case is
// served by a caller-supplied getter (C++ has no runtime reflection), which
// preserves the contract for the structured records this slice defines.
#pragma once

#include "pwb/domain/json.hpp"
#include "pwb/ui_data_core/json_util.hpp"

#include <functional>
#include <optional>
#include <string>
#include <string_view>

namespace pwb::ui_data_core {

// Mapping case: JSON object → member lookup, else default.
inline domain::Json field_value(const domain::Json& source, std::string_view name,
                                const domain::Json& fallback = domain::Json("")) {
    if (source.is_object()) {
        const auto it = source.find(std::string(name));
        if (it != source.end()) {
            return *it;
        }
        return fallback;
    }
    return fallback;
}

// String-typed convenience for the common call shape.
inline std::string field_value_string(const domain::Json& source,
                                      std::string_view name,
                                      std::string_view fallback = "") {
    if (source.is_object()) {
        const auto it = source.find(std::string(name));
        if (it != source.end()) {
            // dict.get(name, default): present-null → None → str → "None".
            if (it->is_null()) {
                return "None";
            }
            if (it->is_string()) {
                return it->get<std::string>();
            }
            return json_str(*it);
        }
    }
    return std::string(fallback);
}

// Attribute case: a typed record is queried through an accessor the record
// type provides. The accessor returns nullopt for "attribute missing".
inline std::string field_value(
    const std::function<std::optional<std::string>(std::string_view)>& getter,
    std::string_view name, std::string_view fallback = "") {
    const auto value = getter(name);
    return value.has_value() ? *value : std::string(fallback);
}

}  // namespace pwb::ui_data_core
