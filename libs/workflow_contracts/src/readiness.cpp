#include <pwb/workflow_contracts/readiness.hpp>

#include <filesystem>
#include <set>

namespace pwb::workflow_contracts {
namespace {

// getattr-or-empty helpers (D4): the Python code reads
// ``getattr(o, k, None) or X`` chains over duck-typed records; here the
// records are Json and a missing/null member is Python's None.
const Json& null_json() {
    static const Json j;
    return j;
}

const Json& member(const Json& o, const char* key) {
    if (!o.is_object()) return null_json();
    const auto it = o.find(key);
    return it == o.end() ? null_json() : *it;
}

// getattr(o, k, None) or [] — list members only.
Json list_member(const Json& o, const char* key) {
    const Json& v = member(o, key);
    return v.is_array() ? v : Json::array();
}

// getattr(o, k, None) or {} — object members only.
Json dict_member(const Json& o, const char* key) {
    const Json& v = member(o, key);
    return v.is_object() ? v : Json::object();
}

// getattr(o, k, "") or "" — string members; non-strings behave like the
// raw value which is falsy only when missing/null/empty here.
std::string str_member(const Json& o, const char* key) {
    const Json& v = member(o, key);
    return v.is_string() ? v.get<std::string>() : std::string{};
}

bool truthy(const Json& v) {
    if (v.is_null()) return false;
    if (v.is_boolean()) return v.get<bool>();
    if (v.is_number()) return v.get<double>() != 0.0;
    if (v.is_string()) return !v.get<std::string>().empty();
    return !v.empty();  // array/object: len
}

std::string strip(const std::string& s) {
    const auto b = s.find_first_not_of(" \t\n\v\f\r");
    if (b == std::string::npos) return "";
    const auto e = s.find_last_not_of(" \t\n\v\f\r");
    return s.substr(b, e - b + 1);
}

// _resource_payload_present — Path checks reach the FS only for absolute
// paths or a real project_root dir (D6).
bool resource_payload_present(const Json& resource,
                              const ProjectView& project) {
    // getattr(resource, "status", "indexed") == "missing"
    const Json& st = member(resource, "status");
    const std::string status =
        st.is_string() ? st.get<std::string>() : "indexed";
    if (status == "missing") return false;
    const std::string path = str_member(resource, "path");
    if (path.empty()) return true;
    const std::filesystem::path candidate(path);
    if (candidate.is_absolute())
        return std::filesystem::exists(candidate);
    const std::string root = str_member(project.meta, "project_root");
    if (!root.empty() && root != ".") {
        const std::filesystem::path root_path(root);
        if (std::filesystem::is_directory(root_path))
            return std::filesystem::exists(root_path / path);
    }
    return true;
}

// _resource_counts — type-keyed presence counts.
std::map<std::string, int> resource_counts(const ProjectView& project) {
    std::map<std::string, int> counts;
    const Json resources = project.resources.is_array()
                               ? project.resources
                               : Json::array();
    for (const auto& r : resources) {
        if (!resource_payload_present(r, project)) continue;
        std::string t = str_member(r, "type");
        if (t.empty()) t = "unknown";
        counts[t] += 1;
    }
    return counts;
}

int count_complete_factor_maps(const ProjectView& project) {
    int n = 0;
    for (const auto& t : project.factor_map_tasks)
        if (str_member(t, "status") == "complete") ++n;
    return n;
}

int count_for_types(const std::map<std::string, int>& counts,
                    const std::vector<std::string>& types) {
    int n = 0;
    for (const auto& t : types) {
        const auto it = counts.find(t);
        if (it != counts.end()) n += it->second;
    }
    return n;
}

void add_reason(std::vector<ReadinessReason>& reasons,
                const std::string& code, const std::string& message_zh,
                const char* severity,
                std::optional<std::string> input_id = std::nullopt) {
    ReadinessReason r;
    r.code = code;
    r.message_zh = message_zh;
    r.severity = severity;
    r.input_id = std::move(input_id);
    reasons.push_back(std::move(r));
}

}  // namespace

ProjectView ProjectView::from_json(const Json& j) {
    ProjectView p;
    if (!j.is_object()) return p;
    const auto take = [&](const char* key, Json& dst) {
        const auto it = j.find(key);
        if (it != j.end()) dst = *it;
    };
    take("resources", p.resources);
    take("factor_map_tasks", p.factor_map_tasks);
    take("paleomap_documents", p.paleomap_documents);
    take("stratigraphy", p.stratigraphy);
    take("correlation_interpretations", p.correlation_interpretations);
    take("prediction_tasks", p.prediction_tasks);
    take("export_artifacts", p.export_artifacts);
    take("meta", p.meta);
    return p;
}

Json ReadinessReport::to_dict() const {
    Json rs = Json::array();
    for (const auto& r : reasons) rs.push_back(r.model_dump());
    return Json{{"contract_id", contract_id},
                {"status", to_string(status)},
                {"reasons", std::move(rs)},
                {"implementation_status", to_string(implementation_status)},
                {"freshness_note", freshness_note}};
}

ReadinessReport evaluate_contract_readiness(
    const ProjectView& project, const DomainWorkflowContract& contract,
    const ProductionModelProbe* catalog) {
    std::vector<ReadinessReason> reasons;
    const auto counts = resource_counts(project);

    const Json tasks = project.factor_map_tasks.is_array()
                           ? project.factor_map_tasks
                           : Json::array();
    const Json docs = project.paleomap_documents.is_array()
                          ? project.paleomap_documents
                          : Json::array();

    for (const auto& inp : contract.inputs) {
        if (!inp.required) continue;
        int n = 0;
        if (!inp.resource_types.empty())
            n = count_for_types(counts, inp.resource_types);
        else if (inp.id == "sample_points") {
            for (const auto& t : tasks)
                if (truthy(member(dict_member(t, "parameters"),
                                  "sample_points")))
                    ++n;
        } else if (inp.id == "target_horizon") {
            if (!strip(str_member(project.stratigraphy, "target_horizon"))
                     .empty())
                n = 1;
            if (n < 1)
                for (const auto& t : tasks)
                    if (!strip(str_member(t, "target_horizon")).empty()) {
                        n = 1;
                        break;
                    }
            if (n < 1)
                for (const auto& d : docs)
                    if (!strip(str_member(d, "linked_target_horizon"))
                             .empty()) {
                        n = 1;
                        break;
                    }
        } else if (inp.id == "map_document") {
            n = static_cast<int>(docs.size());
        } else if (inp.id == "factor_maps") {
            n = count_complete_factor_maps(project);
        } else if (inp.id == "source_products" ||
                   inp.id == "prediction_or_factors" ||
                   inp.id == "parent_version" ||
                   inp.id == "seismic_or_seed") {
            continue;
        } else if (inp.id == "wells" || inp.id == "well_logs" ||
                   inp.id == "las_files") {
            const auto it = counts.find("well_log");
            n = it == counts.end() ? 0 : it->second;
        } else if (inp.id == "segy" || inp.id == "seismic") {
            const auto it = counts.find("seismic");
            n = it == counts.end() ? 0 : it->second;
        } else if (inp.id == "source_files") {
            for (const auto& [t, c] : counts) n += c;
        }

        const int need = 1;  // Python: both ONE_OR_MORE and EXACTLY_ONE → 1
        if (n < need)
            add_reason(reasons, "missing_input:" + inp.id,
                       "缺少必需输入：" + inp.name, "block", inp.id);
        else if (n > 1 && inp.cardinality == InputCardinality::EXACTLY_ONE)
            add_reason(reasons, "ambiguous_input:" + inp.id,
                       inp.name + " 需要恰好一个输入，当前有 " +
                           std::to_string(n) + " 个",
                       "warn", inp.id);
    }

    if (contract.id == "well_correlation") {
        const auto it = counts.find("well_log");
        if ((it == counts.end() ? 0 : it->second) < 2)
            add_reason(reasons, "need_two_wells",
                       "连井对比至少需要 2 口井", "block");
        const Json refs = project.correlation_interpretations.is_array()
                              ? project.correlation_interpretations
                              : Json::array();
        for (const auto& ref : refs) {
            std::vector<std::string> domains;
            for (const auto& d :
                 list_member(ref, "depth_domains"))
                if (d.is_string()) domains.push_back(d.get<std::string>());
            if (domains.empty()) {
                const std::string d0 = str_member(ref, "depth_domain");
                if (!d0.empty()) domains.push_back(d0);
            }
            std::set<std::string> distinct;
            for (const auto& d : domains)
                if (!d.empty()) distinct.insert(d);
            if (distinct.size() > 1) {
                std::string joined;
                for (const auto& d : distinct)
                    joined += (joined.empty() ? "" : "、") + d;
                add_reason(reasons, "depth_domain_mismatch",
                           "对比解释中存在混用深度域: " + joined +
                               "（软件不自动转换）",
                           "warn");
                break;
            }
        }
    }

    if (contract.id == "factor_interpolation") {
        // Python's lazy resolve_correlation_target_horizon call has no
        // observable effect (its result is only `pass`) — D11 non-goal.
        if (tasks.empty())
            add_reason(reasons, "no_factor_task", "尚未创建单因素图任务",
                       "block");
        else {
            std::size_t incomplete = 0;
            for (const auto& t : tasks)
                if (!truthy(member(dict_member(t, "parameters"),
                                   "sample_points")))
                    ++incomplete;
            if (incomplete == tasks.size())
                add_reason(reasons, "no_sample_points",
                           "单因素任务缺少样点 sample_points", "block");
            bool any_horizon = false;
            for (const auto& t : tasks)
                if (!strip(str_member(t, "target_horizon")).empty()) {
                    any_horizon = true;
                    break;
                }
            if (!any_horizon)
                add_reason(reasons, "no_target_horizon", "缺少目标层位",
                           "block");
        }
    }

    if (contract.id == "paleomap_compile") {
        if (docs.empty())
            add_reason(reasons, "no_paleomap_document",
                       "尚未创建古地理图文档", "block");
        else {
            bool any_link = false;
            for (const auto& d : docs)
                if (!strip(str_member(d, "linked_target_horizon"))
                         .empty()) {
                    any_link = true;
                    break;
                }
            if (!any_link)
                add_reason(reasons, "no_linked_target_horizon",
                           "古地理图未关联目标层位", "block");
        }
        bool only_demo = !docs.empty();
        if (only_demo)
            for (const auto& d : docs)
                if (!truthy(member(dict_member(d, "view_state"),
                                   "is_demo_draft"))) {
                    only_demo = false;
                    break;
                }
        if (only_demo)
            add_reason(reasons, "paleomap_demo_only",
                       "当前仅有演示草稿图；生产编图需要真实空间预测几何",
                       "warn");
    }

    if (contract.id == "facies_prediction") {
        const Json preds = project.prediction_tasks.is_array()
                               ? project.prediction_tasks
                               : Json::array();
        if (tasks.empty() && preds.empty())
            add_reason(reasons, "prediction_demo_only",
                       "无单因素输入；仅可运行演示/mock 预测路径", "warn");
        bool all_mock = !preds.empty();
        if (all_mock)
            for (const auto& t : preds) {
                const Json& k = member(t, "adapter_kind");
                const std::string kind =
                    k.is_string() ? k.get<std::string>() : "mock";
                if (kind != "mock") {
                    all_mock = false;
                    break;
                }
            }
        if (all_mock)
            add_reason(reasons, "mock_adapter",
                       "当前预测适配器为 mock（非生产模型）", "warn");
        // Catalog probe seam (D5): three observable outcomes.
        if (catalog == nullptr)
            add_reason(reasons, "no_production_model",
                       "未配置生产模型（目录未连接）", "warn");
        else {
            try {
                if (!catalog->find_production_model(kCapabilityFacies)
                         .has_value())
                    add_reason(reasons, "no_production_model",
                               "未配置生产模型；科学预测不可用（演示路径仍可"
                               "单独运行）",
                               "warn");
            } catch (...) {
                add_reason(reasons, "catalog_read_error",
                           "目录查询失败，无法确认生产模型状态", "warn");
            }
        }
    }

    if (contract.id == "quality_control" && docs.empty())
        add_reason(reasons, "no_map", "无可质检的古地理图文档", "block");

    if (contract.id == "export") {
        const Json preds = project.prediction_tasks;
        const Json arts = project.export_artifacts;
        const bool has_anything =
            (docs.is_array() && !docs.empty()) ||
            (preds.is_array() && !preds.empty()) ||
            (tasks.is_array() && !tasks.empty()) ||
            (arts.is_array() && !arts.empty());
        if (!has_anything)
            add_reason(reasons, "nothing_to_export", "无可导出的成果",
                       "block");
    }

    if (contract.id == "geomodel_3d")
        add_reason(reasons, "demo_modeling",
                   "三维建模模块当前实现以演示/合成为主", "warn");

    bool has_block = false, has_warn = false;
    for (const auto& r : reasons) {
        if (r.severity == "block") has_block = true;
        if (r.severity == "warn") has_warn = true;
    }
    ReadinessReport report;
    report.contract_id = contract.id;
    report.reasons = std::move(reasons);
    report.implementation_status = contract.implementation_status;
    report.status =
        has_block          ? ReadinessStatus::BLOCKED
        : has_warn         ? ReadinessStatus::PARTIAL
        : contract.implementation_status ==
                ImplementationStatus::PLACEHOLDER
            ? ReadinessStatus::UNKNOWN
            : ReadinessStatus::READY;
    return report;
}

ReadinessReport evaluate_readiness(
    const ProjectView& project, const std::string& contract_id,
    const WorkflowContractRegistry* registry,
    const ProductionModelProbe* catalog) {
    const WorkflowContractRegistry& reg =
        registry ? *registry : get_default_registry();
    const DomainWorkflowContract* c = reg.get_contract(contract_id);
    if (c == nullptr) {
        ReadinessReport r;
        r.contract_id = contract_id;
        r.status = ReadinessStatus::UNKNOWN;
        ReadinessReason reason;
        reason.code = "unknown_contract";
        reason.message_zh = "未知模块合同：" + contract_id;
        reason.severity = "block";
        r.reasons.push_back(std::move(reason));
        return r;
    }
    return evaluate_contract_readiness(project, *c, catalog);
}

}  // namespace pwb::workflow_contracts
