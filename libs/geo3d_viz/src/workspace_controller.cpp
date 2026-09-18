#include <pwb/geo3d_viz/workspace_controller.hpp>

#include <pwb/geomodel/builders.hpp>
#include <pwb/geomodel/measurements.hpp>
#include <pwb/geomodel/section.hpp>

#include <algorithm>
#include <cmath>

namespace pwb::geo3d_viz {

using pwb::domain::Json;
using pwb::geomodel::DomainError;
using pwb::geomodel::DomainObject;
using pwb::geomodel::HorizonGrid;
using pwb::geomodel::MeasurementResult;
using pwb::geomodel::QCReport;
using pwb::geomodel::Vec3;

// ---------------------------------------------------------------------------
// measure mode table + strict coercions
// ---------------------------------------------------------------------------

const std::vector<MeasureModeSpec>& measure_modes() {
    static const std::vector<MeasureModeSpec> modes = {
        {"point", "点坐标", 1},
        {"distance", "距离", 2},
        {"polyline", "折线长度", 3},
        {"vertical_difference", "高差", 2},
        {"thickness", "厚度", 1},
        {"plane_orientation", "产状", 3},
    };
    return modes;
}

const MeasureModeSpec* find_measure_mode(const std::string& mode) {
    for (const MeasureModeSpec& spec : measure_modes()) {
        if (mode == spec.mode) return &spec;
    }
    return nullptr;
}

bool state_as_bool(const Json& value, bool default_value) {
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_number()) {
        const double v = value.get<double>();
        if (v == 0.0) return false;
        if (v == 1.0) return true;
        return default_value;
    }
    if (value.is_string()) {
        std::string low = value.get<std::string>();
        std::transform(low.begin(), low.end(), low.begin(),
                       [](unsigned char c) { return std::tolower(c); });
        if (low == "true" || low == "1" || low == "yes" || low == "on") {
            return true;
        }
        if (low == "false" || low == "0" || low == "no" || low == "off" ||
            low.empty()) {
            return false;
        }
    }
    return default_value;
}

double state_as_float(const Json& value, double default_value, const double* lo,
                      const double* hi) {
    double out;
    if (value.is_number()) {
        out = value.get<double>();
    } else if (value.is_string()) {
        try {
            out = pwb::geomodel::py_float(value);
        } catch (const std::exception&) {
            return default_value;
        }
    } else {
        return default_value;
    }
    if (!std::isfinite(out)) return default_value;
    if (lo != nullptr) out = std::max(*lo, out);
    if (hi != nullptr) out = std::min(*hi, out);
    return out;
}

// ---------------------------------------------------------------------------
// ClipAxisState
// ---------------------------------------------------------------------------

Json ClipAxisState::to_json() const {
    Json state = Json::object();
    state["enabled"] = enabled;
    state["value"] = value;
    state["invert"] = invert;
    return state;
}

ClipAxisState ClipAxisState::from_json(const Json& value, bool* ok) {
    ClipAxisState state;
    if (ok != nullptr) *ok = false;
    if (!value.is_object()) return state;
    static const double kZero = 0.0;
    static const double kOne = 1.0;
    state.enabled = state_as_bool(
        value.contains("enabled") ? value["enabled"] : Json(false), false);
    state.value = state_as_float(
        value.contains("value") ? value["value"] : Json(0.5), 0.5, &kZero,
        &kOne);
    state.invert = state_as_bool(
        value.contains("invert") ? value["invert"] : Json(false), false);
    if (ok != nullptr) *ok = true;
    return state;
}

// ---------------------------------------------------------------------------
// construction / object management
// ---------------------------------------------------------------------------

Geo3DWorkspaceController::Geo3DWorkspaceController(
    std::function<SceneObjectManager*()> manager_provider, QObject* parent)
    : QObject(parent), assembly_("page-geo3d"), adapter_(std::move(manager_provider)) {
    clip_state_ = {{"x", ClipAxisState{}}, {"y", ClipAxisState{}},
                   {"z", ClipAxisState{}}};
}

void Geo3DWorkspaceController::set_viewport(Geo3DViewportFacade* facade) {
    facade_ = facade;
}

const DomainObject* Geo3DWorkspaceController::add_object(DomainObject object) {
    DomainObject* stored = nullptr;
    if (assembly_.contains(object.object_id)) {
        stored = &assembly_.replace(std::move(object));
    } else {
        try {
            stored = &assembly_.add(std::move(object));
        } catch (const DomainError& exc) {
            emit status_message(QString::fromStdString(
                std::string("对象被拒绝: ") + exc.what()));
            return nullptr;
        }
    }
    sync_scene();
    qc_single(*stored);
    return stored;
}

bool Geo3DWorkspaceController::remove_object(const std::string& object_id) {
    const bool removed = assembly_.remove(object_id);
    if (removed) {
        if (selected_id_.has_value() && *selected_id_ == object_id) {
            selected_id_.reset();
        }
        sync_scene();
        refresh_qc();
    }
    return removed;
}

int Geo3DWorkspaceController::clear(const std::optional<std::string>& kind) {
    const std::optional<std::string>& k = kind;
    const int n = assembly_.clear(
        k.has_value() ? std::optional<std::string>(*k) : std::nullopt);
    if (n) {
        sync_scene();
        refresh_qc();
    }
    return n;
}

void Geo3DWorkspaceController::reset() {
    // ModelAssembly carries a mutex (non-movable): reset in place.
    assembly_.clear(std::nullopt);
    assembly_.name = "page-geo3d";
    assembly_.display = Json::object();
    adapter_.reset();
    qc_report_ = QCReport();
    selected_id_.reset();
    measure_mode_.reset();
    measure_points_.clear();
    clip_state_ = {{"x", ClipAxisState{}}, {"y", ClipAxisState{}},
                   {"z", ClipAxisState{}}};
    view_presets_.clear();
    camera_.reset();
    measure_counters_.clear();
    refresh_qc();
}

void Geo3DWorkspaceController::set_visibility(const std::string& object_id,
                                              bool visible) {
    adapter_.set_visibility(object_id, visible);
}

bool Geo3DWorkspaceController::visibility(const std::string& object_id) const {
    return adapter_.visibility(object_id);
}

void Geo3DWorkspaceController::set_opacity(const std::string& object_id,
                                           double opacity) {
    adapter_.set_opacity(object_id, opacity);
}

void Geo3DWorkspaceController::sync_scene() { adapter_.sync(assembly_); }

// ---------------------------------------------------------------------------
// selection
// ---------------------------------------------------------------------------

void Geo3DWorkspaceController::set_selected(
    const std::optional<std::string>& object_id, bool broadcast) {
    selected_id_ = object_id;
    adapter_.set_selected(object_id);
    emit selection_changed(
        QString::fromStdString(object_id.value_or(std::string())));
    if (broadcast && object_id.has_value() &&
        object_id->rfind("well:", 0) == 0) {
        const DomainObject* object = assembly_.get(*object_id);
        const std::string well_name =
            object != nullptr ? object->name : *object_id;
        emit well_selected(QString::fromStdString(well_name));
    }
}

std::string Geo3DWorkspaceController::assembly_crs() const {
    for (const DomainObject& object : assembly_.objects()) {
        const std::string& crs = object.crs;
        if (!crs.empty() && crs != "unknown" && crs != "demo") return crs;
    }
    return "unknown";
}

std::optional<Bounds> Geo3DWorkspaceController::scene_bounds() const {
    if (facade_ == nullptr) return std::nullopt;
    return facade_->scene_bounds(false);
}

// ---------------------------------------------------------------------------
// QC
// ---------------------------------------------------------------------------

void Geo3DWorkspaceController::qc_single(const DomainObject& object) {
    QCReport fresh;
    for (const pwb::geomodel::QCIssue& issue : qc_report_.issues) {
        if (issue.object_id != object.object_id) fresh.add(issue);
    }
    QCReport own = pwb::geomodel::qc_object(object);
    fresh.extend(own);
    qc_report_ = fresh;
    emit qc_updated();
}

QCReport Geo3DWorkspaceController::refresh_qc() {
    qc_report_ = pwb::geomodel::qc_assembly(assembly_);
    emit qc_updated();
    return qc_report_;
}

namespace {

std::string html_escape(const std::string& text) {
    std::string out;
    out.reserve(text.size());
    for (const char c : text) {
        if (c == '&') out += "&amp;";
        else if (c == '<') out += "&lt;";
        else if (c == '>') out += "&gt;";
        else out += c;
    }
    return out;
}

}  // namespace

std::string Geo3DWorkspaceController::inspector_text(
    const std::optional<std::string>& object_id) const {
    const std::string oid = object_id.value_or(selected_id_.value_or(""));
    const DomainObject* object =
        !oid.empty() ? assembly_.get(oid) : nullptr;
    if (object == nullptr) return "未选中对象";
    const Json meta = object->meta();
    const Json stats = meta.contains("stats") && meta["stats"].is_object()
                           ? meta["stats"]
                           : Json::object();
    std::vector<std::string> lines;
    lines.push_back("<b>" +
                    html_escape(meta.value("name", oid)) + "</b>");
    lines.push_back("ID: " + html_escape(oid));
    lines.push_back("CRS: " + html_escape(meta.value("crs", "unknown")) +
                    " · 域: " +
                    html_escape(meta.value("vertical_domain", "depth")) +
                    " · 单位: " + html_escape(meta.value("unit", "m")));
    if (oid.rfind("well:", 0) == 0 || oid.rfind("fault:", 0) == 0) {
        lines.push_back("表示: " + html_escape(meta.value("representation", "")));
    }
    const Json prov = meta.contains("provenance") && meta["provenance"].is_object()
                          ? meta["provenance"]
                          : Json::object();
    std::string source_line =
        "来源: " + html_escape(prov.value("source_kind", "derived"));
    if (prov.contains("demo") && prov["demo"].is_boolean() &&
        prov["demo"].get<bool>()) {
        source_line += " (demo)";
    }
    lines.push_back(source_line);
    if (prov.contains("source_version_ids") &&
        prov["source_version_ids"].is_array() &&
        !prov["source_version_ids"].empty()) {
        std::string joined;
        for (const auto& v : prov["source_version_ids"]) {
            if (!joined.empty()) joined += ", ";
            joined += v.is_string() ? v.get<std::string>() : v.dump();
        }
        lines.push_back("源版本: " + html_escape(joined));
    }
    if (stats.contains("vertex_count") && !stats["vertex_count"].is_null()) {
        lines.push_back("顶点数: " +
                        std::to_string(stats.value("vertex_count", 0LL)));
    }
    const Json quality = meta.contains("quality") && meta["quality"].is_object()
                             ? meta["quality"]
                             : Json::object();
    for (const auto& [key, label] :
         {std::pair<const char*, const char*>{"column_count", "柱数"},
          {"closed", "闭合"}, {"min_thickness", "最小厚度"}}) {
        if (quality.contains(key)) {
            lines.push_back(std::string(label) + ": " +
                            (quality[key].is_string()
                                 ? quality[key].get<std::string>()
                                 : quality[key].dump()));
        }
    }
    const QCReport own = pwb::geomodel::qc_object(*object);
    lines.push_back("QC: " + own.worst());
    for (const pwb::geomodel::QCIssue& issue : own.issues) {
        if (issue.severity == "error" || issue.severity == "blocker" ||
            issue.severity == "warning") {
            lines.push_back("&nbsp;&nbsp;[" + issue.severity + "] " +
                            html_escape(issue.code) + ": " +
                            html_escape(issue.message));
        }
    }
    std::string out;
    for (std::size_t i = 0; i < lines.size(); ++i) {
        if (i) out += "<br>";
        out += lines[i];
    }
    return out;
}

// ---------------------------------------------------------------------------
// measurement tool
// ---------------------------------------------------------------------------

bool Geo3DWorkspaceController::set_measure_mode(
    const std::optional<std::string>& mode) {
    if (mode.has_value() && find_measure_mode(*mode) == nullptr) return false;
    measure_mode_ = mode;
    measure_points_.clear();
    if (mode.has_value()) {
        const MeasureModeSpec* spec = find_measure_mode(*mode);
        emit status_message(QString::fromStdString(
            std::string("测量模式: ") + spec->label + "（在 3D 视图点击对象）"));
    }
    return true;
}

std::optional<DomainPick> Geo3DWorkspaceController::pick_via_facade(
    double px, double py) {
    if (facade_ == nullptr) return std::nullopt;
    const std::optional<PickHit> hit = facade_->pick_at(px, py, {});
    if (!hit.has_value()) return std::nullopt;
    return adapter_.resolve_pick(*hit);
}

bool Geo3DWorkspaceController::handle_viewport_click(double px, double py) {
    const std::optional<DomainPick> pick = pick_via_facade(px, py);
    if (!pick.has_value()) {
        if (measure_mode_.has_value()) {
            emit status_message(QStringLiteral("未命中可拾取对象"));
            return true;
        }
        return false;
    }
    if (!measure_mode_.has_value()) {
        set_selected(pick->object_id);
        const DomainObject* object = assembly_.get(pick->object_id);
        if (object != nullptr) {
            emit status_message(
                QString::fromStdString("选中: " + object->name));
        }
        return true;
    }
    const std::string kind = *measure_mode_;
    measure_points_.push_back(pick->domain_xyz);
    const MeasureModeSpec* spec = find_measure_mode(kind);
    if (kind == "thickness") return finish_thickness_pick();
    if (static_cast<int>(measure_points_.size()) >= spec->points_needed) {
        finish_measurement(kind);
    } else {
        emit status_message(QString::fromStdString(
            "测量: 已选 " + std::to_string(measure_points_.size()) + "/" +
            std::to_string(spec->points_needed) + " 点"));
    }
    return true;
}

const DomainObject* Geo3DWorkspaceController::first_of_kind(
    const std::string& kind,
    const std::vector<std::string>& name_hints) const {
    const std::vector<DomainObject> objects = assembly_.objects(kind);
    if (objects.empty()) return nullptr;
    for (const std::string& hint : name_hints) {
        const std::string lowered = [&hint] {
            std::string out = hint;
            std::transform(out.begin(), out.end(), out.begin(),
                           [](unsigned char c) { return std::tolower(c); });
            return out;
        }();
        for (const DomainObject& object : objects) {
            std::string name_low = object.name;
            std::transform(name_low.begin(), name_low.end(), name_low.begin(),
                           [](unsigned char c) { return std::tolower(c); });
            if (name_low.find(lowered) != std::string::npos) {
                return assembly_.get(object.object_id);
            }
        }
    }
    return assembly_.get(objects.front().object_id);
}

HorizonGrid Geo3DWorkspaceController::horizon_grid(
    const DomainObject& horizon) const {
    HorizonGrid grid;
    grid.rows = static_cast<int>(horizon.z_grid.size());
    grid.cols = grid.rows > 0 ? static_cast<int>(horizon.z_grid[0].size()) : 0;
    grid.origin_x = horizon.origin[0];
    grid.origin_y = horizon.origin[1];
    grid.spacing_y = horizon.spacing[0];
    grid.spacing_x = horizon.spacing[1];
    grid.vertical_domain = horizon.vertical_domain;
    grid.unit = horizon.unit;
    grid.object_id = horizon.object_id;
    grid.z.reserve(static_cast<std::size_t>(grid.rows) *
                   static_cast<std::size_t>(grid.cols));
    for (const auto& row : horizon.z_grid) {
        for (double v : row) grid.z.push_back(v);
    }
    return grid;
}

bool Geo3DWorkspaceController::finish_thickness_pick() {
    const auto [x, y, z] = measure_points_.back();
    (void)z;
    const DomainObject* top =
        first_of_kind("horizon", {"top", "顶"});
    const DomainObject* base =
        first_of_kind("horizon", {"base", "底"});
    if (top == nullptr || base == nullptr || top->object_id == base->object_id) {
        emit status_message(
            QStringLiteral("厚度测量需要两个不同的层位面对象（名称含 top/顶 与 base/底）"));
        measure_points_.clear();
        return true;
    }
    try {
        // Python thickness_at(x, y, top, base) defaults crs/unit to the
        // top horizon's values.
        const MeasurementResult record = pwb::geomodel::thickness_at(
            x, y, horizon_grid(*top), horizon_grid(*base), top->crs,
            top->unit);
        emit_measurement(record, {{x, y, z}});
    } catch (const std::exception& exc) {
        emit status_message(
            QString::fromStdString(std::string("测量失败: ") + exc.what()));
        measure_points_.clear();
        return true;
    }
    return true;
}

void Geo3DWorkspaceController::finish_measurement(const std::string& kind) {
    const std::vector<std::array<double, 3>> pts = measure_points_;
    measure_points_.clear();
    const std::string crs = assembly_crs();
    const auto vec = [](const std::array<double, 3>& p) {
        return Vec3{p[0], p[1], p[2]};
    };
    try {
        if (kind == "point") {
            emit_measurement(pwb::geomodel::point_coordinate(vec(pts[0]), crs), pts);
        } else if (kind == "distance") {
            emit_measurement(pwb::geomodel::distance(vec(pts[0]), vec(pts[1]), crs),
                             pts);
        } else if (kind == "polyline") {
            std::vector<Vec3> poly;
            poly.reserve(pts.size());
            for (const auto& p : pts) poly.push_back(vec(p));
            emit_measurement(pwb::geomodel::polyline_length(poly, crs), pts);
        } else if (kind == "vertical_difference") {
            emit_measurement(
                pwb::geomodel::vertical_difference(vec(pts[0]), vec(pts[1]), crs),
                pts);
        } else if (kind == "plane_orientation") {
            std::vector<Vec3> poly;
            poly.reserve(pts.size());
            for (const auto& p : pts) poly.push_back(vec(p));
            emit_measurement(pwb::geomodel::plane_orientation(poly, crs), pts);
        }
    } catch (const std::exception& exc) {
        emit status_message(
            QString::fromStdString(std::string("测量失败: ") + exc.what()));
    }
}

void Geo3DWorkspaceController::emit_measurement(
    MeasurementResult result,
    const std::vector<std::array<double, 3>>& points) {
    // MeasurementRecord construction mirroring the Python measurement
    // kernels: counter id scheme measure:<counter-kind>-<n> (vert/plane are
    // the counter kinds for vertical_difference/plane_orientation) and the
    // display names Point/Distance/Polyline/Vertical Δ/Thickness/Plane.
    static const std::map<std::string, std::pair<std::string, std::string>>
        kIdsAndNames = {
            {"point", {"point", "Point"}},
            {"distance", {"distance", "Distance"}},
            {"polyline", {"polyline", "Polyline"}},
            {"vertical_difference", {"vert", "Vertical Δ"}},
            {"thickness", {"thickness", "Thickness"}},
            {"plane_orientation", {"plane", "Plane"}},
        };
    const auto naming = kIdsAndNames.find(result.measurement_kind);
    const std::string counter_kind =
        naming != kIdsAndNames.end() ? naming->second.first
                                     : result.measurement_kind;
    const std::string display_name =
        naming != kIdsAndNames.end() ? naming->second.second
                                     : result.measurement_kind;
    DomainObject record;
    record.object_id = "measure:" + counter_kind + "-" +
                       std::to_string(++measure_counters_[counter_kind]);
    record.name = display_name;
    record.crs = result.crs.empty() ? "unknown" : result.crs;
    record.unit = result.unit.empty() ? "m" : result.unit;
    record.measurement_kind = result.measurement_kind;
    for (const auto& p : points) record.points.push_back({p[0], p[1], p[2]});
    record.result = result.result;
    Json extra = Json::object();
    if (result.measurement_kind == "plane_orientation") {
        extra["strike_deg"] = result.strike_deg;
        extra["dip_deg"] = result.dip_deg;
        extra["note"] =
            "dip result; strike in extra — planarity<0.05 means picks are "
            "near-collinear";
    } else if (result.measurement_kind == "vertical_difference") {
        extra["dz"] = result.result.value_or(result.dz);
    } else if (result.measurement_kind == "thickness") {
        extra["top_id"] = result.top_id;
        extra["base_id"] = result.base_id;
        extra["signed"] = result.signed_dz;
    } else if (result.measurement_kind == "point") {
        extra["x"] = result.extra_x;
        extra["y"] = result.extra_y;
        extra["z"] = result.extra_z;
    } else if (result.measurement_kind == "distance") {
        extra["unit"] = result.unit.empty() ? "m" : result.unit;
    } else if (result.measurement_kind == "polyline") {
        extra["legs"] = result.legs;
    }
    record.extra = extra;

    // Id uniqueness is the assembly's invariant: resolve a free suffix
    // instead of letting DomainError escape into the click handler.
    DomainObject candidate = record;
    try {
        candidate.validate();
    } catch (const DomainError& exc) {
        emit status_message(QString::fromStdString("测量失败: " + std::string(exc.what())));
        return;
    }
    int suffix = 1;
    for (;;) {
        try {
            assembly_.add(candidate);
            break;
        } catch (const DomainError& exc) {
            const std::string message = exc.what();
            if (message.find("duplicate object_id") == std::string::npos) {
                emit status_message(QString::fromStdString("测量失败: " + message));
                return;
            }
            ++suffix;
            const std::string base =
                record.object_id.substr(0, record.object_id.rfind('-'));
            candidate = record;
            candidate.object_id = base + "-" + std::to_string(suffix);
        }
    }
    sync_scene();
    emit measurements_changed();
    emit status_message(QString::fromStdString(
        candidate.name + ": " + pwb::geomodel::format_result(result)));
}

// ---------------------------------------------------------------------------
// clipping
// ---------------------------------------------------------------------------

void Geo3DWorkspaceController::set_axis_clip(const std::string& axis,
                                             bool enabled, double value01,
                                             bool invert) {
    if (axis != "x" && axis != "y" && axis != "z") return;
    ClipAxisState state;
    state.enabled = enabled;
    state.value = value01;
    state.invert = invert;
    clip_state_[axis] = state;
    apply_clip_state();
}

void Geo3DWorkspaceController::apply_clip_state() {
    std::vector<ClipEquation> planes;
    const std::optional<Bounds> bounds = scene_bounds();
    for (const char* axis : {"x", "y", "z"}) {
        const auto it = clip_state_.find(axis);
        if (it == clip_state_.end() || !it->second.enabled) continue;
        if (!bounds.has_value()) {
            // No scene bounds yet (empty viewport): applying a hardcoded
            // extent would clip with fabricated coordinates — skip.
            continue;
        }
        const int axis_index = axis == "x" ? 0 : axis == "y" ? 1 : 2;
        const double lo = bounds->first[axis_index];
        const double hi = bounds->second[axis_index];
        const double value = lo + (hi - lo) * it->second.value;
        const pwb::geomodel::Plane plane =
            pwb::geomodel::axis_plane(axis, value);
        planes.push_back(plane.as_clip_equation(it->second.invert));
    }
    adapter_.set_clip_planes(planes.empty()
                                 ? std::nullopt
                                 : std::optional<std::vector<ClipEquation>>(planes));
}

void Geo3DWorkspaceController::reset_clip() {
    clip_state_ = {{"x", ClipAxisState{}}, {"y", ClipAxisState{}},
                   {"z", ClipAxisState{}}};
    apply_clip_state();
}

// ---------------------------------------------------------------------------
// camera / view presets
// ---------------------------------------------------------------------------

std::optional<CameraPose> Geo3DWorkspaceController::capture_camera() {
    if (facade_ != nullptr) {
        if (const std::optional<CameraPose> pose = facade_->camera_pose()) {
            camera_ = pose;
        }
    }
    return camera_;
}

bool Geo3DWorkspaceController::save_view_preset(const std::string& name) {
    const std::optional<CameraPose> pose = capture_camera();
    if (!pose.has_value() || pose->distance == 0.0) {
        emit status_message(QStringLiteral("视口未就绪，无法保存视图"));
        return false;
    }
    view_presets_[name] = *pose;
    return true;
}

bool Geo3DWorkspaceController::restore_view_preset(const std::string& name) {
    const auto it = view_presets_.find(name);
    if (it == view_presets_.end()) return false;
    if (facade_ == nullptr) return false;
    facade_->apply_camera_pose(it->second);
    return true;
}

bool Geo3DWorkspaceController::fit_all() {
    if (facade_ == nullptr) return false;
    return facade_->fit_objects(std::nullopt);
}

bool Geo3DWorkspaceController::fit_selected() {
    if (facade_ == nullptr || !selected_id_.has_value()) return false;
    const std::vector<std::string> names = adapter_.derived_names(*selected_id_);
    if (names.empty()) return false;
    return facade_->fit_objects(names);
}

// ---------------------------------------------------------------------------
// persistence
// ---------------------------------------------------------------------------

Json Geo3DWorkspaceController::save_state() {
    Json meta_objects = Json::array();
    Json measurements = Json::array();
    for (const DomainObject& object : assembly_.objects()) {
        if (object.kind() == "measure") {
            measurements.push_back(object.meta());
            continue;
        }
        if (object.provenance.demo) continue;  // demo objects never persist
        meta_objects.push_back(object.meta());
    }
    Json display = Json::object();
    for (const std::string& oid : assembly_.ids()) {
        display[oid] = adapter_.display_state(oid);
    }
    Json clip = Json::object();
    for (const char* axis : {"x", "y", "z"}) {
        clip[axis] = clip_state_.at(axis).to_json();
    }
    Json camera = Json::object();
    if (const std::optional<CameraPose> pose = capture_camera()) {
        camera["distance"] = pose->distance;
        camera["elevation"] = pose->elevation_deg;
        camera["azimuth"] = pose->azimuth_deg;
    }
    Json views = Json::array();  // sorted by name (ordered map iteration)
    for (const auto& [name, pose] : view_presets_) {
        Json view = Json::object();
        view["name"] = name;
        view["distance"] = pose.distance;
        view["elevation"] = pose.elevation_deg;
        view["azimuth"] = pose.azimuth_deg;
        views.push_back(view);
    }
    Json payload = Json::object();
    payload["objects"] = meta_objects;
    payload["measurements"] = measurements;
    payload["display"] = display;
    payload["clip"] = clip;
    payload["camera"] = camera;
    payload["views"] = views;
    payload["selected"] = selected_id_.value_or(std::string());
    return payload;
}

std::vector<std::string> Geo3DWorkspaceController::restore_state(
    const Json& payload) {
    if (!payload.is_object() || payload.empty()) return {};
    // ModelAssembly carries a mutex (non-movable): reset in place.
    assembly_.clear(std::nullopt);
    assembly_.name = "page-geo3d";
    assembly_.display = Json::object();
    measure_counters_.clear();
    std::vector<std::string> restored;
    if (payload.contains("objects") && payload["objects"].is_array()) {
        for (const Json& entry : payload["objects"]) {
            if (!entry.is_object()) continue;
            const std::string oid = entry.contains("object_id") &&
                                            entry["object_id"].is_string()
                                        ? entry["object_id"].get<std::string>()
                                        : "";
            const std::string kind = oid.substr(0, oid.find(':'));
            if (kind != "well" && kind != "horizon" && kind != "fault" &&
                kind != "volume" && kind != "tunnel") {
                continue;
            }
            try {
                DomainObject object = DomainObject::from_meta(entry);
                object.validate();
                if (!object.provenance.demo) {
                    assembly_.add(std::move(object));
                    restored.push_back(oid);
                }
            } catch (const std::exception&) {
                // Corrupted-but-typed entries degrade per object (ADR-03).
            }
        }
    }
    if (payload.contains("measurements") && payload["measurements"].is_array()) {
        for (const Json& entry : payload["measurements"]) {
            if (!entry.is_object()) continue;
            try {
                DomainObject record = DomainObject::from_meta(entry);
                record.validate();
                assembly_.add(std::move(record));
                restored.push_back(entry.value("object_id", ""));
            } catch (const std::exception&) {
                // degrade per entry
            }
        }
    }
    if (payload.contains("display") && payload["display"].is_object()) {
        adapter_.restore_display(payload["display"]);
    }
    if (payload.contains("clip") && payload["clip"].is_object()) {
        const Json& clip = payload["clip"];
        for (const char* axis : {"x", "y", "z"}) {
            if (clip.contains(axis) && clip[axis].is_object()) {
                clip_state_[axis] = ClipAxisState::from_json(clip[axis]);
            }
        }
    }
    if (payload.contains("camera") && payload["camera"].is_object()) {
        const Json& camera = payload["camera"];
        if (!camera.empty()) {
            // Python keeps any finite float triple ({k: _as_float(v, 0.0)}).
            CameraPose pose;
            pose.distance = state_as_float(
                camera.contains("distance") ? camera["distance"] : Json(0.0),
                0.0);
            pose.elevation_deg = state_as_float(
                camera.contains("elevation") ? camera["elevation"] : Json(0.0),
                0.0);
            pose.azimuth_deg = state_as_float(
                camera.contains("azimuth") ? camera["azimuth"] : Json(0.0),
                0.0);
            camera_ = pose;
        } else {
            camera_.reset();
        }
    }
    view_presets_.clear();
    if (payload.contains("views") && payload["views"].is_array()) {
        int index = 0;
        for (const Json& view : payload["views"]) {
            const int i = index++;
            if (!view.is_object()) continue;
            const std::string name =
                view.contains("name") && view["name"].is_string()
                    ? view["name"].get<std::string>()
                    : "view-" + std::to_string(i);
            CameraPose pose;
            const double lo = 1.0;
            const double elev_lo = -89.0;
            const double elev_hi = 89.0;
            pose.distance = state_as_float(
                view.contains("distance") ? view["distance"] : Json(250.0),
                250.0, &lo);
            pose.elevation_deg = state_as_float(
                view.contains("elevation") ? view["elevation"] : Json(30.0),
                30.0, &elev_lo, &elev_hi);
            pose.azimuth_deg = state_as_float(
                view.contains("azimuth") ? view["azimuth"] : Json(-45.0),
                -45.0);
            view_presets_[name] = pose;
        }
    }
    sync_scene();
    apply_clip_state();
    refresh_qc();
    const std::string selected =
        payload.contains("selected") && payload["selected"].is_string()
            ? payload["selected"].get<std::string>()
            : "";
    if (!selected.empty() && assembly_.contains(selected)) {
        set_selected(selected, false);
    }
    return restored;
}

}  // namespace pwb::geo3d_viz
