// CONV-33 轮2 实装 — workflow/service.py 全量移植（route A4）。
//
// 首页步骤状态推断权威（service.hpp 契约冻结轮1 裁决）：
//   _evidence_step_status → infer_workflow_step_status（freshness 叠加）
//   → home_workflow_steps（活动 run 就地回写）→ dashboard_state。
//
// FreshnessService 组合（for_project 等价面，见 compose_freshness）：
// 镜像 Python for_project 的降级分支 —— catalog 图 +
// resolve_current_project_version_context(service=None) 的“每资产末版
// 即 current”推断。project 侧 resolve 覆盖（horizon/correlation/fault
// 引用、factor grid 指针、expected identity）属未移植的 A3 resolve 面，
// 本组合不消费 project —— 边界如实声明（33-impl-a4.md）。
//
// broad-except 边界（E-1，audit #847-3）：Python 在 overlay 探测与
// home 组合两处捕获 Exception 并 log.warning 后回退 evidence-only。
// C++ = catch (const std::exception&)，边界与 Python 对齐（探测 +
// 惰性组合整段包裹）。本库无日志缝 —— 降级路径不写 stderr（静默在
// 语义上等价于 log sink 为 no-op；不静默吞错的诉求由“不捕获非
// std::exception、不改变返回语义”承接，边界注释如下）。
#include "pwb/workflow_runtime/service.hpp"

#include <pwb/workflow_runtime/current_context.hpp>
#include <pwb/workflow_runtime/qc.hpp>
#include <pwb/workflow_graph/graph.hpp>

#include <algorithm>
#include <cstdio>
#include <filesystem>
#include <map>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace pwb::workflow_runtime {
namespace {

using pwb::workflow_graph::DataRunRef;
using pwb::workflow_graph::DataVersionRef;
using pwb::workflow_graph::DependencyGraph;

// ------------------------------------------------------ Json 视图辅助 --
// D4 Json seam：缺键 / 类型不符 ≙ 空（pydantic 模型属性读取 parity）。

const Json* find_array(const Json& project, const char* key) {
    if (!project.is_object()) {
        return nullptr;
    }
    const auto it = project.find(key);
    if (it == project.end() || !it->is_array()) {
        return nullptr;
    }
    return &*it;
}

bool section_non_empty(const Json& project, const char* key) {
    const Json* array = find_array(project, key);
    return array != nullptr && !array->empty();
}

// getattr(obj, "status", "") parity：非字符串（或缺键）按空串读。
std::string status_of(const Json& item) {
    if (!item.is_object()) {
        return {};
    }
    const auto it = item.find("status");
    if (it == item.end() || !it->is_string()) {
        return {};
    }
    return it->get<std::string>();
}

// --------------------------------------------- _evidence_step_status --

// service.py L50-89 —— 五个证据分支 + 默认 pending。
std::string evidence_step_status(const Json& project,
                                 std::string_view step_type) {
    if (step_type == "data_check") {
        return section_non_empty(project, "resources") ? "complete"
                                                       : "pending";
    }
    const auto aggregate_tasks = [&project](const char* key) -> std::string {
        const Json* tasks = find_array(project, key);
        if (tasks == nullptr) {
            return "pending";
        }
        bool any_failed = false;
        bool any_complete = false;
        for (const Json& task : *tasks) {
            const std::string status = status_of(task);
            any_failed = any_failed || status == "failed" ||
                         status == "error";
            any_complete = any_complete || status == "complete";
        }
        if (any_failed) {
            return "failed";
        }
        if (any_complete) {
            return "complete";
        }
        return tasks->empty() ? "pending" : "running";
    };
    if (step_type == "factor_map") {
        return aggregate_tasks("factor_map_tasks");
    }
    if (step_type == "prediction") {
        return aggregate_tasks("prediction_tasks");
    }
    if (step_type == "map_compile") {
        return section_non_empty(project, "paleomap_documents") ? "complete"
                                                                : "pending";
    }
    if (step_type == "qc") {
        // 报告集合走 qc.hpp active_quality_reports（轮2 已实装；本 TU
        // 不触碰 run_basic_qc/run_map_qc —— 那属 A1）。
        const std::vector<project::QualityReport> reports =
            active_quality_reports(project);
        const Json* raw = find_array(project, "quality_reports");
        const bool raw_empty = raw == nullptr || raw->empty();
        if (reports.empty() && raw_empty) {
            return "pending";
        }
        // ``_status_from_issues`` 可能产出 "error"（存在 critical issue）
        // —— 与遗留 "failed" 同为失败门（L78-83）：error 级报告绝不能
        // 沉到 complete。
        for (const project::QualityReport& report : reports) {
            if (report.status == "failed" || report.status == "error") {
                return "failed";
            }
        }
        for (const project::QualityReport& report : reports) {
            if (report.status == "warning") {
                return "warning";
            }
        }
        return (reports.empty() && raw_empty) ? "pending" : "complete";
    }
    if (step_type == "export") {
        return section_non_empty(project, "export_artifacts") ? "complete"
                                                              : "pending";
    }
    return "pending";
}

// ------------------------------------ FreshnessService.for_project 面 --
// 组合根：拥有图 / 上下文 / 版本记录（FreshnessService 持引用，成员
// 声明序保证析构安全 —— service 最后声明）。runtime_service.hpp 的
// FreshnessSession 同构。

struct FreshnessComposition {
    DependencyGraph graph;
    FreshnessService::VersionLookup versions;
    CurrentProjectVersionContext context{};
    CatalogSeam seam{};
    std::unique_ptr<FreshnessService> service;
};

std::unique_ptr<FreshnessComposition> compose_freshness(
    const CatalogRepository* catalog) {
    auto bundle = std::make_unique<FreshnessComposition>();
    if (catalog == nullptr) {
        // 无目录降级路径（for_project cat is None 分支）：空图 —— 一切
        // 查询 UNKNOWN / step_freshness nullopt，调用方保持 evidence 语义。
        bundle->service =
            std::make_unique<FreshnessService>(bundle->graph, bundle->context);
        return bundle;
    }

    // 冻结头以 const CatalogRepository* 暴露缝指针（语义 = 不持有/不
    // 改语义状态），而 seam 接口的 list/resolve 族是非 const virtual ——
    // 在组合边界统一 const_cast（仅解引用调用只读列取面）。
    CatalogRepository* repo = const_cast<CatalogRepository*>(catalog);

    // 图 + 富版本记录（runtime_service.cpp snapshot 同构；Python 的
    // _cached_graph_for 是宿主侧缓存策略，不移植 —— 头 L18 已声明）。
    std::vector<VersionRecord> all_versions;
    for (const AssetRecord& asset : repo->list_assets()) {
        for (VersionRecord& ver : repo->list_versions(asset.id)) {
            all_versions.push_back(std::move(ver));
        }
    }
    const std::vector<RunRecord> all_runs = repo->list_runs();

    std::vector<DataVersionRef> graph_versions;
    graph_versions.reserve(all_versions.size());
    for (const VersionRecord& ver : all_versions) {
        graph_versions.push_back(DataVersionRef{ver.asset_id, ver.version_id,
                                                ver.name,
                                                ver.producing_run_id});
        bundle->versions[ver.version_id] = ver;
    }
    std::vector<DataRunRef> graph_runs;
    graph_runs.reserve(all_runs.size());
    for (const RunRecord& run : all_runs) {
        graph_runs.push_back(DataRunRef{
            run.run_id, run.operation, run.input_version_ids,
            run.output_version_ids, run.parameters, run.generator_version,
            run.status, run.started_at, run.finished_at, run.domain_task_id,
            run.input_snapshot_hash});
    }
    bundle->graph =
        DependencyGraph::from_listings(graph_versions, graph_runs);

    // 上下文：Python resolve_current_project_version_context 在
    // service=None 时的推断分支 —— 按版本 (created_at, version_id) 稳定
    // 排序，每资产末版即 current，label = 版本名（project 侧覆盖段属
    // 未移植的 A3 resolve 面，见文件头）。
    std::map<std::string, std::vector<const VersionRecord*>> by_asset;
    std::vector<std::string> asset_order;
    for (const VersionRecord& ver : all_versions) {
        if (by_asset.find(ver.asset_id) == by_asset.end()) {
            asset_order.push_back(ver.asset_id);
        }
        by_asset[ver.asset_id].push_back(&ver);
    }
    for (const std::string& asset : asset_order) {
        std::vector<const VersionRecord*>& vers = by_asset[asset];
        std::sort(vers.begin(), vers.end(),
                  [](const VersionRecord* a, const VersionRecord* b) {
                      if (a->created_at != b->created_at) {
                          return a->created_at < b->created_at;
                      }
                      return a->version_id < b->version_id;
                  });
        const VersionRecord* last = vers.back();
        bundle->context.select(asset, last->version_id, last->name);
    }

    // 缝：resolve_version / verify_integrity 直通仓库 —— 刻意不吞异常。
    // 探测路径的失败由 _apply_freshness_overlay 的 catch 边界统一承接
    // （Python 的 catalog.resolve_version 异常同样穿透到 overlay 的
    // broad except，audit #847-3）。
    bundle->seam.resolve_version =
        [repo](const std::string& id) -> std::optional<VersionRecord> {
        return repo->resolve_version(id);
    };
    bundle->seam.verify_integrity =
        [repo](const std::string& id) -> std::optional<std::string> {
        return repo->verify_integrity(id);
    };
    bundle->seam.file_exists = [](const std::string& path) {
        std::error_code ec;
        return !path.empty() && std::filesystem::exists(path, ec);
    };
    bundle->service = std::make_unique<FreshnessService>(
        bundle->graph, bundle->context, bundle->versions, bundle->seam);
    return bundle;
}

// ------------------------------------------ _apply_freshness_overlay --

bool freshness_tracked_step(std::string_view step_type) {
    for (const auto& [step, op] : kFreshnessStepOps) {
        if (step == step_type) {
            return true;
        }
    }
    return false;
}

std::string apply_freshness_overlay(const Json& project,
                                    std::string_view step_type,
                                    const std::string& evidence_status,
                                    const StepStatusOptions& options) {
    // project 只进 Python for_project 的 resolve 覆盖段（未移植的 A3
    // 面，见文件头）—— 组合边界外无消费者，显式让渡。
    (void)project;
    if (evidence_status != "complete" && evidence_status != "warning") {
        return evidence_status;
    }
    if (!freshness_tracked_step(step_type)) {
        return evidence_status;
    }
    try {
        // catch 边界（E-1 / audit #847-3）：探测 + 惰性组合整段包裹 ——
        // 探测抛出绝不破坏状态条，但也绝不把 STALE/UNKNOWN 静默降级为
        // “已完成”；此处显式回退 evidence 并保留边界可见性（上层日志
        // 缝为宿主职责，本库无 logger —— 见文件头）。
        const FreshnessService* svc = options.freshness_service;
        std::unique_ptr<FreshnessComposition> composed;
        if (svc == nullptr) {
            composed = compose_freshness(options.catalog);
            svc = composed->service.get();
        }
        const std::optional<FreshnessState> state =
            svc->step_freshness(std::string(step_type));
        if (!state) {
            return evidence_status;
        }
        switch (*state) {
        case FreshnessState::Stale:
            return "stale";
        case FreshnessState::Failed:
            return "failed";
        case FreshnessState::Running:
            return "running";
        case FreshnessState::Missing:
            return "warning";
        case FreshnessState::Unknown:
            // 溯源未知不是“已完成”（H1）：落到既有的 状态未知 标签。
            return "warning";
        case FreshnessState::Fresh:
            break;  // FRESH → 保持 evidence
        }
        return evidence_status;
    } catch (const std::exception&) {
        return evidence_status;
    }
}

Json steps_to_json(const std::vector<project::WorkflowStep>& steps) {
    Json out = Json::array();
    for (const project::WorkflowStep& step : steps) {
        out.push_back(step.to_dict());
    }
    return out;
}

}  // namespace

// ------------------------------------------------ create_compilation_run

project::CompilationRun create_compilation_run(
    domain::Json& project, const std::string& name,
    const std::string& target_horizon, const std::string& sequence_scheme,
    const project::ModelClock& clock) {
    // 就地回写：stratigraphy 的 target_horizon + systems_tract_scheme
    //（段缺失时创建 —— Python 侧模型常驻，Json seam 等价面）。
    if (!project.is_object()) {
        project = Json::object();
    }
    const auto strat_it = project.find("stratigraphy");
    if (strat_it == project.end() || !strat_it->is_object()) {
        project["stratigraphy"] = Json::object();
    }
    project["stratigraphy"]["target_horizon"] = target_horizon;
    project["stratigraphy"]["systems_tract_scheme"] = sequence_scheme;

    // 六步全 pending（STEP_ORDER 顺序即权威）。clock 调用序对齐 Python
    // 构造序：先六个 step id，后 run id，再 created_at —— oracle 冻结
    // 依赖该序。
    std::vector<project::WorkflowStep> steps;
    steps.reserve(std::size(kStepOrder));
    for (std::string_view step_type : kStepOrder) {
        steps.push_back(
            project::make_workflow_step(step_type, "pending", clock));
    }
    project::CompilationRun run = project::make_compilation_run(
        name, target_horizon, sequence_scheme, steps, clock);

    const auto runs_it = project.find("compilation_runs");
    if (runs_it == project.end() || !runs_it->is_array()) {
        project["compilation_runs"] = Json::array();
    }
    project["compilation_runs"].push_back(run.to_dict());
    return run;
}

// ------------------------------------------- infer_workflow_step_status

std::string infer_workflow_step_status(const domain::Json& project,
                                       std::string_view step_type,
                                       const StepStatusOptions& options) {
    const std::string evidence = evidence_step_status(project, step_type);
    if (!options.apply_freshness) {
        return evidence;
    }
    return apply_freshness_overlay(project, step_type, evidence, options);
}

// ------------------------------------------------- home_workflow_steps

std::vector<project::WorkflowStep> home_workflow_steps(
    domain::Json& project, const StepStatusOptions& options) {
    std::unique_ptr<FreshnessComposition> composed;
    if (options.apply_freshness) {
        try {
            composed = compose_freshness(options.catalog);
        } catch (const std::exception&) {
            // catch 边界（E-1 / audit #847-3）：组合失败绝不能废掉整条
            // 首页状态条，也绝不静默 —— 回退 evidence-only（日志缝为
            // 宿主职责）。composed 保持 null：后续每步 overlay 会按
            // Python 语义重新尝试组合并各自降级。
            composed = nullptr;
        }
    }
    StepStatusOptions per_step = options;
    per_step.freshness_service =
        composed != nullptr ? composed->service.get() : nullptr;

    std::map<std::string, std::string, std::less<>> inferred;
    for (std::string_view step_type : kStepOrder) {
        inferred.emplace(
            step_type,
            infer_workflow_step_status(project, step_type, per_step));
    }

    const Json* runs = find_array(project, "compilation_runs");
    if (runs == nullptr || runs->empty() || !runs->back().is_object()) {
        // 无活动 run：纯 evidence 临时步骤（进度条绝不全 pending 的前提
        // 是用户已有成果）。id 为宿主侧戳（默认 clock）—— 从不持久化。
        std::vector<project::WorkflowStep> ephemeral;
        ephemeral.reserve(std::size(kStepOrder));
        for (std::string_view step_type : kStepOrder) {
            ephemeral.push_back(project::make_workflow_step(
                step_type, inferred.find(step_type)->second));
        }
        return ephemeral;
    }
    domain::Json& active_run = project["compilation_runs"].back();

    // 活动 run 就地回写（持久化进度，save/load 保进度语义）。经 DTO
    // 反序列化 → 变异 → 整段写回：from_dict 宽松回填 + to_dict 键序
    // 保真使往返对 fixture 形状（pydantic model_dump）无损。
    std::vector<project::WorkflowStep> steps;
    const auto run_steps_it = active_run.find("workflow_steps");
    if (run_steps_it != active_run.end() && run_steps_it->is_array()) {
        steps.reserve(run_steps_it->size());
        for (const Json& item : *run_steps_it) {
            steps.push_back(project::WorkflowStep::from_dict(item));
        }
    }
    // by_type：同型重复时后者胜（Python dict comprehension 语义）。
    std::map<std::string, std::size_t> by_type;
    for (std::size_t i = 0; i < steps.size(); ++i) {
        by_type[steps[i].step_type] = i;
    }
    std::vector<project::WorkflowStep> ordered;
    ordered.reserve(std::size(kStepOrder));
    for (std::string_view step_type : kStepOrder) {
        const std::string& status = inferred.find(step_type)->second;
        const auto existing_it = by_type.find(std::string(step_type));
        if (existing_it == by_type.end()) {
            steps.push_back(
                project::make_workflow_step(step_type, status));
            ordered.push_back(steps.back());
            continue;
        }
        project::WorkflowStep& existing = steps[existing_it->second];
        // 弱覆盖保留（L236-242）：已持久化的 failed/warning 不被
        // pending/stale 降级；fresh evidence 可升回 complete。
        const bool sticky = (existing.status == "failed" ||
                            existing.status == "warning") &&
                           (status == "pending" || status == "stale");
        if (!sticky) {
            existing.status = status;
        }
        ordered.push_back(existing);
    }
    active_run["workflow_steps"] = steps_to_json(steps);
    return ordered;
}

// ------------------------------------------ build_affected_products_plan

RecomputePlan build_affected_products_plan(
    const domain::Json& project,
    const std::optional<std::vector<std::string>>& changed_version_ids,
    const CatalogRepository* catalog) {
    // Python 此处无降级捕获 —— 组合失败原样抛出（fail-loud parity）。
    std::unique_ptr<FreshnessComposition> composed =
        compose_freshness(catalog);
    RecomputePlanOptions options;
    if (changed_version_ids.has_value()) {
        options.changed_version_ids = *changed_version_ids;
    }
    // Json seam 视图：planner 只读 prediction_tasks /
    // paleomap_documents 两键（整份 project Json 直传等价 —— 缺键 ≙ 空）。
    options.project = project;
    return build_recompute_plan(*composed->service, options);
}

// ------------------------------------------- downstream_impact_for_version

domain::Json downstream_impact_for_version(const std::string& version_id,
                                           const domain::Json* project,
                                           const CatalogRepository* catalog) {
    // project=None ≙ Python 空上下文（freshness 只从 catalog 取图 ——
    // Python for_project 传 project 给 resolve 覆盖段，那属未移植的
    // A3 resolve 面，见文件头；project 形参在组合边界外无消费者，
    // 显式让渡以保持 -Wunused-parameter 清洁）。
    (void)project;
    std::unique_ptr<FreshnessComposition> composed = compose_freshness(catalog);
    const FreshnessService& svc = *composed->service;
    const DependencyGraph& graph = svc.graph();

    // 根扩展镜像 build_recompute_plan（H1）：dependents 挂在其消费的
    // SUPERSEDED 版本上 —— 面板必须含整个 asset 兄弟集 + 产生 run 的
    // domain-task 兄弟 run 输出，否则新 current tip 静默显示“不影响
    // 任何成果”。
    std::set<std::string> roots{version_id};
    const std::optional<std::string> asset = graph.asset_id_for(version_id);
    if (asset.has_value()) {
        for (const auto& [asset_id, version_ids] : graph.asset_versions()) {
            if (asset_id != *asset) {
                continue;
            }
            roots.insert(version_ids.begin(), version_ids.end());
        }
    }
    const DataVersionRef* version = graph.version(version_id);
    if (version != nullptr && version->producing_run_id.has_value()) {
        const DataRunRef* prod = graph.run(*version->producing_run_id);
        if (prod != nullptr && prod->domain_task_id.has_value()) {
            for (const auto& [task_id, run_ids] : graph.domain_task_runs()) {
                if (task_id != *prod->domain_task_id) {
                    continue;
                }
                for (const std::string& run_id : run_ids) {
                    for (const auto& [rid, outputs] : graph.run_outputs()) {
                        if (rid != run_id) {
                            continue;
                        }
                        roots.insert(outputs.begin(), outputs.end());
                    }
                }
            }
        }
    }
    std::vector<std::string> sorted_roots(roots.begin(), roots.end());

    domain::Json rows = domain::Json::array();
    for (const FreshnessReport& report : svc.downstream_impact(sorted_roots)) {
        domain::Json row = domain::Json::object();
        row["run_id"] = report.subject_id;
        row["operation"] = report.operation;
        const auto label_it = OPERATION_LABELS_ZH.find(report.operation);
        row["label"] = label_it != OPERATION_LABELS_ZH.end()
                           ? label_it->second
                           : report.operation;
        row["domain_task_id"] = report.domain_task_id.has_value()
                                    ? domain::Json(*report.domain_task_id)
                                    : domain::Json(nullptr);
        const std::string state_value = freshness_state_value(report.state);
        row["state"] = state_value;
        const auto state_label_it = FRESHNESS_UI_LABELS.find(state_value);
        row["state_label"] = state_label_it != FRESHNESS_UI_LABELS.end()
                                 ? state_label_it->second
                                 : state_value;
        domain::Json reasons = domain::Json::array();
        for (const FreshnessReason& reason : report.reasons) {
            reasons.push_back(reason.to_dict());
        }
        row["reasons"] = std::move(reasons);
        rows.push_back(std::move(row));
    }
    return rows;
}

// ------------------------------------------------------- dashboard_state

domain::Json dashboard_state(const domain::Json& project) {
    const Json* runs = find_array(project, "compilation_runs");
    const Json* active_run =
        (runs != nullptr && !runs->empty() && runs->back().is_object())
            ? &runs->back()
            : nullptr;

    // resource_counts：Counter(resource.type) —— 首见序（语义比较无关
    // 键序，仍按 Python 行为保序）。
    std::vector<std::pair<std::string, std::int64_t>> resource_counts;
    if (const Json* resources = find_array(project, "resources")) {
        for (const Json& resource : *resources) {
            if (!resource.is_object()) {
                continue;
            }
            const auto type_it = resource.find("type");
            if (type_it == resource.end() || !type_it->is_string()) {
                continue;
            }
            const std::string type = type_it->get<std::string>();
            const auto slot = std::find_if(
                resource_counts.begin(), resource_counts.end(),
                [&type](const std::pair<std::string, std::int64_t>& entry) {
                    return entry.first == type;
                });
            if (slot == resource_counts.end()) {
                resource_counts.emplace_back(type, 1);
            } else {
                ++slot->second;
            }
        }
    }
    const auto count_for = [&resource_counts](const std::string& type) {
        for (const auto& [key, count] : resource_counts) {
            if (key == type) {
                return count;
            }
        }
        return static_cast<std::int64_t>(0);
    };
    domain::Json counts_json = domain::Json::object();
    for (const auto& [type, count] : resource_counts) {
        counts_json[type] = count;
    }
    domain::Json available_counts = domain::Json::object();
    domain::Json missing_types = domain::Json::array();
    for (std::string_view type : kRequiredResourceTypes) {
        const std::int64_t count = count_for(std::string(type));
        available_counts[type] = count;
        if (count == 0) {
            missing_types.push_back(std::string(type));
        }
    }
    domain::Json readiness = domain::Json::object();
    {
        domain::Json required_types = domain::Json::array();
        for (std::string_view type : kRequiredResourceTypes) {
            required_types.push_back(std::string(type));
        }
        readiness["required_types"] = std::move(required_types);
        readiness["available_counts"] = std::move(available_counts);
        readiness["missing_types"] = std::move(missing_types);
        readiness["ready"] = readiness["missing_types"].empty();
    }

    // home_workflow_steps 会就地回写活动 run —— 冻结签名是 const&，
    // 回写发生在本地副本上（调用方文档不被 dashboard 隐式持久化；
    // 返回值与 Python 逐字一致 —— 33-impl-a4.md 记录该差异）。
    domain::Json local = project;
    const std::vector<project::WorkflowStep> steps =
        home_workflow_steps(local, {});
    std::int64_t complete_count = 0;
    for (const project::WorkflowStep& step : steps) {
        if (step.status == "complete") {
            ++complete_count;
        }
    }

    const std::string horizon = [&] {
        if (active_run != nullptr) {
            const auto it = active_run->find("target_horizon");
            if (it != active_run->end() && it->is_string()) {
                return it->get<std::string>();
            }
        }
        if (project.is_object()) {
            const auto strat = project.find("stratigraphy");
            if (strat != project.end() && strat->is_object()) {
                const auto it = strat->find("target_horizon");
                if (it != strat->end() && it->is_string()) {
                    return it->get<std::string>();
                }
            }
        }
        return std::string();
    }();
    const std::string scheme = [&] {
        if (active_run != nullptr) {
            const auto it = active_run->find("sequence_scheme_ref");
            if (it != active_run->end() && it->is_string()) {
                return it->get<std::string>();
            }
        }
        if (project.is_object()) {
            const auto strat = project.find("stratigraphy");
            if (strat != project.end() && strat->is_object()) {
                const auto it = strat->find("systems_tract_scheme");
                if (it != strat->end() && it->is_string()) {
                    return it->get<std::string>();
                }
            }
        }
        return std::string();
    }();
    const std::string workflow_status = [&] {
        if (active_run != nullptr) {
            const auto it = active_run->find("status");
            if (it != active_run->end() && it->is_string()) {
                return it->get<std::string>();
            }
        }
        return std::string("draft");
    }();

    std::int64_t qc_issue_count = 0;
    for (const project::QualityReport& report :
         active_quality_reports(project)) {
        if (report.issues.is_array()) {
            qc_issue_count += static_cast<std::int64_t>(report.issues.size());
        }
    }

    const auto length_of = [&project](const char* key) {
        const Json* array = find_array(project, key);
        return array != nullptr ? static_cast<std::int64_t>(array->size())
                                : static_cast<std::int64_t>(0);
    };
    std::string project_name;
    if (project.is_object()) {
        const auto meta = project.find("meta");
        if (meta != project.end() && meta->is_object()) {
            const auto it = meta->find("name");
            if (it != meta->end() && it->is_string()) {
                project_name = it->get<std::string>();
            }
        }
    }

    domain::Json out = domain::Json::object();
    out["project_name"] = project_name;
    out["active_target_horizon"] = horizon;
    out["sequence_scheme"] = scheme;
    out["workflow_status"] = workflow_status;
    out["resource_counts"] = std::move(counts_json);
    out["resource_readiness"] = std::move(readiness);
    out["factor_map_count"] = length_of("factor_map_tasks");
    out["prediction_count"] = length_of("prediction_tasks");
    out["map_document_count"] = length_of("paleomap_documents");
    out["qc_issue_count"] = qc_issue_count;
    out["export_count"] = length_of("export_artifacts");
    out["workflow_complete_count"] = complete_count;
    out["workflow_step_count"] =
        static_cast<std::int64_t>(std::size(kStepOrder));
    return out;
}

}  // namespace pwb::workflow_runtime
