#include <pwb/ui_controllers/project_controller.hpp>

#include <pwb/project/paths.hpp>
#include <pwb/project/relocation.hpp>

namespace pwb::ui_controllers {

namespace {

constexpr const char* kProjectSuffix = ".paleo.json";
constexpr const char* kProjectFilter = "Paleo 工程 (*.paleo.json)";

std::string json_str(const domain::Json& object, const char* key) {
    if (!object.is_object()) return {};
    const auto it = object.find(key);
    if (it == object.end() || !it->is_string()) return {};
    return it->get<std::string>();
}

// window._show_project_error — an unset seam is a no-op (getattr parity).
void show_error(const ProjectHostApi& host, const std::string& title,
                const std::string& message) {
    if (host.show_error) host.show_error(title, message);
}

void refresh_shell(const ProjectHostApi& host, bool defer_nonvisible) {
    if (host.refresh_shell) host.refresh_shell(defer_nonvisible);
}

}  // namespace

ProjectControllerCore::ProjectControllerCore(
    ProjectHostApi host, CatalogRuntimeApi catalog_runtime,
    ProjectServiceApi services, ProjectSaveApiFactory save_factory,
    UiJobRunner* save_runner)
    : host_(std::move(host)),
      catalog_(std::move(catalog_runtime)),
      services_(std::move(services)),
      save_factory_(std::move(save_factory)),
      save_runner_(save_runner) {}

// ---------------------------------------------------------------------------
// Session lifecycle
// ---------------------------------------------------------------------------

bool ProjectControllerCore::end_current_session() {
    ++session_generation_;
    if (maintenance_cancel_) maintenance_cancel_->store(true);
    // An in-flight background save must finish (or refuse) before the
    // catalog underneath it closes (#1040).
    if (!drain_save_job()) {
        ++session_generation_;
        return false;
    }
    if (maintenance_running_()) {
        join_maintenance_(std::chrono::milliseconds(500));
        if (maintenance_running_()) {
            ++session_generation_;
            return false;
        }
    }
    // #1126: commit composite edit sessions before teardown — never drop
    // digitized-but-uncommitted vector edits silently.
    if (host_.flush_composite_edits) {
        try {
            host_.flush_composite_edits();
        } catch (const std::exception&) {
        }
    }
    if (host_.shutdown_workers) {
        try {
            if (!host_.shutdown_workers()) {
                ++session_generation_;
                return false;
            }
        } catch (const std::exception&) {
            ++session_generation_;
            return false;
        }
    }
    // Detached (timed-out) jobs still run — teardown under them destroys
    // QApplication state on a live worker thread (C18). The session stays
    // live until the keeper drains.
    if (host_.detached_job_count) {
        try {
            if (host_.detached_job_count() > 0) {
                ++session_generation_;
                return false;
            }
        } catch (const std::exception&) {
            ++session_generation_;
            return false;
        }
    }
    close_catalog_();
    if (catalog_.reset_catalog) {
        try {
            catalog_.reset_catalog();
        } catch (const std::exception&) {
        }
    }
    return true;
}

void ProjectControllerCore::restore_shell_after_failed_stop() {
    refresh_shell(host_, /*defer_nonvisible=*/true);
}

void ProjectControllerCore::close_catalog_() {
    if (catalog_.get_catalog_service) {
        try {
            if (auto* service = catalog_.get_catalog_service()) {
                // #1079: cancel running transcodes before the handle closes.
                if (catalog_.shutdown_lifecycle) {
                    try {
                        catalog_.shutdown_lifecycle(service);
                    } catch (const std::exception&) {
                    }
                }
                service->close();
            }
        } catch (const std::exception&) {
        }
    }
    if (catalog_.clear_session_caches) {
        try {
            catalog_.clear_session_caches();
        } catch (const std::exception&) {
        }
    }
}

std::optional<std::string> ProjectControllerCore::open_catalog_(
    const fs::path& target) {
    if (!catalog_.open_catalog) return std::nullopt;
    try {
        close_catalog_();
        catalog_.open_catalog(target);
        return std::nullopt;
    } catch (const std::exception& error) {
        // Never leave a closed/stale adapter from the previous project
        // installed after a recoverable catalog-open failure.
        if (catalog_.reset_catalog) {
            try {
                catalog_.reset_catalog();
            } catch (const std::exception&) {
            }
        }
        return std::string("CatalogError: ") + error.what();
    }
}

// ---------------------------------------------------------------------------
// Deferred catalog maintenance + staged domain migration
// ---------------------------------------------------------------------------

bool ProjectControllerCore::maintenance_running_() const {
    return maintenance_future_.valid() &&
           maintenance_future_.wait_for(std::chrono::seconds(0)) !=
               std::future_status::ready;
}

void ProjectControllerCore::join_maintenance_(
    std::chrono::milliseconds timeout) {
    if (!maintenance_future_.valid()) return;
    maintenance_future_.wait_for(timeout);
}

void ProjectControllerCore::schedule_catalog_maintenance_(
    const fs::path& target, project::ProjectDocument* loaded) {
    const int generation = session_generation_;
    // The snapshot is taken HERE on the GUI thread so the worker never
    // iterates a section the GUI may mutate.
    domain::Json resources_snapshot = domain::Json::array();
    if (loaded != nullptr) {
        const auto it = loaded->root().find("resources");
        if (it != loaded->root().end() && it->is_array())
            resources_snapshot = *it;
    }
    auto kickoff = [this, generation, target, loaded, resources_snapshot]() {
        auto* live_doc = host_.document ? host_.document() : nullptr;
        const auto live_path =
            host_.project_path ? host_.project_path() : std::nullopt;
        if (generation != session_generation_ || live_doc != loaded ||
            live_path != target) {
            return;
        }
        if (maintenance_cancel_) maintenance_cancel_->store(true);
        auto cancel = std::make_shared<std::atomic<bool>>(false);
        maintenance_cancel_ = cancel;
        maintenance_future_ = std::async(
            std::launch::async,
            [this, generation, target, loaded, resources_snapshot, cancel]() {
                run_catalog_maintenance_(generation, target, loaded,
                                         resources_snapshot, cancel);
            });
    };
    if (host_.post_next_turn) {
        host_.post_next_turn(std::move(kickoff));
    } else {
        kickoff();  // no event loop (tests) — kick off synchronously
    }
}

void ProjectControllerCore::run_catalog_maintenance_(
    int generation, fs::path target, project::ProjectDocument* loaded,
    domain::Json resources_snapshot,
    std::shared_ptr<std::atomic<bool>> cancel) {
    auto stale = [&]() {
        auto* live_doc = host_.document ? host_.document() : nullptr;
        const auto live_path =
            host_.project_path ? host_.project_path() : std::nullopt;
        return generation != session_generation_ ||
               (cancel && cancel->load()) || live_doc != loaded ||
               live_path != target;
    };
    if (stale()) return;
    CatalogServiceApi* service = nullptr;
    if (catalog_.get_catalog_service) {
        try {
            service = catalog_.get_catalog_service();
        } catch (const std::exception&) {
            service = nullptr;
        }
    }
    if (stale()) return;
    if (service != nullptr) {
        try {
            // Warm the lazily-opened document FIRST (#1212).
            service->warm_document();
            try {
                service->recover_working_copies();
            } catch (const std::exception&) {
            }
            service->migrate_legacy_resources(resources_snapshot);
            service->sweep_temp_on_open();
            service->ensure_index_ready();
            try {
                service->repair_ghost_runs();
            } catch (const std::exception&) {
            }
            try {
                if (loaded != nullptr && catalog_.backfill_role_primaries)
                    catalog_.backfill_role_primaries(loaded->root());
            } catch (const std::exception&) {
            }
            try {
                service->migrate_run_ports();
            } catch (const std::exception&) {
            }
            try {
                // #1223: interrupted transcodes/attributes resume on open.
                if (catalog_.resume_lifecycle)
                    catalog_.resume_lifecycle(service);
            } catch (const std::exception&) {
            }
        } catch (const std::exception&) {
            // Canonical project/catalog remain usable even when optional
            // acceleration work cannot complete.
        }
    }
    if (stale()) return;
    // WorkArea domain staging: heavy file parsing only — NO document
    // mutation on this thread (binding lands via post_next_turn).
    try {
        if (!catalog_.build_asset_id_mapping || !catalog_.stage_resources ||
            !host_.post_next_turn)
            return;
        std::map<std::string, std::string> mapping =
            catalog_.build_asset_id_mapping(service);
        auto resolver = [target](const std::string& relative) -> fs::path {
            fs::path raw(relative);
            if (raw.is_absolute()) return raw;
            auto resolved =
                project::resolve_project_path(relative, target);
            return resolved.is_ok() ? fs::path(resolved.value()) : raw;
        };
        auto* live_doc = host_.document ? host_.document() : nullptr;
        if (live_doc == nullptr) return;
        std::any staged = catalog_.stage_resources(
            live_doc->root(), resources_snapshot, resolver,
            [cancel]() { return cancel && cancel->load(); });
        if (stale()) return;
        if (staged.has_value() || !mapping.empty()) {
            const std::string path_text = target.generic_string();
            host_.post_next_turn([this, path_text, generation,
                                  mapping = std::move(mapping),
                                  staged = std::move(staged)]() mutable {
                on_domain_migration_staged(path_text, generation,
                                           std::move(mapping), staged);
            });
        }
    } catch (const std::exception&) {
        // A migration failure must never break the open project.
        return;
    }
}

void ProjectControllerCore::on_domain_migration_staged(
    const std::string& project_path_text, int generation,
    std::map<std::string, std::string> mapping, const std::any& staged) {
    auto* doc = host_.document ? host_.document() : nullptr;
    const auto live_path =
        host_.project_path ? host_.project_path() : std::nullopt;
    if (generation != session_generation_ || doc == nullptr ||
        !live_path || live_path->generic_string() != project_path_text) {
        return;
    }
    if (!catalog_.migrate_project_to_workarea) return;
    CatalogRuntimeApi::MigrationReport report;
    try {
        report = catalog_.migrate_project_to_workarea(
            doc->root(), std::move(mapping), staged);
    } catch (const std::exception&) {
        return;
    }
    const bool changed = report.migrated || report.wells_created > 0 ||
                         report.wells_updated > 0 ||
                         report.surveys_created > 0 ||
                         report.surveys_updated > 0 ||
                         report.links_created > 0 || report.links_updated > 0;
    if (changed && host_.refresh_domain_views) {
        try {
            host_.refresh_domain_views();
        } catch (const std::exception&) {
        }
    }
}

// ---------------------------------------------------------------------------
// Project operations
// ---------------------------------------------------------------------------

void ProjectControllerCore::new_project(const std::string& name) {
    if (!end_current_session()) {
        restore_shell_after_failed_stop();
        show_error(host_, "切换工程失败",
                   "当前工程仍有未停止的后台任务。");
        return;
    }
    if (host_.replace_document) {
        host_.replace_document(
            project::ProjectDocument::create_new(name, ""));
    }
    if (host_.set_project_path) host_.set_project_path(std::nullopt);
    refresh_shell(host_, /*defer_nonvisible=*/true);
}

bool ProjectControllerCore::open_project_path(const fs::path& path) {
    last_open_error_.clear();
    const fs::path target = path;
    if (!services_.load_project) {
        last_open_error_ = "无法打开工程文件：\n" + target.generic_string();
        return false;
    }
    auto loaded = services_.load_project(target);
    if (!loaded.is_ok()) {
        const auto& error = loaded.error();
        // manager.py open-path failure-class parity: NotFound → 文件不存在,
        // CorruptJson → 损坏/格式无效, PathEscape → 相对路径非法,
        // RecoveryRequired/FutureSchema → honest refusal,
        // IoError → transient unreadable (never a .bak fallback).
        switch (error.code) {
            case domain::ErrorCode::NotFound:
                last_open_error_ =
                    "文件不存在：\n" + target.generic_string();
                break;
            case domain::ErrorCode::CorruptJson:
                last_open_error_ = "工程文件 JSON 损坏：\n" +
                                   target.generic_string() + "\n" +
                                   error.message;
                break;
            case domain::ErrorCode::PathEscape:
                last_open_error_ =
                    "工程内相对路径非法（疑似逃出工程目录）：\n" +
                    target.generic_string() + "\n" + error.message;
                break;
            case domain::ErrorCode::FutureSchema:
                last_open_error_ = "工程文件格式无效（更高 schema 版本）：\n" +
                                   target.generic_string() + "\n" +
                                   error.message;
                break;
            case domain::ErrorCode::IoError:
                last_open_error_ =
                    "工程文件暂时不可读（可能被占用），未回退到备份以免覆盖"
                    "较新内容：\n" +
                    target.generic_string() + "\n" + error.message +
                    "\n请关闭占用该文件的程序后重试。";
                break;
            default:
                last_open_error_ = "无法读取工程文件：\n" +
                                   target.generic_string() + "\n" +
                                   error.message;
                break;
        }
        return false;
    }
    // The old shell may own native sessions/workers that still point at its
    // document/catalog. Tear it down before publishing the new project.
    if (!end_current_session()) {
        restore_shell_after_failed_stop();
        last_open_error_ =
            "当前工程仍有未停止的后台任务，无法安全切换。";
        return false;
    }
    project::ProjectDocument document = std::move(loaded.value().document);
    document.root()["meta"]["project_root"] =
        fs::absolute(target).parent_path().generic_string();
    if (host_.replace_document)
        host_.replace_document(std::move(document));
    if (host_.set_project_path) host_.set_project_path(target);
    auto* live_doc = host_.document ? host_.document() : nullptr;
    if (const auto catalog_error = open_catalog_(target)) {
        // The project opened; the catalog is degraded, not fatal — and it
        // MUST be shown, not just stored (audit A4).
        last_open_error_ = "目录元数据不可用：\n" + target.generic_string() +
                           "\n" + *catalog_error;
        show_error(host_, "目录元数据不可用",
                   "工程已打开，但数据目录元数据不可用（分类 / 标签 / 溯源"
                   "功能受限）。\n" +
                       target.generic_string() + "\n" + *catalog_error);
    }
    refresh_shell(host_, /*defer_nonvisible=*/true);
    if (live_doc != nullptr) schedule_catalog_maintenance_(target, live_doc);
    return true;
}

bool ProjectControllerCore::open_sample_project(
    const std::optional<fs::path>& data_root) {
    // The sample project is unsaved/in-memory → no catalog. Reset BEFORE
    // bootstrapping so sample imports never write into the previous
    // project's catalog (cross-project pollution).
    if (!end_current_session()) {
        restore_shell_after_failed_stop();
        show_error(host_, "打开样例工程失败",
                   "当前工程仍有未停止的后台任务。");
        return false;
    }
    if (!services_.bootstrap_sample) return false;
    auto result = services_.bootstrap_sample(data_root);
    if (!result.is_ok()) {
        show_error(host_, "打开样例工程失败", result.error().message);
        return false;
    }
    if (host_.replace_document) {
        host_.replace_document(std::move(result.value().document));
    }
    if (services_.ensure_demo_prediction && host_.document) {
        if (auto* doc = host_.document())
            services_.ensure_demo_prediction(*doc);
    }
    if (host_.set_project_path) host_.set_project_path(std::nullopt);
    refresh_shell(host_, /*defer_nonvisible=*/false);
    return true;
}

bool ProjectControllerCore::create_project_from_document(
    project::ProjectDocument&& doc, const fs::path& intermediate_dir) {
    if (!end_current_session()) {
        restore_shell_after_failed_stop();
        show_error(host_, "切换工程失败",
                   "当前工程仍有未停止的后台任务。");
        return false;
    }
    const std::string name =
        doc.meta() ? doc.meta()->name : std::string("project");
    fs::path target = normalize_project_path(
        intermediate_dir / (name + kProjectSuffix));
    if (fs::exists(target)) {
        show_error(host_, "新建工程失败",
                   "目标已存在：\n" + target.generic_string());
        return false;
    }
    project::ProjectManager manager(target);
    auto stats = manager.save(doc);
    if (!stats.is_ok()) {
        show_error(host_, "新建工程失败", stats.error().message);
        return false;
    }
    if (host_.replace_document)
        host_.replace_document(std::move(doc));
    if (host_.set_project_path) host_.set_project_path(target);
    if (const auto catalog_error = open_catalog_(target)) {
        show_error(host_, "目录元数据不可用",
                   "工程已创建，但数据目录元数据不可用（分类 / 标签 / 溯源"
                   "功能受限）。\n" +
                       target.generic_string() + "\n" + *catalog_error);
    }
    refresh_shell(host_, /*defer_nonvisible=*/true);
    auto* live_doc = host_.document ? host_.document() : nullptr;
    try {
        if (live_doc != nullptr)
            schedule_catalog_maintenance_(target, live_doc);
    } catch (const std::exception&) {
    }
    return true;
}

// ---------------------------------------------------------------------------
// Saves
// ---------------------------------------------------------------------------

void ProjectControllerCore::flush_composite_vector_edits_() {
    if (!host_.flush_composite_edits) return;
    try {
        host_.flush_composite_edits();
    } catch (const std::exception&) {
    }
}

bool ProjectControllerCore::save_job_running() const {
    return save_runner_ != nullptr && save_runner_->is_running();
}

bool ProjectControllerCore::drain_save_job(int wait_ms) {
    if (save_runner_ == nullptr || !save_runner_->is_running()) {
        save_task_state_.reset();
        return true;
    }
    // Capture the task state BEFORE shutdown: the runner releases its
    // worker identity while joining, so reading afterwards always misses
    // the completed outcome (re-review finding).
    auto task_state = save_task_state_;
    const bool joined = save_runner_->shutdown(wait_ms);
    save_task_state_.reset();
    if (!joined) {
        // The detached worker still writes the project file; the
        // detached-keeper gate in end_current_session keeps teardown from
        // proceeding underneath it. Retained for observability.
        return false;
    }
    const auto live_path =
        host_.project_path ? host_.project_path() : std::nullopt;
    if (task_state &&
        may_commit_drained_save(*task_state, live_path)) {
        // The drain beat the queued saved-delivery: commit the finished
        // write HERE — the file already changed while the snapshot still
        // holds the old baseline; dropping the commit would make the next
        // save raise a false stale-write refusal (review C1).
        auto* doc = host_.document ? host_.document() : nullptr;
        try {
            if (doc != nullptr) {
                task_state->api->commit_save(*doc, task_state->prepared,
                                             *task_state->outcome_stats);
                task_state->committed.store(true);
                register_persisted_factor_grids_(
                    task_state->api->project_path());
            }
        } catch (const std::exception& error) {
            show_error(host_, "保存工程失败", error.what());
        }
    }
    return joined;
}

std::optional<fs::path> ProjectControllerCore::save_project() {
    if (!drain_save_job()) {
        show_error(host_, "保存工程失败",
                   "后台保存线程未能停止，请稍后重试。");
        return std::nullopt;
    }
    if (host_.flush_mapping_draft && !host_.flush_mapping_draft()) {
        show_error(host_, "保存工程失败",
                   "编图草稿未通过拓扑检查，工程文件未写入。请修复拓扑问题"
                   "后重试。");
        return std::nullopt;
    }
    flush_composite_vector_edits_();
    auto* doc = host_.document ? host_.document() : nullptr;
    if (doc != nullptr && host_.flush_joint_analysis) {
        try {
            host_.flush_joint_analysis(*doc);
        } catch (const std::exception&) {
        }
    }
    const auto live_path =
        host_.project_path ? host_.project_path() : std::nullopt;
    if (live_path) {
        if (doc == nullptr || !save_factory_) return std::nullopt;
        try {
            doc->root()["meta"]["project_root"] =
                fs::absolute(*live_path).parent_path().generic_string();
            auto api = save_factory_(*live_path);
            auto prepared = api->prepare_save(*doc);
            if (!prepared.is_ok()) {
                show_error(host_, "保存工程失败",
                           prepared.error().message);
                return std::nullopt;
            }
            auto stats = api->execute_save(prepared.value());
            if (!stats.is_ok()) {
                show_error(host_, "保存工程失败", stats.error().message);
                return std::nullopt;
            }
            api->commit_save(*doc, prepared.value(), stats.value());
            register_persisted_factor_grids_(*live_path);
        } catch (const std::exception& error) {
            show_error(host_, "保存工程失败", error.what());
            return std::nullopt;
        }
        return live_path;
    }
    const std::optional<fs::path> chosen =
        host_.choose_save_project ? host_.choose_save_project() : std::nullopt;
    return save_project_as(chosen);
}

bool ProjectControllerCore::save_project_async() {
    if (save_job_running()) return false;  // one background save at a time
    if (host_.flush_mapping_draft && !host_.flush_mapping_draft()) {
        show_error(host_, "保存工程失败",
                   "编图草稿未通过拓扑检查，工程文件未写入。请修复拓扑问题"
                   "后重试。");
        return false;
    }
    flush_composite_vector_edits_();
    auto* doc = host_.document ? host_.document() : nullptr;
    if (doc != nullptr && host_.flush_joint_analysis) {
        try {
            host_.flush_joint_analysis(*doc);
        } catch (const std::exception&) {
        }
    }
    const auto live_path =
        host_.project_path ? host_.project_path() : std::nullopt;
    if (!live_path) {
        // Save-as relocates artifacts and rebinds the catalog — stays on
        // the synchronous path until that flow is split too.
        const std::optional<fs::path> chosen =
            host_.choose_save_project ? host_.choose_save_project()
                                      : std::nullopt;
        return save_project_as(chosen).has_value();
    }
    if (doc == nullptr || save_runner_ == nullptr || !save_factory_) {
        return false;
    }
    std::shared_ptr<ProjectSaveApi> api;
    project::PreparedSave prepared;
    try {
        doc->root()["meta"]["project_root"] =
            fs::absolute(*live_path).parent_path().generic_string();
        api = save_factory_(*live_path);
        auto result = api->prepare_save(*doc);
        if (!result.is_ok()) {
            show_error(host_, "保存工程失败", result.error().message);
            return false;
        }
        prepared = result.value();
    } catch (const std::exception& error) {
        show_error(host_, "保存工程失败", error.what());
        return false;
    }
    auto task_state = std::make_shared<ProjectSaveTaskState>();
    task_state->generation = session_generation_;
    task_state->api = api;
    task_state->prepared = prepared;
    job::JobSpec spec =
        make_project_save_job_spec(api, prepared, task_state);
    save_runner_->start(
        std::move(spec),
        [this, task_state](const UiJobOutcome& outcome) {
            finish_async_save_(outcome, task_state);
        });
    save_task_state_ = task_state;
    return true;
}

void ProjectControllerCore::finish_async_save_(
    const UiJobOutcome& outcome,
    std::shared_ptr<ProjectSaveTaskState> task_state) {
    if (outcome.state == job::JobState::failed) {
        show_error(host_, "保存工程失败", outcome.error);
        return;
    }
    if (outcome.state == job::JobState::cancelled) return;
    if (task_state->generation != session_generation_) {
        // The project was switched/replaced mid-save. The write for the
        // old path already completed; committing the persistence snapshot
        // onto the NEW live document would corrupt its dirty tracking —
        // drop the commit and let the next save re-diff.
        return;
    }
    auto* doc = host_.document ? host_.document() : nullptr;
    const auto* stats = outcome.try_result<project::SaveStats>();
    if (doc == nullptr || stats == nullptr) return;
    try {
        task_state->api->commit_save(*doc, task_state->prepared, *stats);
        task_state->committed.store(true);
        register_persisted_factor_grids_(task_state->api->project_path());
    } catch (const std::exception& error) {
        show_error(host_, "保存工程失败", error.what());
    }
}

std::optional<fs::path> ProjectControllerCore::save_project_as(
    const std::optional<fs::path>& path) {
    if (!path) return std::nullopt;
    // Same-writer guarantee (review C2): even a same-path Save As must
    // not race the in-flight async write.
    if (!drain_save_job()) {
        show_error(host_, "另存为失败",
                   "后台保存线程未能停止，请稍后重试。");
        return std::nullopt;
    }
    if (host_.flush_mapping_draft && !host_.flush_mapping_draft()) {
        show_error(host_, "保存工程失败",
                   "编图草稿未通过拓扑检查，工程文件未写入。请修复拓扑问题"
                   "后重试。");
        return std::nullopt;
    }
    auto* doc = host_.document ? host_.document() : nullptr;
    if (doc != nullptr && host_.flush_joint_analysis) {
        try {
            host_.flush_joint_analysis(*doc);
        } catch (const std::exception&) {
        }
    }
    const fs::path target = normalize_project_path(*path);
    const auto old_path =
        host_.project_path ? host_.project_path() : std::nullopt;
    std::string old_root;
    if (doc != nullptr && doc->meta()) old_root = doc->meta()->project_root;
    std::optional<project::StagedArtifactRelocation> relocation;
    // A timed-out worker remains attached to the current project/catalog.
    // Do not enter the rollback path: it rebases runtime paths and
    // refreshes the shell, both of which would disturb that live session.
    if (old_path && *old_path != target && !end_current_session()) {
        restore_shell_after_failed_stop();
        show_error(host_, "另存为失败",
                   "当前工程仍有未停止的后台任务，无法安全另存为。");
        return std::nullopt;
    }
    try {
        // Re-home <old>.artifacts/ BEFORE writing the project file —
        // payloads + catalog travel with the project (no orphan-on-save-as).
        if (old_path && *old_path != target) {
            if (fs::exists(project::artifact_dir_for(target))) {
                throw std::runtime_error(
                    "Save As 目标已存在工程成果目录；为避免混合两个工程的"
                    "数据，请选择空目标路径。");
            }
            auto staged = project::StagedArtifactRelocation::stage(
                *old_path, target);
            if (!staged.is_ok()) {
                throw std::runtime_error(staged.error().message);
            }
            relocation = std::move(staged.value());
            rebase_factor_grid_artifact_paths_(*old_path, target);
            rebase_interpretation_artifact_paths_(*old_path, target);
            // The copied catalog belongs to the target before its project
            // JSON lands — rebase it now so an interruption can never
            // leave a valid target pointing at the old artifact dir.
            rebase_staged_catalog_artifact_paths_(target);
        }
        if (doc == nullptr) return std::nullopt;
        doc->root()["meta"]["project_root"] =
            fs::absolute(target).parent_path().generic_string();
        project::ProjectManager manager(target);
        auto stats = manager.save(*doc);
        if (!stats.is_ok()) {
            throw std::runtime_error(stats.error().message);
        }
    } catch (const std::exception& error) {
        if (relocation) relocation->rollback();
        if (old_path && *old_path != target) {
            rebase_factor_grid_artifact_paths_(target, *old_path);
            rebase_interpretation_artifact_paths_(target, *old_path);
            if (doc != nullptr) {
                doc->root()["meta"]["project_root"] = old_root;
            }
            if (host_.set_project_path) host_.set_project_path(old_path);
            open_catalog_(*old_path);
            refresh_shell(host_, /*defer_nonvisible=*/false);
        }
        show_error(host_, "保存工程失败", error.what());
        return std::nullopt;
    }
    if (host_.set_project_path) host_.set_project_path(target);
    // The catalog is bound to the project path: rebind to the new location
    // (best-effort — a catalog failure never blocks saving).
    open_catalog_(target);
    if (old_path && *old_path != target) {
        // _end_current_session deliberately released the old shell's
        // native/worker state before moving its artifacts — rebuild only
        // after the new path + catalog are authoritative.
        refresh_shell(host_, /*defer_nonvisible=*/false);
    }
    auto* live_doc = host_.document ? host_.document() : nullptr;
    if (live_doc != nullptr)
        schedule_catalog_maintenance_(target, live_doc);
    register_persisted_factor_grids_(target);
    if (relocation) {
        try {
            if (!relocation->commit()) {
                show_error(host_, "另存为后清理失败",
                           "新工程已保存，但旧成果目录未能清理。");
            }
        } catch (const std::exception& error) {
            show_error(host_, "另存为后清理失败",
                       std::string("新工程已保存，但旧成果目录未能清理：") +
                           error.what());
        }
    }
    return target;
}

void ProjectControllerCore::rebase_staged_catalog_artifact_paths_(
    const fs::path& target) {
    // Commit target-catalog path rebasing before target JSON publication.
    if (!catalog_.open_catalog) return;
    auto* service = catalog_.open_catalog(target);  // may throw — caller handles
    if (service != nullptr) {
        try {
            service->rebase_artifact_paths();
        } catch (...) {
            service->close();
            throw;
        }
        service->close();
    }
}

void ProjectControllerCore::register_persisted_factor_grids_(
    const fs::path& project_path) {
    if (!catalog_.register_persisted_factor_grids) return;
    auto* doc = host_.document ? host_.document() : nullptr;
    if (doc == nullptr) return;
    try {
        if (catalog_.register_persisted_factor_grids(doc->root())) {
            // Stored version ids/managed paths must reach the portable file.
            project::ProjectManager manager(project_path);
            manager.save(*doc);
        }
    } catch (const std::exception&) {
        // Catalog provenance is best-effort; the already-written project
        // stays usable and registers on a later save (H14 — logged upstream).
    }
}

void ProjectControllerCore::rebase_factor_grid_artifact_paths_(
    const fs::path& old_path, const fs::path& new_path) {
    auto* doc = host_.document ? host_.document() : nullptr;
    if (doc == nullptr) return;
    const fs::path old_root = fs::absolute(project::artifact_dir_for(old_path));
    const fs::path new_root = fs::absolute(project::artifact_dir_for(new_path));
    const fs::path old_dir = fs::absolute(old_path).parent_path();
    auto& tasks = doc->root()["factor_map_tasks"];
    if (!tasks.is_array()) return;
    for (auto& task : tasks) {
        const std::string raw = json_str(task, "grid_artifact_path");
        if (raw.empty()) continue;
        if (auto rebased = project::rebase_owned_artifact_path(
                raw, old_root, new_root, old_dir)) {
            task["grid_artifact_path"] = *rebased;
        }
    }
}

void ProjectControllerCore::rebase_interpretation_artifact_paths_(
    const fs::path& old_path, const fs::path& new_path) {
    auto* doc = host_.document ? host_.document() : nullptr;
    if (doc == nullptr) return;
    const fs::path old_root = fs::absolute(project::artifact_dir_for(old_path));
    const fs::path new_root = fs::absolute(project::artifact_dir_for(new_path));
    const fs::path old_dir = fs::absolute(old_path).parent_path();
    for (const char* section : {"horizon_interpretations",
                                "correlation_interpretations",
                                "fault_interpretations"}) {
        auto& refs = doc->root()[section];
        if (!refs.is_array()) continue;
        for (auto& interpretation : refs) {
            const std::string raw = json_str(interpretation, "artifact_path");
            if (raw.empty()) continue;
            if (auto rebased = project::rebase_owned_artifact_path(
                    raw, old_root, new_root, old_dir)) {
                interpretation["artifact_path"] = *rebased;
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Dialog-facing helpers
// ---------------------------------------------------------------------------

std::string ProjectControllerCore::project_properties_text() const {
    auto* doc = host_.document ? host_.document() : nullptr;
    const auto live_path =
        host_.project_path ? host_.project_path() : std::nullopt;
    const std::string path_str =
        live_path ? live_path->generic_string() : "未保存";
    if (doc == nullptr) {
        return "工程名称: \n工程文件: " + path_str;
    }
    const auto& root = doc->root();
    const auto& meta = root.contains("meta") ? root["meta"] : domain::Json::object();
    auto count_of = [&](const char* key) -> std::size_t {
        const auto it = root.find(key);
        return (it != root.end() && it->is_array()) ? it->size() : 0;
    };
    const auto& coord =
        root.contains("coordinate") ? root["coordinate"] : domain::Json::object();
    return std::string("工程名称: ") + json_str(meta, "name") +
           "\n区域: " +
           (json_str(meta, "region").empty() ? "—" : json_str(meta, "region")) +
           "\n工程文件: " + path_str +
           "\n资源数量: " + std::to_string(count_of("resources")) +
           "\n导出图件: " + std::to_string(count_of("export_artifacts")) +
           "\n显示坐标系: " + json_str(coord, "display_crs") +
           "\n版本: " + json_str(meta, "version");
}

fs::path ProjectControllerCore::normalize_project_path(const fs::path& path) {
    const std::string name = path.filename().generic_string();
    if (name.size() >= std::string(kProjectSuffix).size() &&
        name.compare(name.size() - std::string(kProjectSuffix).size(),
                     std::string(kProjectSuffix).size(), kProjectSuffix) == 0) {
        return path;
    }
    std::string stem = name;
    if (stem.size() >= 5 && stem.compare(stem.size() - 5, 5, ".json") == 0) {
        stem.resize(stem.size() - 5);
    }
    return path.parent_path() / (stem + kProjectSuffix);
}

std::string ProjectControllerCore::default_project_start_dir(
    const std::optional<fs::path>& project_path,
    const std::vector<fs::path>& workspace_roots, const fs::path& home) {
    if (project_path) return project_path->parent_path().generic_string();
    for (const auto& parent : workspace_roots) {
        const fs::path candidate = parent / "data" / "project_area";
        if (fs::is_directory(candidate)) return candidate.generic_string();
    }
    return home.generic_string();
}

}  // namespace pwb::ui_controllers
