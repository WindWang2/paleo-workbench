#pragma once

// CLOSURE-PREVIEW (task 04) — the unified data page, parse-registry base
// seam and preview-dispatch closure for the platform app.
//
// One install call per window mounts THE data page:
//   * AppShell host  → the composed VizEDataPage ADOPTS the shell hub's
//     bare DataWorkspace (duplicate selection entry removed — one page,
//     one AssetSelectionBus, one reader);
//   * reduced shell  → the page mounts in a data dock (viz-e path kept).
//
// The install also wires the product loop the page needs:
//   * catalog asset source (PwbDataStore snapshot → AssetRow via the
//     injected store getter; project switch refreshes through
//     notify_project_store_changed);
//   * the parser-registry base preview (ingest::preview::build_preview
//     adapter, run through the page's JobCenter path with cooperative
//     cancel) covering text/table/image/pdf/json/media/… assets;
//   * the format-family preview targets (json_tree/rich_text/
//     web_document/geotiff/media) from ui_pages_preview registered into
//     the reader panel — the page keeps its full capability set;
//   * the D→E seismic presenter (make_seismic_preview_presenter)
//     registered as the "seismic" external presenter for .sgy/.segy;
//   * the unified preview settings: AppShell::preview_settings_requested
//     → PreviewSettingsDialog → reader/provider/store application.
//
// No fabrication: unsupported assets keep the honest unavailable message;
// a store-less session shows an honest "未打开工程" empty state.

#include <QString>

#include <functional>
#include <memory>

class QMainWindow;

namespace pwb::app {
class AppShell;
class JobCenter;
}  // namespace pwb::app

namespace pwb::application {
class PwbDataStore;
}  // namespace pwb::application

namespace pwb::ui_data_core {
class PreviewProvider;
}

namespace pwb::viz_e {
class VizEDataPage;
}

namespace pwb::closure_preview {

struct Install {
    QMainWindow* window = nullptr;  // reduced-shell dock host
    // When set, the page mounts into the AppShell hub (takes precedence
    // over the dock; the shell's DataWorkspace is adopted).
    pwb::app::AppShell* shell = nullptr;
    pwb::app::JobCenter* jobs = nullptr;
    // Live project-store getter (re-evaluated on every refresh so a
    // project open/switch/close is picked up without re-install).
    std::function<std::shared_ptr<pwb::application::PwbDataStore>()> store;
};

// Mounts and wires the single data page. Returns the page (nullptr only
// when neither a shell nor a window is provided).
pwb::viz_e::VizEDataPage* install(const Install& parts);

// Host notification (project open / new / switch): refresh the asset rows
// from the CURRENT store and re-identify the project. Safe to call when
// no closure install exists (no-op).
void notify_project_store_changed();

// Test seam: clear the refresh registry (production code never calls this).
void reset_refresh_entries_for_tests();

// The VisualizationPage LocalVizProvider base seam (UI-17 deferred): a
// PreviewProvider whose base builder resolves through the real parser
// registry (ingest::preview::build_preview) — replacing the message stub.
// The engine seam stays absent (honest "不支持" per GeoVizError(Unsupported)
// parity until the engine host line lands).
ui_data_core::PreviewProvider registry_preview_provider();

}  // namespace pwb::closure_preview
