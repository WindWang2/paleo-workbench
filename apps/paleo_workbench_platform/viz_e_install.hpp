// VIZ-E — data/preview page assembly (plan P-A + V6 wiring).
//
// VizEDataPage composes the lib-ready UI-06/07 slices into the product
// flow 资产选择 → 识别能力 → 加载 → 真实预览/图表 → 导出:
//   * DataWorkspace (ui_pages_data) — navigation tree, asset table with
//     selection signal, reader panel;
//   * chart hosts (viz_e_hosts) registered into the reader panel through
//     the EXISTING seams — register_target/register_render_hook — under
//     the preview modes "xy_scatter" and "surface" (kPreviewModes
//     vocabulary, preview_dispatch.hpp);
//   * well-head/horizon .dat previews run the real parsing port
//     (viz_e_dat_preview, geoviz previews/dat.py @0885195); horizon
//     surfaces compute through mapping_kernel interpolation inside a
//     JobCenter job (cooperative cancel + generation guard against
//     late/stale deliveries);
//   * external presenter registration: sibling lines (A: LAS, B:
//     time-depth/cross-well, D: seismic/xy_scatter-from-segy) register
//     through register_external_presenter() — a thin, documented contract
//     over the same reader-panel seams, NOT a new plugin architecture.
//
// The page never fabricates success: unsupported assets surface the honest
// unavailable message with the dependency state, and undeclared CRS/unit
// metadata stays undeclared in the provenance line.
#pragma once

#include <QDockWidget>
#include <QMainWindow>
#include <QString>
#include <QWidget>

#include <atomic>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

#include "viz_e_factor_preview.hpp"
#include "viz_e_hosts.hpp"

#include <pwb/ui_pages_data/asset_view.hpp>
#include <pwb/ui_pages_data/qt/data_reader_panel.hpp>

class QMainWindow;

namespace pwb::app {
class JobCenter;
}  // namespace pwb::app

namespace pwb::job {
class JobContext;
}

namespace pwb::qgis_processing {
class PwbTaskOwner;
}  // namespace pwb::qgis_processing

namespace pwb::ui_pages_data::qt {
class DataWorkspace;
class AssetSelectionBus;
}  // namespace pwb::ui_pages_data::qt

namespace pwb::app {
class JobCenter;
}  // namespace pwb::app

namespace pwb::viz_e {

// ---------------------------------------------------------------------------
// External presenter registration (A/B/D contract)
// ---------------------------------------------------------------------------

// A presenter answers two questions: can it present this asset (supports),
// and build the presenting widget (create — parent-owned, nullptr = decline
// at build time). Kind strings follow the preview_dispatch vocabulary
// ("well_log", "time_depth", "seismic", "xy_scatter", ...).
struct ExternalPresenter {
    std::string kind;
    std::function<bool(const QString& asset_path)> supports;
    std::function<QWidget*(const QString& asset_path, QWidget* parent)> create;
    std::string note;  // provider line + dependency state, surfaced in UI
};

// Process-level registry (thread-safe). Returns false when `kind` is
// already registered with a different presenter (first registration wins;
// re-registering the same kind from another line is a wiring bug we make
// loud, not silent).
bool register_external_presenter(ExternalPresenter presenter);

struct PresenterStatus {
    std::string kind;
    std::string note;
};

// Snapshot of registered external presenters (dependency-state reporting).
std::vector<PresenterStatus> registered_presenters();

// Test seam: clear the registry (production code never calls this).
void reset_external_presenters_for_tests();

// ---------------------------------------------------------------------------
// VizEDataPage — the composed data page
// ---------------------------------------------------------------------------

class VizEDataPage : public QWidget {
    Q_OBJECT
public:
    explicit VizEDataPage(QWidget* parent, pwb::app::JobCenter* jobs);
    // CLOSURE-PREVIEW (task 04): adopt an existing workspace (the AppShell
    // hub's bare management DataWorkspace) so a shell-hosted window has
    // exactly ONE data page — the duplicate entry point is removed, not
    // shared. The page takes over the workspace's layout slot; the
    // previous owner keeps its pointer valid (the widget lives on).
    VizEDataPage(QWidget* parent, pwb::app::JobCenter* jobs,
                 pwb::ui_pages_data::qt::DataWorkspace* adopted_workspace);
    ~VizEDataPage() override;

    // Asset source seam: rows shown in the table. The catalog-fed source
    // lives in closure_preview_install (task 04); tests and integrators
    // inject real file-backed rows here.
    void set_asset_rows(const std::vector<pwb::ui_pages_data::AssetRow>& rows);

    // CLOSURE-PREVIEW (task 04): bind the single asset-selection state.
    // When bound, the page previews on bus selection changes ONLY (the
    // direct table connection is dropped) so there is exactly one preview
    // path; rows/selection flow through the bus as the single source of
    // truth. nullptr unbinds (falls back to the direct table signal).
    void bind_selection_bus(pwb::ui_pages_data::qt::AssetSelectionBus* bus);

    // Selection→preview entry point (what DataAssetTable::selected_asset_
    // changed drives). Public for the E2E flow test.
    void preview_asset(const pwb::ui_pages_data::AssetRow& row);

    // Present a worker-produced factor/contour result (factor_prepare /
    // contour_draft outputs adapted via surface_data_from_factor_task).
    // Routes to the surface host through the same reader-panel render path
    // as asset-driven previews.
    void present_factor_surface(const SurfaceHost::SurfaceData& data);

    // CLOSURE-PREVIEW (task 04): the parser-registry base preview seam.
    // `fn` builds the reader view for an asset OFF the GUI thread (the
    // JobContext*, when non-null, carries the cooperative cancel token;
    // nullptr = synchronous no-cancel context). Returning nullopt means
    // "no capability for this asset" → the honest unavailable path. The
    // fn must not touch QWidget API. `payload` inside a returned view is
    // only guaranteed alive for the duration of the render call.
    using BasePreviewFn = std::function<std::optional<
        pwb::ui_pages_data::qt::PreviewResultView>(
        const pwb::ui_pages_data::AssetRow& row,
        pwb::job::JobContext* ctx)>;
    void set_base_preview_builder(BasePreviewFn fn);

    // Cancel an in-flight base/surface preview (loading-page 取消 hook and
    // fast-switch path). Returns true when something was cancelled.
    bool cancel_active_preview();

    pwb::ui_pages_data::qt::DataWorkspace* workspace() const { return workspace_; }
    XyScatterHost* xy_host() const { return xy_host_; }
    SurfaceHost* surface_host() const { return surface_host_; }

    // Last preview state for tests/diagnostics: which target is active.
    QString active_target() const { return active_target_; }

Q_SIGNALS:
    // Emitted after a chart/surface preview rendered (P-A loop telemetry).
    void preview_rendered(const QString& target);
    void preview_failed(const QString& reason);

private Q_SLOTS:
    void on_selected_asset(
        const std::optional<pwb::ui_pages_data::AssetRow>& asset);

private:
    // Worker-side outcome envelope (std::any payload through the owner).
    struct BasePreviewOutcome {
        bool ok = false;
        pwb::ui_pages_data::qt::PreviewResultView view;
        std::string error;
        bool retryable = true;
    };

    void present_well_head(const QString& path, const std::string& asset_id);
    void present_horizon(const QString& path, const std::string& asset_id,
                         const QString& asset_name);
    void present_base_preview(const pwb::ui_pages_data::AssetRow& row);
    void deliver_base_outcome(std::uint64_t generation,
                              const BasePreviewOutcome& outcome);
    void deliver_base_preview(
        std::uint64_t generation,
        const pwb::ui_pages_data::qt::PreviewResultView& view);
    void show_unavailable(const QString& reason);
    void deliver_surface(std::uint64_t generation,
                         const pwb::viz_e::FactorPreviewOutcome& outcome);
    QWidget* try_external_presenter(const QString& path);

    // Cleared in ~VizEDataPage; the surface/base job delivery lambdas hold
    // a copy so a completion hopping to the GUI thread after the page died
    // drops instead of touching freed members.
    std::shared_ptr<std::atomic<bool>> alive_;
    pwb::ui_pages_data::qt::DataWorkspace* workspace_ = nullptr;
    XyScatterHost* xy_host_ = nullptr;
    SurfaceHost* surface_host_ = nullptr;
    pwb::app::JobCenter* jobs_ = nullptr;
    QString active_target_;
    std::uint64_t surface_generation_ = 0;
    // Base-preview job bookkeeping (generation guard + cancel).
    std::uint64_t base_generation_ = 0;
    pwb::qgis_processing::PwbTaskOwner* base_owner_ = nullptr;
    BasePreviewFn base_builder_;
    pwb::ui_pages_data::qt::AssetSelectionBus* selection_bus_ = nullptr;
};

// MainWindow mount (guarded by PWB_WITH_VIZ_E in main_window.cpp): creates
// the 数据 dock on the left area and embeds a VizEDataPage. QMainWindow*
// keeps this linkable from tests without the platform closure. Returns the
// created dock (never null when compiled in).
QDockWidget* install_data_dock(QMainWindow* window,
                               pwb::app::JobCenter* jobs);
// CLOSURE-PREVIEW (task 04): the dock mount returning the page — the
// closure assembly needs the page pointer for bus/settings wiring.
VizEDataPage* install_data_page(QMainWindow* window,
                                pwb::app::JobCenter* jobs);

}  // namespace pwb::viz_e
