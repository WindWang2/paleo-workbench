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

class QgsPrintLayout;
class QMainWindow;

namespace pwb::app {
class AppShell;
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

    // BEGIN qgis-native-layout-convergence
    // Opens the governed layout export dialog (the SAME map_export action
    // path). Bound by the host window; the native layout editor's export
    // button rides it — one export authority, one provenance ledger.
    std::function<void(QgsPrintLayout*)> export_layout_dialog;
    // END qgis-native-layout-convergence

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


}  // namespace pwb::app::closure_mapping
