#pragma once

// UI-09 — heavyweight engine seams (header-only).
//
// The well-log canvas, seismic view and joint-3D scene are engines the
// slice does NOT reimplement. Pages receive them as injected QWidget*
// handles plus a small capability record; a null widget renders the same
// honest placeholder the Python page shows when the engine import fails
// (engine_unavailable_text — never a silent empty pane).

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <QString>
#include <QStringList>
#include <QWidget>

class QTreeWidgetItem;

namespace pwb::ui_wellseis::qt {

// WellLogCanvasPanel: one backend's surface + what it can do.
struct WellLogCanvasSeam {
    QWidget* widget = nullptr;          // nullptr -> engine unavailable
    bool depth_cursor_supported = false; // crosshair channel exists
    std::string engine_error;            // import/probe failure text
};

// SeismicViewPanel: the seismic volume surface.
struct SeismicViewSeam {
    QWidget* widget = nullptr;
    std::string engine_error;
};

// WellSeismicJointPage / GeologicalModeling3DPage: the joint 3D host.
struct JointHostSeam {
    QWidget* widget = nullptr;
    std::string engine_error;
};

// Factories let the platform inject the real engines without this library
// depending on them (the widget's parent is set by the caller's layout).
using WellLogCanvasFactory = std::function<WellLogCanvasSeam(QWidget* parent)>;
using SeismicViewFactory = std::function<SeismicViewSeam(QWidget* parent)>;
using JointHostFactory = std::function<JointHostSeam(QWidget* parent)>;

// ---------------------------------------------------------------------
// WellSeismicJointHost seam (viz/joint_host.py). The pages only ever talk
// to this controller — the geoviz scene/widget behind it is engine-owned.
// A scene-read slice lets the page build its state snapshot without the
// engine's types leaking into the shell.
struct JointTimeSliceEntry {
    double time_ms = 0.0;
    bool visible = true;
};

struct JointSceneSnapshot {
    bool has_scene = false;
    bool depth_domain = false;       // vertical_domain startswith "depth"
    bool depth_available = false;    // scene.depth_available
    std::string slice_state_warning; // scene.slice_state_warning ("")
    std::vector<std::string> fence_well_ids;
    std::string active_fence_id;
    // Scene-order fence entries (06: + visibility for multi-fence UI).
    struct JointFenceEntry {
        std::string id;
        std::string name;
        bool visible = true;
    };
    std::vector<JointFenceEntry> fences;
    // (well presentation id, display name, visible) in scene order.
    struct WellPresentation {
        std::string id;
        std::string display_name;
        bool visible = true;
    };
    std::vector<WellPresentation> well_presentations;
    std::optional<int> inline_index;
    std::optional<int> crossline_index;
    // Registration-resolved physical line numbers (nullopt w/o registration).
    std::optional<double> inline_number;
    std::optional<double> crossline_number;
    // Preview index bounds for the slice card's spin ranges.
    int n_inline = 0;
    int n_crossline = 0;
    double time_min_ms = 0.0;
    double time_max_ms = 0.0;
    std::vector<JointTimeSliceEntry> time_slices;
    std::optional<double> active_time_ms;
    double time_opacity = 0.8;  // 0..1 (the card displays *100)
};

// ---- 2D fence profile view (#61/#62: profile_2d.py contract) ------------
// The amplitude strip the 3D curtain already renders, plus the wells
// projected onto the active fence — seam-local value types keep the
// engine's geo3d types out of the shell.
struct JointFenceProfileStrip {
    std::vector<float> amplitude;   // n_along * n_sample, row-major
    std::vector<double> arc_length_m;
    std::vector<double> sample_axis;  // active-domain units
    std::string sample_unit;          // "ms" or "m"
};

struct JointFenceProfileWell {
    std::string name;
    double distance_m = 0.0;
    std::vector<std::pair<std::string, double>> tops;  // (name, z)
};

// WellSeismicJointHost — every method mirrors the Python host/scene calls
// the pages make. The platform injects the real host; tests use a fake.
class JointHostController : public QObject {
    Q_OBJECT
public:
    using QObject::QObject;

    // Host lifecycle (shutdown_workers parity).
    virtual bool shutdown(int wait_ms) = 0;
    virtual void reload() = 0;
    [[nodiscard]] virtual JointSceneSnapshot scene_snapshot() const = 0;
    [[nodiscard]] virtual bool has_scene() const = 0;
    [[nodiscard]] virtual std::string engine_error() const = 0;
    // 2D fence profile: nullopt when there is no active fence or the
    // volume/survey is not ready (the page keeps its honest placeholder).
    [[nodiscard]] virtual std::optional<JointFenceProfileStrip>
    active_fence_strip() const {
        return std::nullopt;
    }
    // Wells projected onto the active fence (empty without one).
    [[nodiscard]] virtual std::vector<JointFenceProfileWell>
    active_fence_wells() const {
        return {};
    }
    // scene.well_presentations()-ordered (id, display) pairs; falls back to
    // host.well_names() when no scene/presentations exist.
    [[nodiscard]] virtual std::vector<std::pair<std::string, std::string>>
    well_options() const = 0;
    // host.set_vertical_domain — false when the domain change was refused.
    virtual bool set_vertical_domain(const std::string& domain) = 0;
    virtual void add_well_to_well_fence(const std::string& well_a,
                                        const std::string& well_b,
                                        const std::string& name = {}) = 0;
    virtual void delete_active_fence() = 0;
    // Multi-fence management (06): activate an existing fence for the 2D
    // profile view; toggle one fence's curtain visibility. No-ops on
    // hosts without a scene (default impl keeps simple fakes honest).
    virtual void activate_fence(const std::string& fence_id) {
        (void)fence_id;
    }
    virtual void set_fence_visible(const std::string& fence_id,
                                   bool visible) {
        (void)fence_id;
        (void)visible;
    }
    // scene.set_orthogonal_slice_indices / restore_orthogonal_slice_state
    virtual void set_orthogonal_slice_indices(
        std::optional<int> inline_index,
        std::optional<int> crossline_index) = 0;
    virtual void restore_orthogonal_slice_state(
        std::optional<int> inline_index,
        std::optional<int> crossline_index,
        const std::vector<JointTimeSliceEntry>& time_slices,
        std::optional<double> active_time_ms,
        double time_opacity) = 0;
    // registration.il_xl_to_volume_idx (pending physical numbers -> indices).
    virtual bool apply_slice_line_numbers(double inline_number,
                                          double crossline_number) = 0;
    virtual void add_time_slice(double time_ms) = 0;
    virtual void remove_time_slice(double time_ms) = 0;
    virtual void set_time_slice_visible(double time_ms, bool visible) = 0;
    virtual void set_active_time_slice(double time_ms) = 0;
    virtual void set_time_opacity(double fraction) = 0;  // 0..1
    virtual void set_3d_mode(const std::string& mode) = 0;  // planes|volume
    virtual void set_color_scales(const std::string& seismic_scale,
                                  const std::string& gr_scale) = 0;
    virtual void set_well_width(int px) = 0;
    virtual void set_well_visibility(const std::string& well_id,
                                     bool visible) = 0;
    virtual void set_layer_visibility(const std::string& layer_name,
                                      bool visible) = 0;
    virtual void apply_camera_preset(const std::string& preset) = 0;
    // Well-identity diagnostics (collect_joint_analysis_state reads these).
    [[nodiscard]] virtual std::string well_identity_asset_id() const = 0;
    [[nodiscard]] virtual std::map<std::string, std::string>
    well_identity_map() const = 0;
    // host.paths -> path hints (segy/well_head/td_dir/tops/horizons joined
    // with '|' like the Python page).
    [[nodiscard]] virtual std::map<std::string, std::string>
    path_hints() const = 0;
    // Loaded data paths for snapshot lineage (paths slice — resource id
    // matching stays a core helper over ProjectSlice).
    [[nodiscard]] virtual std::vector<std::string>
    loaded_data_paths() const = 0;
    // Cross-page seams (highlight_well / focus_seismic_position parity).
    virtual bool highlight_well(const std::string& well_name) = 0;
    virtual bool focus_position(int il, int xl,
                                std::optional<double> twt) = 0;
    // The engine widget the page embeds (nullptr = engine unavailable —
    // the page renders the honest placeholder like Python does).
    virtual QWidget* joint_widget(QWidget* parent) = 0;
    // scene -> widget.set_scene + 2D strip refresh (engine-side plumbing
    // that follows a scene_updated).
    virtual void push_scene_to_widget() = 0;

signals:
    void status_changed(const QString& text);
    void scene_updated();
    // 3D two-click well pick resolved by the engine (#123); name is the
    // presentation display name the page publishes via well_selected.
    void well_picked(const QString& well_name);
};

// Geo3DWorkspaceController seam (viz/geo3d_workspace.py) — measurement /
// clip / saved views / QC / inspector, all state controller-owned.
class Geo3DController : public QObject {
    Q_OBJECT
public:
    using QObject::QObject;

    virtual void set_widget(QWidget* widget) = 0;
    virtual void set_measure_mode(const QString& mode) = 0;
    virtual int clear(const QString& kind) = 0;  // -> removed count
    virtual void set_axis_clip(const QString& axis, bool enabled,
                               double value, bool invert) = 0;
    virtual void reset_clip() = 0;
    // axis -> (enabled, value 0..1) for UI restore.
    [[nodiscard]] virtual std::map<QString, std::pair<bool, double>>
    clip_state() const = 0;
    virtual void fit_all() = 0;
    [[nodiscard]] virtual std::vector<QString> saved_view_names() const = 0;
    virtual void save_view(const QString& name) = 0;
    virtual void apply_view(const QString& name) = 0;
    virtual void rebuild_tree(QTreeWidgetItem* root) = 0;
    virtual void sync_scene() = 0;
    virtual void save_state() = 0;  // -> project (geo3d save_state parity)
    virtual void set_tree_visibility(const QString& name, bool checked) = 0;
    // Selected-object inspector text ("" = nothing selected).
    virtual void inspect(const QString& object_id) = 0;

signals:
    void status_message(const QString& text);
    void qc_updated(const QStringList& lines);
    void selection_changed(const QString& object_id);
    void inspector_updated(const QString& text);
};

}  // namespace pwb::ui_wellseis::qt
