// VIZ-E — data/preview page assembly implementation (plan P-A + V6).
// See viz_e_install.hpp for the composition contract.
#include "viz_e_install.hpp"

#include "job_center.hpp"
#include "viz_e_dat_preview.hpp"
#include "viz_e_factor_preview.hpp"

#include <pwb/ui_pages_data/asset_view.hpp>
#include <pwb/ui_pages_data/preview_dispatch.hpp>
#include <pwb/ui_pages_data/qt/asset_selection_bus.hpp>
#include <pwb/ui_pages_data/qt/data_asset_table.hpp>
#include <pwb/ui_pages_data/qt/data_reader_panel.hpp>
#include <pwb/ui_pages_data/qt/data_workspace.hpp>

#include <pwb/qgis_processing/job_compat.hpp>

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
    : VizEDataPage(parent, jobs, nullptr) {}

VizEDataPage::VizEDataPage(QWidget* parent, pwb::app::JobCenter* jobs,
                           updqt::DataWorkspace* adopted_workspace)
    : QWidget(parent), jobs_(jobs),
      alive_(std::make_shared<std::atomic<bool>>(true)) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    if (adopted_workspace != nullptr) {
        // Adopted workspace: reparent into this page's layout (the hub
        // slot it occupied was already swapped by the host).
        adopted_workspace->setParent(this);
        workspace_ = adopted_workspace;
    } else {
        workspace_ = new updqt::DataWorkspace(this);
    }
    layout->addWidget(workspace_, 1);

    xy_host_ = new XyScatterHost(this);
    surface_host_ = new SurfaceHost(this);

    // Chart hosts join the reader panel through the EXISTING target/hook
    // seams (preview_dispatch maps "xy_scatter"→"xy_scatter_chart",
    // "surface"→"surface_chart").
    updqt::DataReaderPanel* reader = workspace_->reader_panel();
    reader->register_target(QStringLiteral("xy_scatter_chart"), xy_host_);
    reader->register_target(QStringLiteral("surface_chart"), surface_host_);
    // Loading-page 取消 → cancel the in-flight preview (task-mandated
    // affordance; no-op when nothing is in flight).
    reader->set_cancel_hook([this]() { return cancel_active_preview(); });

    connect(workspace_->asset_table(),
            &updqt::DataAssetTable::selected_asset_changed, this,
            &VizEDataPage::on_selected_asset);
}

VizEDataPage::~VizEDataPage() {
    alive_->store(false);  // in-flight deliveries drop instead of UAF
}

void VizEDataPage::set_asset_rows(
    const std::vector<pwb::ui_pages_data::AssetRow>& rows) {
    if (selection_bus_ != nullptr) {
        // Rows flow through the bus (single source of truth) keeping the
        // current project identity; the bus mirrors them into the table.
        selection_bus_->set_assets(rows, selection_bus_->project_id());
        return;
    }
    workspace_->asset_table()->update_assets(rows);
}

void VizEDataPage::bind_selection_bus(updqt::AssetSelectionBus* bus) {
    if (selection_bus_ != nullptr) {
        disconnect(selection_bus_, nullptr, this, nullptr);
    }
    // The ctor's direct table path must go: with the bus bound there is
    // EXACTLY ONE preview path (bus selection changes) — leaving both
    // connected dispatches every click twice.
    disconnect(workspace_->asset_table(),
               &updqt::DataAssetTable::selected_asset_changed, this,
               &VizEDataPage::on_selected_asset);
    selection_bus_ = bus;
    if (selection_bus_ == nullptr) {
        // Restore the direct table path (unbound tests / reduced mounts).
        connect(workspace_->asset_table(),
                &updqt::DataAssetTable::selected_asset_changed, this,
                &VizEDataPage::on_selected_asset,
                Qt::UniqueConnection);
        return;
    }
    // Bus-bound: exactly one preview path (bus selection changes). The
    // workspace mirrors bus state into the table via its own binding.
    workspace_->bind_selection_bus(bus);
    connect(bus, &updqt::AssetSelectionBus::current_asset_changed, this,
            [this](const std::optional<pwb::ui_pages_data::AssetRow>&
                       asset) {
                if (asset.has_value()) {
                    preview_asset(*asset);
                    return;
                }
                // Deletion / project switch: the stale preview must go —
                // the honest empty state, never a ghost asset's payload
                // (Python preview(None) parity). No preview_rendered: the
                // signal means a real preview landed (deliver_base_preview
                // suppresses empty/message the same way).
                updqt::PreviewResultView empty;
                empty.mode = "empty";
                active_target_ = QStringLiteral("empty");
                workspace_->reader_panel()->render(empty);
            });
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
    // Fast-switch discipline: any in-flight preview is superseded. Both
    // guards bump HERE so the early-exit paths (external presenter,
    // .dat, honest unavailable) cannot be clobbered by a still-in-flight
    // base delivery; a USER cancel with no follow-up selection does not
    // bump (cancel_active_preview), so its honest 已取消 delivery lands.
    ++surface_generation_;
    ++base_generation_;
    cancel_active_preview();

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

    // 3) Parser-registry base preview (CLOSURE-PREVIEW task 04): real
    //    parse through the injected seam for the text/table/image/pdf/
    //    json/media family. Honest unavailable when the seam is absent or
    //    reports no capability — never a fabricated success.
    if (base_builder_ != nullptr) {
        present_base_preview(row);
        return;
    }

    // 4) Honest unavailable with the dependency state (never a fake
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

// --- base parser-registry preview (task 04) ----------------------------------

void VizEDataPage::set_base_preview_builder(BasePreviewFn fn) {
    base_builder_ = std::move(fn);
}

bool VizEDataPage::cancel_active_preview() {
    if (base_owner_ == nullptr) {
        return false;
    }
    base_owner_->cancel();  // cooperative; the job lands the cancelled state
    base_owner_ = nullptr;  // the delivery releases/clears the handle
    // No generation bump here: the CANCELLED delivery must land (the
    // honest 已取消 state). A new selection bumps the generation itself,
    // dropping both the stale result and its cancelled notice.
    return true;
}

void VizEDataPage::present_base_preview(
    const pwb::ui_pages_data::AssetRow& row) {
    updqt::DataReaderPanel* reader = workspace_->reader_panel();
    const std::uint64_t generation = ++base_generation_;

    if (jobs_ == nullptr) {
        // Synchronous fallback (tests without a JobCenter): identical
        // mapping, no cancellation context.
        BasePreviewOutcome outcome;
        try {
            auto view = base_builder_(row, nullptr);
            if (view.has_value()) {
                outcome.ok = true;
                outcome.view = std::move(*view);
            } else {
                outcome.retryable = false;
                outcome.error = "该资产类型没有可用的解析器";
            }
        } catch (const std::exception& e) {
            outcome.ok = false;
            outcome.error = e.what();
        }
        if (generation == base_generation_) {
            deliver_base_outcome(generation, outcome);
        }
        return;
    }

    reader->show_loading(row.view.name);
    active_target_ = QStringLiteral("loading");

    auto& owner = jobs_->make_owner(nullptr);
    base_owner_ = &owner;
    pwb::qgis_processing::PwbTaskOwner* owner_ptr = &owner;
    pwb::job::JobSpec spec;
    spec.kind = "preview.registry_base";
    spec.title = pwb::ui_pages_data::loading_title(row.view.name);
    // A superseded job can still be running/cancelling when the next
    // selection submits; the scheduler throws duplicate.task_key for a
    // still-active key. Scoping the key to the generation keeps dedupe
    // per selection instead of colliding with the outgoing job's shutdown.
    spec.task_key = "preview.registry_base.g" + std::to_string(generation);
    spec.run = [row, fn = base_builder_](
                   pwb::job::JobContext& ctx) -> std::any {
        BasePreviewOutcome outcome;
        try {
            auto view = fn(row, &ctx);
            if (view.has_value()) {
                outcome.ok = true;
                outcome.view = std::move(*view);
            } else {
                outcome.retryable = false;
                outcome.error = "该资产类型没有可用的解析器";
            }
        } catch (const pwb::job::JobCancelled&) {
            throw;  // the framework maps this to the cancelled state
        } catch (const std::exception& e) {
            outcome.error = e.what();
        }
        return outcome;
    };
    const std::shared_ptr<std::atomic<bool>> alive = alive_;
    pwb::qgis_processing::start_job_spec(
        owner, std::move(spec),
        [this, alive, generation, owner_ptr](
            const pwb::qgis_processing::CompatJobOutcome& o) {
                    if (!alive->load()) return;
                    const bool terminal =
                        o.state != pwb::job::JobState::queued &&
                        o.state != pwb::job::JobState::running &&
                        o.state != pwb::job::JobState::cancelling;
                    if (terminal && base_owner_ == owner_ptr) {
                        base_owner_ = nullptr;  // cancel handle released
                    }
                    if (generation != base_generation_) {
                        return;  // superseded by a newer selection
                    }
                    if (o.state == pwb::job::JobState::done ||
                        o.state == pwb::job::JobState::degraded) {
                        if (const auto* outcome =
                                std::any_cast<BasePreviewOutcome>(
                                    &o.result)) {
                            deliver_base_outcome(generation, *outcome);
                        }
                    } else if (o.state ==
                               pwb::job::JobState::cancelled) {
                        updqt::PreviewResultView view;
                        view.mode = "message";
                        view.message = "预览已取消";
                        deliver_base_preview(generation, view);
                    } else if (o.state == pwb::job::JobState::failed) {
                        updqt::PreviewResultView view;
                        view.mode = "message";
                        view.message = "预览加载失败: " + o.error;
                        view.retryable = true;
                        deliver_base_preview(generation, view);
                        Q_EMIT preview_failed(QStringLiteral("base"));
                    }
                });
}

void VizEDataPage::deliver_base_outcome(std::uint64_t generation,
                                        const BasePreviewOutcome& outcome) {
    if (!outcome.ok) {
        updqt::PreviewResultView view;
        view.mode = "message";
        view.message = outcome.error.empty() ? "预览不可用" : outcome.error;
        view.retryable = outcome.retryable;
        deliver_base_preview(generation, view);
        Q_EMIT preview_failed(QStringLiteral("base"));
        return;
    }
    deliver_base_preview(generation, outcome.view);
}

void VizEDataPage::deliver_base_preview(
    std::uint64_t generation,
    const pwb::ui_pages_data::qt::PreviewResultView& view) {
    if (generation != base_generation_) {
        return;  // stale delivery — a newer selection superseded this job
    }
    active_target_ = QString::fromStdString(view.mode);
    workspace_->reader_panel()->render(view);
    if (view.mode != "message" && view.mode != "empty") {
        Q_EMIT preview_rendered(active_target_);
    }
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

    // One task owner per request: the owner refuses a second concurrent
    // start, and repeated previews must not serialize behind a cancelling
    // job. JobCenter's unique_ptr owns the owner for its whole lifetime,
    // so the nullptr parent is fine (no parent-child double delete, and
    // the owner still delivers to this GUI thread, which is where
    // make_owner runs).
    pwb::qgis_processing::PwbTaskOwner& owner = jobs_->make_owner(nullptr);
    pwb::job::JobSpec spec;
    spec.kind = "compute.viz_e.surface_preview";
    spec.title = "曲面预览插值";
    // Same duplicate.task_key hazard as the base preview: a still-running
    // predecessor must not make the next selection throw.
    spec.task_key = "viz_e.surface_preview.g" + std::to_string(generation);
    spec.run = [request](pwb::job::JobContext& ctx) -> std::any {
        return compute_factor_preview(request, ctx);
    };
    const std::shared_ptr<std::atomic<bool>> alive = alive_;
    pwb::qgis_processing::start_job_spec(
        owner, std::move(spec),
        [this, alive, generation](
            const pwb::qgis_processing::CompatJobOutcome& o) {
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

VizEDataPage* install_data_page(QMainWindow* window,
                                pwb::app::JobCenter* jobs) {
    auto* dock = new QDockWidget(QObject::tr("数据"), window);
    dock->setObjectName(QStringLiteral("viz-e-data-dock"));
    auto* page = new VizEDataPage(dock, jobs);
    dock->setWidget(page);
    window->addDockWidget(Qt::LeftDockWidgetArea, dock);
    return page;
}

}  // namespace pwb::viz_e
