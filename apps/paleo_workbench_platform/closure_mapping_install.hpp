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

#include <functional>
#include <memory>

#include <pwb/domain/json.hpp>

class QMainWindow;

namespace pwb::app {
class AppShell;
}

namespace pwb::application {
class PwbDataStore;
}  // namespace pwb::application

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

}  // namespace pwb::app::closure_mapping
