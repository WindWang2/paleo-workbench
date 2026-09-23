// 08-line closure — product install for 数据制备 + 编图编辑 + 组合文档.
//
// Installs (each a no-op returning false when its UI targets are absent —
// honest skip, never a fake page):
//   1. MappingPage slot adoption: the four deferred-slice placeholders
//      become the real ui_pages_mapedit edit view / reference panel /
//      bottom workbench and the ui_seqviz composition panel; a
//      MapDocumentBank binds the edit scene to the project's
//      paleomap_documents entries (guard / save / discard / switch).
//   2. AppShell hub-3 preparation submodule: the placeholder becomes the
//      real PreparationPage with the ui_seqviz / ui_wellseis /
//      ui_pages_mapedit panels and ui_workers-backed prepare/contour
//      seams committing into project.factor_map_tasks / contour_drafts.
//
// Kernel honesty: the contour extraction seam binds the real viz_charts
// marching-squares port; the factor batch grid computation kernel is not
// ported natively yet (cross-line dependency, see the PR) — an unbound
// kernel surfaces as an explicit per-task failure, never a fabricated
// product.

#pragma once

// PWB-V14-DATA-LINEAGE: std::string used below without its header
// (g++ pulled it in transitively).
#include <string>

#include <functional>
#include <memory>

#include <pwb/domain/json.hpp>

class QMainWindow;

namespace pwb::app {
class AppShell;
class JobCenter;
}

namespace pwb::application {
class PwbDataStore;
}  // namespace pwb::application

// Composition-root accessor types (forward declarations — the heavy
// headers stay in the .cpp).
namespace pwb::ui_pages_data::qt {
class PreparationPage;
}
namespace pwb::factor_production {
class LiveFactorGridStore;
}
namespace pwb::workflow_runtime {
class CatalogRepository;
}

namespace pwb::app::closure_mapping {

struct Install {
    QMainWindow* window = nullptr;
    AppShell* shell = nullptr;
    // Lazily resolves the live project store (set at openProject). An
    // empty result ⇒ the bank/persist run store-less (honest failure on
    // save) until a project is opened.
    std::function<std::shared_ptr<pwb::application::PwbDataStore>()>
        store_getter;

    // BEGIN V14-COMPILATION-PUBLISH
    // Optional native QGIS layout executor for composition export: the
    // platform binds its CompositionLayoutService (session-backed; the
    // extent / CRS / mirror-layer description is resolved on the platform
    // side). When absent — or when it refuses (hybrid elements, no
    // session, …) — the export falls back to the native composer engine
    // (SVG + Qt PNG/PDF replay) and the report's engine label says which
    // path produced the file. Never a silent no-op, never a fake file.
    std::function<pwb::domain::Json(const std::string& composition_json,
                                    const std::string& path,
                                    const std::string& format, double dpi)>
        layout_export;
    // END V14-COMPILATION-PUBLISH

    // The composition root's JobCenter (may be null in reduced hosts):
    // the preparation worker lanes take their PwbTaskOwner slots from it
    // (close-protocol registration + the shared admission gate). Null
    // falls back to window-parented owners.
    JobCenter* jobs = nullptr;
};

// Installs the mapping-page adopt set + preparation page. Safe to call
// once per window.
bool install(const Install& install);

// Rebinds the preparation page + document bank to the CURRENT project
// store (call after openProject / project close). With no store bound the
// page honestly unbinds (QC/contour report "请先打开或绑定工程。").
void notify_project_changed(QMainWindow* window);

// 12's global save routes here: save the active mapping document through
// the bank (topology gate -> apply_features_to_document -> project
// persist). Returns false + error when nothing is installed yet or the
// write failed.
bool save_documents(QMainWindow* window, std::string* error);

// V14-THREE-STAGE-UX: the installed document bank for this window
// (nullptr when the mapping closure is absent or not yet installed).
// Read-only access for presentation wiring (bank signals → page state).
class MapDocumentBank;
MapDocumentBank* document_bank(QMainWindow* window);

// Composition-root accessors (the workflow binding shares these — one
// live grid store, one provenance rail, one preparation page per window):
pwb::ui_pages_data::qt::PreparationPage* preparation_page(
    QMainWindow* window);
#if defined(PWB_WITH_FACTOR_KERNEL)
std::shared_ptr<pwb::factor_production::LiveFactorGridStore>
factor_grid_store(QMainWindow* window);
std::shared_ptr<pwb::workflow_runtime::CatalogRepository> factor_catalog(
    QMainWindow* window);
#endif

// BEGIN V14-COMPILATION-PUBLISH — composition export control surface.
//
// The panel's export seam stays synchronous (Python composition_panel
// `_export` parity: export_composition_reported runs inline and returns a
// report). Cooperative cancellation + coarse progress ride a per-window
// token the running export polls at stage boundaries — the same
// map_export_worker discipline (CancellationToken checkpoints; a
// cancelled export removes the partial file and reports ok=false, never
// a success claim).
//
// cancel_composition_export: idempotent, no-op when idle; also invoked
// by notify_project_changed so a project switch cannot let an in-flight
// export write against the old project.
void cancel_composition_export(QMainWindow* window);

// Installs a coarse progress sink (0..100 at stage boundaries) for the
// window's composition exports; an empty function clears it. The sink is
// invoked on whichever thread the export runs — GUI-thread for the
// panel's synchronous seam, the worker lane for export_composition_async.
void set_composition_export_progress(QMainWindow* window,
                                     std::function<void(int)> progress);

// Worker-capable entry (one export at a time per window — the honest
// refusal is false when a run is in flight). `composition_json` is the
// dumped Composition document (transport-stable across the thread hop);
// GUI-affine canvas seams marshal onto the GUI thread internally.
// `progress` and `finished` fire on the GUI thread via queued delivery;
// `finished` receives a report object {ok, engine, path, message,
// warnings, cancelled} — ok=false with `failure`/`message` on refusals,
// never a fabricated success.
bool export_composition_async(
    QMainWindow* window, const std::string& composition_json,
    const std::string& path, const std::string& format, double dpi,
    std::function<void(int)> progress,
    std::function<void(pwb::domain::Json report)> finished);
// END V14-COMPILATION-PUBLISH

}  // namespace pwb::app::closure_mapping
