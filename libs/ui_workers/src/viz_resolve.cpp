#include "pwb/ui_workers/viz_resolve.hpp"

#include <algorithm>
#include <cctype>
#include <filesystem>

namespace pwb::ui_workers {

namespace viz_tables {
const std::set<std::string> kWellTypes = {"well_log"};
const std::set<std::string> kWellFormats = {"las", "xml"};
const std::set<std::string> kSeismicTypes = {"seismic"};
const std::set<std::string> kSeismicFormats = {"sgy", "segy"};
const std::set<std::string> kMapTypes = {"geojson"};
const std::set<std::string> kMapFormats = {"geojson", "json"};
const std::set<std::string> kEnginePreviewTypes = {
    "horizon", "well_head", "well_stratification", "time_depth",
    "formation_tops"};
}  // namespace viz_tables

namespace {

std::string lower_strip(const std::string& value) {
    const auto first = value.find_first_not_of(" \t\r\n");
    const auto last = value.find_last_not_of(" \t\r\n");
    if (first == std::string::npos) return "";
    std::string out = value.substr(first, last - first + 1);
    std::transform(out.begin(), out.end(), out.begin(),
                   [](unsigned char c) { return std::tolower(c); });
    return out;
}

}  // namespace

std::string viz_norm_type(const std::string& value) {
    return lower_strip(value);
}

std::string viz_norm_format(const std::string& value) {
    std::string out = lower_strip(value);
    // Python .lstrip(".") — strip ALL leading dots.
    const auto pos = out.find_first_not_of('.');
    return pos == std::string::npos ? "" : out.substr(pos);
}

bool supports_resource(const ResourceSlice& resource) {
    const std::string rtype = viz_norm_type(resource.type);
    const std::string fmt = viz_norm_format(resource.format);
    using namespace viz_tables;
    if (kWellTypes.count(rtype) && kWellFormats.count(fmt)) return true;
    if (kSeismicTypes.count(rtype) && kSeismicFormats.count(fmt)) return true;
    if (kMapTypes.count(rtype) && kMapFormats.count(fmt)) return true;
    if (kEnginePreviewTypes.count(rtype)) return true;
    return false;
}

std::optional<VizRefSlice> ref_from_resource(const ResourceSlice& resource) {
    if (!supports_resource(resource)) return std::nullopt;
    const std::string rtype = viz_norm_type(resource.type);
    const std::string fmt = viz_norm_format(resource.format);
    using namespace viz_tables;
    std::string kind;
    if (kWellTypes.count(rtype) && kWellFormats.count(fmt)) {
        kind = "well_log";
    } else if (kSeismicTypes.count(rtype) && kSeismicFormats.count(fmt)) {
        kind = "seismic";
    } else if (kMapTypes.count(rtype) && kMapFormats.count(fmt)) {
        kind = "map";
    } else if (kEnginePreviewTypes.count(rtype)) {
        kind = "engine_preview";
    } else {
        return std::nullopt;
    }
    VizRefSlice ref;
    ref.kind = kind;
    ref.id = resource.id;
    ref.path = resource.path;
    ref.label = resource.name;
    ref.source = "";
    return ref;
}

const ResourceSlice* find_resource(
    const VizRefSlice& ref, const std::vector<ResourceSlice>& resources) {
    for (const auto& item : resources) {
        if (item.id == ref.id) return &item;
    }
    if (!ref.path.empty()) {
        for (const auto& item : resources) {
            if (item.path == ref.path) return &item;
        }
    }
    return nullptr;
}

VizPayloadSlice resolve_well_log(
    const VizRefSlice& ref, const std::vector<ResourceSlice>& resources,
    const std::string& project_root,
    const std::function<bool()>& is_cancelled,
    const WellLogLoadFn& load_fn) {
    const std::string label =
        !ref.label.empty() ? ref.label
                           : (!ref.id.empty() ? ref.id : ref.kind);
    const ResourceSlice* resource = find_resource(ref, resources);
    std::string path =
        (resource != nullptr && !resource->path.empty()) ? resource->path
                                                         : ref.path;
    if (!path.empty()) {
        path = absolute_resource_path(path, project_root);
    }
    std::error_code ec;
    if (path.empty() || !std::filesystem::is_regular_file(path, ec)) {
        VizPayloadSlice payload;
        payload.kind = "message";
        payload.label = label;
        payload.message = "井数据文件不存在或不可读";
        return payload;
    }
    if (!load_fn) {
        throw KernelUnavailable("engine LAS/XML preview load");
    }
    std::optional<LoadedWellLog> loaded = load_fn(path, is_cancelled);
    if (!loaded || !loaded->data.has_value()) {
        VizPayloadSlice payload;
        payload.kind = "message";
        payload.label = label;
        payload.message = "无法解析 LAS 井数据（engine load_las_preview）";
        return payload;
    }
    const std::string stem = std::filesystem::path(path).stem().string();
    // adapter.py: label or well_name or path; well_names = well_name or
    // label or stem.
    VizPayloadSlice payload;
    payload.kind = "well_log";
    payload.well_log = loaded->data;
    payload.well_logs = {loaded->data};
    payload.label = !label.empty()
                        ? label
                        : (!loaded->well_name.empty() ? loaded->well_name
                                                      : path);
    payload.well_names = {!loaded->well_name.empty()
                              ? loaded->well_name
                              : (!label.empty() ? label : stem)};
    return payload;
}

VizPayloadSlice viz_resolve(const VizRefSlice& ref,
                            const std::vector<ResourceSlice>& resources,
                            const std::string& project_root,
                            const std::function<bool()>& is_cancelled,
                            const WellLogLoadFn& load_fn) {
    const std::string label =
        !ref.label.empty() ? ref.label
                           : (!ref.id.empty() ? ref.id : ref.kind);
    try {
        if (ref.kind == "well_log") {
            return resolve_well_log(ref, resources, project_root,
                                    is_cancelled, load_fn);
        }
        // resolve() dispatches seismic/map/cross_well/engine_preview/
        // prediction to their own resolvers — those are NOT ported here;
        // "不支持的可视化类型" is only for kinds outside the resolver
        // table. An unported-but-valid kind must stay loud, not fabricate
        // the unsupported message Python would never emit for it.
        static const std::set<std::string> kResolverKinds = {
            "seismic", "map", "cross_well", "engine_preview", "prediction"};
        if (kResolverKinds.count(ref.kind)) {
            throw KernelUnavailable("viz resolver kind: " + ref.kind);
        }
        VizPayloadSlice payload;
        payload.kind = "message";
        payload.label = label;
        payload.message = "不支持的可视化类型: " + ref.kind;
        return payload;
    } catch (const WellLogLoadCancelled&) {
        throw;  // honest cancellation — never a fake message payload
    } catch (const job::JobCancelled&) {
        throw;
    } catch (const KernelUnavailable&) {
        throw;  // unbound seams stay loud — host configuration error
    } catch (const std::exception& exc) {
        // Python: f"解析失败: {exc.__class__.__name__}" — class name only.
        VizPayloadSlice payload;
        payload.kind = "message";
        payload.label = label;
        payload.message = "解析失败: " + py_error_class_name(exc);
        return payload;
    }
}

}  // namespace pwb::ui_workers
