#pragma once

// UI-02 — QgisCanvasShim: the QGIS canvas host exposing the
// CompositeDocument-facing contract, ported from
// paleo_workbench/ui/qgis_stack/canvas_shim.py.
//
// Boundary notes (native port):
//  - The Python shim wraps the qgis_render_bridge mapstack (canvas by
//    address, JSON tool callbacks, capability-manifest probing). The
//    native port IS the bridge: a session-owned QgsMapCanvas via
//    pwb::qgis::MapSession. Address bookkeeping collapses to the
//    canvas pointer; manifest probes collapse to direct API presence.
//  - Bridge JSON callback surfaces (digitize/edit_pick/selection/
//    measure) become explicit entry methods driven by the native edit
//    stack — the same payload vocabulary, the same downstream dispatch
//    (tool commit -> tool_operation / commit_rejected).
//  - Python monkey-patching of tools.set_active_tool becomes the
//    arm_tool(tool_id) entry: hosts call it when their tool state
//    changes; kind vocabulary is preserved, a factory injects native
//    QgsMapTool instances for edit kinds (pan/zoom are built in).
//  - Live-shim registry + shutdown_live_shims() parity is kept:
//    orderly teardown stays a host responsibility.

#include <QPointer>
#include <QString>
#include <QStringList>
#include <QVariantMap>
#include <QVariantList>
#include <QWidget>

#include <array>
#include <functional>
#include <memory>
#include <optional>
#include <set>
#include <vector>

class QgsMapCanvas;
class QgsMapTool;
class QgsVectorLayer;
class QgsHighlight;
class QMouseEvent;

namespace pwb::qgis {
class MapSession;
}

namespace pwb::ui_widgets::qgis {

class StackEvents;
class QgisCanvasHost;
class MirrorLedger;
class CanvasMouseRouter;
struct MirrorSnapshot;
struct MirrorOptions;
struct MirrorResult;

// Extent tuple (xmin, ymin, xmax, ymax) — the Python (float,4) shape.
using CanvasExtent = std::array<double, 4>;

// The Python `tool` duck (commit_vertex_move / commit_move /
// commit_vertex_insert / commit_vertex_delete / commit_geometry /
// commit_selection + measure fallback surface) as an explicit hook
// set. Missing hooks behave like the absent Python attributes.
struct ToolHooks {
    QString tool_id;
    // Edit picks: return true when the session accepted the write.
    std::function<bool(const QString& feature_id,
                       const QVariantList& path,
                       std::pair<double, double> xy)> commit_vertex_move;
    std::function<bool(const QString& feature_id, double dx,
                       double dy)> commit_move;
    std::function<bool(const QString& feature_id,
                       const QVariantList& path,
                       std::pair<double, double> xy)> commit_vertex_insert;
    std::function<bool(const QString& feature_id,
                       const QVariantList& path)> commit_vertex_delete;
    // Digitize completion (geometry payload dict) -> accepted?
    std::function<bool(const QVariantMap& geometry)> commit_geometry;
    // Selection commit (feature_ids, modifiers) -> accepted?
    std::function<bool(const QVariantList& feature_ids,
                       const QVariantList& modifiers)> commit_selection;
    // Selection highlight projection: the Python path reads
    // tool.layer.selection + tool.layer.id and pushes a highlight;
    // natively the host resolves ids/doc_id via this hook (fid mapping
    // is the edit stack's domain). Return "" to skip.
    std::function<QString()> highlight_layer_doc_id;
    std::function<QStringList()> highlight_feature_ids;
    // Fallback measure surface (host's non-native measure tool):
    std::function<void(std::pair<double, double> point,
                       const QString& button,
                       const QStringList& modifiers)> mouse_press;
    std::function<void(std::pair<double, double> point,
                       const QString& button,
                       const QStringList& modifiers)> mouse_release;
    std::function<void(std::pair<double, double> point,
                       const QStringList& modifiers)> double_click;
    std::function<std::optional<double>()> last_distance;
    std::function<std::optional<std::pair<double, double>>()> start_point;
    std::function<std::optional<std::pair<double, double>>()> current_point;
    // add_part/fault_cut-style tools: host-declared digitize kind.
    QString native_digitize_kind;
};

// The Python `controller` duck (commit_native_capture /
// cancel_native_capture / record_native_gesture / join_native_layers /
// active_tool) as hooks.
struct ControllerHooks {
    std::function<ToolHooks*()> active_tool;
    // Native-first routing for digitize completions (splits/cuts take
    // precedence over the active tool's commit_geometry — ordering is
    // contract, see _on_digitize docstring parity).
    std::function<bool(const QVariantMap& geometry)> commit_native_capture;
    std::function<void()> cancel_native_capture;
    // Native gesture bookkeeping (edit happened on the mirror buffer).
    std::function<bool(const QVariantMap& gesture)> record_native_gesture;
    // All-layers vertex scope: the gesture touched neighbor layers ->
    // host re-checks admission for the joined set.
    std::function<void(const QStringList& layer_doc_ids)>
        join_native_layers;
};

// edit-pick dispatch — the Python module-level dispatch_edit_pick
// parity function. Returns true when the tool accepted and committed.
// `shim` receives the outcome signals (tool_operation/commit_rejected).
bool dispatch_edit_pick(class QgisCanvasShim& shim,
                        ToolHooks* tool,
                        const QString& action,
                        const QVariantMap& payload);

class QgisCanvasShim : public QWidget {
    Q_OBJECT
public:
    explicit QgisCanvasShim(QWidget* parent = nullptr);
    ~QgisCanvasShim() override;

    // ---- state & geometry ------------------------------------------
    QString backend_status() const;
    quintptr canvas_address() const {
        return reinterpret_cast<quintptr>(canvas_);
    }
    QgsMapCanvas* canvas() const { return canvas_; }
    CanvasExtent view_extent() const;
    bool can_previous_extent() const { return extent_history_index_ > 0; }
    bool can_next_extent() const {
        return extent_history_index_ + 1 < int(extent_history_.size());
    }
    void set_extent(const CanvasExtent& extent,
                    bool record_history = true,
                    bool coalesce_history = false);
    bool previous_extent();
    bool next_extent();
    void zoom_by(double factor,
                 std::optional<std::pair<double, double>> center = {},
                 bool coalesce_history = false);
    double map_units_per_pixel() const;
    std::pair<double, double> map_to_screen(
        std::pair<double, double> point) const;
    std::pair<double, double> screen_to_map(
        std::pair<double, double> point) const;

    void set_overlay_provider(std::function<QVariantMap()> provider);

    // ---- snapping / current layer / tools ---------------------------
    bool set_snapping_config(const QVariantMap& config);
    void set_vertex_edit_scope(bool all_layers);
    void set_tracing_enabled(bool enabled);
    void set_current_layer(const QString& doc_id);
    QString current_layer_doc_id() const;
    bool native_tool_busy() const;
    void cancel_native_tool();
    // The kind-vocabulary tool arming entry (the Python wrapped
    // set_active_tool): resolves tool_id -> kind, asks the factory for
    // a QgsMapTool, arms the canvas. Failures emit
    // backend_status_changed + native_tool_activation_failed (ADV-1:
    // checked state must never drift from the canvas tool silently).
    void arm_tool(const QString& tool_id);
    QString active_map_tool_id() const;
    // Factory for kinds the built-in set (pan/zoomIn/zoomOut) does not
    // cover — the edit stack registers its native tools here. Returning
    // nullptr counts as activation failure (honest).
    void set_tool_factory(
        std::function<QgsMapTool*(const QString& kind,
                                  QgsMapCanvas* canvas)> factory);
    // Host-declared native measure support (the Python manifest probe;
    // natively there is no bridge manifest — the host declares what it
    // can arm). When false, the viewport router drives the fallback
    // measure surface on the active ToolHooks.
    void set_native_measure_supported(bool supported);
    // Esc-semantics probe for digitize/drag-in-progress (native tools
    // expose busy state via their own signals; the host reports it).
    void set_busy_probe(std::function<bool()> probe);
    // The controller hook set the dispatch methods consult.
    void set_controller_hooks(ControllerHooks hooks);

    // ---- canvas facts ----------------------------------------------
    double map_scale() const;
    QString destination_crs() const;
    QString map_units() const;
    double output_dpi() const;
    QVariantMap mirror_provider_facts(const QString& doc_id) const;
    QVariantMap crs_chain_facts(const QString& storage_crs = {}) const;

    // ---- bridge-callback entry points (native edit stack drives) ---
    // Same payload vocabulary as the Python bridge callbacks; the
    // downstream dispatch (commit order, rejection surfaces) is ported
    // verbatim.
    void on_digitize(const QString& status, const QVariantMap& geom);
    void on_edit_pick(const QString& action, const QVariantMap& payload);
    void on_selection(const QString& action, const QVariantMap& payload);
    void on_measure(const QString& action, const QVariantMap& payload);

    // ---- layer mirror ----------------------------------------------
    // Mirror a snapshot into the session project (incremental reconcile
    // by pwb/doc_id). changed_hints is accepted for API parity — the
    // native full-resend already matches the semantics (documented
    // simplification).
    void set_layer_snapshot(const MirrorSnapshot& snapshot,
                            bool changed_hints = false);
    bool layer_groups_enabled = false;  // Python public attr parity
    // Layers the host's edit session owns (M0 §3 stop-publish window).
    void set_edit_frozen_layer_ids(std::set<QString> ids);

    // ---- export (export_service capability detection) --------------
    QStringList export_capabilities() const;
    // Honest failures (the Python ExportError becomes an error string
    // return; empty = success).
    QString export_png(const QString& path);
    QString export_svg(const QString& path);
    QString export_pdf(const QString& path);

    // ---- lifecycle --------------------------------------------------
    // Orderly teardown — the host calls this before the widget tree
    // dies (Python shutdown() parity).
    void shutdown();
    bool is_shutdown() const { return shutdown_done_; }

    // Internal surfaces used by the file-local chrome/router helpers
    // (public for the same reason Python's private helpers are
    // reachable — chrome widgets live outside the class).
    std::pair<int, int> chrome_map_size() const;
    QVariantMap overlay_state() const;
    bool route_measure_mouse(QMouseEvent* event);

    // Highlight projection (selection feedback visual only): resolves
    // doc feature ids through the mirror __pwb_fid attribute.
    void apply_highlight(const QString& doc_id,
                         const QStringList& feature_ids);
    void clear_highlights();

    // Process-wide live-shim cleanup (test hygiene / shell teardown).
    static int shutdown_live_shims();

signals:
    void extent_changed(CanvasExtent extent);
    void map_position_changed(std::pair<double, double> position);
    void backend_status_changed(const QString& status);
    void tool_operation(bool mutated);
    void native_identified(const QVariantMap& payload);
    void measure_segment(double distance);
    void measure_preview(double distance);
    void measure_updated(const QVariantMap& payload);
    void snap_feedback(const QVariantMap& payload);
    void capture_progress(const QVariantMap& payload);
    void measure_canceled();
    void commit_rejected(const QString& reason);
    void native_tool_activation_failed(const QString& tool_id,
                                       const QString& reason);
    void canvas_context_menu(std::pair<double, double> map_point,
                             QPoint global_pos);
    void status_hint(const QString& message);

protected:
    bool eventFilter(QObject* obj, QEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;
    void showEvent(QShowEvent* event) override;
    void closeEvent(QCloseEvent* event) override;

private:
    friend class CanvasMouseRouter;
    friend bool dispatch_edit_pick(QgisCanvasShim&, ToolHooks*,
                                   const QString&, const QVariantMap&);

    // Internals (private in Python too).
    void on_stack_extent(double xmin, double ymin, double xmax,
                         double ymax);
    void install_chrome_overlay();
    void refresh_chrome_overlay() { install_chrome_overlay(); }
    bool is_fitted_compatible(const CanvasExtent& expected,
                              const CanvasExtent& actual) const;
    QWidget* canvas_viewport() const;
    void emit_measure_preview(ToolHooks* tool);
    void on_canvas_context_menu(const QPoint& pos);
    void warn_vertex_without_target();
    QString export_vector(const QString& path, const QString& fmt);
    void mark_disposed();
    void record_extent_for_user(const CanvasExtent& extent);

    std::unique_ptr<pwb::qgis::MapSession> session_;
    QgisCanvasHost* host_ = nullptr;
    QgsMapCanvas* canvas_ = nullptr;
    StackEvents* events_ = nullptr;
    QWidget* chrome_scale_ = nullptr;
    QWidget* chrome_north_ = nullptr;
    QWidget* chrome_legend_ = nullptr;
    bool chrome_filter_installed_ = false;
    std::function<QVariantMap()> overlay_provider_;
    std::unique_ptr<MirrorLedger> ledger_;
    std::unique_ptr<MirrorSnapshot> last_snapshot_;
    QStringList mirrored_layers_;
    QStringList mirrored_doc_ids_;
    QStringList mirror_failures_;
    bool shutdown_done_ = false;
    bool canvas_created_ = false;
    bool canvas_destroyed_ = false;
    ControllerHooks controller_;
    CanvasMouseRouter* measure_router_ = nullptr;
    std::optional<double> last_measure_emit_;
    bool native_measure_supported_ = false;
    bool measure_degrade_warned_ = false;
    std::function<QgsMapTool*(const QString&, QgsMapCanvas*)> tool_factory_;
    std::unique_ptr<QgsMapTool> owned_tool_;  // pan/zoom tools the shim owns
    std::pair<QString, QString> last_native_tool_{QStringLiteral("pan"),
                                                 QStringLiteral("pan")};
    std::function<bool()> busy_probe_;
    QString pushed_current_layer_;
    bool vertex_no_target_warned_ = false;
    QString project_crs_hint_;
    int pending_programmatic_ = 0;
    std::vector<CanvasExtent> expected_programmatic_extents_;
    std::optional<CanvasExtent> last_emitted_extent_;
    std::vector<CanvasExtent> extent_history_;
    int extent_history_index_ = 0;
    std::set<QString> edit_frozen_ids_;
    bool exporting_ = false;
    std::vector<QgsHighlight*> highlights_;  // owned visual projections
};

}  // namespace pwb::ui_widgets::qgis
