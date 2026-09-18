// CONV-06: validation.cpp — faithful port of
// paleo_workbench/workflow/dag/validation.py plus the validate_parameters
// subset it depends on (paleo_workbench/providers/execution.py).
#include <pwb/workflow_spec/validation.hpp>

#include <algorithm>
#include <set>
#include <string_view>

#include "python_repr.hpp"

namespace pwb::workflow_spec {

namespace {

using detail::py_repr;
using detail::py_str_number;
using detail::py_type_name;

std::string quoted(const std::string& text) { return "'" + text + "'"; }

std::string py_list_of_quoted(const std::vector<std::string>& items) {
    std::string out = "[";
    for (std::size_t i = 0; i < items.size(); ++i) {
        if (i != 0) out += ", ";
        out += quoted(items[i]);
    }
    out += "]";
    return out;
}

// Python walk() dict-key-set classification for binding objects.
std::set<std::string> key_set(const domain::Json& object) {
    std::set<std::string> keys;
    for (const auto& [key, value] : object.items()) {
        keys.insert(key);
    }
    return keys;
}

// validation._condition_nodes
void collect_condition_nodes(const NodeCondition& condition,
                             std::set<std::string>& refs) {
    // Python `if condition.node:` — empty strings are not references.
    if (condition.node.has_value() && !condition.node->empty()) {
        refs.insert(*condition.node);
    }
    for (const auto& sub : condition.conditions) {
        collect_condition_nodes(sub, refs);
    }
    if (condition.has_condition()) {
        collect_condition_nodes(condition.inner_condition(), refs);
    }
}

// validation._binding_problems (walk closure)
void collect_binding_problems(const domain::Json& value,
                              const std::map<std::string, const NodeSpec*>& seen,
                              const NodeSpec& node,
                              const std::set<std::string>& slot_names,
                              std::vector<std::string>& problems) {
    if (!value.is_object()) {
        if (value.is_array()) {
            for (const auto& item : value) {
                collect_binding_problems(item, seen, node, slot_names, problems);
            }
        }
        return;
    }
    const auto keys = key_set(value);
    if (keys == std::set<std::string>{"$slot"}) {
        const domain::Json& name = value.at("$slot");
        const bool ok = name.is_string() &&
                        slot_names.count(name.get<std::string>()) > 0;
        if (!ok) {
            problems.push_back("binding $slot " + py_repr(name) +
                               " is not a declared slot");
        }
        return;
    }
    if (keys == std::set<std::string>{"$ref"} ||
        keys == std::set<std::string>{"$ref", "key"}) {
        const domain::Json& ref = value.at("$ref");
        const std::string ref_text =
            ref.is_string() ? ref.get<std::string>() : std::string();
        const bool known = ref.is_string() && seen.count(ref_text) > 0;
        if (!known) {
            problems.push_back("binding $ref " + py_repr(ref) +
                               " is not a node in this workflow");
            return;
        }
        const bool declared =
            std::find(node.depends_on.begin(), node.depends_on.end(),
                      ref_text) != node.depends_on.end();
        if (!declared) {
            problems.push_back("binding $ref " + py_repr(ref) +
                               " must be listed in depends_on "
                               "(data dependencies are explicit)");
            return;
        }
        if (value.contains("key") && !value.at("key").is_string()) {
            problems.push_back("$ref key must be a string");
        }
        return;
    }
    if (keys == std::set<std::string>{"$context"}) {
        const domain::Json& key = value.at("$context");
        const bool ok =
            key.is_string() &&
            context_binding_whitelist().count(key.get<std::string>()) > 0;
        if (!ok) {
            problems.push_back(
                "binding $context " + py_repr(key) + " is not whitelisted " +
                py_list_of_quoted({context_binding_whitelist().begin(),
                                   context_binding_whitelist().end()}));
        }
        return;
    }
    if (keys.count("$ref") > 0 || keys.count("$slot") > 0 ||
        keys.count("$context") > 0) {
        problems.push_back(
            "binding objects must be exactly one of "
            "{\"$slot\": name} / {\"$ref\": node} / {\"$context\": key}");
        return;
    }
    for (const auto& [key, item] : value.items()) {
        (void)key;
        collect_binding_problems(item, seen, node, slot_names, problems);
    }
}

}  // namespace

bool matches_node_id_pattern(const std::string& text) {
    // ^[a-z][a-z0-9_]*$ — Python `$` also matches before one trailing
    // newline; replicate by dropping it for the match.
    std::string_view view(text);
    if (!view.empty() && view.back() == '\n') view.remove_suffix(1);
    if (view.empty() || view[0] < 'a' || view[0] > 'z') {
        return false;
    }
    for (const char ch : view) {
        const bool ok = (ch >= 'a' && ch <= 'z') ||
                        (ch >= '0' && ch <= '9') || ch == '_';
        if (!ok) return false;
    }
    return true;
}

bool matches_workflow_id_pattern(const std::string& text) {
    // ^[a-z][a-z0-9_.-]{1,63}$ — total length 2..64; Python `$` matches
    // before one trailing newline, so the newline is excluded first.
    std::string_view view(text);
    if (!view.empty() && view.back() == '\n') view.remove_suffix(1);
    if (view.size() < 2 || view.size() > 64) {
        return false;
    }
    if (view[0] < 'a' || view[0] > 'z') {
        return false;
    }
    for (std::size_t i = 1; i < view.size(); ++i) {
        const char ch = view[i];
        const bool ok = (ch >= 'a' && ch <= 'z') ||
                        (ch >= '0' && ch <= '9') || ch == '_' ||
                        ch == '.' || ch == '-';
        if (!ok) return false;
    }
    return true;
}

const std::set<std::string>& context_binding_whitelist() {
    static const std::set<std::string> whitelist{
        "workspace_id",
        "project_path",
        "active_survey_id",
        "active_well_id",
        "current_map_id",
        "selection.active_well_id",
        "selection.selected_well_ids",
        "selection.seismic_cursor",
        "selection.depth_range",
    };
    return whitelist;
}

// -------------------------------------------------- validate_workflow_spec --

std::vector<std::string> validate_workflow_spec(const WorkflowSpec& spec,
                                                const ActionCatalog& catalog) {
    std::vector<std::string> problems;
    if (!matches_workflow_id_pattern(spec.workflow_id)) {
        problems.push_back("workflow_id " + quoted(spec.workflow_id) +
                           " must match ^[a-z][a-z0-9_.-]{1,63}$");
    }
    if (spec.nodes.empty()) {
        problems.push_back("workflow needs at least one node");
    }
    if (spec.max_concurrency < 1) {
        problems.push_back("max_concurrency must be >= 1");
    }

    std::map<std::string, const NodeSpec*> seen;
    for (const auto& node : spec.nodes) {
        if (!matches_node_id_pattern(node.node_id)) {
            problems.push_back("node_id " + quoted(node.node_id) +
                               " must match ^[a-z][a-z0-9_]*$");
        }
        if (seen.count(node.node_id) > 0) {
            problems.push_back("duplicate node id " + quoted(node.node_id));
            continue;
        }
        seen[node.node_id] = &node;

        const auto action = catalog.find(node.action_id);
        if (action == catalog.end()) {
            problems.push_back("node " + quoted(node.node_id) +
                               ": unknown action " + quoted(node.action_id));
            continue;
        }
        if (node.action_id.rfind("workflow.", 0) == 0) {
            problems.push_back("node " + quoted(node.node_id) +
                               ": workflow.* actions cannot be nodes of a "
                               "workflow (meta-workflow recursion is not "
                               "supported)");
            continue;
        }
        if (action->second == "destructive") {
            problems.push_back("node " + quoted(node.node_id) +
                               ": DESTRUCTIVE actions cannot appear in "
                               "workflows");
        }
        if (node.retry.max_attempts < 1) {
            problems.push_back("node " + quoted(node.node_id) +
                               ": retry.max_attempts must be >= 1");
        }
        if (node.condition.has_value()) {
            for (const auto& problem : validate_condition_tree(*node.condition)) {
                problems.push_back("node " + quoted(node.node_id) + ": " +
                                   problem);
            }
        }
    }

    std::set<std::string> slot_names;
    for (const auto& slot : spec.slots) {
        slot_names.insert(slot.name);
    }
    for (const auto& slot : spec.slots) {
        if (!matches_node_id_pattern(slot.name)) {
            problems.push_back("slot name " + quoted(slot.name) +
                               " must match ^[a-z][a-z0-9_]*$");
        }
    }
    if (slot_names.size() != spec.slots.size()) {
        problems.push_back("duplicate slot names");
    }

    for (const auto& node : spec.nodes) {
        for (const auto& dep : node.depends_on) {
            if (seen.count(dep) == 0) {
                problems.push_back("node " + quoted(node.node_id) +
                                   ": dependency " + quoted(dep) +
                                   " does not exist");
            } else if (dep == node.node_id) {
                problems.push_back("node " + quoted(node.node_id) +
                                   ": self-dependency");
            }
        }
        if (node.condition.has_value()) {
            std::set<std::string> refs;
            collect_condition_nodes(*node.condition, refs);
            for (const auto& ref : refs) {
                if (seen.count(ref) == 0) {
                    problems.push_back("node " + quoted(node.node_id) +
                                       ": condition references unknown node " +
                                       quoted(ref));
                }
            }
        }
        std::vector<std::string> binding;
        collect_binding_problems(node.parameters, seen, node, slot_names,
                                 binding);
        for (auto& problem : binding) {
            problems.push_back("node " + quoted(node.node_id) + ": " + problem);
        }
    }

    // _cycle_problems: Kahn; every leftover (indegree > 0) node lands in the
    // message — including nodes downstream of a cycle, and the empty list is
    // emitted whenever node ENTRIES outnumber deduplicated ids (duplicate-id
    // parity, findings §_cycle_problems).
    std::map<std::string, int> indegree;
    std::map<std::string, std::vector<std::string>> consumers;
    for (const auto& node : spec.nodes) {
        indegree[node.node_id] = 0;
        consumers[node.node_id] = {};
    }
    for (const auto& node : spec.nodes) {
        for (const auto& dep : node.depends_on) {
            if (indegree.count(dep) > 0) {
                indegree[node.node_id] += 1;
                consumers[dep].push_back(node.node_id);
            }
        }
    }
    std::vector<std::string> queue;
    for (const auto& [id, degree] : indegree) {
        if (degree == 0) queue.push_back(id);  // map iteration = sorted
    }
    std::size_t visited = 0;
    while (!queue.empty()) {
        const std::string current = queue.back();  // Python queue.pop()
        queue.pop_back();
        ++visited;
        for (const auto& consumer : consumers[current]) {
            if (--indegree[consumer] == 0) {
                queue.push_back(consumer);
            }
        }
    }
    if (visited != spec.nodes.size()) {
        std::vector<std::string> cyclic;
        for (const auto& [id, degree] : indegree) {
            if (degree > 0) cyclic.push_back(id);
        }
        problems.push_back("dependency cycle among nodes " +
                           py_list_of_quoted(cyclic));
    }
    return problems;
}

// ------------------------------------------------------------ resolve_value --

namespace {

std::optional<domain::Json> context_value(const BindEnv& env,
                                          const std::string& key) {
    // Python _context_value: missing/None -> BindingError.
    const auto it = env.context_values.find(key);
    if (it == env.context_values.end() || it->second.is_null()) {
        return std::nullopt;
    }
    return it->second;
}

}  // namespace

domain::Json resolve_value(const domain::Json& value, const BindEnv& env) {
    if (value.is_object()) {
        const auto keys = key_set(value);
        if (keys == std::set<std::string>{"$slot"}) {
            const auto& name = value.at("$slot");
            if (!name.is_string() || !env.slot_values.contains(name)) {
                throw BindingError("slot " + py_repr(name) +
                                   " has no bound value");
            }
            return env.slot_values.at(name.get<std::string>());
        }
        if (keys == std::set<std::string>{"$ref"} ||
            keys == std::set<std::string>{"$ref", "key"}) {
            const auto& node_ref = value.at("$ref");
            const auto results_it =
                node_ref.is_string()
                    ? env.results.find(node_ref.get<std::string>())
                    : env.results.end();
            if (results_it == env.results.end()) {
                throw BindingError("reference " + py_repr(node_ref) +
                                   " has no resolved output yet");
            }
            if (value.contains("key")) {
                const auto& key = value.at("key");
                const domain::Json& outputs = results_it->second;
                // A non-string key can never be an object member; Python
                // reports it through the same BindingError message.
                if (!outputs.is_object() || !key.is_string() ||
                    !outputs.contains(key.get<std::string>())) {
                    throw BindingError("reference " + py_repr(node_ref) +
                                       " produced no output key " +
                                       py_repr(key));
                }
                return outputs.at(key.get<std::string>());
            }
            return results_it->second;
        }
        if (keys == std::set<std::string>{"$context"}) {
            auto resolved = context_value(env, value.at("$context").is_string()
                                                       ? value.at("$context").get<std::string>()
                                                       : std::string());
            if (!resolved.has_value()) {
                throw BindingError("context binding " +
                                   py_repr(value.at("$context")) +
                                   " is not available in this session");
            }
            return *resolved;
        }
        domain::Json resolved = domain::Json::object();
        for (const auto& [key, item] : value.items()) {
            resolved[key] = resolve_value(item, env);
        }
        return resolved;
    }
    if (value.is_array()) {
        domain::Json resolved = domain::Json::array();
        for (const auto& item : value) {
            resolved.push_back(resolve_value(item, env));
        }
        return resolved;
    }
    return value;
}

domain::Json bind_parameters(const NodeSpec& node, const BindEnv& env) {
    return resolve_value(node.parameters, env);
}

// ------------------------------------------------------ validate_parameters --

namespace {

bool type_matches(const std::string& expected, const domain::Json& value) {
    if (expected == "object") return value.is_object();
    if (expected == "array") return value.is_array();
    if (expected == "string") return value.is_string();
    if (expected == "integer") {
        return value.is_number_integer() || value.is_number_unsigned();
    }
    if (expected == "number") return value.is_number();
    if (expected == "boolean") return value.is_boolean();
    if (expected == "null") return value.is_null();
    return false;
}

bool is_known_type_name(const std::string& name) {
    return name == "object" || name == "array" || name == "string" ||
           name == "integer" || name == "number" || name == "boolean" ||
           name == "null";
}

bool enum_contains(const domain::Json& enum_list, const domain::Json& value) {
    // Python `value in enum` uses ==; nlohmann compares numeric 1 == 1.0
    // the same way. bool is an int subclass in Python, so True == 1 holds
    // there and is replicated explicitly.
    for (const auto& member : enum_list) {
        if (member == value) return true;
        if (member.is_boolean() && value.is_number_integer()) {
            if (static_cast<int>(member.get<bool>()) ==
                value.get<long long>()) {
                return true;
            }
        }
        if (value.is_boolean() && member.is_number_integer()) {
            if (static_cast<int>(value.get<bool>()) ==
                member.get<long long>()) {
                return true;
            }
        }
    }
    return false;
}

void check_value(const domain::Json& value, const domain::Json& sub,
                 const std::string& path, std::vector<std::string>& problems);

void check_object(const domain::Json& value, const domain::Json& sub,
                  const std::string& path, std::vector<std::string>& problems) {
    const auto properties_it = sub.find("properties");
    const domain::Json properties =
        properties_it != sub.end() && properties_it->is_object()
            ? *properties_it
            : domain::Json::object();
    if (auto required = sub.find("required"); required != sub.end() &&
                                               required->is_array()) {
        for (const auto& key : *required) {
            // str(key) renders like Python's f-string for odd members.
            const std::string key_text = key.is_string()
                                             ? key.get<std::string>()
                                             : detail::py_str_scalar(key);
            if (!value.is_object() || !value.contains(key_text)) {
                problems.push_back(path + "." + key_text + ": required");
            }
        }
    }
    for (const auto& [key, item] : value.items()) {
        const auto child = properties.find(key);
        // Python: properties.get(key) is None for BOTH missing keys and
        // explicit null sub-schemas — both fall to the additionalProperties
        // check.
        if (child == properties.end() || child->is_null()) {
            if (sub.contains("additionalProperties") &&
                sub.at("additionalProperties").is_boolean() &&
                !sub.at("additionalProperties").get<bool>()) {
                problems.push_back(path + "." + key +
                                   ": not declared and additionalProperties "
                                   "false");
            }
            continue;
        }
        check_value(item, *child, path + "." + key, problems);
    }
}

void check_value(const domain::Json& value, const domain::Json& sub,
                 const std::string& path, std::vector<std::string>& problems) {
    const auto type_field = sub.find("type");
    if (type_field != sub.end() && !type_field->is_null()) {
        if (type_field->is_array()) {
            // JSON Schema union (B3): valid when ANY known member matches.
            // Members are str()-filtered; a union whose members are all
            // unknown type names is a schema problem, not a silent pass.
            std::vector<std::string> members;
            for (const auto& member : *type_field) {
                std::string name = detail::py_str_scalar(member);
                if (!name.empty()) members.push_back(std::move(name));
            }
            std::vector<std::string> known;
            for (const auto& member : members) {
                if (is_known_type_name(member)) known.push_back(member);
            }
            bool matches = false;
            for (const auto& member : known) {
                if (type_matches(member, value)) {
                    matches = true;
                    break;
                }
            }
            if (!known.empty() && matches) {
                // pass
            } else {
                const std::string detail =
                    known.empty() ? " (no known JSON type in union)" : "";
                problems.push_back(path + ": expected one of " +
                                   py_repr(*type_field) + detail + ", got " +
                                   py_type_name(value));
                return;
            }
        } else {
            // str(expected) — scalar type names stringify like Python.
            const std::string expected = type_field->is_string()
                                             ? type_field->get<std::string>()
                                             : detail::py_str_scalar(*type_field);
            if (!is_known_type_name(expected)) {
                // B3: an unknown type is reported, not trusted; Python
                // interpolates the raw value with !r.
                problems.push_back(path + ": unknown type " +
                                   py_repr(*type_field));
                return;
            }
            if (!type_matches(expected, value)) {
                // Python isinstance(bool, int) is True, so a boolean against
                // integer/number passes isinstance and is reported by the
                // dedicated message instead.
                if ((expected == "integer" || expected == "number") &&
                    value.is_boolean()) {
                    problems.push_back(path + ": expected " + expected +
                                       ", got boolean");
                } else {
                    problems.push_back(path + ": expected " + expected +
                                       ", got " + py_type_name(value));
                }
                return;
            }
        }
    }
    if (auto enum_field = sub.find("enum");
        enum_field != sub.end() && enum_field->is_array()) {
        if (!enum_contains(*enum_field, value)) {
            problems.push_back(path + ": " + py_repr(value) +
                               " not in enum " + py_repr(*enum_field));
        }
    }
    if (value.is_number() && !value.is_boolean()) {
        // Python crashes with TypeError on a non-numeric bound; fail closed
        // the same way instead of silently skipping the check.
        const auto check_bound = [&](const char* name, bool less) {
            const auto bound = sub.find(name);
            if (bound == sub.end()) return;
            if (!bound->is_number()) {
                throw ModelError(std::string(name) + ": expected a number");
            }
            const bool violated = less ? value.get<double>() <
                                             bound->get<double>()
                                       : value.get<double>() >
                                             bound->get<double>();
            if (violated) {
                problems.push_back(path + ": " + py_str_number(value) +
                                   (less ? " < minimum " : " > maximum ") +
                                   py_str_number(*bound));
            }
        };
        check_bound("minimum", true);
        check_bound("maximum", false);
    }
    if (value.is_array()) {
        if (auto min_items = sub.find("minItems");
            min_items != sub.end() && min_items->is_number()) {
            // Python compares against any number and str()s it in the message.
            if (static_cast<double>(value.size()) <
                min_items->get<double>()) {
                problems.push_back(path + ": " +
                                   std::to_string(value.size()) +
                                   " items < minItems " +
                                   py_str_number(*min_items));
            }
        }
        if (auto max_items = sub.find("maxItems");
            max_items != sub.end() && max_items->is_number()) {
            if (static_cast<double>(value.size()) >
                max_items->get<double>()) {
                problems.push_back(path + ": " +
                                   std::to_string(value.size()) +
                                   " items > maxItems " +
                                   py_str_number(*max_items));
            }
        }
        if (auto items = sub.find("items"); items != sub.end() &&
                                             items->is_object()) {
            for (std::size_t i = 0; i < value.size(); ++i) {
                check_value(value[i], *items,
                            path + "[" + std::to_string(i) + "]", problems);
            }
        }
    }
    if (value.is_object()) {
        check_object(value, sub, path, problems);
    }
}

}  // namespace

std::vector<std::string> validate_parameters(const domain::Json& schema,
                                             const domain::Json& parameters,
                                             const std::string& label) {
    std::vector<std::string> problems;
    // schema.get("type", "object") == "object" — a union type field is never
    // equal to the string "object", so the top-level object check is skipped.
    const auto type_field = schema.find("type");
    const bool top_expects_object =
        type_field == schema.end()
            ? true
            : type_field->is_string() &&
                  type_field->get<std::string>() == "object";
    if (top_expects_object && !parameters.is_object()) {
        problems.push_back(label + ": expected object");
        return problems;
    }
    check_value(parameters, schema, label, problems);
    return problems;
}

// ------------------------------------------------------ slot_schema_problems --

std::vector<std::string> slot_schema_problems(const WorkflowSpec& spec,
                                              const domain::Json& slot_values) {
    std::vector<std::string> problems;
    std::set<std::string> known;
    for (const auto& slot : spec.slots) {
        known.insert(slot.name);
    }
    for (const auto& [name, unused] : slot_values.items()) {
        (void)unused;
        if (known.count(name) == 0) {
            std::vector<std::string> declared(known.begin(), known.end());
            problems.push_back("unknown slot " + quoted(name) +
                               " (declared: " + py_list_of_quoted(declared) +
                               ")");
        }
    }
    for (const auto& slot : spec.slots) {
        if (slot_values.contains(slot.name)) {
            for (auto& problem : validate_parameters(
                     slot.schema, slot_values.at(slot.name),
                     "slot " + slot.name)) {
                problems.push_back(std::move(problem));
            }
        } else if (slot.required && slot.default_value.is_null()) {
            problems.push_back("required slot " + quoted(slot.name) +
                               " has no value");
        }
    }
    return problems;
}

domain::Json materialize_slot_defaults(const WorkflowSpec& spec,
                                       const domain::Json& slot_values) {
    domain::Json values = slot_values;
    for (const auto& slot : spec.slots) {
        if (!values.contains(slot.name) && !slot.default_value.is_null()) {
            values[slot.name] = slot.default_value;
        }
    }
    return values;
}

}  // namespace pwb::workflow_spec
