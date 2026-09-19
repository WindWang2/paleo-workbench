#pragma once

// Port of paleo_workbench/ui/workstation/explorer.py's tree-spec layer
// (UI-12): the _TreeNode specification the WorkstationExplorer builds
// from the project, then diffs against the item model by stable key.
//
// The C++ project model is a JSON envelope, not the Python typed entity
// graph — so the spec builder consumes injected ExplorerFacts (the
// authority-side adapter's projection; empty vectors == honest empty
// state, never fabricated rows).
//
// Qt-free.

#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::ui_workstation {

// Search filter debounce (B3): keystrokes only restart the timer; the
// filter applies 200 ms after typing stops.
inline constexpr int kExplorerSearchDebounceMs = 200;
// Per-group row cap: very large directories are carried by search/paging,
// not laid out in the tree (B3).
inline constexpr int kExplorerGroupRowLimit = 5000;

// Stable diff key + payload kinds. `object` is an opaque authority-side
// reference (the host resolves it; the core never dereferences).
struct ExplorerNode {
    std::string key;
    std::string label;
    std::string icon;
    std::string tooltip;
    std::map<std::string, std::string> payload;
    // (hub index, subkey) navigation payload; nullopt = none.
    std::optional<std::pair<int, std::string>> navigation;
    // nullopt = not checkable; otherwise the tri-state check value
    // (Qt::CheckState int — kept as int so the core stays Qt-free).
    std::optional<int> check_state;
    const void* object = nullptr;  // opaque authority reference
    std::vector<ExplorerNode> children;
};

// --- injected authority facts (adapter output) -------------------------

struct ExplorerWellFact {
    std::string id;
    std::string name;
};

struct ExplorerResourceFact {
    std::string id;
    std::string name;
    std::string type;    // well_log|seismic|well_head|… (Python ResourceItem.type)
    std::string path;
    std::string format;
    std::string status;
    const void* object = nullptr;
};

struct ExplorerEntityFact {
    std::string name;
    const void* object = nullptr;
};

struct ExplorerUserLayerFact {
    std::string id;
    std::string name;
    std::string geometry_kind;  // point|line|polygon
    int feature_count = 0;
    bool visible = true;
    const void* object = nullptr;
};

struct ExplorerMapDocumentFact {
    std::string id;
    std::string name;
    int line_features = 0;
    int facies_polygons = 0;
    int label_features = 0;
    int reference_layers = 0;
    const void* object = nullptr;
};

struct ExplorerInterpretationFact {
    std::string id;
    std::string name;
    std::string current_version_id;
    const void* object = nullptr;
};

struct ExplorerExportFact {
    std::string id;
    std::string name;
    std::string output_path;
    const void* object = nullptr;
};

// mapping_workspace membership projection (process results): role label
// is already resolved by the adapter (ROLE_LABELS authority); maturity is
// the artifact_maturity value for the layer.
struct ExplorerMembershipFact {
    std::string layer_id;
    std::string layer_name;
    std::string role_label;
    std::string maturity;
    std::string source_version_id;
    const void* object = nullptr;
};

struct ExplorerFacts {
    bool project_open = false;
    std::string project_name;    // "未命名工程" fallback applied inside
    std::string workarea_name;   // "未命名工区" fallback applied inside
    std::string target_horizon;  // stratigraphy.target_horizon
    const void* project_object = nullptr;
    const void* workarea_object = nullptr;
    std::vector<ExplorerWellFact> wells;
    std::vector<ExplorerResourceFact> resources;
    std::vector<ExplorerEntityFact> geological_entities;
    std::vector<ExplorerUserLayerFact> user_layers;
    std::vector<ExplorerMapDocumentFact> map_documents;
    std::vector<ExplorerInterpretationFact> interpretations;
    std::vector<ExplorerExportFact> export_artifacts;
    std::vector<ExplorerMembershipFact> memberships;
};

// One spec build: roots + the footer text the panel shows (the Python
// builders set footer_label as a side effect — here it is an output).
struct ExplorerSpec {
    std::vector<ExplorerNode> roots;
    std::string footer;
};

// Explorer view modes (ActivityRail mode keys).
const std::map<std::string, std::string>& explorer_mode_titles();
// Unknown modes fall back to "project" (Python parity).
std::string normalize_explorer_mode(const std::string& mode);

// Build the tree spec for `mode` from `facts` (mode is normalized first).
ExplorerSpec build_explorer_spec(const std::string& mode,
                                 const ExplorerFacts& facts);

}  // namespace pwb::ui_workstation
