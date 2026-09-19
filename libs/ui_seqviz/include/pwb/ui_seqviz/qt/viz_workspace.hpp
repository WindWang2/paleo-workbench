#pragma once

// UI-10 — Qt shell for composite_visualization_panel.py
// (VisualizationWorkspace / CompositeVisualizationPanel).
//
// The seven tab hosts (well log / well section / seismic / cross-well /
// paleo map / well tie / engine preview) stay injected engine surfaces —
// the workspace owns the tab strip, the ordered load_payload routing,
// the keep-well-session decision, the multi-scale facies level bar and
// the cross-well section cursor band. Host apply()/clear() results feed
// the Qt-free hosts_to_apply / focus_tab_for / workspace_status_text
// core so the routing order and status text match Python verbatim.

#include <QFrame>

#include <any>
#include <functional>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

#include <pwb/ui_seqviz/viz_page_state.hpp>

class QComboBox;
class QLabel;
class QScrollArea;
class QTabWidget;

namespace pwb::ui_seqviz::qt {

// ---------------------------------------------------------------------------
// Injected host surface — one per tab. `widget` is required; everything
// else maps to a Python host method the workspace calls (absent seams are
// treated like the Python getattr-defaults: no apply, no extras).
// ---------------------------------------------------------------------------
struct VizHostSurface {
    QWidget* widget = nullptr;  // the tab page (required)
    // host.apply(payload) -> bool
    std::function<bool(const UiVizPayload&)> apply;
    // host.clear()
    std::function<void()> clear;

    // -- PaleoMapHost extras (the multi-scale level bar) ------------------
    // host.hierarchy_active property
    std::function<bool()> hierarchy_active;
    // host._current_features — facies_level_choices input
    std::function<domain::Json()> current_features;
    // host.set_level(value)
    std::function<void(const std::string&)> set_level;

    // -- CrossWellHost extras (section cursor band + scroll area) --------
    // host.last_well_names
    std::function<std::vector<std::string>()> last_well_names;
    // host.inner — the cursor band's parent widget (canvas container).
    QWidget* inner_widget = nullptr;

    // -- WellLogHost extras ------------------------------------------------
    // host.has_data()
    std::function<bool()> has_data;
    // host.set_project(project, project_path=...)
    std::function<void(const std::any& project,
                       const std::string& project_path)>
        set_project;
};

// The injected seams the workspace needs beyond the host surfaces.
struct VizWorkspaceSeams {
    std::map<VizHostKind, VizHostSurface> hosts;
    // VizAdapter().from_ref(ref, project) — absent ⇒ load_ref is a no-op
    // returning a "message" payload (the honest empty-resolution path).
    std::function<UiVizPayload(const VizRefSlice&)> ref_resolver;
    // VizAdapter().from_prediction(task) — the legacy update_state
    // fallback (last task wins; absent ⇒ the clear + hint branch).
    std::function<UiVizPayload(const PredictionTaskSlice&)>
        prediction_resolver;
    // view_export_capabilities(widget) -> {"PNG",...} — absent ⇒ empty set.
    std::function<std::set<std::string>(QWidget*)> export_caps_fn;
    // export_widget_snapshot(widget, path, format) -> success — absent
    // ⇒ false (honest export failure, never a fabricated file).
    std::function<bool(QWidget*, const std::string& path,
                       const std::string& format)>
        export_fn;
};

// ---------------------------------------------------------------------------
// VisualizationWorkspace — the deep composite surface (load /
// export_snapshot 2-method interface + the panel members Python exposes).
// ---------------------------------------------------------------------------
class VisualizationWorkspace : public QFrame {
    Q_OBJECT
public:
    explicit VisualizationWorkspace(QWidget* parent = nullptr);

    // Bind the host surfaces + resolver seams (call once after the engine
    // hosts exist; may be re-called — tabs rebuild like Python's __init__).
    void set_seams(VizWorkspaceSeams seams);
    const VizWorkspaceSeams& seams() const { return seams_; }

    // -- Python member surfaces ------------------------------------------
    QLabel* status_label() const { return status_label_; }
    QTabWidget* tabs() const { return tabs_; }
    QWidget* level_bar() const { return level_bar_; }
    QComboBox* level_combo() const { return level_combo_; }
    QScrollArea* cross_well_scroll() const { return cross_well_scroll_; }
    QWidget* section_cursor_band() const { return section_cursor_band_; }

    bool has_well_log_loaded() const;

    // load(payload_or_ref): two entry points for the payload/ref union.
    UiVizPayload load(const UiVizPayload& payload);
    UiVizPayload load_ref(const VizRefSlice& ref);
    void load_payload(const UiVizPayload& payload);

    // export_snapshot: caps query (path empty) or snapshot write.
    std::set<std::string> export_capabilities() const;
    bool export_snapshot(const std::string& path,
                         const std::string& format = "PNG");

    // show_section_cursor — the M3 well-level linkage indicator.
    void show_section_cursor(const std::string& well_name);
    // set_project — Stage-12 well-log correlation overlay binding.
    void set_project(const std::any& project,
                     const std::string& project_path = "");
    // update_state — the legacy no-ref fallback (active task or hint).
    void update_state(const std::vector<PredictionTaskSlice>& tasks);
    // _clear_all / _clear_canvases.
    void clear_all(bool preserve_well = false);

private:
    const VizHostSurface* host(VizHostKind kind) const;
    int tab_index_of(VizHostKind kind) const;
    void rebuild_tabs();
    void refresh_level_selector();
    void on_level_changed(int index);

    VizWorkspaceSeams seams_;
    std::any project_;
    std::string project_path_;

    QLabel* status_label_ = nullptr;
    QWidget* level_bar_ = nullptr;
    QComboBox* level_combo_ = nullptr;
    QTabWidget* tabs_ = nullptr;
    QScrollArea* cross_well_scroll_ = nullptr;
    QWidget* section_cursor_band_ = nullptr;
    // Tab-page order, matching Python's addTab sequence.
    std::vector<VizHostKind> tab_order_;
};

// Backward-compatible alias (composite_visualization_panel.py bottom).
using CompositeVisualizationPanel = VisualizationWorkspace;

}  // namespace pwb::ui_seqviz::qt
