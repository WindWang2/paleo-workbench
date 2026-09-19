#include <pwb/ui_seqviz/viz_page_state.hpp>

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <utility>

#include <pwb/ui_data_core/json_util.hpp>
#include <pwb/ui_data_core/preview_types.hpp>

namespace pwb::ui_seqviz {

namespace {

namespace fs = std::filesystem;

// pipeline/assets.py SEISMIC_KEY.
constexpr const char* kSeismicKey = "seismic_resource_ids";

std::vector<ui_workers::ResourceSlice> to_slices(
    const std::vector<ResourceItem>& resources) {
    std::vector<ui_workers::ResourceSlice> out;
    out.reserve(resources.size());
    for (const auto& resource : resources) {
        out.push_back(resource_slice(resource));
    }
    return out;
}

const ResourceItem* find_item(const VizRefSlice& ref,
                              const std::vector<ResourceItem>& resources) {
    for (const auto& item : resources) {
        if (item.id == ref.id) {
            return &item;
        }
    }
    if (!ref.path.empty()) {
        for (const auto& item : resources) {
            if (item.path == ref.path) {
                return &item;
            }
        }
    }
    return nullptr;
}

bool is_file(const std::string& path) {
    std::error_code ec;
    return fs::is_regular_file(fs::path(path), ec);
}

std::string abs_path(const std::string& path,
                     const VizPageProjectSlice& project) {
    return path.empty() ? std::string{}
                        : ui_workers::absolute_resource_path(
                              path, project.project_root);
}

UiVizPayload message_payload(std::string label, std::string message) {
    UiVizPayload payload;
    payload.kind = "message";
    payload.label = std::move(label);
    payload.message = std::move(message);
    return payload;
}

bool json_list_truthy(const domain::Json& list) {
    return list.is_array() && !list.empty();
}

std::string path_suffix(const std::string& path) {
    std::string ext = fs::path(path).extension().string();
    while (!ext.empty() && ext.front() == '.') {
        ext.erase(ext.begin());
    }
    return ext;
}

}  // namespace

// ---------------------------------------------------------------------------
// Payload conversion
// ---------------------------------------------------------------------------

UiVizPayload payload_from_slice(const ui_workers::VizPayloadSlice& slice) {
    UiVizPayload payload;
    payload.kind = slice.kind;
    payload.label = slice.label;
    payload.message = slice.message;
    payload.warning = slice.warning;
    payload.well_log = slice.well_log;
    payload.well_logs = slice.well_logs;
    payload.well_names = slice.well_names;
    payload.seismic_path = slice.seismic_path;
    return payload;
}

// ---------------------------------------------------------------------------
// Adapter refs / lookups
// ---------------------------------------------------------------------------

VizRefSlice ref_from_map_document(const MapDocSlice& doc) {
    VizRefSlice ref;
    ref.kind = "map";
    ref.id = doc.id;
    ref.label = doc.name;
    return ref;
}

VizRefSlice ref_from_prediction(const PredictionTaskSlice& task) {
    VizRefSlice ref;
    ref.kind = "prediction";
    ref.id = task.id;
    ref.label = task.name;
    ref.source = "prediction";
    return ref;
}

const MapDocSlice* find_map_document(
    const VizRefSlice& ref, const std::vector<MapDocSlice>& docs) {
    for (const auto& doc : docs) {
        if (doc.id == ref.id) {
            return &doc;
        }
    }
    if (!ref.label.empty()) {
        for (const auto& doc : docs) {
            if (doc.name == ref.label) {
                return &doc;
            }
        }
    }
    return nullptr;
}

const PredictionTaskSlice* find_prediction(
    const VizRefSlice& ref, const std::vector<PredictionTaskSlice>& tasks) {
    for (const auto& task : tasks) {
        if (task.id == ref.id) {
            return &task;
        }
    }
    return nullptr;
}

std::optional<ResourceItem> engine_preview_resource(
    const VizRefSlice& ref, const VizPageProjectSlice& project) {
    const ResourceItem* resource = find_item(ref, project.resources);
    if (resource == nullptr) {
        return std::nullopt;
    }
    ResourceItem copy = *resource;  // model_copy(update=...) parity
    const std::string raw_path =
        !copy.path.empty() ? copy.path : ref.path;
    copy.path = abs_path(raw_path, project);
    if (copy.type == "formation_tops") {
        copy.type = "well_stratification";
    }
    return copy;
}

UiVizPayload payload_from_engine_preview_result(
    const VizRefSlice& ref, const ui_data_core::PreviewResult& result) {
    const std::string label = !ref.label.empty()     ? ref.label
                              : !result.title.empty() ? result.title
                              : !ref.id.empty()       ? ref.id
                                                      : ref.kind;
    if (result.engine_preview == nullptr) {
        const std::string message = !result.message.empty()  ? result.message
                                    : !result.warning.empty() ? result.warning
                                                              : "未能生成引擎预览";
        return message_payload(label, message);
    }
    UiVizPayload payload;
    payload.kind = "engine_preview";
    payload.label = label;
    payload.prepared = result.engine_preview;
    payload.warning = result.warning;
    return payload;
}

// ---------------------------------------------------------------------------
// resolve()
// ---------------------------------------------------------------------------

namespace {

UiVizPayload resolve_seismic(const VizRefSlice& ref,
                             const VizPageProjectSlice& project,
                             const std::string& label) {
    const ResourceItem* resource = find_item(ref, project.resources);
    const std::string raw =
        (resource != nullptr && !resource->path.empty()) ? resource->path
                                                         : ref.path;
    const std::string path = abs_path(raw, project);
    if (path.empty() || !is_file(path)) {
        return message_payload(label, "地震数据文件不存在或不可读");
    }
    // Do not parse SEGY here — the engine view owns budgeted background
    // preparation (adapter.py verbatim comment).
    UiVizPayload payload;
    payload.kind = "seismic";
    payload.label = label;
    payload.seismic_path = path;
    payload.warning = "SEGY 将在后台按体素预算加载";
    return payload;
}

UiVizPayload resolve_map(const VizRefSlice& ref,
                         const VizPageProjectSlice& project,
                         const VizPageResolveSeams& seams,
                         const std::string& label) {
    const MapDocSlice* doc = find_map_document(ref, project.map_documents);
    domain::Json features = domain::Json::array();
    domain::Json wells = domain::Json::array();
    std::string period;
    std::string warning;
    if (doc != nullptr) {
        if (!seams.map_doc_load_fn) {
            throw ui_workers::KernelUnavailable(
                "load_map_payload_from_document seam");
        }
        std::tie(features, wells, period) = seams.map_doc_load_fn(doc->raw);
    } else if (!ref.path.empty()) {
        const std::string path = abs_path(ref.path, project);
        if (path.empty() || !is_file(path)) {
            return message_payload(label, "相图文件不存在或不可读");
        }
        if (!seams.geojson_load_fn) {
            throw ui_workers::KernelUnavailable(
                "facies-group/geojson map load seam");
        }
        std::tie(features, wells, period, warning) = seams.geojson_load_fn(
            find_item(ref, project.resources), path, project);
    } else {
        return message_payload(label, "未找到对应的古地理图文档");
    }
    UiVizPayload payload;
    payload.kind = "map";
    payload.label = !label.empty()      ? label
                    : doc != nullptr    ? doc->name
                                        : std::string{};
    payload.map_features = features.is_array() ? features
                                               : domain::Json::array();
    payload.map_wells = wells.is_array() ? wells : domain::Json::array();
    payload.period_name = period;
    if (!json_list_truthy(payload.map_features) &&
        !json_list_truthy(payload.map_wells)) {
        payload.message = "地图文档无可用几何";
        payload.warning = "无相多边形或井位可显示";
    } else {
        payload.warning = warning;
    }
    return payload;
}

UiVizPayload resolve_cross_well(const VizRefSlice& ref,
                                const VizPageProjectSlice& project,
                                const VizPageResolveSeams& seams,
                                const std::string& label) {
    std::vector<std::string> ids = ref.related_ids;
    if (!ref.id.empty() &&
        std::find(ids.begin(), ids.end(), ref.id) == ids.end()) {
        ids.insert(ids.begin(), ref.id);
    }
    std::map<std::string, const ResourceItem*> by_id;
    for (const auto& resource : project.resources) {
        by_id[resource.id] = &resource;
    }
    std::vector<std::any> logs;
    std::vector<std::string> names;
    const auto load_for = [&seams](const ResourceItem* res,
                                   const std::string& fallback_name,
                                   std::vector<std::any>& out_logs,
                                   std::vector<std::string>& out_names) {
        if (res == nullptr || res->path.empty() || !seams.load_fn) {
            return;
        }
        // Python calls load_well_log_from_path(path) — no cancel token on
        // this branch (adapter.py verbatim).
        auto loaded = seams.load_fn(res->path, {});
        if (!loaded.has_value()) {
            return;
        }
        out_logs.push_back(std::move(loaded->data));
        const std::string name = !res->name.empty()         ? res->name
                                 : !loaded->well_name.empty() ? loaded->well_name
                                                              : fallback_name;
        out_names.push_back(name);
    };
    for (const auto& rid : ids) {
        const auto it = by_id.find(rid);
        load_for(it != by_id.end() ? it->second : nullptr, rid, logs, names);
    }
    if (logs.empty()) {
        for (const auto& resource : project.resources) {
            if (ui_workers::viz_norm_type(resource.type) != "well_log") {
                continue;
            }
            load_for(&resource, resource.path, logs, names);
            if (logs.size() >= 8) {
                break;
            }
        }
    }
    if (logs.empty()) {
        return message_payload(label, "无可用测井数据构建连井");
    }
    UiVizPayload payload;
    payload.kind = "cross_well";
    payload.label = label;
    payload.well_log = logs.front();
    payload.well_logs = std::move(logs);
    payload.well_names = std::move(names);
    return payload;
}

UiVizPayload resolve_engine_preview(const VizRefSlice& ref,
                                    const VizPageProjectSlice& project,
                                    const VizPageResolveSeams& seams,
                                    const std::string& label) {
    const ResourceItem* resource = find_item(ref, project.resources);
    const std::string raw =
        (resource != nullptr && !resource->path.empty()) ? resource->path
                                                         : ref.path;
    const std::string path = abs_path(raw, project);
    if (path.empty() || !is_file(path)) {
        return message_payload(label, "预览文件不存在或不可读");
    }
    if (seams.engine == nullptr) {
        // Python's `from geoviz import GeoVizEngine` ImportError branch.
        return message_payload(label, "geo-viz-engine 不可用");
    }
    std::string rtype = resource != nullptr ? resource->type : "";
    if (rtype == "formation_tops") {
        rtype = "well_stratification";
    }
    const std::string fmt =
        resource != nullptr && !resource->format.empty()
            ? resource->format
            : path_suffix(path);
    PreviewRequestData request;
    if (resource != nullptr) {
        request = request_from_resource(
            *resource, path,
            !rtype.empty() ? rtype : "unknown", label,
            project.comparison_crs);
    } else {
        request.resource_id = !ref.id.empty() ? ref.id : "viz";
        request.path = path;
        request.semantic_type = !rtype.empty() ? rtype : "unknown";
        request.format = fmt;
        request.label = label;
    }
    if (!seams.engine->supports(request)) {
        return message_payload(label, "引擎不支持此资源类型: " + rtype + "/" +
                                          fmt);
    }
    PreparedPreviewData prepared;
    try {
        // PreviewOptions.local() parity — defaults from active settings.
        prepared = seams.engine->prepare(request, GeovizPreviewOptions{});
    } catch (const std::exception& exc) {
        return message_payload(
            label, "引擎 prepare 失败: " +
                       ui_workers::py_error_class_name(exc));
    }
    UiVizPayload payload;
    payload.kind = "engine_preview";
    payload.label = label;
    payload.prepared = prepared.payload;
    payload.warning = prepared.warning;
    return payload;
}

}  // namespace

UiVizPayload payload_from_prediction(
    const PredictionTaskSlice& task, const VizPageProjectSlice& project,
    const VizPageResolveSeams& seams) {
    const std::string name =
        !task.name.empty() ? task.name : std::string("prediction");
    try {
        std::any well_log = seams.well_log_from_prediction_fn
                                ? seams.well_log_from_prediction_fn(task.raw)
                                : std::any{};
        std::any volume = seams.seismic_volume_from_prediction_fn
                              ? seams.seismic_volume_from_prediction_fn(task.raw)
                              : std::any{};
        std::string seismic_path;
        const domain::Json* ids =
            task.input_refs.is_object() &&
                    task.input_refs.find(kSeismicKey) != task.input_refs.end()
                ? &task.input_refs.at(kSeismicKey)
                : nullptr;
        if (ids != nullptr && ids->is_array() && !ids->empty() &&
            ids->front().is_string()) {
            const std::string first = ids->front().get<std::string>();
            for (const auto& resource : project.resources) {
                if (resource.id == first && !resource.path.empty()) {
                    seismic_path = abs_path(resource.path, project);
                    break;
                }
            }
        }
        UiVizPayload payload;
        payload.kind = "prediction";
        payload.label = name;
        payload.well_log = well_log;
        if (well_log.has_value()) {
            payload.well_logs.push_back(well_log);
        }
        payload.well_names.push_back(name);
        payload.seismic_volume = std::move(volume);
        payload.seismic_path = std::move(seismic_path);
        return payload;
    } catch (const std::exception& exc) {
        return message_payload(name, "预测可视化失败: " +
                                         ui_workers::py_error_class_name(exc));
    }
}

UiVizPayload resolve_page_payload(
    const VizRefSlice& ref, const VizPageProjectSlice& project,
    const VizPageResolveSeams& seams,
    const std::function<bool()>& is_cancelled) {
    const std::string label = !ref.label.empty()   ? ref.label
                              : !ref.id.empty()    ? ref.id
                                                   : ref.kind;
    try {
        if (ref.kind == "well_log") {
            return payload_from_slice(ui_workers::resolve_well_log(
                ref, to_slices(project.resources), project.project_root,
                is_cancelled, seams.load_fn));
        }
        if (ref.kind == "seismic") {
            return resolve_seismic(ref, project, label);
        }
        if (ref.kind == "map") {
            return resolve_map(ref, project, seams, label);
        }
        if (ref.kind == "cross_well") {
            return resolve_cross_well(ref, project, seams, label);
        }
        if (ref.kind == "engine_preview") {
            return resolve_engine_preview(ref, project, seams, label);
        }
        if (ref.kind == "prediction") {
            const PredictionTaskSlice* task =
                find_prediction(ref, project.prediction_tasks);
            if (task == nullptr) {
                return message_payload(label, "未找到对应的预测任务");
            }
            return payload_from_prediction(*task, project, seams);
        }
        return message_payload(label, "不支持的可视化类型: " + ref.kind);
    } catch (const ui_workers::WellLogLoadCancelled&) {
        throw;  // honest cancellation, never a fake "resolved" payload
    } catch (const std::exception& exc) {
        return message_payload(label, "解析失败: " +
                                          ui_workers::py_error_class_name(exc));
    }
}

// ---------------------------------------------------------------------------
// Summary panel
// ---------------------------------------------------------------------------

namespace {

const std::map<std::string, std::string>& kind_labels() {
    static const std::map<std::string, std::string> labels = {
        {"well_log", "测井"},      {"seismic", "地震"},
        {"map", "古地理"},         {"cross_well", "连井"},
        {"engine_preview", "引擎"}, {"prediction", "预测"},
    };
    return labels;
}

}  // namespace

std::optional<VizRefSlice> cross_well_virtual_ref(
    const std::vector<ResourceItem>& resources) {
    std::vector<std::string> well_ids;
    for (const auto& resource : resources) {
        if (ui_workers::viz_norm_type(resource.type) == "well_log" &&
            ui_workers::viz_norm_format(resource.format) == "las" &&
            !resource.id.empty()) {
            well_ids.push_back(resource.id);
        }
    }
    if (well_ids.size() < 2) {
        return std::nullopt;
    }
    VizRefSlice ref;
    ref.kind = "cross_well";
    ref.id = well_ids.front();
    ref.label =
        "连井剖面 (" + std::to_string(well_ids.size()) + " 口井)";
    ref.related_ids.assign(
        well_ids.begin(), well_ids.begin() +
                              std::min<std::size_t>(8, well_ids.size()));
    return ref;
}

std::vector<VizAssetEntry> summary_asset_entries(
    const std::vector<ResourceItem>& resources,
    const std::vector<MapDocSlice>& map_documents,
    const std::vector<PredictionTaskSlice>& prediction_tasks) {
    std::vector<VizAssetEntry> entries;
    for (const auto& resource : resources) {
        const auto ref = ui_workers::ref_from_resource(resource_slice(resource));
        if (!ref.has_value()) {
            continue;
        }
        const std::string name = !resource.name.empty()   ? resource.name
                                 : !ref->label.empty()    ? ref->label
                                 : !ref->id.empty()       ? ref->id
                                                          : "未命名";
        const auto it = kind_labels().find(ref->kind);
        const std::string label =
            it != kind_labels().end() ? it->second : ref->kind;
        entries.push_back({"res:" + ref->id, *ref, label + " · " + name});
    }
    for (const auto& doc : map_documents) {
        VizRefSlice ref = ref_from_map_document(doc);
        const std::string name = !doc.name.empty()      ? doc.name
                                 : !ref.label.empty()   ? ref.label
                                                        : "未命名图件";
        entries.push_back({"map:" + ref.id, ref, "古地理 · " + name});
    }
    for (const auto& task : prediction_tasks) {
        VizRefSlice ref = ref_from_prediction(task);
        const std::string name = !task.name.empty()    ? task.name
                                 : !ref.label.empty()  ? ref.label
                                                       : "预测任务";
        entries.push_back({"pred:" + ref.id, ref, "预测 · " + name});
    }
    if (const auto ref = cross_well_virtual_ref(resources); ref.has_value()) {
        entries.push_back({"cross_well", *ref, "连井 · " + ref->label});
    }
    return entries;
}

VizSummaryCounts summary_counts(std::size_t resources,
                                std::size_t prediction_tasks,
                                std::size_t map_documents) {
    return {std::to_string(prediction_tasks) + " 个",
            std::to_string(map_documents) + " 幅",
            std::to_string(resources) + " 项"};
}

// ---------------------------------------------------------------------------
// Page combo / signatures
// ---------------------------------------------------------------------------

std::vector<VizComboEntry> asset_combo_entries(
    const std::vector<ResourceItem>& resources,
    const std::vector<MapDocSlice>& map_documents) {
    std::vector<VizComboEntry> entries;
    for (const auto& resource : resources) {
        const auto ref = ui_workers::ref_from_resource(resource_slice(resource));
        if (!ref.has_value()) {
            continue;
        }
        const std::string icon = ref->kind == "well_log" ? "▤ "
                                 : ref->kind == "map"   ? "◉ "
                                                        : "✦ ";
        entries.push_back({icon + ref->label, *ref});
    }
    for (const auto& doc : map_documents) {
        VizRefSlice ref = ref_from_map_document(doc);
        entries.push_back({"◉ " + ref.label, ref});
    }
    return entries;
}

VizRefSignature combo_signature(const std::vector<VizComboEntry>& entries) {
    VizRefSignature signature;
    signature.reserve(entries.size());
    for (const auto& entry : entries) {
        signature.emplace_back(entry.ref.kind, entry.ref.id, entry.ref.label,
                               entry.ref.path);
    }
    return signature;
}

bool refs_match(const VizRefSlice* a, const VizRefSlice* b) {
    if (a == b) {
        return true;
    }
    if (a == nullptr || b == nullptr) {
        return false;
    }
    return a->kind == b->kind && a->id == b->id && a->path == b->path;
}

bool refs_match(const std::optional<VizRefSlice>& a, const VizRefSlice& b) {
    return a.has_value() && refs_match(&*a, &b);
}

// ---------------------------------------------------------------------------
// Trace panel
// ---------------------------------------------------------------------------

VizTraceView trace_state_view(
    const std::vector<PredictionTaskSlice>& prediction_tasks,
    const std::vector<MapDocSlice>& map_documents) {
    return trace_state_view_prefer(prediction_tasks, map_documents, "");
}

VizTraceView trace_state_view_prefer(
    const std::vector<PredictionTaskSlice>& prediction_tasks,
    const std::vector<MapDocSlice>& map_documents,
    const std::string& prefer_map_id) {
    VizTraceView view;
    if (!prediction_tasks.empty() && !prediction_tasks.back().name.empty()) {
        view.task_text = prediction_tasks.back().name;
    }
    // active_map_document: prefer_id hit else last document.
    const MapDocSlice* active = nullptr;
    if (!prefer_map_id.empty()) {
        for (const auto& doc : map_documents) {
            if (doc.id == prefer_map_id) {
                active = &doc;
                break;
            }
        }
    }
    if (active == nullptr && !map_documents.empty()) {
        active = &map_documents.back();
    }
    if (active != nullptr && !active->name.empty()) {
        view.map_text = active->name;
    }
    return view;
}

void trace_apply_ref(VizTraceView& view, const VizRefSlice* ref,
                     const UiVizPayload* payload) {
    if (ref == nullptr) {
        view.source_text = "—";
        view.label_text = "—";
        view.kind_text = "—";
        view.path_text = "—";
        return;
    }
    const auto payload_label = [&payload]() -> std::string {
        return payload != nullptr ? payload->label : std::string{};
    };
    view.source_text = !ref->source.empty() ? ref->source : "—";
    const std::string label = !ref->label.empty() ? ref->label
                                                  : payload_label();
    view.label_text = !label.empty() ? label : "—";
    view.kind_text = !ref->kind.empty() ? ref->kind : "—";

    if (ref->kind == "prediction") {
        view.task_text = !label.empty() ? label : "—";
    }
    if (ref->kind == "map") {
        view.map_text = !label.empty() ? label : "—";
    }

    std::string path_or_message = ref->path;
    if (payload != nullptr) {
        if (!payload->message.empty()) {
            path_or_message = path_or_message.empty()
                                  ? payload->message
                                  : path_or_message + "\n" + payload->message;
        } else if (!payload->warning.empty() && path_or_message.empty()) {
            path_or_message = payload->warning;
        } else if (path_or_message.empty() && !payload->label.empty()) {
            path_or_message = payload->label;
        }
    }
    view.path_text = !path_or_message.empty() ? path_or_message : "—";
}

ExportCaps export_capability_state(const std::set<std::string>& formats) {
    std::set<std::string> caps;
    for (const auto& format : formats) {
        std::string upper = format;
        std::transform(upper.begin(), upper.end(), upper.begin(),
                       [](unsigned char c) {
                           return static_cast<char>(std::toupper(c));
                       });
        caps.insert(std::move(upper));
    }
    ExportCaps out;
    out.png = caps.count("PNG") != 0U;
    out.svg = caps.count("SVG") != 0U;
    out.pdf = caps.count("PDF") != 0U;
    if (out.svg) {
        out.svg_tip = "导出当前 Tab 为 SVG 矢量图";
    }
    if (out.pdf) {
        out.pdf_tip = "导出当前 Tab 为 PDF";
    }
    if (out.png) {
        out.png_tip = "导出当前 Tab 截图 PNG";
    }
    return out;
}

// ---------------------------------------------------------------------------
// Workspace routing (composite_visualization_panel.load_payload)
// ---------------------------------------------------------------------------

std::string host_tab_title(VizHostKind kind) {
    switch (kind) {
        case VizHostKind::WellLog: return "测井";
        case VizHostKind::WellSection: return "多井对比剖面";
        case VizHostKind::Seismic: return "地震";
        case VizHostKind::CrossWell: return "连井";
        case VizHostKind::PaleoMap: return "古地理";
        case VizHostKind::WellTie: return "井震标定";
        case VizHostKind::EnginePreview: return "引擎预览";
    }
    return {};
}

bool keep_well_session(const UiVizPayload& payload) {
    return (payload.kind == "well_log" || payload.kind == "prediction" ||
            payload.kind == "cross_well") &&
           (payload.well_log.has_value() || !payload.well_logs.empty());
}

std::vector<VizHostKind> hosts_to_apply(const UiVizPayload& payload) {
    std::vector<VizHostKind> hosts;
    const bool well_family = payload.kind == "well_log" ||
                             payload.kind == "prediction" ||
                             payload.kind == "cross_well";
    if (well_family) {
        hosts.push_back(VizHostKind::WellLog);
        hosts.push_back(VizHostKind::WellSection);
        hosts.push_back(VizHostKind::CrossWell);
    }
    if (payload.kind == "seismic" || payload.kind == "prediction" ||
        !payload.seismic_path.empty() || payload.seismic_volume.has_value()) {
        hosts.push_back(VizHostKind::Seismic);
    }
    if (payload.kind == "map" || json_list_truthy(payload.map_features) ||
        json_list_truthy(payload.map_wells)) {
        hosts.push_back(VizHostKind::PaleoMap);
    }
    if (well_family || payload.kind == "seismic" ||
        payload.well_log.has_value() || !payload.well_logs.empty() ||
        payload.seismic_volume.has_value()) {
        hosts.push_back(VizHostKind::WellTie);
    }
    if (payload.kind == "engine_preview" || payload.prepared.has_value()) {
        hosts.push_back(VizHostKind::EnginePreview);
    }
    return hosts;
}

std::optional<VizHostKind> focus_tab_for(const UiVizPayload& payload) {
    if (payload.kind == "well_log") return VizHostKind::WellLog;
    if (payload.kind == "seismic") return VizHostKind::Seismic;
    if (payload.kind == "cross_well") return VizHostKind::CrossWell;
    if (payload.kind == "map") return VizHostKind::PaleoMap;
    if (payload.kind == "engine_preview") return VizHostKind::EnginePreview;
    if (payload.kind == "prediction") {
        return payload.seismic_volume.has_value() ? VizHostKind::Seismic
                                                  : VizHostKind::WellLog;
    }
    return std::nullopt;
}

std::string workspace_status_text(const std::string& label,
                                  const std::string& warning,
                                  const std::vector<std::string>& applied) {
    std::vector<std::string> parts;
    if (!applied.empty()) {
        std::string head = "已加载: " + label + " → ";
        std::set<std::string> seen;
        bool first = true;
        for (const auto& title : applied) {
            if (!seen.insert(title).second) {
                continue;
            }
            if (!first) {
                head += ", ";
            }
            head += title;
            first = false;
        }
        parts.push_back(std::move(head));
    } else {
        parts.push_back("未能加载: " + label);
    }
    if (!warning.empty()) {
        parts.push_back(warning);
    }
    std::string out;
    for (const auto& part : parts) {
        if (part.empty()) {
            continue;
        }
        if (!out.empty()) {
            out += " · ";
        }
        out += part;
    }
    return out;
}

std::optional<SectionCursorRect> section_cursor_geometry(
    const std::string& well_name,
    const std::vector<std::string>& last_well_names, int widget_width,
    int widget_height) {
    const std::string name =
        ui_data_core::strip_copy(well_name.empty() ? "" : well_name);
    if (name.empty()) {
        return std::nullopt;
    }
    const auto it =
        std::find(last_well_names.begin(), last_well_names.end(), name);
    if (it == last_well_names.end() || last_well_names.empty()) {
        return std::nullopt;
    }
    const int width = std::max(1, widget_width);
    const auto index =
        static_cast<double>(std::distance(last_well_names.begin(), it));
    const int x = static_cast<int>(
                      width * (index + 0.5) /
                      static_cast<double>(last_well_names.size())) -
                  3;
    return SectionCursorRect{x, 0, 6, std::max(1, widget_height)};
}

// ---------------------------------------------------------------------------
// Facies hierarchy
// ---------------------------------------------------------------------------

std::string facies_level_display(const std::string& level) {
    static const std::map<std::string, std::string> display = {
        {"facies", "相（1 级）"},
        {"sub_facies", "亚相（2 级）"},
        {"micro_facies", "微相（3 级）"},
    };
    const auto it = display.find(level);
    return it != display.end() ? it->second : level;
}

std::optional<std::string> feature_facies_level(const domain::Json& feature) {
    if (!feature.is_object()) {
        return std::nullopt;
    }
    const auto props_it = feature.find("properties");
    if (props_it == feature.end() || !props_it->is_object()) {
        return std::nullopt;
    }
    const domain::Json& props = *props_it;
    const domain::Json* raw = nullptr;
    if (const auto it = props.find("level");
        it != props.end() && !it->is_null()) {
        raw = &*it;
    } else if (const auto it2 = props.find("facies_level");
               it2 != props.end() && !it2->is_null()) {
        raw = &*it2;
    }
    if (raw == nullptr || !raw->is_string()) {
        return std::nullopt;
    }
    std::string level = raw->get<std::string>();
    std::transform(level.begin(), level.end(), level.begin(),
                   [](unsigned char c) {
                       return static_cast<char>(std::tolower(c));
                   });
    level = ui_data_core::strip_copy(level);
    for (const char* known : kFaciesLevels) {
        if (level == known) {
            return level;
        }
    }
    return std::nullopt;
}

std::vector<std::string> hierarchy_levels_present(
    const domain::Json& features) {
    std::set<std::string> present;
    if (features.is_array()) {
        for (const auto& feature : features) {
            if (const auto level = feature_facies_level(feature);
                level.has_value()) {
                present.insert(*level);
            }
        }
    }
    std::vector<std::string> ordered;
    for (const char* level : kFaciesLevels) {
        if (present.count(level) != 0U) {
            ordered.emplace_back(level);
        }
    }
    return ordered;
}

bool is_hierarchical_feature_set(const domain::Json& features) {
    if (!features.is_array()) {
        return false;
    }
    for (const auto& feature : features) {
        if (feature_facies_level(feature).has_value()) {
            return true;
        }
    }
    return false;
}

std::vector<std::pair<std::string, std::string>> facies_level_choices(
    const domain::Json& features) {
    std::vector<std::pair<std::string, std::string>> choices = {
        {kAutoLevel, "自动（按比例尺切换）"}};
    for (const auto& level : hierarchy_levels_present(features)) {
        choices.emplace_back(level, facies_level_display(level));
    }
    return choices;
}

// ---------------------------------------------------------------------------
// misc
// ---------------------------------------------------------------------------

bool payload_has_map_geometry(const UiVizPayload& payload) {
    return json_list_truthy(payload.map_features) ||
           json_list_truthy(payload.map_wells);
}

// ---------------------------------------------------------------------------
// shared page-level helpers (the adapter conversions the shells reuse)
// ---------------------------------------------------------------------------

ui_workers::ResourceSlice resource_slice(const ResourceItem& resource) {
    return ui_workers::ResourceSlice{resource.id, resource.name,
                                     resource.path, resource.type,
                                     resource.format};
}

std::vector<ui_workers::ResourceSlice> resource_slices(
    const std::vector<ResourceItem>& resources) {
    return to_slices(resources);
}

std::string absolute_ref_path(const std::string& path,
                              const VizPageProjectSlice& project) {
    return abs_path(path, project);
}

bool ref_path_is_file(const std::string& path) { return is_file(path); }

}  // namespace pwb::ui_seqviz
