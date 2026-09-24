#include <pwb/closure_science/qt/page_binding.hpp>

#include <pwb/closure_science/inference_service.hpp>
#include <pwb/closure_science/model_seed.hpp>
#include <pwb/closure_science/providers.hpp>
#include <pwb/closure_science/run_spec_service.hpp>
#include <pwb/closure_science/task_journal.hpp>
#include <pwb/catalog/model_registry.hpp>
#include <pwb/catalog/service_core.hpp>
#include <pwb/domain/diagnostics.hpp>
#include <pwb/domain/ids.hpp>
#include <pwb/project/manager.hpp>
#include <pwb/ui_wellseis/qt/seismic_prediction_page.hpp>
#include <pwb/ui_wellseis/qt/well_log_prediction_page.hpp>

#include <QMetaObject>

#include <QThread>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <thread>

namespace pwb::closure_science::qt {

using pwb::ui_wellseis::PredictionTaskSlice;
using pwb::ui_wellseis::RunSlice;

namespace {

std::string json_text(const Json& value, const std::string& fallback = {}) {
    return value.is_string() ? value.get<std::string>() : fallback;
}

Json json_array_strings(const Json& value) {
    return value.is_array() ? value : Json::array();
}

}  // namespace

// One project-bound execution context: opened lazily for the current
// project file, replaced on project switch. Shared with the worker thread —
// a rebind drops only the binding's reference, so an in-flight run keeps a
// consistent view of ITS project and lands its rows in that project's
// store (never the new project's).
struct SciencePageBinding::CatalogContext {
    std::filesystem::path project_file;
    std::unique_ptr<catalog::CatalogServiceCore> core;
    std::vector<ResourceRef> resources;
    std::unique_ptr<PredictionTaskJournal> journal;
    std::string open_error;

    [[nodiscard]] std::filesystem::path project_dir() const {
        return project_file.parent_path();
    }
    [[nodiscard]] std::filesystem::path artifacts_root() const {
        return project_dir() / (project_file.stem().string() + ".artifacts");
    }
    [[nodiscard]] catalog::SaveHook save_hook() const {
        catalog::CatalogServiceCore* core = this->core.get();
        return [core](const catalog::DirtySet& dirty) {
            return core->save(dirty);
        };
    }
};

class SciencePageBinding::Impl {
public:
    explicit Impl(Config config) : config_(std::move(config)) {
        providers_.register_provider(std::string(kProviderDemo),
                                     make_demo_facies_provider());
        // work_root defaults to the run's context artifacts tree; the
        // provider receives it per call (see tiled provider config below).
        providers_.register_provider(
            std::string(kProviderTiledOnnx),
            make_tiled_onnx_provider(TiledOnnxProviderConfig{}));
        // local_asset / geoviz_online have no native executor: never
        // registered, so a run against them fails with the explicit
        // unknown-provider / no-native-executor error instead of a stub.
    }

    ~Impl() {
        alive_->store(false);
        shutdown(2000);
    }

    // ------------------------------------------------------------------
    // Catalog context (lazy per project)
    // ------------------------------------------------------------------
    [[nodiscard]] std::shared_ptr<CatalogContext> catalog() {
        std::filesystem::path current;
        if (config_.project_file != nullptr) {
            current = config_.project_file();
        }
        {
            const std::lock_guard<std::mutex> lock(catalog_mutex_);
            if (cached_ != nullptr && cached_->project_file == current) {
                return cached_->open_error.empty() && cached_->core != nullptr
                           ? cached_
                           : nullptr;
            }
        }
        auto context = std::make_shared<CatalogContext>();
        context->project_file = current;
        if (!current.empty()) {
            auto opened = catalog::open_catalog(current);
            if (opened.is_ok()) {
                context->core = std::make_unique<catalog::CatalogServiceCore>(
                    std::move(opened.value()));
                collect_resources(*context);
            } else {
                context->open_error = opened.error().message;
            }
        }
        const std::lock_guard<std::mutex> lock(catalog_mutex_);
        cached_ = std::move(context);
        return cached_->open_error.empty() && cached_->core != nullptr
                   ? cached_
                   : nullptr;
    }

    [[nodiscard]] std::string catalog_error() {
        std::filesystem::path current;
        if (config_.project_file != nullptr) {
            current = config_.project_file();
        }
        if (current.empty()) return "没有已打开的工程";
        (void)catalog();
        const std::lock_guard<std::mutex> lock(catalog_mutex_);
        if (cached_ == nullptr) return "没有已打开的工程";
        return cached_->open_error;
    }

    void collect_resources(CatalogContext& context) {
        pwb::project::ProjectManager manager(context.project_file);
        auto loaded = manager.load();
        if (!loaded.is_ok()) {
            context.open_error = loaded.error().message;
            return;
        }
        const auto& document = loaded.value().document;
        const Json* resources = document.find_section("resources");
        if (resources == nullptr || !resources->is_array()) return;
        for (const auto& resource : *resources) {
            if (!resource.is_object()) continue;
            ResourceRef ref;
            ref.id = resource.contains("id") ? json_text(resource["id"])
                                             : std::string();
            ref.type = resource.contains("type")
                           ? json_text(resource["type"])
                           : std::string();
            ref.path = resource.contains("path")
                           ? json_text(resource["path"])
                           : std::string();
            if (resource.contains("parsed_summary") &&
                resource["parsed_summary"].is_object() &&
                resource["parsed_summary"].contains("catalog_asset_id") &&
                resource["parsed_summary"]["catalog_asset_id"].is_string()) {
                ref.catalog_asset_id =
                    resource["parsed_summary"]["catalog_asset_id"]
                        .get<std::string>();
            }
            context.resources.push_back(std::move(ref));
        }
        // Resolved absolute paths (external/missing resources surface in
        // the resolved path / provider error, never as fake input).
        for (auto& resolved :
             pwb::project::resolve_resource_paths(document,
                                                  context.project_file)) {
            for (ResourceRef& ref : context.resources) {
                if (ref.id == resolved.id && !resolved.resolved.empty()) {
                    ref.path = resolved.resolved;
                }
            }
        }
    }

    [[nodiscard]] PredictionTaskJournal* journal(
        CatalogContext& context) const {
        if (context.journal == nullptr) {
            context.journal = std::make_unique<PredictionTaskJournal>(
                context.artifacts_root() / "prediction_tasks.json",
                PredictionTaskJournal::token_for_project_path(
                    context.project_file));
        }
        return context.journal.get();
    }

    [[nodiscard]] static PredictionTaskSlice task_to_slice(const Json& task) {
        PredictionTaskSlice slice;
        slice.id = json_text(task["id"]);
        slice.name = json_text(task["name"]);
        slice.status = json_text(task["status"]);
        slice.adapter_kind = json_text(task["adapter_kind"]);
        if (task.contains("seed") && task["seed"].is_number_integer()) {
            slice.seed = task["seed"].get<std::int64_t>();
        }
        if (task.contains("input_refs") && task["input_refs"].is_object()) {
            for (auto it = task["input_refs"].begin();
                 it != task["input_refs"].end(); ++it) {
                std::vector<std::string> ids;
                for (const auto& id : it.value()) {
                    if (id.is_string()) ids.push_back(id.get<std::string>());
                }
                slice.input_refs[it.key()] = std::move(ids);
            }
        }
        slice.result_summary = task.value("result_summary", Json::object());
        slice.model_metadata = task.value("model_metadata", Json::object());
        slice.probability_summary =
            task.value("probability_summary", Json::object());
        slice.evidence_contribution =
            task.value("evidence_contribution", Json::array());
        if (task.contains("review_areas") && task["review_areas"].is_array()) {
            slice.review_area_count = task["review_areas"].size();
        }
        return slice;
    }

    // ------------------------------------------------------------------
    // Hooks
    // ------------------------------------------------------------------
    [[nodiscard]] std::optional<std::string> production_model_id() {
        auto context = catalog();
        if (context == nullptr) return std::nullopt;
        // try-lock: an in-flight run holds the document for its whole
        // execute — the page's on_run must not freeze the GUI on it.
        // Fall back to the last cached identity (the demo path's answer
        // during a run); "not cached yet + busy" reads as 未配置生产模型,
        // which the single-flight guard turns into a refusal anyway.
        std::unique_lock<std::mutex> lock(document_mutex_,
                                          std::try_to_lock);
        if (!lock.owns_lock()) {
            return cached_production_version_id_.empty()
                       ? std::nullopt
                       : std::optional<std::string>(
                           cached_production_version_id_);
        }
        const catalog::ModelVersion* version = catalog::find_production_model(
            context->core->document(), std::string(kCapabilityFacies));
        if (version == nullptr) return std::nullopt;
        cached_production_version_id_ = version->id;
        return version->id;
    }

    [[nodiscard]] std::optional<std::string> demo_model_id(
        std::string& error) {
        auto context = catalog();
        if (context == nullptr) {
            error = catalog_error();
            return std::nullopt;
        }
        // An in-flight run holds the document: answer from the cache (the
        // seeding happened on the first call and is stable).
        if (!document_mutex_.try_lock()) {
            if (cached_demo_version_id_.empty()) {
                error = "推断进行中，演示模型尚未就绪";
                return std::nullopt;
            }
            return cached_demo_version_id_;
        }
        std::lock_guard<std::mutex> unlock(document_mutex_, std::adopt_lock);
        auto& document = context->core->document();
        auto seeded = ensure_default_models(document,
                                            context->save_hook());
        if (seeded.code != pwb::domain::ErrorCode::Ok) {
            error = seeded.message;
            return std::nullopt;
        }
        auto version = catalog::get_model_version(document, kModelIdDemo, "1");
        if (!version.is_ok()) {
            error = version.error().message;
            return std::nullopt;
        }
        cached_demo_version_id_ = version.value()->id;
        return cached_demo_version_id_;
    }

    [[nodiscard]] std::optional<std::string> resolve_inputs(
        const std::string& model_version_id,
        const std::optional<std::string>& selected_resource_id,
        std::vector<std::string>& input_ids) {
        auto context = catalog();
        if (context == nullptr) return catalog_error();
        // The pages check is_running() before resolving; the lock here is a
        // second line of defence against concurrent document access.
        const std::lock_guard<std::mutex> lock(document_mutex_);
        auto resolved = resolve_model_inputs(
            context->core->document(), context->resources, model_version_id,
            selected_resource_id);
        if (!resolved.is_ok()) return resolved.error().message;
        input_ids = std::move(resolved.value());
        return std::nullopt;
    }

    // Selection-dialog data: try-lock the document so a dialog opened while
    // a run holds the lock degrades to an honest "busy" answer instead of
    // freezing the GUI thread until the run finishes.
    std::vector<WellCandidate> well_candidates(
        const std::optional<std::string>& model_version_id,
        std::string* error) {
        auto context = catalog();
        if (context == nullptr) {
            if (error != nullptr) *error = catalog_error();
            return {};
        }
        std::unique_lock<std::mutex> lock(document_mutex_,
                                          std::try_to_lock);
        if (!lock.owns_lock()) {
            if (error != nullptr) {
                *error = "推断进行中，选择数据请稍后再试";
            }
            return {};
        }
        return list_well_candidates(context->core->document(),
                                    context->resources, model_version_id);
    }

    std::vector<ModelCandidate> model_candidates(std::string* error) {
        auto context = catalog();
        if (context == nullptr) {
            if (error != nullptr) *error = catalog_error();
            return {};
        }
        std::unique_lock<std::mutex> lock(document_mutex_,
                                          std::try_to_lock);
        if (!lock.owns_lock()) {
            if (error != nullptr) {
                *error = "推断进行中，模型选择请稍后再试";
            }
            return {};
        }
        return list_model_candidates(context->core->document());
    }

    [[nodiscard]] bool is_running() {
        const std::lock_guard<std::mutex> lock(worker_mutex_);
        return worker_active_;
    }

    // Cooperative cancel: the provider observes cancel_requested_ at its
    // tile-group seams and execute_run records the terminal "cancelled"
    // status — a late result can never relabel the run as success.
    bool request_cancel() {
        const std::lock_guard<std::mutex> lock(worker_mutex_);
        if (!worker_active_) return false;
        cancel_requested_.store(true);
        return true;
    }

    // The predict.run RunSpec path: single-flight, preflight under the
    // document lock, then the SAME start_inference + launch_worker the
    // page runs use (one execution lifecycle, never a second stack).
    SciencePageBinding::SpecRunResult start_spec_run(
        const pwb::prediction::PredictionRunSpec& spec,
        QPointer<QObject> page) {
        SciencePageBinding::SpecRunResult out;
        {
            const std::lock_guard<std::mutex> lock(worker_mutex_);
            if (worker_active_) {
                out.errors.push_back("已有推断在运行（不可并发运行同一 RunSpec）");
                return out;
            }
        }
        auto context = catalog();
        if (context == nullptr) {
            out.errors.push_back(catalog_error());
            return out;
        }
        PreflightReport preflight;
        {
            // No run is active, so the document lock is free: preflight
            // sees the quiescent catalog the run will open against.
            const std::lock_guard<std::mutex> lock(document_mutex_);
            preflight = preflight_run(context->core->document(),
                                      context->resources, spec,
                                      context->project_dir());
        }
        if (!preflight.ok) {
            out.errors = std::move(preflight.errors);
            return out;
        }
        out.warnings = std::move(preflight.warnings);
        auto run = start_inference(
            context->core->document(), context->save_hook(),
            StartInferenceRequest{preflight.spec.model_version_id,
                                  preflight.input_version_ids,
                                  run_parameters_from_spec(preflight.spec)});
        if (!run.is_ok()) {
            out.errors.push_back(run.error().message);
            return out;
        }
        out.run_id = run.value().id.str();
        std::string launch_error;
        launch_worker(context, out.run_id, page, &launch_error);
        if (!launch_error.empty()) {
            out.errors.push_back(launch_error);
            out.run_id.clear();
            return out;
        }
        // The completion lands in the page's on_inference_completed (queued
        // — it cannot run before this slot returns to the event loop), but
        // the RunSpec path bypasses the page's own start_inference: mark
        // the run in flight here or the session guard drops the payload.
        if (auto* well = qobject_cast<
                pwb::ui_wellseis::qt::WellLogPredictionPage*>(page.data());
            well != nullptr) {
            well->begin_external_run();
        } else if (auto* seismic = qobject_cast<
                       pwb::ui_wellseis::qt::SeismicPredictionPage*>(
                       page.data());
                   seismic != nullptr) {
            seismic->begin_external_run();
        }
        out.started = true;
        return out;
    }

    bool shutdown(int wait_ms) {
        bool finished = true;
        {
            std::unique_lock<std::mutex> lock(worker_mutex_);
            cancel_requested_.store(true);
            if (wait_ms > 0) {
                done_cv_.wait_for(lock, std::chrono::milliseconds(wait_ms),
                                  [this] { return !worker_active_; });
            }
            finished = !worker_active_;
        }
        // A joinable thread must ALWAYS be joined before the member is
        // destroyed (a destroyed joinable thread calls std::terminate and
        // kills the process on exit). After cancel, providers stop at the
        // next tile-group seam, so the unbounded join below is bounded in
        // practice by the provider's cancel responsiveness.
        if (worker_.joinable()) {
            worker_.join();
        }
        return finished;
    }

    [[nodiscard]] RunSlice start_run(
        std::shared_ptr<CatalogContext> context,
        const std::string& model_version_id,
        const std::vector<std::string>& input_ids, Json parameters,
        QPointer<QObject> page, bool* failed, std::string* error_text) {
        RunSlice slice;
        // Refuse BEFORE creating the run: a rejected start must not leave a
        // permanently "running" run behind.
        {
            const std::lock_guard<std::mutex> lock(worker_mutex_);
            if (worker_active_) {
                *failed = true;
                *error_text = "已有推断在运行";
                return slice;
            }
        }
        auto run = start_inference(context->core->document(),
                                   context->save_hook(),
                                   StartInferenceRequest{model_version_id,
                                                         input_ids,
                                                         std::move(parameters)});
        if (!run.is_ok()) {
            *failed = true;
            *error_text = run.error().message;
            return slice;
        }
        slice.id = run.value().id.str();
        slice.status = run.value().status;
        slice.created_at = run.value().created_at;
        slice.parameters = run.value().parameters;
        launch_worker(std::move(context), run.value().id.str(), page,
                      error_text);
        return slice;
    }

    void launch_worker(std::shared_ptr<CatalogContext> context,
                       const std::string& run_id, QPointer<QObject> page,
                       std::string* error_text) {
        const std::string start_token =
            PredictionTaskJournal::token_for_project_path(
                context->project_file);
        auto alive = alive_;
        {
            const std::lock_guard<std::mutex> lock(worker_mutex_);
            if (worker_active_) {
                *error_text = "已有推断在运行";
                return;
            }
            // A previous worker that finished (worker_active_ == false)
            // was never joined — the only join lives in shutdown(). A
            // joinable std::thread must be joined before it is assigned
            // over, or the assignment calls std::terminate() (#1443).
            // The finished thread no longer touches this mutex, so the
            // join under the lock returns promptly.
            if (worker_.joinable()) {
                worker_.join();
            }
            cancel_requested_ = false;
            worker_active_ = true;
            worker_ = std::thread(
                [this, context, run_id, page, start_token, alive]() {
                    ExecuteRunDeps deps;
                    deps.save = context->save_hook();
                    deps.providers = &providers_;
                    deps.project_dir = context->project_dir();
                    deps.artifacts_root = context->artifacts_root();
                    // Poll the binding's cancel flag (shutdown / page
                    // close) at the task runtime's stage seams.
                    auto cancel = [this]() {
                        return cancel_requested_.load();
                    };
                    // Exclusive document access for the whole run: every
                    // GUI hook either takes this lock or falls back to
                    // cached values — never touches the document
                    // concurrently (P0: the catalog document is not
                    // thread-safe).
                    const std::lock_guard<std::mutex> document_lock(
                        document_mutex_);
                    auto outcome = execute_run(context->core->document(),
                                               deps, run_id, cancel);
                    // The queued GUI callback re-checks the project token
                    // ON the GUI thread (reading the host's project state
                    // from this worker thread would be unsynchronized).
                    Json payload = Json::object();
                    if (outcome.is_ok()) {
                        payload["run"] = run_to_json(outcome.value().run);
                        payload["result"] = outcome.value().cancelled
                                                ? Json(nullptr)
                                                : outcome.value().payload;
                    } else {
                        Json failed_run = Json::object();
                        failed_run["id"] = run_id;
                        failed_run["status"] = "failed";
                        Json failed_parameters = Json::object();
                        failed_parameters["error"] = outcome.error().message;
                        failed_run["parameters"] = std::move(failed_parameters);
                        payload["run"] = std::move(failed_run);
                        payload["result"] = Json(nullptr);
                    }
                    if (page != nullptr && alive->load()) {
                        QMetaObject::invokeMethod(
                            page,
                            [this, page, alive, payload, start_token,
                             context]() {
                                if (!alive->load() || page == nullptr) return;
                                // Token guard runs on the GUI thread: a
                                // completion whose project was closed or
                                // switched is dropped for the UI — but the
                                // catalog rows already landed in THAT
                                // project's store, so the task is still
                                // materialized + journaled against the
                                // worker's own context (never invisible in
                                // every project).
                                std::filesystem::path current;
                                if (config_.project_file != nullptr) {
                                    current = config_.project_file();
                                }
                                if (PredictionTaskJournal::
                                        token_for_project_path(current) !=
                                    start_token) {
                                    if (payload.contains("run") &&
                                        payload.contains("result") &&
                                        payload["result"].is_object() &&
                                        !payload["result"].empty()) {
                                        // Journal into the worker's OWN
                                        // project (context), never the
                                        // newly opened one.
                                        (void)materialize_task(
                                            context, payload["run"],
                                            payload["result"],
                                            /*publish=*/false);
                                    }
                                    return;
                                }
                                auto* well =
                                    qobject_cast<
                                        pwb::ui_wellseis::qt::
                                            WellLogPredictionPage*>(
                                        page.data());
                                if (well != nullptr) {
                                    well->on_inference_completed(payload);
                                    return;
                                }
                                auto* seismic =
                                    qobject_cast<
                                        pwb::ui_wellseis::qt::
                                            SeismicPredictionPage*>(
                                        page.data());
                                if (seismic != nullptr) {
                                    seismic->on_inference_completed(payload);
                                }
                            },
                            Qt::QueuedConnection);
                    }
                    {
                        const std::lock_guard<std::mutex> lock(
                            worker_mutex_);
                        worker_active_ = false;
                    }
                    done_cv_.notify_all();
                });
        }
    }

    [[nodiscard]] PredictionTaskSlice materialize_task(
        std::shared_ptr<CatalogContext> context, const Json& run,
        const Json& result, bool publish = true) {
        PredictionTaskOptions options;
        const Json parameters =
            run.contains("parameters") && run["parameters"].is_object()
                ? run["parameters"]
                : Json::object();
        const auto text_at = [&](const Json& object, const char* key) {
            return object.is_object() &&
                           object.contains(key)
                       ? json_text(object[key])
                       : std::string();
        };
        options.workflow = text_at(parameters, "workflow");
        options.name_prefix = text_at(parameters, "name_prefix");
        options.run_id = text_at(run, "id");
        if (run.contains("output_version_ids") &&
            run["output_version_ids"].is_array() &&
            !run["output_version_ids"].empty() &&
            run["output_version_ids"][0].is_string()) {
            options.output_version_id =
                run["output_version_ids"][0].get<std::string>();
        }
        const Json well_ids =
            parameters.contains("well_log_resource_ids")
                ? parameters["well_log_resource_ids"]
                : Json::array();
        for (const auto& id : json_array_strings(well_ids)) {
            if (id.is_string()) {
                options.well_log_resource_ids.push_back(
                    id.get<std::string>());
            }
        }
        const Json seismic_ids =
            parameters.contains("seismic_resource_ids")
                ? parameters["seismic_resource_ids"]
                : Json::array();
        for (const auto& id : json_array_strings(seismic_ids)) {
            if (id.is_string()) {
                options.seismic_resource_ids.push_back(
                    id.get<std::string>());
            }
        }
        Json task;
        {
            const std::lock_guard<std::mutex> lock(document_mutex_);
            task = materialize_prediction_task(context->core->document(),
                                               result, options);
        }
        task["id"] = domain::make_id("task_");
        if (journal(*context) != nullptr) {
            auto recorded = context->journal->record(task);
            if (recorded.code != pwb::domain::ErrorCode::Ok) {
                // link_failed parity: the journal write failing must not
                // hide the completed run — flag it on the task.
                task["model_metadata"]["link_failed"] = true;
            }
        } else {
            task["model_metadata"]["link_failed"] = true;
        }
        // Project-document publish (GUI thread — this hook runs inside the
        // page's materialize_task): ws2/ws3 overlays, the m5 comparison and
        // the pages' own update_state read the "prediction_tasks" section;
        // without this publish a finished run stays invisible to them. A
        // publish failure is flagged on the task, never fabricated.
        // publish=false is the project-switched fallback: journal into the
        // WORKER's project only — publishing there would write the old
        // project's task into the newly opened project's document.
        if (publish && config_.publish_task) {
            const domain::DataError published = config_.publish_task(task);
            if (published.code != domain::ErrorCode::Ok) {
                task["model_metadata"]["publish_failed"] = published.message;
            }
        }
        return task_to_slice(task);
    }

    [[nodiscard]] std::vector<RunSlice> list_runs(
        std::shared_ptr<CatalogContext> context) {
        std::vector<RunSlice> runs;
        // try-lock: the persisted-failure replay must not freeze the GUI
        // while a run holds the document; empty reads as "nothing to
        // replay" until the run lands.
        std::unique_lock<std::mutex> lock(document_mutex_,
                                          std::try_to_lock);
        if (!lock.owns_lock()) return runs;
        for (const catalog::DataRun& run :
             context->core->document().runs) {
            if (run.operation != "prediction") continue;
            RunSlice slice;
            slice.id = run.id.str();
            slice.status = run.status;
            slice.created_at = run.created_at;
            for (const auto& vid : run.output_version_ids) {
                slice.output_version_ids.push_back(vid.str());
            }
            slice.parameters = run.parameters;
            runs.push_back(std::move(slice));
        }
        std::sort(runs.begin(), runs.end(),
                  [](const RunSlice& a, const RunSlice& b) {
                      return a.created_at > b.created_at;
                  });
        if (runs.size() > 20) runs.resize(20);
        return runs;
    }

    void register_export(std::shared_ptr<CatalogContext> context,
                         const std::string& path, const std::string& fmt,
                         const std::vector<std::string>& source_task_ids) {
        PredictionTaskJournal* task_journal = journal(*context);
        if (task_journal == nullptr) return;
        Json export_note = Json{
            {"_kind", "export"},
            {"path", path},
            {"format", fmt},
            {"source_task_ids", source_task_ids},
            {"recorded_at", domain::now_iso8601()}};
        (void)task_journal->record(std::move(export_note));
    }

    [[nodiscard]] std::vector<Json> restored_tasks(
        std::shared_ptr<CatalogContext> context) const {
        std::vector<Json> tasks;
        if (context->journal == nullptr) return tasks;
        auto loaded = context->journal->load();
        if (!loaded.is_ok()) return tasks;
        for (auto& entry : loaded.value()) {
            if (entry.is_object() && entry.contains("_kind") &&
                json_text(entry["_kind"]) == "export") {
                continue;
            }
            tasks.push_back(std::move(entry));
        }
        return tasks;
    }

    Config config_;
    ProviderRegistry providers_;
    std::shared_ptr<std::atomic<bool>> alive_ =
        std::make_shared<std::atomic<bool>>(true);

    std::mutex catalog_mutex_;
    std::shared_ptr<CatalogContext> cached_;

    std::mutex worker_mutex_;  // guards worker_active_ / cancel_requested_
    std::condition_variable done_cv_;
    std::thread worker_;
    bool worker_active_ = false;
    std::atomic<bool> cancel_requested_{false};

    // Serializes every access to the cached CatalogContext's DOCUMENT (the
    // worker thread mutates it for the whole execute_run; GUI hooks either
    // take the lock or fall back to cached values — never touch the
    // document concurrently).
    std::mutex document_mutex_;
    // Values cached on the GUI thread while the document was quiescent, so
    // hooks can answer during an in-flight run without touching it.
    std::string cached_demo_version_id_;
    std::string cached_production_version_id_;
};

// ---------------------------------------------------------------------------
// SciencePageBinding public surface
// ---------------------------------------------------------------------------

SciencePageBinding::SciencePageBinding(Config config, QObject* parent)
    : QObject(parent), impl_(std::make_unique<Impl>(std::move(config))) {}

SciencePageBinding::~SciencePageBinding() = default;

void SciencePageBinding::attach(
    pwb::ui_wellseis::qt::WellLogPredictionPage& well_page,
    pwb::ui_wellseis::qt::SeismicPredictionPage& seismic_page) {
    // The pages keep hooks by value; the lambdas hold the binding alive via
    // `this` (the binding is parent-owned and outlives the pages' shutdown
    // call; hook calls after binding destruction never happen because the
    // pages die with the same shell).
    {
        pwb::ui_wellseis::qt::WellLogPredictionHooks hooks;
        hooks.catalog_connected = [this]() {
            return impl_->catalog() != nullptr;
        };
        hooks.online_route =
            [this](std::string& error) -> std::optional<
            pwb::ui_wellseis::qt::WellLogPredictionHooks::OnlineRoute> {
            error =
                "线上测井预测需要 geoviz_online HTTP 执行器（原生运行时未接"
                "入）";
            return std::nullopt;
        };
        hooks.demo_model_id = [this](std::string& error) {
            return impl_->demo_model_id(error);
        };
        hooks.resolve_inputs =
            [this](const std::string& model_version_id,
                   const std::optional<std::string>& resource_id,
                   std::vector<std::string>& input_ids) {
                return impl_->resolve_inputs(model_version_id, resource_id,
                                             input_ids);
            };
        hooks.resolve_postprocess_inputs = [this](
                                               std::vector<
                                                   std::string>& input_ids) {
            if (auto context = impl_->catalog()) {
                auto extras = resolve_postprocess_inputs(
                    context->core->document(), context->resources);
                for (auto& id : extras) input_ids.push_back(std::move(id));
            }
        };
        hooks.is_running = [this]() { return impl_->is_running(); };
        hooks.start_run =
            [this, &well_page](const std::string& model_version_id,
                               const std::vector<std::string>& input_ids,
                               Json parameters) {
                RunSlice slice;
                auto context = impl_->catalog();
                if (context == nullptr) return slice;
                std::string error_text;
                bool failed = false;
                slice = impl_->start_run(
                    std::move(context), model_version_id, input_ids,
                    std::move(parameters),
                    QPointer<QObject>(&well_page), &failed, &error_text);
                if (failed) {
                    QPointer<QObject> page(&well_page);
                    auto alive = impl_->alive_;
                    QMetaObject::invokeMethod(
                        page,
                        [page, alive, error_text]() {
                            if (!alive->load() || page == nullptr) return;
                            auto* well = qobject_cast<
                                pwb::ui_wellseis::qt::
                                    WellLogPredictionPage*>(page.data());
                            if (well != nullptr) {
                                well->on_inference_failed(error_text);
                            }
                        },
                        Qt::QueuedConnection);
                }
                return slice;
            };
        hooks.materialize_task = [this](const Json& run, const Json& result) {
            auto context = impl_->catalog();
            if (context == nullptr) return PredictionTaskSlice{};
            return impl_->materialize_task(std::move(context), run, result);
        };
        hooks.list_runs = [this]() {
            auto context = impl_->catalog();
            if (context == nullptr) return std::vector<RunSlice>{};
            return impl_->list_runs(std::move(context));
        };
        hooks.shutdown = [this](int wait_ms) {
            return impl_->shutdown(wait_ms);
        };
        hooks.register_export =
            [this](const std::string& path, const std::string& fmt,
                   const std::vector<std::string>& source_task_ids) {
                if (auto context = impl_->catalog()) {
                    impl_->register_export(std::move(context), path, fmt,
                                           source_task_ids);
                }
            };
        hooks.default_export_dir = [this]() {
            std::filesystem::path current;
            if (impl_->config_.project_file != nullptr) {
                current = impl_->config_.project_file();
            }
            if (current.empty()) return std::string();
            return (current.parent_path() / "exports").string();
        };
        well_page.set_hooks(std::move(hooks));
    }
    {
        pwb::ui_wellseis::qt::SeismicPredictionHooks hooks;
        hooks.catalog_connected = [this]() {
            return impl_->catalog() != nullptr;
        };
        hooks.production_model_id = [this]() {
            return impl_->production_model_id();
        };
        hooks.demo_model_id = [this]() -> std::optional<std::string> {
            std::string error;
            return impl_->demo_model_id(error);
        };
        hooks.resolve_inputs =
            [this](const std::string& model_version_id,
                   const std::optional<std::string>& resource_id,
                   std::vector<std::string>& input_ids) {
                return impl_->resolve_inputs(model_version_id, resource_id,
                                             input_ids);
            };
        hooks.is_running = [this]() { return impl_->is_running(); };
        hooks.start_run =
            [this, &seismic_page](const std::string& model_version_id,
                                  const std::vector<std::string>& input_ids,
                                  Json parameters) {
                auto context = impl_->catalog();
                if (context == nullptr) return;
                std::string error_text;
                bool failed = false;
                impl_->start_run(std::move(context), model_version_id,
                                 input_ids, std::move(parameters),
                                 QPointer<QObject>(&seismic_page), &failed,
                                 &error_text);
                if (failed) {
                    QPointer<QObject> page(&seismic_page);
                    auto alive = impl_->alive_;
                    QMetaObject::invokeMethod(
                        page,
                        [page, alive, error_text]() {
                            if (!alive->load() || page == nullptr) return;
                            auto* seismic = qobject_cast<
                                pwb::ui_wellseis::qt::
                                    SeismicPredictionPage*>(page.data());
                            if (seismic != nullptr) {
                                seismic->on_inference_failed(error_text);
                            }
                        },
                        Qt::QueuedConnection);
                }
            };
        hooks.materialize_task = [this](const Json& run, const Json& result) {
            auto context = impl_->catalog();
            if (context == nullptr) return PredictionTaskSlice{};
            return impl_->materialize_task(std::move(context), run, result);
        };
        hooks.shutdown = [this](int wait_ms) {
            return impl_->shutdown(wait_ms);
        };
        seismic_page.set_hooks(std::move(hooks));
    }
}

bool SciencePageBinding::shutdown_workers(int wait_ms) {
    return impl_->shutdown(wait_ms);
}

void SciencePageBinding::set_publish_task(
    std::function<domain::DataError(const Json& task)> publish_task) {
    impl_->config_.publish_task = std::move(publish_task);
}

bool SciencePageBinding::request_cancel() {
    return impl_->request_cancel();
}

bool SciencePageBinding::is_running() const {
    return impl_->is_running();
}

std::vector<WellCandidate> SciencePageBinding::well_candidates(
    const std::optional<std::string>& model_version_id, std::string* error) {
    return impl_->well_candidates(model_version_id, error);
}

std::vector<ModelCandidate> SciencePageBinding::model_candidates(
    std::string* error) {
    return impl_->model_candidates(error);
}

SciencePageBinding::SpecRunResult SciencePageBinding::start_spec_run(
    const pwb::prediction::PredictionRunSpec& spec, QObject* completion_page) {
    return impl_->start_spec_run(spec, QPointer<QObject>(completion_page));
}

std::vector<Json> SciencePageBinding::restored_tasks() const {
    std::filesystem::path current;
    if (impl_->config_.project_file != nullptr) {
        current = impl_->config_.project_file();
    }
    if (current.empty()) return {};
    auto context = impl_->catalog();
    if (context == nullptr) return {};
    return impl_->restored_tasks(std::move(context));
}

SciencePageBinding* attach_prediction_pages(
    pwb::ui_wellseis::qt::WellLogPredictionPage& well_page,
    pwb::ui_wellseis::qt::SeismicPredictionPage& seismic_page,
    std::function<std::filesystem::path()> project_file, QObject* parent) {
    auto* binding = new SciencePageBinding(
        SciencePageBinding::Config{std::move(project_file)}, parent);
    binding->attach(well_page, seismic_page);
    return binding;
}

}  // namespace pwb::closure_science::qt
