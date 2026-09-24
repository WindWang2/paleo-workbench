#pragma once

// UI-10 — Qt shell for stratigraphy_correlation_page.py: multi-well
// stratigraphic correlation over an injected CrossWell/WellLogEngine
// surface.
//
// The page owns the widget tree (well picker | section host | action
// panel in a horizontal splitter), the backend stack, the well-list
// keyed diff, the UI-04 load/DTW worker wiring through PwbTaskOwner, and
// the interpretation-version dialogs. Every domain call the Python page
// reaches into (tops files, correlation lifecycle, engine adapters,
// catalog registration) is an injected seam — absent seams take the
// honest-refusal paths the core's gate functions describe.

#include <QDialog>
#include <QWidget>

#include <any>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <pwb/qgis_processing/task_bridge.hpp>
#include <pwb/ui_seqviz/correlation_state.hpp>
#include <pwb/ui_seqviz/viz_page_state.hpp>
#include <pwb/ui_workers/correlation_load.hpp>
#include <pwb/ui_workers/dtw_propagation.hpp>

class QButtonGroup;
class QCheckBox;
class QComboBox;
class QFrame;
class QLabel;
class QListWidget;
class QListWidgetItem;
class QPushButton;
class QSlider;
class QSplitter;
class QStackedLayout;
class QScrollArea;
class QSpinBox;
class QTimer;

namespace pwb::ui_shell {
class FloatController;
class LayoutPersistence;
}  // namespace pwb::ui_shell

namespace pwb::ui_seqviz::qt {

// ---------------------------------------------------------------------------
// Canvas/host seams — the Python CrossWellHost surface the page calls.
// ---------------------------------------------------------------------------

// One pick from picks_model.all_picks() — connected_wells() /
// depth_for_well() / formation_name frozen as slices.
struct CorrelationPick {
    std::string formation_name;
    // well name -> depth (pick.depth_for_well(w) lookup).
    std::map<std::string, double> depth_by_well;
    // pick.connected_wells() order.
    std::vector<std::string> connected_wells;
};

// CrossWellExportDialog options() payload.
struct CrossWellExportOptions {
    std::string fmt = "svg";
    int dpi = 150;
    std::optional<int> width_px;
    std::optional<std::string> page_size;
};

struct CorrelationCanvasApi {
    QWidget* widget = nullptr;        // cross_host.widget (canvas)
    QWidget* inner_widget = nullptr;  // cross_host.inner

    // host.apply(VizPayload(kind="cross_well")) / host.clear()
    std::function<bool(const UiVizPayload&)> apply;
    std::function<void()> clear;

    // picks_model
    std::function<std::vector<CorrelationPick>()> all_picks;
    // picks_model.add_pick(formation, well, depth, source=...) -> pick
    std::function<void(const std::string& formation,
                       const std::string& well, double depth,
                       const std::string& source)>
        add_pick;
    std::function<void()> picks_undo;
    std::function<void()> picks_redo;
    std::function<void()> picks_clear;

    // tops_model + formation data
    std::function<void()> tops_clear;
    std::function<bool()> tops_any;
    // tops_model.add_top(FormationTop(well, marker, depth))
    std::function<void(const std::string& well, const std::string& marker,
                       double depth)>
        add_top;
    std::function<std::vector<std::string>()> formation_names;
    // tops_model.save_csv(path)
    std::function<void(const std::string& path)> save_tops_csv;
    // inner.set_formation_data(well, tops_to_intervals(tops))
    std::function<void(const std::string& well, const std::any& intervals)>
        set_formation_data;

    // canvas/inner interaction state
    std::function<void(bool)> set_pick_mode;        // canvas.pick_mode
    std::function<void(bool)> set_manual_link;      // inner.set_manual_link
    // canvas.active_formation = text or None
    std::function<void(const std::optional<std::string>&)>
        set_active_formation;
    std::function<void(const std::string&)> set_snap_type;  // snap_type
    std::function<void(bool)> set_tops_visible;             // set_tops_visible
    std::function<void(int)> set_well_spacing;              // inner
    std::function<void()> auto_link;                        // inner

    // inner track labels + visibility
    std::function<std::vector<std::string>()> track_labels;
    std::function<void(const std::string& label, bool visible)>
        set_track_visible;

    // compute_dtw_propagation scene snapshot (wells + curves).
    std::function<ui_workers::DtwSceneSlice()> dtw_scene;

    // inner._canvases non-empty — the export precondition.
    std::function<bool()> has_canvases;
    // inner.export_composite(path, fmt, dpi, width_px, page_size)
    std::function<void(const std::string& path,
                       const CrossWellExportOptions& options)>
        export_composite;
};

// ---------------------------------------------------------------------------
// WellLogEngine backend seams — engine_adapter + multi_adapter.
// ---------------------------------------------------------------------------
struct CorrelationEngineApi {
    // engine_adapter.try_import_welllog — absent factory = "welllog 绑定
    // 未安装"; has_submit==nullptr/false = "缺少 submit_multi_well_section".
    std::function<QWidget*(QWidget* parent)> view_factory;
    std::function<bool()> has_submit_multi_well_section;
    // engine_adapter.clear_engine_view(view)
    std::function<void(QWidget*)> release_view;
    // view.clear_multi_well_section() — optional callable.
    std::function<void(QWidget*)> clear_view_section;
    // view.grab() for the engine PNG export — default widget->grab().
    std::function<bool(QWidget* view, const std::string& path)> grab_png;

    // multi_adapter.adapt_multi_well_section(...) -> plan (type-erased).
    struct PlanInput {
        std::vector<std::any> logs;
        std::vector<std::string> names;
        std::vector<std::string> resource_ids;
        std::map<std::string, std::vector<std::pair<std::string, double>>>
            tops_by_well;
        int spacing_px = 150;
        std::string datum_mode = "md";   // "horizon" when target set
        std::string target_horizon;
    };
    std::function<std::any(const PlanInput&)> adapt_plan;
    // plan truthiness — plan.wells non-empty.
    std::function<bool(const std::any& plan)> plan_has_wells;
    // multi_adapter.submit_multi_well_plan(view, plan) -> report.
    std::function<std::any(QWidget* view, const std::any& plan)>
        submit_plan;
};

// ---------------------------------------------------------------------------
// Workflow seams — stratigraphy_correlation / correlation_lifecycle /
// catalog calls the Python page reaches into (no C++ port — injected).
// ---------------------------------------------------------------------------

// tops_by_well — load_well_tops(project) payload.
using TopsByWell =
    std::map<std::string, std::vector<std::pair<std::string, double>>>;

struct CorrelationWorkflowSeams {
    // StratigraphicCorrelationEngine — bind_wells + recommend_top.
    // bind_wells receives the loaded (logs, names) — the seam builds the
    // engine's well dicts (curves/depths extraction is engine-side).
    std::function<void(const std::vector<std::any>& logs,
                       const std::vector<std::string>& names)>
        bind_wells;
    // recommend_top(ref_well, ref_depth, target_well) -> recommendation
    // (type-erased); absent = the empty-engine path.
    std::function<std::any(const std::string& ref_well, double ref_depth,
                           const std::string& target_well)>
        recommend_top;
    // rec -> (dtw_cost, confidence); absent rec/未绑定 => sentinel.
    std::function<std::pair<double, double>(const std::any& rec)>
        recommend_values;

    // Loaded-log introspection (getattr parity; absent => 0s).
    CurveCountFn curve_count_fn;
    CurveLengthFn curve_length_fn;

    // load_well_tops(project) -> (tops_by_well, warnings)
    std::function<std::pair<TopsByWell, std::vector<std::string>>()>
        load_well_tops;
    // match_tops_to_wells(tops_by_well, names)
    std::function<TopsMatchResult(const TopsByWell& tops,
                                  const std::vector<std::string>& names)>
        match_tops;
    // tops_to_intervals(tops) -> engine interval object (type-erased).
    std::function<std::any(
        const std::vector<std::pair<std::string, double>>& tops)>
        tops_to_intervals;

    // workflow.stratigraphy — active_target_horizon(project) / bound ids.
    std::function<std::optional<std::string>()> active_target_horizon;
    std::function<std::set<std::string>()> bound_well_ids;

    // -- interpretation lifecycle (Stage-12) ------------------------------
    // project.correlation_interpretations -> ref slices (last wins).
    std::function<std::vector<CorrelationInterpRef>()> interp_refs;
    // _tops_from_canvas — build science tops; throws => the
    // TopsBuildFailed gate carries the exception text.
    std::function<std::vector<std::any>(
        const std::vector<std::string>& loaded_names,
        const std::vector<std::string>& loaded_ids,
        const std::any& draft)>
        tops_from_canvas;
    // _links_from_session — derived+merged links into draft.payload.
    std::function<void(std::any& draft,
                       const std::vector<std::any>& tops)>
        apply_links;
    // new_correlation_draft(name, ids, version_ids, tops, domain, horizon)
    std::function<std::any(const std::vector<std::any>& tops,
                           const std::vector<std::string>& ids,
                           const std::vector<std::string>& version_ids,
                           const std::string& horizon)>
        new_draft;
    // _resolve_well_version_ids
    std::function<std::vector<std::string>(
        const std::vector<std::string>& resource_ids)>
        resolve_version_ids;
    // draft update path (draft!=None): tops/links/ids/version_ids assign +
    // dirty=True (the bump-only-if-content-changes fingerprint stays
    // lifecycle-side).
    std::function<void(std::any& draft,
                       const std::vector<std::any>& tops,
                       const std::vector<std::string>& ids,
                       const std::vector<std::string>& version_ids)>
        update_draft;
    // save_correlation_draft(draft, project, project_file) -> (ref, msg)
    std::function<
        std::pair<std::optional<CorrelationInterpRef>, std::string>(
            std::any& draft)>
        save_draft;
    // restore_draft_from_project_ref(project, file) -> draft or {} —
    // throws => the RestoreFailed gate carries the text.
    std::function<std::any()> restore_draft;
    // draft reads: dirty / parent_version_id / tops rows for canvas apply.
    struct DraftInfo {
        bool dirty = false;
        std::string parent_version_id;
        // (well, marker, depth) rows — draft.payload.tops frozen.
        std::vector<std::tuple<std::string, std::string, double>> tops;
    };
    std::function<DraftInfo(const std::any& draft)> draft_info;
    // run_link_editor(parent, draft, on_changed) — L4 editor seam.
    std::function<void(QWidget* parent, std::any& draft,
                       const std::function<void()>& on_changed)>
        run_link_editor;

    // register_export_output / record_export provenance (best-effort).
    std::function<void(const std::string& name, const std::string& path,
                       const std::string& fmt,
                       const std::vector<std::string>& source_ids)>
        register_export;
    // default_export_dir(project_file)
    std::function<std::string()> export_dir;

    // -- correlation load worker seams -------------------------------------
    // The loader's resolve/merge/name internals (Python passes
    // loader=load_correlation_wells — the C++ port runs
    // ui_workers::load_correlation_wells with these seams).
    ui_workers::CorrelationSeams correlation;
    // Worker-level loader override (Python `loader=` parity — tests
    // inject fakes); absent ⇒ ui_workers::load_correlation_wells.
    std::function<ui_workers::CorrelationLoadResult(
        const ui_workers::CorrelationLoadInput&)>
        loader_fn;
};

// ---------------------------------------------------------------------------
// StratigraphyCorrelationPage — the page widget.
// ---------------------------------------------------------------------------
class StratigraphyCorrelationPage : public QWidget {
    Q_OBJECT
public:
    explicit StratigraphyCorrelationPage(
        QWidget* parent = nullptr,
        ui_shell::LayoutPersistence* persistence = nullptr);
    ~StratigraphyCorrelationPage() override;

    // Bind the host surfaces (call once the engine widgets exist).
    void set_canvas(CorrelationCanvasApi canvas);
    void set_engine(CorrelationEngineApi engine);
    void set_workflow(CorrelationWorkflowSeams workflow);

    // set_project(project) — the host's live project handle (type-erased;
    // forwarded to the workflow seams) plus the worker-facing project
    // slice (resources + project_root + prediction task). `token` is the
    // host's identity key for the Python `project is not self._project`
    // check — a changed token while a load runs gets the bump+cancel.
    void set_project(
        const std::any& project,
        const ui_workers::CorrelationProjectSlice& project_slice,
        const void* token = nullptr);
    void set_project_path(const std::string& path);

    const std::any& project() const { return project_; }
    CorrelationBackend backend() const { return backend_; }
    void set_backend(const std::string& name);
    const std::any& engine_plan() const { return engine_plan_; }
    const std::any& engine_report() const { return engine_report_; }
    const std::string& engine_error() const { return engine_error_; }

    void update_state();
    std::vector<std::string> selected_resource_ids() const;
    void load_section();
    void clear_section();
    bool shutdown_workers(int wait_ms = 3'000);

    // save/open/restore interpretation versions (Stage-12 lifecycle).
    void save_interpretation_version();
    void open_saved_interpretation();
    void restore_saved_interpretation();

    // -- Python member surfaces ------------------------------------------
    QListWidget* well_list() const { return well_list_; }
    QListWidget* track_list() const { return track_list_; }
    QLabel* status_label() const { return status_label_; }
    QLabel* horizon_value() const { return horizon_value_; }
    QLabel* section_title() const { return section_title_; }
    QLabel* loaded_value() const { return loaded_value_; }
    QLabel* tops_value() const { return tops_value_; }
    QLabel* interp_status() const { return interp_status_; }
    QComboBox* backend_combo() const { return backend_combo_; }
    QComboBox* formation_combo() const { return formation_combo_; }
    QSplitter* content_splitter() const { return splitter_; }

    // QMessageBox.question seam — default QMessageBox::question (Python
    // parity); tests inject a non-blocking answer.
    using ConfirmFn = std::function<bool(const QString& title,
                                         const QString& message)>;
    void set_confirm_fn(ConfirmFn fn) { confirm_fn_ = std::move(fn); }

signals:
    void section_updated();
    // QMessageBox seams.
    void warning_requested(const QString& title, const QString& message);
    void info_requested(const QString& title, const QString& message);

protected:
    void closeEvent(QCloseEvent* event) override;

private:
    void on_backend_combo(int index);
    void probe_engine();
    void sync_backend_stack();
    void ensure_engine_view();
    void release_engine_view();

    void sync_well_list(
        const std::vector<ui_workers::ResourceSlice>& resources);
    void select_bound_wells();

    void on_mode_changed();
    void on_formation_changed(const QString& text);
    void on_snap_changed();
    void on_tops_visible(bool checked);
    void on_spacing_changed(int value);
    void undo_pick();
    void redo_pick();
    void run_auto_link();
    void run_dtw();
    void on_dtw_progress(double done, double total);
    void on_dtw_finished(const ui_workers::DtwPropagationResult& result);
    void on_dtw_failed(const std::string& message);
    void on_dtw_cancelled();
    void on_track_item_changed(QListWidgetItem* item);
    std::vector<std::string> inject_well_tops(
        const std::vector<std::string>& names,
        const std::optional<TopsByWell>& tops_by_well);
    void refresh_track_list();
    void export_tops();
    void export_section();
    void open_link_editor();
    void refresh_interp_status();
    bool apply_draft_tops_to_canvas(const std::any& draft);
    void bind_engine_wells();
    void reload_current_section();
    // _apply_loaded_section — returns (ok, notices, path_msg).
    std::tuple<bool, std::vector<std::string>, std::string>
    apply_loaded_section();
    void build_engine_plan_only(
        const std::vector<std::any>& logs,
        const std::vector<std::string>& names,
        const std::vector<std::string>& resource_ids,
        const std::optional<TopsByWell>& raw_tops);
    bool apply_engine_section(const std::vector<std::any>& logs,
                              const std::vector<std::string>& names,
                              const std::vector<std::string>& ids);
    void on_load_finished(
        const ui_workers::CorrelationLoadResult& result);
    void on_load_failed(const std::string& message);
    void on_load_cancelled();
    void register_export(const std::string& path, const std::string& fmt,
                         const std::string& label);
    bool confirm_question(const QString& title, const QString& message);
    void make_floatable(const std::string& key, QWidget* panel,
                        const QString& title);
    void persist_docked_sizes();

    CorrelationCanvasApi canvas_;
    CorrelationEngineApi engine_;
    CorrelationWorkflowSeams workflow_;

    std::any project_;
    ui_workers::CorrelationProjectSlice project_slice_;
    const void* project_token_ = nullptr;
    std::string project_path_;
    CorrelationBackend backend_ = CorrelationBackend::Legacy;
    bool engine_binding_installed_ = false;

    std::vector<WellListEntry> well_entries_;
    WellListSignature well_list_signature_;
    std::vector<std::any> loaded_logs_;
    std::vector<std::string> loaded_names_;
    std::vector<std::string> loaded_ids_;
    std::any engine_plan_;
    std::any engine_report_;
    std::string engine_error_;
    QWidget* engine_view_ = nullptr;
    std::any correlation_draft_;
    LoadSeqGuard load_seq_;
    std::string dtw_formation_;
    std::string dtw_conf_text_ = "置信度: 不可用";
    double dtw_confidence_ = 0.0;

    pwb::qgis_processing::PwbTaskOwner* load_job_ = nullptr;
    pwb::qgis_processing::PwbTaskOwner* dtw_job_ = nullptr;

    // widgets
    QSplitter* splitter_ = nullptr;
    QFrame* well_panel_ = nullptr;
    QListWidget* well_list_ = nullptr;
    QLabel* horizon_value_ = nullptr;
    QLabel* section_title_ = nullptr;
    QLabel* status_label_ = nullptr;
    QComboBox* backend_combo_ = nullptr;
    QButtonGroup* mode_group_ = nullptr;
    QPushButton* browse_btn_ = nullptr;
    QPushButton* pick_btn_ = nullptr;
    QPushButton* link_btn_ = nullptr;
    QComboBox* formation_combo_ = nullptr;
    QComboBox* snap_combo_ = nullptr;
    QPushButton* dtw_btn_ = nullptr;
    QPushButton* undo_btn_ = nullptr;
    QPushButton* redo_btn_ = nullptr;
    QPushButton* auto_link_btn_ = nullptr;
    QCheckBox* tops_visible_box_ = nullptr;
    QSlider* spacing_slider_ = nullptr;
    QStackedLayout* view_stack_ = nullptr;
    class QScrollArea* legacy_scroll_ = nullptr;
    QWidget* engine_view_parent_ = nullptr;
    QLabel* engine_placeholder_ = nullptr;
    QFrame* action_panel_ = nullptr;
    QLabel* loaded_value_ = nullptr;
    QLabel* tops_value_ = nullptr;
    QListWidget* track_list_ = nullptr;
    QPushButton* load_btn_ = nullptr;
    QLabel* interp_status_ = nullptr;

    ConfirmFn confirm_fn_;
    ui_shell::LayoutPersistence* persistence_ = nullptr;
    std::unique_ptr<ui_shell::FloatController> float_controller_;
    std::vector<std::pair<std::string, QWidget*>> floatable_;
};

// cross_well_export_dialog.py — format/DPI/width/page-size picker.
class CrossWellExportDialog : public QDialog {
    Q_OBJECT
public:
    explicit CrossWellExportDialog(QWidget* parent = nullptr);
    CrossWellExportOptions options() const;

private:
    void update_enabled();
    QComboBox* format_combo_ = nullptr;
    QComboBox* dpi_combo_ = nullptr;
    class QSpinBox* width_spin_ = nullptr;
    QComboBox* page_size_combo_ = nullptr;
};

}  // namespace pwb::ui_seqviz::qt
