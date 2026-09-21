#pragma once

// UI-09 — GeologicalModeling3DPage Qt shell
// (geological_modeling_3d_page.py). Well–seismic joint workbench
// (nav 井震联合): geoviz scene tree + Geo3D inspector panel on the left;
// joint 3D toolbar + slice card + collapsible 2D strip + tabbed analysis
// card in the center. ALL scene/engine/worker semantics live behind
// JointHostController / Geo3DController / Geo3DAnalysisHooks — the page
// owns controls, enablement, labels, tree-check state and the
// JointAnalysisSlice collect/restore lifecycle (never preview voxels).

#include <cstdint>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include <QString>
#include <QWidget>

#include <pwb/ui_wellseis/joint_state.hpp>
#include <pwb/ui_wellseis/qt/engine_seams.hpp>
#include <pwb/ui_wellseis/slices.hpp>

class QCheckBox;
class QComboBox;
class QDoubleSpinBox;
class QFrame;
class QLabel;
class QListWidget;
class QPushButton;
class QSlider;
class QSpinBox;
class QSplitter;
class QTabWidget;
class QTextBrowser;
class QTreeWidget;
class QTreeWidgetItem;

namespace pwb::ui_wellseis::qt {

// Analysis worker + persistence seams (viz/geo3d_workspace +
// OwnedWorkerJob entries + project.joint_analysis). Empty hooks map to
// the honest "未接入" status — never a silent dead button.
struct Geo3DAnalysisHooks {
    // project.joint_analysis get/set (the C++ slice carries every field
    // collect_joint_analysis_state reads; preview voxels never stored).
    std::function<std::optional<JointAnalysisSlice>()> stored_state;
    std::function<void(const JointAnalysisSlice&)> save_state;
    // Versioned horizon interpretations for the stratal combos:
    // (label, "interp:<artifact_path>") pairs pre-resolved like
    // _populate_stratal_interpretations (project-anchored, is_file-checked).
    std::function<std::vector<std::pair<std::string, std::string>>(
        const QString& project_path)>
        horizon_interpretations;
    // Worker entry points — the host runs ui_workers run_* in a job and
    // reports status via set_status / the tab status labels.
    // (No run_modeling seam: the Python page's modeling trigger lives on a
    // permanently hidden card with no visible entry — porting a dead button
    // would be wiring noise. The demo-scene generator itself stays available
    // through ui_workers for tests/examples.)
    std::function<void(const std::string& top_entry,
                       const std::string& bottom_entry,
                       const std::vector<double>& fractions, bool demo)>
        generate_stratal;
    std::function<void()> clear_stratal;
    std::function<void(int wavelet_freq, int td_shift)> tie_params_changed;
    std::function<void()> run_auto_tie;
    std::function<void()> run_rgb_fusion;
    std::function<void()> run_crossplot;
    std::function<void()> run_export;
    std::function<void()> run_advisor;
    // 浏览… horizon file dialog seam.
    std::function<QString(const QString& title)> pick_horizon_file;
};

class GeologicalModeling3DPage : public QWidget {
    Q_OBJECT
public:
    GeologicalModeling3DPage(QWidget* parent, JointHostController* host,
                             Geo3DController* geo3d = nullptr,
                             Geo3DAnalysisHooks hooks = {});

    void set_project(const ProjectSlice* project,
                     const std::optional<JointAnalysisSlice>&
                         joint_state);
    void set_project_path(const QString& path);
    bool shutdown_workers(int wait_ms = 3000);

    // Composition-root hook injection (the product install fills every
    // seam; reduced builds keep the honest 未接入 fallbacks). Replaces the
    // hooks and refreshes the interpretation combos.
    void set_analysis_hooks(const Geo3DAnalysisHooks& hooks);
    // Auto-tie result surface for the host hook: applies the recovered
    // shift to the 时深偏移 slider and reports the correlation coefficient
    // (Python parity: slider_td_shift.setValue + CC label).
    void set_well_tie_result(int shift_samples, double cc);
    // Export/diagnostics status line (the export tab's own label).
    void set_export_status(const QString& text);
    // Stratal tab status line / joint top-bar status (host hooks report).
    void set_stratal_status(const QString& text);
    void set_status_text(const QString& text);
    // Test/verification surface: the stratal tab status line text
    // (definition in the .cpp — QLabel is only forward-declared here).
    [[nodiscard]] QString stratal_status_text() const;

    // Page navigation entry (activate_page + showEvent parity).
    void activate_page();
    void ensure_joint_data_loaded();

    // #90 — snapshot joint UI into the slice (never voxels).
    [[nodiscard]] JointAnalysisSlice collect_joint_analysis_state() const;
    void save_joint_analysis_to_project();
    void apply_tree_checks(const std::map<std::string, bool>& checks);
    void restore_fence(const JointAnalysisSlice& state);

    // Cross-page seams.
    bool highlight_well(const std::string& well_name);
    bool focus_seismic_position(int il, int xl,
                                std::optional<double> twt);

    [[nodiscard]] QTreeWidget* model_tree() const;
    [[nodiscard]] QString status_text() const;

signals:
    // A well picked in the 3D view is announced by name so other pages
    // can sync their selection to it.
    void well_selected(const QString& well_name);

protected:
    void showEvent(QShowEvent* event) override;
    void closeEvent(QCloseEvent* event) override;

private:
    void populate_model_tree();
    QTreeWidgetItem* add_checkable_child(QTreeWidgetItem* parent,
                                       const QString& name);
    void refresh_joint_well_tree();
    void refresh_joint_fence_tree();
    void update_coordinate_note();
    void on_scene_updated();
    void fill_joint_well_combos();
    void rebuild_joint_well_combos(const QString& preferred_a,
                                   const QString& preferred_b);
    void on_joint_domain_changed(const QString& text);
    void update_domain_combo_availability();
    void update_domain_z_guard(const QString& domain);
    void refresh_joint_slice_card();
    void apply_display_settings();
    void apply_joint_tree_checks_from_project();
    void sync_joint_visibility_from_tree();
    void on_tree_item_changed(QTreeWidgetItem* item, int column);
    bool is_tree_descendant(QTreeWidgetItem* item,
                            QTreeWidgetItem* ancestor) const;
    void restore_joint_slice_settings();
    void apply_pending_slice_numbers();
    void sync_2d_time_chip();
    QWidget* build_stratal_tab();
    QWidget* build_welltie_tab();
    QWidget* build_facies_tab();
    QWidget* build_export_diag_tab();
    void sync_analysis_actions();
    void populate_stratal_interpretations();

    JointHostController* host_ = nullptr;
    Geo3DController* geo3d_ = nullptr;
    Geo3DAnalysisHooks hooks_;
    const ProjectSlice* project_ = nullptr;
    std::optional<JointAnalysisSlice> joint_state_;
    QString project_path_;

    // Tree.
    QTreeWidget* model_tree_ = nullptr;
    QTreeWidgetItem* joint_root_ = nullptr;
    QTreeWidgetItem* joint_wells_item_ = nullptr;
    QTreeWidgetItem* joint_fence_item_ = nullptr;
    QTreeWidgetItem* stratal_item_ = nullptr;
    QTreeWidgetItem* geo3d_root_ = nullptr;
    bool joint_well_visibility_restored_ = false;

    // Geo3D inspector panel.
    QComboBox* measure_combo_ = nullptr;
    std::map<QString, std::pair<QCheckBox*, QSlider*>> clip_rows_;
    QComboBox* view_combo_ = nullptr;
    QListWidget* qc_list_ = nullptr;
    QTextBrowser* inspector_ = nullptr;

    // Toolbar.
    QComboBox* domain_combo_ = nullptr;
    QComboBox* mode_3d_combo_ = nullptr;
    QPushButton* slice_card_btn_ = nullptr;
    QPushButton* analysis_btn_ = nullptr;
    QComboBox* pick_mode_combo_ = nullptr;
    QComboBox* well_a_ = nullptr;
    QComboBox* well_b_ = nullptr;
    QLabel* status_ = nullptr;
    QString domain_guard_note_;

    // 2D strip + color card.
    QFrame* joint_2d_panel_ = nullptr;
    QFrame* joint_color_card_ = nullptr;
    QWidget* joint_2d_host_ = nullptr;
    QLabel* time_chip_ = nullptr;
    QLabel* coord_note_ = nullptr;  // 坐标/单位说明 (06)
    QLabel* joint_2d_placeholder_ = nullptr;
    bool depth_domain_2d_ = false;
    QComboBox* seismic_color_combo_ = nullptr;
    QComboBox* gr_color_combo_ = nullptr;
    QSpinBox* well_width_spin_ = nullptr;
    QWidget* joint_widget_ = nullptr;
    bool suppress_tree_signals_ = false;

    // Slice card.
    QSpinBox* inline_slice_ = nullptr;
    QSpinBox* crossline_slice_ = nullptr;
    QComboBox* time_selector_ = nullptr;
    QDoubleSpinBox* active_time_editor_ = nullptr;
    QCheckBox* active_time_visible_ = nullptr;
    QDoubleSpinBox* new_time_ = nullptr;
    QSpinBox* time_opacity_ = nullptr;
    QLabel* time_domain_note_ = nullptr;
    std::optional<std::pair<double, double>> pending_slice_numbers_;

    // Analysis card.
    QFrame* analysis_card_ = nullptr;
    QTabWidget* analysis_tabs_ = nullptr;
    QComboBox* stratal_top_combo_ = nullptr;
    QComboBox* stratal_bot_combo_ = nullptr;
    QComboBox* stratal_fractions_ = nullptr;
    QCheckBox* stratal_demo_check_ = nullptr;
    QPushButton* stratal_generate_btn_ = nullptr;
    QPushButton* stratal_clear_btn_ = nullptr;
    QLabel* stratal_status_ = nullptr;
    QSlider* wtie_freq_ = nullptr;
    QSlider* wtie_shift_ = nullptr;
    QLabel* wtie_corr_label_ = nullptr;
    QLabel* export_status_ = nullptr;

    bool loaded_once_ = false;
};

}  // namespace pwb::ui_wellseis::qt
