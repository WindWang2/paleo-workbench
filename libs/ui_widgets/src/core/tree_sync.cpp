#include "pwb/ui_widgets/core/tree_sync.hpp"

#include <cstdlib>

namespace pwb::ui_widgets::core {

bool py_truthy(const nlohmann::json& value) {
    switch (value.type()) {
        case nlohmann::json::value_t::null:
            return false;
        case nlohmann::json::value_t::boolean:
            return value.get<bool>();
        case nlohmann::json::value_t::number_integer:
        case nlohmann::json::value_t::number_unsigned:
            return value.get<std::int64_t>() != 0;
        case nlohmann::json::value_t::number_float:
            return value.get<double>() != 0.0;
        case nlohmann::json::value_t::string:
            return !value.get_ref<const std::string&>().empty();
        case nlohmann::json::value_t::array:
        case nlohmann::json::value_t::object:
        case nlohmann::json::value_t::binary:
        case nlohmann::json::value_t::discarded:
            return !value.empty();
    }
    return false;
}

std::string py_str(const nlohmann::json& value) {
    switch (value.type()) {
        case nlohmann::json::value_t::null:
            return "None";
        case nlohmann::json::value_t::boolean:
            return value.get<bool>() ? "True" : "False";
        case nlohmann::json::value_t::string:
            return value.get<std::string>();
        case nlohmann::json::value_t::number_integer:
        case nlohmann::json::value_t::number_unsigned:
        case nlohmann::json::value_t::number_float:
            // repr-shortest == Python str() for ints/floats (nlohmann dump).
            return value.dump();
        case nlohmann::json::value_t::array:
        case nlohmann::json::value_t::object:
        case nlohmann::json::value_t::binary:
        case nlohmann::json::value_t::discarded:
            // Python str(container) uses repr formatting — unreachable on the
            // wire (ids are scalars); JSON dump is the honest approximation.
            return value.dump();
    }
    return {};
}

std::int64_t py_int(const nlohmann::json& value) {
    switch (value.type()) {
        case nlohmann::json::value_t::boolean:
            return value.get<bool>() ? 1 : 0;
        case nlohmann::json::value_t::number_integer:
        case nlohmann::json::value_t::number_unsigned:
            return value.get<std::int64_t>();
        case nlohmann::json::value_t::number_float:
            return static_cast<std::int64_t>(value.get<double>());
        case nlohmann::json::value_t::string: {
            const std::string& s = value.get_ref<const std::string&>();
            char* end = nullptr;
            const long long parsed = std::strtoll(s.c_str(), &end, 10);
            if (end == s.c_str() || *end != '\0') return 0;  // int("5.5") -> ValueError
            return parsed;
        }
        default:
            return 0;
    }
}

namespace {

nlohmann::ordered_json parse_payload(const std::string& payload, bool* ok) {
    *ok = false;
    if (payload.empty()) return nlohmann::ordered_json::object();
    nlohmann::ordered_json data =
        nlohmann::ordered_json::parse(payload, nullptr, false);
    if (data.is_discarded() || !data.is_object()) {
        return nlohmann::ordered_json::object();
    }
    *ok = true;
    return data;
}

TreeChangeSet change_set_from(const nlohmann::ordered_json& data) {
    TreeChangeSet out;
    const auto visibility = data.value("visibility", nlohmann::ordered_json{});
    if (visibility.is_object()) {
        for (auto it = visibility.begin(); it != visibility.end(); ++it) {
            out.visibility[it.key()] = py_truthy(it.value());
        }
    }
    const auto order = data.value("order", nlohmann::ordered_json{});
    if (order.is_array()) {
        for (const auto& item : order) out.order.push_back(py_str(item));
    }
    const auto renames = data.value("renames", nlohmann::ordered_json{});
    if (renames.is_object()) {
        for (auto it = renames.begin(); it != renames.end(); ++it) {
            out.renames[it.key()] = py_str(it.value());
        }
    }
    return out;
}

}  // namespace

std::map<std::string, bool> TreeChangeBatch::group_visibility() const {
    std::map<std::string, bool> out;
    for (const TreeEvent& event : events) {
        if (event.type == "visibility" && event.is_group()) {
            out[event.node_id] = event.visibility_value;
        }
    }
    return out;
}

std::map<std::string, std::string> TreeChangeBatch::group_renames() const {
    std::map<std::string, std::string> out;
    for (const TreeEvent& event : events) {
        if (event.type == "rename" && event.is_group()) {
            out[event.node_id] = event.rename_value;
        }
    }
    return out;
}

TreeChangeSet parse_tree_change(const std::string& payload) {
    bool ok = false;
    const nlohmann::ordered_json data = parse_payload(payload, &ok);
    if (!ok) return TreeChangeSet{};
    return change_set_from(data);
}

TreeChangeBatch parse_tree_events(const std::string& payload) {
    bool ok = false;
    const nlohmann::ordered_json data = parse_payload(payload, &ok);
    TreeChangeBatch batch;
    if (!ok) return batch;
    batch.changes = change_set_from(data);

    // Python `str(raw.get(k) or default)` — falsy collapses to default first.
    auto str_or = [](const nlohmann::ordered_json& obj, const char* key,
                     const char* fallback) -> std::string {
        const auto value = obj.value(key, nlohmann::ordered_json{});
        return py_truthy(value) ? py_str(value) : fallback;
    };

    const auto events = data.value("events", nlohmann::ordered_json{});
    if (events.is_array()) {
        for (const auto& raw : events) {
            if (!raw.is_object()) continue;
            const std::string event_type = str_or(raw, "type", "");
            const std::string node_type = str_or(raw, "node_type", "layer");
            const std::string node_id = str_or(raw, "node_id", "");
            if ((event_type != "visibility" && event_type != "rename") ||
                node_id.empty()) {
                continue;
            }
            TreeEvent event;
            event.type = event_type;
            event.node_type = node_type;
            event.node_id = node_id;
            const nlohmann::ordered_json value =
                raw.value("value", nlohmann::ordered_json{});
            if (event_type == "visibility") {
                event.visibility_value = py_truthy(value);
            } else {
                event.rename_value = py_str(value);
            }
            batch.events.push_back(std::move(event));
        }
    }
    const auto tree = data.value("tree", nlohmann::ordered_json{});
    if (tree.is_array()) {
        for (const auto& node : tree) {
            if (node.is_object()) batch.tree.push_back(node);
        }
    }
    // `data.get("tree_revision") or 0` then int() — falsy -> 0, bad -> 0.
    const auto revision = data.value("tree_revision", nlohmann::ordered_json{});
    batch.revision = py_truthy(revision) ? py_int(revision) : 0;
    return batch;
}

}  // namespace pwb::ui_widgets::core
