#pragma once

// Port of paleo_workbench/ui/pages/json_tree_preview_widget.py semantics
// (UI-07) — Qt-free part: the node spec the QTreeView model materializes.
//
// Lazy materialization contract (#531): containers larger than
// array_collapse_threshold never build children eagerly — they render a
// single collapsed row carrying the payload, and expansion materializes
// bounded batches of _EXPAND_BATCH rows behind a "load more" sentinel.

#include <cstddef>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::ui_pages_preview {

inline constexpr int JSON_EXPAND_BATCH = 2000;   // _EXPAND_BATCH
inline constexpr int JSON_MAX_BUILD_DEPTH = 64;  // _MAX_BUILD_DEPTH

enum class JsonNodeKind {
    scalar,           // leaf: label = str(value)
    object_inline,    // dict <= threshold: children materialized now
    array_inline,     // list <= threshold: children materialized now
    container_lazy,   // > threshold: label only; children arrive via batches
    depth_cap,        // depth >= 64: "…" placeholder
    sentinel,         // "… 展开加载下一批（剩余 N 项）" load-more row
};

struct JsonNode {
    std::string key;
    JsonNodeKind kind = JsonNodeKind::scalar;
    std::string label;
    domain::Json container = domain::Json(nullptr);  // lazy/sentinel payload
    std::size_t offset = 0;                          // sentinel resume offset
    std::vector<JsonNode> children;                  // inline kinds only
};

// load_payload parity: dict && len > threshold → a single "[root]" lazy row;
// otherwise one row per top-level key (non-dict → single "[root]" row).
std::vector<JsonNode> build_tree(const domain::Json& payload,
                                 int array_collapse_threshold);

// _build_row parity.
JsonNode build_row(const std::string& key, const domain::Json& value,
                   int array_collapse_threshold, int depth = 0);

// _container_items: dict → (key, value) pairs; list → (str(i), value) pairs.
std::vector<std::pair<std::string, domain::Json>> container_items(
    const domain::Json& container);

// _append_batch: materializes entries[offset : offset+batch] into `out` and
// returns the next offset.
std::size_t append_batch(const domain::Json& container, std::size_t offset,
                         int array_collapse_threshold, int depth,
                         std::vector<JsonNode>& out,
                         int batch_size = JSON_EXPAND_BATCH);

// Sentinel row for resuming a lazy container at `offset`.
JsonNode sentinel_node(const domain::Json& container, std::size_t offset);

// "… 展开加载下一批（剩余 N 项）" — the sentinel's visible text.
std::string sentinel_label(std::size_t total, std::size_t offset);

// Scalar str() parity: str(True)="True", str(None)="None", numbers shortest
// repr, strings raw (no quotes).
std::string scalar_label(const domain::Json& value);

}  // namespace pwb::ui_pages_preview
