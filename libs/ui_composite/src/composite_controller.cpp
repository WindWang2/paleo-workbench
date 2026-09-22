#include <pwb/ui_composite/composite_controller.hpp>

#include <algorithm>
#include <cmath>
#include <tuple>

#include <pwb/ui_composite/capture_spec.hpp>
#include <pwb/ui_composite/geometry.hpp>
#include <pwb/ui_composite/map_styles.hpp>
#include <pwb/ui_composite/roles.hpp>
#include <pwb/ui_composite/snapping_profiles.hpp>
#include <pwb/ui_data_core/map_edit_geometry.hpp>

namespace pwb::ui_composite {
namespace {

void emit(const std::function<void()>& fn) {
    if (fn) fn();
}
// 信号槽语义：槽签名与实参类型分别推导——槽声明 const ref 形参时实参
// 仍可传值/引用；槽异常绝不改写命令结果。
template <typename... SigArgs, typename... CallArgs>
void emit(const std::function<void(SigArgs...)>& fn, CallArgs&&... args) {
    if (!fn) return;
    try {
        fn(std::forward<CallArgs>(args)...);
    } catch (const std::exception&) {
    }
}

// _union_extent parity: bounding-box union of two extents (session
// 增量 extent 的单调并集).
MapExtent union_extents(const MapExtent& left, const MapExtent& right) {
    return {std::min(left[0], right[0]), std::min(left[1], right[1]),
            std::max(left[2], right[2]), std::max(left[3], right[3])};
}

// _feature_extent parity: empty set keeps the placeholder extent
// (Python caught ValueError -> (0,0,1,1)).
MapExtent feature_extent_or_placeholder(const std::vector<Json>& features) {
    try {
        return feature_extent(features);
    } catch (const std::exception&) {
        return MapExtent{0.0, 0.0, 1.0, 1.0};
    }
}

// _KIND_STYLE_PRESET: default_style_for 的符号库预设。
const std::map<std::string, std::string>& kind_style_preset() {
    static const std::map<std::string, std::string> presets = {
        {"point", "well"}, {"line", "line"}, {"polygon", "facies"}};
    return presets;
}

Json point_to_json(const MapPoint& p) {
    return Json::array({p[0], p[1]});
}

// _iter_layer_coords parity: committed features of the layer.
std::vector<MapPoint> iter_layer_coords(const VectorLayer& layer) {
    std::vector<Json> records;
    for (const auto& f : layer.features())
        records.push_back(f.as_record());
    return iter_feature_coords(records);
}

}  // namespace

// ---------------------------------------------------------------------------
// module constants
// ---------------------------------------------------------------------------

const std::set<std::string>& layer_bound_tools() {
    static const std::set<std::string> tools = {
        "identify", "select", "select_rectangle", "move_feature", "vertex"};
    return tools;
}

const std::map<std::string, std::string>& kind_bound_tools() {
    static const std::map<std::string, std::string> tools = {
        {"add_point", "point"},          {"add_line", "line"},
        {"add_polygon", "polygon"},      {"add_rectangle", "polygon"},
        {"add_circle", "polygon"},       {"add_regular_polygon", "polygon"},
        {"add_arc", "line"},             {"add_ellipse", "polygon"},
        {"add_sector", "polygon"}};
    return tools;
}

const std::set<std::string>& snapshot_roleless_roles() {
    static const std::set<std::string> roles = {
        "", "legacy_unclassified", "user_general"};
    return roles;
}

std::string normalize_layer_role(const std::string& role) {
    std::string value = role;
    // trim
    const auto first = value.find_first_not_of(" \t\r\n");
    const auto last = value.find_last_not_of(" \t\r\n");
    if (first == std::string::npos) return "";
    return value.substr(first, last - first + 1);
}

std::optional<std::string> pick_topmost_visible_layer_id(
    const std::vector<std::string>& layer_ids_bottom_up,
    const std::set<std::string>& visible_ids) {
    for (auto it = layer_ids_bottom_up.rbegin();
         it != layer_ids_bottom_up.rend(); ++it) {
        if (visible_ids.count(*it)) return *it;
    }
    return std::nullopt;
}

// ---------------------------------------------------------------------------
// ctor / gates
// ---------------------------------------------------------------------------

CompositeEditController::CompositeEditController(std::string crs)
    : project_crs(std::move(crs)) {}

std::pair<bool, std::string> CompositeEditController::can_edit_layer(
    const std::string& layer_id) const {
    if (!edit_gate_) return {true, ""};
    return edit_gate_(layer_id);
}

std::optional<bool> CompositeEditController::snapping_role_recommended(
    const VectorLayer* layer) const {
    if (layer == nullptr) return std::nullopt;
    std::string role = role_of_layer(layer->id());
    if (role.empty()) return std::nullopt;
    const SnappingProfile* profile = recommended_profile_for_role(role);
    if (profile == nullptr) return std::nullopt;
    auto modes_it = snapping_.layer_modes.find(layer->id());
    auto tol_it = snapping_.layer_tolerance.find(layer->id());
    if (modes_it == snapping_.layer_modes.end() ||
        tol_it == snapping_.layer_tolerance.end())
        return false;
    std::set<std::string> want(profile->modes.begin(),
                               profile->modes.end());
    return modes_it->second == want &&
           std::abs(tol_it->second - profile->tolerance_px) < 1e-9;
}

std::string CompositeEditController::role_of_layer(
    const std::string& layer_id) const {
    if (!role_lookup_) return "";
    try {
        auto role = role_lookup_(layer_id);
        if (!role.has_value()) return "";
        return *role;
    } catch (const std::exception&) {
        return "";
    }
}

void CompositeEditController::set_layer_role(const std::string& layer_id,
                                             const std::string& role) {
    std::string value = normalize_layer_role(role);
    if (!value.empty())
        layer_roles_[layer_id] = value;
    else
        layer_roles_.erase(layer_id);
}

Json CompositeEditController::capture_defaults_for_role(
    const std::string& layer_id) const {
    const GeologicalCaptureSpec* spec =
        capture_spec_for_role(role_of_layer(layer_id));
    if (spec == nullptr || spec->template_key.empty()) return Json::object();
    const GeoTemplate* geo_template = template_by_key(spec->template_key);
    return geo_template ? geo_template->field_defaults() : Json::object();
}

std::optional<std::string> CompositeEditController::apply_capture_spec(
    const std::string& layer_id) {
    const GeologicalCaptureSpec* spec =
        capture_spec_for_role(role_of_layer(layer_id));
    if (spec == nullptr) return std::nullopt;
    auto summary = snapping_.apply_role_profile(layer_id, spec->role);
    push_snapping_config();
    std::string hint = summary.value_or("");
    if (spec->recommend_topological_editing && !topology_.enabled) {
        hint += hint.empty() ? "建议开启拓扑编辑"
                             : "；建议开启拓扑编辑（相带拼接共享节点）";
    }
    if (hint.empty()) return std::nullopt;
    return hint;
}

// ---------------------------------------------------------------------------
// 画布绑定
// ---------------------------------------------------------------------------

void CompositeEditController::attach_canvas(
    const CompositeCanvasHooks& canvas) {
    canvas_ = canvas;
    push_snapping_config();
    push_native_edit_toggles();
}

// ---------------------------------------------------------------------------
// 图层 CRUD
// ---------------------------------------------------------------------------

std::vector<std::string> CompositeEditController::layer_ids() const {
    std::vector<std::string> ids;
    ids.reserve(layers_.size());
    for (const auto& [id, _] : layers_) ids.push_back(id);
    return ids;
}

VectorLayer* CompositeEditController::layer(const std::string& layer_id) {
    auto it = layers_.find(layer_id);
    return it == layers_.end() ? nullptr : it->second.get();
}
const VectorLayer* CompositeEditController::layer(
    const std::string& layer_id) const {
    auto it = layers_.find(layer_id);
    return it == layers_.end() ? nullptr : it->second.get();
}

std::string CompositeEditController::kind_of(
    const std::string& layer_id) const {
    auto it = kinds_.find(layer_id);
    return it == kinds_.end() ? "" : it->second;
}

bool CompositeEditController::is_composite_layer(
    const std::string& layer_id) {
    return layer_id.rfind(composite_layer_id_prefix(), 0) == 0;
}

VectorLayer& CompositeEditController::create_layer(
    const std::string& name, const std::string& kind_in,
    const std::string& template_key, const std::string& role) {
    std::string kind = kind_in;
    // Python parity: kind validated against GEOMETRY_KINDS before
    // template resolution (create_layer raises ValueError upfront).
    if (kind != "point" && kind != "line" && kind != "polygon")
        throw std::invalid_argument("unsupported geometry kind");
    const GeoTemplate* geo_template = template_by_key(template_key);
    Json schema = Json::object();
    Json style;
    std::string resolved_template;
    std::string resolved_name = name;
    if (geo_template != nullptr) {
        kind = geo_template->kind;
        style = geo_template->style.to_dict();
        schema = fields_to_schema(geo_template->fields);
        resolved_template = template_key;
        if (resolved_name.find_first_not_of(" \t\r\n") ==
            std::string::npos)
            resolved_name = geo_template->label;
    } else {
        style = default_style_for(kind_style_preset().at(kind)).to_dict();
    }
    std::string layer_id = composite_layer_id_prefix() +
                           ui_data_core::new_feature_id("layer");
    auto layer = std::make_unique<VectorLayer>(
        layer_id,
        resolved_name.empty()
            ? "编修图层 " + std::to_string(layers_.size() + 1)
            : resolved_name,
        project_crs, "", schema, std::vector<VectorFeature>{}, style);
    VectorLayer* out = layer.get();
    layers_[layer_id] = std::move(layer);
    kinds_[layer_id] = kind;
    templates_[layer_id] = resolved_template;
    schemas_[layer_id] = schema;
    std::string role_value = normalize_layer_role(role);
    if (!role_value.empty()) layer_roles_[layer_id] = role_value;
    // V10 M-G（D4 修复）：新建层经 set_active_layer 走完整链。
    set_active_layer(layer_id);
    push_snapping_config();
    emit(events.layers_changed);
    emit(events.state_changed);
    return *out;
}

void CompositeEditController::rename_layer(const std::string& layer_id,
                                           const std::string& name_in) {
    VectorLayer* lyr = layer(layer_id);
    std::string name = normalize_layer_role(name_in);
    if (lyr == nullptr || name.empty() || lyr->name() == name) return;
    lyr->set_name(name);
    emit(events.layers_changed);
}

std::string CompositeEditController::layer_template(
    const std::string& layer_id) const {
    auto it = templates_.find(layer_id);
    return it == templates_.end() ? "" : it->second;
}

Json CompositeEditController::layer_schema(
    const std::string& layer_id) const {
    const VectorLayer* lyr = layer(layer_id);
    if (lyr != nullptr && lyr->schema().is_object() &&
        !lyr->schema().empty())
        return lyr->schema();
    auto it = schemas_.find(layer_id);
    return it == schemas_.end() ? Json::object() : it->second;
}

std::string CompositeEditController::layer_role(
    const std::string& layer_id) const {
    auto it = layer_roles_.find(layer_id);
    return it == layer_roles_.end() ? "" : it->second;
}

void CompositeEditController::set_snapping_scope(bool current_layer_only) {
    snapping_.current_layer_only = current_layer_only;
    push_snapping_config();
    emit(events.state_changed);
}

std::pair<bool, std::string> CompositeEditController::apply_render_preset(
    const std::string& layer_id) {
    VectorLayer* lyr = layer(layer_id);
    if (lyr == nullptr) return {false, "图层不存在"};
    const GeoTemplate* geo_template =
        template_by_key(layer_template(layer_id));
    VectorStyle preset;
    if (geo_template != nullptr) {
        preset = geo_template->style;
    } else {
        std::string kind = kind_of(layer_id);
        auto it = kind_style_preset().find(kind);
        preset = default_style_for(it == kind_style_preset().end()
                                       ? "facies"
                                       : it->second);
    }
    set_layer_style(layer_id, preset.to_dict());
    return {true, ""};
}

void CompositeEditController::set_layer_style(const std::string& layer_id,
                                              const Json& style) {
    VectorLayer* lyr = layer(layer_id);
    if (lyr == nullptr) return;
    lyr->set_style(style);
    lyr->style_revision += 1;
    emit(events.layers_changed);
    emit(events.state_changed);
}

VectorLayer* CompositeEditController::duplicate_layer(
    const std::string& layer_id_in, bool notify) {
    VectorLayer* source = layer(layer_id_in);
    if (source == nullptr) return nullptr;
    std::string kind = kind_of(layer_id_in).empty()
                           ? "line"
                           : kind_of(layer_id_in);
    std::string new_id = composite_layer_id_prefix() +
                         ui_data_core::new_feature_id("layer");
    VectorEditSession* session = source->edit_session();
    std::vector<VectorFeature> origin =
        session ? session->features() : source->features();
    std::vector<VectorFeature> copies;
    copies.reserve(origin.size());
    for (const auto& f : origin) {
        copies.emplace_back(ui_data_core::new_feature_id("copy"),
                            f.geometry, f.attributes);
    }
    auto copy = std::make_unique<VectorLayer>(
        new_id, source->name() + " 副本", source->crs(), "",
        source->schema(), std::move(copies), source->style());
    copy->style_revision = source->style_revision + 1;
    VectorLayer* out = copy.get();
    layers_[new_id] = std::move(copy);
    kinds_[new_id] = kind;
    templates_[new_id] = layer_template(layer_id_in);
    schemas_[new_id] = source->schema();
    std::string source_role = layer_role(layer_id_in);
    if (!source_role.empty()) layer_roles_[new_id] = source_role;
    set_active_layer(new_id);
    if (notify) {
        emit(events.layers_changed);
        emit(events.state_changed);
    }
    return out;
}

void CompositeEditController::remove_layer(const std::string& layer_id) {
    auto it = layers_.find(layer_id);
    if (it == layers_.end()) return;
    if (it->second->edit_session() != nullptr)
        it->second->edit_session()->rollback_changes();
    topology_.forget_error_count({layer_id});
    layers_.erase(it);
    kinds_.erase(layer_id);
    templates_.erase(layer_id);
    schemas_.erase(layer_id);
    layer_roles_.erase(layer_id);
    display_.erase(layer_id);
    snapping_.layer_enabled.erase(layer_id);
    snapping_.layer_modes.erase(layer_id);
    snapping_.layer_tolerance.erase(layer_id);
    snapping_.layer_priority.erase(layer_id);
    push_snapping_config();
    records_cache_.erase(layer_id);
    persist_cache_.erase(layer_id);
    if (active_layer_id_ == layer_id) {
        set_active_layer(layers_.empty()
                             ? std::nullopt
                             : std::optional<std::string>(
                                   layers_.begin()->first));
    }
    emit(events.layers_changed);
    emit(events.state_changed);
}

// ---------------------------------------------------------------------------
// 工程持久化
// ---------------------------------------------------------------------------

bool CompositeEditController::load_from_project(
    const std::vector<Json>& user_vector_layers,
    const Json& mapping_workspace, const Json& workarea_boundary) {
    auto [committed, blocked] = flush_edit_sessions();
    (void)committed;
    bool remaining = false;
    for (const auto& [_, lyr] : layers_)
        if (lyr->edit_session() != nullptr) remaining = true;
    if (remaining ||
        (native_editing_ && !native_editing_->session_layer_ids().empty()))
        return false;
    layers_.clear();
    kinds_.clear();
    templates_.clear();
    schemas_.clear();
    layer_roles_.clear();
    display_.clear();
    records_cache_.clear();
    persist_cache_.clear();
    snapping_.layer_enabled.clear();
    snapping_.layer_modes.clear();
    snapping_.layer_tolerance.clear();
    snapping_.layer_priority.clear();
    topology_.forget_all_error_counts();
    active_layer_id_.reset();

    for (const Json& record : user_vector_layers) {
        if (!record.is_object()) continue;
        std::string kind = record.value("geometry_kind", "");
        if (kind != "point" && kind != "line" && kind != "polygon")
            kind = "line";
        std::vector<VectorFeature> features;
        for (const Json& item : record.value("features", Json::array())) {
            Json geometry = item.value("geometry", Json());
            if (!geometry.is_object() || !geometry.contains("type"))
                continue;
            features.emplace_back(
                item.value("id", ""), geometry,
                item.value("properties", Json::object()));
        }
        std::string template_key = record.value("template", "");
        const GeoTemplate* geo_template = template_by_key(template_key);
        Json style = record.value("style", Json::object());
        if (style.is_null() || (style.is_object() && style.empty())) {
            auto preset = kind_style_preset().find(kind);
            style = geo_template
                        ? geo_template->style.to_dict()
                        : default_style_for(preset->second).to_dict();
        }
        Json schema = record.value("field_schema", Json::object());
        if ((schema.is_null() || (schema.is_object() && schema.empty())) &&
            geo_template != nullptr)
            schema = fields_to_schema(geo_template->fields);
        std::string layer_id = record.value("id", "");
        auto lyr = std::make_unique<VectorLayer>(
            layer_id, record.value("name", "编修图层"),
            record.value("crs", "").empty() ? project_crs
                                           : record.value("crs", ""),
            "", schema, std::move(features), style);
        layers_[layer_id] = std::move(lyr);
        kinds_[layer_id] = kind;
        templates_[layer_id] = template_key;
        schemas_[layer_id] = schema;
        display_[layer_id] = {record.value("visible", true),
                              record.value("opacity", 1.0) <= 0.0
                                  ? 1.0
                                  : record.value("opacity", 1.0)};
    }
    // 科学角色随层恢复（mapping_workspace.memberships 权威）。
    Json memberships = mapping_workspace.is_object()
                           ? mapping_workspace.value("memberships",
                                                     Json::object())
                           : Json::object();
    for (const auto& [layer_id, _] : layers_) {
        std::string role_value;
        if (memberships.is_object() && memberships.contains(layer_id) &&
            memberships[layer_id].is_object())
            role_value = normalize_layer_role(
                memberships[layer_id].value("role", ""));
        if (!role_value.empty()) layer_roles_[layer_id] = role_value;
    }
    if (!layers_.empty()) active_layer_id_ = layers_.begin()->first;
    rebind_active_tool();
    try {
        snapping_.restore_state(mapping_workspace.is_object()
                                    ? mapping_workspace.value("snapping",
                                                              Json::object())
                                    : Json::object());
    } catch (const std::exception&) {
    }
    Json topo = mapping_workspace.is_object()
                    ? mapping_workspace.value("topo_editing", Json::object())
                    : Json::object();
    vertex_all_layers = topo.value("vertex_all_layers", true);
    avoid_intersections_enabled = topo.value("avoid_intersections", true);
    tracing_enabled = topo.value("tracing", false);
    try {
        topology_.checker().restore_state(
            mapping_workspace.is_object()
                ? mapping_workspace.value("topo_checker", Json::object())
                : Json::object());
    } catch (const std::exception&) {
    }
    // _sync_checker_workspace parity: workarea boundary → checker margin.
    if (workarea_boundary.is_array() && workarea_boundary.size() >= 3) {
        Json ring = Json::array();
        for (const Json& pt : workarea_boundary) {
            if (pt.is_array() && pt.size() >= 2)
                ring.push_back(Json::array({pt[0], pt[1]}));
        }
        if (ring.size() >= 3) {
            if (ring.front() != ring.back()) ring.push_back(ring.front());
            topology_.checker().workspace = {
                {"type", "Polygon"}, {"coordinates", {ring}}};
        }
    }
    push_snapping_config();
    emit(events.layers_changed);
    emit(events.state_changed);
    return true;
}

std::vector<Json> CompositeEditController::sync_to_project(
    Json& mapping_workspace) const {
    std::vector<Json> records;
    for (const auto& [layer_id, lyr] : layers_) {
        auto disp = display_.find(layer_id);
        bool visible = disp == display_.end() ? true : disp->second.first;
        double opacity =
            disp == display_.end() ? 1.0 : disp->second.second;
        auto cached = persist_cache_.find(layer_id);
        std::vector<Json> persisted;
        if (cached != persist_cache_.end() &&
            cached->second.first == lyr->data_revision) {
            persisted = cached->second.second;
        } else {
            for (const auto& f : lyr->features()) {
                persisted.push_back({{"id", f.feature_id},
                                     {"geometry", f.geometry},
                                     {"properties", f.attributes}});
            }
            persist_cache_[layer_id] = {lyr->data_revision, persisted};
        }
        Json features = Json::array();
        for (auto& f : persisted) features.push_back(f);
        records.push_back(
            {{"id", lyr->id()},
             {"name", lyr->name()},
             {"geometry_kind", kind_of(layer_id).empty()
                                    ? "line"
                                    : kind_of(layer_id)},
             {"template", layer_template(layer_id)},
             {"crs", lyr->crs()},
             {"style", lyr->style()},
             {"field_schema",
              lyr->schema().is_object() && !lyr->schema().empty()
                  ? lyr->schema()
                  : layer_schema(layer_id)},
             {"features", features},
             {"visible", visible},
             {"opacity", opacity}});
    }
    try {
        mapping_workspace["snapping"] = snapping_.snapshot_state();
        mapping_workspace["topo_editing"] = {
            {"vertex_all_layers", vertex_all_layers},
            {"avoid_intersections", avoid_intersections_enabled},
            {"tracing", tracing_enabled}};
        mapping_workspace["topo_checker"] = topology_.checker().persist();
    } catch (const std::exception&) {
    }
    return records;
}

// ---------------------------------------------------------------------------
// 活动图层与编辑会话
// ---------------------------------------------------------------------------

VectorLayer* CompositeEditController::active_layer() {
    if (!active_layer_id_) return nullptr;
    return layer(*active_layer_id_);
}

std::optional<std::string> CompositeEditController::topmost_visible_layer_id()
    const {
    std::set<std::string> visible;
    for (const auto& [id, _] : layers_) {
        auto it = display_.find(id);
        if (it == display_.end() || it->second.first) visible.insert(id);
    }
    return pick_topmost_visible_layer_id(layer_ids(), visible);
}

std::vector<Json> CompositeEditController::gate_topology_issues(
    const VectorLayer& layer) {
    // M4：原生会话走桥检查器，Python 会话校验工作副本。
    if (layer.edit_session() != nullptr) {
        std::vector<Json> issues = topology_.validate({&layer});
        issues = topology_.checker().blocking_errors(issues);
        return issues;
    }
    if (native_editing_ && native_editing_->is_open(layer.id())) {
        // Bridge checker via checker.run_for_commit seam.
        try {
            return topology_.checker().run_for_commit({layer.id()});
        } catch (const std::exception&) {
        }
    }
    return topology_.validate({&layer});
}

std::vector<Json> CompositeEditController::run_topology_checks() {
    std::vector<std::string> ids;
    if (native_editing_)
        ids = native_editing_->session_layer_ids();
    if (ids.empty()) {
        for (const auto& [id, lyr] : layers_)
            if (lyr->edit_session() != nullptr) ids.push_back(id);
    }
    if (ids.empty() && active_layer() != nullptr)
        ids.push_back(active_layer()->id());
    // Bridge seam: when the checker has a run fn it owns the full run
    // (含已忽略) and refreshes last_errors.
    try {
        return topology_.checker().run(ids);
    } catch (const std::exception&) {
    }
    std::vector<Json> issues;
    for (const auto& layer_id : ids) {
        const VectorLayer* lyr = layer(layer_id);
        if (lyr == nullptr) continue;
        auto found = topology_.validate({lyr});
        issues.insert(issues.end(), found.begin(), found.end());
    }
    topology_.checker().last_errors = issues;
    return issues;
}

bool CompositeEditController::editing() const {
    const VectorLayer* lyr =
        active_layer_id_ ? layer(*active_layer_id_) : nullptr;
    if (lyr == nullptr) return false;
    return lyr->edit_session() != nullptr ||
           (native_editing_ && native_editing_->is_open(lyr->id()));
}

std::string CompositeEditController::current_canvas_layer_id() const {
    if (!canvas_.current_layer_doc_id) return "";
    try {
        return canvas_.current_layer_doc_id();
    } catch (const std::exception&) {
        return "";
    }
}

bool CompositeEditController::repush_canvas_current_layer() {
    if (!active_layer_id_ || !canvas_.set_current_layer) return false;
    if (current_canvas_layer_id() == *active_layer_id_) return false;
    try {
        canvas_.set_current_layer(*active_layer_id_);
    } catch (const std::exception&) {
        return false;
    }
    return true;
}

void CompositeEditController::set_active_layer(
    const std::optional<std::string>& layer_id_in) {
    std::optional<std::string> layer_id = layer_id_in;
    if (layer_id.has_value() && layers_.find(*layer_id) == layers_.end())
        layer_id.reset();
    if (layer_id == active_layer_id_) {
        repush_canvas_current_layer();
        return;
    }
    VectorLayer* previous = active_layer();
    if (previous != nullptr && previous->edit_session() != nullptr)
        retire_session_on_target_switch(*previous);
    active_layer_id_ = layer_id;
    rebind_active_tool();
    if (canvas_.set_current_layer) {
        try {
            canvas_.set_current_layer(layer_id.value_or(""));
        } catch (const std::exception&) {
        }
    }
    emit(events.state_changed);
}

void CompositeEditController::retire_session_on_target_switch(
    VectorLayer& previous) {
    VectorEditSession* session = previous.edit_session();
    if (session == nullptr) return;
    MapTool* active = tools.active_tool();
    auto* bound = dynamic_cast<CaptureTool*>(active);
    VectorEditSession* held = bound ? bound->session : nullptr;
    if (held == nullptr) {
        if (auto* mv = dynamic_cast<MoveFeatureTool*>(active))
            held = mv->session;
        if (auto* vt = dynamic_cast<VertexTool*>(active))
            held = vt->session;
        if (auto* rt = dynamic_cast<ReshapeTool*>(active))
            held = rt->session;
        if (auto* rc = dynamic_cast<RingCaptureTool*>(active))
            held = rc->session;
        if (auto* pc = dynamic_cast<PartCaptureTool*>(active))
            held = pc->session;
    }
    if (held != session) {
        last_switch_block_reason_.reset();
        return;
    }
    last_switch_block_reason_ = {
        previous.id(),
        "数字化进行中：捕获目标保持为「" + previous.name() +
            "」（编辑目标与会话锁定直至手势完成）"};
}

std::map<std::string, std::tuple<int64_t, int64_t, std::set<std::string>>>
CompositeEditController::snapshot_changed_hints() const {
    return changed_hints_;
}

void CompositeEditController::note_tree_selection(
    const std::optional<std::string>& node_id) {
    tree_selection_ = node_id;
}

EditTargetSnapshot CompositeEditController::edit_targets() const {
    const MapTool* active = tools.active_tool();
    const VectorEditSession* session = nullptr;
    if (auto* t = dynamic_cast<const CaptureTool*>(active))
        session = t->session;
    else if (auto* t = dynamic_cast<const MoveFeatureTool*>(active))
        session = t->session;
    else if (auto* t = dynamic_cast<const VertexTool*>(active))
        session = t->session;
    else if (auto* t = dynamic_cast<const ReshapeTool*>(active))
        session = t->session;
    else if (auto* t = dynamic_cast<const RingCaptureTool*>(active))
        session = t->session;
    else if (auto* t = dynamic_cast<const PartCaptureTool*>(active))
        session = t->session;
    std::optional<std::string> tool_target;
    if (session != nullptr) {
        for (const auto& [id, lyr] : layers_) {
            if (lyr->edit_session() == session) {
                tool_target = id;
                break;
            }
        }
    }
    std::optional<std::string> target =
        tool_target.has_value() ? tool_target : active_layer_id_;
    return EditTargetSnapshot{tree_selection_, active_layer_id_, target,
                              target, active_layer_id_};
}

void CompositeEditController::start_editing() {
    VectorLayer* lyr = active_layer();
    if (lyr == nullptr || lyr->edit_session() != nullptr) return;
    if (native_editing_ && native_editing_->is_open(lyr->id())) return;
    auto [allowed, _reason] = can_edit_layer(lyr->id());
    if (!allowed) return;
    auto [ok_crs, _crs_reason] = crs_domain_gate(*lyr);
    if (!ok_crs) return;
    if (native_session_eligible(*lyr)) {
        auto [ok, reason] = native_editing_->open(
            lyr->id(),
            [this](const std::string& id) { return can_edit_layer(id); });
        if (ok) {
            repush_canvas_current_layer();
            rebind_active_tool();
            emit(events.state_changed);
            return;
        }
        // 原生会话开启失败 → 回落 Python 会话（warning logged upstream）。
    }
    open_session(*lyr);
    rebind_active_tool();
    emit(events.state_changed);
}

bool CompositeEditController::native_session_eligible(
    const VectorLayer& layer) {
    if (native_editing_ == nullptr || !native_editing_->bridge_supports())
        return false;
    if (!canvas_.canvas_address) return false;  // 回退画布无原生面
    std::string kind = kind_of(layer.id());
    if (kind == "polygon" || kind == "line") return true;
    if (kind == "point") {
        std::string role = layer_role(layer.id());
        return role == "map_annotation" || role == "interpretation_annotation";
    }
    return false;
}

std::pair<VectorEditSession*, std::string>
CompositeEditController::ensure_layer_session(const std::string& layer_id) {
    VectorLayer* lyr = layer(layer_id);
    if (lyr == nullptr) return {nullptr, "图层不存在"};
    if (native_editing_ && native_editing_->is_open(lyr->id()))
        return {nullptr, "该图层处于原生编辑会话——请先保存或回滚编辑"};
    auto [allowed, reason] = can_edit_layer(lyr->id());
    if (!allowed) return {nullptr, reason};
    if (lyr->edit_session() == nullptr) {
        auto [ok_crs, crs_reason] = crs_domain_gate(*lyr);
        if (!ok_crs) return {nullptr, crs_reason};
        open_session(*lyr);
        emit(events.state_changed);
    }
    return {lyr->edit_session(), ""};
}

std::pair<bool, std::string> CompositeEditController::crs_domain_gate(
    const VectorLayer& layer) {
    std::string declared = layer.crs();
    CrsDomainCheck check = validate_crs_domain(
        declared, feature_bounds(iter_layer_coords(layer)));
    last_crs_gate_check_ = check;
    if (check.ok) return {true, ""};
    return {false, check.reason};
}

bool CompositeEditController::apply_crs_fix(const std::string& layer_id,
                                            const std::string& mode) {
    VectorLayer* lyr = layer(layer_id);
    if (lyr == nullptr || (mode != "declare_local" && mode != "clear"))
        return false;
    lyr->set_crs("");
    last_crs_gate_check_.reset();
    emit(events.state_changed);
    return true;
}

std::pair<bool, std::string> CompositeEditController::apply_project_crs(
    const std::string& crs_in) {
    std::string crs = crs_in;
    if (crs.empty() || crs == project_crs) return {true, ""};
    for (const auto& [_, lyr] : layers_) {
        if (lyr->edit_session() != nullptr)
            return {false,
                    "编辑会话进行中：CRS 声明被冻结（先保存或回滚）"};
    }
    project_crs = crs;
    return {true, ""};
}

std::set<std::string> CompositeEditController::facies_field_names(
    const std::string& layer_id) const {
    if (native_editing_ && native_editing_->is_open(layer_id)) {
        try {
            Json payload = native_editing_->mirror_layer_schema(layer_id);
            std::set<std::string> names;
            if (payload.is_object()) {
                for (const Json& field :
                     payload.value("fields", Json::array())) {
                    if (field.is_object()) {
                        std::string n = field.value("name", "");
                        if (!n.empty()) names.insert(n);
                    }
                }
            }
            if (!names.empty()) return names;
        } catch (const std::exception&) {
        }
    }
    std::set<std::string> names;
    Json schema = layer_schema(layer_id);
    if (schema.is_object()) {
        for (const Json& field : schema.value("fields", Json::array())) {
            if (field.is_object()) {
                std::string n = field.value("name", "");
                if (!n.empty()) names.insert(n);
            }
        }
    }
    const VectorLayer* lyr = layer(layer_id);
    if (lyr != nullptr) {
        for (const auto& f : lyr->features()) {
            if (f.attributes.is_object()) {
                for (auto it = f.attributes.begin();
                     it != f.attributes.end(); ++it)
                    names.insert(it.key());
            }
        }
    }
    return names;
}

std::pair<bool, std::string> CompositeEditController::apply_facies_selection(
    const std::string& layer_id,
    const std::vector<std::string>& feature_ids, const Json& selection) {
    // facies_taxonomy FACIES_LEVEL_KEYS / selection_level /
    // resolve_facies_field parity.
    static const std::vector<std::string> level_keys = {
        "facies", "sub_facies", "micro_facies"};
    std::vector<std::string> ids;
    for (const auto& fid : feature_ids)
        if (!fid.empty()) ids.push_back(fid);
    if (ids.empty()) return {false, "没有要修改的要素"};

    // selection_level: deepest level with a non-empty selection value.
    std::string level = "facies";
    if (!selection.value("micro_facies", "").empty())
        level = "micro_facies";
    else if (!selection.value("sub_facies", "").empty())
        level = "sub_facies";
    std::map<std::string, Json> values = {
        {"facies", selection.value("facies", "")},
        {"sub_facies", selection.value("sub_facies", "")},
        {"micro_facies", selection.value("micro_facies", "")},
        {"level", level}};
    std::set<std::string> available = facies_field_names(layer_id);
    Json payload = Json::object();
    // resolve_facies_field(level, available): "facies" accepts "facies" or
    // "facies_name"; sub/micro map onto their own key or a suffixed
    // variant — keep the same candidate order as Python.
    auto resolve = [&available](const std::string& key) -> std::string {
        static const std::map<std::string, std::vector<std::string>>
            candidates = {
                {"facies", {"facies", "facies_name"}},
                {"sub_facies", {"sub_facies", "subfacies"}},
                {"micro_facies", {"micro_facies", "microfacies"}}};
        auto it = candidates.find(key);
        if (it == candidates.end()) return "";
        for (const auto& cand : it->second)
            if (available.count(cand)) return cand;
        return "";
    };
    for (const auto& key : level_keys) {
        std::string field = resolve(key);
        if (!field.empty()) payload[field] = values[key];
    }
    if (available.count("level")) payload["level"] = values["level"];
    if (payload.empty())
        return {false,
                "图层缺少相字段（facies/facies_name）——请在图层属性中补齐字段"};
    if (native_editing_ && native_editing_->is_open(layer_id)) {
        auto [ok, reason] =
            native_editing_->set_feature_attributes(layer_id, ids, payload);
        if (ok) emit(events.content_changed, layer_id);
        return {ok, reason};
    }
    auto [session, reason] = ensure_layer_session(layer_id);
    if (session == nullptr) return {false, reason};
    // R2-28: begin OUTSIDE the try (a nested-begin throw must not destroy
    // an outer command in our catch).
    session->begin_edit_command();
    try {
        for (const auto& fid : ids)
            for (auto it = payload.begin(); it != payload.end(); ++it)
                session->change_attribute(fid, it.key(), it.value());
    } catch (const std::exception& exc) {
        session->destroy_edit_command();
        return {false, exc.what()};
    }
    session->end_edit_command();
    emit(events.content_changed, layer_id);
    return {true, ""};
}

void CompositeEditController::import_layer_features(
    const std::string& layer_id,
    const std::vector<VectorFeature>& features) {
    VectorLayer* lyr = layer(layer_id);
    if (lyr == nullptr || features.empty()) return;
    VectorEditSession& session = open_session(*lyr);
    try {
        auto guard = session.edit_source("domain_import");
        for (const auto& f : features) session.add_feature(f);
    } catch (...) {
        session.rollback_changes();
        emit(events.state_changed);
        throw;
    }
    session.commit_changes();
    emit(events.content_changed, layer_id);
}

std::optional<std::string> CompositeEditController::save_edits() {
    VectorLayer* lyr = active_layer();
    if (lyr == nullptr || lyr->edit_session() == nullptr) {
        if (lyr == nullptr ||
            !(native_editing_ && native_editing_->is_open(lyr->id())))
            return std::nullopt;
        return commit_native_sessions();
    }
    if (topology_.enabled) {
        std::vector<Json> issues = gate_topology_issues(*lyr);
        topology_.record_validation(*lyr, static_cast<int>(issues.size()));
        if (!issues.empty()) {
            std::string details;
            size_t shown = std::min<size_t>(3, issues.size());
            for (size_t i = 0; i < shown; ++i) {
                if (i) details += "；";
                details += issues[i].value("feature_id", "") + "：" +
                           issues[i].value("message", "");
            }
            std::string more =
                issues.size() > 3
                    ? "（另有 " + std::to_string(issues.size() - 3) +
                          " 个问题）"
                    : "";
            return "图层「" + lyr->name() + "」" +
                   std::to_string(issues.size()) +
                   " 个要素未通过拓扑检查：" + details + more;
        }
    }
    lyr->edit_session()->commit_changes();
    emit(events.content_changed, lyr->id());
    rebind_active_tool();
    emit(events.sessions_committed);
    emit(events.state_changed);
    return std::nullopt;
}

std::optional<std::string> CompositeEditController::commit_native_sessions() {
    if (native_editing_ == nullptr) return std::nullopt;
    std::vector<Json> violations;
    if (geology_gate_enabled())
        violations = collect_geology_violations();
    std::vector<Json> errors;
    for (const Json& v : violations)
        if (v.value("severity", "error") == "error") errors.push_back(v);
    if (!errors.empty()) {
        Json all = violations;
        emit(events.geology_blocked, all);
        return "地质不变量校验未通过：" + errors[0].value("code", "") + "：" +
               errors[0].value("message", "") + "（全部编辑未提交）";
    }
    auto [ok, reason] = native_editing_->commit_all(
        [this](const std::string& id) { return can_edit_layer(id); },
        topology_,
        geology_gate_enabled()
            ? std::function<Json(const Json&)>(
                  [this](const Json& records) {
                      Json out = Json::array();
                      for (const Json& v :
                           collect_geology_violations(records))
                          out.push_back(v);
                      return out;
                  })
            : std::function<Json(const Json&)>(nullptr),
        [this](const std::string& layer_id) {
            VectorLayer* lyr = layer(layer_id);
            if (lyr) on_native_committed(*lyr);
        });
    if (!ok) return reason;
    std::vector<Json> warnings;
    for (const Json& v : violations)
        if (v.value("severity", "error") == "warning") warnings.push_back(v);
    if (!warnings.empty()) {
        Json w = warnings;
        emit(events.geology_blocked, w);
    }
    rebind_active_tool();
    emit(events.sessions_committed);
    emit(events.state_changed);
    return std::nullopt;
}

bool CompositeEditController::geology_gate_enabled() const {
    return topology_.enabled;
}

std::vector<Json> CompositeEditController::collect_geology_violations(
    const std::optional<Json>& records_opt) {
    std::vector<Json> empty;
    if (!geology_gate_ || native_editing_ == nullptr) return empty;
    Json records = Json::object();
    if (records_opt.has_value()) {
        records = *records_opt;
    } else {
        for (const auto& layer_id : native_editing_->session_layer_ids()) {
            try {
                Json feats = Json::array();
                for (const Json& f :
                     native_editing_->readback_features(layer_id))
                    feats.push_back(f);
                records[layer_id] = feats;
            } catch (const std::exception&) {
                records[layer_id] = Json::array();
            }
        }
    }
    if (records.is_object() && records.empty()) return empty;
    static const std::map<std::string, std::string> geology_role_map = {
        {"fault_constraint", "fault_line"},
        {"factor_contour", "isopath_line"}};
    std::map<std::string, std::vector<Json>> recs;
    std::map<std::string, std::string> roles;
    if (records.is_object()) {
        for (auto it = records.begin(); it != records.end(); ++it) {
            std::vector<Json> feats;
            if (it.value().is_array())
                feats.assign(it.value().begin(), it.value().end());
            recs[it.key()] = feats;
            auto role_it = layer_roles_.find(it.key());
            std::string lr = role_it == layer_roles_.end()
                                 ? ""
                                 : role_it->second;
            auto g_it = geology_role_map.find(lr);
            roles[it.key()] =
                g_it == geology_role_map.end() ? "" : g_it->second;
        }
    }
    try {
        Json violations = geology_gate_(recs, roles);
        if (violations.is_array())
            return std::vector<Json>(violations.begin(), violations.end());
    } catch (const std::exception&) {
        // 守卫自身异常不阻塞提交主链。
    }
    return empty;
}

void CompositeEditController::on_native_committed(VectorLayer& layer) {
    if (native_editing_) {
        std::map<std::string, std::string> metadata;
        auto it = layer_roles_.find(layer.id());
        if (it != layer_roles_.end()) metadata["role"] = it->second;
        try {
            native_editing_->align_publish_ledger(layer.id(), metadata);
        } catch (const std::exception&) {
        }
    }
    emit(events.content_changed, layer.id());
}

bool CompositeEditController::commit_native_capture(const Json& geometry) {
    VectorLayer* lyr = active_layer();
    if (lyr == nullptr || native_editing_ == nullptr ||
        !native_editing_->is_open(lyr->id()))
        return false;
    if (pending_native_split_.has_value())
        return commit_native_split(geometry);
    std::string host_id = ui_data_core::new_feature_id("feature");
    Json feature = {{"type", "Feature"},
                    {"geometry", geometry},
                    {"properties", {{"__pwb_fid", host_id}}}};
    std::string error;
    try {
        error = native_editing_->add_mirror_feature(lyr->id(), feature);
    } catch (const std::exception& exc) {
        error = exc.what();
    }
    if (!error.empty()) return false;
    native_editing_->finish_gesture(
        ui_data_core::new_feature_id("gesture"), "Added feature",
        {lyr->id()});
    if (facies_template_keys().count(layer_template(lyr->id())))
        emit(events.feature_captured, lyr->id(), host_id);
    return true;
}

void CompositeEditController::cancel_native_capture() {
    pending_native_split_.reset();
}

void CompositeEditController::join_native_layers(
    const std::vector<std::string>& doc_ids) {
    if (native_editing_ == nullptr) return;
    std::vector<std::string> refused;
    for (const auto& doc_id : doc_ids) {
        if (native_editing_->is_open(doc_id)) continue;
        VectorLayer* lyr = layer(doc_id);
        if (lyr == nullptr) {
            refused.push_back(doc_id + "（图层不存在）");
            continue;
        }
        auto [ok, reason] = native_editing_->open(
            doc_id, [this](const std::string& id) {
                return can_edit_layer(id);
            });
        if (!ok) refused.push_back("「" + lyr->name() + "」" + reason);
    }
    repush_canvas_current_layer();
    if (!refused.empty()) {
        std::string msg = "邻层未参与编辑：";
        for (size_t i = 0; i < refused.size(); ++i) {
            if (i) msg += "；";
            msg += refused[i];
        }
        emit(events.native_join_refused, msg);
    }
    emit(events.state_changed);
}

void CompositeEditController::set_vertex_scope(bool all_layers) {
    vertex_all_layers = all_layers;
    push_native_edit_toggles();
}

void CompositeEditController::set_avoid_intersections(bool enabled) {
    avoid_intersections_enabled = enabled;
    push_snapping_config();
    emit(events.state_changed);
}

void CompositeEditController::set_tracing(bool enabled) {
    tracing_enabled = enabled;
    push_native_edit_toggles();
    emit(events.state_changed);
}

void CompositeEditController::push_native_edit_toggles() {
    if (canvas_.set_vertex_edit_scope) {
        try {
            canvas_.set_vertex_edit_scope(vertex_all_layers);
        } catch (const std::exception&) {
        }
    }
    if (canvas_.set_tracing_enabled) {
        try {
            canvas_.set_tracing_enabled(tracing_enabled);
        } catch (const std::exception&) {
        }
    }
}

void CompositeEditController::record_native_gesture(const Json& payload) {
    std::string gesture_id = payload.value(
        "gesture_id", ui_data_core::new_feature_id("g"));
    std::vector<std::string> layer_ids;
    for (const Json& doc : payload.value("layers", Json::array()))
        if (doc.is_string()) layer_ids.push_back(doc.get<std::string>());
    if (layer_ids.empty())
        layer_ids.push_back(payload.value("layer_doc_id", ""));
    if (compound_capture_.has_value()) {
        for (const auto& id : layer_ids)
            if (!id.empty()) compound_capture_layers_.push_back(id);
        return;
    }
    if (native_editing_)
        native_editing_->finish_gesture(
            gesture_id, payload.value("undo_text", ""), layer_ids);
}

void CompositeEditController::note_compound_layer(
    const std::string& layer_id) {
    if (compound_capture_.has_value() && !layer_id.empty())
        compound_capture_layers_.push_back(layer_id);
}

void CompositeEditController::begin_compound_macro(
    const std::string& undo_text) {
    if (compound_capture_.has_value()) return;  // 嵌套块并入外层宏
    compound_capture_ = Json::object();
    compound_capture_layers_.clear();
    compound_capture_undo_text_ = undo_text;
}

void CompositeEditController::end_compound_macro() {
    if (!compound_capture_.has_value()) return;
    auto layer_ids = std::move(compound_capture_layers_);
    std::string undo_text = std::move(compound_capture_undo_text_);
    compound_capture_.reset();
    compound_capture_layers_.clear();
    if (!layer_ids.empty() && native_editing_)
        native_editing_->finish_gesture(
            ui_data_core::new_feature_id("gesture"), undo_text, layer_ids);
}

void CompositeEditController::rollback_edits() {
    VectorLayer* lyr = active_layer();
    if (lyr == nullptr) return;
    if (lyr->edit_session() == nullptr && native_editing_ &&
        native_editing_->is_open(lyr->id())) {
        auto [ok, reason] = native_editing_->rollback(lyr->id());
        (void)ok;  // warning logged upstream on failure
        topology_.forget_error_count({lyr->id()});
        rebind_active_tool();
        emit(events.sessions_committed);
        emit(events.state_changed);
        return;
    }
    if (lyr->edit_session() == nullptr) return;
    lyr->edit_session()->rollback_changes();
    topology_.forget_error_count({lyr->id()});
    emit(events.content_changed, lyr->id());
    rebind_active_tool();
    emit(events.sessions_committed);
    emit(events.state_changed);
}

std::pair<int, std::vector<std::string>>
CompositeEditController::flush_edit_sessions() {
    std::vector<std::string> blocked;
    int committed = 0;
    // M1 原生会话整集合先行（§3 全或无）。
    if (native_editing_ && !native_editing_->session_layer_ids().empty()) {
        auto [ok, reason] = native_editing_->commit_all(
            [this](const std::string& id) { return can_edit_layer(id); },
            topology_, nullptr,
            [this](const std::string& layer_id) {
                VectorLayer* lyr = layer(layer_id);
                if (lyr) on_native_committed(*lyr);
            });
        if (ok) {
            committed += 1;
        } else {
            blocked.push_back(reason);
            return {0, blocked};
        }
    }
    // V11 M0（#1283 全或无）：两阶段——先判门禁，全过才逐层提交。
    std::vector<std::pair<VectorLayer*, VectorEditSession*>> pending;
    for (auto& [_, lyr] : layers_) {
        VectorEditSession* session = lyr->edit_session();
        if (session == nullptr) continue;
        bool allowed;
        std::string gate_reason;
        try {
            std::tie(allowed, gate_reason) = can_edit_layer(lyr->id());
        } catch (const std::exception& exc) {
            blocked.push_back("图层「" + lyr->name() +
                              "」门禁判定异常（该图层编辑未提交）: " +
                              exc.what());
            continue;
        }
        if (!allowed) {
            blocked.push_back("图层「" + lyr->name() + "」" + gate_reason +
                              "（该图层编辑未提交）");
            continue;
        }
        if (topology_.enabled) {
            std::vector<Json> issues;
            try {
                issues = gate_topology_issues(*lyr);
            } catch (const std::exception& exc) {
                blocked.push_back("图层「" + lyr->name() +
                                  "」拓扑校验异常（该图层编辑未提交）: " +
                                  exc.what());
                continue;
            }
            topology_.record_validation(*lyr,
                                        static_cast<int>(issues.size()));
            if (!issues.empty()) {
                const Json& first = issues.front();
                blocked.push_back(
                    "图层「" + lyr->name() + "」要素 " +
                    first.value("feature_id", "") +
                    " 未通过拓扑检查（该图层编辑未提交）：" +
                    first.value("message", ""));
                continue;
            }
        }
        pending.emplace_back(lyr.get(), session);
    }
    if (!blocked.empty()) return {committed, blocked};
    std::vector<std::string> committed_ids;
    for (size_t index = 0; index < pending.size(); ++index) {
        auto* lyr = pending[index].first;
        auto* session = pending[index].second;
        try {
            session->commit_changes();
        } catch (const std::exception&) {
            for (size_t j = index; j < pending.size(); ++j) {
                try {
                    pending[j].second->rollback_changes();
                } catch (const std::exception&) {
                }
                blocked.push_back("图层「" + pending[j].first->name() +
                                  "」提交失败已回滚");
            }
            if (!committed_ids.empty()) {
                std::string msg = "已提交图层（保留，未回滚）: ";
                for (size_t i = 0; i < committed_ids.size(); ++i) {
                    if (i) msg += "、";
                    msg += "「" + committed_ids[i] + "」";
                }
                blocked.push_back(msg);
            }
            break;
        }
        committed += 1;
        committed_ids.push_back(lyr->id());
        emit(events.content_changed, lyr->id());
    }
    if (committed) {
        rebind_active_tool();
        emit(events.sessions_committed);
        emit(events.state_changed);
    }
    return {committed, blocked};
}

// ---------------------------------------------------------------------------
// 会话开启 / appliers
// ---------------------------------------------------------------------------

VectorEditSession& CompositeEditController::open_session(
    VectorLayer& layer) {
    VectorEditSession* session = layer.edit_session();
    if (session == nullptr) session = &layer.start_editing();
    session->qgis_capability_token = qgis_capability_token;
    return *session;
}

std::function<bool(const Json&)>
CompositeEditController::make_reshape_applier(
    VectorEditSession* session, const std::string& feature_id) {
    if (feature_id.empty() || geometry_ops_ == nullptr) return nullptr;
    auto* ops = geometry_ops_.get();
    return [this, ops, session, feature_id](const Json& line) -> bool {
        if (session == nullptr) return false;
        try {
            const VectorFeature& feature = session->feature(feature_id);
            auto reshaped =
                ops->reshape(feature.as_record().value("geometry", Json()),
                             line);
            if (!reshaped.has_value()) return false;
            session->set_geometry(feature_id, *reshaped);
            emit(events.content_changed, session->layer.id());
            return true;
        } catch (const std::exception&) {
            return false;
        }
    };
}

bool CompositeEditController::apply_captured_ring(
    VectorEditSession* session, const std::string& feature_id,
    const Json& ring_geometry) {
    try {
        std::vector<MapPoint> ring;
        std::string gtype = ring_geometry.value("type", "");
        Json coords = ring_geometry.value("coordinates", Json());
        if (gtype == "Polygon" && coords.is_array() && !coords.empty()) {
            for (const Json& p : coords[0]) {
                auto pt = json_point(p);
                if (pt) ring.push_back(*pt);
            }
        } else if (gtype == "MultiPolygon" && coords.is_array() &&
                   !coords.empty() && coords[0].is_array() &&
                   !coords[0].empty()) {
            for (const Json& p : coords[0][0]) {
                auto pt = json_point(p);
                if (pt) ring.push_back(*pt);
            }
        }
        if (session == nullptr) return false;
        const VectorFeature& feature = session->feature(feature_id);
        Json exterior = feature.as_record()
                            .value("geometry", Json::object())
                            .value("coordinates", Json::array());
        MapRing exterior_ring;
        if (exterior.is_array() && !exterior.empty())
            exterior_ring = ui_data_core::ring_to_pts(exterior[0]);
        bool inside = false;
        for (const auto& p : ring) {
            if (point_in_ring_scalar(p[0], p[1], exterior_ring)) {
                inside = true;
                break;
            }
        }
        if (!inside) return false;
        session->add_ring(feature_id, ring);
        refresh_error_count_quiet(session->layer);
        emit(events.content_changed, session->layer.id());
        return true;
    } catch (const std::exception&) {
        return false;
    }
}

std::function<bool(const Json&)> CompositeEditController::make_part_applier(
    VectorEditSession* session, const std::string& feature_id) {
    if (geometry_ops_ == nullptr) return nullptr;
    auto* ops = geometry_ops_.get();
    return [this, ops, session, feature_id](const Json& part) -> bool {
        if (session == nullptr) return false;
        try {
            const VectorFeature& feature = session->feature(feature_id);
            auto merged =
                ops->add_part(feature.as_record().value("geometry", Json()),
                              part);
            if (!merged.has_value()) return false;
            session->add_part(feature_id, *merged);
            refresh_error_count_quiet(session->layer);
            emit(events.content_changed, session->layer.id());
            return true;
        } catch (const std::exception&) {
            return false;
        }
    };
}

bool CompositeEditController::apply_captured_part(
    VectorEditSession* session, const std::string& feature_id,
    const Json& part_geometry) {
    auto applier = make_part_applier(session, feature_id);
    return applier && applier(part_geometry);
}

void CompositeEditController::refresh_error_count_quiet(
    VectorLayer& layer) {
    try {
        topology_.refresh_error_count(layer);
    } catch (const std::exception&) {
        // 刷新绝不吞命令结果。
    }
}

// ---------------------------------------------------------------------------
// 工具装配
// ---------------------------------------------------------------------------

double CompositeEditController::tolerance() const {
    return snapping_.pixel_tolerance * canvas_.units_per_pixel();
}

MapPoint CompositeEditController::snap_point(const MapPoint& point) {
    std::vector<VectorLayer*> all;
    for (auto& [_, lyr] : layers_) all.push_back(lyr.get());
    return snapping_.snap(point, tolerance(), all,
                          canvas_.units_per_pixel());
}

void CompositeEditController::activate_tool(const std::string& action_id) {
    std::shared_ptr<MapTool> tool;
    if (action_id == "pan") {
        tool = std::make_shared<PanTool>();
    } else if (action_id == "zoom_in" || action_id == "zoom_out") {
        if (!canvas_.zoom_by) return;
        tool = std::make_shared<ZoomTool>(
            canvas_.zoom_by, action_id == "zoom_in" ? 0.5 : 2.0, action_id);
    } else if (action_id == "measure_distance") {
        tool = std::make_shared<MeasureDistanceTool>();
    } else {
        VectorLayer* lyr = active_layer();
        // V10 识别修复：identify 恒绑无层 IdentifyTool（delegate 缺席才
        // 回落带层 SelectTool）。
        if (action_id == "identify" && identify_delegate) {
            tool = std::make_shared<IdentifyTool>(identify_delegate);
            active_tool_action_ = action_id;
            tools.set_active_tool(tool);
            if (canvas_.focus) canvas_.focus();
            emit(events.state_changed);
            return;
        }
        if (lyr == nullptr && action_id == "identify") {
            auto fallback = topmost_visible_layer_id();
            if (fallback.has_value()) lyr = layer(*fallback);
        }
        if (lyr == nullptr) return;
        FeatureSpatialIndex& index = snapping_.index_for(lyr);
        if (action_id == "identify" || action_id == "select") {
            std::function<std::optional<std::string>(const MapPoint&)>
                identify_fn;
            if (action_id == "identify" && identify_delegate) {
                identify_fn = [this](const MapPoint& p) {
                    identify_delegate(p);
                    return std::optional<std::string>();
                };
            } else {
                double tol = tolerance();
                identify_fn = [&index, tol](const MapPoint& p) {
                    return index.identify(p, tol);
                };
            }
            tool = std::make_shared<SelectTool>(*lyr, identify_fn);
        } else if (action_id == "select_rectangle") {
            tool = std::make_shared<RectangleSelectTool>(
                *lyr, [&index](const MapPoint& a, const MapPoint& b) {
                    return index.select_rectangle(a, b);
                });
        } else {
            VectorEditSession* session = lyr->edit_session();
            bool native_open = native_editing_ &&
                               native_editing_->is_open(lyr->id());
            if (session == nullptr && !native_open)
                return;  // M1：原生会话同样允许激活
            if ((action_id == "vertex" || action_id == "move_feature" ||
                 action_id == "fault_cut" ||
                 action_id == "boundary_reshape") &&
                native_open) {
                // V12 M1-8 激活预检：画布当前层须就位（无自省面跳过
                // 硬门禁）。
                bool can_query =
                    static_cast<bool>(canvas_.current_layer_doc_id);
                bool can_push = static_cast<bool>(canvas_.set_current_layer);
                if (can_query || can_push) {
                    repush_canvas_current_layer();
                    if (can_query && current_canvas_layer_id() != lyr->id()) {
                        emit(events.state_changed);
                        return;
                    }
                }
            }
            auto kind_it = kind_bound_tools().find(action_id);
            if (kind_it != kind_bound_tools().end() &&
                kind_it->second != kind_of(lyr->id()))
                return;
            const GeoTemplate* geo_template =
                template_by_key(layer_template(lyr->id()));
            Json defaults = geo_template ? geo_template->field_defaults()
                                         : Json::object();
            if (defaults.is_null() ||
                (defaults.is_object() && defaults.empty()))
                defaults = capture_defaults_for_role(lyr->id());
            std::function<void(const std::string&)> captured;
            if (facies_template_keys().count(layer_template(lyr->id()))) {
                std::string lid = lyr->id();
                captured = [this, lid](const std::string& fid) {
                    emit(events.feature_captured, lid, fid);
                };
            }
            auto snap_fn = [this](const MapPoint& p) {
                return snap_point(p);
            };
            if (action_id == "add_point") {
                tool = std::make_shared<AddPointTool>(
                    session, snap_fn, defaults, captured);
            } else if (action_id == "add_line") {
                tool = std::make_shared<AddLineTool>(session, snap_fn,
                                                   defaults, captured);
            } else if (action_id == "add_polygon") {
                tool = std::make_shared<AddPolygonTool>(
                    session, snap_fn, defaults, captured);
            } else if (action_id == "add_rectangle") {
                tool = std::make_shared<RectangleCaptureTool>(
                    session, snap_fn, defaults, captured);
            } else if (action_id == "add_circle") {
                tool = std::make_shared<CircleCaptureTool>(
                    session, snap_fn, defaults, captured);
            } else if (action_id == "add_arc") {
                tool = std::make_shared<ArcCaptureTool>(session, snap_fn,
                                                      defaults, captured);
            } else if (action_id == "add_regular_polygon") {
                tool = std::make_shared<RegularPolygonCaptureTool>(
                    session, snap_fn, defaults, captured);
            } else if (action_id == "add_ellipse") {
                tool = std::make_shared<EllipseCaptureTool>(
                    session, snap_fn, defaults, captured);
            } else if (action_id == "add_sector") {
                tool = std::make_shared<SectorCaptureTool>(
                    session, snap_fn, defaults, captured);
            } else if (action_id == "move_feature") {
                double tol = tolerance();
                tool = std::make_shared<MoveFeatureTool>(
                    session, [&index, tol](const MapPoint& p) {
                        return index.identify(p, tol);
                    });
            } else if (action_id == "vertex") {
                double tol = tolerance();
                tool = std::make_shared<VertexTool>(
                    session, [&index, tol](const MapPoint& p) {
                        return index.identify_vertex(p, tol);
                    });
            } else if (action_id == "reshape") {
                // V7：native-only 工具——非原生画布/无算子/选集非恰一个
                // 拒激活。
                if (!canvas_.canvas_address) return;
                if (lyr->selection().size() != 1) return;
                std::string feature_id = *lyr->selection().begin();
                auto applier = make_reshape_applier(session, feature_id);
                if (applier == nullptr) return;
                tool = std::make_shared<ReshapeTool>(session, feature_id,
                                                     applier);
            } else if (action_id == "add_ring") {
                if (!canvas_.canvas_address) return;
                if (kind_of(lyr->id()) != "polygon" ||
                    lyr->selection().size() != 1)
                    return;
                std::string feature_id = *lyr->selection().begin();
                if (feature_id.empty()) return;
                tool = std::make_shared<RingCaptureTool>(
                    session, feature_id,
                    [this, session, feature_id](const Json& ring) {
                        return apply_captured_ring(session, feature_id,
                                                   ring);
                    });
            } else if (action_id == "add_part") {
                if (!canvas_.canvas_address) return;
                if (lyr->selection().size() != 1) return;
                std::string feature_id = *lyr->selection().begin();
                if (feature_id.empty() ||
                    make_part_applier(session, feature_id) == nullptr)
                    return;
                auto part_tool = std::make_shared<PartCaptureTool>(
                    session, feature_id,
                    [this, session, feature_id](const Json& part) {
                        return apply_captured_part(session, feature_id,
                                                   part);
                    });
                static const std::map<std::string, std::string> kinds = {
                    {"point", "addPoint"},
                    {"line", "addLine"},
                    {"polygon", "addPolygon"}};
                auto kit = kinds.find(kind_of(lyr->id()));
                part_tool->native_digitize_kind =
                    kit == kinds.end() ? "pan" : kit->second;
                tool = part_tool;
            } else if (action_id == "fault_cut") {
                if (!canvas_.canvas_address) return;
                if (kind_of(lyr->id()) != "polygon") return;
                if (native_editing_ == nullptr ||
                    !native_editing_->has_fault_cut())
                    return;
                tool = std::make_shared<FaultCutTool>();
            } else if (action_id == "boundary_reshape") {
                if (!canvas_.canvas_address) return;
                if (kind_of(lyr->id()) != "polygon") return;
                if (lyr->selection().size() != 2) return;
                if (native_editing_ == nullptr ||
                    !native_editing_->has_shared_boundary_reshape())
                    return;
                tool = std::make_shared<BoundaryReshapeTool>();
            } else {
                return;
            }
        }
    }
    active_tool_action_ = action_id;
    tools.set_active_tool(tool);
    if (canvas_.focus) canvas_.focus();
    emit(events.state_changed);
}

void CompositeEditController::rebind_active_tool() {
    const std::string& action = active_tool_action_;
    static const std::set<std::string> session_actions = {
        "add_point", "add_line", "add_polygon", "add_rectangle",
        "add_circle", "add_arc", "add_regular_polygon", "add_ellipse",
        "add_sector", "move_feature", "vertex", "reshape", "add_ring",
        "add_part"};
    if (session_actions.count(action)) {
        VectorLayer* lyr = active_layer();
        if (lyr == nullptr || lyr->edit_session() == nullptr) {
            // 会话仍属于某个活图层 → 保留工具不打断数字化。
            const MapTool* active = tools.active_tool();
            const VectorEditSession* held = nullptr;
            if (auto* t = dynamic_cast<const CaptureTool*>(active))
                held = t->session;
            else if (auto* t = dynamic_cast<const MoveFeatureTool*>(active))
                held = t->session;
            else if (auto* t = dynamic_cast<const VertexTool*>(active))
                held = t->session;
            else if (auto* t = dynamic_cast<const ReshapeTool*>(active))
                held = t->session;
            else if (auto* t = dynamic_cast<const RingCaptureTool*>(active))
                held = t->session;
            else if (auto* t = dynamic_cast<const PartCaptureTool*>(active))
                held = t->session;
            if (held != nullptr) {
                for (const auto& [_, l] : layers_)
                    if (l->edit_session() == held) return;
            }
            activate_tool("pan");
            return;
        }
        auto kit = kind_bound_tools().find(action);
        if (kit != kind_bound_tools().end() &&
            kit->second != kind_of(lyr->id())) {
            activate_tool("pan");
            return;
        }
        if ((action == "reshape" || action == "add_ring" ||
             action == "add_part") &&
            lyr->selection().size() != 1) {
            activate_tool("pan");
            emit(events.state_changed);
            return;
        }
        if (action == "add_ring" && kind_of(lyr->id()) != "polygon") {
            activate_tool("pan");
            emit(events.state_changed);
            return;
        }
        activate_tool(action);
    } else if (layer_bound_tools().count(action)) {
        if (active_layer() == nullptr)
            activate_tool("pan");
        else
            activate_tool(action);
    } else if (kind_bound_tools().count(action)) {
        activate_tool("pan");
    }
}

// ---------------------------------------------------------------------------
// 捕捉 / 拓扑配置
// ---------------------------------------------------------------------------

void CompositeEditController::set_snapping(bool enabled) {
    snapping_.enabled = enabled;
    push_snapping_config();
}

std::set<std::string> CompositeEditController::bridge_snapping_features()
    const {
    if (!bridge_features_) return {};
    try {
        return bridge_features_();
    } catch (const std::exception&) {
        return {};
    }
}

void CompositeEditController::push_snapping_config() {
    if (!canvas_.set_snapping_config) return;
    std::set<std::string> features = bridge_snapping_features();
    bool endpoint_pushable = features.count("snapping_endpoint");
    bool intersection_pushable = features.count("snapping_intersection");
    // P2-8：旧桥不识别 endpoint/intersection 时如实告警（日志在宿主；
    // 这里只保证不静默下推——与 Python 相同地把未声明模式留在 Python
    // 执行体路径）。
    Json types = Json::array();
    for (const char* m : {"vertex", "segment", "midpoint", "endpoint"}) {
        if (snapping_.modes.count(m) &&
            (std::string(m) != "endpoint" || endpoint_pushable))
            types.push_back(m);
    }
    Json config = {
        {"enabled", snapping_.enabled},
        {"mode",
         snapping_.current_layer_only ? "active_layer" : "all_layers"},
        {"units", snapping_.tolerance_units},
        {"tolerance_px", snapping_.pixel_tolerance},
        {"types", types},
        {"reference_enabled", snapping_.modes.count("reference") != 0},
        {"intersection_enabled",
         snapping_.modes.count("intersection") != 0 &&
             intersection_pushable}};
    if (features.count("snapping_topological_editing"))
        config["topological_editing"] = topology_.enabled;
    if (snapping_.scale_minimum.has_value() &&
        *snapping_.scale_minimum > 0.0)
        config["scale_dependent"] = {
            {"minimum_scale", *snapping_.scale_minimum}};
    config["avoid_intersections"] = {
        {"enabled", avoid_intersections_enabled}};
    if (!snapping_.current_layer_only) {
        // 逐层条目：按 layer_priority 升序下发（QGIS 按配置顺序尝试）。
        std::vector<std::string> ordered = layer_ids();
        std::sort(ordered.begin(), ordered.end(),
                  [this](const std::string& a, const std::string& b) {
                      auto pa = snapping_.layer_priority.find(a);
                      auto pb = snapping_.layer_priority.find(b);
                      int va = pa == snapping_.layer_priority.end()
                                   ? 0
                                   : pa->second;
                      int vb = pb == snapping_.layer_priority.end()
                                   ? 0
                                   : pb->second;
                      return va < vb;
                  });
        Json layer_entries = Json::object();
        for (const auto& lid : ordered) {
            auto modes_it = snapping_.layer_modes.find(lid);
            Json entry_types = Json::array();
            if (modes_it != snapping_.layer_modes.end()) {
                for (const char* m :
                     {"vertex", "segment", "midpoint", "endpoint"}) {
                    if (modes_it->second.count(m) &&
                        (std::string(m) != "endpoint" || endpoint_pushable))
                        entry_types.push_back(m);
                }
            } else {
                entry_types = types;
            }
            auto en_it = snapping_.layer_enabled.find(lid);
            auto tol_it = snapping_.layer_tolerance.find(lid);
            auto unit_it = snapping_.layer_tolerance_units.find(lid);
            layer_entries[lid] = {
                {"enabled",
                 en_it == snapping_.layer_enabled.end()
                     ? true
                     : en_it->second},
                {"units",
                 unit_it == snapping_.layer_tolerance_units.end()
                     ? snapping_.tolerance_units
                     : unit_it->second},
                {"types", entry_types},
                {"tolerance_px",
                 tol_it == snapping_.layer_tolerance.end()
                     ? snapping_.pixel_tolerance
                     : tol_it->second}};
        }
        config["layers"] = layer_entries;
    }
    bool pushed = false;
    try {
        pushed = canvas_.set_snapping_config(config);
    } catch (const std::exception&) {
        pushed = false;
    }
    if (!pushed && snapping_.enabled) {
        // Native digitize uses QGIS snap, not Python snap (#1276).
        snapping_.enabled = false;
        emit(events.state_changed);
    }
}

void CompositeEditController::set_topology(bool enabled) {
    topology_.enabled = enabled;
    if (enabled) {
        for (auto& [_, lyr] : layers_) {
            if (lyr->edit_session() != nullptr)
                refresh_error_count_quiet(*lyr);
        }
    }
    push_snapping_config();
    emit(events.state_changed);
}

std::vector<Json> CompositeEditController::validate_open_session_topology() {
    std::vector<std::string> native_ids;
    if (native_editing_)
        native_ids = native_editing_->session_layer_ids();
    std::vector<std::string> python_ids;
    for (const auto& [id, lyr] : layers_)
        if (lyr->edit_session() != nullptr) python_ids.push_back(id);
    const std::vector<std::string>& run_ids =
        !native_ids.empty() ? native_ids : python_ids;
    if (!run_ids.empty()) {
        try {
            std::vector<Json> errors = topology_.checker().run(run_ids);
            std::vector<Json> issues =
                topology_.checker().blocking_errors(errors);
            for (const auto& layer_id : run_ids) {
                VectorLayer* lyr = layer(layer_id);
                if (lyr == nullptr) continue;
                int count = 0;
                for (const Json& issue : issues)
                    if (issue.value("layer_id", "") == layer_id) ++count;
                topology_.record_validation(*lyr, count);
            }
            return issues;
        } catch (const std::exception&) {
        }
    }
    std::vector<Json> issues;
    for (const auto& [layer_id, lyr] : layers_) {
        if (lyr->edit_session() == nullptr) continue;
        auto found = topology_.validate({lyr.get()});
        topology_.record_validation(*lyr, static_cast<int>(found.size()));
        issues.insert(issues.end(), found.begin(), found.end());
    }
    return issues;
}

std::vector<Json>
CompositeEditController::validate_active_layer_topology() {
    VectorLayer* lyr = active_layer();
    if (lyr == nullptr) return {};
    std::vector<Json> issues = gate_topology_issues(*lyr);
    topology_.record_validation(*lyr, static_cast<int>(issues.size()));
    return issues;
}

int CompositeEditController::repair_layer_geometries(
    const std::string& layer_id) {
    VectorLayer* lyr = layer(layer_id);
    if (lyr == nullptr) return 0;
    auto [allowed, _reason] = can_edit_layer(lyr->id());
    if (!allowed) return 0;
    bool opened_session = lyr->edit_session() == nullptr;
    VectorEditSession& session = open_session(*lyr);
    int repaired = 0;
    {
        auto guard = session.edit_source("repair_geometry");
        for (const auto& feature : session.features()) {
            Json geometry = feature.as_record().value("geometry", Json());
            std::string gtype = geometry.value("type", "");
            if (gtype != "Polygon" && gtype != "MultiPolygon") continue;
            Json fixed = geometry_ops_
                             ? geometry_ops_->make_geometry_valid(geometry)
                             : repair_invalid_geometry(geometry);
            if (!geometry_equal(fixed, geometry)) {
                session.set_geometry(feature.feature_id, fixed);
                repaired += 1;
            }
        }
    }
    if (repaired) {
        emit(events.content_changed, lyr->id());
        emit(events.state_changed);
    } else if (opened_session) {
        // 没有需要修复的要素时不留幽灵会话（review #12）。
        session.rollback_changes();
        emit(events.state_changed);
    }
    return repaired;
}

// ---------------------------------------------------------------------------
// 几何命令（split / merge / fault_cut / transforms / clipboard / rings）
// ---------------------------------------------------------------------------

std::optional<CompositeEditController::SplitInputs>
CompositeEditController::split_inputs() {
    VectorLayer* polygon_layer = nullptr;
    VectorLayer* active = active_layer();
    if (active != nullptr && kind_of(active->id()) == "polygon" &&
        !active->selection().empty() && active->edit_session() != nullptr) {
        polygon_layer = active;
    } else {
        for (auto& [id, lyr] : layers_) {
            if (kinds_[id] == "polygon" && !lyr->selection().empty() &&
                lyr->edit_session() != nullptr) {
                polygon_layer = lyr.get();
                break;
            }
        }
    }
    if (polygon_layer == nullptr) return std::nullopt;
    for (auto& [id, lyr] : layers_) {
        if (kinds_[id] != "line") continue;
        if (lyr->selection().empty()) continue;
        std::string line_id = *lyr->selection().begin();
        VectorEditSession* session = lyr->edit_session();
        try {
            VectorFeature line_feature =
                session ? session->feature(line_id) : lyr->feature(line_id);
            return SplitInputs{polygon_layer,
                               *polygon_layer->selection().begin(),
                               line_feature};
        } catch (const std::exception&) {
            continue;
        }
    }
    return std::nullopt;
}

std::pair<bool, std::string>
CompositeEditController::geometry_command_at_point(
    const std::string& command_id, const MapPoint& point) {
    VectorLayer* lyr = active_layer();
    if (lyr == nullptr) return {false, "没有活动的矢量图层"};
    std::vector<Json> results = identify_all(point);
    const Json* hit = nullptr;
    for (const Json& r : results) {
        if (r.value("layer_id", "") == lyr->id() &&
            r.value("editable", false)) {
            hit = &r;
            break;
        }
    }
    if (hit != nullptr &&
        lyr->selection() != std::set<std::string>{
                                hit->value("feature_id", "")}) {
        lyr->set_selection({(*hit)["feature_id"].get<std::string>()});
    }
    return ring_and_part_commands(command_id, point_to_json(point));
}

std::pair<bool, std::string> CompositeEditController::geometry_command(
    const std::string& command_id, const std::optional<Json>& curve) {
    VectorLayer* lyr = active_layer();
    if (lyr == nullptr) return {false, "没有活动的矢量图层"};
    if (command_id == "fault_cut" && lyr->edit_session() != nullptr)
        return {false, "断层截断需要原生编辑会话（QGIS 桥）"};
    VectorEditSession* session = lyr->edit_session();
    if (session == nullptr) {
        if (native_editing_ && native_editing_->is_open(lyr->id()))
            return native_geometry_command(command_id, *lyr, curve);
        return {false, "请先开始编辑（几何操作需要编辑会话）"};
    }
    std::vector<VectorLayer*> mutated = {lyr};
    try {
        if (command_id == "merge") {
            if (lyr->selection().empty())
                return {false, "请先选择要合并的要素"};
            if (geometry_ops_ == nullptr)
                return {false, "几何算子不可用（无 QGIS/Shapely 引擎）"};
            std::vector<std::string> ids(lyr->selection().begin(),
                                       lyr->selection().end());
            std::sort(ids.begin(), ids.end());
            std::string new_id;
            {
                auto guard = session->edit_source("merge(command)");
                new_id = geometry_ops_->merge_selected_polygons(*session,
                                                                ids);
            }
            lyr->set_selection({new_id});
            emit(events.content_changed, lyr->id());
            emit(events.state_changed);
            return {true, "已合并所选要素"};
        }
        if (command_id == "split") {
            auto inputs = split_inputs();
            if (!inputs.has_value())
                return {false,
                        "分割需要一个选中多边形（正在编辑）与一条选中的切割线"};
            VectorLayer* poly = inputs->polygon_layer;
            if (poly != lyr) mutated.push_back(poly);
            if (geometry_ops_ == nullptr)
                return {false, "几何算子不可用（无 QGIS/Shapely 引擎）"};
            std::vector<std::string> new_ids;
            {
                auto guard =
                    poly->edit_session()->edit_source("split(command)");
                new_ids = geometry_ops_->split_polygon_by_line(
                    *poly->edit_session(), inputs->polygon_id,
                    inputs->line_feature);
            }
            poly->set_selection(new_ids);
            if (poly != lyr) {
                active_layer_id_ = poly->id();
                rebind_active_tool();
            }
            emit(events.content_changed, poly->id());
            emit(events.state_changed);
            return {true, "已按切割线分割多边形"};
        }
        if (command_id == "explode_multipart")
            return explode_selected_multipart(*lyr, *session);
        if (command_id == "collect_multipart")
            return collect_selected_multipart(*lyr, *session);
    } catch (const std::exception& exc) {
        return {false, exc.what()};
    } catch (...) {
        return {false, "几何命令失败"};
    }
    // finally parity：按实际触及集合刷新错误计数。
    for (VectorLayer* m : mutated)
        if (m->edit_session() != nullptr) refresh_error_count_quiet(*m);
    return {false, "未知几何命令 " + command_id};
}

std::pair<bool, std::string> CompositeEditController::transform_selection(
    const std::string& op_id, double angle_degrees, double xfact,
    double yfact) {
    VectorLayer* lyr = active_layer();
    if (lyr == nullptr) return {false, "没有活动的矢量图层"};
    VectorEditSession* session = lyr->edit_session();
    if (session == nullptr) return {false, "请先开始编辑"};
    if (lyr->selection().empty()) return {false, "没有选中的要素"};
    if (geometry_ops_ == nullptr)
        return {false, "几何算子不可用（无 QGIS/Shapely 引擎）"};
    if (yfact == 0.0) yfact = xfact;
    std::vector<std::string> ids(lyr->selection().begin(),
                               lyr->selection().end());
    std::sort(ids.begin(), ids.end());
    std::vector<Json> geoms;
    for (const auto& fid : ids)
        geoms.push_back(session->feature(fid).as_record().value("geometry",
                                                                Json()));
    if (geoms.empty()) return {false, "选中要素没有几何"};
    MapPoint center = geometry_ops_->union_centroid(geoms);
    int changed = 0;
    {
        auto guard = session->edit_source(op_id + "(command)");
        for (const auto& fid : ids) {
            Json geometry =
                session->feature(fid).as_record().value("geometry", Json());
            Json transformed;
            if (op_id == "rotate_feature")
                transformed =
                    geometry_ops_->rotate(geometry, angle_degrees, center);
            else if (op_id == "scale_feature")
                transformed =
                    geometry_ops_->scale(geometry, xfact, yfact, center);
            else
                return {false, "未知变换 " + op_id};
            session->set_geometry(fid, transformed);
            changed += 1;
        }
    }
    refresh_error_count_quiet(*lyr);
    emit(events.content_changed, lyr->id());
    emit(events.state_changed);
    return {true,
            "已应用" + op_id + "（" + std::to_string(changed) + " 个要素）"};
}

std::pair<bool, std::string>
CompositeEditController::clipboard_copy_selection(bool cut) {
    VectorLayer* lyr = active_layer();
    if (lyr == nullptr) return {false, "没有活动的矢量图层"};
    if (lyr->selection().empty()) return {false, "没有选中的要素"};
    VectorEditSession* session = lyr->edit_session();
    if (cut && session == nullptr) return {false, "剪切需要先开始编辑"};
    std::vector<VectorFeature> source =
        session ? session->features() : lyr->features();
    std::vector<Json> entries;
    for (const auto& f : source) {
        if (lyr->selection().count(f.feature_id))
            entries.push_back({{"geometry", f.geometry},
                               {"attributes", f.attributes}});
    }
    if (entries.empty()) return {false, "选中要素没有可复制的几何"};
    feature_clipboard_ =
        std::make_tuple(lyr->id(), lyr->crs(), entries);
    if (cut) {
        {
            auto guard = session->edit_source("cut_features(command)");
            for (const auto& f : source)
                if (lyr->selection().count(f.feature_id))
                    session->delete_feature(f.feature_id);
        }
        emit(events.content_changed, lyr->id());
        emit(events.state_changed);
        return {true,
                "已剪切 " + std::to_string(entries.size()) + " 个要素"};
    }
    return {true, "已复制 " + std::to_string(entries.size()) + " 个要素"};
}

std::pair<bool, std::string> CompositeEditController::clipboard_paste() {
    if (!feature_clipboard_.has_value()) return {false, "剪贴板为空"};
    const auto& [source_layer_id, source_crs, entries] =
        *feature_clipboard_;
    VectorLayer* lyr = active_layer();
    if (lyr == nullptr) return {false, "没有活动的矢量图层"};
    VectorEditSession* session = lyr->edit_session();
    if (session == nullptr) return {false, "粘贴需要先开始编辑"};
    std::string target_crs = lyr->crs();
    if (!source_crs.empty() && !target_crs.empty() &&
        source_crs != target_crs)
        return {false, "源/目标坐标系不同（" + source_crs + " → " +
                           target_crs +
                           "），不静默重投影——请改目标层坐标或分层粘贴"};
    Json schema = lyr->schema();
    std::optional<std::set<std::string>> allowed;
    if (schema.is_object() && !schema.empty()) {
        allowed.emplace();
        for (auto it = schema.begin(); it != schema.end(); ++it)
            allowed->insert(it.key());
    }
    std::set<std::string> dropped;
    {
        auto guard = session->edit_source("paste_features(command)");
        for (const Json& entry : entries) {
            Json mapped = Json::object();
            Json attrs = entry.value("attributes", Json::object());
            if (attrs.is_object()) {
                for (auto it = attrs.begin(); it != attrs.end(); ++it) {
                    if (!allowed.has_value() || allowed->count(it.key()))
                        mapped[it.key()] = it.value();
                    else
                        dropped.insert(it.key());
                }
            }
            session->add_feature(VectorFeature(
                "f" + ui_data_core::new_feature_id("feature"),
                entry.value("geometry", Json::object()), mapped));
        }
    }
    emit(events.content_changed, lyr->id());
    emit(events.state_changed);
    std::string message =
        "已粘贴 " + std::to_string(entries.size()) + " 个要素";
    if (!dropped.empty()) {
        message += "（丢弃字段：";
        bool first = true;
        for (const auto& d : dropped) {
            if (!first) message += "、";
            first = false;
            message += d;
        }
        message += "）";
    }
    return {true, message};
}

std::pair<bool, std::string> CompositeEditController::fill_ring_at_point(
    const MapPoint& point) {
    VectorLayer* lyr = active_layer();
    if (lyr == nullptr) return {false, "没有活动的矢量图层"};
    VectorEditSession* session = lyr->edit_session();
    if (session == nullptr) return {false, "请先开始编辑"};
    if (lyr->selection().size() != 1)
        return {false, "该操作需要恰好选中一个要素"};
    std::string feature_id = *lyr->selection().begin();
    try {
        const VectorFeature& feature = session->feature(feature_id);
        Json geometry = feature.as_record().value("geometry", Json());
        int ring_index = nearest_interior_ring(geometry, point);
        if (ring_index < 0) return {false, "定位点附近没有内环"};
        std::string new_id;
        {
            auto guard = session->edit_source("fill_ring(command)");
            new_id = session->fill_ring(feature_id, ring_index);
        }
        refresh_error_count_quiet(*lyr);
        emit(events.content_changed, lyr->id());
        emit(events.state_changed);
        return {true, "已填充内环（新要素 " + new_id + "）"};
    } catch (const std::exception& exc) {
        return {false, exc.what()};
    }
}

std::pair<bool, std::string> CompositeEditController::trim_extend_selection(
    const std::string& op_id, const Json& boundary,
    const std::string& keep, double max_extend) {
    VectorLayer* lyr = active_layer();
    if (lyr == nullptr) return {false, "没有活动的矢量图层"};
    VectorEditSession* session = lyr->edit_session();
    if (session == nullptr) return {false, "请先开始编辑"};
    if (lyr->selection().empty()) return {false, "没有选中的要素"};
    if (geometry_ops_ == nullptr)
        return {false, "几何算子不可用（无 QGIS/Shapely 引擎）"};
    int changed = 0;
    {
        auto guard = session->edit_source(op_id + "(command)");
        std::vector<std::string> ids(lyr->selection().begin(),
                                     lyr->selection().end());
        std::sort(ids.begin(), ids.end());
        for (const auto& fid : ids) {
            Json geometry =
                session->feature(fid).as_record().value("geometry", Json());
            Json new_geometry;
            try {
                if (op_id == "trim_line")
                    new_geometry =
                        geometry_ops_->trim_line(geometry, boundary, keep);
                else if (op_id == "extend_line")
                    new_geometry = geometry_ops_->extend_line_to_boundary(
                        geometry, boundary, max_extend);
                else
                    return {false, "未知命令 " + op_id};
            } catch (const std::exception&) {
                continue;
            }
            session->set_geometry(fid, new_geometry);
            changed += 1;
        }
    }
    if (changed == 0) return {false, "选中要素无法按该边界修剪/延伸"};
    refresh_error_count_quiet(*lyr);
    emit(events.content_changed, lyr->id());
    emit(events.state_changed);
    return {true,
            "已应用" + op_id + "（" + std::to_string(changed) + " 个要素）"};
}

std::pair<bool, std::string> CompositeEditController::snap_geometries(
    std::optional<double> tolerance_opt) {
    VectorLayer* lyr = active_layer();
    if (lyr == nullptr) return {false, "没有活动的矢量图层"};
    VectorEditSession* session = lyr->edit_session();
    if (session == nullptr) return {false, "请先开始编辑"};
    if (lyr->selection().empty()) return {false, "没有选中的要素"};
    double mupp = canvas_.units_per_pixel();
    double tol = std::max(
        1e-12, tolerance_opt.has_value() ? *tolerance_opt : tolerance());
    auto snap_vertex = [this, lyr, tol, mupp](const MapPoint& p) {
        try {
            return snapping_.snap(p, tol, {lyr}, mupp);
        } catch (const std::exception&) {
            return p;
        }
    };
    SnapGeometriesTool tool(session, snap_vertex);
    bool changed = tool.run(*lyr);
    if (!changed) return {false, "选集无人可吸附"};
    refresh_error_count_quiet(*lyr);
    emit(events.content_changed, lyr->id());
    emit(events.state_changed);
    return {true, "已把选中要素吸附到捕捉命中"};
}

std::pair<bool, std::string> CompositeEditController::selection_geometry_op(
    const std::string& op_id, double tolerance, int iterations,
    double offset, double distance) {
    VectorLayer* lyr = active_layer();
    if (lyr == nullptr) return {false, "没有活动的矢量图层"};
    VectorEditSession* session = lyr->edit_session();
    if (session == nullptr) return {false, "请先开始编辑"};
    if (lyr->selection().empty()) return {false, "没有选中的要素"};
    if (geometry_ops_ == nullptr)
        return {false, "几何算子不可用（无 QGIS/Shapely 引擎）"};
    int changed = 0;
    {
        auto guard = session->edit_source(op_id + "(command)");
        std::vector<std::string> ids(lyr->selection().begin(),
                                     lyr->selection().end());
        std::sort(ids.begin(), ids.end());
        for (const auto& fid : ids) {
            Json geometry =
                session->feature(fid).as_record().value("geometry", Json());
            Json new_geometry;
            try {
                if (op_id == "reverse_line")
                    new_geometry = geometry_ops_->reverse_geometry(geometry);
                else if (op_id == "simplify_feature")
                    new_geometry =
                        geometry_ops_->simplify(geometry, tolerance);
                else if (op_id == "smooth_feature")
                    new_geometry = geometry_ops_->smooth(geometry,
                                                         iterations, offset);
                else if (op_id == "offset_curve")
                    new_geometry =
                        geometry_ops_->offset_curve(geometry, distance);
                else
                    return {false, "未知算子 " + op_id};
            } catch (const std::exception&) {
                continue;
            }
            session->set_geometry(fid, new_geometry);
            changed += 1;
        }
    }
    if (changed == 0) return {false, "选中要素无法应用该算子"};
    refresh_error_count_quiet(*lyr);
    emit(events.content_changed, lyr->id());
    emit(events.state_changed);
    return {true,
            "已应用" + op_id + "（" + std::to_string(changed) + " 个要素）"};
}

// ---------------------------------------------------------------------------
// 原生几何命令
// ---------------------------------------------------------------------------

std::pair<bool, std::string> CompositeEditController::native_geometry_command(
    const std::string& command_id, VectorLayer& layer,
    const std::optional<Json>& curve) {
    if (native_editing_ == nullptr || !native_editing_->is_open(layer.id()))
        return {false, "该图层没有进行中的原生编辑会话"};
    if (command_id == "merge") return native_merge(layer);
    if (command_id == "split") return native_split_begin(layer);
    if (command_id == "fault_cut") return native_fault_cut(layer, curve);
    return {false, "该图层处于原生编辑会话——请先保存或回滚编辑"};
}

std::pair<bool, std::string> CompositeEditController::native_fault_cut(
    VectorLayer& layer, const std::optional<Json>& curve) {
    if (!native_editing_->has_fault_cut())
        return {false, "当前 QGIS 桥不支持原生断层截断（需重建桥扩展）"};
    if (!curve.has_value() || !curve->is_object() ||
        curve->value("type", "") != "LineString")
        return {false, "断层截断需要一条断层折线（LineString GeoJSON）"};
    std::vector<std::string> ids(layer.selection().begin(),
                                 layer.selection().end());
    std::sort(ids.begin(), ids.end());
    std::string error;
    try {
        error = native_editing_->fault_cut_mirror_features(
            layer.id(), *curve, ids, {{"mark_field", "fault_bounded"}});
    } catch (const std::exception& exc) {
        return {false, std::string("断层截断调用失败：") + exc.what()};
    }
    if (!error.empty()) return {false, error};
    emit(events.content_changed, layer.id());
    emit(events.state_changed);
    return {true, "断层已截断相带（两侧属性延续并标记 fault_bounded）"};
}

std::vector<Json> CompositeEditController::selected_native_records(
    VectorLayer& layer) {
    std::set<std::string> selected = layer.selection();
    std::vector<Json> records;
    try {
        for (const Json& feature :
             native_editing_->mirror_features(layer.id())) {
            std::string fid = feature.value("id", "");
            if (!selected.count(fid)) continue;
            records.push_back(
                {{"id", fid},
                 {"geometry", feature.value("geometry", Json::object())},
                 {"properties",
                  feature.value("properties", Json::object())}});
        }
    } catch (const std::exception&) {
    }
    if (!records.empty()) return records;
    for (const auto& fid : selected) {
        try {
            const VectorFeature& f = layer.feature(fid);
            records.push_back({{"id", fid},
                               {"geometry", f.geometry},
                               {"properties", f.attributes}});
        } catch (const std::exception&) {
        }
    }
    return records;
}

std::pair<bool, std::string> CompositeEditController::native_merge(
    VectorLayer& layer) {
    if (layer.selection().size() < 2)
        return {false, "请先选择要合并的要素"};
    if (!native_editing_->has_merge())
        return {false, "当前 QGIS 桥不支持原生合并（需重建桥扩展）"};
    std::vector<Json> records = selected_native_records(layer);
    if (records.size() < 2) return {false, "请先选择要合并的要素"};
    if (!merge_confirm_) return {false, "已取消合并"};
    auto payload = merge_confirm_(records);
    if (!payload.has_value()) return {false, "已取消合并"};
    std::vector<std::string> ids(layer.selection().begin(),
                                 layer.selection().end());
    std::sort(ids.begin(), ids.end());
    std::string error;
    try {
        error = native_editing_->merge_mirror_features(layer.id(), ids,
                                                       *payload);
    } catch (const std::exception& exc) {
        return {false, std::string("合并失败：") + exc.what()};
    }
    if (!error.empty()) return {false, error};
    std::string target = payload->value("target_id", "");
    if (!target.empty()) layer.set_selection({target});
    emit(events.state_changed);
    return {true, "已合并所选要素"};
}

std::pair<bool, std::string> CompositeEditController::native_split_begin(
    VectorLayer& layer) {
    if (layer.selection().empty())
        return {false, "请先选择要分割的要素"};
    if (!native_editing_->has_split())
        return {false, "当前 QGIS 桥不支持原生分割（需重建桥扩展）"};
    pending_native_split_ = layer.id();
    std::uintptr_t address =
        canvas_.canvas_address ? canvas_.canvas_address() : 0;
    try {
        native_editing_->set_map_tool(address, "addLine");
    } catch (const std::exception&) {
    }
    return {true, "请在画布上绘制切线后右键确认"};
}

bool CompositeEditController::commit_native_split(const Json& geometry) {
    std::string layer_id = pending_native_split_.value_or("");
    pending_native_split_.reset();
    VectorLayer* lyr = layer(layer_id);
    if (lyr == nullptr) return true;  // pending 已消耗
    if (native_editing_ == nullptr || !native_editing_->has_split())
        return true;
    Json curve = geometry.is_object() ? geometry : Json::object();
    if (curve.value("type", "") == "Feature")
        curve = curve.value("geometry", Json::object());
    std::vector<std::string> ids(lyr->selection().begin(),
                                 lyr->selection().end());
    std::sort(ids.begin(), ids.end());
    try {
        std::string error = native_editing_->split_mirror_features(
            layer_id, curve, ids);
        (void)error;
    } catch (const std::exception&) {
    }
    emit(events.state_changed);
    return true;
}

// ---------------------------------------------------------------------------
// multipart / ring / part commands
// ---------------------------------------------------------------------------

std::pair<bool, std::string>
CompositeEditController::explode_selected_multipart(
    VectorLayer& layer, VectorEditSession& session) {
    if (geometry_ops_ == nullptr)
        return {false, "几何算子不可用（无 QGIS/Shapely 引擎）"};
    try {
        bool exploded_any = false;
        int skipped = 0;
        std::vector<std::string> new_selection;
        session.begin_edit_command();
        try {
            std::vector<std::string> ids(layer.selection().begin(),
                                         layer.selection().end());
            std::sort(ids.begin(), ids.end());
            for (const auto& fid : ids) {
                const VectorFeature& feature = session.feature(fid);
                std::string gtype =
                    feature.geometry.value("type", "");
                if (gtype.rfind("Multi", 0) != 0) {
                    new_selection.push_back(fid);
                    skipped += 1;
                    continue;
                }
                std::vector<Json> parts;
                for (const Json& part :
                     geometry_ops_->multipart_to_singlepart(
                         feature.as_record().value("geometry", Json()))) {
                    std::string pt = part.value("type", "");
                    if ((pt == "Point" || pt == "LineString" ||
                         pt == "Polygon") &&
                        part.contains("coordinates"))
                        parts.push_back(part);
                }
                if (parts.size() < 2) {
                    new_selection.push_back(fid);
                    skipped += 1;
                    continue;
                }
                std::vector<VectorFeature> replacements;
                for (const Json& part : parts)
                    replacements.emplace_back(
                        ui_data_core::new_feature_id("explode"), part,
                        feature.attributes);
                {
                    auto guard = session.edit_source(
                        "explode_multipart(command)");
                    session.split_feature(fid, replacements);
                }
                for (const auto& r : replacements)
                    new_selection.push_back(r.feature_id);
                exploded_any = true;
            }
        } catch (...) {
            session.destroy_edit_command();
            throw;
        }
        session.end_edit_command();
        if (!exploded_any) return {false, "选中的要素都不是多部件几何"};
        layer.set_selection(new_selection);
        refresh_error_count_quiet(layer);
        emit(events.content_changed, layer.id());
        emit(events.state_changed);
        std::string message = "已拆分为单部件要素";
        if (skipped)
            message += "（" + std::to_string(skipped) +
                       " 个非多部件要素保持原样）";
        return {true, message};
    } catch (const std::exception& exc) {
        return {false, exc.what()};
    }
}

std::pair<bool, std::string>
CompositeEditController::collect_selected_multipart(
    VectorLayer& layer, VectorEditSession& session) {
    if (geometry_ops_ == nullptr)
        return {false, "几何算子不可用（无 QGIS/Shapely 引擎）"};
    try {
        std::vector<std::string> selected(layer.selection().begin(),
                                          layer.selection().end());
        std::sort(selected.begin(), selected.end());
        if (selected.size() < 2)
            return {false, "组合多部件需要至少两个要素"};
        std::vector<VectorFeature> features;
        for (const auto& fid : selected)
            features.push_back(session.feature(fid));
        std::set<std::string> kinds;
        for (const auto& f : features)
            kinds.insert(f.geometry.value("type", ""));
        if (kinds.size() != 1 || kinds.begin()->rfind("Multi", 0) == 0)
            return {false, "组合多部件需要同类型的单部件要素"};
        std::vector<Json> geoms;
        for (const auto& f : features)
            geoms.push_back(f.as_record().value("geometry", Json()));
        Json collected = plain_geometry(
            geometry_ops_->singlepart_to_multipart(geoms));
        VectorFeature merged(ui_data_core::new_feature_id("collect"),
                             collected, features[0].attributes);
        {
            auto guard =
                session.edit_source("collect_multipart(command)");
            session.merge_features(selected, merged);
        }
        layer.set_selection({merged.feature_id});
        refresh_error_count_quiet(layer);
        emit(events.content_changed, layer.id());
        emit(events.state_changed);
        return {true, "已组合为多部件要素"};
    } catch (const std::exception& exc) {
        return {false, exc.what()};
    }
}

std::pair<bool, std::string> CompositeEditController::ring_and_part_commands(
    const std::string& command_id, const Json& pick_point) {
    VectorLayer* lyr = active_layer();
    if (lyr == nullptr) return {false, "没有活动的矢量图层"};
    VectorEditSession* session = lyr->edit_session();
    if (session == nullptr) return {false, "请先开始编辑"};
    if (lyr->selection().size() != 1)
        return {false, "该操作需要恰好选中一个要素"};
    if (pick_point.is_null())
        return {false, "需要提供定位点（pick_point）"};
    std::string feature_id = *lyr->selection().begin();
    try {
        const VectorFeature& feature = session->feature(feature_id);
        Json geometry = feature.as_record().value("geometry", Json());
        if (command_id == "delete_ring") {
            auto pt = json_point(pick_point);
            int ring_index =
                pt ? nearest_interior_ring(geometry, *pt) : -1;
            if (ring_index < 0) return {false, "定位点附近没有内环"};
            {
                auto guard = session->edit_source("delete_ring(command)");
                session->delete_ring(feature_id, ring_index);
            }
            refresh_error_count_quiet(*lyr);
            emit(events.content_changed, lyr->id());
            emit(events.state_changed);
            return {true, "已删除内环"};
        }
        if (command_id == "delete_part") {
            auto pt = json_point(pick_point);
            int part_index = pt ? nearest_part(geometry, *pt) : -1;
            if (part_index < 0) return {false, "定位点附近没有部件"};
            if (geometry_ops_ == nullptr)
                return {false, "删除部件失败：几何算子不可用"};
            auto new_geometry =
                geometry_ops_->delete_part(geometry, part_index);
            if (!new_geometry.has_value())
                return {false, "删除部件失败"};
            {
                auto guard = session->edit_source("delete_part(command)");
                session->delete_part(feature_id, *new_geometry);
            }
            refresh_error_count_quiet(*lyr);
            emit(events.content_changed, lyr->id());
            emit(events.state_changed);
            return {true, "已删除部件"};
        }
        if (command_id == "move_part") {
            if (!pick_point.is_object() ||
                !pick_point.contains("delta"))
                return {false,
                        "move_part 需要 pick_point={'point':(x,y),'delta':(dx,dy)}"};
            auto pt = json_point(pick_point.value("point", Json()));
            int part_index = pt ? nearest_part(geometry, *pt) : -1;
            if (part_index < 0) return {false, "定位点附近没有部件"};
            auto delta = json_point(pick_point.value("delta", Json()));
            double dx = delta ? (*delta)[0] : 0.0;
            double dy = delta ? (*delta)[1] : 0.0;
            {
                auto guard = session->edit_source("move_part(command)");
                session->move_part(feature_id, part_index, dx, dy);
            }
            refresh_error_count_quiet(*lyr);
            emit(events.content_changed, lyr->id());
            emit(events.state_changed);
            return {true, "已平移部件"};
        }
    } catch (const std::exception& exc) {
        return {false, exc.what()};
    }
    return {false, "未知命令 " + command_id};
}

// ---------------------------------------------------------------------------
// 多图层识别 / 命令
// ---------------------------------------------------------------------------

std::vector<Json> CompositeEditController::identify_all(
    const MapPoint& point, const std::vector<MapLayerSnapshot>& base_layers) {
    std::vector<Json> results;
    double tol = std::max(tolerance(), 1e-9);
    for (auto& [_, lyr] : layers_) {
        auto disp = display_.find(lyr->id());
        bool visible = disp == display_.end() ? true : disp->second.first;
        if (!visible) continue;
        auto feature_id =
            snapping_.index_for(lyr.get()).identify(point, tol);
        if (!feature_id.has_value()) continue;
        VectorEditSession* session = lyr->edit_session();
        std::vector<VectorFeature> source =
            session ? session->features() : lyr->features();
        const VectorFeature* feature = nullptr;
        for (const auto& f : source)
            if (f.feature_id == *feature_id) feature = &f;
        if (feature == nullptr) continue;
        results.push_back(
            {{"layer_id", lyr->id()},
             {"layer_name", lyr->name()},
             {"feature_id", feature->feature_id},
             {"geometry_type", feature->geometry.value("type", "")},
             {"attributes", feature->attributes},
             {"source", "composite"},
             {"template", layer_template(lyr->id())},
             {"editable", true},
             {"record", feature->as_record()}});
    }
    for (const auto& snap_layer : base_layers) {
        if (!snap_layer.visible) continue;
        for (const Json& record : snap_layer.features) {
            if (!record.is_object()) continue;
            Json geometry = record.value("geometry", Json());
            if (!geometry.is_object()) continue;
            if (!geometry_hit(point, geometry, tol)) continue;
            results.push_back(
                {{"layer_id", snap_layer.id},
                 {"layer_name", snap_layer.name},
                 {"feature_id", record.value("id", "")},
                 {"geometry_type", geometry.value("type", "")},
                 {"attributes",
                  record.value("properties", Json::object())},
                 {"source",
                  snap_layer.source_version_id.empty()
                      ? "workarea"
                      : snap_layer.source_version_id},
                 {"template", ""},
                 {"editable", false},
                 {"record", record}});
        }
    }
    return results;
}

bool CompositeEditController::locate_identify_result(const Json& result) {
    std::string layer_id = result.value("layer_id", "");
    std::string feature_id = result.value("feature_id", "");
    VectorLayer* lyr = layer(layer_id);
    if (lyr == nullptr || feature_id.empty()) return false;
    set_active_layer(layer_id);
    lyr->set_selection({feature_id});
    emit(events.state_changed);
    return true;
}

void CompositeEditController::cancel_active_tool() {
    if (canvas_.native_tool_busy && canvas_.native_tool_busy()) {
        if (canvas_.cancel_native_tool) canvas_.cancel_native_tool();
        emit(events.state_changed);
        return;
    }
    tools.key_press("escape");
    emit(events.state_changed);
}

void CompositeEditController::selection_command(
    const std::string& command_id) {
    VectorLayer* lyr = active_layer();
    if (lyr == nullptr) return;
    if (command_id == "clear_selection")
        lyr->set_selection({});
    else if (command_id == "select_all")
        lyr->select_all();
    else if (command_id == "invert_selection")
        lyr->invert_selection();
    else
        return;
    rebind_active_tool();
    emit(events.state_changed);
}

bool CompositeEditController::edit_command(const std::string& command_id) {
    VectorLayer* lyr = active_layer();
    VectorEditSession* session =
        lyr ? lyr->edit_session() : nullptr;
    if ((command_id == "undo" || command_id == "redo") && lyr != nullptr &&
        native_editing_ && native_editing_->is_open(lyr->id())) {
        bool done = command_id == "undo" ? native_editing_->undo_gesture()
                                         : native_editing_->redo_gesture();
        if (done) emit(events.state_changed);
        return done;
    }
    if (command_id == "undo" && session != nullptr) {
        if (session->undo()) {
            refresh_error_count_quiet(*lyr);
            emit(events.content_changed, lyr->id());
            emit(events.state_changed);
            return true;
        }
        return false;
    }
    if (command_id == "redo" && session != nullptr) {
        if (session->redo()) {
            refresh_error_count_quiet(*lyr);
            emit(events.content_changed, lyr->id());
            emit(events.state_changed);
            return true;
        }
        return false;
    }
    if (command_id == "delete_selected" && session != nullptr &&
        !lyr->selection().empty()) {
        session->begin_edit_command();
        try {
            std::vector<std::string> ids(lyr->selection().begin(),
                                         lyr->selection().end());
            std::sort(ids.begin(), ids.end());
            for (const auto& fid : ids) session->delete_feature(fid);
        } catch (...) {
            session->destroy_edit_command();
            throw;
        }
        session->end_edit_command();
        lyr->set_selection({});
        refresh_error_count_quiet(*lyr);
        emit(events.content_changed, lyr->id());
        emit(events.state_changed);
        return true;
    }
    if (command_id == "duplicate_selected" && session != nullptr &&
        !lyr->selection().empty()) {
        std::vector<std::string> duplicates;
        session->begin_edit_command();
        try {
            std::vector<std::string> ids(lyr->selection().begin(),
                                         lyr->selection().end());
            std::sort(ids.begin(), ids.end());
            for (const auto& fid : ids) {
                auto guard =
                    session->edit_source("duplicate_selected(command)");
                VectorFeature dup = session->duplicate_feature(fid);
                duplicates.push_back(dup.feature_id);
            }
        } catch (...) {
            session->destroy_edit_command();
            throw;
        }
        session->end_edit_command();
        lyr->set_selection(duplicates);
        refresh_error_count_quiet(*lyr);
        emit(events.content_changed, lyr->id());
        emit(events.state_changed);
        return true;
    }
    return false;
}

// ---------------------------------------------------------------------------
// 快照与状态
// ---------------------------------------------------------------------------

std::vector<MapLayerSnapshot> CompositeEditController::snapshot_layers(
    const std::map<std::string, MapLayerSnapshot>& display) {
    std::vector<MapLayerSnapshot> snapshots;
    for (auto& [layer_id, lyr] : layers_) {
        VectorEditSession* session = lyr->edit_session();
        int64_t revision =
            session == nullptr
                ? lyr->data_revision
                : (lyr->data_revision << 32) + session->revision;
        auto cached_it = records_cache_.find(layer_id);
        std::vector<Json> features;
        MapExtent extent{0.0, 0.0, 1.0, 1.0};
        bool hit = false;
        if (cached_it != records_cache_.end() &&
            cached_it->second.revision == revision &&
            cached_it->second.session == session) {
            features = cached_it->second.features;
            extent = cached_it->second.extent;
            hit = true;
        }
        if (!hit) {
            std::optional<int64_t> base_revision;
            if (session != nullptr && cached_it != records_cache_.end()) {
                if (cached_it->second.session == session &&
                    (cached_it->second.revision & ~int64_t(0xFFFFFFFF)) ==
                        (lyr->data_revision << 32))
                    base_revision =
                        cached_it->second.revision & int64_t(0xFFFFFFFF);
                else if (cached_it->second.session == nullptr &&
                         cached_it->second.revision == lyr->data_revision)
                    base_revision = 0;
            }
            std::map<std::string, Json> records;
            bool incremental = false;
            if (base_revision.has_value() && session != nullptr) {
                auto entries = session->changes_since(*base_revision);
                if (entries.has_value()) {
                    records = cached_it->second.records;
                    std::vector<Json> changed;
                    for (const auto& ids : *entries) {
                        for (const auto& fid : ids) {
                            try {
                                Json record =
                                    session->feature(fid).as_record();
                                records[fid] = record;
                                changed.push_back(record);
                            } catch (const std::exception&) {
                                records.erase(fid);
                            }
                        }
                    }
                    extent = cached_it->second.extent;
                    if (!changed.empty())
                        extent = union_extents(extent, feature_extent_or_placeholder(changed));
                    incremental = true;
                }
            }
            if (!incremental) {
                records.clear();
                std::vector<VectorFeature> source =
                    session ? session->features() : lyr->features();
                std::vector<Json> recs;
                for (const auto& f : source) {
                    Json record = f.as_record();
                    records[f.feature_id] = record;
                    recs.push_back(record);
                }
                extent = feature_extent_or_placeholder(recs);
            }
            features.clear();
            for (auto& [_, r] : records) features.push_back(r);
            RecordsCacheEntry entry;
            entry.revision = revision;
            entry.session = session;
            entry.features = features;
            entry.extent = extent;
            entry.records = records;
            records_cache_[layer_id] = entry;
            // V11 changed hints（journal 展开；无会话 = 无提示）。
            if (session != nullptr) {
                std::set<std::string> touched;
                bool journal_ok = false;
                if (base_revision.has_value()) {
                    auto entries = session->changes_since(*base_revision);
                    if (entries.has_value()) {
                        journal_ok = true;
                        for (const auto& ids : *entries)
                            touched.insert(ids.begin(), ids.end());
                    }
                }
                if (journal_ok)
                    changed_hints_[layer_id] = std::make_tuple(
                        revision, lyr->data_revision, touched);
                else
                    changed_hints_.erase(layer_id);
            } else {
                changed_hints_.erase(layer_id);
            }
        }
        auto prev = display.find(layer_id);
        if (prev != display.end())
            display_[layer_id] = {prev->second.visible,
                                  prev->second.opacity};
        auto disp = display_.find(layer_id);
        bool visible = disp == display_.end() ? true : disp->second.first;
        double opacity = disp == display_.end() ? 1.0 : disp->second.second;
        // metadata：editable / geometry_kind / template / editing / role。
        std::string role_value = role_of_layer(layer_id);
        if (role_value.empty()) {
            auto it = layer_roles_.find(layer_id);
            if (it != layer_roles_.end()) role_value = it->second;
        }
        auto [allowed, _reason] = can_edit_layer(layer_id);
        std::map<std::string, std::string> metadata = {
            {"editable", allowed ? "true" : "false"},
            {"geometry_kind", kind_of(layer_id)},
            {"template", layer_template(layer_id)},
            {"editing",
             (session != nullptr ||
              (native_editing_ && native_editing_->is_open(layer_id)))
                 ? "true"
                 : "false"}};
        if (!role_value.empty() &&
            !snapshot_roleless_roles().count(role_value))
            metadata["role"] = role_value;
        MapLayerSnapshot snap;
        snap.id = lyr->id();
        snap.name = lyr->name();
        snap.layer_type = "vector";
        snap.extent = extent;
        snap.crs = lyr->crs();
        snap.data_revision = revision;
        snap.style_revision = lyr->style_revision;
        snap.features = features;
        snap.style = lyr->style();
        snap.visible = visible;
        snap.opacity = opacity;
        snap.metadata = metadata;
        snapshots.push_back(std::move(snap));
    }
    return snapshots;
}

void CompositeEditController::apply_display_state(
    const std::vector<MapLayerSnapshot>& display_layers,
    bool include_names) {
    std::vector<std::string> order;
    std::set<std::string> seen;
    for (const auto& snapshot : display_layers) {
        const std::string& layer_id = snapshot.id;
        if (layers_.count(layer_id) && !seen.count(layer_id)) {
            seen.insert(layer_id);
            order.push_back(layer_id);
            display_[layer_id] = {
                snapshot.visible,
                std::min(1.0, std::max(0.05, snapshot.opacity))};
            if (include_names) {
                std::string name = normalize_layer_role(snapshot.name);
                if (!name.empty()) rename_layer(layer_id, name);
            }
        }
    }
    if (!order.empty()) {
        std::vector<std::string> remaining;
        for (const auto& [lid, _] : layers_)
            if (!seen.count(lid)) remaining.push_back(lid);
        std::map<std::string, std::unique_ptr<VectorLayer>> reordered;
        for (const auto& lid : order) {
            reordered[lid] = std::move(layers_[lid]);
        }
        for (const auto& lid : remaining)
            reordered[lid] = std::move(layers_[lid]);
        layers_ = std::move(reordered);
    }
}

std::pair<int, bool> CompositeEditController::selection_geometry_facts(
    const VectorLayer& layer, const VectorEditSession* session) const {
    if (session == nullptr || layer.selection().empty()) return {0, false};
    std::set<std::string> sel = layer.selection();
    auto key = std::make_tuple(static_cast<const void*>(session),
                               session->revision, sel);
    auto cached = selection_facts_cache_.find(key);
    if (cached != selection_facts_cache_.end()) return cached->second;
    int multipart = 0;
    std::set<std::string> kinds;
    bool collect_valid = sel.size() >= 2;
    for (const auto& fid : sel) {
        std::string kind;
        try {
            kind = session->feature(fid).geometry.value("type", "");
        } catch (const std::exception&) {
            collect_valid = false;
            continue;
        }
        if (kind.rfind("Multi", 0) == 0) {
            multipart += 1;
            collect_valid = false;
        } else if (kind != "Point" && kind != "LineString" &&
                   kind != "Polygon") {
            collect_valid = false;
        }
        kinds.insert(kind);
        if (kinds.size() > 1) collect_valid = false;
    }
    std::pair<int, bool> facts = {multipart,
                                  collect_valid && kinds.size() == 1};
    if (selection_facts_cache_.size() > 8) selection_facts_cache_.clear();
    selection_facts_cache_[key] = facts;
    return facts;
}

tool_policy::ToolContextSnapshot
CompositeEditController::tool_context_inputs() const {
    const VectorLayer* lyr =
        active_layer_id_ ? layer(*active_layer_id_) : nullptr;
    const VectorEditSession* session =
        lyr ? lyr->edit_session() : nullptr;
    std::string layer_kind =
        lyr ? kind_of(lyr->id()) : std::string();
    std::vector<std::string> kinds_among_selection;
    if (lyr != nullptr && !lyr->selection().empty() && !layer_kind.empty())
        kinds_among_selection.push_back(layer_kind);
    static const std::map<std::string, std::string> wkb_map = {
        {"point", "Point"}, {"line", "LineString"}, {"polygon", "Polygon"}};
    std::string wkb_type;
    auto wit = wkb_map.find(layer_kind);
    if (wit != wkb_map.end()) wkb_type = wit->second;
    auto [gate_allowed, gate_reason] =
        lyr ? can_edit_layer(lyr->id())
            : std::pair<bool, std::string>{false, "没有活动图层"};
    bool native_open = lyr != nullptr && native_editing_ &&
                       native_editing_->is_open(lyr->id());
    std::string role;
    if (lyr != nullptr) {
        role = role_of_layer(lyr->id());
        if (role.empty()) {
            auto it = layer_roles_.find(lyr->id());
            if (it != layer_roles_.end()) role = it->second;
        }
    }
    auto facts = lyr && session
                     ? selection_geometry_facts(*lyr, session)
                     : std::pair<int, bool>{0, false};
    // split_inputs 的 const 变体（本采集器不改动状态）。
    bool split_ready = false;
    if (lyr != nullptr) {
        // 保守近似：本层 polygon + 选集 + 会话即 ready；原生会话同款。
        if (kind_of(lyr->id()) == "polygon" &&
            !lyr->selection().empty() &&
            (session != nullptr || native_open))
            split_ready = true;
    }
    if (!split_ready) {
        // 跨层情形（活动层非 polygon）：扫描任一 polygon+线层组合。
        bool has_poly = false, has_line = false;
        for (const auto& [id, l] : layers_) {
            auto k = kinds_.find(id);
            if (k == kinds_.end()) continue;
            if (k->second == "polygon" && !l->selection().empty() &&
                l->edit_session() != nullptr)
                has_poly = true;
            if (k->second == "line" && !l->selection().empty())
                has_line = true;
        }
        split_ready = has_poly && has_line;
    }
    tool_policy::ToolContextSnapshot ctx;
    ctx.project_open = true;
    ctx.active_layer_id = lyr ? lyr->id() : "";
    ctx.active_layer_kind = layer_kind;
    ctx.layer_role = role;
    ctx.layer_is_facies =
        lyr != nullptr &&
        is_facies_family_layer(templates_, lyr->id(), role);
    ctx.wkb_type = wkb_type;
    ctx.vector_writable = lyr != nullptr;
    ctx.editing = session != nullptr || native_open;
    ctx.dirty = (session != nullptr && session->is_dirty()) ||
                (native_open &&
                 native_editing_->pending_changes(lyr->id())
                         .value_or(false));
    ctx.edit_gate_open = gate_allowed;
    ctx.edit_gate_reason = gate_reason;
    ctx.can_undo = session != nullptr && session->undo_depth() > 0;
    ctx.can_redo = session != nullptr && session->redo_depth() > 0;
    ctx.selection_count =
        lyr ? static_cast<int>(lyr->selection().size()) : 0;
    ctx.selection_geometry_types = kinds_among_selection;
    ctx.compatible_polygon_count =
        (lyr != nullptr && session != nullptr &&
         kind_of(lyr->id()) == "polygon")
            ? static_cast<int>(lyr->selection().size())
            : 0;
    ctx.split_ready = split_ready;
    ctx.merge_ready = lyr != nullptr && kind_of(lyr->id()) == "polygon" &&
                      lyr->selection().size() >= 2 &&
                      (session != nullptr || native_open);
    ctx.reshape_ready =
        lyr != nullptr && session != nullptr &&
        (kind_of(lyr->id()) == "line" || kind_of(lyr->id()) == "polygon") &&
        lyr->selection().size() == 1;
    ctx.selection_multipart_count = facts.first;
    ctx.collect_ready = facts.second;
    ctx.snapping_enabled = snapping_.enabled;
    ctx.topology_enabled = topology_.enabled;
    ctx.avoid_intersections_enabled = avoid_intersections_enabled;
    ctx.tracing_enabled = tracing_enabled;
    ctx.vertex_all_layers = vertex_all_layers;
    ctx.snapping_tolerance_px = snapping_.pixel_tolerance;
    ctx.snapping_modes.assign(snapping_.modes.begin(),
                              snapping_.modes.end());
    if (auto rec = snapping_role_recommended(lyr); rec.has_value())
        ctx.snapping_role_recommended = *rec;
    ctx.crs_valid =
        project_crs.find_first_not_of(" \t\r\n") == std::string::npos ||
        crs_parseable(project_crs, crs_validator_);
    ctx.project_crs = project_crs;
    ctx.layer_crs = lyr ? lyr->crs() : "";
    std::vector<const VectorLayer*> layer_ptrs;
    for (const auto& [_, l] : layers_) layer_ptrs.push_back(l.get());
    ctx.topology_error_count = topology_.cached_error_count(layer_ptrs);
    ctx.current_tool =
        tools.active_tool() ? tools.active_tool()->tool_id : "pan";
    if (ctx.current_tool.empty()) ctx.current_tool = "pan";
    ctx.blocking_task = blocking_task_label;
    return ctx;
}

Json CompositeEditController::overlay_state() const {
    Json selected = Json::array();
    for (const auto& [_, lyr] : layers_) {
        if (lyr->selection().empty()) continue;
        const VectorEditSession* session = lyr->edit_session();
        for (const auto& fid : lyr->selection()) {
            try {
                const VectorFeature& feature =
                    session ? session->feature(fid) : lyr->feature(fid);
                selected.push_back(feature.as_record());
            } catch (const std::exception&) {
            }
        }
    }
    Json capture = Json::array();
    const MapTool* tool = tools.active_tool();
    if (auto* ct = dynamic_cast<const CaptureTool*>(tool)) {
        for (const auto& p : ct->points)
            capture.push_back(Json::array({p[0], p[1]}));
    }
    Json snap = Json();
    if (snapping_.last_match.has_value())
        snap = Json::array({snapping_.last_match->point[0],
                            snapping_.last_match->point[1]});
    // WORKAREA_LEGEND_ITEMS parity (label, colour) — workarea_map_snapshot
    // vocabulary, one data story keeps one look across pages.
    static const Json legend_items = Json::array(
        {Json::object({{"label", "工区边界"}, {"color", "#64748b"}}),
         Json::object({{"label", "地震工区"}, {"color", "#0d9488"}}),
         Json::object({{"label", "井位"}, {"color", "#409cff"}}),
         Json::object(
             {{"label", "井位（坐标待处理）"}, {"color", "#f59e0b"}})});
    return {{"selected_features", selected},
            {"capture_points", capture},
            {"snap_point", snap},
            {"decorations",
             {{"elements",
               Json::array({"比例尺", "指北针", "图例"})},
              {"legend_items", legend_items}}}};
}

}  // namespace pwb::ui_composite
