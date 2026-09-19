// CONV-32 — FactorProduct projection (factor_product.py port). See header.
// Deviations (documented):
//  * FACTOR_FAMILIES is not exported by the frozen factor_units.hpp, so the
//    6-entry family table is frozen LOCALLY below (values verbatim from
//    paleo_workbench/workflow/factor_units.py).
//  * Key normalization reuses factor_fusion::normalize_factor_key — the
//    CONV-24-proven exact str.strip().lower() (Unicode-aware).
//  * JSON booleans in grid height/width are accepted as 1/0 (Python
//    isinstance(True, int) is True); the oracle keeps shapes integral.
#include <pwb/workflow_interpretation/factor_product.hpp>

#include <pwb/factor_fusion/factor_units.hpp>
#include <pwb/workflow_interpretation/algorithm_registry.hpp>

#include <array>
#include <charconv>
#include <cmath>
#include <optional>
#include <string>
#include <utility>

namespace pwb::workflow_interpretation {
namespace {

// --- Python truthiness / str() coercions ------------------------------------

// Python bool(x): null/False/0/""/empty container -> false.
[[nodiscard]] bool truthy(const Json& v) {
    if (v.is_null()) return false;
    if (v.is_boolean()) return v.get<bool>();
    if (v.is_number_integer()) {
        return v.is_number_unsigned() ? v.get<unsigned long long>() != 0
                                      : v.get<long long>() != 0;
    }
    if (v.is_number_float()) return v.get<double>() != 0.0;
    if (v.is_string()) return !v.get_ref<const std::string&>().empty();
    if (v.is_array() || v.is_object()) return !v.empty();
    return false;
}

// str-field read: string value or "" (task fields are strings / null / absent).
[[nodiscard]] std::string str_field(const Json& obj, const char* key) {
    const auto it = obj.find(key);
    if (it != obj.end() && it->is_string()) {
        return it->get_ref<const std::string&>();
    }
    return "";
}

// dict(x or {}): object value or empty object (null/absent/other -> {}).
[[nodiscard]] Json object_field(const Json& obj, const char* key) {
    const auto it = obj.find(key);
    if (it != obj.end() && it->is_object()) return *it;
    return Json::object();
}

// Shortest round-trip repr of a double, Python str(float) formatting rules.
[[nodiscard]] std::string py_repr_double(double d) {
    if (std::isnan(d)) return "nan";
    if (std::isinf(d)) return d < 0.0 ? "-inf" : "inf";
    if (d == 0.0) return std::signbit(d) ? "-0.0" : "0.0";
    char buf[64];
    const auto res =
        std::to_chars(buf, buf + sizeof buf, d, std::chars_format::scientific);
    const std::string s(buf, static_cast<std::size_t>(res.ptr - buf));
    bool neg = false;
    std::size_t start = 0;
    if (s[0] == '-') {
        neg = true;
        start = 1;
    }
    const std::size_t epos = s.find('e');
    std::string digits;
    for (const char c : s.substr(start, epos - start)) {
        if (c != '.') digits += c;
    }
    int exp10 = 0;
    std::from_chars(s.data() + epos + 1, s.data() + s.size(), exp10);
    const int decpt = exp10 + 1;  // value = 0.<digits> * 10^decpt
    std::string out;
    if (decpt <= -4 || decpt > 16) {  // CPython float repr format rule
        out = digits.substr(0, 1);
        if (digits.size() > 1) out += "." + digits.substr(1);
        const int e = decpt - 1;
        out += e < 0 ? "e-" : "e+";
        const int ae = e < 0 ? -e : e;
        if (ae < 10) out += '0';
        out += std::to_string(ae);
    } else if (decpt <= 0) {
        out = "0." + std::string(static_cast<std::size_t>(-decpt), '0') + digits;
    } else if (static_cast<std::size_t>(decpt) >= digits.size()) {
        out = digits +
              std::string(static_cast<std::size_t>(decpt) - digits.size(), '0') +
              ".0";
    } else {
        out = digits.substr(0, static_cast<std::size_t>(decpt)) + "." +
              digits.substr(static_cast<std::size_t>(decpt));
    }
    return neg ? "-" + out : out;
}

// str(x) for the descriptor-ish scalars (string in practice; numbers /
// booleans coerce with Python str() semantics).
[[nodiscard]] std::string py_str_scalar(const Json& v) {
    if (v.is_null()) return "";
    if (v.is_boolean()) return v.get<bool>() ? "True" : "False";
    if (v.is_number_unsigned()) return std::to_string(v.get<unsigned long long>());
    if (v.is_number_integer()) return std::to_string(v.get<long long>());
    if (v.is_number_float()) return py_repr_double(v.get<double>());
    if (v.is_string()) return v.get_ref<const std::string&>();
    return "";  // containers never appear on these fields
}

// --- local FACTOR_FAMILIES table (factor_units.py, verbatim) ----------------

struct FamilyAliases {
    const char* family;
    std::vector<const char*> aliases;  // already lowercase
};

// Python reverse lookup: strip+lower the key, membership in the lowercased
// alias set; unknown/empty -> "" (never guessed).
[[nodiscard]] std::string factor_family_lookup(const std::string& factor_type) {
    const std::string key = factor_fusion::normalize_factor_key(factor_type);
    if (key.empty()) return "";
    static const std::array<FamilyAliases, 6> kFamilies{{
        {"sand_thickness", {"砂岩厚度", "sand_thickness", "h_s"}},
        {"formation_thickness", {"地层厚度", "formation_thickness", "h_t"}},
        {"sand_ratio", {"砂地比", "sand_ratio", "r_s"}},
        {"porosity", {"孔隙度", "porosity"}},
        {"probability", {"probability", "概率"}},
        {"paleo_water_depth", {"古水深", "water_depth"}},
    }};
    for (const FamilyAliases& fam : kFamilies) {
        for (const char* alias : fam.aliases) {
            if (key == alias) return fam.family;
        }
    }
    return "";
}

// Python isinstance(v, int) — JSON booleans count (accepted as 1/0).
[[nodiscard]] bool is_py_int(const Json& v) {
    return v.is_number_integer() || v.is_boolean();
}

[[nodiscard]] long long as_py_int(const Json& v) {
    if (v.is_boolean()) return v.get<bool>() ? 1 : 0;
    return v.is_number_unsigned()
               ? static_cast<long long>(v.get<unsigned long long>())
               : v.get<long long>();
}

// 不确定度缺失的诚实原因（评审 R1-F10：从注册表能力推导，不硬编码）。
[[nodiscard]] std::string uncertainty_absent_reason(const std::string& algorithm_id,
                                                    const Json& metadata) {
    const AlgorithmSpec* spec =
        algorithm_id.empty() ? nullptr : get_algorithm(algorithm_id);
    const Json params = object_field(metadata, "algorithm_parameters");
    const auto method_it = params.find("method");
    // str(params.get("method", "")) — present null behaves like any other
    // non-matching value here ("" and "None" both miss "kriging_fallback").
    const std::string method_str =
        method_it == params.end() ? "" : py_str_scalar(*method_it);
    if (method_str == "kriging_fallback") {
        return "numpy kriging fallback（不产生克里金方差面）";
    }
    if (spec != nullptr && !spec->produces_uncertainty) {
        return "方法 " + spec->display_label + " 不产生不确定度面（注册表能力声明）";
    }
    return "任务无方差记录（方法声明产方差但本次运行未产出）";
}

}  // namespace

Json FactorArtifactRef::to_json() const {
    Json out = Json::object();
    out["artifact"] = artifact;
    out["present"] = present;
    out["version_id"] = version_id;
    out["absent_reason"] = absent_reason;
    return out;
}

bool FactorProduct::is_mock() const {
    return source_kind == "mock" || source_kind == "mixed";
}

bool FactorProduct::has_uncertainty() const {
    for (const FactorArtifactRef& ref : artifacts) {
        if (ref.artifact == "uncertainty" && ref.present) return true;
    }
    return false;
}

FactorArtifactRef FactorProduct::artifact(std::string_view kind) const {
    for (const FactorArtifactRef& ref : artifacts) {
        if (ref.artifact == kind) return ref;
    }
    return FactorArtifactRef{std::string(kind), false, "",
                             "not part of this product"};
}

Json FactorProduct::to_json() const {
    Json grid_shape_json = Json::array();
    for (const long long v : grid_shape) grid_shape_json.push_back(v);
    Json inputs_json = Json::array();
    for (const std::string& v : input_version_ids) inputs_json.push_back(v);
    Json artifacts_json = Json::array();
    for (const FactorArtifactRef& ref : artifacts) {
        artifacts_json.push_back(ref.to_json());
    }
    Json out = Json::object();
    out["factor_id"] = factor_id;
    out["name"] = name;
    out["factor_type"] = factor_type;
    out["factor_family"] = factor_family;
    out["target_horizon"] = target_horizon;
    out["algorithm_id"] = algorithm_id;
    out["method_label"] = method_label;
    out["unit"] = unit;
    out["unit_declared"] = unit_declared;
    out["crs"] = crs;
    out["crs_declared"] = crs_declared;
    out["grid_shape"] = std::move(grid_shape_json);
    out["input_version_ids"] = std::move(inputs_json);
    out["grid_version_id"] = grid_version_id;
    out["run_id"] = run_id;
    out["source_kind"] = source_kind;
    out["generator_version"] = generator_version;
    out["qc"] = qc;
    out["maturity"] = maturity;
    out["freshness"] = freshness;
    out["freshness_detail"] = freshness_detail;
    out["artifacts"] = std::move(artifacts_json);
    out["constraint_pins"] = constraint_pins;
    out["created_at"] = created_at;
    return out;
}

std::string factor_family_for_type(const std::string& factor_type) {
    return factor_family_lookup(factor_type);
}

std::optional<FactorProduct> factor_product_for_task(
    const Json& tasks_array, const std::string& task_id,
    const CatalogResolver& catalog, const WorkspaceView& workspace_state,
    std::optional<FreshnessEntry> freshness_entry) {
    const Json* task = nullptr;
    if (tasks_array.is_array()) {
        for (const Json& candidate : tasks_array) {
            if (candidate.is_object() && str_field(candidate, "id") == task_id) {
                task = &candidate;
                break;
            }
        }
    }
    if (task == nullptr) return std::nullopt;

    const Json params = object_field(*task, "parameters");
    const Json metrics = object_field(*task, "quality_metrics");
    const Json metadata = object_field(*task, "grid_metadata");

    // 算法身份：任务 method 是 UI 标签或 engine id（历史两者皆有）——
    // 经注册表规范化；无法识别时诚实保留原串并标记（绝不猜）。
    const std::string method_label = str_field(*task, "method");
    std::string algorithm_id;
    try {
        algorithm_id = canonical_algorithm_id(method_label);
    } catch (...) {  // 未知方法词汇：摘要层如实显示 method_label
        algorithm_id = "";
    }

    const std::string factor_type = str_field(*task, "factor_type");

    // 单位：grid 契约 > 任务参数 > 因子默认（默认标注 unit_declared=False）。
    std::string unit;
    bool unit_declared = false;
    const Json declared_unit =
        metadata.contains("unit") ? metadata.at("unit") : Json(nullptr);
    if (truthy(declared_unit)) {
        unit = py_str_scalar(declared_unit);
        unit_declared = true;
    } else {
        const Json params_unit =
            params.contains("unit") ? params.at("unit") : Json(nullptr);
        if (truthy(params_unit)) {
            unit = py_str_scalar(params_unit);
            unit_declared = true;
        } else {
            const std::optional<std::string> family_default =
                factor_fusion::unit_for_factor(factor_type);
            if (family_default.has_value() && !family_default->empty()) {
                unit = *family_default;  // 家族默认，非本任务声明
                unit_declared = false;
            }
        }
    }

    const Json crs_json =
        metadata.contains("crs") ? metadata.at("crs") : Json(nullptr);
    const std::string crs = truthy(crs_json) ? py_str_scalar(crs_json) : "";

    // to_descriptor 的键是 width/height（评审 R1-F9：shape 键不存在）。
    const Json height =
        metadata.contains("height") ? metadata.at("height") : Json(nullptr);
    const Json width =
        metadata.contains("width") ? metadata.at("width") : Json(nullptr);
    std::vector<long long> grid_shape;
    if (is_py_int(height)) grid_shape.push_back(as_py_int(height));
    if (is_py_int(width)) grid_shape.push_back(as_py_int(width));

    const std::string grid_version_id =
        str_field(*task, "grid_artifact_version_id");
    std::string run_id;
    std::vector<std::string> input_version_ids;
    if (!grid_version_id.empty() && catalog.resolve_version) {
        std::optional<VersionRunInfo> info;
        try {
            info = catalog.resolve_version(grid_version_id);
        } catch (...) {  // 溯源缺失→空（版本字段诚实为空）
            info = std::nullopt;
        }
        if (info.has_value()) {
            run_id = info->run_id;
            if (!run_id.empty() && catalog.resolve_run) {
                std::optional<RunInfo> run;
                try {
                    run = catalog.resolve_run(run_id);
                } catch (...) {
                    run = std::nullopt;
                }
                if (run.has_value()) {
                    input_version_ids = run->input_version_ids;
                }
            }
        }
    }

    static const std::array<const char*, 11> kQcKeys{{
        "r_squared", "r2", "n_points", "backend", "mean", "range",
        "variance_min", "variance_max", "distance_policy",
        "duplicate_wells_dropped", "synthesized_fallback",
    }};
    Json qc = Json::object();
    for (const char* key : kQcKeys) {
        if (metrics.contains(key)) qc[key] = metrics.at(key);
    }

    // artifacts：grid 为载荷权威；派生件按能力诚实标注 presence。
    std::string maturity = "draft";
    if (workspace_state.maturity_of) {
        maturity = workspace_state.maturity_of("factor:" + task_id);
    }
    std::string freshness;
    std::string freshness_detail;
    if (freshness_entry.has_value()) {
        freshness = freshness_entry->status;  // enum value string, "" = 未评估
        freshness_detail = freshness_entry->detail;
    }

    const bool has_variance =
        (metrics.contains("variance_min") && !metrics.at("variance_min").is_null()) ||
        truthy(metadata.contains("has_variance_grid") ? metadata.at("has_variance_grid")
                                                     : Json(nullptr));
    const bool has_grid = !grid_version_id.empty() || truthy(metadata);
    const bool has_metadata = truthy(metadata);
    const bool has_qc = truthy(qc);
    std::vector<FactorArtifactRef> artifacts;
    artifacts.reserve(5);
    artifacts.push_back(FactorArtifactRef{
        "grid", has_grid, grid_version_id,
        has_grid ? "" : "尚无插值结果（任务未完成）"});
    artifacts.push_back(FactorArtifactRef{
        "contours", has_metadata, "",
        has_metadata ? "" : "等值线由 grid 派生（渲染期生成，无独立版本）"});
    artifacts.push_back(FactorArtifactRef{
        "polygons", false, "",
        "分类多边形由 grid 派生（按阈值请求生成，无独立版本）"});
    artifacts.push_back(FactorArtifactRef{
        "uncertainty", has_variance, "",
        has_variance ? "" : uncertainty_absent_reason(algorithm_id, metadata)});
    artifacts.push_back(FactorArtifactRef{
        "qc", has_qc, "", has_qc ? "" : "无质量指标记录"});

    Json constraint_pins = Json::array();
    if (params.contains("constraint_pins") &&
        params.at("constraint_pins").is_array()) {
        for (const Json& pin : params.at("constraint_pins")) {
            constraint_pins.push_back(pin);  // verbatim deep copy
        }
    }

    FactorProduct product;
    product.factor_id = task_id;
    product.name = str_field(*task, "name");
    product.factor_type = factor_type;
    product.factor_family = factor_family_lookup(factor_type);
    product.target_horizon = str_field(*task, "target_horizon");
    product.algorithm_id = algorithm_id;
    product.method_label = method_label;
    product.parameters = params;
    product.unit = unit;
    product.unit_declared = unit_declared;
    product.crs = crs;
    product.crs_declared = truthy(crs_json);
    product.grid_shape = std::move(grid_shape);
    product.input_version_ids = std::move(input_version_ids);
    product.grid_version_id = grid_version_id;
    product.run_id = run_id;
    product.source_kind = str_field(*task, "source_kind");
    product.generator_version = str_field(*task, "generator_version");
    product.qc = std::move(qc);
    product.maturity = std::move(maturity);
    product.freshness = std::move(freshness);
    product.freshness_detail = std::move(freshness_detail);
    product.artifacts = std::move(artifacts);
    product.constraint_pins = std::move(constraint_pins);
    product.created_at = str_field(*task, "created_at");
    return product;
}

std::vector<FactorProduct> factor_products(
    const Json& tasks_array,
    const std::map<std::string, FreshnessEntry>& freshness_by_task,
    const CatalogResolver& catalog, const WorkspaceView& workspace_state) {
    std::vector<FactorProduct> out;
    if (!tasks_array.is_array()) return out;
    for (const Json& task : tasks_array) {
        if (!task.is_object()) continue;
        const std::string task_id = str_field(task, "id");
        std::optional<FreshnessEntry> entry;
        const auto it = freshness_by_task.find(task_id);
        if (it != freshness_by_task.end()) entry = it->second;
        std::optional<FactorProduct> product = factor_product_for_task(
            tasks_array, task_id, catalog, workspace_state, entry);
        if (product.has_value()) out.push_back(std::move(*product));
    }
    return out;
}

}  // namespace pwb::workflow_interpretation
