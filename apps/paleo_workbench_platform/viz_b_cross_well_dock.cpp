#include "viz_b_cross_well_dock.hpp"

#include "job_center.hpp"
#if defined(PWB_WITH_VIZ_B_LAS)
#include "viz_b_well_source.hpp"
#endif

// VIZ-B — see header. This file is product wiring only: the numeric and
// painting contracts live in Pwb::Visualization{CrossWell,WellTie} and
// the workers in Pwb::UiWorkers (no second DTW, no Python).

#include <QComboBox>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QLabel>
#include <QMessageBox>
#include <QProgressDialog>
#include <QPushButton>
#include <QTabWidget>
#include <QTimer>
#include <QToolButton>
#include <QVBoxLayout>

#include <pwb/domain/json.hpp>
#include <pwb/job_runtime/qt/job_bridge.hpp>
#include <pwb/ui_wellseis/correlation.hpp>
#include <pwb/ui_wellseis/qt/correlation_link_editor.hpp>
#include <pwb/ui_wellseis/qt/cross_well_export_dialog.hpp>
#include <pwb/ui_wellseis/qt/object_table_model.hpp>
#include <pwb/ui_workers/dtw_propagation.hpp>
#include <pwb/ui_workers/well_identity.hpp>
#include <pwb/viz/cross_well/auto_section_planner.hpp>
#include <pwb/viz/cross_well/qt/formation_tops_preview.hpp>
#include <pwb/viz/cross_well/qt/report_export.hpp>
#include <pwb/viz/well_tie/qt/report_export.hpp>
#include <pwb/viz/well_tie/synthetic.hpp>
#include <pwb/viz/well_tie/qt/tie_canvas.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <fstream>
#include <utility>

namespace pwb::app {

using pwb::domain::Json;
using pwb::viz::cross_well::FormationTop;
using pwb::viz::cross_well::WellColumnData;
using pwb::viz::cross_well::WellCoord;
using pwb::viz::cross_well::WellCurve;
using pwb::viz::well_tie::qt::WellTieReportInputs;
using pwb::viz::well_tie::qt::export_well_tie_report;

namespace {

std::vector<double> read_nums(const Json& arr) {
    std::vector<double> out;
    if (!arr.is_array()) return out;
    for (const Json& v : arr) {
        if (v.is_number()) {
            out.push_back(v.get<double>());
        } else if (v.is_string()) {
            const std::string s = v.get<std::string>();
            if (s == "nan") {
                out.push_back(std::numeric_limits<double>::quiet_NaN());
            } else if (s == "inf") {
                out.push_back(std::numeric_limits<double>::infinity());
            } else if (s == "-inf") {
                out.push_back(-std::numeric_limits<double>::infinity());
            }
        }
    }
    return out;
}

// top id = "<pick_id>#<well>" (the link editor's row key).
std::string top_id(const std::string& pick_id, const std::string& well) {
    return pick_id + "#" + well;
}

bool split_top_id(const std::string& id, std::string& pick_id,
                  std::string& well) {
    const auto pos = id.find('#');
    if (pos == std::string::npos) return false;
    pick_id = id.substr(0, pos);
    well = id.substr(pos + 1);
    return true;
}

}  // namespace

VizBCrossWellDock::VizBCrossWellDock(JobCenter* job_center,
                                     QWidget* parent)
    : QDockWidget(parent), job_center_(job_center) {
    setObjectName(QStringLiteral("viz-b-cross-well-dock"));
    setWindowTitle(tr("井间对比与井震标定"));
    build_ui();
    picks_model_.set_changed_handler([this] { on_picks_changed(); });
    tops_model_.set_changed_handler([this] {
        preview_->set_tops(tops_model_.all_tops());
        canvas_->update();
    });
    persist_timer_ = new QTimer(this);
    persist_timer_->setSingleShot(true);
    persist_timer_->setInterval(300);
    connect(persist_timer_, &QTimer::timeout, this,
            &VizBCrossWellDock::persist_now);
}

VizBCrossWellDock::~VizBCrossWellDock() = default;

void VizBCrossWellDock::build_ui() {
    tabs_ = new QTabWidget(this);

    // --- Section page ----------------------------------------------
    auto* section_page = new QWidget(tabs_);
    auto* section_layout = new QVBoxLayout(section_page);
    auto* toolbar = new QHBoxLayout();
    toolbar->setContentsMargins(4, 4, 4, 4);

    auto* load_wells_button = new QPushButton(tr("加载井数据…"), section_page);
    connect(load_wells_button, &QPushButton::clicked, this,
            &VizBCrossWellDock::on_load_wells);
    toolbar->addWidget(load_wells_button);

    // 05 线：真实 LAS 通路（与测井页同一 WLE 解析 seam）。
    auto* load_las_button =
        new QPushButton(tr("加载井数据（LAS）…"), section_page);
    connect(load_las_button, &QPushButton::clicked, this,
            &VizBCrossWellDock::on_load_las);
    toolbar->addWidget(load_las_button);

    auto* load_tops_button = new QPushButton(tr("加载分层…"), section_page);
    connect(load_tops_button, &QPushButton::clicked, this,
            &VizBCrossWellDock::on_load_tops);
    toolbar->addWidget(load_tops_button);

    auto* load_tie_button = new QPushButton(tr("加载校准表…"), section_page);
    connect(load_tie_button, &QPushButton::clicked, this,
            &VizBCrossWellDock::on_load_checkshot);
    toolbar->addWidget(load_tie_button);

    auto* arrange_button = new QPushButton(tr("自动排列剖面"), section_page);
    connect(arrange_button, &QPushButton::clicked, this,
            &VizBCrossWellDock::on_auto_arrange);
    toolbar->addWidget(arrange_button);

    auto* pick_mode_button = new QPushButton(tr("拾取模式"), section_page);
    pick_mode_button->setCheckable(true);
    connect(pick_mode_button, &QPushButton::toggled, this,
            [this](bool on) { canvas_->set_pick_mode(on); });
    toolbar->addWidget(pick_mode_button);

    auto* undo_button = new QPushButton(tr("撤销"), section_page);
    connect(undo_button, &QPushButton::clicked, this, [this]() {
        if (!picks_model_.undo()) {
            emit status_message(tr("没有可撤销的拾取"));
        }
    });
    toolbar->addWidget(undo_button);

    auto* redo_button = new QPushButton(tr("重做"), section_page);
    connect(redo_button, &QPushButton::clicked, this, [this]() {
        if (!picks_model_.redo()) {
            emit status_message(tr("没有可重做的拾取"));
        }
    });
    toolbar->addWidget(redo_button);

    auto* dtw_button = new QPushButton(tr("DTW 传播"), section_page);
    connect(dtw_button, &QPushButton::clicked, this,
            &VizBCrossWellDock::on_propagate_dtw);
    toolbar->addWidget(dtw_button);

    auto* links_button = new QPushButton(tr("相关链接编辑…"), section_page);
    connect(links_button, &QPushButton::clicked, this,
            &VizBCrossWellDock::on_edit_links);
    toolbar->addWidget(links_button);

    auto* export_button = new QPushButton(tr("导出剖面…"), section_page);
    connect(export_button, &QPushButton::clicked, this,
            &VizBCrossWellDock::on_export_section);
    toolbar->addWidget(export_button);

    auto* report_button = new QPushButton(tr("导出报告…"), section_page);
    connect(report_button, &QPushButton::clicked, this,
            &VizBCrossWellDock::on_export_report);
    toolbar->addWidget(report_button);

    toolbar->addStretch(1);
    section_layout->addLayout(toolbar);

    canvas_ = new pwb::viz::cross_well::qt::SectionCanvas(section_page);
    canvas_->set_models(&tops_model_, &picks_model_);
    section_layout->addWidget(canvas_, 3);
    preview_ =
        new pwb::viz::cross_well::qt::FormationTopsPreview(section_page);
    section_layout->addWidget(preview_, 1);
    // 05 线：数据/结果来源显示（诚实出处：井文件 + 最近计算结果）。
    source_label_ = new QLabel(tr("井数据来源：未加载"), section_page);
    source_label_->setWordWrap(true);
    section_layout->addWidget(source_label_);
    tabs_->addTab(section_page, tr("连井剖面"));

    // --- Well tie page ----------------------------------------------
    auto* tie_page = new QWidget(tabs_);
    auto* tie_layout = new QVBoxLayout(tie_page);
    auto* tie_top = new QHBoxLayout();
    tie_top->addWidget(new QLabel(tr("井："), tie_page));
    tie_well_selector_ = new QComboBox(tie_page);
    connect(tie_well_selector_, &QComboBox::currentTextChanged, this,
            &VizBCrossWellDock::on_well_tie_well_changed);
    tie_top->addWidget(tie_well_selector_);
    auto* tie_report_button = new QPushButton(tr("导出标定报告…"), tie_page);
    connect(tie_report_button, &QPushButton::clicked, this,
            &VizBCrossWellDock::on_export_tie_report);
    tie_top->addWidget(tie_report_button);
    tie_top->addStretch(1);
    tie_layout->addLayout(tie_top);
    tie_canvas_ = new pwb::viz::well_tie::qt::WellTieCanvas(tie_page);
    tie_layout->addWidget(tie_canvas_, 1);
    tie_readout_ = new QLabel(tr("未选择井"), tie_page);
    tie_layout->addWidget(tie_readout_);
    tabs_->addTab(tie_page, tr("井震标定"));

    setWidget(tabs_);
}

bool VizBCrossWellDock::load_wells_from_json(const QString& path,
                                             QString* error) {
    std::ifstream file(path.toStdString());
    if (!file.is_open()) {
        if (error != nullptr) {
            *error = tr("无法打开井数据文件");
        }
        return false;
    }
    Json payload;
    try {
        file >> payload;
    } catch (const std::exception& exc) {
        if (error != nullptr) {
            *error = QString::fromStdString(exc.what());
        }
        return false;
    }
    const Json* wells_json = &payload;
    if (payload.is_object() && payload.contains("wells")) {
        wells_json = &payload.at("wells");
    } else if (payload.is_object() && payload.contains("real_wells")) {
        // The frozen oracle fixture shape (real LAS arrays).
        wells_json = &payload.at("real_wells").at("wells");
    }
    if (!wells_json->is_array()) {
        if (error != nullptr) *error = tr("井数据格式错误（需要 wells 数组）");
        return false;
    }
    std::vector<WellColumnData> wells;
    for (const Json& w : *wells_json) {
        WellColumnData column;
        column.name = w.value("name", std::string());
        if (column.name.empty()) continue;
        if (w.contains("curves") && w.at("curves").is_array()) {
            for (const Json& c : w.at("curves")) {
                WellCurve curve;
                curve.name = c.value("name", std::string());
                curve.depths = read_nums(c.at("depths"));
                curve.values = read_nums(c.at("values"));
                if (!curve.name.empty() &&
                    curve.depths.size() == curve.values.size()) {
                    column.curves.push_back(std::move(curve));
                }
            }
        }
        wells.push_back(std::move(column));
    }
    if (wells.empty()) {
        if (error != nullptr) *error = tr("井数据为空");
        return false;
    }
    wells_ = std::move(wells);
    last_wells_path_ = QFileInfo(path).absoluteFilePath();
    last_las_paths_.clear();
    canvas_->set_wells(wells_);
    tie_well_selector_->clear();
    for (const WellColumnData& well : wells_) {
        tie_well_selector_->addItem(QString::fromStdString(well.name));
    }
    // Cache the well coordinates for the section planner.
    well_coords_cache_ = Json::array();
    for (const Json& w : *wells_json) {
        if (w.contains("lng") && w.contains("lat")) {
            well_coords_cache_.push_back(
                Json::object({{"name", w.value("name", std::string())},
                              {"lng", w.value("lng", 0.0)},
                              {"lat", w.value("lat", 0.0)}}));
        }
    }
    register_well_identities();
    update_source_label();
    emit status_message(
        tr("已加载 %1 口井").arg(static_cast<int>(wells_.size())));
    return true;
}

bool VizBCrossWellDock::load_wells_from_las(const QStringList& paths,
                                            QString* error) {
    if (paths.isEmpty()) {
        if (error != nullptr) *error = tr("未选择 LAS 文件");
        return false;
    }
#if defined(PWB_WITH_VIZ_B_LAS)
    const auto result = pwb::app::load_wells_from_las(
        paths, pwb::ui_workers::make_wle_load_fn());
    if (result.wells.empty()) {
        if (error != nullptr) {
            *error = result.errors.isEmpty()
                         ? tr("LAS 井数据为空")
                         : result.errors.join(QLatin1String("; "));
        }
        return false;
    }
    wells_ = result.wells;
    last_wells_path_.clear();
    last_las_paths_.clear();
    for (const QString& path : paths) {
        last_las_paths_.append(QFileInfo(path).absoluteFilePath());
    }
    well_coords_cache_ = result.coords;  // LAS 无坐标：诚实空数组
    canvas_->set_wells(wells_);
    tie_well_selector_->clear();
    for (const WellColumnData& well : wells_) {
        tie_well_selector_->addItem(QString::fromStdString(well.name));
    }
    register_well_identities();
    update_source_label();
    QString status = tr("已从 LAS 加载 %1 口井")
                         .arg(static_cast<int>(wells_.size()));
    if (!result.errors.isEmpty()) {
        status += QStringLiteral("；") + result.errors.join(
                                               QLatin1String("; "));
    }
    emit status_message(status);
    return true;
#else
    // WLE 解析桥未参与本构建：诚实不可用，不伪造加载。
    Q_UNUSED(paths);
    if (error != nullptr) {
        *error = tr("LAS 解析内核未接入本构建（WLE 桥缺失）");
    }
    emit status_message(tr("LAS 解析内核未接入本构建"));
    return false;
#endif
}

void VizBCrossWellDock::on_load_las() {
    const QStringList paths = QFileDialog::getOpenFileNames(
        this, tr("加载井数据（LAS）"), QString(),
        tr("Well LAS (*.las);;All files (*.*)"));
    if (paths.isEmpty()) return;
    QString error;
    if (!load_wells_from_las(paths, &error)) {
        QMessageBox::warning(this, tr("加载失败"), error);
    }
}

void VizBCrossWellDock::register_well_identities() {
    // 共享井身份（05 线）：连井页井列按名注册；同键幂等（first wins）。
    for (const WellColumnData& well : wells_) {
        (void)pwb::ui_workers::WellIdentityRegistry::instance()
            .register_well(well.name, "cross_well");
    }
}

void VizBCrossWellDock::update_source_label() {
    if (source_label_ == nullptr) return;
    QString source;
    if (!last_wells_path_.isEmpty()) {
        source = tr("井数据来源：JSON %1 ｜ %2 口井")
                     .arg(last_wells_path_)
                     .arg(static_cast<int>(wells_.size()));
    } else if (!last_las_paths_.isEmpty()) {
        source = tr("井数据来源：LAS %1 个文件 ｜ %2 口井")
                     .arg(last_las_paths_.size())
                     .arg(static_cast<int>(wells_.size()));
    } else {
        source = tr("井数据来源：未加载");
    }
    source_label_->setText(last_result_note_.isEmpty()
                               ? source
                               : source + QStringLiteral(" ｜ ") +
                                     last_result_note_);
}

bool VizBCrossWellDock::load_tops_csv(const QString& path, QString* error) {
    if (!tops_model_.load_csv(path.toStdString())) {
        if (error != nullptr) *error = tr("无法读取分层 CSV");
        return false;
    }
    emit status_message(tr("已加载分层"));
    return true;
}

bool VizBCrossWellDock::load_checkshot_csv(const QString& path,
                                           QString* error) {
    if (!tie_.load_csv(path.toStdString())) {
        if (error != nullptr) *error = tr("无法读取校准表 CSV");
        return false;
    }
    canvas_->set_seismic_tie(tie_);
    emit status_message(tr("已加载校准表（%1 口井）")
                            .arg(static_cast<int>(
                                tie_.well_names().size())));
    return true;
}

void VizBCrossWellDock::on_load_wells() {
    const QString path = QFileDialog::getOpenFileName(
        this, tr("加载井数据（JSON）"), QString(), tr("Well JSON (*.json)"));
    if (path.isEmpty()) return;
    QString error;
    if (!load_wells_from_json(path, &error)) {
        QMessageBox::warning(this, tr("加载失败"), error);
    }
}

void VizBCrossWellDock::on_load_tops() {
    const QString path = QFileDialog::getOpenFileName(
        this, tr("加载分层（CSV）"), QString(), tr("Tops CSV (*.csv)"));
    if (path.isEmpty()) return;
    QString error;
    if (!load_tops_csv(path, &error)) {
        QMessageBox::warning(this, tr("加载失败"), error);
    }
}

void VizBCrossWellDock::on_load_checkshot() {
    const QString path = QFileDialog::getOpenFileName(
        this, tr("加载时深校准表（CSV）"), QString(), tr("CSV (*.csv)"));
    if (path.isEmpty()) return;
    QString error;
    if (!load_checkshot_csv(path, &error)) {
        QMessageBox::warning(this, tr("加载失败"), error);
    }
}

void VizBCrossWellDock::on_auto_arrange() {
    if (wells_.size() <= 2) {
        emit status_message(tr("井数 ≤2，无需排列"));
        return;
    }
    std::vector<WellCoord> coords;
    // Coordinates come from the well store when present; otherwise the
    // display order stands (planner needs real coordinates to be
    // meaningful — honest no-op without them).
    if (well_coords_cache_.is_array()) {
        for (const Json& w : well_coords_cache_) {
            coords.push_back({w.value("name", std::string()),
                              w.value("lng", 0.0), w.value("lat", 0.0)});
        }
    }
    if (coords.size() != wells_.size()) {
        emit status_message(tr("井位坐标缺失，保持当前排列"));
        return;
    }
    try {
        const auto order =
            pwb::viz::cross_well::plan_section(coords, "pca");
        std::vector<WellColumnData> arranged;
        arranged.reserve(order.size());
        for (std::size_t index : order) {
            arranged.push_back(wells_[index]);
        }
        wells_ = std::move(arranged);
        canvas_->set_wells(wells_);
        emit status_message(tr("剖面已按 PCA 主轴排列"));
    } catch (const pwb::viz::cross_well::PlannerError& exc) {
        emit status_message(QString::fromStdString(exc.what()));
    }
}

void VizBCrossWellDock::on_propagate_dtw() {
    if (wells_.empty()) {
        emit status_message(tr("先加载井数据"));
        return;
    }
    if (job_center_ == nullptr) {
        emit status_message(tr("作业中心不可用"));
        return;
    }
    // Reference = the most recent pick on the first well (or view top).
    double ref_depth = 0.5 * (canvas_->build_scene().view.depth_top +
                              canvas_->build_scene().view.depth_bottom);
    std::string formation = "DTW-Horizon";
    const std::string ref_well = wells_.front().name;
    const auto recent = picks_model_.picks_for_well(ref_well);
    if (!recent.empty()) {
        const auto* pick = recent.back();
        if (pick->depth_for_well(ref_well).has_value()) {
            ref_depth = *pick->depth_for_well(ref_well);
            formation = pick->formation_name;
        }
    }
    // Scene slice from the display curves (extract GR-preferred).
    pwb::ui_workers::DtwSceneSlice scene;
    const std::vector<std::string> preferred = {"GR", "SP", "RT"};
    std::size_t max_samples = 0;
    for (const WellColumnData& well : wells_) {
        pwb::ui_workers::DtwWellSlice slice;
        slice.name = well.name;
        if (auto curve = pwb::viz::cross_well::extract_curve(well.curves,
                                                            preferred)) {
            slice.depths = curve->depths;
            slice.values = curve->values;
            max_samples = std::max(max_samples, curve->values.size());
        }
        scene.wells.push_back(std::move(slice));
    }
    if (max_samples < 2) {
        emit status_message(tr("无可用的对比曲线"));
        return;
    }

    auto* progress = new QProgressDialog(tr("DTW 拾取传播…"), tr("取消"), 0,
                                         100, this);
    progress->setWindowModality(Qt::WindowModal);
    progress->setMinimumDuration(0);
    progress->setValue(1);
    const std::uint64_t generation = session_generation_;
    const std::string formation_copy = formation;

    pwb::ui_workers::DtwPropagationInput input;
    input.scene = std::move(scene);
    input.ref_well = ref_well;
    input.ref_depth = ref_depth;
    input.formation = formation;
    // The largest curve length drives the engine band max(20, n/4)
    // (Python worker contract).
    input.n_samples = static_cast<int>(max_samples);
    input.band_radius = std::nullopt;
    // NOTE: spec.on_done/on_fail/on_cancel are left EMPTY on purpose —
    // they run on the WORKER thread (job_bridge contract). All GUI work
    // (dialog teardown, generation check, picks apply) happens in the
    // queued on_finished below (submitSegyJob pattern).
    auto spec = pwb::ui_workers::make_dtw_propagation_job_spec(
        std::move(input));

    // A fresh owner per submission: JobOwner::start throws when the
    // owner already runs a job (single-job-per-owner contract).
    auto& owner = job_center_->make_owner(this);
    QObject::connect(progress, &QProgressDialog::canceled, &owner,
                     &pwb::job::qtbridge::JobOwner::cancel);
    owner.start(
        job_center_->scheduler(), std::move(spec),
        [this, generation, formation_copy, progress](
            const pwb::job::qtbridge::JobOutcome& outcome) {
            // Queued to the GUI thread; the released guard already
            // dropped this delivery if the dock is gone.
            progress->deleteLater();
            if (generation != session_generation_) {
                return;  // project switched/closed in flight — dropped
            }
            if (outcome.state == pwb::job::JobState::cancelled) {
                emit status_message(tr("DTW 传播已取消"));
                return;
            }
            if (outcome.state == pwb::job::JobState::failed) {
                QMessageBox::warning(
                    nullptr, tr("DTW 传播"),
                    QString::fromStdString(outcome.error));
                return;
            }
            const auto* result = std::any_cast<
                pwb::ui_workers::DtwPropagationResult>(&outcome.result);
            if (result == nullptr) {
                emit status_message(tr("DTW 传播结果类型异常"));
                return;
            }
            apply_dtw_results(result->pairs, formation_copy);
            emit status_message(tr("DTW 传播完成：%1 个拾取").arg(
                static_cast<int>(result->pairs.size())));
        },
        [progress](double ratio, const QString&) {
            progress->setValue(std::max(1, static_cast<int>(ratio * 100.0)));
        });
}

void VizBCrossWellDock::apply_dtw_results(
    const std::vector<std::pair<std::string, double>>& pairs,
    const std::string& formation) {
    for (const auto& [well, depth] : pairs) {
        // 返回的 pick id 仅供模型内部键控；UI 刷新走 changed-handler，
        // 此处显式丢弃。
        (void)picks_model_.add_dtw_pick(formation, well, depth,
                                        pwb::viz::cross_well::PickConfidence{});
    }
    // 05 线：结果来源显示——产出引擎与来源会话可追溯。
    last_result_note_ = tr("最近结果：DTW 传播（banded 引擎，会话代际 %1）"
                           "为层位「%2」产出 %3 个拾取")
                           .arg(session_generation_)
                           .arg(QString::fromStdString(formation))
                           .arg(static_cast<int>(pairs.size()));
    update_source_label();
}

void VizBCrossWellDock::on_edit_links() {
    // Build the draft from the picks model (real model binding —
    // UI-09's CorrelationDraftSlice is the editor's contract).
    pwb::ui_wellseis::CorrelationDraftSlice draft;
    for (const auto* pick : picks_model_.all_picks()) {
        for (const auto& [well, depth] : pick->well_depths) {
            if (!depth.has_value()) continue;
            pwb::ui_wellseis::CorrelationTopSlice top;
            top.id = top_id(pick->pick_id, well);
            top.well_name = well;
            top.marker = pick->formation_name;
            top.depth = *depth;
            top.method = pick->source == "dtw" ? "DTW_ASSISTED" : "MANUAL";
            top.depth_domain = "MD";
            const std::string key = top.id;
            if (top_meta_.contains(key)) {
                const Json& meta = top_meta_.at(key);
                top.status = meta.value("status", std::string("active"));
                top.confidence = meta.value("confidence", std::string());
                top.notes = meta.value("notes", std::string());
            }
            draft.tops.push_back(std::move(top));
        }
    }
    if (draft.tops.empty()) {
        emit status_message(tr("无拾取可编辑"));
        return;
    }
    // Pre-seed links from the model's connectivity (adjacent pairs in
    // each pick's connection order).
    std::size_t link_n = 0;
    for (const auto* pick : picks_model_.all_picks()) {
        const std::vector<std::string> connected = pick->connected_wells();
        for (std::size_t i = 0; i + 1 < connected.size(); ++i) {
            pwb::ui_wellseis::CorrelationLinkSlice link;
            link.id = "link:" + std::to_string(link_n++);
            link.top_a_id = top_id(pick->pick_id, connected[i]);
            link.top_b_id = top_id(pick->pick_id, connected[i + 1]);
            link.method = "MANUAL";
            link.adjacent_only = true;
            draft.links.push_back(std::move(link));
        }
    }
    pwb::ui_wellseis::qt::CorrelationEditorHooks hooks;
    hooks.new_link_id = [&link_n](const pwb::ui_wellseis::
                                      CorrelationDraftSlice&) {
        return "link:" + std::to_string(link_n++);
    };
    const pwb::ui_wellseis::CorrelationDraftSlice before = draft;
    const int generation_before = draft.generation;
    pwb::ui_wellseis::qt::run_link_editor(
        this, draft, hooks, [this]() { schedule_persistence(); });
    if (draft.generation == generation_before) {
        return;  // untouched
    }
    // Write the editor's mutations back into the picks model (the
    // real binding — see docs/development/cpp-viz-b/scope.md).
    const auto find_pick_id = [](const std::string& id) {
        std::string pick_id;
        std::string well;
        split_top_id(id, pick_id, well);
        return std::pair{pick_id, well};
    };
    // Status / confidence / notes edits.
    for (const auto& top : draft.tops) {
        const auto [pick_id, well] = find_pick_id(top.id);
        Json meta = Json::object({{"status", top.status},
                                  {"confidence", top.confidence},
                                  {"notes", top.notes}});
        top_meta_[top.id] = std::move(meta);
        if (top.status == "rejected") {
            picks_model_.disconnect_pick(pick_id, well);
        }
        // Map the editor's method back onto the pick source (accepting
        // a DTW-suggested pick promotes it; MANUAL keeps it manual).
        if (top.method == "MANUAL") {
            picks_model_.accept_dtw_pick(pick_id);
        }
    }
    // Link adds between different picks merge them; link removes
    // disconnect that well on the pick.
    auto top_depth = [&draft](const std::string& id) {
        for (const auto& t : draft.tops) {
            if (t.id == id) return std::optional<double>(t.depth);
        }
        return std::optional<double>();
    };
    auto top_well = [&draft](const std::string& id) {
        for (const auto& t : draft.tops) {
            if (t.id == id) return t.well_name;
        }
        return std::string();
    };
    for (const auto& link : draft.links) {
        const auto [pick_a, well_a] = find_pick_id(link.top_a_id);
        const auto [pick_b, well_b] = find_pick_id(link.top_b_id);
        if (pick_a != pick_b && !pick_b.empty()) {
            // Cross-pick link: extend pick_a to pick_b's well at its
            // depth (merge semantics).
            const std::optional<double> depth_b = top_depth(link.top_b_id);
            if (depth_b.has_value()) {
                picks_model_.connect_picks(pick_a, top_well(link.top_b_id),
                                           *depth_b);
            }
        }
    }
    // Removals relative to the pre-dialog link set.
    for (const auto& old : before.links) {
        bool still_there = false;
        for (const auto& link : draft.links) {
            if (link.top_a_id == old.top_a_id &&
                link.top_b_id == old.top_b_id) {
                still_there = true;
                break;
            }
        }
        if (still_there) continue;
        const auto [pick_id, well] = find_pick_id(old.top_b_id);
        picks_model_.disconnect_pick(pick_id, well);
    }
    links_json_ = Json::array();
    for (const auto& link : draft.links) {
        links_json_.push_back(Json::object(
            {{"id", link.id},
             {"top_a_id", link.top_a_id},
             {"top_b_id", link.top_b_id},
             {"method", link.method},
             {"adjacent_only", link.adjacent_only},
             {"notes", link.notes}}));
    }
    schedule_persistence();
}

void VizBCrossWellDock::on_export_section() {
    if (wells_.empty()) {
        emit status_message(tr("无剖面可导出"));
        return;
    }
    pwb::ui_wellseis::qt::CrossWellExportDialog dialog(this);
    if (dialog.exec() != QDialog::Accepted) return;
    const pwb::ui_wellseis::ResolvedExportOptions options = dialog.options();
    const QString path = QFileDialog::getSaveFileName(
        this, tr("导出剖面"), QString(),
        tr("Images/PDF (*.%1)").arg(
            QString::fromStdString(options.fmt)));
    if (path.isEmpty()) return;
    const bool ok = pwb::viz::cross_well::qt::export_section_composite(
        canvas_->build_scene(), path,
        QString::fromStdString(options.fmt), options.dpi, options.width_px,
        options.page_size.has_value()
            ? std::optional<QString>(QString::fromStdString(
                  *options.page_size))
            : std::nullopt);
    emit status_message(ok ? tr("剖面已导出：%1").arg(path)
                           : tr("导出失败"));
}

void VizBCrossWellDock::on_export_report() {
    if (wells_.empty()) {
        emit status_message(tr("无报告可导出"));
        return;
    }
    const QString path = QFileDialog::getSaveFileName(
        this, tr("导出报告"), QString(), tr("PDF (*.pdf);;PNG (*.png)"));
    if (path.isEmpty()) return;
    pwb::viz::cross_well::qt::CrossWellReportOptions options;
    options.dpi = 150;
    const bool ok = pwb::viz::cross_well::qt::export_cross_well_report(
        canvas_->build_scene(), path, options);
    emit status_message(ok ? tr("报告已导出：%1").arg(path)
                           : tr("报告导出失败"));
}

void VizBCrossWellDock::on_well_tie_well_changed() {
    const QString name = tie_well_selector_->currentText();
    if (name.isEmpty()) {
        tie_readout_->setText(tr("未选择井"));
        return;
    }
    const WellColumnData* selected = nullptr;
    for (const WellColumnData& well : wells_) {
        if (QString::fromStdString(well.name) == name) {
            selected = &well;
            break;
        }
    }
    if (selected == nullptr) return;
    std::vector<double> depths;
    std::vector<double> sonic;
    std::vector<double> density;
    for (const WellCurve& curve : selected->curves) {
        const std::string upper = [&curve] {
            std::string out;
            for (unsigned char c : curve.name) {
                out.push_back(static_cast<char>(std::toupper(c)));
            }
            return out;
        }();
        if (upper == "AC" || upper == "DT") {
            depths = curve.depths;
            sonic = curve.values;
        } else if (upper == "DEN" || upper == "RHOB") {
            density = curve.values;
        }
    }
    if (depths.size() != density.size() || sonic.size() != depths.size()) {
        tie_readout_->setText(
            tr("井 %1 缺少声波/密度曲线（AC+DEN），标定不可用")
                .arg(name));
        tie_canvas_->set_tie_data({}, {}, {}, {}, {});
        return;
    }
    // Integrated TWT from the sonic (from_sonic masks NaN pairs).
    std::vector<double> twt;
    std::vector<double> masked_depths;
    try {
        const auto calibration =
            pwb::viz::well_tie::WellTieCalibration::from_sonic(depths,
                                                                sonic);
        twt = calibration.twt();
        // from_sonic masks non-finite pairs — pass the SAME shortened
        // depth axis so the canvas lengths always match.
        masked_depths = calibration.depths();
    } catch (const std::invalid_argument&) {
        tie_readout_->setText(tr("声波样本不足，无法积分时深"));
        tie_canvas_->set_tie_data({}, {}, {}, {}, {});
        return;
    }
    // Synthetic trace on the sonic grid (canonical kernel).
    const auto synthetic = pwb::viz::well_tie::synthetic_from_logs(
        sonic, density);
    std::vector<double> seismic(synthetic.begin(), synthetic.end());
    tie_canvas_->set_tie_data(masked_depths, twt, sonic, density,
                              seismic);
    tie_readout_->setText(
        tr("井 %1：R = %2，lag = %3 ms（合成记录初算）")
            .arg(name)
            .arg(tie_canvas_->correlation_r(), 0, 'f', 3)
            .arg(tie_canvas_->lag_ms(), 0, 'f', 1));
}

void VizBCrossWellDock::on_export_tie_report() {
    const QString name = tie_well_selector_->currentText();
    if (name.isEmpty() || tie_canvas_->sample_count() == 0) {
        emit status_message(tr("无可导出的标定结果"));
        return;
    }
    const QString path = QFileDialog::getSaveFileName(
        this, tr("导出标定报告"), QString(), tr("PDF (*.pdf);;SVG (*.svg)"));
    if (path.isEmpty()) return;
    WellTieReportInputs inputs;
    inputs.well_name = name;
    inputs.block = QStringLiteral("—");
    inputs.horizon = QStringLiteral("—");
    inputs.wavelet = QStringLiteral("Ricker 30 Hz");
    inputs.r_score = tie_canvas_->correlation_r();
    inputs.lag_ms = tie_canvas_->lag_ms();
    const bool ok = export_well_tie_report(inputs, path);
    emit status_message(ok ? tr("标定报告已导出：%1").arg(path)
                           : tr("标定报告导出失败"));
}

void VizBCrossWellDock::on_picks_changed() {
    canvas_->update();
    schedule_persistence();
}

void VizBCrossWellDock::schedule_persistence() {
    // Coalesced sidecar write (300 ms) — never a catalog write, never a
    // write after handle_project_closed cleared the directory.
    persist_dirty_ = true;
    if (persist_timer_ != nullptr && !persist_timer_->isActive()) {
        persist_timer_->start();
    }
}

void VizBCrossWellDock::set_project_directory(const QString& directory) {
    project_directory_ = directory;
}

void VizBCrossWellDock::persist_now() {
    if (project_directory_.isEmpty()) {
        persist_dirty_ = false;
        return;
    }
    const QString path =
        project_directory_ + QStringLiteral("/cross_well_workspace.json");
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        emit status_message(tr("连井工作区保存失败：%1").arg(path));
        return;  // dirty stays set — retried on the next coalesced tick
    }
    const QByteArray text =
        QByteArray::fromStdString(save_state().dump(2));
    file.write(text);
    file.flush();
    persist_dirty_ = false;
}

void VizBCrossWellDock::restore_from_project() {
    if (project_directory_.isEmpty()) return;
    const QString path =
        project_directory_ + QStringLiteral("/cross_well_workspace.json");
    QFile file(path);
    if (!file.exists()) {
        // 05 线：新工程无 sidecar → 清空工作区（跨工程切换不串扰）。
        reset_workspace();
        emit status_message(tr("新工程无连井工作区，已重置"));
        return;
    }
    if (!file.open(QIODevice::ReadOnly)) return;
    try {
        restore_state(Json::parse(file.readAll().toStdString()));
        emit status_message(tr("已恢复连井工作区"));
    } catch (const std::exception&) {
        emit status_message(tr("连井工作区损坏，忽略"));
    }
}

void VizBCrossWellDock::reset_workspace() {
    ++session_generation_;  // 在途结果一并作废
    wells_.clear();
    last_wells_path_.clear();
    last_las_paths_.clear();
    well_coords_cache_ = Json::array();
    picks_model_.from_json(Json::object({{"picks", Json::array()}}));
    tops_model_.clear();
    links_json_ = Json::array();
    top_meta_ = Json::object();
    last_result_note_.clear();
    if (tie_well_selector_ != nullptr) tie_well_selector_->clear();
    if (canvas_ != nullptr) {
        canvas_->set_wells(wells_);
        canvas_->update();
    }
    if (preview_ != nullptr) preview_->set_tops(tops_model_.all_tops());
    update_source_label();
}

Json VizBCrossWellDock::save_state() const {
    Json state = Json::object();
    state["picks"] = picks_model_.to_json();
    Json tops = Json::array();
    for (const FormationTop& top : tops_model_.all_tops()) {
        tops.push_back(Json::object({{"well", top.well_name},
                                     {"formation", top.formation_name},
                                     {"depth_m", top.depth_m},
                                     {"color", top.color}}));
    }
    state["tops"] = std::move(tops);
    state["links"] = links_json_;
    state["top_meta"] = top_meta_;
    const auto scene = canvas_->build_scene();
    state["view"] = Json::object({{"depth_top", scene.view.depth_top},
                                  {"depth_bottom", scene.view.depth_bottom},
                                  {"depth_domain", scene.depth_domain}});
    if (!last_wells_path_.isEmpty()) {
        state["well_source"] = last_wells_path_.toStdString();
    }
    if (!last_las_paths_.isEmpty()) {
        // 05 线：LAS 来源（重开会话自动重载；与 JSON 来源互斥，后设者
        // 生效——加载函数已互斥清零对方）。
        Json las = Json::array();
        for (const QString& path : last_las_paths_) {
            las.push_back(path.toStdString());
        }
        state["well_source_las"] = std::move(las);
    }
    return state;
}

void VizBCrossWellDock::restore_state(const Json& state) {
    if (!state.is_object()) return;
    ++session_generation_;  // drop any in-flight DTW results
    if (state.contains("picks")) {
        picks_model_.from_json(state.at("picks"));
    }
    if (state.contains("tops") && state.at("tops").is_array()) {
        tops_model_.clear();
        for (const Json& t : state.at("tops")) {
            FormationTop top{t.value("well", std::string()),
                             t.value("formation", std::string()),
                             t.value("depth_m", 0.0),
                             t.value("color", std::string())};
            tops_model_.add_top(std::move(top));
        }
    }
    if (state.contains("links") && state.at("links").is_array()) {
        links_json_ = state.at("links");
    }
    if (state.contains("well_source") &&
        state.at("well_source").is_string()) {
        const QString source = QString::fromStdString(
            state.at("well_source").get<std::string>());
        if (QFile::exists(source)) {
            QString error;
            load_wells_from_json(source, &error);
        }
    }
    if (state.contains("well_source_las") &&
        state.at("well_source_las").is_array()) {
        // 05 线：LAS 来源重开重载（同生产 seam；失败诚实降级为无井，
        // 不清空已恢复的 picks/tops——拾取仍可审计）。
        QStringList paths;
        for (const Json& p : state.at("well_source_las")) {
            if (p.is_string()) {
                const QString path = QString::fromStdString(p.get<std::string>());
                if (QFile::exists(path)) paths.append(path);
            }
        }
        if (!paths.isEmpty()) {
            QString error;
            load_wells_from_las(paths, &error);
        }
    }
    if (state.contains("top_meta") && state.at("top_meta").is_object()) {
        top_meta_ = state.at("top_meta");
    }
    canvas_->update();
    preview_->set_tops(tops_model_.all_tops());
}

void VizBCrossWellDock::handle_project_closed() {
    ++session_generation_;
    persist_now();
    project_directory_.clear();
}

}  // namespace pwb::app
