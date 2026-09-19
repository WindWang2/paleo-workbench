#pragma once

// Port of paleo_workbench/mapping/vector_layer.py + edit_delta.py (UI-13).
//
// VectorLayer/VectorFeature/VectorEditSession is THE working-copy data
// authority of the composite edit stack: every write flows through
// VectorEditSession commands (QGIS edit-buffer semantics — undo/redo,
// compound commands, commit/rollback). EditDelta is a derived audit
// stream over the command flow, never a second authority.
//
// GeoJSON geometry + attribute dicts travel as pwb::domain::Json.
// Qt-free.

#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_data_core/map_edit_geometry.hpp>

namespace pwb::ui_composite {

using pwb::domain::Json;
using pwb::ui_data_core::MapPoint;

// DELTA_JOURNAL_LIMIT / VectorEditSession.JOURNAL_LIMIT parity.
inline constexpr size_t kDeltaJournalLimit = 1024;
inline constexpr size_t kSessionJournalLimit = 1024;
inline constexpr size_t kCommitJournalLimit = 1024;

// ---------------------------------------------------------------------------
// VectorFeature
// ---------------------------------------------------------------------------

// _validate_geometry parity: kind must be a GeoJSON geometry type and
// every leaf coordinate a finite [x, y] pair; throws std::invalid_argument
// (Python ValueError parity).
Json validate_geometry(const Json& geometry);

struct VectorFeature {
    std::string feature_id;
    Json geometry;
    Json attributes = Json::object();

    VectorFeature() = default;
    VectorFeature(std::string feature_id, Json geometry,
                  Json attributes = Json::object());

    // {"id": fid, "geometry": {...}, "properties": {...}}
    Json as_record() const;
};

// ---------------------------------------------------------------------------
// EditCommand
// ---------------------------------------------------------------------------

// EditCommand parity: a deterministic before/after working-copy patch.
// Keys are feature ids; nullopt marks "feature absent on this side".
struct EditCommand {
    std::string command_type;
    std::map<std::string, std::optional<VectorFeature>> before;
    std::map<std::string, std::optional<VectorFeature>> after;

    std::vector<std::string> feature_ids() const;  // sorted union
    void apply(std::map<std::string, VectorFeature>& target) const;
    void revert(std::map<std::string, VectorFeature>& target) const;
    Json audit_record() const;
};

// Named command constructors (Python EditCommand subclass parity — the
// subclasses carry no behavior beyond the type/before/after payload).
EditCommand add_feature_command(const VectorFeature& feature);
EditCommand delete_feature_command(const VectorFeature& feature);
EditCommand move_feature_command(const VectorFeature& before,
                                 const VectorFeature& after);
EditCommand set_geometry_command(const VectorFeature& before,
                                 const VectorFeature& after);
EditCommand set_vertex_command(const VectorFeature& before,
                               const VectorFeature& after);
EditCommand insert_vertex_command(const VectorFeature& before,
                                  const VectorFeature& after);
EditCommand delete_vertex_command(const VectorFeature& before,
                                  const VectorFeature& after);
EditCommand change_attribute_command(const VectorFeature& before,
                                     const VectorFeature& after);
EditCommand split_feature_command(
    const std::map<std::string, std::optional<VectorFeature>>& before,
    const std::map<std::string, std::optional<VectorFeature>>& after);
EditCommand merge_features_command(
    const std::map<std::string, std::optional<VectorFeature>>& before,
    const std::map<std::string, std::optional<VectorFeature>>& after);
EditCommand add_ring_command(const VectorFeature& before,
                             const VectorFeature& after);
EditCommand delete_ring_command(const VectorFeature& before,
                                const VectorFeature& after);
EditCommand fill_ring_command(const VectorFeature& before,
                              const VectorFeature& after,
                              const VectorFeature& new_feature);
EditCommand duplicate_feature_command(const VectorFeature& feature);
EditCommand add_part_command(const VectorFeature& before,
                             const VectorFeature& after);
EditCommand delete_part_command(const VectorFeature& before,
                                const VectorFeature& after);
EditCommand move_part_command(const VectorFeature& before,
                              const VectorFeature& after);

// ---------------------------------------------------------------------------
// EditDelta (edit_delta.py)
// ---------------------------------------------------------------------------

namespace edit_ops {
inline constexpr const char* kCreateFeature = "create_feature";
inline constexpr const char* kMoveFeature = "move_feature";
inline constexpr const char* kMoveVertex = "move_vertex";
inline constexpr const char* kDeleteFeature = "delete_feature";
inline constexpr const char* kSplitFeature = "split_feature";
inline constexpr const char* kMergeFeatures = "merge_features";
inline constexpr const char* kReplaceGeometry = "replace_geometry";
inline constexpr const char* kUpdateAttributes = "update_attributes";
}  // namespace edit_ops

// geometry_hash: sha256(json.dumps(geometry, sort_keys))[:16]; "" for
// non-object/empty geometry (Python None parity uses empty string).
std::string geometry_hash(const Json& geometry);

struct EditDelta {
    std::string layer_id;
    std::string feature_id;
    std::string operation;
    std::string session_id;
    int order = 0;
    std::string source_tool = "command";
    std::string qgis_capability = "unavailable";
    std::optional<std::string> before_geometry_hash;
    std::optional<Json> after_geometry;
    std::optional<Json> attribute_delta;
    std::vector<std::string> selection_context;
    std::vector<std::string> related_feature_ids;
    double timestamp = 0.0;
    int contract_version = 1;

    bool from_native_tool() const;  // source_tool endswith "(native)"
    Json to_dict() const;
};

// delta_from_command parity — nullopt for unmapped command types
// ("compound" included: compounds flatten upstream).
std::optional<EditDelta> delta_from_command(
    const EditCommand& command, const std::string& layer_id,
    const std::string& session_id, int order, const std::string& source_tool,
    const std::string& qgis_capability,
    const std::vector<std::string>& selection_context = {},
    std::optional<double> timestamp = std::nullopt);

// ---------------------------------------------------------------------------
// VectorLayer
// ---------------------------------------------------------------------------

class VectorEditSession;

class VectorLayer {
public:
    VectorLayer(std::string id, std::string name, std::string crs = "",
                std::string source_ref = "", Json schema = Json::object(),
                std::vector<VectorFeature> features = {},
                Json style = Json::object(), Json labels = Json::object());

    const std::string& id() const { return id_; }
    const std::string& name() const { return name_; }
    void set_name(std::string name) { name_ = std::move(name); }
    const std::string& crs() const { return crs_; }
    void set_crs(std::string crs) { crs_ = std::move(crs); }
    const std::string& source_ref() const { return source_ref_; }
    const Json& schema() const { return schema_; }
    Json& schema() { return schema_; }
    const Json& style() const { return style_; }
    void set_style(Json style);
    const Json& labels() const { return labels_; }
    Json& labels() { return labels_; }

    int64_t data_revision = 1;
    int64_t style_revision = 1;

    std::vector<std::string> feature_ids() const;
    std::vector<VectorFeature> features() const;
    const VectorFeature& feature(const std::string& feature_id) const;
    bool has_feature(const std::string& feature_id) const;
    size_t feature_count() const { return features_.size(); }

    // Direct committed-state write for host load paths (mirrors Python
    // assigning layer._features during construction).
    void replace_features(std::vector<VectorFeature> features);

    // -- selection ---------------------------------------------------------
    std::set<std::string> selectable_feature_ids() const;
    std::set<std::string> selection() const;
    std::set<std::string> set_selection(
        const std::vector<std::string>& feature_ids);
    std::set<std::string> toggle_selection(const std::string& feature_id);
    std::set<std::string> select_all();
    std::set<std::string> invert_selection();
    void set_staged_selection(const std::vector<std::string>& feature_ids);
    std::set<std::string> staged_selection() const;

    // -- edit session --------------------------------------------------------
    VectorEditSession* edit_session() const { return edit_session_.get(); }
    VectorEditSession& start_editing();
    // Layer commits the session working copy (called by the session only).
    void commit_working(const std::map<std::string, VectorFeature>& working);
    void discard_session(VectorEditSession* session);

    // -- native-commit audit stream (apply_committed_delta) -------------------
    std::vector<Json> commit_audit() const;
    // Absorb one native edit commit delta; returns produced audit records.
    std::vector<Json> apply_committed_delta(
        const Json& delta, const std::string& session_id,
        const std::string& source_tool, const Json& gestures = Json());

private:
    std::string id_;
    std::string name_;
    std::string crs_;
    std::string source_ref_;
    Json schema_ = Json::object();
    Json style_ = Json::object();
    Json labels_ = Json::object();
    std::map<std::string, VectorFeature> features_;
    std::set<std::string> selection_;
    std::set<std::string> staged_selection_;
    std::unique_ptr<VectorEditSession> edit_session_;
    std::vector<Json> commit_journal_;

    friend class VectorEditSession;
};

// ---------------------------------------------------------------------------
// VectorEditSession
// ---------------------------------------------------------------------------

// QGIS-inspired edit buffer: working state, undo/redo, commit, rollback.
// All mutations raise std::invalid_argument / std::out_of_range mirroring
// Python ValueError/KeyError/IndexError.
class VectorEditSession {
public:
    explicit VectorEditSession(VectorLayer& layer);

    VectorLayer& layer;
    const std::string session_id;
    int64_t revision = 0;
    std::string qgis_capability_token = "unavailable";

    bool is_dirty() const { return !undo_stack_.empty(); }
    size_t undo_depth() const { return undo_stack_.size(); }
    size_t redo_depth() const { return redo_stack_.size(); }

    const VectorFeature& feature(const std::string& feature_id) const;
    std::vector<VectorFeature> features() const;
    bool has_feature(const std::string& feature_id) const;

    // changes_since: journal entries with revision > watermark, oldest
    // first; nullopt when the span is unrecoverable.
    std::optional<std::vector<std::vector<std::string>>> changes_since(
        int64_t watermark) const;

    // -- compound commands ---------------------------------------------------
    void begin_edit_command();
    void end_edit_command();
    void destroy_edit_command();
    bool has_open_command() const { return open_command_.has_value(); }

    // edit_source context tag (RAII): deltas recorded while the guard is
    // alive carry source_tool.
    class SourceGuard {
    public:
        SourceGuard(VectorEditSession& session, std::string source);
        ~SourceGuard();
        SourceGuard(const SourceGuard&) = delete;
        SourceGuard& operator=(const SourceGuard&) = delete;

    private:
        VectorEditSession& session_;
        std::string previous_;
    };
    SourceGuard edit_source(std::string source_tool) {
        return SourceGuard(*this, std::move(source_tool));
    }

    // -- mutation surface ------------------------------------------------------
    void add_feature(const VectorFeature& feature);
    void delete_feature(const std::string& feature_id);
    void move_feature(const std::string& feature_id, double dx, double dy);
    void set_geometry(const std::string& feature_id, const Json& geometry);
    void set_vertex(const std::string& feature_id,
                    const std::vector<int>& path, const Json& coordinate);
    void insert_vertex(const std::string& feature_id,
                       const std::vector<int>& path, const Json& coordinate);
    void delete_vertex(const std::string& feature_id,
                       const std::vector<int>& path);
    void change_attribute(const std::string& feature_id,
                          const std::string& key, const Json& value);
    void add_ring(const std::string& feature_id,
                  const std::vector<MapPoint>& ring);
    // fill_ring returns the new feature id.
    std::string fill_ring(const std::string& feature_id, int ring_index);
    void delete_ring(const std::string& feature_id, int ring_index);
    VectorFeature duplicate_feature(const std::string& feature_id,
                                    const std::string& new_feature_id = "");
    void add_part(const std::string& feature_id, const Json& geometry);
    void delete_part(const std::string& feature_id, const Json& geometry);
    void move_part(const std::string& feature_id, int part_index, double dx,
                   double dy);
    void split_feature(const std::string& feature_id,
                       const std::vector<VectorFeature>& replacements);
    void merge_features(const std::vector<std::string>& feature_ids,
                        const VectorFeature& merged);

    // -- history ---------------------------------------------------------------
    bool undo();
    bool redo();
    void commit_changes();
    void rollback_changes();
    std::vector<Json> audit_history() const;
    const std::vector<EditDelta>& deltas() const { return delta_journal_; }

    // Test/host introspection parity with Python attributes.
    const std::vector<EditCommand>& undo_stack() const { return undo_stack_; }
    const std::vector<EditCommand>& redo_stack() const { return redo_stack_; }

private:
    void bump_revision(const std::vector<std::string>& touched = {});
    void record(const EditCommand& command, bool already_applied = false);
    void record_delta(const EditCommand& command);

    std::map<std::string, VectorFeature> working_;
    std::vector<EditCommand> undo_stack_;
    std::vector<EditCommand> redo_stack_;
    std::optional<std::vector<EditCommand>> open_command_;
    std::vector<std::pair<int64_t, std::vector<std::string>>> journal_;
    std::vector<EditDelta> delta_journal_;
    int64_t delta_order_ = 0;
    std::optional<std::string> delta_source_tool_;
    std::optional<std::vector<EditDelta>> pending_deltas_;
};

}  // namespace pwb::ui_composite
