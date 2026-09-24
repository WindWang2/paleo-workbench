// 08-line closure — install implementation. See closure_mapping_install.hpp
// for the contract. The Stage 3 composition surface is the native QGIS
// layout editor (pwb::qgis::LayoutEditorPanel) over persistent
// QgsPrintLayouts; the retired composer registry/panel/replay machinery
// lives on only in the mapping_document frozen oracles.

#include "closure_mapping_install.hpp"

#include <QMainWindow>
#include <pwb/qgis/layout_editor_panel.hpp>
#include "app_context.hpp"
#include "main_window.hpp"

#include <QCoreApplication>
#include <QIODevice>
#include <QFile>
#include <QPointer>
#include <QSemaphore>
#include <QSize>
#include <QThread>

#include "app_shell.hpp"
#include "job_center.hpp"

#include <pwb/ui_map/mapping_page.hpp>

#include <QMetaObject>
#include <QObject>
#include <QPushButton>
#include <QVariant>
#include <QVBoxLayout>
#include <QWidget>

#include <algorithm>
#include <any>
#include <atomic>
#include <cstdint>
#include <chrono>
#include <cstdio>
#include <filesystem>
#include <limits>
#include <map>
#include <memory>
#include <set>
#include <thread>
#include <utility>

#include "closure_mapping_document.hpp"

// cpp-close-03: the canonical SQLite-backed workflow catalog rail —
// preferred over the JSON-rail PersistentRuntimeCatalog whenever the
// closure_workflow slice is linked (PWB_WITH_CLOSURE_WORKFLOW).
#if defined(PWB_WITH_CLOSURE_WORKFLOW) && \
    __has_include(<pwb/closure_workflow/catalog_closure_adapter.hpp>)
#include <pwb/closure_workflow/catalog_closure_adapter.hpp>
#define PWB_MAPPING_SQLITE_CATALOG 1
#endif

#if PWB_WITH_FACTOR_KERNEL
#include "factor_prepare_production.hpp"
#endif

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/qgis_processing/task_bridge.hpp>
#include <pwb/mapping_document/document_io.hpp>
#include <pwb/project/manager.hpp>
#include <pwb/ui_map/display_map_canvas.hpp>
#include <pwb/qgis/map_session.hpp>
#include <pwb/ui_pages_data/qt/preparation_page.hpp>
#include <pwb/ui_pages_mapedit/boundary_panel.hpp>
#include <pwb/ui_pages_mapedit/factor_preview_grid.hpp>
#include <pwb/ui_pages_mapedit/map_edit_scene.hpp>
#include <pwb/ui_pages_mapedit/map_edit_view.hpp>
#include <pwb/ui_pages_mapedit/map_reference_panel.hpp>
#include <pwb/ui_pages_mapedit/map_workbench_bottom.hpp>
#include <pwb/ui_seqviz/factor_state.hpp>
#include <pwb/ui_seqviz/qt/factor_panels.hpp>
#include <pwb/ui_workers/contour_draft.hpp>
#include <pwb/ui_workers/factor_prepare.hpp>
#include <pwb/ui_wellseis/qt/well_table_panel.hpp>
#include <pwb/ui_wellseis/slices.hpp>
#include <pwb/viz_charts/marching_squares.hpp>

namespace pwb::app::closure_mapping {
namespace {

using pwb::domain::Json;

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

}  // namespace

namespace {

// App-lifetime delivery pump for WorkerLane::Client::marshal (the
// job_bridge DeliveryPump pattern): a plain QObject on the GUI thread,
// parented to the app, so a worker-side invokeMethod can never target a
// dead receiver. Per-run suppression is the released flag re-checked
// inside the queued body at delivery time.
class WorkerDeliveryPump : public QObject {
public:
    using QObject::QObject;
};

WorkerDeliveryPump* worker_delivery_pump() {
    QCoreApplication* app = QCoreApplication::instance();
    if (app == nullptr) return nullptr;  // no application: nowhere to marshal
    // Heap-allocated with NO parent at construction (the first call may
    // happen on a worker thread — parenting across threads is silently
    // dropped), then adopted by the app from the GUI thread via a queued
    // call: the app owns it, so there is no static-destruction ordering
    // hazard at exit.
    static WorkerDeliveryPump* pump = [app] {
        auto* created = new WorkerDeliveryPump();
        created->moveToThread(app->thread());
        QMetaObject::invokeMethod(
            created,
            [created, app] { created->setParent(app); },
            Qt::QueuedConnection);
        return created;
    }();
    return pump;
}

}  // namespace

// ---------------------------------------------------------------------------
// Off-thread worker lanes — QgsTaskManager edition (the retired WorkerHost
// contract over PwbTaskOwner): the injected worker body runs as a
// PaleoFunctionTask body on a task-manager thread; terminal/progress
// callbacks marshal back to the GUI thread through the app-lifetime pump
// above. The page's guards prevent overlapping runs; each lane is
// single-flight (start refuses a second concurrent task).
//
// #1455 hardening kept: the worker body NEVER touches the lane object. It
// runs against a per-run released flag shared with the lane, plus a
// copyable Client handle whose marshal() hops through the app-lifetime
// delivery pump guarded by that flag. A shutdown that times out abandons
// the body — QgsTaskManager keeps the task alive (adoption inherent), the
// abandoned body holds only shared_ptr state, and its queued deliveries
// are dropped at delivery time.
// ---------------------------------------------------------------------------
class WorkerLane {
public:
    // Copyable worker-side handle (capture BY VALUE inside bodies — it
    // never dangles). marshal() targets the app-lifetime pump; a delivery
    // queued before the run was released is dropped at delivery time,
    // never committed.
    class Client {
    public:
        void marshal(std::function<void()> fn) const {
            auto* pump = worker_delivery_pump();
            // Post-app-exit guard: ~QCoreApplication destroys the pump
            // while a shutdown-abandoned body may still run — instance()
            // nulls early, so drop rather than touch it.
            if (pump == nullptr || QCoreApplication::instance() == nullptr) {
                return;
            }
            auto guard = released_;
            QMetaObject::invokeMethod(
                pump,
                [guard, fn = std::move(fn)]() {
                    if (guard->load()) return;  // run released: drop
                    fn();
                },
                Qt::QueuedConnection);
        }

        // Terminal-callback variant: clears the lane's busy flag inside
        // the GUI-side delivery BEFORE running fn. marshal() posts are
        // non-blocking, so clearing busy after body() returns races the
        // queued callback — a page could observe the terminal state while
        // busy() still read true and pop a "still running" modal.
        // Clearing inside the delivery restores the happens-before:
        // terminal observed ⇒ not busy.
        void marshal_terminal(std::function<void()> fn) const {
            marshal([busy = busy_, fn = std::move(fn)]() {
                busy->store(false, std::memory_order_release);
                fn();
            });
        }

    private:
        friend class WorkerLane;
        Client(std::shared_ptr<std::atomic<bool>> released,
               std::shared_ptr<std::atomic<bool>> busy)
            : released_(std::move(released)), busy_(std::move(busy)) {}
        std::shared_ptr<std::atomic<bool>> released_;
        std::shared_ptr<std::atomic<bool>> busy_;
    };

    // Cancel observation moved onto PaleoTaskBodyContext (the retired
    // Client::cancelled poll is ctx.cancel_requested() now).
    using Body = std::function<void(
        Client&, pwb::qgis_processing::PaleoTaskBodyContext&)>;

    WorkerLane(pwb::qgis_processing::PwbTaskOwner* owner, void** target_slot)
        : owner_(owner), target_slot_(target_slot) {}

    ~WorkerLane() {
        // Last-resort release (#1455 parity): drop the run's queued pump
        // deliveries. The lane NEVER touches the owner here — it may
        // already be gone (JobCenter members die before the window's
        // QObject children); the owner cancels through its own teardown
        // paths (JobCenter::shutdown_workers / ~PwbTaskOwner), and the
        // task keeps running under QgsTaskManager. The normal path runs
        // shutdown() first through AppShell::shutdown_workers.
        if (released_ != nullptr) released_->store(true);
    }

    // target mirrors Python OwnedWorkerJob.target: the page's guards
    // compare it against the bound project so stale completions drop.
    void run(void* target, QString kind, QString title, Body body) {
        if (owner_ == nullptr) return;
        // Defensive single-flight (the page's guards normally prevent
        // overlap): the retired host joined the previous run here —
        // release it and give it a bounded drain instead.
        if (busy_) shutdown(2000);
        *target_slot_ = target;
        // Fresh release guard per run (task-owner start discipline): a
        // delivery already queued for the PREVIOUS run keeps its own
        // guard and stays suppressed after its shutdown.
        auto released = std::make_shared<std::atomic<bool>>(false);
        released_ = released;
        // busy_ is the retired Control::busy flag, NOT owner_->is_running():
        // the task STATUS flips on the worker thread only after the
        // blocking finished() handshake reached the GUI. Terminal
        // callbacks go through marshal_terminal() which clears busy
        // inside the GUI-side delivery itself — a page that observes a
        // terminal callback can never still read busy() true. The
        // body-thread store below remains as the backstop for bodies
        // that never marshal a terminal callback.
        auto busy = busy_;
        busy->store(true, std::memory_order_release);
        owner_->start(
            std::move(kind), std::move(title),
            [body = std::move(body), released,
             busy](pwb::qgis_processing::PaleoTaskBodyContext& ctx) -> bool {
                Client client(released, busy);
                body(client, ctx);
                // Marshals exactly one terminal callback itself
                // (completed/cancelled/failed); the task-level outcome is
                // projection only.
                busy->store(false, std::memory_order_release);
                return true;
            },
            [busy](const pwb::qgis_processing::PaleoTaskOutcome&) {
                // No owner-level finish: the body's marshalled terminal
                // callback IS the page contract. This only clears the busy
                // flag for terminal paths that never ran the body (a task
                // cancelled while QUEUED).
                busy->store(false, std::memory_order_release);
            });
    }

    void cancel() {
        if (owner_ != nullptr) owner_->cancel();
    }

    bool busy() const { return busy_->load(std::memory_order_acquire); }
    void* target() const { return *target_slot_; }

    // OwnedWorkerJob.shutdown parity: release the run's queued deliveries
    // FIRST (an already-queued callback must never fire into the page
    // being torn down), cancel, then bounded wait — page teardown /
    // window close must not freeze the GUI for the full kernel duration.
    // On timeout the task keeps running under QgsTaskManager; its guards
    // discard late results.
    bool shutdown(int wait_ms) {
        if (released_ != nullptr) released_->store(true);
        busy_->store(false, std::memory_order_release);
        *target_slot_ = nullptr;
        return owner_ == nullptr || owner_->shutdown(wait_ms);
    }

private:
    pwb::qgis_processing::PwbTaskOwner* owner_ = nullptr;  // not owned
    void** target_slot_ = nullptr;
    // Worker-side busy flag (the retired Control::busy): set on run(),
    // cleared on the body thread right after the terminal marshal (and
    // on terminal-without-body / shutdown paths).
    std::shared_ptr<std::atomic<bool>> busy_ =
        std::make_shared<std::atomic<bool>>(false);
    std::shared_ptr<std::atomic<bool>> released_ =
        std::make_shared<std::atomic<bool>>(false);
};

namespace {

// ---------------------------------------------------------------------------
// factor_map_tasks Json ↔ FactorTaskRecord (ui_seqviz shelf payload).
// ---------------------------------------------------------------------------

pwb::ui_seqviz::FactorTaskRecord record_from_json(const Json& entry) {
    pwb::ui_seqviz::FactorTaskRecord record;
    auto get = [&entry](const char* key) -> std::string {
        const auto it = entry.find(key);
        return it != entry.end() && it->is_string() ? it->get<std::string>()
                                                    : std::string{};
    };
    record.id = get("id");
    record.name = get("name");
    record.status = get("status");
    record.target_horizon = get("target_horizon");
    record.factor_type = get("factor_type");
    record.method = get("method");
    if (const auto it = entry.find("parameters");
        it != entry.end() && it->is_object()) {
        record.parameters = *it;
    }
    if (const auto it = entry.find("quality_metrics");
        it != entry.end() && it->is_object()) {
        record.quality_metrics = *it;
    }
    return record;
}

// ---------------------------------------------------------------------------
// Contour draft Json conversion (project.contour_drafts entries). Python
// shape: ContourDraft model — id / name / target_horizon / factor_type /
// linked_factor_task_id / levels / segments[{id, level, coordinates,
// closed, properties}] / source_grid_n / source_backend /
// source_value_range / status / generator_version / updated_at /
// linked_map_document_id.
// ---------------------------------------------------------------------------

Json draft_to_json(const pwb::ui_workers::ContourDraftSlice& draft) {
    Json out = Json::object();
    out["id"] = draft.id;
    out["name"] = draft.name;
    out["target_horizon"] = draft.target_horizon;
    out["factor_type"] = draft.factor_type;
    out["linked_factor_task_id"] = draft.linked_factor_task_id;
    out["levels"] = draft.levels;
    Json segments = Json::array();
    for (const auto& segment : draft.segments) {
        Json seg = Json::object();
        seg["id"] = segment.id;
        seg["level"] = segment.level;
        Json coords = Json::array();
        for (const auto& [x, y] : segment.coordinates) {
            coords.push_back(Json::array({x, y}));
        }
        seg["coordinates"] = coords;
        seg["closed"] = segment.closed;
        Json props = Json::object();
        for (const auto& [key, value] : segment.properties) {
            if (auto const* s = std::any_cast<std::string>(&value)) {
                props[key] = *s;
            } else if (auto const* d = std::any_cast<double>(&value)) {
                props[key] = *d;
            } else if (auto const* b = std::any_cast<bool>(&value)) {
                props[key] = *b;
            } else if (auto const* i = std::any_cast<int>(&value)) {
                props[key] = *i;
            }
            // Unrepresentable payload types are skipped (honest subset;
            // the compile path only stores string/double/bool/int).
        }
        seg["properties"] = props;
        segments.push_back(std::move(seg));
    }
    out["segments"] = segments;
    out["source_grid_n"] = draft.source_grid_n;
    out["source_backend"] = draft.source_backend;
    out["source_value_range"] = Json::array(
        {draft.source_value_range.first, draft.source_value_range.second});
    out["status"] = draft.status;
    out["generator_version"] = draft.generator_version;
    out["updated_at"] = draft.updated_at;
    out["linked_map_document_id"] = draft.linked_map_document_id;
    return out;
}

// ---------------------------------------------------------------------------
// PreparationPage panel shims — adapt the real panels to the page's seam
// interfaces (the page stays dependency-light; the real panels live in
// ui_seqviz / ui_wellseis / ui_pages_mapedit).
// ---------------------------------------------------------------------------

class TaskPanelShim final : public pwb::ui_pages_data::qt::FactorTaskPanelApi {
public:
    explicit TaskPanelShim(QWidget* parent = nullptr)
        : FactorTaskPanelApi(parent) {
        auto* layout = new QVBoxLayout(this);
        layout->setContentsMargins(0, 0, 0, 0);
        panel_ = new pwb::ui_seqviz::qt::FactorTaskPanel(this);
        layout->addWidget(panel_, 1);
        connect(panel_, &pwb::ui_seqviz::qt::FactorTaskPanel::generate_requested,
                this, &FactorTaskPanelApi::generate_requested);
        connect(panel_,
                &pwb::ui_seqviz::qt::FactorTaskPanel::contour_draft_requested,
                this, &FactorTaskPanelApi::contour_draft_requested);
    }

    QString selected_method() const override {
        return panel_->selected_method();
    }
    void update_state(const Json& tasks) override {
        std::vector<pwb::ui_seqviz::FactorTaskRecord> records;
        if (tasks.is_array()) {
            for (const auto& entry : tasks) {
                records.push_back(record_from_json(entry));
            }
        }
        panel_->update_state(records);
    }
    QPushButton* generate_btn() override { return panel_->generate_btn(); }
    QPushButton* contour_draft_btn() override {
        return panel_->contour_draft_btn();
    }
    QLabel* summary_label() override { return panel_->summary_label(); }

private:
    pwb::ui_seqviz::qt::FactorTaskPanel* panel_ = nullptr;
};

// The C++ WellTablePanel (UI-09) has no QC button; the shim carries the
// page's QC row so the Python toolbar contract survives without touching
// ui_wellseis.
class WellTableShim final : public pwb::ui_pages_data::qt::WellTablePanelApi {
public:
    explicit WellTableShim(QWidget* parent = nullptr)
        : WellTablePanelApi(parent) {
        auto* layout = new QVBoxLayout(this);
        layout->setContentsMargins(0, 0, 0, 0);
        qc_btn_ = new QPushButton(QStringLiteral("运行井点 QC"), this);
        qc_btn_->setObjectName(QStringLiteral("run_qc_btn"));
        layout->addWidget(qc_btn_, 0);
        panel_ = new pwb::ui_wellseis::qt::WellTablePanel(this);
        layout->addWidget(panel_, 1);
    }

    QPushButton* run_qc_btn() override { return qc_btn_; }
    void update_from_well_table(void* table) override {
        const auto* slice =
            static_cast<const pwb::ui_wellseis::WellTableSlice*>(table);
        if (slice != nullptr) {
            panel_->update_from_well_table(*slice);
        } else {
            panel_->clear();
        }
    }

private:
    QPushButton* qc_btn_ = nullptr;
    pwb::ui_wellseis::qt::WellTablePanel* panel_ = nullptr;
};

class PreviewGridShim final
    : public pwb::ui_pages_data::qt::FactorPreviewGridApi {
public:
    explicit PreviewGridShim(QWidget* parent = nullptr)
        : FactorPreviewGridApi(parent) {
        auto* layout = new QVBoxLayout(this);
        layout->setContentsMargins(0, 0, 0, 0);
        panel_ = new pwb::ui_pages_mapedit::FactorPreviewGrid(this);
        layout->addWidget(panel_, 1);
    }

    void update_state(const Json& tasks) override {
        std::vector<Json> entries;
        if (tasks.is_array()) {
            for (const auto& entry : tasks) entries.push_back(entry);
        }
        panel_->update_state(entries);
    }

private:
    pwb::ui_pages_mapedit::FactorPreviewGrid* panel_ = nullptr;
};

// Factor task grid from the legacy `parameters` lists (grid_x/grid_y/
// grid_z) — the _grid_from_task legacy branch parity.
bool grid_from_task_parameters(const Json& task, std::vector<double>& grid_x,
                               std::vector<double>& grid_y,
                               pwb::ui_workers::Grid2D& grid_z) {
    const auto params = task.find("parameters");
    if (params == task.end() || !params->is_object()) return false;
    auto read = [params](const char* key,
                         std::vector<double>& out) {
        const auto it = params->find(key);
        if (it == params->end() || !it->is_array()) return false;
        out.clear();
        for (const auto& v : *it) {
            if (!v.is_number()) return false;
            out.push_back(v.get<double>());
        }
        return true;
    };
    if (!read("grid_x", grid_x) || !read("grid_y", grid_y)) return false;
    const auto z = params->find("grid_z");
    if (z == params->end() || !z->is_array() || grid_y.empty()) return false;
    grid_z.rows = z->size();
    grid_z.cols = grid_x.size();
    grid_z.data.clear();
    for (const auto& row : *z) {
        if (!row.is_array()) return false;
        for (const auto& v : row) {
            // null == nodata (encode_legacy_grid_lists convention).
            if (!v.is_number() && !v.is_null()) return false;
            grid_z.data.push_back(
                v.is_null() ? std::numeric_limits<double>::quiet_NaN()
                            : v.get<double>());
        }
    }
    if (grid_z.data.size() != grid_z.rows * grid_z.cols) return false;
    return true;
}

}  // namespace

// Per-window install state — lives as a QObject child of the window so
// notify_project_changed / save_documents can recover it by property.
class ClosureContext : public QObject {
    Q_OBJECT
public:
    explicit ClosureContext(QObject* parent) : QObject(parent) {}
    Install install;
    MapDocumentBank* bank = nullptr;
    pwb::ui_pages_data::qt::PreparationPage* preparation = nullptr;
    // Worker lanes over the QGIS task bridge (the retired WorkerHost):
    // one QgsTask-backed owner per lane; the owners are parented to this
    // window (JobCenter registration when available) and die with it.
    std::unique_ptr<WorkerLane> prepare_lane;
    std::unique_ptr<WorkerLane> contour_lane;
    // The page's stale-completion guard values (target identity per lane).
    void* prepare_target = nullptr;
    void* contour_target = nullptr;
#if PWB_WITH_FACTOR_KERNEL
    // V14-FACTOR: process-live grid cache + the persisted factor_map
    // provenance rail (one workflow seam contract, GUI-thread-confined like
    // every other catalog surface in this install). The catalog is the
    // SHARED rail: the workflow binding may install the canonical SQLite
    // adapter (closure_workflow::CatalogClosureAdapter) here so factor
    // prep, map compile and product assembly write one provenance store;
    // the JSON-backed PersistentRuntimeCatalog remains the fallback when
    // the deep store refuses to open (cpp-close-03 contract).
    std::shared_ptr<pwb::factor_production::LiveFactorGridStore> factor_grids;
    std::shared_ptr<pwb::workflow_runtime::CatalogRepository> factor_catalog;
    // Project the live grid store currently serves (same-project reopen
    // keeps its entries; a switch clears them — #848).
    std::filesystem::path factor_grids_project_;
#endif

    // BEGIN qgis-native-layout-convergence
    // The Stage 3 native layout editor installed on the mapping page
    // (refreshed on project switch).
    pwb::qgis::LayoutEditorPanel* layout_editor = nullptr;
    // END qgis-native-layout-convergence
};


// ---------------------------------------------------------------------------
// install
// ---------------------------------------------------------------------------

bool install(const Install& install) {
    if (install.window == nullptr || install.shell == nullptr) {
        return false;
    }
    auto* mapping_page = install.shell->mapping_page();
    if (mapping_page == nullptr) return false;

    // Capture the getter BY VALUE — the Install struct lives on the
    // caller's frame only.
    auto store_getter = install.store_getter;
    const auto store =
        store_getter ? store_getter()
                       : std::shared_ptr<pwb::application::PwbDataStore>{};

    // ---- 1. mapping-page adopt set ---------------------------------------
    auto* view = new pwb::ui_pages_mapedit::MapEditView(mapping_page);
    auto* scene = view->edit_scene();
    mapping_page->adopt_edit_view(view);
    mapping_page->adopt_reference_panel(
        new pwb::ui_pages_mapedit::MapReferencePanel(mapping_page));
    mapping_page->adopt_bottom_workbench(
        new pwb::ui_pages_mapedit::MapWorkbenchBottom(mapping_page));

    // BEGIN qgis-native-layout-convergence
    // Stage 3 composition surface = the native QGIS layout editor over the
    // session's persistent QgsPrintLayouts (QgsLayoutManager-backed
    // authority). The retired CompositionPanel / edit-session / SVG
    // renderer / Qt-replay export path is deleted: geometry, undo,
    // property editing, preview and export are QGIS-native; Paleo
    // semantics ride on item slots (pwb/item_slots).
    auto* main_window = dynamic_cast<pwb::app::MainWindow*>(install.window);
    if (main_window == nullptr) return false;
    auto* window_session = &main_window->context().session();
    auto* editor = new pwb::qgis::LayoutEditorPanel(
        window_session->layout(), window_session->canvas(), mapping_page);
    mapping_page->adopt_composition_panel(editor);

    // Per-window context (bank/preparation back-pointers + editor handle).
    auto* context = new ClosureContext(install.window);
    context->install = Install{install.window, install.shell, store_getter};
    context->layout_editor = editor;
    install.window->setProperty(
        "closure_mapping_context",
        QVariant::fromValue(static_cast<QObject*>(context)));
    // The editor's export button opens the same governed export dialog the
    // map_export action carries (one export authority, one provenance
    // ledger).
    if (install.export_layout_dialog) {
        QObject::connect(editor,
                         &pwb::qgis::LayoutEditorPanel::export_requested,
                         install.window,
                         [open_export = install.export_layout_dialog](
                             QgsPrintLayout* layout) {
                             if (layout == nullptr) return;
                             open_export(layout);
                         });
    }
    // END qgis-native-layout-convergence
    // ---- 2. document bank -------------------------------------------------
    auto* bank = new MapDocumentBank(scene, view, install.window);
    // BEGIN V14-COMPILATION-PUBLISH — the context was created before the
    // composition seams (the main-map binding seam records on it); only
    // the bank back-pointer is set here now.
    context->bank = bank;
    // END V14-COMPILATION-PUBLISH
    bank->set_persist_fn([store_getter, store](std::string*) -> bool {
        const auto persisted =
            store != nullptr ? store
                             : (store_getter ? store_getter() : nullptr);
        if (persisted == nullptr) return false;
        // ProjectManager::save is the atomic project write kernel (crash-
        // safe replace + .bak + stale-write guard). The store does not
        // expose save yet (01-line surface), so the same kernel runs
        // against the store's live document.
        pwb::project::ProjectManager manager(persisted->project_file());
        auto result = manager.save(persisted->document());
        return result.is_ok();
    });
    if (store != nullptr) {
        std::vector<Json> documents;
        const auto& root = store->document().root();
        const auto section = root.find("paleomap_documents");
        if (section != root.end() && section->is_array()) {
            for (const auto& entry : *section) documents.push_back(entry);
        }
        bank->set_documents(std::move(documents), {}, install.window);
    }

    // ---- 3. preparation page ---------------------------------------------
    auto* preparation =
        new pwb::ui_pages_data::qt::PreparationPage(install.window);
    preparation->setObjectName(QStringLiteral("PreparationPage"));
    preparation->set_task_panel(new TaskPanelShim(preparation));
    preparation->set_well_table_panel(new WellTableShim(preparation));
    preparation->set_preview_grid(new PreviewGridShim(preparation));
    preparation->set_boundary_panel(
        new pwb::ui_pages_mapedit::BoundaryPanel(preparation));

    // Worker lanes (the retired WorkerHost): one QgsTask-backed owner per
    // lane. Through the JobCenter when available (close-protocol
    // registration + the shared admission gate); window-parented owners
    // as the reduced-host fallback.
    pwb::qgis_processing::PwbTaskOwner* prepare_owner = nullptr;
    pwb::qgis_processing::PwbTaskOwner* contour_owner = nullptr;
    if (install.jobs != nullptr) {
        prepare_owner = &install.jobs->make_owner(install.window);
        contour_owner = &install.jobs->make_owner(install.window);
    } else {
        prepare_owner =
            new pwb::qgis_processing::PwbTaskOwner(install.window);
        contour_owner =
            new pwb::qgis_processing::PwbTaskOwner(install.window);
    }
    context->prepare_lane = std::make_unique<WorkerLane>(
        prepare_owner, &context->prepare_target);
    context->contour_lane = std::make_unique<WorkerLane>(
        contour_owner, &context->contour_target);
    WorkerLane* const prepare_lane = context->prepare_lane.get();
    WorkerLane* const contour_lane = context->contour_lane.get();

    // Project store seam — returns the STORE (shared_ptr), never a raw
    // pointer into its document: every caller holds the store alive for
    // its own use (review finding: a bare Json* outlived the local
    // shared_ptr).
    auto project_store_fn = [store_getter]()
        -> std::shared_ptr<pwb::application::PwbDataStore> {
        return store_getter ? store_getter() : nullptr;
    };
    preparation->set_factor_map_tasks_fn(
        [project_store_fn](void*) -> Json {
        const auto store = project_store_fn();
        if (store == nullptr) return Json::array();
        const auto& root = store->document().root();
        const auto it = root.find("factor_map_tasks");
        return it != root.end() ? *it : Json::array();
    });

    // #834 parity — the process-global counter lives in
    // factor_prepare_production.cpp so this page and the
    // WorkflowController recompute path share one run identity.
    preparation->set_generation_fns(
        &pwb::factor_production::next_factor_prepare_generation,
        &pwb::factor_production::current_factor_prepare_generation);

    // OwnedWorkerJob seams — the page's running/target/cancel guards need
    // a live job binding (review P1-7); each lane owns its slot.
    preparation->set_prepare_job(
        pwb::ui_pages_data::qt::WorkerJobApi{
            [prepare_lane] { return prepare_lane->busy(); },
            [prepare_lane](int wait_ms) {
                return prepare_lane->shutdown(wait_ms);
            },
            [prepare_lane] { prepare_lane->cancel(); },
            [prepare_lane]() -> void* { return prepare_lane->target(); }});
    preparation->set_contour_job(
        pwb::ui_pages_data::qt::WorkerJobApi{
            [contour_lane] { return contour_lane->busy(); },
            [contour_lane](int wait_ms) {
                return contour_lane->shutdown(wait_ms);
            },
            [contour_lane] { contour_lane->cancel(); },
            [contour_lane]() -> void* { return contour_lane->target(); }});
    preparation->set_snapshot_task_count_fn(
        [project_store_fn](void*, const std::string&, int) {
            const auto store = project_store_fn();
            if (store == nullptr) return 0;
            const auto& root = store->document().root();
            const auto it = root.find("factor_map_tasks");
            return it != root.end() && it->is_array()
                       ? static_cast<int>(it->size())
                       : 0;
        });

#if PWB_WITH_FACTOR_KERNEL
    // BEGIN V14-FACTOR PREPARE — the REAL batch grid kernel: the host
    // thread builds the narrow scientific snapshot (fingerprint inputs
    // match classification, Python parity), the worker lane's task thread
    // runs the scheduler over the fully-bound seams (classify → reuse →
    // per-task isolated interpolation), and exactly one terminal callback
    // is marshalled back to the GUI thread. The cancel bridge polls the
    // task context onto the job token (50 ms granularity, Python
    // CancellationToken parity).
    context->factor_grids =
        std::make_shared<pwb::factor_production::LiveFactorGridStore>();
    context->factor_grids_project_.clear();
    // The provenance rail opens in notify_project_changed (below, called
    // unconditionally at the end of install) — SQLite catalog first, the
    // JSON-rail PersistentRuntimeCatalog as the fail-closed fallback.
    {
        pwb::factor_production::FactorPrepareKernelConfig kernel_config;
        auto seams = pwb::factor_production::make_factor_prepare_seams(
            context->factor_grids, kernel_config);
        auto grids = context->factor_grids;
        preparation->set_prepare_worker_fn(
            [prepare_lane, project_store_fn, seams, grids](
                void* project, const std::string& method, int gen,
                std::function<void(
                    const pwb::ui_pages_data::qt::PrepareProgressView&)>
                    progress,
                std::function<void(
                    const pwb::ui_pages_data::qt::PrepareResultView&)>
                    completed,
                std::function<void(const QString&)> failed,
                std::function<void()> cancelled) {
            // Snapshot on the host thread (the GUI thread at call time) so
            // the scientific inputs match the Stage-4 fingerprints.
            const auto store = project_store_fn();
            pwb::ui_workers::FactorPrepareSnapshot snapshot;
            if (store != nullptr) {
                const auto slice = pwb::factor_production::
                    build_prepare_slice(store->document().root());
                snapshot = pwb::ui_workers::build_prepare_snapshot(
                    slice, gen, method, /*grid_n=*/std::nullopt,
                    /*power=*/2.0, /*force=*/false, /*seed=*/0,
                    /*target_horizon=*/std::nullopt,
                    /*factor_types=*/std::nullopt, seams);
            }
            prepare_lane->run(
                project, QStringLiteral("background.compute"),
                QStringLiteral("单因素图制备"),
                [snapshot = std::move(snapshot), seams, grids,
                 progress, completed, failed, cancelled, gen,
                 method](WorkerLane::Client& client,
                         pwb::qgis_processing::PaleoTaskBodyContext& ctx) {
                try {
                    job::CancellationToken token;
                    std::atomic<bool> body_done{false};
                    // The cancel bridge polls the task context (pure
                    // shared state — never the lane object, so it stays
                    // legal even on the shutdown-abandoned path #1455
                    // guards).
                    std::thread cancel_bridge([&ctx, &token, &body_done] {
                        while (!body_done.load(std::memory_order_relaxed)) {
                            if (ctx.cancel_requested()) {
                                token.cancel();
                                return;
                            }
                            std::this_thread::sleep_for(
                                std::chrono::milliseconds(50));
                        }
                    });
                    // RAII: whatever path leaves this scope (result, cancel
                    // or exception) joins the bridge — a joinable thread at
                    // destruction would std::terminate the app.
                    const auto join_bridge =
                        [&cancel_bridge, &body_done]() {
                            body_done.store(true,
                                            std::memory_order_relaxed);
                            if (cancel_bridge.joinable()) {
                                cancel_bridge.join();
                            }
                        };
                    struct JoinGuard {
                        std::function<void()> fn;
                        ~JoinGuard() { fn(); }
                    } join_guard{join_bridge};
                    const auto forward =
                        [&](const pwb::ui_workers::FactorPrepareProgress&
                                update) {
                        pwb::ui_pages_data::qt::PrepareProgressView view;
                        view.generation = update.generation;
                        view.total_tasks = update.total_tasks;
                        view.clean = update.clean;
                        view.dirty = update.dirty;
                        view.completed = update.completed;
                        view.phase = update.phase;
                        view.message = update.message;
                        client.marshal(
                            [progress, view] { progress(view); });
                    };
                    auto result = pwb::ui_workers::
                        run_factor_prepare_schedule(snapshot, token, forward,
                                                    seams, /*workers=*/0);
                    // (the JoinGuard joins at scope exit on every path)
                    pwb::ui_pages_data::qt::PrepareResultView done;
                    done.generation = result.generation;
                    done.clean_count = result.clean_count;
                    done.executed_count = result.executed_count;
                    if (result.cancelled) {
                        client.marshal_terminal(
                            [cancelled] { cancelled(); });
                    } else {
                        // The full DTO travels through the shared grid
                        // store keyed by task id; the view carries the
                        // counters the page label reads. The commit pulls
                        // the staged DTOs back out of the context.
                        auto payload =
                            std::make_shared<pwb::ui_workers::
                                                 FactorPrepareBatchResult>(
                                std::move(result));
                        client.marshal_terminal(
                            [completed, done, payload, grids] {
                                grids->stash_last_result(payload);
                                completed(done);
                            });
                    }
                } catch (const job::JobCancelled&) {
                    client.marshal_terminal([cancelled] { cancelled(); });
                } catch (const std::exception& exc) {
                    const QString message = QString::fromUtf8(exc.what());
                    client.marshal_terminal(
                        [failed, message] { failed(message); });
                }
            });
        });
    }

    // Commit: the real host-side guard semantics — stale generation
    // mutates nothing; per-item fingerprint re-verification against the
    // LIVE project under the scheduled overrides; targeted index
    // replacement; live grid repair; factor_map run + INTERMEDIATE version
    // registration on the persisted provenance rail.
    preparation->set_commit_prepare_fn(
        [project_store_fn, context](
            void*, const pwb::ui_pages_data::qt::PrepareResultView&,
            int expected_generation) -> int {
        const auto store = project_store_fn();
        if (store == nullptr) return 0;
        auto last = context->factor_grids->take_last_result();
        if (!last.has_value()) return 0;
        pwb::factor_production::CommitPrepareReport report;
        try {
            report = pwb::factor_production::
                commit_prepare_batch_result(
                    store->document().root(), *last, expected_generation,
                    *context->factor_grids, context->factor_catalog.get());
        } catch (const std::exception&) {
            return 0;  // commit failure mutates nothing (host guard)
        }
        return static_cast<int>(report.discarded.size());
    });
#else
    // Prepare worker: the real batch grid kernel slices (CONV-05/18) are
    // not in this configure. The run stages a real batch result whose
    // tasks carry the explicit kernel-missing error; the page shows the
    // honest failure instead of a fabricated product.
    preparation->set_prepare_worker_fn(
        [prepare_lane](void* project, const std::string& method, int gen,
               std::function<void(const pwb::ui_pages_data::qt::PrepareProgressView&)>
                   progress,
               std::function<void(const pwb::ui_pages_data::qt::PrepareResultView&)>
                   completed,
               std::function<void(const QString&)>,
               std::function<void()> cancelled) {
        (void)project;
        prepare_lane->run(
            project, QStringLiteral("background.compute"),
            QStringLiteral("单因素图制备"),
            [method, gen, progress, completed,
             cancelled](WorkerLane::Client& client,
                        pwb::qgis_processing::PaleoTaskBodyContext& ctx) {
            pwb::ui_pages_data::qt::PrepareProgressView start;
            start.generation = gen;
            start.phase = "classify";
            start.message = "网格计算内核未接入";
            client.marshal([progress, start] { progress(start); });

            pwb::ui_workers::FactorPrepareBatchResult result;
            result.generation = gen;
            result.method = method;
            for (int i = 0; i < 1; ++i) {
                if (ctx.cancel_requested()) {
                    client.marshal_terminal([cancelled] { cancelled(); });
                    return;
                }
                pwb::ui_workers::FactorPrepareTaskResult item;
                item.task_id = "kernel_binding";
                item.dirty_state = "missing_output";
                item.error = "网格计算内核未接入（等待科学计算内核绑定）";
                result.task_results.push_back(std::move(item));
            }
            pwb::ui_pages_data::qt::PrepareResultView done;
            done.generation = gen;
            done.clean_count = result.clean_count;
            done.executed_count = result.executed_count;
            client.marshal_terminal([completed, done] { completed(done); });
        });
        });
    preparation->set_commit_prepare_fn(
        [](void*, const pwb::ui_pages_data::qt::PrepareResultView&,
           int) { return 0; });
#endif
    // END V14-FACTOR PREPARE

    // Contour worker: the REAL ui_workers compile pipeline with the REAL
    // viz_charts marching-squares extraction kernel. Grid resolution order
    // (V14-FACTOR, Python factor_grid_result_for_task parity): live grid
    // cache → catalog version payload → legacy inline parameters. Without
    // completed grids it honestly yields zero drafts.
    preparation->set_contour_worker_fn(
        [contour_lane, project_store_fn, context](
            void* project, std::function<void(void*)> completed,
            std::function<void(const QString&)> failed) {
        // Keep the store alive for the whole worker run (captured on the
        // GUI thread): the Json root pointer stays valid even if the user
        // opens another project mid-run — the stale commit then writes to
        // the captured (superseded) store and is dropped by the page
        // guards on the GUI thread.
        auto store = project_store_fn();
        // GUI-thread pre-resolution of every complete task's grid payload
        // (the live cache and the catalog seam are thread-confined to the
        // GUI thread by contract — the worker body only reads the copies).
        std::map<std::string,
                 std::tuple<std::vector<double>, std::vector<double>,
                            pwb::ui_workers::Grid2D>>
            resolved_grids;
#if PWB_WITH_FACTOR_KERNEL
        if (store != nullptr && context->factor_grids != nullptr) {
            const Json& root = store->document().root();
            const auto tasks_it = root.find("factor_map_tasks");
            if (tasks_it != root.end() && tasks_it->is_array()) {
                for (const auto& entry : *tasks_it) {
                    if (!entry.is_object()) continue;
                    const auto status_it = entry.find("status");
                    if (status_it == entry.end()
                        || status_it->get<std::string>() != "complete") {
                        continue;
                    }
                    std::string id;
                    if (const auto id_it = entry.find("id");
                        id_it != entry.end() && id_it->is_string()) {
                        id = id_it->get<std::string>();
                    }
                    if (id.empty()) continue;
                    if (auto live = context->factor_grids->peek(id)) {
                        pwb::ui_workers::Grid2D grid;
                        grid.rows = live->grid_y.size();
                        grid.cols = live->grid_x.size();
                        grid.data.assign(live->grid_z.begin(),
                                         live->grid_z.end());
                        resolved_grids.emplace(
                            id, std::make_tuple(live->grid_x, live->grid_y,
                                                std::move(grid)));
                        continue;
                    }
                    // Catalog version payload (to_legacy_dict shape) — the
                    // reopened-project leg (live cache is empty there).
                    if (context->factor_catalog != nullptr) {
                        const auto vid_it =
                            entry.find("grid_artifact_version_id");
                        if (vid_it == entry.end() || !vid_it->is_string()) {
                            continue;
                        }
                        try {
                            const auto version =
                                context->factor_catalog->resolve_version(
                                    vid_it->get<std::string>());
                            if (!version.has_value()) continue;
                            const Json payload =
                                Json::parse(version->payload_json);
                            std::vector<double> gx, gy;
                            for (const auto& v : payload["grid_x"]) {
                                gx.push_back(v.get<double>());
                            }
                            for (const auto& v : payload["grid_y"]) {
                                gy.push_back(v.get<double>());
                            }
                            pwb::ui_workers::Grid2D gz;
                            gz.rows = gy.size();
                            gz.cols = gx.size();
                            gz.data.reserve(gz.rows * gz.cols);
                            for (const auto& row : payload["grid_z"]) {
                                for (const auto& cell : row) {
                                    gz.data.push_back(
                                        cell.is_null()
                                            ? std::numeric_limits<double>::quiet_NaN()
                                            : cell.get<double>());
                                }
                            }
                            if (gz.data.size() == gz.rows * gz.cols
                                && !gx.empty()) {
                                resolved_grids.emplace(
                                    id, std::make_tuple(
                                            std::move(gx), std::move(gy),
                                            std::move(gz)));
                            }
                        } catch (const std::exception&) {
                            // Unresolvable payload — the legacy inline leg
                            // below is the last resort, then honest skip.
                        }
                    }
                }
            }
        }
#endif
        // GUI-thread snapshot of the task list (the worker body never
        // touches the live document — a commit may mutate it concurrently
        // while this body runs).
        Json tasks_json = Json::array();
        if (store != nullptr) {
            if (const auto it = store->document().root().find(
                    "factor_map_tasks");
                it != store->document().root().end() && it->is_array()) {
                tasks_json = *it;
            }
        }
        contour_lane->run(
            project, QStringLiteral("background.compute"),
            QStringLiteral("等值线初稿"),
            [completed = std::move(completed),
             failed = std::move(failed), store,
             tasks_json = std::move(tasks_json),
             resolved_grids = std::move(resolved_grids)](
                WorkerLane::Client& client,
                pwb::qgis_processing::PaleoTaskBodyContext& ctx) {
            try {
                // Shared result payload: the ledger JSON the GUI-thread
                // commit writes back, plus the created-draft count.
                auto payload = std::make_shared<Json>(Json::array());
                int count = 0;
                {
                    std::vector<pwb::ui_workers::FactorTaskSlice> tasks;
                    for (const auto& entry : tasks_json) {
                        pwb::ui_workers::FactorTaskSlice task;
                        auto field = [&entry](const char* key) {
                            const auto f = entry.find(key);
                            return f != entry.end() && f->is_string()
                                       ? f->get<std::string>()
                                       : std::string{};
                        };
                        task.id = field("id");
                        task.name = field("name");
                        task.status = field("status");
                        task.target_horizon = field("target_horizon");
                        task.factor_type = field("factor_type");
                        task.method = field("method");
                        if (task.status == "complete") {
                            std::vector<double> x, y;
                            pwb::ui_workers::Grid2D z;
                            if (grid_from_task_parameters(entry, x, y, z)) {
                                task.grid_x = std::move(x);
                                task.grid_y = std::move(y);
                                task.grid_z = std::move(z);
                            } else if (const auto resolved =
                                           resolved_grids.find(task.id);
                                       resolved != resolved_grids.end()) {
                                task.grid_x = std::get<0>(resolved->second);
                                task.grid_y = std::get<1>(resolved->second);
                                task.grid_z = std::get<2>(resolved->second);
                            }
                        }
                        tasks.push_back(std::move(task));
                    }

                    std::vector<pwb::ui_workers::ContourDraftSlice> ledger;
                    // Existing ledger rides in the project (upsert parity).
                    // (Parsing existing entries back is not needed for the
                    // created-count contract; compile upserts into a fresh
                    // snapshot ledger and the commit replaces the section.)
                    job::CancellationToken token;
                    // Cancel bridge (prepare-worker parity): the marching-
                    // squares kernel observes the token, so a shutdown's
                    // cancel actually interrupts the compile instead of
                    // waiting out the whole pass (#1455). The bridge polls
                    // the task context — never the lane object.
                    std::atomic<bool> body_done{false};
                    std::thread cancel_bridge([&ctx, &token, &body_done] {
                        while (!body_done.load(std::memory_order_relaxed)) {
                            if (ctx.cancel_requested()) {
                                token.cancel();
                                return;
                            }
                            std::this_thread::sleep_for(
                                std::chrono::milliseconds(50));
                        }
                    });
                    const auto join_bridge = [&cancel_bridge, &body_done]() {
                        body_done.store(true, std::memory_order_relaxed);
                        if (cancel_bridge.joinable()) {
                            cancel_bridge.join();
                        }
                    };
                    struct JoinGuard {
                        std::function<void()> fn;
                        ~JoinGuard() { fn(); }
                    } join_guard{join_bridge};
                    // The real extraction kernel: viz_charts marching
                    // squares (contourpy serial port) behind the
                    // ui_workers ExtractLinesFn seam.
                    pwb::ui_workers::ExtractLinesFn extract =
                        [](const std::vector<double>& grid_x,
                           const std::vector<double>& grid_y,
                           const pwb::ui_workers::Grid2D& grid_z,
                           const std::vector<double>& levels,
                           const job::CancellationToken& token) {
                            std::map<double, std::vector<
                                                 std::vector<std::pair<double, double>>>>
                                out;
                            if (levels.empty()) return out;
                            auto cancelled = [&token]() {
                                return token.is_cancelled();
                            };
                            const auto lines =
                                pwb::viz_charts::extract_contour_lines(
                                    grid_x, grid_y, grid_z.data, levels,
                                    cancelled);
                            if (!lines.has_value()) return out;
                            for (const auto& [level, polylines] : *lines) {
                                auto& points = out[level];
                                for (const auto& line : polylines) {
                                    std::vector<std::pair<double, double>> pts;
                                    pts.reserve(line.xs.size());
                                    for (std::size_t i = 0;
                                         i < line.xs.size() &&
                                         i < line.ys.size();
                                         ++i) {
                                        pts.emplace_back(line.xs[i],
                                                         line.ys[i]);
                                    }
                                    points.push_back(std::move(pts));
                                }
                            }
                            return out;
                        };
                    const auto drafts =
                        pwb::ui_workers::compile_contour_drafts_for_project(
                            tasks, ledger, std::nullopt, /*only_complete=*/true,
                            pwb::ui_workers::kContourDefaultNLevels, token,
                            extract, /*id_fn=*/{},
                            /*updated_at=*/{});
                    count = static_cast<int>(drafts.size());
                    for (const auto& draft : drafts) {
                        payload->push_back(draft_to_json(draft));
                    }
                }
                client.marshal_terminal([completed, payload] {
                    completed(payload.get());
                });
            } catch (const std::exception& exc) {
                const QString message = QString::fromUtf8(exc.what());
                client.marshal_terminal(
                    [failed, message] { failed(message); });
            }
        });
        });
    // The commit receives the shared Json payload pointer and writes the
    // compiled ledger into project.contour_drafts.
    // BEGIN V14-FACTOR CONTOUR COMMIT — id-preserving upsert into
    // project.contour_drafts + apply each draft to its map document
    // (paleomap_documents line features, role "contour"); the commit that
    // previously wholesale-replaced the ledger. Without the kernel slices
    // the legacy replace stays (same honest surface).
#if PWB_WITH_FACTOR_KERNEL
    preparation->set_commit_contour_fn(
        [project_store_fn](void*, void* result) -> int {
            auto* payload = static_cast<Json*>(result);
            if (payload == nullptr) return 0;
            const auto store = project_store_fn();
            if (store == nullptr) return 0;
            return pwb::factor_production::commit_contour_drafts_full(
                store->document().root(), *payload);
        });
#else
    preparation->set_commit_contour_fn(
        [project_store_fn](void*, void* result) -> int {
            auto* payload = static_cast<Json*>(result);
            if (payload == nullptr) return 0;
            const auto store = project_store_fn();
            if (store != nullptr) {
                store->document().root()["contour_drafts"] = *payload;
            }
            return payload->is_array() ? static_cast<int>(payload->size()) : 0;
        });
#endif
    // END V14-FACTOR CONTOUR COMMIT

    context->preparation = preparation;
#if PWB_WITH_FACTOR_KERNEL
    // BEGIN V14-FACTOR CROSSWELL: expose the factor context handles for
    // the cross-well dock's linkage provider (GUI-thread-confined reads).
    install.window->setProperty(
        "closure_factor_grids",
        QVariant::fromValue(context->factor_grids.get()));
    install.window->setProperty(
        "closure_factor_catalog",
        QVariant::fromValue(
            static_cast<pwb::workflow_runtime::CatalogRepository*>(
                context->factor_catalog.get())));
#endif

    install.shell->adopt_preparation_page(preparation);

    // Bind whatever project is already open (review P0-1: the page's
    // project guard stayed null forever, making the real contour kernel
    // unreachable and QC lie about "工程未绑定").
    notify_project_changed(install.window);
    return true;
}

void notify_project_changed(QMainWindow* window) {
    if (window == nullptr) return;
    const QVariant stored = window->property("closure_mapping_context");
    auto* context = stored.value<QObject*>();
    if (context == nullptr) return;
    auto* self = dynamic_cast<ClosureContext*>(context);
    if (self == nullptr) return;
    const auto store =
        self->install.store_getter ? self->install.store_getter() : nullptr;
    void* project_root =
        store != nullptr ? &store->document().root() : nullptr;
#if PWB_WITH_FACTOR_KERNEL
    // V14-FACTOR: the provenance rail follows the open project — reopened
    // on every switch so run/version history stays per-project. The
    // canonical SQLite catalog (catalog.sqlite, the same store the deep
    // catalog closure + map-compile/product lineage write) is preferred;
    // when it refuses (corrupt/absent and not creatable) the JSON-backed
    // PersistentRuntimeCatalog remains so provenance degrades honestly
    // instead of vanishing. A corrupt store fails closed either way —
    // never a silently reset history.
    if (store != nullptr) {
        const std::filesystem::path project_file = store->project_file();
        std::shared_ptr<pwb::workflow_runtime::CatalogRepository> next;
#if defined(PWB_MAPPING_SQLITE_CATALOG)
        if (auto opened = pwb::closure_workflow::CatalogClosureAdapter::
                try_open(project_file)) {
            next = std::make_shared<
                pwb::closure_workflow::CatalogClosureAdapter>(
                std::move(*opened));
        }
#endif
        if (next == nullptr) {
            auto fallback = std::make_shared<
                pwb::factor_production::PersistentRuntimeCatalog>();
            try {
                fallback->open(project_file.parent_path() /
                               "workflow_provenance");
            } catch (const std::exception&) {
                fallback.reset();
            }
            next = fallback;
        }
        self->factor_catalog = std::move(next);
    } else {
        self->factor_catalog.reset();
    }
    // The property mirrors the LIVE pointer — a project switch replaces
    // the catalog object, so re-publish here (a stale pointer into a
    // destroyed rail is worse than none).
    window->setProperty(
        "closure_factor_catalog",
        QVariant::fromValue(
            static_cast<pwb::workflow_runtime::CatalogRepository*>(
                self->factor_catalog.get())));
    // Session caches must not leak ACROSS projects (Python
    // clear_session_caches parity — called on catalog close/switch):
    // reopen of the SAME project keeps the grids (the classifier then
    // sees live grids for reuse), a DIFFERENT project clears them.
    if (self->factor_grids != nullptr) {
        const std::filesystem::path current_project =
            store != nullptr
                ? store->project_file()
                : std::filesystem::path{};
        if (current_project != self->factor_grids_project_) {
            self->factor_grids->clear_all();
            self->factor_grids_project_ = current_project;
        }
    }
    if (QMainWindow* owner = window; owner != nullptr) {
        owner->setProperty("closure_factor_catalog",
                           QVariant::fromValue(
                               self->factor_catalog.get()));
        owner->setProperty(
            "closure_project_store",
            QVariant::fromValue(store.get()));
    }
#endif
    // BEGIN qgis-native-layout-convergence
    // The restore itself runs in MainWindow::openProject (unconditional);
    // here the editor panel just re-reads the live authority (project
    // switch/close both land in notify_project_changed).
    if (self->layout_editor != nullptr) self->layout_editor->refresh();
    // END qgis-native-layout-convergence
    if (self->preparation != nullptr) {
        self->preparation->set_project(project_root);
    }
    if (self->bank != nullptr) {
        std::vector<Json> documents;
        if (store != nullptr) {
            const auto& root = store->document().root();
            const auto section = root.find("paleomap_documents");
            if (section != root.end() && section->is_array()) {
                for (const auto& entry : *section) documents.push_back(entry);
            }
        }
        self->bank->set_documents(std::move(documents), {}, window);
    }
}

bool save_documents(QMainWindow* window, std::string* error) {
    if (window == nullptr) {
        if (error != nullptr) *error = "无宿主窗口";
        return false;
    }
    const QVariant stored = window->property("closure_mapping_context");
    auto* context = stored.value<QObject*>();
    auto* self = dynamic_cast<ClosureContext*>(context);
    if (self == nullptr || self->bank == nullptr) {
        if (error != nullptr) *error = "编图文档库未安装";
        return false;
    }
    // Route through the bank's public save (persist seam included).
    if (!self->bank->save_active(window)) {
        if (error != nullptr) *error = "编图文档保存失败（见页面诊断）";
        return false;
    }
    return true;
}

// V14-THREE-STAGE-UX — read-only bank access for the stage-flow
// presentation wiring (bank signals → MappingPage state).
MapDocumentBank* document_bank(QMainWindow* window) {
    if (window == nullptr) return nullptr;
    const QVariant stored = window->property("closure_mapping_context");
    auto* context = stored.value<QObject*>();
    auto* self = dynamic_cast<ClosureContext*>(context);
    return self != nullptr ? self->bank : nullptr;
}

// V14 composition-root accessors — the workflow binding shares the same
// live grid store / provenance rail / preparation page instead of
// constructing parallel instances (the #834 generation guard only works
// when every producer writes through ONE cache + ONE catalog).
pwb::ui_pages_data::qt::PreparationPage* preparation_page(
    QMainWindow* window) {
    if (window == nullptr) return nullptr;
    const QVariant stored = window->property("closure_mapping_context");
    auto* context = stored.value<QObject*>();
    auto* self = dynamic_cast<ClosureContext*>(context);
    return self != nullptr ? self->preparation : nullptr;
}

#if PWB_WITH_FACTOR_KERNEL
std::shared_ptr<pwb::factor_production::LiveFactorGridStore>
factor_grid_store(QMainWindow* window) {
    if (window == nullptr) return nullptr;
    const QVariant stored = window->property("closure_mapping_context");
    auto* context = stored.value<QObject*>();
    auto* self = dynamic_cast<ClosureContext*>(context);
    return self != nullptr ? self->factor_grids : nullptr;
}

std::shared_ptr<pwb::workflow_runtime::CatalogRepository> factor_catalog(
    QMainWindow* window) {
    if (window == nullptr) return nullptr;
    const QVariant stored = window->property("closure_mapping_context");
    auto* context = stored.value<QObject*>();
    auto* self = dynamic_cast<ClosureContext*>(context);
    return self != nullptr ? self->factor_catalog : nullptr;
}
#endif

}  // namespace pwb::app::closure_mapping

#include "closure_mapping_install.moc"
