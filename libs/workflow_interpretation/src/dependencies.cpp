// MappingDependencyService.evaluate — see dependencies.hpp. Pure domain
// query over the catalog rail; verdicts never fabricated.

#include "pwb/workflow_interpretation/dependencies.hpp"

#include "pwb/workflow_interpretation/compilation.hpp"
#include "pwb/workflow_runtime/constraint_versions.hpp"

#include <algorithm>
#include <map>
#include <optional>
#include <set>
#include <tuple>
#include <utility>

namespace pwb::workflow_interpretation {
namespace {

using workflow_runtime::CatalogRepository;
using workflow_runtime::RunRecord;
using workflow_runtime::VersionRecord;

const Json* find_member(const Json& object, const char* key) {
    if (!object.is_object()) return nullptr;
    const auto it = object.find(key);
    return it == object.end() ? nullptr : &*it;
}

const Json* find_array(const Json& object, const char* key) {
    const Json* value = find_member(object, key);
    return value != nullptr && value->is_array() ? value : nullptr;
}

std::string str_field(const Json& object, const char* key) {
    const Json* value = find_member(object, key);
    if (value == nullptr) return "";
    if (value->is_string()) return value->get<std::string>();
    if (value->is_number_integer()) return std::to_string(value->get<long long>());
    if (value->is_number()) {
        const double d = value->get<double>();
        if (d == static_cast<double>(static_cast<long long>(d))) {
            return std::to_string(static_cast<long long>(d));
        }
        return value->dump();
    }
    if (value->is_boolean()) return value->get<bool>() ? "True" : "False";
    return "";
}

std::string str_value(const Json& value) {
    if (value.is_string()) return value.get<std::string>();
    if (value.is_number_integer()) return std::to_string(value.get<long long>());
    if (value.is_number()) return value.dump();
    if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
    return "";
}

// Membership records of the workspace Json section.
const Json* memberships(const Json* workspace_state) {
    if (workspace_state == nullptr) return nullptr;
    const Json* m = find_member(*workspace_state, "memberships");
    return m != nullptr && m->is_object() ? m : nullptr;
}

// -- catalog helpers (MappingDependencyService private accessors) -------

// _asset_current_version: the rail's list_versions is version-sorted
// (oldest → latest), so the asset tip is the last entry — the Python
// "version_number missing → last-in-list fallback" corner collapses onto
// the same rule.
std::optional<std::string> asset_current_version(
    CatalogRepository* catalog, const std::string& asset_id) {
    if (catalog == nullptr || asset_id.empty()) return std::nullopt;
    try {
        const std::vector<VersionRecord> versions =
            catalog->list_versions(asset_id);
        if (versions.empty()) return std::nullopt;
        return versions.back().version_id;
    } catch (...) {
        return std::nullopt;
    }
}

std::optional<VersionRecord> version_info(
    CatalogRepository* catalog, const std::string& version_id) {
    if (catalog == nullptr || version_id.empty()) return std::nullopt;
    try {
        return catalog->resolve_version(version_id);
    } catch (...) {
        return std::nullopt;
    }
}

std::vector<std::string> run_input_versions(
    CatalogRepository* catalog, const std::string& run_id) {
    if (catalog == nullptr || run_id.empty()) return {};
    try {
        const std::optional<RunRecord> run = catalog->resolve_run(run_id);
        if (!run.has_value()) return {};
        return run->input_version_ids;
    } catch (...) {
        return {};
    }
}

// _check_pinned_versions → (status, culprits, detail).
std::tuple<std::string, std::vector<std::string>, std::string>
check_pinned_versions(CatalogRepository* catalog,
                      const std::vector<std::string>& pinned) {
    // WI2: no catalog attached means the check is UNVERIFIABLE — the
    // header contract says null catalog degrades verifiable checks to
    // UNKNOWN; fabricating "missing" (version cleaned) misleads the
    // stale-input UI when the truth is only "no catalog wired".
    if (catalog == nullptr) {
        return {freshness_status::kUnknown, {},
                "无法验证（未接入目录服务）"};
    }
    std::vector<std::string> missing;
    std::vector<std::string> stale;
    for (const std::string& version_id : pinned) {
        const std::optional<VersionRecord> info =
            version_info(catalog, version_id);
        if (!info.has_value()) {
            missing.push_back(version_id);
            continue;
        }
        const std::optional<std::string> current =
            asset_current_version(catalog, info->asset_id);
        if (current.has_value() && *current != version_id) {
            stale.push_back(version_id);
        }
    }
    if (!missing.empty()) {
        return {freshness_status::kMissingInput, missing,
                "输入版本缺失或已清理"};
    }
    if (!stale.empty()) {
        return {freshness_status::kStale, stale, "上游输入已有新版本"};
    }
    return {freshness_status::kCurrent, {}, ""};
}

// _check_output_superseded.
bool output_superseded(CatalogRepository* catalog,
                       const std::string& output_version_id) {
    const std::optional<VersionRecord> info =
        version_info(catalog, output_version_id);
    if (!info.has_value()) return false;
    const std::optional<std::string> current =
        asset_current_version(catalog, info->asset_id);
    return current.has_value() && *current != output_version_id;
}

// -- per-stage evaluators ------------------------------------------------

std::vector<ArtifactFreshness> evaluate_phase1_drafts(
    const Json* workspace_state, CatalogRepository* catalog) {
    std::vector<ArtifactFreshness> results;
    const Json* members = memberships(workspace_state);
    if (members == nullptr) return results;
    for (auto it = members->begin(); it != members->end(); ++it) {
        const std::string layer_id = it.key();
        if (str_field(it.value(), "role") != "initial_facies_draft") continue;
        const std::string key = phase1_draft_key(layer_id);
        const std::string pinned_id = str_field(it.value(), "source_version_id");
        const std::vector<std::string> pinned =
            pinned_id.empty() ? std::vector<std::string>{}
                              : std::vector<std::string>{pinned_id};
        if (pinned.empty()) {
            results.push_back(ArtifactFreshness{
                key, artifact_type::kPhase1Draft,
                freshness_stage::kFaciesCalibration,
                freshness_status::kUnknown,
                "草稿未钉住 RAW 版本（旧工程迁移）"});
            continue;
        }
        if (catalog == nullptr) {
            // 评审 R3-F7：无目录=不可验证（UNKNOWN），不是"输入被清理"。
            results.push_back(ArtifactFreshness{
                key, artifact_type::kPhase1Draft,
                freshness_stage::kFaciesCalibration,
                freshness_status::kUnknown,
                "无目录服务，钉住的 RAW 版本不可验证",
                {{"version", pinned_id}}});
            continue;
        }
        const auto [status, culprits, detail] =
            check_pinned_versions(catalog, pinned);
        results.push_back(ArtifactFreshness{
            key, artifact_type::kPhase1Draft,
            freshness_stage::kFaciesCalibration, status, detail,
            {{"version", pinned_id}}, culprits});
    }
    return results;
}

std::vector<ArtifactFreshness> evaluate_factors(
    const Json& document, CatalogRepository* catalog) {
    std::vector<ArtifactFreshness> results;
    const Json* tasks = find_array(document, "factor_map_tasks");
    if (tasks == nullptr) return results;
    for (const Json& task : *tasks) {
        const std::string task_id = str_field(task, "id");
        const std::string key = factor_key(task_id);
        const std::string grid_version =
            str_field(task, "grid_artifact_version_id");
        if (grid_version.empty()) {
            results.push_back(ArtifactFreshness{
                key, artifact_type::kFactor,
                freshness_stage::kConstraintFactor,
                freshness_status::kUnknown, "任务尚无插值结果版本"});
            continue;
        }
        const std::optional<VersionRecord> info =
            version_info(catalog, grid_version);
        // DataVersionRef.producing_run_id parity (V13 fix comment).
        const std::string run_id =
            info.has_value() && info->producing_run_id.has_value()
                ? *info->producing_run_id
                : "";
        const std::vector<std::string> inputs =
            run_input_versions(catalog, run_id);
        if (inputs.empty()) {
            results.push_back(ArtifactFreshness{
                key, artifact_type::kFactor,
                freshness_stage::kConstraintFactor,
                freshness_status::kUnknown, "插值 run 未登记输入版本"});
            continue;
        }
        auto [status, culprits, detail] =
            check_pinned_versions(catalog, inputs);
        if (status == freshness_status::kCurrent &&
            output_superseded(catalog, grid_version)) {
            status = freshness_status::kSuperseded;
            detail = "已有更新的插值结果版本";
        }
        std::vector<std::pair<std::string, std::string>> pinned;
        pinned.reserve(inputs.size());
        for (const std::string& v : inputs) pinned.emplace_back("version", v);
        results.push_back(ArtifactFreshness{
            key, artifact_type::kFactor,
            freshness_stage::kConstraintFactor, status, detail,
            std::move(pinned), culprits});
    }
    return results;
}

std::vector<ArtifactFreshness> evaluate_integrated(
    const Json& document, const Json* workspace_state,
    CatalogRepository* catalog) {
    std::vector<ArtifactFreshness> results;
    const Json* members = memberships(workspace_state);
    if (members == nullptr) return results;

    // evidence_view — the single consumption adapter (R2-F1).
    const auto input_set = evidence_view(document, workspace_state);
    // 先算上游（draft/factor），传播时复用。
    std::map<std::string, ArtifactFreshness> upstream;
    for (auto& entry : evaluate_phase1_drafts(workspace_state, catalog)) {
        upstream.emplace(entry.artifact_key, std::move(entry));
    }
    for (auto& entry : evaluate_factors(document, catalog)) {
        upstream.emplace(entry.artifact_key, std::move(entry));
    }
    std::map<std::string, std::string> task_grid_version;
    if (const Json* tasks = find_array(document, "factor_map_tasks")) {
        for (const Json& task : *tasks) {
            task_grid_version[str_field(task, "id")] =
                str_field(task, "grid_artifact_version_id");
        }
    }

    auto is_integrated_role = [](const std::string& role) {
        return role == "integrated_facies" || role == "integrated_boundary";
    };
    const std::string missing = freshness_status::kMissingInput;

    for (auto it = members->begin(); it != members->end(); ++it) {
        const std::string layer_id = it.key();
        if (!is_integrated_role(str_field(it.value(), "role"))) continue;
        const std::string key = integrated_key(layer_id);
        if (input_set.empty()) {
            results.push_back(ArtifactFreshness{
                key, artifact_type::kIntegrated,
                freshness_stage::kIntegratedCompilation,
                freshness_status::kUnknown,
                "未选择证据版本（Compilation Input Set 为空）"});
            continue;
        }
        std::vector<std::pair<std::string, std::string>> pinned_inputs;
        std::vector<std::string> culprits;
        std::string worst;
        std::string detail;
        for (const auto& [ref_key, raw] : input_set) {
            const std::string value = raw;
            if (value.empty()) continue;
            if (value.rfind("draft:", 0) == 0) {
                const std::string upstream_key =
                    phase1_draft_key(value.substr(6));
                const auto entry_it = upstream.find(upstream_key);
                if (entry_it != upstream.end()) {
                    pinned_inputs.emplace_back(ref_key, value);
                    if (entry_it->second.is_problem() && worst != missing) {
                        worst = entry_it->second.status;
                        culprits.push_back(entry_it->second.artifact_key);
                        detail = "上游证据已过期：" +
                                 entry_it->second.artifact_key;
                    }
                }
            } else if (value.rfind("factor:", 0) == 0) {
                // factor:<task_id>[:<version>]
                const std::string rest = value.substr(7);
                const auto sep = rest.find(':');
                const std::string task_id =
                    sep == std::string::npos ? rest : rest.substr(0, sep);
                const std::string pinned_version =
                    sep == std::string::npos ? "" : rest.substr(sep + 1);
                pinned_inputs.emplace_back(ref_key, value);
                // 评审 R3-F3：先看上游 factor 评估——任务被删除/无结果版本
                // 时其 factor 条目即 MISSING/UNKNOWN，综合解释绝不能因此
                // 读作 CURRENT。
                const auto upstream_it =
                    upstream.find(factor_key(task_id));
                if (upstream_it == upstream.end()) {
                    if (worst != missing) {
                        worst = missing;
                        culprits.push_back(factor_key(task_id));
                        detail = "证据单因素任务不存在（" + ref_key + "）";
                    }
                } else if (upstream_it->second.is_problem() &&
                           worst != missing) {
                    worst = upstream_it->second.status;
                    culprits.push_back(upstream_it->second.artifact_key);
                    detail =
                        "上游证据已过期：" + upstream_it->second.artifact_key;
                } else if (upstream_it->second.status ==
                           freshness_status::kUnknown) {
                    if (worst.empty()) {
                        worst = freshness_status::kUnknown;
                        detail = "证据单因素状态未知（" + ref_key + "）";
                    }
                }
                const auto grid_it = task_grid_version.find(task_id);
                if (!pinned_version.empty() &&
                    grid_it != task_grid_version.end() &&
                    !grid_it->second.empty() &&
                    grid_it->second != pinned_version &&
                    worst != missing) {
                    worst = freshness_status::kSuperseded;
                    culprits.push_back(factor_key(task_id));
                    detail = "证据单因素已有新结果版本（" + ref_key + "）";
                }
            } else if (value.rfind("constraints:", 0) == 0) {
                // V8 M2: constraint refs resolve against committed catalog
                // versions — resolve_constraint_ref verdict strings map
                // onto the freshness vocabulary; resolution failure keeps
                // the honest UNKNOWN, never a fabricated CURRENT.
                pinned_inputs.emplace_back(ref_key, value);
                try {
                    const Json verdict = workflow_runtime::
                        resolve_constraint_ref(document, catalog, value);
                    // _FRESHNESS_FROM_CONSTRAINT parity: current/stale/
                    // superseded/unknown map; every other value → UNKNOWN.
                    const std::string state = str_field(verdict, "status");
                    const std::string mapped =
                        (state == "stale" || state == "superseded")
                            ? state
                            : (state == "current"
                                   ? freshness_status::kCurrent
                                   : freshness_status::kUnknown);
                    if (mapped != freshness_status::kCurrent &&
                        mapped != freshness_status::kUnknown &&
                        worst != missing) {
                        worst = mapped;
                        culprits.push_back(ref_key);
                        detail = str_field(verdict, "detail");
                    }
                } catch (...) {
                    // Resolution failure must NOT fabricate freshness:
                    // honest UNKNOWN (never CURRENT).
                    if (worst.empty()) worst = freshness_status::kUnknown;
                }
            } else if (looks_like_version_id(value)) {
                pinned_inputs.emplace_back(ref_key, value);
                const auto [status, bad, why] =
                    check_pinned_versions(catalog, {value});
                if (status != freshness_status::kCurrent &&
                    worst != missing) {
                    worst = status;
                    culprits.insert(culprits.end(), bad.begin(), bad.end());
                    detail = why;
                }
            }
        }
        if (worst.empty()) worst = freshness_status::kCurrent;
        results.push_back(ArtifactFreshness{
            key, artifact_type::kIntegrated,
            freshness_stage::kIntegratedCompilation, worst, detail,
            std::move(pinned_inputs), std::move(culprits)});
    }
    return results;
}

std::vector<ArtifactFreshness> evaluate_map_products(
    const Json& document, CatalogRepository* catalog) {
    std::vector<ArtifactFreshness> results;
    const Json* products = find_array(document, "map_products");
    if (products == nullptr) return results;
    for (const Json& record : *products) {
        const std::string key = mapproduct_key(str_field(record, "id"));
        const std::string output_version =
            str_field(record, "output_version_id");
        const std::string run_id = str_field(record, "run_id");
        const std::vector<std::string> inputs =
            run_input_versions(catalog, run_id);
        if (output_version.empty() || inputs.empty()) {
            results.push_back(ArtifactFreshness{
                key, artifact_type::kMapProduct,
                freshness_stage::kIntegratedCompilation,
                freshness_status::kUnknown, "产品未登记完整溯源 run"});
            continue;
        }
        auto [status, culprits, detail] =
            check_pinned_versions(catalog, inputs);
        if (status == freshness_status::kCurrent &&
            output_superseded(catalog, output_version)) {
            status = freshness_status::kSuperseded;
            detail = "产品已被更新版本取代";
        }
        std::vector<std::pair<std::string, std::string>> pinned;
        pinned.reserve(inputs.size());
        for (const std::string& v : inputs) pinned.emplace_back("version", v);
        results.push_back(ArtifactFreshness{
            key, artifact_type::kMapProduct,
            freshness_stage::kIntegratedCompilation, status, detail,
            std::move(pinned), culprits});
    }
    return results;
}

}  // namespace

// -- artifact keys --------------------------------------------------------

std::string factor_key(const std::string& task_id) {
    return "factor:" + task_id;
}
std::string phase1_draft_key(const std::string& layer_id) {
    return "phase1_draft:" + layer_id;
}
std::string integrated_key(const std::string& layer_id) {
    return "integrated:" + layer_id;
}
std::string mapproduct_key(const std::string& record_id) {
    return "mapproduct:" + record_id;
}

std::string freshness_status_label(const std::string& status) {
    if (status == freshness_status::kCurrent) return "最新";
    if (status == freshness_status::kStale) return "已过期";
    if (status == freshness_status::kMissingInput) return "输入缺失";
    if (status == freshness_status::kSuperseded) return "已被取代";
    return "状态未知";
}

bool ArtifactFreshness::is_problem() const {
    return status == freshness_status::kStale ||
           status == freshness_status::kMissingInput ||
           status == freshness_status::kSuperseded;
}

Json ArtifactFreshness::to_dict() const {
    Json pinned = Json::array();
    for (const auto& [k, v] : pinned_inputs) {
        pinned.push_back(Json::array({k, v}));
    }
    Json culprits = Json::array();
    for (const std::string& c : upstream_culprits) culprits.push_back(c);
    return Json::object({
        {"artifact_key", artifact_key},
        {"artifact_type", type},
        {"stage", stage},
        {"status", status},
        {"status_label", status_label()},
        {"detail", detail},
        {"is_problem", is_problem()},
        {"pinned_inputs", std::move(pinned)},
        {"upstream_culprits", std::move(culprits)},
    });
}

std::vector<ArtifactFreshness> evaluate_workspace_freshness(
    const Json& document, const Json* workspace_state,
    workflow_runtime::CatalogRepository* catalog) {
    std::vector<ArtifactFreshness> entries;
    auto phase1 = evaluate_phase1_drafts(workspace_state, catalog);
    auto factors = evaluate_factors(document, catalog);
    auto integrated =
        evaluate_integrated(document, workspace_state, catalog);
    auto products = evaluate_map_products(document, catalog);
    entries.reserve(phase1.size() + factors.size() + integrated.size() +
                    products.size());
    std::move(phase1.begin(), phase1.end(), std::back_inserter(entries));
    std::move(factors.begin(), factors.end(), std::back_inserter(entries));
    std::move(integrated.begin(), integrated.end(),
              std::back_inserter(entries));
    std::move(products.begin(), products.end(), std::back_inserter(entries));
    return entries;
}

Json stale_summary_json(const std::vector<ArtifactFreshness>& entries) {
    Json artifacts = Json::array();
    for (const ArtifactFreshness& entry : entries) {
        artifacts.push_back(entry.to_dict());
    }
    return Json::object({{"artifacts", std::move(artifacts)}});
}

std::vector<ArtifactFreshness> stale_entries(
    const std::vector<ArtifactFreshness>& entries) {
    std::vector<ArtifactFreshness> out;
    for (const ArtifactFreshness& entry : entries) {
        if (entry.is_problem()) out.push_back(entry);
    }
    return out;
}

std::string stale_headline(const std::vector<ArtifactFreshness>& entries) {
    const std::size_t count = stale_entries(entries).size();
    if (count == 0) return "";
    if (count == 1) return "1 项输入成果已过期";
    return std::to_string(count) + " 项输入成果已过期";
}

bool looks_like_version_id(const std::string& value) {
    if (value.rfind("ver_", 0) == 0 || value.rfind("dver_", 0) == 0) {
        return true;
    }
    return value.size() >= 32 && value.find('-') != std::string::npos &&
           value.rfind("sha:", 0) != 0;
}

}  // namespace pwb::workflow_interpretation
