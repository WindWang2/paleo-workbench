// VIZ-E — data/preview page assembly implementation (plan P-A + V6).
// See viz_e_install.hpp for the composition contract.
#include "viz_e_install.hpp"

#include "job_center.hpp"
#include "viz_e_dat_preview.hpp"
#include "viz_e_factor_preview.hpp"

#include <pwb/ui_pages_data/asset_view.hpp>
#include <pwb/ui_pages_data/preview_dispatch.hpp>
#include <pwb/ui_pages_data/qt/data_asset_table.hpp>
#include <pwb/ui_pages_data/qt/data_reader_panel.hpp>
#include <pwb/ui_pages_data/qt/data_workspace.hpp>


#include <pwb/job_runtime/qt/job_bridge.hpp>

#include <QDockWidget>
#include <QLabel>
#include <QVBoxLayout>

#include <atomic>
#include <mutex>
#include <optional>

class MainWindow;

namespace pwb::viz_e {
namespace updqt = ::pwb::ui_pages_data::qt;
namespace {

class MainWindow;

// ---------------------------------------------------------------------------
// External presenter registry (process-wide; A/B/D registration contract)
// ---------------------------------------------------------------------------
struct Registry {
    std::mutex mutex;
    std::vector<ExternalPresenter> entries;
};

Registry& registry() {
    static Registry instance;
    return instance;
}

QString asset_path_of(const pwb::ui_pages_data::AssetRow& row) {
    return QString::fromStdString(row.view.path);
}

}  // namespace

bool register_external_presenter(ExternalPresenter presenter) {
    if (presenter.kind.empty() || !presenter.supports || !presenter.create) {
        return false;
    }
    auto& reg = registry();
    std::lock_guard<std::mutex> lock(reg.mutex);
    for (const auto& existing : reg.entries) {
        if (existing.kind == presenter.kind) {
            return false;  // first registration wins; a second is a wiring bug
        }
    }
    reg.entries.push_back(std::move(presenter));
    return true;
}

std::vector<PresenterStatus> registered_presenters() {
    auto& reg = registry();
    std::lock_guard<std::mutex> lock(reg.mutex);
    std::vector<PresenterStatus> out;
    out.reserve(reg.entries.size());
    for (const auto& entry : reg.entries) {
        out.push_back({entry.kind, entry.note});
    }
    return out;
}

void reset_external_presenters_for_tests() {
    auto& reg = registry();
    std::lock_guard<std::mutex> lock(reg.mutex);
    reg.entries.clear();
}

// ---------------------------------------------------------------------------
// VizEDataPage
// ---------------------------------------------------------------------------

VizEDataPage::VizEDataPage(QWidget* parent, pwb::app::JobCenter* jobs)
    : QWidget(parent), jobs_(jobs),
      alive_(std::make_shared<std::atomic<bool>>(true)) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    workspace_ = new updqt::DataWorkspace(this);
    layout->addWidget(workspace_, 1);

    xy_host_ = new XyScatterHost(this);
    surface_host_ = new SurfaceHost(this);

    // Chart hosts join the reader panel through the EXISTING target/hook
    // seams (preview_dispatch maps "xy_scatter"→"xy_scatter_chart",
    // "surface"→"surface_chart").
    updqt::DataReaderPanel* reader = workspace_->reader_panel();
    reader->register_target(QStringLiteral("xy_scatter_chart"), xy_host_);
    reader->register_target(QStringLiteral("surface_chart"), surface_host_);

    connect(workspace_->asset_table(),
            &updqt::DataAssetTable::selected_asset_changed, this,
            &VizEDataPage::on_selected_asset);
}

VizEDataPage::~VizEDataPage() {
    alive_->store(false);  // in-flight deliveries drop instead of UAF
}

void VizEDataPage::set_asset_rows(
    const std::vector<pwb::ui_pages_data::AssetRow>& rows) {
    workspace_->asset_table()->update_assets(rows);
}

void VizEDataPage::on_selected_asset(
    const std::optional<pwb::ui_pages_data::AssetRow>& asset) {
    if (!asset.has_value()) {
        return;
    }
    preview_asset(*asset);
}

void VizEDataPage::preview_asset(
    const pwb::ui_pages_data::AssetRow& row) {
    const QString path = asset_path_of(row);
    if (path.isEmpty()) {
        show_unavailable(QStringLiteral("资产没有可解析的路径"));
        return;
    }

    // 1) External presenters first (A/B/D contract): the first registered
    //    presenter that supports the asset presents it.
    if (QWidget* presented = try_external_presenter(path); presented != nullptr) {
        return;
    }

    // 2) Built-in chart-capable .dat previews (real parsing port).
    const std::string path_std = path.toStdString();
    if (pwb::viz_e::well_head_supported(path_std)) {
        present_well_head(path, row.view.id);
        return;
    }
    if (pwb::viz_e::horizon_supported(path_std)) {
        present_horizon(path, row.view.id,
                        QString::fromStdString(row.view.name));
        return;
    }

    // 3) Honest unavailable with the dependency state (never a fake
    //    success preview).
    QString reason = QStringLiteral(
        "该资产类型暂无原生预览（格式: %1）")
                         .arg(QString::fromStdString(row.view.format));
    const auto presenters = registered_presenters();
    if (!presenters.empty()) {
        QStringList lines;
        for (const auto& p : presenters) {
            lines << QString::fromStdString(
                p.kind + ": " + p.note);
        }
        reason += QStringLiteral("\n已注册外部预览: ") + lines.join("; ");
    } else {
        reason += QStringLiteral(
            "\n井日志(.las)/时深/地震预览由并行批次提供，尚未合入。");
    }
    show_unavailable(reason);
}

QWidget* VizEDataPage::try_external_presenter(const QString& path) {
    // Snapshot under the lock, invoke user code outside it: presenter
    // callbacks may register presenters (non-recursive mutex) or block on
    // file IO.
    std::vector<ExternalPresenter> entries;
    {
        auto& reg = registry();
        std::lock_guard<std::mutex> lock(reg.mutex);
        entries = reg.entries;
    }
    for (auto& entry : entries) {
        if (entry.supports(path)) {
            QWidget* widget = entry.create(path, this);
            if (widget == nullptr) {
                continue;  // presenter declined at build time — next one
            }
            active_target_ = QString::fromStdString(entry.kind);
            updqt::PreviewResultView result;
            result.mode = entry.kind;
            result.title = path.toStdString();
            result.path = path.toStdString();
            auto* reader = workspace_->reader_panel();
            reader->register_target(
                QString::fromStdString(
                    std::string(pwb::ui_pages_data::preview_target(entry.kind))),
                widget);
            reader->render(result);
            Q_EMIT preview_rendered(active_target_);
            return widget;
        }
    }
    return nullptr;
}

void VizEDataPage::present_well_head(const QString& path,
                                     const std::string& asset_id) {
    try {
        const pwb::viz_e::WellHeadPreview data =
            pwb::viz_e::parse_well_head(path.toStdString());
        xy_host_->show_well_head(
            data, QString::fromStdString(asset_id.empty() ? path.toStdString() : asset_id));
        active_target_ = QStringLiteral("xy_scatter");
        updqt::PreviewResultView result;
        result.mode = "xy_scatter";
        result.title = path.toStdString();
        result.path = path.toStdString();
        workspace_->reader_panel()->render(result);
        Q_EMIT preview_rendered(active_target_);
        return;
    } catch (const std::exception& error) {
        show_unavailable(QString::fromUtf8(error.what()));
    }
}

void VizEDataPage::present_horizon(const QString& path,
                                   const std::string& asset_id,
                                   const QString& asset_name) {
    if (jobs_ == nullptr) {
        show_unavailable(QStringLiteral("任务运行时不可用，无法计算曲面"));
        return;
    }
    pwb::viz_e::HorizonPoints points;
    try {
        points = pwb::viz_e::parse_horizon_points(path.toStdString());
    } catch (const std::exception& error) {
        show_unavailable(QString::fromUtf8(error.what()));
        return;
    }
    if (points.x.empty()) {
        show_unavailable(QStringLiteral("horizon 数据没有有效点"));
        return;
    }

    // Cancel any in-flight surface job; a stale delivery is dropped by the
    // generation guard in deliver_surface().
    surface_host_->show_unavailable(QStringLiteral("正在计算曲面…"));
    active_target_ = QStringLiteral("surface");
    const std::uint64_t generation = ++surface_generation_;

    FactorPreviewRequest request;
    request.asset_path = path.toStdString();
    request.asset_id = asset_id;
    request.factor_name =
        (asset_name.isEmpty() ? QStringLiteral("horizon") : asset_name)
            .toStdString();
    request.method = "idw";
    request.grid_n = pwb::viz_e::horizon_grid_resolution(points);
    request.crs = points.source_crs;      // declared only, never inferred
    request.unit = points.coordinate_units;
    request.samples.reserve(points.x.size());
    for (std::size_t i = 0; i < points.x.size(); ++i) {
        request.samples.push_back(
            {points.x[i], points.y[i], points.z[i], "ok"});
    }

    // One JobOwner per request: JobOwner refuses a second concurrent
    // start, and repeated previews must not serialize behind a cancelling
    // job. NO QObject parent — JobCenter's unique_ptr already owns the
    // owner, and a parent here would double-delete whenever this page dies
    // before the JobCenter (the owner still delivers to this GUI thread,
    // which is where make_owner runs).
    pwb::job::qtbridge::JobOwner& owner = jobs_->make_owner(nullptr);
    pwb::job::JobSpec spec;
    spec.kind = "compute.viz_e.surface_preview";
    spec.title = "曲面预览插值";
    spec.task_key = "viz_e.surface_preview";
    spec.run = [request](pwb::job::JobContext& ctx) -> std::any {
        return compute_factor_preview(request, ctx);
    };
    const std::shared_ptr<std::atomic<bool>> alive = alive_;
    owner.start(jobs_->scheduler(), std::move(spec),
                 [this, alive, generation](
                     const pwb::job::qtbridge::JobOutcome& o) {
                     if (!alive->load()) {
                         return;  // page died mid-flight — drop the delivery
                     }
                     if (o.state == pwb::job::JobState::done ||
                         o.state == pwb::job::JobState::degraded) {
                         const FactorPreviewOutcome* outcome =
                             std::any_cast<FactorPreviewOutcome>(&o.result);
                         if (outcome != nullptr) {
                             deliver_surface(generation, *outcome);
                         } else {
                             deliver_surface(
                                 generation,
                                 FactorPreviewOutcome{});
                         }
                     } else if (o.state == pwb::job::JobState::cancelled) {
                         if (generation == surface_generation_) {
                             surface_host_->show_unavailable(
                                 QStringLiteral("曲面计算已取消"));
                         }
                     } else {
                         if (generation == surface_generation_) {
                             surface_host_->show_unavailable(
                                 QStringLiteral("曲面计算失败: %1")
                                     .arg(QString::fromStdString(o.error)));
                             Q_EMIT preview_failed(
                                 QStringLiteral("surface"));
                         }
                     }
                 });
}

void VizEDataPage::present_factor_surface(
    const SurfaceHost::SurfaceData& data) {
    surface_host_->show_surface(data);
    active_target_ = QStringLiteral("surface");
    updqt::PreviewResultView result;
    result.mode = "surface";
    result.title = data.title.toStdString();
    result.path = data.provenance.toStdString();
    workspace_->reader_panel()->render(result);
    Q_EMIT preview_rendered(QStringLiteral("surface"));
}

void VizEDataPage::deliver_surface(
    std::uint64_t generation, const pwb::viz_e::FactorPreviewOutcome& outcome) {
    if (generation != surface_generation_) {
        return;  // stale delivery — a newer selection superseded this job
    }
    if (!outcome.ok) {
        surface_host_->show_unavailable(outcome.error);
        Q_EMIT preview_failed(QStringLiteral("surface"));
        return;
    }
    surface_host_->show_surface(outcome.data);
    updqt::PreviewResultView result;
    result.mode = "surface";
    result.title = outcome.data.title.toStdString();
    result.path = outcome.data.provenance.toStdString();
    workspace_->reader_panel()->render(result);
    Q_EMIT preview_rendered(QStringLiteral("surface"));
}

void VizEDataPage::show_unavailable(const QString& reason) {
    updqt::PreviewResultView result;
    result.mode = "message";
    result.message = reason.toStdString();
    active_target_ = QStringLiteral("message");
    workspace_->reader_panel()->render(result);
    Q_EMIT preview_failed(reason);
}

// ---------------------------------------------------------------------------
// MainWindow mount
// ---------------------------------------------------------------------------

QDockWidget* install_data_dock(QMainWindow* window,
                               pwb::app::JobCenter* jobs) {
    auto* dock = new QDockWidget(QObject::tr("数据"), window);
    dock->setObjectName(QStringLiteral("viz-e-data-dock"));
    auto* page = new VizEDataPage(dock, jobs);
    dock->setWidget(page);
    window->addDockWidget(Qt::LeftDockWidgetArea, dock);
    return dock;
}

}  // namespace pwb::viz_e
