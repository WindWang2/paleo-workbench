// MapDocumentEditSession — undoable edit history over one MapDocument with
// unified data/style/layout revisions and dirty state (CONV-27).
//
// Python's MapDocument (mapping/layers.py) mutates directly with no history;
// this session freezes those behaviors into reversible commands:
//   * add/remove/reorder keep the exact kernel contracts (active-layer
//     fallforward, recompute_extent, first-wins reorder) and revert restores
//     the captured extent + active layer bit-exactly;
//   * per-layer style ops mirror the Python bump helpers (set_visible /
//     set_opacity clamp / style payload), data ops mirror
//     VectorMapLayer.set_features (extent recompute + data_revision bump);
//   * RevisionKind bookkeeping feeds the unified dirty state: document-level
//     data/style/layout counters bumped on every apply AND undo/redo of a
//     command of that kind (monotonic, never restored — the cache-invalidation
//     contract), mark_saved() latches them, is_dirty() compares.
//
// Error surface: unknown layer ids throw UnknownElementError where Python has
// no equivalent (there is no Python session); ops Python defines as quiet
// (remove_layer → None) keep that contract and create no command.
#pragma once

#include <pwb/mapping_document/edit_command.hpp>
#include <pwb/mapping_document/map_document.hpp>

#include <array>
#include <optional>
#include <string>
#include <vector>

namespace pwb::mapping_document {

// Document-level revision counters (the map-document analog of the
// per-layer data_revision/style_revision pairs plus a layout counter for
// structural/state changes).
struct DocumentRevisions {
    long long data = 0;
    long long style = 0;
    long long layout = 0;
};

struct SavedRevisions {
    long long data = 0;
    long long style = 0;
    long long layout = 0;
};

class MapDocumentEditSession {
public:
    explicit MapDocumentEditSession(MapDocument& document);

    MapDocumentEditSession(const MapDocumentEditSession&) = delete;
    MapDocumentEditSession& operator=(const MapDocumentEditSession&) = delete;
    // Custom moves: the revision observer captures `this` and must be
    // re-installed onto the moved-to object.
    MapDocumentEditSession(MapDocumentEditSession&& other) noexcept;
    MapDocumentEditSession& operator=(MapDocumentEditSession&& other) noexcept;

    // -- queries ----------------------------------------------------------
    bool can_undo() const { return stack_.can_undo(); }
    bool can_redo() const { return stack_.can_redo(); }
    // Total applied-command counter (Python session semantics: every command
    // and every undo/redo bumps it).
    long long revision() const { return stack_.revision(); }
    const DocumentRevisions& revisions() const { return revisions_; }
    // Unified dirty state: any of data/style/layout changed since mark_saved.
    bool is_dirty() const;
    void mark_saved() { saved_ = SavedRevisions{revisions_.data, revisions_.style,
                                                revisions_.layout}; }
    const CommandStack& stack() const { return stack_; }

    // -- layer structure ---------------------------------------------------
    void add_layer(MapLayer layer, std::optional<std::size_t> position = std::nullopt);
    // Missing id → nullopt, no command (Python returns None).
    std::optional<MapLayer> remove_layer(const std::string& layer_id);
    void reorder_layers(const std::vector<std::string>& layer_ids);
    void set_active_layer(const std::string& layer_id);
    void clear_active_layer();

    // -- per-layer data / style (Python bump-helper semantics) --------------
    void set_layer_visible(const std::string& layer_id, bool visible);
    void set_layer_opacity(const std::string& layer_id, double opacity);
    void set_layer_style(const std::string& layer_id, Json style);
    // VectorMapLayer.set_features: payload replace + layer extent recompute
    // (VectorMapLayer.recompute_extent contract, sentinel on no coordinates)
    // + data revision bump. Vector-family layers only.
    void set_layer_features(const std::string& layer_id, Json features);
    void bump_layer_data_revision(const std::string& layer_id);
    void bump_layer_style_revision(const std::string& layer_id);

    // -- document-level -----------------------------------------------------
    void set_title(const std::string& title);
    void set_crs(const std::string& crs);
    void set_extent(const std::array<double, 4>& extent);
    void set_metadata(const std::string& key, Json value);

    // -- history / grouped edit ----------------------------------------------
    bool undo();
    bool redo();
    void clear_history();
    void begin_group(const std::string& label);
    void end_group();
    void rollback_group();
    bool group_open() const { return stack_.group_open(); }

private:
    MapLayer& layer_ref(const std::string& layer_id);
    void bump(RevisionKind kind);
    void install_observer();

    MapDocument* document_;
    CommandStack stack_;
    DocumentRevisions revisions_;
    SavedRevisions saved_;
};

// Port of VectorMapLayer.recompute_extent over the JSON feature payload:
// walk GeoJSON coordinates of every feature's "geometry", degenerate/empty
// → the sentinel (0, 0, 1, 1), degenerate axes padded by
// max(1, |min|, |max|) * 1e-6 guarded by math.isclose (rel_tol 1e-9).
std::array<double, 4> recompute_layer_features_extent(const Json& features);

// True for the layer_type strings whose family carries a features payload
// (the CONV-02 D-05 table, shared with the session's set_layer_features).
bool is_vector_family_layer_type(const std::string& layer_type);

}  // namespace pwb::mapping_document
