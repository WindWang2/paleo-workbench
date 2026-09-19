#include <pwb/ui_pages_preview/json_tree_spec.hpp>

namespace pwb::ui_pages_preview {

std::string scalar_label(const domain::Json& value) {
    // Python str() on the decoded JSON leaf.
    if (value.is_null()) return "None";
    if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
    if (value.is_string()) return value.get<std::string>();
    if (value.is_number()) {
        // nlohmann shortest round-trip ≈ Python repr(float)/str(int).
        return value.dump();
    }
    // Containers never reach this path in Python (handled before str()).
    return value.dump();
}

namespace {

std::size_t size_of(const domain::Json& v) {
    return v.is_object() || v.is_array() ? v.size() : 0;
}

}  // namespace

JsonNode build_row(const std::string& key, const domain::Json& value,
                   int threshold, int depth) {
    JsonNode node;
    node.key = key;
    if (depth >= JSON_MAX_BUILD_DEPTH) {
        node.kind = JsonNodeKind::depth_cap;
        node.label = "…";
        return node;
    }
    if (value.is_object()) {
        node.label = "{object · " + std::to_string(value.size()) + " keys}";
        if (static_cast<int>(value.size()) > threshold) {
            node.kind = JsonNodeKind::container_lazy;
            node.container = value;
            return node;
        }
        node.kind = JsonNodeKind::object_inline;
        for (auto it = value.begin(); it != value.end(); ++it) {
            node.children.push_back(build_row(it.key(), it.value(), threshold, depth + 1));
        }
        return node;
    }
    if (value.is_array()) {
        if (static_cast<int>(value.size()) > threshold) {
            node.kind = JsonNodeKind::container_lazy;
            node.label = "[" + std::to_string(value.size()) + " items]";
            node.container = value;
            return node;
        }
        node.kind = JsonNodeKind::array_inline;
        node.label = "[list · " + std::to_string(value.size()) + "]";
        for (std::size_t i = 0; i < value.size(); ++i) {
            node.children.push_back(build_row(std::to_string(i), value[i], threshold, depth + 1));
        }
        return node;
    }
    node.kind = JsonNodeKind::scalar;
    node.label = scalar_label(value);
    return node;
}

std::vector<JsonNode> build_tree(const domain::Json& payload, int threshold) {
    std::vector<JsonNode> rows;
    if (payload.is_object()) {
        if (static_cast<int>(payload.size()) > threshold) {
            rows.push_back(build_row("[root]", payload, threshold, 0));
        } else {
            for (auto it = payload.begin(); it != payload.end(); ++it) {
                rows.push_back(build_row(it.key(), it.value(), threshold, 0));
            }
        }
    } else {
        rows.push_back(build_row("[root]", payload, threshold, 0));
    }
    return rows;
}

std::vector<std::pair<std::string, domain::Json>> container_items(
    const domain::Json& container) {
    std::vector<std::pair<std::string, domain::Json>> items;
    if (container.is_object()) {
        items.reserve(container.size());
        for (auto it = container.begin(); it != container.end(); ++it) {
            items.emplace_back(it.key(), it.value());
        }
    } else if (container.is_array()) {
        items.reserve(container.size());
        for (std::size_t i = 0; i < container.size(); ++i) {
            items.emplace_back(std::to_string(i), container[i]);
        }
    }
    return items;
}

std::size_t append_batch(const domain::Json& container, std::size_t offset,
                         int threshold, int depth,
                         std::vector<JsonNode>& out, int batch_size) {
    const auto items = container_items(container);
    const std::size_t end = std::min(offset + static_cast<std::size_t>(batch_size),
                                   items.size());
    for (std::size_t i = offset; i < end; ++i) {
        out.push_back(build_row(items[i].first, items[i].second, threshold, depth + 1));
    }
    return end;
}

std::string sentinel_label(std::size_t total, std::size_t offset) {
    return "… 展开加载下一批（剩余 " + std::to_string(total - offset) + " 项）";
}

JsonNode sentinel_node(const domain::Json& container, std::size_t offset) {
    JsonNode node;
    node.kind = JsonNodeKind::sentinel;
    // Python appends [more, ""]: the sentinel text lives in the KEY column.
    node.key = sentinel_label(container.size(), offset);
    node.label = "";
    node.container = container;
    node.offset = offset;
    // The sentinel carries one placeholder child (key column) so the
    // expand arrow shows.
    JsonNode placeholder;
    placeholder.kind = JsonNodeKind::scalar;
    placeholder.key = "（点击左侧箭头加载）";
    node.children.push_back(std::move(placeholder));
    return node;
}

}  // namespace pwb::ui_pages_preview
