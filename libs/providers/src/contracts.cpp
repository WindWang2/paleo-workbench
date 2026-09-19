#include <pwb/providers/contracts.hpp>

#include <pwb/providers/errors.hpp>

#include <algorithm>
#include <cctype>
#include <regex>

namespace pwb::providers {

namespace {
// Python contracts.py: ^[a-z0-9][a-z0-9._-]{1,63}$ / ^[0-9]+(\.[0-9]+){0,3}$
const std::regex& id_pattern() {
    static const std::regex pattern(R"(^[a-z0-9][a-z0-9._-]{1,63}$)");
    return pattern;
}
const std::regex& version_pattern() {
    static const std::regex pattern(R"(^[0-9]+(\.[0-9]+){0,3}$)");
    return pattern;
}

// Python repr of a string: single quotes preferred, double quotes when the
// value contains a single quote but no double quote, and an escaped single
// quote when both kinds appear.
std::string repr_string(const std::string& value) {
    const bool has_single = value.find('\'') != std::string::npos;
    const bool has_double = value.find('"') != std::string::npos;
    if (has_single && !has_double) {
        return "\"" + value + "\"";
    }
    if (has_single) {
        std::string out = "'";
        for (char c : value) {
            if (c == '\'') out += "\\'";
            else out += c;
        }
        return out + "'";
    }
    return "'" + value + "'";
}

// Python repr of a list of strings: ['a', 'b'].
std::string repr_string_list(const std::vector<std::string>& values) {
    std::string out = "[";
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (i != 0) out += ", ";
        out += repr_string(values[i]);
    }
    return out + "]";
}
}  // namespace

std::string to_string(ProviderFamily family) {
    switch (family) {
        case ProviderFamily::Interpolation: return "interpolation";
        case ProviderFamily::SeismicAttribute: return "seismic_attribute";
        case ProviderFamily::Inference: return "inference";
        case ProviderFamily::Visualization: return "visualization";
        case ProviderFamily::Exporter: return "exporter";
        case ProviderFamily::Importer: return "importer";
        case ProviderFamily::DataFormat: return "data_format";
        case ProviderFamily::Preview: return "preview";
        case ProviderFamily::MapComponent: return "map_component";
    }
    return "interpolation";
}

std::optional<ProviderFamily> family_from_string(std::string_view value) {
    if (value == "interpolation") return ProviderFamily::Interpolation;
    if (value == "seismic_attribute") return ProviderFamily::SeismicAttribute;
    if (value == "inference") return ProviderFamily::Inference;
    if (value == "visualization") return ProviderFamily::Visualization;
    if (value == "exporter") return ProviderFamily::Exporter;
    if (value == "importer") return ProviderFamily::Importer;
    if (value == "data_format") return ProviderFamily::DataFormat;
    if (value == "preview") return ProviderFamily::Preview;
    if (value == "map_component") return ProviderFamily::MapComponent;
    return std::nullopt;
}

const std::vector<std::string>& typed_refs() {
    static const std::vector<std::string> kRefs = {
        "DataVersionRef", "FactorDatasetRef", "FactorGridRef",
        "GeologicalFactorDataset", "MapDocument", "MapDocumentRef",
        "PathRef", "SeismicVolumeRef", "WellRef",
    };
    return kRefs;
}

Json ResourceProfile::to_json() const {
    Json out = Json::object();
    out["estimated_cpu_cores"] = estimated_cpu_cores;
    out["estimated_ram_bytes"] = estimated_ram_bytes;
    out["estimated_vram_bytes"] = estimated_vram_bytes;
    out["io_weight"] = io_weight;
    out["category"] = category;
    return out;
}

Json ProviderDescriptor::to_json() const {
    Json out = Json::object();
    out["provider_id"] = provider_id;
    out["family"] = to_string(family);
    out["version"] = version;
    out["display_name"] = display_name;
    out["description"] = description;
    out["capabilities"] = capabilities;
    out["input_types"] = input_types;
    out["output_types"] = output_types;
    out["parameters_schema"] = parameters_schema;
    out["resource_profile"] = resource_profile.to_json();
    out["supports_cancel"] = supports_cancel;
    out["supports_resume"] = supports_resume;
    out["deterministic"] = deterministic;
    out["threading_model"] = threading_model;
    if (build_identity.has_value()) {
        out["build_identity"] = *build_identity;
    } else {
        out["build_identity"] = Json(nullptr);
    }
    return out;
}

std::vector<std::string> validate_descriptor(const ProviderDescriptor& descriptor) {
    std::vector<std::string> problems;

    if (!std::regex_match(descriptor.provider_id, id_pattern())) {
        problems.push_back("provider_id " + repr_string(descriptor.provider_id) +
                           " must match ^[a-z0-9][a-z0-9._-]{1,63}$");
    }
    if (!std::regex_match(descriptor.version, version_pattern())) {
        problems.push_back("version " + repr_string(descriptor.version) +
                           " must be numeric dotted (e.g. 1.0.0)");
    }
    // family: a C++ enum value is always a ProviderFamily (compile-time).
    const bool display_name_blank = std::all_of(descriptor.display_name.begin(),
                                                descriptor.display_name.end(),
                                                [](unsigned char c) {
                                                    return std::isspace(c) != 0;
                                                });
    if (display_name_blank) {
        problems.push_back("display_name must be a non-empty string");
    }

    const Json& schema = descriptor.parameters_schema;
    if (!schema.is_object()) {
        problems.push_back("parameters_schema must be a dict (JSON schema)");
    } else {
        const Json schema_type = schema.contains("type") ? schema.at("type") : Json(nullptr);
        if (!(schema_type.is_null() || (schema_type.is_string() && schema_type == "object"))) {
            problems.push_back("parameters_schema must describe an object at the top level");
        }
        if (schema.contains("properties") && !schema.at("properties").is_object()) {
            problems.push_back("parameters_schema.properties must be a dict");
        }
        if (schema.contains("required") && !schema.at("required").is_array()) {
            problems.push_back("parameters_schema.required must be a list");
        }
    }

    const auto check_typed_refs = [&problems](const std::string& role,
                                              const std::vector<std::string>& types) {
        for (const auto& type : types) {
            if (std::find(typed_refs().begin(), typed_refs().end(), type) ==
                typed_refs().end()) {
                problems.push_back(role + " entry " + repr_string(type) +
                                   " is not a known typed ref " +
                                   repr_string_list(typed_refs()));
            }
        }
    };
    check_typed_refs("input_types", descriptor.input_types);
    check_typed_refs("output_types", descriptor.output_types);

    if (descriptor.threading_model != "worker_thread" &&
        descriptor.threading_model != "gui_thread" && descriptor.threading_model != "any") {
        problems.push_back("threading_model " + repr_string(descriptor.threading_model) +
                           " invalid");
    }
    // build_identity: std::optional<std::string> is always a string or null.

    if (descriptor.resource_profile.estimated_cpu_cores <= 0.0) {
        problems.push_back("resource_profile.estimated_cpu_cores must be > 0");
    }
    if (descriptor.resource_profile.io_weight < 0.0) {
        problems.push_back("resource_profile.io_weight must be >= 0");
    }
    return problems;
}

void assert_valid_descriptor(const ProviderDescriptor& descriptor) {
    auto problems = validate_descriptor(descriptor);
    if (!problems.empty()) {
        throw InvalidProviderError(descriptor.provider_id, std::move(problems));
    }
}

}  // namespace pwb::providers
