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
#include <QStringList>

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
    // 05 线：LAS 经与测井页同一 WellLogLoadFn 生产 seam 真解析接入).
    bool load_wells_from_json(const QString& path, QString* error);
    bool load_wells_from_las(const QStringList& paths, QString* error);
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
    void on_load_las();
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
    // 清空工作区（工程切换到无 sidecar 的新工程时——绝不带着上一个工程
    // 的井/拾取显示）。
    void reset_workspace();
    // LAS 加载结果统一落账（同步路径与 JobCenter 异步路径共用）：井列、
    // 坐标、逐文件错误 → 状态 + 身份注册 + 来源显示 + 持久化调度。
    void apply_las_wells(const QStringList& paths,
                         const std::vector<
                             pwb::viz::cross_well::WellColumnData>& wells,
                         const pwb::domain::Json& coords,
                         const QStringList& errors);
    // 共享井身份（05 线）：井列加载成功后按名注册；结果来源显示引用。
    void register_well_identities();
    // 数据/结果来源显示（用户可见的出处：井文件来源 + 最近计算结果）。
    void update_source_label();
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
    QLabel* source_label_ = nullptr;  // 05 线：井来源 + 最近结果出处

    // Jobs.
    JobCenter* job_center_ = nullptr;  // fresh JobOwner per submission
    std::uint64_t session_generation_ = 1;
    QTimer* persist_timer_ = nullptr;
    bool persist_dirty_ = false;
    QString project_directory_;
    QString last_wells_path_;  // sidecar well source (auto-reload, JSON)
    QStringList last_las_paths_;  // 05 线：sidecar well_source_las (auto-reload)
    QString last_result_note_;  // 05 线：最近计算结果出处（来源显示）
    void persist_now();
    // Well coordinates (lng/lat) from the well store — the planner's
    // real input; without it auto-arrange is an honest no-op.
    pwb::domain::Json well_coords_cache_ = pwb::domain::Json::array();
};

}  // namespace pwb::app
