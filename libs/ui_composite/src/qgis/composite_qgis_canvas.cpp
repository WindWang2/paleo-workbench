#include <pwb/ui_composite/qgis/composite_qgis_canvas.hpp>

#include <pwb/ui_composite/map_tools.hpp>
#include <pwb/ui_composite/vector_layer.hpp>
#include <pwb/ui_widgets/qgis/mirror_snapshot.hpp>

#include <QString>
#include <QVariantMap>

namespace pwb::ui_composite::qgis {

namespace {

// Json ⇄ QVariant bridges (same shape as composite_controller_qt's
// file-local helper — payloads cross the shim as QVariantMap/List).
QVariant json_to_variant(const Json& value) {
    if (value.is_null()) return {};
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_number_integer())
        return QVariant::fromValue<qlonglong>(value.get<long long>());
    if (value.is_number_unsigned())
        return QVariant::fromValue<qulonglong>(
            value.get<unsigned long long>());
    if (value.is_number_float()) return value.get<double>();
    if (value.is_string())
        return QString::fromStdString(value.get<std::string>());
    if (value.is_array()) {
        QVariantList list;
        for (const Json& entry : value)
            list.append(json_to_variant(entry));
        return list;
    }
    if (value.is_object()) {
        QVariantMap map;
        for (auto it = value.begin(); it != value.end(); ++it)
            map[QString::fromStdString(it.key())] =
                json_to_variant(it.value());
        return map;
    }
    return {};
}

Json variant_to_json(const QVariant& value) {
    switch (value.typeId()) {
        case QMetaType::Bool:
            return Json(value.toBool());
        case QMetaType::Int:
        case QMetaType::LongLong:
            return Json(value.toLongLong());
        case QMetaType::UInt:
        case QMetaType::ULongLong:
            return Json(value.toULongLong());
        case QMetaType::Float:
        case QMetaType::Double:
            return Json(value.toDouble());
        case QMetaType::QString:
            return Json(value.toString().toStdString());
        case QMetaType::QStringList:
        case QMetaType::QVariantList: {
            Json out = Json::array();
            for (const QVariant& entry : value.toList())
                out.push_back(variant_to_json(entry));
            return out;
        }
        case QMetaType::QVariantMap: {
            Json out = Json::object();
            const QVariantMap map = value.toMap();
            for (auto it = map.constBegin(); it != map.constEnd(); ++it)
                out[it.key().toStdString()] = variant_to_json(it.value());
            return out;
        }
        default:
            return Json();
    }
}

std::vector<int> variant_path(const QVariantList& path) {
    std::vector<int> out;
    out.reserve(path.size());
    for (const QVariant& entry : path) out.push_back(entry.toInt());
    return out;
}

Modifiers variant_modifiers(const QVariantList& mods) {
    Modifiers out;
    for (const QVariant& entry : mods)
        out.insert(entry.toString().toStdString());
    return out;
}

// The Python `tool.layer` duck: selection feedback resolves the
// highlight layer from whichever handle the active tool exposes.
VectorLayer* tool_layer(MapTool* tool) {
    if (tool == nullptr) return nullptr;
    if (auto* t = dynamic_cast<SelectTool*>(tool)) return &t->layer();
    if (auto* t = dynamic_cast<RectangleSelectTool*>(tool))
        return &t->layer();
    VectorEditSession* session = nullptr;
    if (auto* t = dynamic_cast<CaptureTool*>(tool))
        session = t->session;
    else if (auto* t = dynamic_cast<SnapGeometriesTool*>(tool))
        session = t->session;
    else if (auto* t = dynamic_cast<MoveFeatureTool*>(tool))
        session = t->session;
    else if (auto* t = dynamic_cast<ReshapeTool*>(tool))
        session = t->session;
    else if (auto* t = dynamic_cast<VertexTool*>(tool))
        session = t->session;
    else if (auto* t = dynamic_cast<RingCaptureTool*>(tool))
        session = t->session;
    else if (auto* t = dynamic_cast<PartCaptureTool*>(tool))
        session = t->session;
    return session == nullptr ? nullptr : &session->layer;
}

// tool.commit_geometry duck: every tool class exposing the commit
// surface gets a shot (Python getattr dispatch order).
bool dispatch_commit_geometry(MapTool* tool, const Json& geometry) {
    if (auto* t = dynamic_cast<CaptureTool*>(tool))
        return t->commit_geometry(geometry);
    if (auto* t = dynamic_cast<ReshapeTool*>(tool))
        return t->commit_geometry(geometry);
    if (auto* t = dynamic_cast<RingCaptureTool*>(tool))
        return t->commit_geometry(geometry);
    if (auto* t = dynamic_cast<PartCaptureTool*>(tool))
        return t->commit_geometry(geometry);
    return false;
}

}  // namespace

CompositeQgisCanvas::CompositeQgisCanvas(
    CompositeEditController* controller, QWidget* parent)
    : QObject(parent), controller_(controller) {
    shim_ = new ui_widgets::qgis::QgisCanvasShim(parent);
    install_canvas_hooks();
    install_controller_hooks();
}

CompositeQgisCanvas::~CompositeQgisCanvas() { shutdown(); }

void CompositeQgisCanvas::install_canvas_hooks() {
    if (controller_ == nullptr) return;
    ui_widgets::qgis::QgisCanvasShim* shim = shim_;
    CompositeCanvasHooks hooks;
    hooks.map_units_per_pixel = [shim]() {
        return shim == nullptr ? 0.0 : shim->map_units_per_pixel();
    };
    hooks.zoom_by = [shim](double factor, const MapPoint& center) {
        if (shim != nullptr)
            shim->zoom_by(factor, {{center[0], center[1]}});
    };
    hooks.set_current_layer = [shim](const std::string& layer_id) {
        if (shim != nullptr)
            shim->set_current_layer(QString::fromStdString(layer_id));
    };
    hooks.current_layer_doc_id = [shim]() {
        return shim == nullptr
                   ? std::string{}
                   : shim->current_layer_doc_id().toStdString();
    };
    // #1276 parity: a rejected push reports false; the controller flips
    // snapping.enabled off on its side.
    hooks.set_snapping_config = [shim](const Json& config) {
        return shim != nullptr &&
               shim->set_snapping_config(
                   json_to_variant(config).toMap());
    };
    hooks.set_vertex_edit_scope = [shim](bool all_layers) {
        if (shim != nullptr) shim->set_vertex_edit_scope(all_layers);
    };
    hooks.set_tracing_enabled = [shim](bool enabled) {
        if (shim != nullptr) shim->set_tracing_enabled(enabled);
    };
    hooks.native_tool_busy = [shim]() {
        return shim != nullptr && shim->native_tool_busy();
    };
    hooks.cancel_native_tool = [shim]() {
        if (shim != nullptr) shim->cancel_native_tool();
    };
    hooks.focus = [shim]() {
        if (shim != nullptr) shim->setFocus();
    };
    hooks.canvas_address = [shim]() {
        return shim == nullptr ? std::uintptr_t{0} : shim->canvas_address();
    };
    controller_->attach_canvas(hooks);
    hooks_installed_ = true;
}

ui_widgets::qgis::ToolHooks CompositeQgisCanvas::make_tool_hooks()
    const {
    using ui_widgets::qgis::ToolHooks;
    CompositeEditController* ctl = controller_;
    ToolHooks hooks;
    MapTool* tool = ctl->tools.active_tool();
    hooks.tool_id =
        QString::fromStdString(ctl->tools.active_tool_id());
    hooks.native_digitize_kind =
        tool == nullptr ? QString{}
                        : QString::fromStdString(tool->native_digitize_kind);
    hooks.commit_vertex_move =
        [ctl](const QString& feature_id, const QVariantList& path,
              std::pair<double, double> xy) {
            auto* tool = dynamic_cast<VertexTool*>(
                ctl->tools.active_tool());
            if (tool == nullptr) return false;
            return tool->commit_vertex_move(
                feature_id.toStdString(), variant_path(path),
                {xy.first, xy.second});
        };
    hooks.commit_vertex_insert =
        [ctl](const QString& feature_id, const QVariantList& path,
              std::pair<double, double> xy) {
            auto* tool = dynamic_cast<VertexTool*>(
                ctl->tools.active_tool());
            if (tool == nullptr) return false;
            return tool->commit_vertex_insert(
                feature_id.toStdString(), variant_path(path),
                {xy.first, xy.second});
        };
    hooks.commit_vertex_delete =
        [ctl](const QString& feature_id, const QVariantList& path) {
            auto* tool = dynamic_cast<VertexTool*>(
                ctl->tools.active_tool());
            if (tool == nullptr) return false;
            return tool->commit_vertex_delete(feature_id.toStdString(),
                                              variant_path(path));
        };
    hooks.commit_move =
        [ctl](const QString& feature_id, double dx, double dy) {
            auto* tool = dynamic_cast<MoveFeatureTool*>(
                ctl->tools.active_tool());
            if (tool == nullptr) return false;
            return tool->commit_move(feature_id.toStdString(), dx, dy);
        };
    hooks.commit_geometry = [ctl](const QVariantMap& geometry) {
        return dispatch_commit_geometry(ctl->tools.active_tool(),
                                        variant_to_json(geometry));
    };
    hooks.commit_selection =
        [ctl](const QVariantList& feature_ids,
              const QVariantList& modifiers) {
            auto* tool = dynamic_cast<SelectTool*>(
                ctl->tools.active_tool());
            if (tool == nullptr) return false;
            std::vector<std::string> ids;
            ids.reserve(feature_ids.size());
            for (const QVariant& id : feature_ids)
                ids.push_back(id.toString().toStdString());
            return tool->commit_selection(ids,
                                          variant_modifiers(modifiers));
        };
    hooks.highlight_layer_doc_id = [ctl]() {
        VectorLayer* layer = tool_layer(ctl->tools.active_tool());
        return layer == nullptr ? QString{}
                                : QString::fromStdString(layer->id());
    };
    hooks.highlight_feature_ids = [ctl]() {
        QStringList out;
        VectorLayer* layer = tool_layer(ctl->tools.active_tool());
        if (layer != nullptr) {
            for (const std::string& fid : layer->selection())
                out.append(QString::fromStdString(fid));
        }
        return out;
    };
    // Fallback measure surface (non-native measure tool): the router
    // feeds raw mouse events into the active MapTool state machine.
    hooks.mouse_press =
        [ctl](std::pair<double, double> point, const QString& button,
              const QStringList& modifiers) {
            MapTool* active = ctl->tools.active_tool();
            if (active != nullptr) {
                Modifiers mods;
                for (const QString& m : modifiers)
                    mods.insert(m.toStdString());
                active->mouse_press({point.first, point.second},
                                    button.toStdString(), mods);
            }
        };
    hooks.mouse_release =
        [ctl](std::pair<double, double> point, const QString& button,
              const QStringList& modifiers) {
            MapTool* active = ctl->tools.active_tool();
            if (active != nullptr) {
                Modifiers mods;
                for (const QString& m : modifiers)
                    mods.insert(m.toStdString());
                active->mouse_release({point.first, point.second},
                                      button.toStdString(), mods);
            }
        };
    hooks.double_click =
        [ctl](std::pair<double, double> point,
              const QStringList& modifiers) {
            MapTool* active = ctl->tools.active_tool();
            if (active != nullptr) {
                Modifiers mods;
                for (const QString& m : modifiers)
                    mods.insert(m.toStdString());
                active->double_click({point.first, point.second}, mods);
            }
        };
    hooks.last_distance = [ctl]() -> std::optional<double> {
        auto* tool = dynamic_cast<MeasureDistanceTool*>(
            ctl->tools.active_tool());
        if (tool == nullptr) return std::nullopt;
        return tool->last_distance;
    };
    hooks.start_point =
        [ctl]() -> std::optional<std::pair<double, double>> {
        auto* tool = dynamic_cast<MeasureDistanceTool*>(
            ctl->tools.active_tool());
        if (tool == nullptr || !tool->start.has_value())
            return std::nullopt;
        return std::pair{(*tool->start)[0], (*tool->start)[1]};
    };
    hooks.current_point =
        [ctl]() -> std::optional<std::pair<double, double>> {
        auto* tool = dynamic_cast<MeasureDistanceTool*>(
            ctl->tools.active_tool());
        if (tool == nullptr || !tool->current.has_value())
            return std::nullopt;
        return std::pair{(*tool->current)[0], (*tool->current)[1]};
    };
    return hooks;
}

void CompositeQgisCanvas::install_controller_hooks() {
    if (controller_ == nullptr || shim_ == nullptr) return;
    CompositeEditController* ctl = controller_;
    ui_widgets::qgis::ControllerHooks hooks;
    // active_tool: rebuilt per call — the lambdas re-resolve the live
    // MapTool so a tool switch can never leave a stale duck bound.
    hooks.active_tool = [this]() -> ui_widgets::qgis::ToolHooks* {
        tool_hooks_ = make_tool_hooks();
        return &tool_hooks_;
    };
    // Native-first digitize routing (splits/cuts take precedence over
    // the active tool's commit_geometry — ordering is contract).
    hooks.commit_native_capture = [ctl](const QVariantMap& geometry) {
        return ctl->commit_native_capture(variant_to_json(geometry));
    };
    hooks.cancel_native_capture = [ctl]() {
        ctl->cancel_native_capture();
    };
    hooks.record_native_gesture = [ctl](const QVariantMap& gesture) {
        ctl->record_native_gesture(variant_to_json(gesture));
        return true;
    };
    hooks.join_native_layers = [ctl](const QStringList& layer_doc_ids) {
        std::vector<std::string> ids;
        ids.reserve(layer_doc_ids.size());
        for (const QString& id : layer_doc_ids)
            ids.push_back(id.toStdString());
        ctl->join_native_layers(ids);
    };
    shim_->set_controller_hooks(hooks);
    // Native tool factory: the composite edit stack's QgsMapTool
    // inventory lands with the native-editing seam; absent → the
    // shim's built-in pan/zoom only, and edit kinds report activation
    // failure honestly (native_tool_activation_failed).
    shim_->set_native_measure_supported(false);
    // Esc/drag-in-progress probe: routed to the native-editing seam,
    // NOT back through the canvas hooks (native_tool_busy → busy_probe_
    // would recurse). Absent seam = no host-declared busy state — the
    // shim's own armed QgsMapTool still reports via its signals.
    // No busy surface exists on the INativeEditing seam yet — the
    // probe reports false honestly; the shim's own armed QgsMapTool
    // still reports its busy state via signals.
    shim_->set_busy_probe([]() { return false; });
}

void CompositeQgisCanvas::publish_layers(
    const std::vector<MapLayerSnapshot>& layers,
    const std::string& project_crs) {
    if (shim_ == nullptr) return;
    ui_widgets::qgis::MirrorSnapshot snapshot;
    snapshot.project_crs = QString::fromStdString(project_crs);
    snapshot.layers.reserve(layers.size());
    for (const MapLayerSnapshot& layer : layers) {
        ui_widgets::qgis::MirrorLayerSpec spec;
        spec.id = QString::fromStdString(layer.id);
        spec.name = QString::fromStdString(layer.name);
        spec.layer_type = QString::fromStdString(layer.layer_type);
        for (const Json& record : layer.features) {
            // {"id","geometry","properties"} record → Feature dict;
            // the doc feature id rides as __pwb_fid (memory provider
            // keeps no fid authority).
            QVariantMap feature;
            feature[QStringLiteral("type")] =
                QStringLiteral("Feature");
            feature[QStringLiteral("geometry")] =
                json_to_variant(record.value("geometry", Json()));
            QVariantMap props =
                json_to_variant(
                    record.value("properties", Json::object()))
                    .toMap();
            const auto id = record.find("id");
            if (id != record.end() && !id->is_null()) {
                props[QStringLiteral("__pwb_fid")] =
                    QString::fromStdString(
                        id->is_string() ? id->get<std::string>()
                                        : id->dump());
            }
            feature[QStringLiteral("properties")] = props;
            spec.features.append(feature);
        }
        for (const auto& [key, value] : layer.metadata) {
            spec.metadata[QString::fromStdString(key)] =
                QString::fromStdString(value);
        }
        spec.style = json_to_variant(layer.style).toMap();
        spec.visible = layer.visible;
        spec.opacity = layer.opacity;
        spec.crs = QString::fromStdString(layer.crs);
        spec.extent = {layer.extent[0], layer.extent[1],
                       layer.extent[2], layer.extent[3]};
        spec.data_revision = layer.data_revision;
        if (layer.scale_range.has_value()) {
            spec.min_scale = layer.scale_range->first;
            spec.max_scale = layer.scale_range->second;
        }
        spec.source_version_id =
            QString::fromStdString(layer.source_version_id);
        // raster_source layers carry their file path as the opaque
        // renderer payload token.
        spec.source_path =
            QString::fromStdString(layer.renderer_payload);
        snapshot.layers.push_back(std::move(spec));
    }
    shim_->set_layer_snapshot(snapshot);
}

void CompositeQgisCanvas::shutdown() {
    if (hooks_installed_ && controller_ != nullptr) {
        controller_->detach_canvas();
        hooks_installed_ = false;
    }
    if (shim_ != nullptr && !shim_->is_shutdown()) shim_->shutdown();
}

}  // namespace pwb::ui_composite::qgis
