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

#include <functional>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

#include "viz_e_factor_preview.hpp"
#include "viz_e_hosts.hpp"

#include <pwb/ui_pages_data/asset_view.hpp>

namespace pwb::app {
class JobCenter;
}  // namespace pwb::app

namespace pwb::ui_pages_data::qt {
class DataWorkspace;
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
    ~VizEDataPage() override;

    // Asset source seam: rows shown in the table. The catalog-fed source is
    // the catalog integration slice's job (not this line's exclusive
    // files); tests and integrators inject real file-backed rows here.
    void set_asset_rows(const std::vector<pwb::ui_pages_data::AssetRow>& rows);

    // Selection→preview entry point (what DataAssetTable::selected_asset_
    // changed drives). Public for the E2E flow test.
    void preview_asset(const pwb::ui_pages_data::AssetRow& row);

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
    void present_well_head(const QString& path, const std::string& asset_id);
    void present_horizon(const QString& path, const std::string& asset_id,
                         const QString& asset_name);
    void show_unavailable(const QString& reason);
    void deliver_surface(std::uint64_t generation,
                         const pwb::viz_e::FactorPreviewOutcome& outcome);
    QWidget* try_external_presenter(const QString& path);

    pwb::ui_pages_data::qt::DataWorkspace* workspace_ = nullptr;
    XyScatterHost* xy_host_ = nullptr;
    SurfaceHost* surface_host_ = nullptr;
    pwb::app::JobCenter* jobs_ = nullptr;
    QString active_target_;
    std::uint64_t surface_generation_ = 0;
};

// MainWindow mount (guarded by PWB_WITH_VIZ_E in main_window.cpp): creates
// the 数据 dock on the left area and embeds a VizEDataPage. QMainWindow*
// keeps this linkable from tests without the platform closure. Returns the
// created dock (never null when compiled in).
QDockWidget* install_data_dock(QMainWindow* window,
                               pwb::app::JobCenter* jobs);

}  // namespace pwb::viz_e
