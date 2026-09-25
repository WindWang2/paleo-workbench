#include "pwb/prediction/run_spec.hpp"

#include <algorithm>
#include <array>

namespace pwb::prediction {

namespace {

Json int_value(long long value) { return Json(value); }

bool get_bool(const Json& params, const char* key, bool fallback) {
    if (!params.is_object()) return fallback;
    const auto it = params.find(key);
    if (it == params.end() || !it->is_boolean()) return fallback;
    return it->get<bool>();
}

long long get_int(const Json& params, const char* key, long long fallback) {
    if (!params.is_object()) return fallback;
    const auto it = params.find(key);
    if (it == params.end() || !it->is_number_integer()) return fallback;
    return it->get<long long>();
}

const PredictionParamSpec* find_spec(
    const std::vector<PredictionParamSpec>& schema, const std::string& key) {
    for (const auto& spec : schema) {
        if (spec.key == key) return &spec;
    }
    return nullptr;
}

}  // namespace

std::vector<PredictionParamSpec> prediction_param_schema() {
    std::vector<PredictionParamSpec> schema;
    // Tile geometry: Tile3{64,128,128} is (inline, xline, time) — the
    // kernel's kDefaultTile. 0 keeps the package-declared tile (the
    // pipeline sentinel), which is the honest default for model packages
    // that declare their own receptive geometry.
    schema.push_back({"tile_inline", "内联块", PredictionParamSpec::Type::Int,
                      0, 1024, 0, false, "体素",
                      "内联方向分块大小；0 = 采用模型包声明值"});
    schema.push_back({"tile_xline", "交叉线块",
                      PredictionParamSpec::Type::Int, 0, 1024, 0, false,
                      "体素", "交叉线方向分块大小；0 = 采用模型包声明值"});
    schema.push_back({"tile_time", "时间块", PredictionParamSpec::Type::Int,
                      0, 1024, 0, false, "体素",
                      "时间/深度方向分块大小；0 = 采用模型包声明值"});
    schema.push_back({"overlap", "分块重叠", PredictionParamSpec::Type::Int,
                      -1, 256, -1, false, "体素",
                      "相邻分块重叠像元；-1 = 采用模型包声明值"});
    schema.push_back({"batch", "批次大小", PredictionParamSpec::Type::Int, 0,
                      64, 0, false, "块",
                      "每次推理的批次；0 = 自动（从 1 起，OOM 时减半）"});
    schema.push_back({"prefer_gpu", "优先 GPU",
                      PredictionParamSpec::Type::Bool, 0, 0, 0, false, "",
                      "可用时选择 CUDA/EPS 执行提供器（未配置时回退 CPU）"});
    schema.push_back({"keep_probmap", "保留概率体",
                      PredictionParamSpec::Type::Bool, 0, 0, 0, true, "",
                      "持久化概率体 artifact（摘要计算始终使用内存融合结果）"});
    schema.push_back({"write_outputs", "写出成果",
                      PredictionParamSpec::Type::Bool, 0, 0, 0, true, "",
                      "把 classmap/概率/掩膜写入输出目录"});
    schema.push_back({"resume", "断点续跑", PredictionParamSpec::Type::Bool,
                      0, 0, 0, true, "",
                      "复用同指纹的既有分块标记，仅计算缺失分块"});
    schema.push_back({"output_budget_mb", "输出内存预算",
                      PredictionParamSpec::Type::Int, 64, 4096,
                      kDefaultOutputBudgetBytes / (1024LL * 1024), false,
                      "MiB",
                      "classmap+概率+掩膜运行时缓冲上限（默认即内核 "
                      "kDefaultOutputBudgetBytes）"});
    schema.push_back({"seed", "随机种子", PredictionParamSpec::Type::Int, 0,
                      2147483647, 0, false, "",
                      "演示/可复现路径的种子；真实 tiled 推理是确定性的"});
    return schema;
}

Json default_prediction_params() {
    Json params = Json::object();
    for (const auto& spec : prediction_param_schema()) {
        params[spec.key] = spec.type == PredictionParamSpec::Type::Bool
                               ? Json(spec.default_bool)
                               : int_value(spec.default_int);
    }
    return params;
}

std::vector<std::string> validate_prediction_params(const Json& params) {
    std::vector<std::string> errors;
    if (!params.is_object()) {
        errors.push_back("params 必须是对象");
        return errors;
    }
    const auto schema = prediction_param_schema();
    for (auto it = params.begin(); it != params.end(); ++it) {
        const PredictionParamSpec* spec = find_spec(schema, it.key());
        if (spec == nullptr) {
            errors.push_back("未知参数: " + it.key());
            continue;
        }
        if (spec->type == PredictionParamSpec::Type::Bool) {
            if (!it.value().is_boolean()) {
                errors.push_back(spec->key + " 必须是布尔值");
            }
            continue;
        }
        if (!it.value().is_number_integer()) {
            errors.push_back(spec->key + " 必须是整数");
            continue;
        }
        const long long value = it.value().get<long long>();
        if (value < spec->min_value) {
            errors.push_back(spec->label + " 低于下限 " +
                             std::to_string(spec->min_value));
        }
        if (spec->max_value > 0 && value > spec->max_value) {
            errors.push_back(spec->label + " 超过上限 " +
                             std::to_string(spec->max_value));
        }
    }
    return errors;
}

void apply_prediction_params(const Json& params,
                             PredictionPipelineOptions& options) {
    options.tile = Tile3{
        static_cast<int>(get_int(params, "tile_inline", 0)),
        static_cast<int>(get_int(params, "tile_xline", 0)),
        static_cast<int>(get_int(params, "tile_time", 0))};
    options.overlap = static_cast<int>(get_int(params, "overlap", -1));
    options.batch = static_cast<int>(get_int(params, "batch", 0));
    options.prefer_gpu = get_bool(params, "prefer_gpu", false);
    options.keep_probmap = get_bool(params, "keep_probmap", true);
    options.write_outputs = get_bool(params, "write_outputs", true);
    options.resume = get_bool(params, "resume", true);
    constexpr long long kBytesPerMiB = 1024LL * 1024;
    options.output_budget_bytes =
        get_int(params, "output_budget_mb", 2048) * kBytesPerMiB;
}

Json PredictionRunSpec::to_json() const {
    Json value = Json::object();
    value["schema_version"] = kRunSpecSchemaVersion;
    Json wells = Json::array();
    for (const auto& id : well_resource_ids) wells.push_back(id);
    value["well_resource_ids"] = std::move(wells);
    value["seismic_resource_id"] =
        seismic_resource_id.has_value() ? Json(*seismic_resource_id)
                                        : Json(nullptr);
    value["model_version_id"] = model_version_id;
    value["params"] = params.is_object() ? params : Json::object();
    value["workflow"] = workflow;
    value["name_prefix"] = name_prefix;
    value["demo"] = demo;
    value["resolved"] = resolved.is_object() ? resolved : Json::object();
    return value;
}

std::optional<PredictionRunSpec> PredictionRunSpec::from_json(
    const Json& value, std::vector<std::string>& errors, bool require_model) {
    errors.clear();
    if (!value.is_object()) {
        errors.push_back("RunSpec 必须是对象");
        return std::nullopt;
    }
    // Params live nested under "params" — a param key at the TOP level is
    // an unknown key, never accepted by shape.
    static const std::array<std::string, 9> kKeys = {
        "schema_version", "well_resource_ids", "seismic_resource_id",
        "model_version_id", "params", "workflow", "name_prefix", "demo",
        "resolved"};
    for (auto it = value.begin(); it != value.end(); ++it) {
        if (std::find(kKeys.begin(), kKeys.end(), it.key()) == kKeys.end()) {
            errors.push_back("未知 RunSpec 键: " + it.key());
        }
    }
    PredictionRunSpec spec;
    if (const auto it = value.find("schema_version");
        it != value.end() && it->is_number_integer()) {
        const int version = it->get<int>();
        if (version != kRunSpecSchemaVersion) {
            errors.push_back("不支持的 RunSpec 版本: " + std::to_string(version));
        }
    } else {
        errors.push_back("缺少 schema_version");
    }
    if (const auto it = value.find("well_resource_ids");
        it != value.end() && it->is_array()) {
        for (const auto& id : *it) {
            if (id.is_string() && !id.get<std::string>().empty()) {
                spec.well_resource_ids.push_back(id.get<std::string>());
            } else if (!id.is_string()) {
                errors.push_back("well_resource_ids 含非字符串元素");
            }
        }
    }
    if (const auto it = value.find("seismic_resource_id"); it != value.end()) {
        if (it->is_string() && !it->get<std::string>().empty()) {
            spec.seismic_resource_id = it->get<std::string>();
        } else if (!it->is_null()) {
            errors.push_back("seismic_resource_id 必须是字符串或 null");
        }
    }
    if (const auto it = value.find("model_version_id");
        it != value.end() && it->is_string()) {
        spec.model_version_id = it->get<std::string>();
    }
    if (spec.model_version_id.empty() && require_model) {
        errors.push_back("未选择模型版本（model_version_id）");
    }
    if (const auto it = value.find("params"); it != value.end()) {
        if (it->is_object()) {
            for (const std::string& problem : validate_prediction_params(*it)) {
                errors.push_back(problem);
            }
            spec.params = *it;
        } else {
            errors.push_back("params 必须是对象");
        }
    }
    for (const auto& [key, target] :
         std::array<std::pair<const char*, std::string*>, 2>{
             {{"workflow", &spec.workflow}, {"name_prefix", &spec.name_prefix}}}) {
        if (const auto it = value.find(key); it != value.end()) {
            if (it->is_string()) {
                *target = it->get<std::string>();
            } else {
                errors.push_back(std::string(key) + " 必须是字符串");
            }
        }
    }
    if (const auto it = value.find("demo"); it != value.end()) {
        if (it->is_boolean()) {
            spec.demo = it->get<bool>();
        } else {
            errors.push_back("demo 必须是布尔值");
        }
    }
    if (const auto it = value.find("resolved");
        it != value.end() && it->is_object()) {
        spec.resolved = *it;
    }
    if (!errors.empty()) return std::nullopt;
    return spec;
}

bool operator==(const PredictionRunSpec& a, const PredictionRunSpec& b) {
    return a.well_resource_ids == b.well_resource_ids &&
           a.seismic_resource_id == b.seismic_resource_id &&
           a.model_version_id == b.model_version_id && a.params == b.params &&
           a.workflow == b.workflow && a.name_prefix == b.name_prefix &&
           a.demo == b.demo && a.resolved == b.resolved;
}

bool operator!=(const PredictionRunSpec& a, const PredictionRunSpec& b) {
    return !(a == b);
}

}  // namespace pwb::prediction
