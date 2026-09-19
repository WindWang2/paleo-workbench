#include <pwb/ui_controllers/workflow_controller.hpp>

#include <algorithm>

#include <pwb/prediction/spatial_result.hpp>

namespace pwb::ui_controllers {

namespace {

std::string json_str(const domain::Json& object, const char* key) {
    if (!object.is_object()) return {};
    const auto it = object.find(key);
    if (it == object.end() || !it->is_string()) return {};
    return it->get<std::string>();
}

bool json_truthy(const domain::Json& object, const char* key) {
    const auto it = object.find(key);
    if (it == object.end()) return false;
    if (it->is_boolean()) return it->get<bool>();
    if (it->is_number()) return it->get<double>() != 0.0;
    if (it->is_string()) return !it->get<std::string>().empty();
    return !it->is_null();
}

// getattr(resource, "id", "") across every handle shape.
std::string handle_id(const AssetHandle& item) {
    if (!item) return {};
    const ui_data_core::AssetObjectData* data = &*item;
    if (const auto* view = std::get_if<std::shared_ptr<AssetView>>(data);
        view != nullptr && *view && (*view)->raw_asset) {
        data = (*view)->raw_asset.get();
    }
    if (const auto* resource = std::get_if<ResourceItem>(data))
        return resource->id;
    if (const auto* ref = std::get_if<SqlCatalogAssetRef>(data))
        return ref->id;
    if (const auto* asset =
            std::get_if<std::shared_ptr<const catalog::DataAsset>>(data))
        return (*asset)->id.str();
    if (const auto* artifact = std::get_if<ExportArtifact>(data))
        return artifact->id;
    if (const auto* generic = std::get_if<GenericAsset>(data))
        return json_str(generic->attrs, "id");
    return {};
}

std::string join(const std::vector<std::string>& parts,
                 const std::string& sep) {
    std::string out;
    for (std::size_t i = 0; i < parts.size(); ++i) {
        if (i) out += sep;
        out += parts[i];
    }
    return out;
}

}  // namespace

// ---------------------------------------------------------------------------
// Recompute worker body
// ---------------------------------------------------------------------------

RecomputeRunResult run_recompute(
    const domain::Json& project_root_snapshot, int generation,
    const std::function<workflow_runtime::RecomputePlan(
        const domain::Json& project_root)>& build_plan,
    const FactorRecomputeSeams& factor_seams, job::JobContext& ctx) {
    if (!build_plan) {
        throw std::runtime_error(
            "RuntimeError: build_affected_products_plan seam unavailable");
    }
    RecomputeRunResult payload;
    payload.generation = generation;
    payload.plan = build_plan(project_root_snapshot);

    // The task rows the factor_map handler needs ride the snapshot — the
    // live document is NEVER read/mutated on this thread (C05).
    const domain::Json* tasks = nullptr;
    const auto it = project_root_snapshot.find("factor_map_tasks");
    if (it != project_root_snapshot.end() && it->is_array()) tasks = &*it;

    workflow_runtime::StepHandler factor_handler =
        [&](const workflow_runtime::RecomputeStep& step) {
            const std::string task_id =
                step.domain_task_id ? *step.domain_task_id : "";
            if (task_id.empty()) {
                throw std::runtime_error(
                    "factor_map 步骤缺少任务 id (run " +
                    (step.run_id ? *step.run_id : std::string("?")) + ")");
            }
            const domain::Json* task = nullptr;
            if (tasks != nullptr) {
                for (const auto& candidate : *tasks) {
                    if (json_str(candidate, "id") == task_id) {
                        task = &candidate;
                        break;
                    }
                }
            }
            if (task == nullptr) {
                throw std::runtime_error("未找到单因素任务 '" + task_id +
                                         "'");
            }
            ctx.check_cancelled();
            // Stage a deep copy — Json value semantics give it for free.
            domain::Json staged = *task;
            // Re-run with the task's OWN recorded algorithm parameters —
            // the host binds interpolation_params_from_task +
            // apply_interpolation_to_task (#919).
            if (factor_seams.interpolate_fn) {
                factor_seams.interpolate_fn(staged, project_root_snapshot);
            }
            if (factor_seams.grid_peek_fn) {
                payload.grids[task_id] = factor_seams.grid_peek_fn(task_id);
            }
            payload.task_updates.emplace_back(task_id, std::move(staged));
        };

    workflow_runtime::PlanExecutor executor(
        {{"factor_map", std::move(factor_handler)}});
    payload.result = executor.execute(payload.plan);
    return payload;
}

job::JobSpec make_recompute_job_spec(
    domain::Json project_root_snapshot, int generation,
    std::function<workflow_runtime::RecomputePlan(const domain::Json&)>
        build_plan,
    FactorRecomputeSeams factor_seams) {
    job::JobSpec spec;
    spec.kind = "compute.recompute";
    spec.title = "更新受影响成果";
    spec.run = [snapshot = std::move(project_root_snapshot), generation,
                build_plan = std::move(build_plan),
                factor_seams = std::move(factor_seams)](
                   job::JobContext& ctx) -> std::any {
        return run_recompute(snapshot, generation, build_plan,
                             factor_seams, ctx);
    };
    return spec;
}

// ---------------------------------------------------------------------------
// Core
// ---------------------------------------------------------------------------

WorkflowCore::WorkflowCore(
    WorkflowPageApi pages, WorkflowDialogApi dialogs,
    WorkflowServiceApi services, CatalogRuntimeApi catalog,
    PrepareGenerationApi generation, LiveFactorGridApi grids,
    FactorRecomputeSeams factor_recompute,
    ui_workers::FactorPrepareSeams prepare_seams,
    UiJobRunner* recompute_job, UiJobRunner* prepare_job)
    : pages_(std::move(pages)),
      dialogs_(std::move(dialogs)),
      services_(std::move(services)),
      catalog_(std::move(catalog)),
      generation_(std::move(generation)),
      grids_(std::move(grids)),
      factor_recompute_(std::move(factor_recompute)),
      prepare_seams_(std::move(prepare_seams)),
      recompute_job_(recompute_job),
      prepare_job_(prepare_job) {}

project::ProjectDocument* WorkflowCore::document() const {
    return pages_.document ? pages_.document() : nullptr;
}

domain::Json WorkflowCore::root_section_(const char* key) const {
    auto* doc = document();
    if (doc == nullptr) return domain::Json(nullptr);
    const auto it = doc->root().find(key);
    return it != doc->root().end() ? *it : domain::Json(nullptr);
}

std::string WorkflowCore::project_crs_() const {
    const auto coordinate = root_section_("coordinate");
    return json_str(coordinate, "project_crs");
}

void WorkflowCore::info_(const std::string& title,
                         const std::string& text) const {
    if (dialogs_.info) dialogs_.info(title, text);
}
void WorkflowCore::warning_(const std::string& title,
                            const std::string& text) const {
    if (dialogs_.warning) dialogs_.warning(title, text);
}

// ---------------------------------------------------------------------------
// Preview settings
// ---------------------------------------------------------------------------

void WorkflowCore::show_preview_settings() {
    if (!dialogs_.preview_settings_editor) return;
    const domain::Json current =
        pages_.preview_settings ? pages_.preview_settings()
                                : domain::Json::object();
    const std::string mode =
        pages_.preview_mode ? pages_.preview_mode() : std::string();
    const auto applied = dialogs_.preview_settings_editor(current, mode);
    if (applied) apply_preview_settings(*applied);
}

void WorkflowCore::apply_preview_settings(const domain::Json& settings) {
    // Route to the current shell, never a stale page — the seam resolves
    // the live reader panel each call.
    if (pages_.set_preview_settings) pages_.set_preview_settings(settings);
}

// ---------------------------------------------------------------------------
// Page-update fan-out
// ---------------------------------------------------------------------------

void WorkflowCore::update_home_() const {
    auto* doc = document();
    if (doc == nullptr || !pages_.update_home_page) return;
    domain::Json state(nullptr), steps(nullptr);
    if (services_.dashboard_state) {
        try {
            state = services_.dashboard_state(doc->root());
        } catch (const std::exception&) {
        }
    }
    if (services_.home_workflow_steps) {
        try {
            steps = services_.home_workflow_steps(doc->root());
        } catch (const std::exception&) {
        }
    }
    pages_.update_home_page(state, steps);
}

void WorkflowCore::refresh_home_steps() {
    if (document() == nullptr) return;
    update_home_();
    refresh_data_page();
}

void WorkflowCore::refresh_data_page() {
    // dashboard_state + resources + export_artifacts — the produce→browse
    // refresh (factor grids / predictions / QC register catalog versions).
    auto* doc = document();
    if (doc == nullptr || !pages_.update_data_page) return;
    domain::Json state(nullptr);
    if (services_.dashboard_state) {
        try {
            state = services_.dashboard_state(doc->root());
        } catch (const std::exception&) {
            return;  // Python try/except: pass — a failed state build
                     // skips the whole update.
        }
    }
    try {
        pages_.update_data_page(state, root_section_("resources"),
                                root_section_("export_artifacts"));
    } catch (const std::exception&) {
    }
}

void WorkflowCore::update_mapping_() const {
    if (pages_.update_mapping_page) {
        pages_.update_mapping_page(root_section_("paleomap_documents"),
                                   root_section_("factor_map_tasks"),
                                   project_crs_());
    }
}

void WorkflowCore::on_qc_reports_updated() {
    update_home_();
    if (pages_.update_review_export_page) {
        domain::Json reports(nullptr);
        if (services_.active_quality_reports) {
            try {
                auto* doc = document();
                if (doc != nullptr)
                    reports = services_.active_quality_reports(doc->root());
            } catch (const std::exception&) {
            }
        }
        pages_.update_review_export_page(
            reports, root_section_("paleomap_documents"),
            root_section_("export_artifacts"));
    }
    refresh_data_page();
}

void WorkflowCore::on_well_log_prediction_updated() {
    on_seismic_prediction_updated();
}

void WorkflowCore::on_seismic_prediction_updated() {
    update_home_();
    const auto tasks = root_section_("prediction_tasks");
    if (pages_.update_seismic_prediction_page)
        pages_.update_seismic_prediction_page(tasks);
    if (pages_.update_well_log_prediction_page)
        pages_.update_well_log_prediction_page(tasks);
    if (pages_.update_visualization_page) {
        pages_.update_visualization_page(root_section_("resources"), tasks,
                                         root_section_(
                                             "paleomap_documents"));
    }
    refresh_data_page();
}

void WorkflowCore::on_factor_maps_updated() {
    const auto tasks = root_section_("factor_map_tasks");
    if (pages_.update_preparation_page)
        pages_.update_preparation_page(tasks);
    update_mapping_();
    refresh_data_page();
}

void WorkflowCore::on_contour_drafts_updated() {
    if (pages_.mapping_set_project) pages_.mapping_set_project();
    const auto tasks = root_section_("factor_map_tasks");
    if (pages_.update_preparation_page)
        pages_.update_preparation_page(tasks);
    update_mapping_();
    update_home_();
}

void WorkflowCore::on_stratigraphy_updated() {
    update_home_();
    if (pages_.update_sequence_framework_page) {
        pages_.update_sequence_framework_page(
            root_section_("stratigraphy"));
    }
    if (pages_.update_stratigraphy_correlation_page)
        pages_.update_stratigraphy_correlation_page();
    const auto tasks = root_section_("factor_map_tasks");
    if (pages_.update_preparation_page)
        pages_.update_preparation_page(tasks);
    update_mapping_();
}

// ---------------------------------------------------------------------------
// Recompute
// ---------------------------------------------------------------------------

void WorkflowCore::request_recompute() {
    auto* doc = document();
    if (doc == nullptr) {
        info_("更新受影响成果", "请先打开或绑定工程。");
        return;
    }
    if (recompute_job_ == nullptr) return;
    if (recompute_job_->is_running()) {
        info_("更新受影响成果", "重算任务正在进行中…");
        return;
    }
    // Global run identity (#834): supersedes (and is superseded by) any
    // concurrent prepare / send-to-prepare run.
    const int generation = generation_.next ? generation_.next() : 0;
    auto payload = std::make_shared<RecomputeRunResult>();
    payload->generation = generation;
    last_recompute_ = payload;
    auto spec = make_recompute_job_spec(doc->root(), generation,
                                        services_.build_affected_plan,
                                        factor_recompute_);
    recompute_job_->set_target(doc);
    recompute_job_->start(
        std::move(spec),
        [this, payload](const UiJobOutcome& outcome) {
            if (outcome.state == job::JobState::failed) {
                on_recompute_failed(outcome.error);
                return;
            }
            if (outcome.state == job::JobState::cancelled) return;
            if (const auto* result =
                    outcome.try_result<RecomputeRunResult>()) {
                on_recompute_completed(*result);
            }
        });
}

void WorkflowCore::on_recompute_completed(
    const RecomputeRunResult& payload) {
    // Commit staged factor tasks on the GUI thread — never into a project
    // that is no longer the one the plan was built against (#537).
    const int current_generation =
        generation_.current ? generation_.current() : 0;
    const bool superseded = payload.generation != current_generation;
    std::vector<std::pair<std::string, domain::Json>> updates =
        payload.task_updates;
    if (superseded) {
        // A newer prepare/recompute run superseded this one (#834): drop
        // the staged metadata AND this run's grids — without evicting a
        // newer run's entries keyed over the same task ids (#881: the
        // fingerprint of THIS run's stored grid, never the cache read).
        for (const auto& [task_id, staged] : updates) {
            (void)staged;
            const auto git = payload.grids.find(task_id);
            if (git == payload.grids.end() || !git->second.has_value())
                continue;
            if (!grids_.fingerprint || !grids_.clear_if_fingerprint)
                continue;
            const auto fp = grids_.fingerprint(git->second);
            if (fp) grids_.clear_if_fingerprint(task_id, *fp);
        }
        updates.clear();
    }
    auto* doc = document();
    if (doc != nullptr && !updates.empty() &&
        recompute_job_ != nullptr &&
        recompute_job_->target() == doc) {
        auto& tasks = doc->root()["factor_map_tasks"];
        if (tasks.is_array()) {
            std::map<std::string, std::size_t> by_id;
            for (std::size_t i = 0; i < tasks.size(); ++i)
                by_id[json_str(tasks[i], "id")] = i;
            for (auto& [task_id, staged] : updates) {
                const auto it = by_id.find(task_id);
                if (it == by_id.end()) continue;
                tasks[it->second] = staged;
                // Pair accepted metadata with exactly this run's grid
                // (#834): repair a cache keyed over by a competing entry.
                const auto git = payload.grids.find(task_id);
                if (git != payload.grids.end() && git->second.has_value() &&
                    grids_.store) {
                    try {
                        grids_.store(task_id, git->second);
                    } catch (const std::exception&) {
                    }
                }
            }
        }
    }
    std::vector<std::string> lines{payload.plan.summary_zh()};
    if (payload.plan.cycle_error) {
        lines.push_back("依赖环: " + *payload.plan.cycle_error);
    }
    if (!payload.result.messages.empty()) {
        lines.push_back("执行结果: " + join(payload.result.messages, "；"));
    }
    const bool no_handler =
        std::any_of(payload.result.messages.begin(),
                    payload.result.messages.end(),
                    [](const std::string& message) {
                        return message.find("no handler") !=
                               std::string::npos;
                    });
    if (no_handler) {
        lines.push_back(
            "部分步骤没有自动重算入口，请在对应页面手动执行。");
    } else if (payload.result.stopped_early) {
        lines.push_back("已提前停止（上游失败）");
    }
    refresh_home_steps();
    info_("更新受影响成果", join(lines, "\n"));
}

void WorkflowCore::on_recompute_failed(const std::string& message) {
    warning_("更新受影响成果", "重算失败：" + message);
}

// ---------------------------------------------------------------------------
// 发送制备
// ---------------------------------------------------------------------------

void WorkflowCore::set_prep_summary_(const std::string& text) const {
    if (pages_.prep_summary_text) pages_.prep_summary_text(text);
}

void WorkflowCore::on_well_log_send_to_prep() {
    auto* doc = document();
    const auto prediction_tasks = root_section_("prediction_tasks");
    if (doc == nullptr || !prediction_tasks.is_array() ||
        prediction_tasks.empty()) {
        info_("发送制备", "请先运行测井预测");
        return;
    }
    if (prepare_job_ == nullptr) return;
    if (prepare_job_->is_running()) {
        info_("发送制备", "单因素图制备正在进行中…");
        return;
    }
    prepare_generation_ = generation_.next ? generation_.next() : 0;
    const int generation = prepare_generation_;
    // Snapshot on the host thread so scientific inputs match Stage-4
    // fingerprints (preparation_page._start_prepare_worker parity).
    // method="IDW" is deliberate — 发送制备 derives fresh factor maps from
    // prediction results with the documented default algorithm.
    ui_workers::FactorPrepareInput input;
    input.generation = generation;
    input.method = "IDW";
    try {
        input.slice =
            services_.prepare_slice ? services_.prepare_slice(*doc)
                                    : ui_workers::PrepareProjectSlice{};
        input.snapshot = ui_workers::build_prepare_snapshot(
            input.slice, generation, "IDW", std::nullopt, 2.0,
            /*force=*/false);
    } catch (const std::exception& exc) {
        warning_("发送制备失败", exc.what());
        return;
    }
    input.seams = prepare_seams_;
    if (input.snapshot && pages_.prep_summary_text) {
        set_prep_summary_("制备中… 任务 " +
                          std::to_string(input.snapshot->tasks.size()) +
                          " · 发送制备");
    }
    if (pages_.navigate_to) {
        pages_.navigate_to(ui_shell::kPageIndexMapping, "preparation");
    }
    // Typed progress hops to the GUI thread through post_to_gui — the
    // worker-side hook formats the label text (deterministic) and the
    // posted body only sets it (the queued-connection parity of the
    // Python progress signal).
    auto poster = pages_.post_to_gui;
    auto set_summary = pages_.prep_summary_text;
    input.on_progress =
        [poster, set_summary](const ui_workers::FactorPrepareProgress& p) {
            std::string text = "制备中：复用 " + std::to_string(p.clean) +
                               " · 需计算 " + std::to_string(p.dirty) +
                               " · 已完成 " +
                               std::to_string(p.completed) + "/" +
                               std::to_string(p.total_tasks);
            const std::string msg =
                !p.message.empty() ? p.message : p.phase;
            if (!msg.empty()) text += " · " + msg;
            if (poster && set_summary) {
                poster([set_summary, text = std::move(text)]() mutable {
                    set_summary(text);
                });
            } else if (set_summary) {
                set_summary(std::move(text));
            }
        };
    auto spec = ui_workers::make_factor_prepare_job_spec(std::move(input));
    prepare_job_->set_target(doc);
    prepare_job_->start(
        std::move(spec),
        [this](const UiJobOutcome& outcome) {
            if (outcome.state == job::JobState::failed) {
                on_prep_send_failed(outcome.error);
                return;
            }
            if (outcome.state == job::JobState::cancelled) {
                on_prep_send_cancelled();
                return;
            }
            if (const auto* result =
                    outcome.try_result<
                        ui_workers::FactorPrepareBatchResult>()) {
                on_prep_send_completed(*result);
            }
        });
}

void WorkflowCore::on_prep_send_progress(
    const ui_workers::FactorPrepareProgress& update) {
    // Direct-call parity (the slot the Python progress signal drives) —
    // kept for hosts that deliver typed progress without post_to_gui.
    auto* doc = document();
    if (prepare_job_ == nullptr || prepare_job_->target() != doc) return;
    const std::string msg =
        !update.message.empty() ? update.message : update.phase;
    std::string text = "制备中：复用 " + std::to_string(update.clean) +
                       " · 需计算 " + std::to_string(update.dirty) +
                       " · 已完成 " + std::to_string(update.completed) +
                       "/" + std::to_string(update.total_tasks);
    if (!msg.empty()) text += " · " + msg;
    set_prep_summary_(text);
}

void WorkflowCore::on_prep_send_completed(
    const ui_workers::FactorPrepareBatchResult& result) {
    auto* doc = document();
    if (prepare_job_ == nullptr || prepare_job_->target() != doc) return;
    const int current = generation_.current ? generation_.current() : 0;
    if (result.generation != current) return;
    // Fingerprint-guarded commit — same semantics as the preparation page.
    if (services_.commit_prepare) {
        services_.commit_prepare(*doc, result, current);
    }
    on_factor_maps_updated();
    auto& tasks = doc->root()["factor_map_tasks"];
    if (pages_.update_prep_state) pages_.update_prep_state(tasks);
    int complete = 0;
    if (tasks.is_array()) {
        for (const auto& task : tasks)
            if (json_str(task, "status") == "complete") ++complete;
    }
    set_prep_summary_("已制备 " + std::to_string(complete) + "/" +
                      std::to_string(tasks.is_array() ? tasks.size() : 0) +
                      " 个单因素图 · 复用 " +
                      std::to_string(result.clean_count) + " · 计算 " +
                      std::to_string(result.executed_count));
    if (pages_.navigate_to) {
        pages_.navigate_to(ui_shell::kPageIndexMapping, "preparation");
    }
}

void WorkflowCore::on_prep_send_failed(const std::string& message) {
    warning_("发送制备失败", message);
    set_prep_summary_("单因素图生成失败：" + message);
}

void WorkflowCore::on_prep_send_cancelled() {
    set_prep_summary_("发送制备已取消");
}

// ---------------------------------------------------------------------------
// 发送编图
// ---------------------------------------------------------------------------

void WorkflowCore::on_seismic_send_to_mapping() {
    auto* doc = document();
    auto tasks = root_section_("prediction_tasks");
    if (doc == nullptr || !tasks.is_array() || tasks.empty()) {
        info_("发送编图", "请先运行地震预测");
        return;
    }
    const auto& task = tasks[tasks.size() - 1];
    const auto summary_it = task.find("result_summary");
    const domain::Json summary =
        (summary_it != task.end() && summary_it->is_object())
            ? *summary_it
            : domain::Json::object();
    const auto meta_it = task.find("model_metadata");
    const domain::Json meta =
        (meta_it != task.end() && meta_it->is_object())
            ? *meta_it
            : domain::Json::object();
    const bool is_demo_task =
        json_truthy(summary, "demo") || json_truthy(summary, "is_mock") ||
        json_truthy(meta, "demo") || json_truthy(meta, "demo_only") ||
        json_str(task, "adapter_kind") == "mock";

    domain::Json payload = domain::Json::object();
    payload["result_summary"] = summary;
    const std::string task_id = json_str(task, "id");
    if (is_demo_task) {
        // Explicit Demo path only.
        if (!services_.compile_map_draft) {
            warning_("发送编图", "演示编图服务不可用。");
            return;
        }
        services_.compile_map_draft(doc->root(), 0);
    } else if (prediction::is_map_compilable(payload)) {
        if (!services_.compile_map_production) {
            warning_("发送编图", "生产编图服务不可用。");
            return;
        }
        CatalogServiceApi* catalog_service = nullptr;
        if (catalog_.get_catalog_service) {
            try {
                catalog_service = catalog_.get_catalog_service();
            } catch (const std::exception&) {
                catalog_service = nullptr;
            }
        }
        const std::string vid = json_str(meta, "prediction_version_id");
        try {
            services_.compile_map_production(
                doc->root(), task_id, payload, catalog_service,
                vid.empty() ? std::nullopt
                            : std::optional<std::string>(vid));
        } catch (const std::exception& exc) {
            warning_("发送编图",
                     std::string("生产编图失败（不会生成演示占位方块）:\n") +
                         exc.what());
            return;
        }
    } else {
        // Scientific/non-demo tasks without spatial geometry → BLOCK
        // (never silently fall through to fake squares).
        warning_("发送编图",
                 "当前预测结果无可编绘的平面空间几何。\n"
                 "井深区间或非空间结果不能自动变成古地理图；"
                 "也不会生成「未分类」占位方块。\n"
                 "请使用生产模型输出 VECTOR_POLYGONS，或通过「生成演示"
                 "草稿」显式运行演示。");
        return;
    }
    update_mapping_();
    // The production compile registered a paleomap catalog version —
    // surface it in the Data Manager too.
    refresh_data_page();
    if (pages_.navigate_to) {
        pages_.navigate_to(ui_shell::kPageIndexMapping, "canvas");
    }
}

// ---------------------------------------------------------------------------
// Demo draft + navigation
// ---------------------------------------------------------------------------

void WorkflowCore::on_generate_demo_map_draft() {
    auto* doc = document();
    if (doc == nullptr) return;
    if (pages_.mapping_is_dirty && pages_.mapping_is_dirty() &&
        dialogs_.dirty_confirm) {
        const auto choice = dialogs_.dirty_confirm(
            "未保存的编图修改",
            "当前图件有未保存修改。生成演示草稿将刷新编图页面。是否先保存"
            "草稿？");
        if (choice == WorkflowDialogApi::DirtyChoice::cancel) return;
        if (choice == WorkflowDialogApi::DirtyChoice::save) {
            if (!pages_.mapping_save_draft ||
                !pages_.mapping_save_draft()) {
                return;
            }
        }
    }
    if (services_.compile_map_draft) {
        services_.compile_map_draft(doc->root(), 0);
    }
    if (pages_.refresh_shell) pages_.refresh_shell();
}

void WorkflowCore::on_open_in_visualization(const std::string& ref) {
    if (pages_.navigate_to)
        pages_.navigate_to(ui_shell::kPageIndexVisualization, "");
    if (pages_.open_viz_ref) pages_.open_viz_ref(ref);
}

void WorkflowCore::on_open_in_well_prediction(const AssetHandle& resource) {
    const std::string resource_id = handle_id(resource);
    if (resource_id.empty() || !pages_.select_well_resource ||
        !pages_.select_well_resource(resource_id)) {
        return;
    }
    if (pages_.navigate_to)
        pages_.navigate_to(ui_shell::kPageIndexWell, "well_log");
}

void WorkflowCore::on_open_in_seismic_prediction(
    const AssetHandle& resource) {
    const std::string resource_id = handle_id(resource);
    if (resource_id.empty() || !pages_.select_seismic_resource ||
        !pages_.select_seismic_resource(resource_id)) {
        return;
    }
    if (pages_.navigate_to)
        pages_.navigate_to(ui_shell::kPageIndexSeismic, "seismic");
}

void WorkflowCore::on_home_navigation(int legacy_index) {
    const auto hub =
        ui_shell::legacy_page_to_hub(legacy_index)
            .value_or(std::pair<int, std::string>{
                ui_shell::kPageIndexData, "overview"});
    if (pages_.navigate_to) pages_.navigate_to(hub.first, hub.second);
}

// ---------------------------------------------------------------------------
// Prediction-source import relay
// ---------------------------------------------------------------------------

std::string WorkflowCore::well_log_import_path_key(const fs::path& path) {
    std::error_code ec;
    const auto resolved = fs::weakly_canonical(fs::absolute(path, ec), ec);
    return (ec ? fs::absolute(path).lexically_normal() : resolved)
        .generic_string();
}

void WorkflowCore::on_well_log_import_requested(
    const std::vector<fs::path>& raw_paths) {
    std::vector<fs::path> paths;
    for (const auto& raw : raw_paths) {
        if (!raw.empty()) paths.push_back(raw);
    }
    if (paths.empty()) return;
    if (!pages_.begin_import_well_log_paths) {
        if (pages_.set_source_import_status) {
            pages_.set_source_import_status(
                "当前数据管理页不支持从预测页导入测井数据");
        }
        return;
    }
    pending_well_log_import_paths_.clear();
    for (const auto& path : paths)
        pending_well_log_import_paths_.insert(
            well_log_import_path_key(path));
    if (!pages_.begin_import_well_log_paths(paths)) {
        pending_well_log_import_paths_.clear();
        if (pages_.set_source_import_status) {
            pages_.set_source_import_status(
                "测井数据导入未启动，请稍后重试");
        }
        return;
    }
    if (pages_.set_source_import_status) {
        pages_.set_source_import_status("正在导入测井数据…");
    }
}

void WorkflowCore::on_prediction_source_import_finished(
    const std::vector<ResourceItem>& added) {
    if (pending_well_log_import_paths_.empty()) return;
    pending_well_log_import_paths_.clear();
    std::vector<const ResourceItem*> resources;
    for (const auto& resource : added) {
        if (resource.type == "well_log") resources.push_back(&resource);
    }
    if (resources.empty()) {
        if (pages_.set_source_import_status) {
            pages_.set_source_import_status(
                "未导入可用的测井数据；请检查格式或是否已在数据管理中归档");
        }
        return;
    }
    const auto tasks = root_section_("prediction_tasks");
    if (pages_.update_well_log_prediction_page)
        pages_.update_well_log_prediction_page(tasks);
    const auto* resource = resources.front();
    if (pages_.select_well_resource &&
        pages_.select_well_resource(resource->id)) {
        if (pages_.set_source_import_status) {
            pages_.set_source_import_status(
                "已导入并加载测井数据：" +
                (resource->name.empty() ? std::string("未命名测井")
                                        : resource->name));
        }
    }
}

void WorkflowCore::on_prediction_source_import_failed(
    const std::string& message) {
    if (pending_well_log_import_paths_.empty()) return;
    pending_well_log_import_paths_.clear();
    if (pages_.set_source_import_status) {
        pages_.set_source_import_status("测井数据导入失败：" + message);
    }
}

}  // namespace pwb::ui_controllers
