#pragma once

// UI-02 — tree-change payload parsing, ported from
// paleo_workbench/ui/qgis_stack/tree_sync.py (Qt-free).
//
// Wire contract (bridge flushTreeChange payload):
//   legacy: {"visibility": {doc_id: bool}, "order": [doc_id...],
//            "renames": {doc_id: name}}
//   schema 2 adds: {"schema": 2, "events": [{"type","node_type","node_id",
//            "value"}], "tree": [structured nodes], "tree_revision": int}
//
// `tree` is kept as raw JSON objects (ordered_json) — the consumer diffs
// structured nodes, it does not string-parse. Malformed payloads return
// empty sets (never throw), matching the frozen Python contract.

#include <nlohmann/json.hpp>

#include <cstdint>
#include <map>
#include <string>
#include <vector>

namespace pwb::ui_widgets::core {

// Legacy flat change batch (old semantics, kept for existing consumers).
struct TreeChangeSet {
    std::map<std::string, bool> visibility;
    std::vector<std::string> order;
    std::map<std::string, std::string> renames;

    [[nodiscard]] bool empty() const {
        return visibility.empty() && order.empty() && renames.empty();
    }
};

// V5 typed tree event.
struct TreeEvent {
    std::string type;       // "visibility" | "rename"
    std::string node_type;  // "layer" | "group"
    std::string node_id;
    // bool for "visibility" events, string for "rename" events
    // (Python: value: object — typed by event type).
    bool visibility_value = false;
    std::string rename_value;

    [[nodiscard]] bool is_group() const { return node_type == "group"; }
};

// schema-2 batch: legacy keys + typed events + structure snapshot.
struct TreeChangeBatch {
    TreeChangeSet changes;
    std::vector<TreeEvent> events;
    // Structured snapshot nodes (non-empty only on structure change):
    // [{"type": "group"|"layer", "id": ..., "children": [...]}]
    std::vector<nlohmann::ordered_json> tree;
    // V11 tree revision (bridge 0.7.0a0+); 0 = old bridge, not stale.
    std::int64_t revision = 0;

    [[nodiscard]] bool empty() const {
        return changes.empty() && events.empty() && tree.empty();
    }
    [[nodiscard]] bool has_structure_change() const { return !tree.empty(); }

    [[nodiscard]] std::map<std::string, bool> group_visibility() const;
    [[nodiscard]] std::map<std::string, std::string> group_renames() const;
};

// Legacy parse (unchanged behavior; missing keys / bad JSON -> empty set).
[[nodiscard]] TreeChangeSet parse_tree_change(const std::string& payload);

// schema-2 parse: legacy keys + typed events + structure snapshot.
[[nodiscard]] TreeChangeBatch parse_tree_events(const std::string& payload);

// Python-coercion helpers shared by both parsers (exposed for tests):
//   py_truthy — Python bool() over JSON (null->F, 0->F, ""->F, []/{} ->F)
//   py_str    — Python str() over JSON scalars ("True"/"False"/"None")
//   py_int    — Python int() over JSON (bool->0/1, float trunc, str parse)
[[nodiscard]] bool py_truthy(const nlohmann::json& value);
[[nodiscard]] std::string py_str(const nlohmann::json& value);
[[nodiscard]] std::int64_t py_int(const nlohmann::json& value);

}  // namespace pwb::ui_widgets::core
