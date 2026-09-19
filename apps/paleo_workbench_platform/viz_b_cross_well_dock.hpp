#pragma once

// VIZ-B — cross-well correlation & well-tie dock (platform wiring).
//
// Product composition root for line B: the multi-well section canvas +
// formation tops preview + well tie page, the picks/tops models with
// undo, DTW propagation through the JobCenter (never inline), the
// UI-09 CorrelationLinkEditor / CrossWellExportDialog bindings, and the
// cross_well_workspace persistence payload. MainWindow only creates
// this dock and wires save/restore to the project document — all logic
// lives here and in the viz-B libraries.

#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <QDockWidget>
#include <QString>

#include <pwb/domain/json.hpp>
#include <pwb/viz/cross_well/picks_model.hpp>
#include <pwb/viz/cross_well/qt/section_canvas.hpp>
#include <pwb/viz/cross_well/seismic_tie.hpp>
#include <pwb/viz/cross_well/tops_model.hpp>

class QComboBox;
class QLabel;
class QTabWidget;
class QTimer;

namespace pwb::app {
class JobCenter;
}

namespace pwb::viz::well_tie::qt {
class WellTieCanvas;
}
namespace pwb::viz::cross_well::qt {
class FormationTopsPreview;
}

namespace pwb::app {

class VizBCrossWellDock : public QDockWidget {
    Q_OBJECT

  public:
    explicit VizBCrossWellDock(JobCenter* job_center,
                               QWidget* parent = nullptr);
    ~VizBCrossWellDock() override;

    // B-line persistence payload. Today the payload lives in a
    // B-exclusive sidecar (cross_well_workspace.json next to the project
    // file — the C++ shell has no project-document save path yet); the
    // schema is already shaped for the future cross_well_workspace
    // top-level node (Python ProjectDocument is extra=allow).
    [[nodiscard]] pwb::domain::Json save_state() const;
    void restore_state(const pwb::domain::Json& state);
    void set_project_directory(const QString& directory);
    // Reads the sidecar (when a project directory is set). Late in-flight
    // results are dropped by the generation bump in restore/handle_close.
    void restore_from_project();
    // Project closed/switched: bump the session generation so in-flight
    // job results are dropped on arrival (never written late), flush the
    // sidecar one last time, then detach from the directory.
    void handle_project_closed();

    // Real data paths (JSON well store = the frozen fixture format;
    // LAS arrives through the same seam once line A's parser merges).
    bool load_wells_from_json(const QString& path, QString* error);
    bool load_tops_csv(const QString& path, QString* error);
    bool load_checkshot_csv(const QString& path, QString* error);

    [[nodiscard]] std::size_t well_count() const {
        return wells_.size();
    }
    [[nodiscard]] std::size_t pick_count() const {
        return picks_model_.all_picks().size();
    }

  signals:
    void status_message(const QString& message);

  private slots:
    void on_load_wells();
    void on_load_tops();
    void on_load_checkshot();
    void on_auto_arrange();
    void on_propagate_dtw();
    void on_edit_links();
    void on_export_section();
    void on_export_report();
    void on_export_tie_report();
    void on_well_tie_well_changed();
    void on_picks_changed();

  private:
    void build_ui();
    void schedule_persistence();
    void apply_dtw_results(
        const std::vector<std::pair<std::string, double>>& pairs,
        const std::string& formation);

    // Data.
    std::vector<pwb::viz::cross_well::WellColumnData> wells_;
    pwb::viz::cross_well::FormationTopsModel tops_model_;
    pwb::viz::cross_well::HorizonPicksModel picks_model_;
    pwb::viz::cross_well::SeismicTie tie_;
    pwb::domain::Json links_json_ = pwb::domain::Json::array();
    pwb::domain::Json top_meta_ = pwb::domain::Json::object();

    // UI.
    QTabWidget* tabs_ = nullptr;
    pwb::viz::cross_well::qt::SectionCanvas* canvas_ = nullptr;
    pwb::viz::cross_well::qt::FormationTopsPreview* preview_ = nullptr;
    pwb::viz::well_tie::qt::WellTieCanvas* tie_canvas_ = nullptr;
    QComboBox* tie_well_selector_ = nullptr;
    QLabel* tie_readout_ = nullptr;

    // Jobs.
    JobCenter* job_center_ = nullptr;  // fresh JobOwner per submission
    std::uint64_t session_generation_ = 1;
    QTimer* persist_timer_ = nullptr;
    bool persist_dirty_ = false;
    QString project_directory_;
    QString last_wells_path_;  // sidecar well source (auto-reload)
    void persist_now();
    // Well coordinates (lng/lat) from the well store — the planner's
    // real input; without it auto-arrange is an honest no-op.
    pwb::domain::Json well_coords_cache_ = pwb::domain::Json::array();
};

}  // namespace pwb::app
