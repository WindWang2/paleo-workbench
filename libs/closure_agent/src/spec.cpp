// spec.cpp — ActionSpec behaviour, byte-identical problem strings and JSON
// projections against the frozen Python oracle (agent_oracle.json).
#include <pwb/closure_agent/spec.hpp>

#include <pwb/providers/contracts.hpp>
#include <pwb/providers/schema.hpp>

namespace pwb::closure_agent {

std::string to_string(ActionRisk risk) {
    switch (risk) {
        case ActionRisk::Read: return "read";
        case ActionRisk::Compute: return "compute";
        case ActionRisk::Write: return "write";
        case ActionRisk::Destructive: return "destructive";
    }
    return "read";
}

std::optional<ActionRisk> action_risk_from_string(const std::string& value) {
    if (value == "read") return ActionRisk::Read;
    if (value == "compute") return ActionRisk::Compute;
    if (value == "write") return ActionRisk::Write;
    if (value == "destructive") return ActionRisk::Destructive;
    return std::nullopt;
}

std::string to_string(ActionStatus status) {
    switch (status) {
        case ActionStatus::Success: return "success";
        case ActionStatus::Degraded: return "degraded";
        case ActionStatus::Failed: return "failed";
        case ActionStatus::Cancelled: return "cancelled";
        case ActionStatus::Rejected: return "rejected";
        case ActionStatus::Unavailable: return "unavailable";
    }
    return "failed";
}

bool is_positive_status(ActionStatus status) {
    return status == ActionStatus::Success || status == ActionStatus::Degraded;
}

bool is_known_typed_ref(const std::string& ref) {
    for (const auto& known : pwb::providers::typed_refs()) {
        if (known == ref) return true;
    }
    return false;
}

std::string ActionSpec::domain() const {
    const auto pos = action_id.find('.');
    return pos == std::string::npos ? action_id : action_id.substr(0, pos);
}

Json ActionSpec::effective_resource_profile() const {
    if (!resource_profile.is_null()) return resource_profile;
    Json profile = Json::object();
    profile["estimated_cpu_cores"] = 0.5;
    profile["estimated_ram_bytes"] = 0;
    profile["estimated_vram_bytes"] = 0;
    profile["io_weight"] = 0.5;
    return profile;
}

Json ActionSpec::to_dict() const {
    Json dict = Json::object();
    dict["action_id"] = action_id;
    dict["description"] = description;
    dict["input_schema"] = input_schema;
    dict["output_schema"] = output_schema;
    dict["risk"] = to_string(risk);
    dict["category"] = category;
    dict["resource_profile"] = effective_resource_profile();
    dict["required_context"] = required_context;
    dict["supports_cancel"] = supports_cancel;
    dict["provider_id"] = provider_id ? Json(*provider_id) : Json(nullptr);
    dict["side_effect_notes"] = side_effect_notes;
    dict["version"] = version;
    dict["deterministic"] = deterministic;
    dict["cacheable"] = cacheable;
    dict["idempotent"] = idempotent;
    dict["domain_tags"] = domain_tags;
    dict["input_refs"] = input_refs;
    dict["output_refs"] = output_refs;
    return dict;
}

Json ActionSpec::tool_schema() const {
    std::string derived = description + " [risk: " + to_string(risk);
    if (provider_id) derived += "; via provider " + *provider_id;
    derived += "]";
    // Python: action_id.replace(".", "__").
    std::string mapped;
    mapped.reserve(action_id.size() + 4);
    for (const char ch : action_id) {
        if (ch == '.') {
            mapped += "__";
        } else {
            mapped += ch;
        }
    }
    Json function = Json::object();
    function["name"] = mapped;
    function["description"] = derived;
    // Python: self.input_schema or {default object schema} (empty dict is
    // falsy).
    Json parameters =
        input_schema.is_object() && !input_schema.empty()
            ? input_schema
            : Json(Json::object());
    if (!input_schema.is_object() || input_schema.empty()) {
        parameters["type"] = "object";
        parameters["properties"] = Json::object();
        parameters["additionalProperties"] = false;
    }
    function["parameters"] = parameters;
    Json schema = Json::object();
    schema["type"] = "function";
    schema["function"] = function;
    return schema;
}

namespace {

// Python dict/get semantics: absent key -> Json(nullptr).
const Json& get(const Json& object, const char* key) {
    static const Json null_value = Json(nullptr);
    if (!object.is_object()) return null_value;
    const auto it = object.find(key);
    return it == object.end() ? null_value : *it;
}

bool is_known_type_name(const std::string& name) {
    return name == "object" || name == "array" || name == "string" ||
           name == "integer" || name == "number" || name == "boolean" ||
           name == "null";
}

}  // namespace

std::vector<std::string> validate_schema_shape(const Json& schema,
                                               const std::string& path) {
    std::vector<std::string> problems;
    if (!schema.is_object()) {
        problems.push_back(path + ": must be a dict (JSON schema)");
        return problems;
    }
    const Json& expected = get(schema, "type");
    if (!expected.is_null()) {
        std::vector<std::string> names;
        if (expected.is_array()) {
            for (const auto& entry : expected) names.push_back(entry.get<std::string>());
        } else {
            names.push_back(expected.get<std::string>());
        }
        for (const auto& name : names) {
            if (!is_known_type_name(name)) {
                problems.push_back(path + ": unknown type " +
                                   pwb::providers::python_repr(name));
            }
        }
    }
    const Json& enum_value = get(schema, "enum");
    if (!enum_value.is_null() && !enum_value.is_array()) {
        problems.push_back(path + ": enum must be a list");
    }
    for (const char* bound : {"minimum", "maximum"}) {
        const Json& value = get(schema, bound);
        if (!value.is_null() && !value.is_number()) {
            problems.push_back(path + ": " + bound + " must be numeric");
        }
    }
    for (const char* bound : {"minItems", "maxItems"}) {
        const Json& value = get(schema, bound);
        if (!value.is_null() && !value.is_number_integer()) {
            problems.push_back(path + ": " + bound + " must be an integer");
        }
    }
    const Json& properties = get(schema, "properties");
    if (!properties.is_null()) {
        if (!properties.is_object()) {
            problems.push_back(path + ".properties: must be a dict");
        } else {
            for (auto it = properties.begin(); it != properties.end(); ++it) {
                auto sub = validate_schema_shape(
                    it.value(), path + ".properties." + it.key());
                problems.insert(problems.end(), sub.begin(), sub.end());
            }
        }
    }
    const Json& required = get(schema, "required");
    if (!required.is_null()) {
        bool ok = required.is_array();
        if (ok) {
            for (const auto& entry : required) {
                if (!entry.is_string()) {
                    ok = false;
                    break;
                }
            }
        }
        if (!ok) problems.push_back(path + ".required: must be a list of strings");
    }
    const Json& items = get(schema, "items");
    if (!items.is_null()) {
        if (items.is_object()) {
            auto sub = validate_schema_shape(items, path + ".items");
            problems.insert(problems.end(), sub.begin(), sub.end());
        } else {
            problems.push_back(path + ".items: must be a dict");
        }
    }
    const Json& additional = get(schema, "additionalProperties");
    if (!additional.is_null() && !additional.is_boolean()) {
        problems.push_back(path + ".additionalProperties: must be a boolean");
    }
    return problems;
}

namespace {

// Python re.match(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$", id) — full match.
bool matches_action_id_pattern(const std::string& id) {
    const auto dot = id.find('.');
    if (dot == std::string::npos || id.find('.', dot + 1) != std::string::npos) {
        return false;
    }
    auto part_ok = [](const std::string& part) {
        if (part.empty()) return false;
        if (part[0] < 'a' || part[0] > 'z') return false;
        for (const char ch : part) {
            const bool ok = (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') ||
                            ch == '_';
            if (!ok) return false;
        }
        return true;
    };
    return part_ok(id.substr(0, dot)) && part_ok(id.substr(dot + 1));
}

// Python re.match(r"^[0-9]+(\.[0-9]+){0,3}$", version) — full match:
// one to four dot-separated all-digit groups.
bool matches_version_pattern(const std::string& version) {
    std::size_t i = 0;
    auto digits = [&](std::size_t start) {
        std::size_t j = start;
        while (j < version.size() && version[j] >= '0' && version[j] <= '9') ++j;
        return j;
    };
    i = digits(0);
    if (i == 0) return false;
    int groups = 1;
    while (i < version.size()) {
        if (version[i] != '.') return false;
        const std::size_t next = digits(i + 1);
        if (next == i + 1) return false;
        i = next;
        ++groups;
    }
    return groups >= 1 && groups <= 4;
}

// Python re.match(r"^[a-z0-9][a-z0-9_.-]*$", tag) — full match.
bool matches_tag_pattern(const std::string& tag) {
    if (tag.empty()) return false;
    const auto head_ok = [](char ch) {
        return (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9');
    };
    if (!head_ok(tag[0])) return false;
    for (const char ch : tag) {
        const bool ok = (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') ||
                        ch == '_' || ch == '.' || ch == '-';
        if (!ok) return false;
    }
    return true;
}

}  // namespace

std::vector<std::string> validate_action_spec(const ActionSpec& spec) {
    std::vector<std::string> problems;
    if (!matches_action_id_pattern(spec.action_id)) {
        problems.push_back("action_id " + pwb::providers::python_repr(spec.action_id) +
                           " must be '<domain>.<name>' lowercase dotted");
    }
    bool description_blank = true;
    for (const char ch : spec.description) {
        if (ch != ' ' && ch != '\t' && ch != '\n' && ch != '\r' && ch != '\v' &&
            ch != '\f') {
            description_blank = false;
            break;
        }
    }
    if (description_blank) {
        problems.push_back("description must be non-empty");
    }
    if (!spec.handler && !spec.provider_id) {
        problems.push_back("spec needs a handler or a provider_id to be executable");
    }
    if (!spec.input_schema.is_object()) {
        problems.push_back("input_schema must be a dict (JSON schema)");
    } else {
        const Json& top_type = get(spec.input_schema, "type");
        if (!top_type.is_null() &&
            (!top_type.is_string() || top_type.get<std::string>() != "object")) {
            problems.push_back("input_schema must describe an object at the top level");
        }
        auto shape = validate_schema_shape(spec.input_schema, "input_schema");
        problems.insert(problems.end(), shape.begin(), shape.end());
    }
    if (spec.output_schema.is_object() && !spec.output_schema.empty()) {
        auto shape = validate_schema_shape(spec.output_schema, "output_schema");
        problems.insert(problems.end(), shape.begin(), shape.end());
    }
    if (!spec.version.empty() && !matches_version_pattern(spec.version)) {
        problems.push_back("version " + pwb::providers::python_repr(spec.version) +
                           " must be numeric dotted (e.g. 1.0)");
    }
    if (spec.cacheable && !spec.deterministic) {
        problems.push_back(
            "cacheable requires deterministic (a cache hit replays the execution)");
    }
    if (spec.cacheable && spec.output_refs.empty()) {
        problems.push_back(
            "cacheable requires declared output_refs: a cache hit must "
            "re-materialise from catalog-resolvable outputs");
    }
    for (const auto& tag : spec.domain_tags) {
        if (!matches_tag_pattern(tag)) {
            problems.push_back("domain_tag " + pwb::providers::python_repr(tag) +
                               " must match ^[a-z0-9][a-z0-9_.-]*$");
        }
    }
    for (const auto& [role, refs] :
         {std::pair<const char*, const std::vector<std::string>&>{"input_refs",
                                                                 spec.input_refs},
          {"output_refs", spec.output_refs}}) {
        for (const auto& ref : refs) {
            if (!is_known_typed_ref(ref)) {
                std::string known = "[";
                const auto& typed = pwb::providers::typed_refs();
                for (std::size_t i = 0; i < typed.size(); ++i) {
                    if (i) known += ", ";
                    known += pwb::providers::python_repr(typed[i]);
                }
                known += "]";
                problems.push_back(std::string(role) + " entry " +
                                   pwb::providers::python_repr(ref) +
                                   " is not a known typed ref " + known);
            }
        }
    }
    // resource_profile: null -> the Python default profile (always valid);
    // an explicit profile is checked like the Python dict.get defaults.
    if (!spec.resource_profile.is_null()) {
        if (!spec.resource_profile.is_object()) {
            problems.push_back("resource_profile must be a dict");
        } else {
            const Json& cores = get(spec.resource_profile, "estimated_cpu_cores");
            const double cores_value =
                cores.is_number() ? cores.get<double>() : 0.5;
            if (cores_value <= 0.0) {
                problems.push_back(
                    "resource_profile.estimated_cpu_cores must be > 0");
            }
            const Json& io = get(spec.resource_profile, "io_weight");
            const double io_value = io.is_number() ? io.get<double>() : 0.5;
            if (io_value < 0.0) {
                problems.push_back("resource_profile.io_weight must be >= 0");
            }
            const Json& temp = get(spec.resource_profile, "estimated_temp_bytes");
            if (!temp.is_null() && !temp.is_number()) {
                problems.push_back(
                    "resource_profile.estimated_temp_bytes must be numeric");
            }
        }
    }
    return problems;
}

}  // namespace pwb::closure_agent
