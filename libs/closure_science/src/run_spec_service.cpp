#include "pwb/closure_science/run_spec_service.hpp"

#include <pwb/catalog/models.hpp>
#include <pwb/prediction/model_package_runtime.hpp>
#include <pwb/prediction/onnx_session.hpp>

#include <algorithm>
#include <deque>
#include <filesystem>
#include <mutex>
#include <set>
#include <utility>

namespace pwb::closure_science {

namespace {

using catalog::CatalogDocument;
using catalog::DataVersion;

std::vector<std::string> string_list(const Json& value) {
    std::vector<std::string> out;
    if (value.is_array()) {
        for (const auto& item : value) {
            if (item.is_string()) out.push_back(item.get<std::string>());
        }
    }
    return out;
}

// The model's required curves per the input_contract vocabulary
// (required_curves / curves). Empty when the model declares none.
std::vector<std::string> required_curves_of(const catalog::ModelVersion& mv) {
    if (mv.input_schema.contains("required_curves")) {
        return string_list(mv.input_schema["required_curves"]);
    }
    if (mv.input_schema.contains("curves")) {
        return string_list(mv.input_schema["curves"]);
    }
    return {};
}

// Curve mnemonics a well-log version declares, when it declares any
// (metadata.curves / metadata.data_headers). An absent declaration is NOT
// "no curves" — it is unverifiable and reported as such (no false missing).
std::vector<std::string> declared_curves_of(const DataVersion& version) {
    for (const char* key : {"curves", "data_headers", "mnemonics"}) {
        if (version.metadata.contains(key)) {
            return string_list(version.metadata[key]);
        }
    }
    return {};
}

const DataVersion* current_version_of(const CatalogDocument& document,
                                      const ResourceRef& resource,
                                      int* live_version_count) {
    const std::optional<std::string> version_id =
        resolve_resource_version_id(document, resource);
    if (live_version_count != nullptr) {
        *live_version_count = 0;
        for (const auto& asset : document.assets) {
            if (asset.trashed) continue;
            if (asset.id.str() != resource.id &&
                !(asset.legacy_resource_id.has_value() &&
                  *asset.legacy_resource_id == resource.id) &&
                asset.id.str() != resource.catalog_asset_id) {
                continue;
            }
            for (const auto& vid : document.versions) {
                if (vid.asset_id == asset.id && !vid.trashed) {
                    ++*live_version_count;
                }
            }
        }
    }
    if (!version_id.has_value()) return nullptr;
    const DataVersion* version =
        document.find_version(domain::VersionId(*version_id));
    if (version == nullptr || version->trashed) return nullptr;
    return version;
}

std::string tile_text(const std::vector<int>& tile) {
    if (tile.size() != 3) return std::string();
    return std::to_string(tile[0]) + "x" + std::to_string(tile[1]) + "x" +
           std::to_string(tile[2]);
}

}  // namespace

std::vector<WellCandidate> list_well_candidates(
    const CatalogDocument& document, const std::vector<ResourceRef>& resources,
    const std::optional<std::string>& model_version_id) {
    std::vector<std::string> required_curves;
    if (model_version_id.has_value()) {
        if (const catalog::ModelVersion* mv =
                document.find_model_version_by_id(*model_version_id);
            mv != nullptr) {
            required_curves = required_curves_of(*mv);
        }
    }
    std::vector<WellCandidate> wells;
    for (const ResourceRef& resource : resources) {
        if (resource.type != "well_log") continue;
        WellCandidate well;
        well.resource_id = resource.id;
        well.name = resource.path.empty()
                        ? resource.id
                        : std::filesystem::path(resource.path)
                              .filename()
                              .string();
        well.path = resource.path;
        int live_versions = 0;
        const DataVersion* version =
            current_version_of(document, resource, &live_versions);
        well.version_count = live_versions;
        if (version != nullptr) {
            well.version_id = version->id.str();
            well.curves = declared_curves_of(*version);
            // Missing = DECLARED curve set that lacks a required mnemonic.
            // Unverifiable metadata never fabricates a missing curve.
            if (!required_curves.empty() && !well.curves.empty()) {
                std::set<std::string> have(well.curves.begin(),
                                           well.curves.end());
                for (const std::string& curve : required_curves) {
                    if (have.count(curve) == 0u) {
                        well.missing_required_curves.push_back(curve);
                    }
                }
            }
        } else {
            bool trashed = false;
            for (const auto& asset : document.assets) {
                const bool bound =
                    asset.id.str() == resource.id ||
                    asset.id.str() == resource.catalog_asset_id ||
                    (asset.legacy_resource_id.has_value() &&
                     *asset.legacy_resource_id == resource.id);
                if (bound) trashed = trashed || asset.trashed;
            }
            well.availability =
                trashed          ? "trashed_asset"
                : live_versions > 0 ? "no_current_version"
                                    : "unmanaged";
        }
        wells.push_back(std::move(well));
    }
    std::sort(wells.begin(), wells.end(),
              [](const WellCandidate& a, const WellCandidate& b) {
                  return a.name < b.name;
              });
    return wells;
}

std::vector<ModelCandidate> list_model_candidates(
    const CatalogDocument& document) {
    std::vector<ModelCandidate> models;
    for (const catalog::ModelVersion& mv : document.model_versions) {
        const catalog::Model* model = document.find_model(mv.model_id);
        if (model == nullptr) continue;
        ModelCandidate candidate;
        candidate.model_version_id = mv.id;
        candidate.model_id = mv.model_id;
        candidate.model_version = mv.model_version;
        candidate.name = model->model_name.empty() ? mv.model_id
                                                   : model->model_name;
        candidate.provider = model->provider;
        candidate.runtime = mv.runtime;
        candidate.status = model->status;
        candidate.checksum = mv.checksum;
        candidate.artifact_uri = mv.artifact_uri;
        candidate.demo_only = mv.demo_only;
        candidate.input_schema = mv.input_schema;
        if (model->provider == "tiled_onnx") {
            candidate.executor_available =
                pwb::prediction::onnx_runtime_available();
            candidate.executor_note =
                candidate.executor_available
                    ? std::string()
                    : std::string("未找到可加载的 libonnxruntime（可配置 "
                                  "PALEO_ONNXRUNTIME_LIBRARY）");
        } else if (model->provider == "demo") {
            candidate.executor_available = true;
        } else {
            // local_asset / geoviz_online / future providers: no native
            // executor registered — visible but never runnable from here.
            candidate.executor_available = false;
            candidate.executor_note =
                "该 provider 在原生运行时没有执行器（未知执行器会被显式拒绝）";
        }
        models.push_back(std::move(candidate));
    }
    std::sort(models.begin(), models.end(),
              [](const ModelCandidate& a, const ModelCandidate& b) {
                  if (a.model_id != b.model_id) return a.model_id < b.model_id;
                  return a.model_version < b.model_version;
              });
    return models;
}

ModelPackageSummary inspect_model_package(
    const std::string& manifest_or_artifact_uri) {
    ModelPackageSummary summary;
    if (manifest_or_artifact_uri.empty()) {
        summary.error = "模型版本未登记 artifact（manifest.json 路径）";
        return summary;
    }
    std::filesystem::path manifest_path(manifest_or_artifact_uri);
    // A package registers its manifest; tolerate an artifact-path slip by
    // resolving the sibling manifest (register_package_model does the same
    // when handed the package directory).
    if (manifest_path.filename() != "manifest.json") {
        std::error_code ec;
        const std::filesystem::path sibling =
            manifest_path.parent_path() / "manifest.json";
        if (std::filesystem::exists(sibling, ec)) manifest_path = sibling;
    }
    // The artifact digest dominates the cost (whole-file sha256). Selection
    // and preflight both inspect; an UNCHANGED package (every file's size +
    // mtime) within this process must not re-hash — the cache never
    // bypasses identity: any file change changes the key.
    struct CacheEntry {
        std::string key;
        ModelPackageSummary summary;
    };
    static std::mutex cache_mutex;
    static std::deque<CacheEntry> cache;
    const auto stat_of = [](const std::filesystem::path& path) {
        std::error_code ec;
        const auto time = std::filesystem::last_write_time(path, ec);
        const auto size = std::filesystem::file_size(path, ec);
        return std::to_string(time.time_since_epoch().count()) + ":" +
               std::to_string(ec ? 0 : static_cast<long long>(size));
    };
    std::string dir_stats;
    std::error_code iter_ec;
    for (const auto& entry :
         std::filesystem::directory_iterator(
             manifest_path.parent_path(), iter_ec)) {
        if (entry.is_regular_file(iter_ec)) {
            dir_stats += "|" + entry.path().filename().string() + "=" +
                         stat_of(entry.path());
        }
    }
    const std::string key =
        manifest_path.string() + dir_stats;
    {
        const std::lock_guard<std::mutex> lock(cache_mutex);
        for (const auto& entry : cache) {
            if (entry.key == key) return entry.summary;
        }
    }
    try {
        const pwb::prediction::LoadedModelPackage package =
            pwb::prediction::load_model_package(manifest_path.string());
        summary.ok = true;
        summary.model_id = package.manifest.model_id;
        summary.model_version = package.manifest.model_version;
        summary.checksum = package.artifact_sha256;
        summary.model_file = package.manifest.artifact;
        summary.expected_inputs = package.prediction.input_bands;
        summary.class_names = package.prediction.class_names;
        summary.preprocessing_version = package.manifest.preprocessing_version;
        summary.declared_tile = tile_text(package.prediction.tile);
    } catch (const std::exception& exc) {
        summary.ok = false;
        summary.error = exc.what();
    }
    {
        const std::lock_guard<std::mutex> lock(cache_mutex);
        constexpr std::size_t kCacheLimit = 32;
        if (cache.size() >= kCacheLimit) cache.pop_front();
        cache.push_back({key, summary});
    }
    return summary;
}

PreflightReport preflight_run(const CatalogDocument& document,
                              const std::vector<ResourceRef>& resources,
                              const pwb::prediction::PredictionRunSpec& spec,
                              const std::filesystem::path& project_dir) {
    PreflightReport report;
    report.spec = spec;

    // 1) Parameter contract — invalid params never reach a worker.
    for (const std::string& problem :
         pwb::prediction::validate_prediction_params(spec.params)) {
        report.errors.push_back("参数无效: " + problem);
    }

    // 2) Model resolution + identity.
    if (spec.model_version_id.empty()) {
        report.errors.push_back("未选择模型版本");
        return report;
    }
    const catalog::ModelVersion* mv =
        document.find_model_version_by_id(spec.model_version_id);
    if (mv == nullptr) {
        report.errors.push_back("模型版本不存在或已删除: " +
                                spec.model_version_id);
        return report;
    }
    const catalog::Model* model = document.find_model(mv->model_id);
    if (model == nullptr) {
        report.errors.push_back("模型登记不完整（缺少 Model 行）: " +
                                mv->model_id);
        return report;
    }
    Json model_identity = Json::object();
    model_identity["model_id"] = mv->model_id;
    model_identity["model_version"] = mv->model_version;
    model_identity["model_version_id"] = mv->id;
    model_identity["provider"] = model->provider;
    model_identity["runtime"] = mv->runtime;
    model_identity["status"] = model->status;
    model_identity["artifact_uri"] = mv->artifact_uri;
    model_identity["checksum"] =
        mv->checksum.has_value() ? Json(*mv->checksum) : Json("");
    model_identity["model_name"] = model->model_name;

    // 3) Executor availability (honest — an unexecutable provider is a
    // preflight failure, not a run-time surprise).
    if (model->provider == "tiled_onnx") {
        if (!pwb::prediction::onnx_runtime_available()) {
            report.errors.push_back(
                "ONNX Runtime 执行器不可用（未找到可加载的 libonnxruntime，"
                "请配置 PALEO_ONNXRUNTIME_LIBRARY）");
        }
        // Package validation = the same load the run performs (checksum +
        // path containment); a mismatched/absent package stops here.
        const ModelPackageSummary package =
            inspect_model_package(mv->artifact_uri);
        if (!package.ok) {
            report.errors.push_back("模型包校验失败: " + package.error);
        } else {
            if (mv->checksum.has_value() && !mv->checksum->empty()) {
                if (*mv->checksum != package.checksum) {
                    report.errors.push_back(
                        "模型文件校验和不一致（登记 " + *mv->checksum +
                        "，实际 " + package.checksum + "）——模型文件已变更");
                }
            } else {
                report.warnings.push_back(
                    "模型版本未登记校验和——模型文件被替换将无法检测");
            }
            model_identity["artifact_checksum"] = package.checksum;
            model_identity["expected_inputs"] = package.expected_inputs;
            model_identity["class_names"] = package.class_names;
        }
    } else if (model->provider == "demo") {
        // The deterministic synthetic — always executable.
    } else {
        report.errors.push_back("模型 provider 无原生执行器: " +
                                model->provider);
    }

    // 4) Seismic input resolution (the tiled kernel's input).
    if (spec.seismic_resource_id.has_value()) {
        const ResourceRef* seismic = nullptr;
        for (const ResourceRef& resource : resources) {
            if (resource.id == *spec.seismic_resource_id) {
                seismic = &resource;
                break;
            }
        }
        if (seismic == nullptr) {
            report.errors.push_back("所选地震资源不在工程中: " +
                                    *spec.seismic_resource_id);
        } else {
            const std::optional<std::string> version_id =
                resolve_resource_version_id(document, *seismic);
            if (!version_id.has_value()) {
                report.errors.push_back(
                    "所选地震体尚未纳管为可用版本，无法运行预测");
            } else {
                const DataVersion* version =
                    document.find_version(domain::VersionId(*version_id));
                if (version == nullptr || version->trashed) {
                    report.errors.push_back("所选地震体版本不可用（已删除）");
                } else {
                    // The cheap subset of the run's own input contract
                    // (prediction_input validate): grid_descriptor shape,
                    // crs, dtype — plus the payload file actually being
                    // where the run will read it.
                    const Json* grid = nullptr;
                    if (version->metadata.contains("grid_descriptor") &&
                        version->metadata["grid_descriptor"].is_object()) {
                        grid = &version->metadata["grid_descriptor"];
                    }
                    if (grid == nullptr) {
                        report.errors.push_back(
                            "地震输入版本缺少 grid_descriptor（shape/dtype/CRS/"
                            "geotransform 是 tiled 推理的必需声明）");
                    } else {
                        bool shape_ok = false;
                        long long voxels = 0;
                        if (grid->contains("shape") &&
                            (*grid)["shape"].is_array() &&
                            (*grid)["shape"].size() == 3) {
                            shape_ok = true;
                            for (const auto& dim : (*grid)["shape"]) {
                                if (!dim.is_number_integer() ||
                                    dim.get<long long>() <= 0) {
                                    shape_ok = false;
                                    break;
                                }
                                if (voxels == 0) {
                                    voxels = dim.get<long long>();
                                } else {
                                    voxels *= dim.get<long long>();
                                }
                            }
                        }
                        if (!shape_ok) {
                            report.errors.push_back(
                                "地震输入的 shape 必须是三个正整数（inline/"
                                "xline/time）");
                        }
                        const std::string dtype =
                            grid->contains("dtype") &&
                                    (*grid)["dtype"].is_string()
                                ? (*grid)["dtype"].get<std::string>()
                                : std::string();
                        if (dtype != "float32") {
                            report.errors.push_back(
                                "地震输入 dtype 必须是 float32（当前: " +
                                (dtype.empty() ? std::string("未声明") : dtype) +
                                "）");
                        }
                        const std::string crs =
                            grid->contains("crs") &&
                                    (*grid)["crs"].is_string()
                                ? (*grid)["crs"].get<std::string>()
                                : std::string();
                        if (crs.empty()) {
                            report.errors.push_back(
                                "地震输入未声明 CRS（tiled 推理按契约拒绝）");
                        }
                        // Payload file check (absolute or project-anchored).
                        if (shape_ok && dtype == "float32" &&
                            !version->path.empty() && !project_dir.empty()) {
                            std::filesystem::path payload(version->path);
                            if (payload.is_relative()) {
                                payload = project_dir / payload;
                            }
                            std::error_code ec;
                            if (!std::filesystem::exists(payload, ec)) {
                                report.errors.push_back(
                                    "地震体载荷文件不存在: " +
                                    payload.generic_string());
                            } else if (const auto size =
                                           std::filesystem::file_size(payload,
                                                                      ec);
                                       !ec && shape_ok && voxels > 0 &&
                                       size !=
                                           static_cast<std::uintmax_t>(
                                               voxels * 4)) {
                                report.errors.push_back(
                                    "地震体载荷大小与 shape×float32 不一致（"
                                    "文件 " +
                                    std::to_string(size) + " 字节，声明 " +
                                    std::to_string(voxels * 4) + " 字节）");
                            }
                        }
                        if (report.errors.empty()) {
                            model_identity["seismic_version_id"] = *version_id;
                        }
                    }
                }
            }
        }
    } else if (model->provider == "tiled_onnx") {
        report.errors.push_back(
            "tiled 推理需要选择一个地震体作为输入（predict.select_seismic）");
    }

    // 5) Well selection — provenance identity + per-well availability. A
    // well without a usable version is an error (fail closed), not a
    // silent skip: the spec says these wells participate in the run.
    Json well_versions = Json::array();
    for (const std::string& well_id : spec.well_resource_ids) {
        const ResourceRef* well = nullptr;
        for (const ResourceRef& resource : resources) {
            if (resource.id == well_id) {
                well = &resource;
                break;
            }
        }
        if (well == nullptr) {
            report.errors.push_back("所选井不在工程资源中: " + well_id);
            continue;
        }
        const std::optional<std::string> version_id =
            resolve_resource_version_id(document, *well);
        if (!version_id.has_value()) {
            report.errors.push_back("井 " + well_id +
                                    " 没有可用的纳管版本（无法参与预测）");
            continue;
        }
        well_versions.push_back(*version_id);
    }
    model_identity["well_version_ids"] = well_versions;

    // 6) Input contract — exactly what the run would resolve (min_wells,
    // required types, scoped resolution). Catches contract gaps pre-run.
    if (report.errors.empty()) {
        auto resolved = resolve_model_inputs(
            document, resources, spec.model_version_id,
            spec.seismic_resource_id);
        if (!resolved.is_ok()) {
            report.errors.push_back("输入不满足模型契约: " +
                                    resolved.error().message);
        } else {
            model_identity["input_version_ids"] = resolved.value();
        }
    }

    if (!report.errors.empty()) return report;
    report.input_version_ids =
        model_identity["input_version_ids"]
            .get<std::vector<std::string>>();

    // 7) Fill the resolved block (provenance payload recorded verbatim).
    Json resolved = Json::object();
    resolved["model"] = model_identity;
    resolved["run_spec_schema_version"] =
        pwb::prediction::kRunSpecSchemaVersion;
    resolved["generator"] = std::string(kInferenceGenerator);
    resolved["workflow"] = spec.workflow;
    if (mv->status == "demo" || mv->demo_only) {
        report.warnings.push_back("所选模型为演示模型，输出不得作为生产成果");
    }
    report.spec.resolved = std::move(resolved);
    report.ok = true;
    return report;
}

Json run_parameters_from_spec(
    const pwb::prediction::PredictionRunSpec& spec) {
    Json parameters = Json::object();
    parameters["workflow"] = spec.workflow;
    parameters["name_prefix"] = spec.name_prefix;
    parameters["demo"] = spec.demo;
    Json wells = Json::array();
    for (const auto& id : spec.well_resource_ids) wells.push_back(id);
    parameters["well_log_resource_ids"] = std::move(wells);
    parameters["seismic_resource_ids"] =
        spec.seismic_resource_id.has_value()
            ? Json::array({*spec.seismic_resource_id})
            : Json::array();
    if (spec.params.is_object() && spec.params.contains("seed") &&
        spec.params["seed"].is_number_integer()) {
        parameters["seed"] = spec.params["seed"];
    }
    if (spec.params.is_object() && spec.params.contains("prefer_gpu") &&
        spec.params["prefer_gpu"].is_boolean()) {
        parameters["prefer_gpu"] = spec.params["prefer_gpu"];
    }
    // The verbatim spec — UI, runner and provenance share ONE contract.
    parameters["_run_spec"] = spec.to_json();
    return parameters;
}

}  // namespace pwb::closure_science
