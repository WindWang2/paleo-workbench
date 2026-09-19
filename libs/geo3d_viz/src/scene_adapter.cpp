#include <pwb/geo3d_viz/scene_adapter.hpp>

#include <pwb/domain/sha256.hpp>
#include <pwb/geomodel/builders.hpp>
#include <pwb/geomodel/measurements.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <stdexcept>

namespace pwb::geo3d_viz {

using pwb::domain::Json;
using pwb::geomodel::DomainObject;

namespace {

std::string format_double(double v) {
    char buffer[40];
    std::snprintf(buffer, sizeof(buffer), "%.17g", v);
    return buffer;
}

std::string format_double_array(const std::array<double, 2>& v) {
    return "(" + format_double(v[0]) + "," + format_double(v[1]) + ")";
}

// scene_adapter._finite_checksum port: full-array digest with NaN/±inf
// canonicalized to 0.0. Python uses blake2b(digest_size=12); the token is
// internal-only (never persisted), so a Sha256 digest keeps the same
// cross-process determinism guarantee.
std::string finite_checksum_doubles(const std::vector<double>& values,
                                    std::size_t count) {
    if (count == 0) return "(0,)";
    std::string canonical;
    canonical.reserve(count * 8);
    for (std::size_t i = 0; i < count; ++i) {
        const double c = std::isfinite(values[i]) ? values[i] : 0.0;
        unsigned char bytes[8];
        std::memcpy(bytes, &c, 8);
        canonical.append(reinterpret_cast<const char*>(bytes), 8);
    }
    return "(" + std::to_string(count) + ",'" +
           pwb::domain::Sha256::of_bytes(canonical).substr(0, 24) + "')";
}

std::vector<double> flatten_verts(
    const std::vector<pwb::geomodel::Vec3>& verts) {
    std::vector<double> out;
    out.reserve(verts.size() * 3);
    for (const auto& v : verts) {
        out.push_back(v[0]);
        out.push_back(v[1]);
        out.push_back(v[2]);
    }
    return out;
}

}  // namespace

// ---------------------------------------------------------------------------
// SceneSyncReport / SceneTransform
// ---------------------------------------------------------------------------

std::string SceneSyncReport::to_string() const {
    return "+" + std::to_string(added.size()) + " ~" +
           std::to_string(updated.size()) + " -" +
           std::to_string(removed.size()) + " =" + std::to_string(unchanged);
}

std::vector<std::array<double, 3>> SceneTransform::forward(
    const std::vector<std::array<double, 3>>& world) const {
    if (!to_render || world.empty()) return world;
    return to_render(world);
}

std::vector<std::array<double, 3>> SceneTransform::inverse(
    const std::vector<std::array<double, 3>>& render) const {
    if (!to_domain || render.empty()) return render;
    return to_domain(render);
}

// ---------------------------------------------------------------------------
// construction / teardown
// ---------------------------------------------------------------------------

GeologicalSceneAdapter::GeologicalSceneAdapter(ManagerProvider provider,
                                               ObjectStyle styles)
    : provider_(std::move(provider)), styles_(styles) {}

void GeologicalSceneAdapter::set_scene_transform(SceneTransform transform) {
    transform_ = std::move(transform);
}

void GeologicalSceneAdapter::shutdown() {
    reset();
    provider_ = nullptr;
}

void GeologicalSceneAdapter::reset() {
    if (SceneObjectManager* manager = provider_()) {
        for (const auto& [oid, names] : derived_) {
            (void)oid;
            for (const std::string& name : names) manager->remove(name);
        }
    }
    synced_tokens_.clear();
    derived_.clear();
    visibility_.clear();
    opacity_.clear();
    overlays_.clear();
    selected_.reset();
}

std::vector<std::array<double, 3>> GeologicalSceneAdapter::to_render(
    const std::vector<std::array<double, 3>>& world) const {
    return transform_.forward(world);
}

Rgba GeologicalSceneAdapter::base_color(const std::string& name_or_id) const {
    const std::string oid = name_or_id.substr(0, name_or_id.find('#'));
    const std::string kind = oid.substr(0, oid.find(':'));
    if (kind == "well") return styles_.well_color;
    if (kind == "horizon") return styles_.horizon_color;
    if (kind == "fault") return styles_.fault_color;
    if (kind == "volume") return styles_.volume_color;
    if (kind == "tunnel") return styles_.tunnel_color;
    if (kind == "measure") return styles_.measurement_color;
    return styles_.color;
}

// ---------------------------------------------------------------------------
// payload tokens (content address; scene identity participates)
// ---------------------------------------------------------------------------

std::optional<std::string> GeologicalSceneAdapter::payload_token(
    const DomainObject& object) const {
    const std::string kind = object.kind();
    const std::string vis =
        visibility_.count(object.object_id) ? (visibility_.at(object.object_id) ? "1" : "0") : "1";
    if (kind == "well") {
        if (object.stations.empty()) return std::nullopt;
        double sum = 0.0;
        for (const auto& st : object.stations) {
            sum += st[0] + st[1] + st[2] + st[3];
        }
        return "('well'," + std::to_string(object.version) + "," +
               std::to_string(object.stations.size()) + ",'" +
               object.representation + "'," + format_double(sum) + "," +
               format_double(styles_.well_width) + "," +
               (styles_.show_well_labels ? "True" : "False") + "," + vis +
               ",'" + scene_identity_ + "')";
    }
    if (kind == "horizon") {
        std::vector<double> flat;
        std::size_t rows = object.z_grid.size();
        std::size_t cols = rows ? object.z_grid[0].size() : 0;
        for (const auto& row : object.z_grid) {
            for (double z : row) flat.push_back(z);
        }
        if (flat.empty()) return std::nullopt;
        return "('horizon'," + std::to_string(object.version) + ",(" +
               std::to_string(rows) + "," + std::to_string(cols) + ")," +
               finite_checksum_doubles(flat, flat.size()) + "," +
               format_double_array(object.origin) + "," +
               format_double_array(object.spacing) + "," + vis + ",'" +
               scene_identity_ + "')";
    }
    if (kind == "fault") {
        if (object.verts.empty()) return std::nullopt;
        const std::vector<double> flat = flatten_verts(object.verts);
        return "('fault'," + std::to_string(object.version) + "," +
               std::to_string(object.verts.size()) + "," +
               std::to_string(object.faces.size()) + "," +
               finite_checksum_doubles(flat, flat.size()) + ",'" +
               object.representation + "'," + vis + ",'" + scene_identity_ +
               "')";
    }
    if (kind == "volume") {
        if (object.verts.empty()) return std::nullopt;
        const std::vector<double> flat = flatten_verts(object.verts);
        return "('volume'," + std::to_string(object.version) + "," +
               std::to_string(object.verts.size()) + "," +
               std::to_string(object.faces.size()) + "," +
               finite_checksum_doubles(flat, flat.size()) + "," + vis + ",'" +
               scene_identity_ + "')";
    }
    if (kind == "tunnel") {
        if (object.path.empty()) return std::nullopt;
        const std::vector<double> flat = flatten_verts(object.path);
        return "('tunnel'," + std::to_string(object.version) + "," +
               std::to_string(object.path.size()) + "," +
               format_double(object.radius) + "," +
               finite_checksum_doubles(flat, flat.size()) + "," + vis + ",'" +
               scene_identity_ + "')";
    }
    if (kind == "measure") {
        if (object.points.empty()) return std::nullopt;
        const std::vector<double> flat = flatten_verts(object.points);
        return "('measure'," + std::to_string(object.version) + "," +
               std::to_string(object.points.size()) + "," +
               finite_checksum_doubles(flat, flat.size()) + ",'" +
               object.measurement_kind + "'," + vis + ",'" + scene_identity_ +
               "')";
    }
    return std::nullopt;
}

// ---------------------------------------------------------------------------
// sync
// ---------------------------------------------------------------------------

SceneSyncReport GeologicalSceneAdapter::sync(
    const pwb::geomodel::ModelAssembly& assembly) {
    SceneSyncReport report;
    SceneObjectManager* manager = provider_();
    if (manager == nullptr) return report;  // viewport absent: record nothing

    const std::vector<std::string> live_ids = assembly.ids();
    // Removals first (also drops derived names + per-object view state).
    for (const auto& [oid, token] : synced_tokens_) {
        (void)token;
        if (std::find(live_ids.begin(), live_ids.end(), oid) == live_ids.end()) {
            remove_tree(*manager, oid);
            report.removed.push_back(oid);
        }
    }
    for (const auto& oid : report.removed) {
        synced_tokens_.erase(oid);
        visibility_.erase(oid);
        opacity_.erase(oid);
    }

    for (const DomainObject& object : assembly.objects()) {
        const std::optional<std::string> token = payload_token(object);
        if (!token.has_value()) continue;  // not renderable right now
        const auto prev = synced_tokens_.find(object.object_id);
        if (prev != synced_tokens_.end() && prev->second == *token) {
            ++report.unchanged;
            continue;
        }
        std::optional<std::vector<std::string>> derived =
            build_payloads(*manager, object);
        if (!derived.has_value()) continue;
        const bool had_previous = synced_tokens_.count(object.object_id) != 0;
        derived_[object.object_id] = *derived;
        synced_tokens_[object.object_id] = *token;
        if (had_previous) {
            report.updated.push_back(object.object_id);
        } else {
            report.added.push_back(object.object_id);
        }
    }
    prune_state(live_ids);
    return report;
}

void GeologicalSceneAdapter::prune_state(
    const std::vector<std::string>& live_ids) {
    // Collect first, then erase (never invalidate the range-for iterator).
    std::vector<std::string> gone;
    for (const auto& [oid, token] : synced_tokens_) {
        (void)token;
        if (std::find(live_ids.begin(), live_ids.end(), oid) ==
            live_ids.end()) {
            gone.push_back(oid);
        }
    }
    for (const std::string& oid : gone) {
        synced_tokens_.erase(oid);
        derived_.erase(oid);
        visibility_.erase(oid);
        opacity_.erase(oid);
    }
}

std::optional<std::vector<std::string>> GeologicalSceneAdapter::build_payloads(
    SceneObjectManager& manager, const DomainObject& object) {
    // Replace semantics: previous derived objects go first.
    remove_tree(manager, object.object_id);
    const std::string kind = object.kind();
    try {
        if (kind == "well") return build_well(manager, object);
        if (kind == "horizon") return build_horizon(manager, object);
        if (kind == "fault") return build_fault(manager, object);
        if (kind == "volume") return build_volume(manager, object);
        if (kind == "tunnel") return build_tunnel(manager, object);
        if (kind == "measure") return build_measurement(manager, object);
    } catch (const std::exception&) {
        return std::nullopt;  // payload build failed: token not recorded
    }
    return std::nullopt;
}

void GeologicalSceneAdapter::remove_tree(SceneObjectManager& manager,
                                         const std::string& oid) {
    const auto it = derived_.find(oid);
    if (it == derived_.end()) return;
    for (const std::string& name : it->second) manager.remove(name);
    derived_.erase(it);
}

// ---------------------------------------------------------------------------
// payload builders
// ---------------------------------------------------------------------------

std::optional<std::vector<std::string>> GeologicalSceneAdapter::build_well(
    SceneObjectManager& manager, const DomainObject& well) {
    const std::string oid = well.object_id;
    const Rgba color = (selected_.has_value() && *selected_ == oid)
                           ? styles_.selected_color
                           : styles_.well_color;
    std::vector<std::array<double, 3>> world;
    world.reserve(well.stations.size());
    for (const auto& st : well.stations) {
        world.push_back({st[1], st[2], st[3]});
    }
    const std::vector<std::array<double, 3>> render = to_render(world);
    const auto to_f = [](const std::array<double, 3>& p) {
        return Vec3f{static_cast<float>(p[0]), static_cast<float>(p[1]),
                     static_cast<float>(p[2])};
    };
    std::vector<std::string> names;
    if (render.size() >= 2) {
        SceneObject line;
        line.name = oid;
        line.kind = ObjectKind::Well;
        line.mode = ObjectMode::Lines;
        line.line_strip = true;
        line.verts.reserve(render.size());
        for (const auto& p : render) line.verts.push_back(to_f(p));
        line.color = color;
        line.pickable = true;
        line.pick_radius = 2.0f;
        line.width = styles_.well_width;
        line.opacity = opacity_.count(oid) ? static_cast<float>(opacity_.at(oid)) : 1.0f;
        line.clip_planes = clip_planes_;
        manager.add(std::move(line));
        names.push_back(oid);
    }
    if (!render.empty()) {
        SceneObject head;
        const std::string head_name = oid + "#head";
        head.name = head_name;
        head.kind = ObjectKind::Well;
        head.mode = ObjectMode::Points;
        head.verts.push_back(to_f(render.front()));
        head.color = color;
        head.size = 9.0f;
        head.clip_planes = clip_planes_;
        manager.add(std::move(head));
        names.push_back(head_name);
    }
    if (styles_.show_well_labels && !render.empty()) {
        SceneObject label;
        const std::string label_name = oid + "#label";
        label.name = label_name;
        label.kind = ObjectKind::Well;
        label.mode = ObjectMode::Text;
        label.verts.push_back(to_f(render.front()));
        label.text = well.name;
        label.color = color;
        label.clip_planes = clip_planes_;
        manager.add(std::move(label));
        names.push_back(label_name);
    }
    return names;
}

std::optional<std::vector<std::string>> GeologicalSceneAdapter::build_horizon(
    SceneObjectManager& manager, const DomainObject& horizon) {
    const std::string oid = horizon.object_id;
    std::array<double, 2> origin = horizon.origin;
    std::array<double, 2> spacing = horizon.spacing;
    // Deterministic decimation ceiling (G12): stride-thin per axis so a
    // huge interpretation grid cannot explode the scene; QC always audits
    // the full-resolution grid.
    const std::size_t n_i = horizon.z_grid.size();
    const std::size_t n_x = n_i ? horizon.z_grid[0].size() : 0;
    if (n_i == 0 || n_x == 0) return std::vector<std::string>{};
    const auto stride = [](std::size_t n) {
        const std::size_t span = std::max<std::size_t>(n - 1, 1);
        return std::max<std::size_t>(1, (span + kMaxHorizonDim - 1) / kMaxHorizonDim);
    };
    const std::size_t sy = stride(n_i);
    const std::size_t sx = stride(n_x);
    std::vector<std::vector<double>> g;
    std::size_t rows = 0;
    std::size_t cols = 0;
    if (sy > 1 || sx > 1) {
        for (std::size_t i = 0; i < n_i; i += sy) {
            std::vector<double> row;
            for (std::size_t j = 0; j < n_x; j += sx) row.push_back(horizon.z_grid[i][j]);
            g.push_back(std::move(row));
        }
        rows = g.size();
        cols = rows ? g[0].size() : 0;
        spacing = {spacing[0] * static_cast<double>(sy),
                   spacing[1] * static_cast<double>(sx)};
    } else {
        g = horizon.z_grid;
        rows = n_i;
        cols = n_x;
    }
    std::vector<double> z;
    z.reserve(rows * cols);
    for (const auto& row : g) {
        for (double v : row) z.push_back(v);
    }
    pwb::geomodel::HorizonGrid grid;
    grid.rows = static_cast<int>(rows);
    grid.cols = static_cast<int>(cols);
    grid.origin_x = origin[0];
    grid.origin_y = origin[1];
    grid.spacing_y = spacing[0];
    grid.spacing_x = spacing[1];
    grid.z = std::move(z);
    const pwb::geomodel::TriMesh mesh = pwb::geomodel::triangulate_heightfield(grid);
    if (mesh.faces.empty()) return std::vector<std::string>{};
    std::vector<std::array<double, 3>> world;
    world.reserve(mesh.verts.size());
    for (const auto& v : mesh.verts) world.push_back({v[0], v[1], v[2]});
    const std::vector<std::array<double, 3>> render = to_render(world);
    if (render.empty()) return std::vector<std::string>{};
    SceneObject object;
    object.name = oid;
    object.kind = ObjectKind::Horizon;
    object.mode = ObjectMode::Mesh;
    object.verts.reserve(render.size());
    for (const auto& p : render) {
        object.verts.push_back({static_cast<float>(p[0]), static_cast<float>(p[1]),
                                static_cast<float>(p[2])});
    }
    object.faces = mesh.faces;
    object.color = (selected_.has_value() && *selected_ == oid)
                       ? styles_.selected_color
                       : styles_.horizon_color;
    object.pickable = true;
    object.opacity = opacity_.count(oid) ? static_cast<float>(opacity_.at(oid)) : 1.0f;
    object.clip_planes = clip_planes_;
    manager.add(std::move(object));
    return std::vector<std::string>{oid};
}

std::optional<std::vector<std::string>> GeologicalSceneAdapter::build_fault(
    SceneObjectManager& manager, const DomainObject& fault) {
    const std::string oid = fault.object_id;
    std::vector<std::array<double, 3>> world;
    world.reserve(fault.verts.size());
    for (const auto& v : fault.verts) world.push_back({v[0], v[1], v[2]});
    const std::vector<std::array<double, 3>> render = to_render(world);
    if (render.empty()) return std::vector<std::string>{};
    SceneObject object;
    object.name = oid;
    object.kind = ObjectKind::Fault;
    object.mode = ObjectMode::Mesh;
    object.verts.reserve(render.size());
    for (const auto& p : render) {
        object.verts.push_back({static_cast<float>(p[0]), static_cast<float>(p[1]),
                                static_cast<float>(p[2])});
    }
    object.faces = fault.faces;
    object.color = (selected_.has_value() && *selected_ == oid)
                       ? styles_.selected_color
                       : styles_.fault_color;
    object.pickable = true;
    object.opacity = opacity_.count(oid) ? static_cast<float>(opacity_.at(oid)) : 1.0f;
    object.clip_planes = clip_planes_;
    manager.add(std::move(object));
    return std::vector<std::string>{oid};
}

std::optional<std::vector<std::string>> GeologicalSceneAdapter::build_volume(
    SceneObjectManager& manager, const DomainObject& volume) {
    const std::string oid = volume.object_id;
    std::vector<std::array<double, 3>> world;
    world.reserve(volume.verts.size());
    for (const auto& v : volume.verts) world.push_back({v[0], v[1], v[2]});
    const std::vector<std::array<double, 3>> render = to_render(world);
    if (render.empty()) return std::vector<std::string>{};
    const bool selected = selected_.has_value() && *selected_ == oid;
    SceneObject object;
    object.name = oid;
    object.kind = ObjectKind::Volume;
    object.mode = ObjectMode::Mesh;
    object.verts.reserve(render.size());
    for (const auto& p : render) {
        object.verts.push_back({static_cast<float>(p[0]), static_cast<float>(p[1]),
                                static_cast<float>(p[2])});
    }
    object.faces = volume.faces;
    object.pickable = true;
    object.opacity = opacity_.count(oid) ? static_cast<float>(opacity_.at(oid)) : 1.0f;
    object.clip_planes = clip_planes_;
    if (volume.facies.has_value() && !selected) {
        object.face_colors = facies_face_colors(*volume.facies, volume.faces);
        object.smooth = false;  // per-face colors: flat shading
    } else {
        object.color = selected ? styles_.selected_color : styles_.volume_color;
    }
    manager.add(std::move(object));
    return std::vector<std::string>{oid};
}

std::optional<std::vector<std::string>> GeologicalSceneAdapter::build_tunnel(
    SceneObjectManager& manager, const DomainObject& tunnel) {
    const std::string oid = tunnel.object_id;
    std::vector<std::array<double, 3>> world;
    world.reserve(tunnel.path.size());
    for (const auto& v : tunnel.path) world.push_back({v[0], v[1], v[2]});
    const std::vector<std::array<double, 3>> render = to_render(world);
    if (render.size() < 2) return std::vector<std::string>{};
    const TubeMesh tube = generate_tube_geometry(render, tunnel.radius);
    if (tube.faces.empty()) return std::vector<std::string>{};
    SceneObject object;
    // Intentional divergence (documented in the migration note): Python
    // passes kind="tunnel", which the engine's OBJECT_KINDS rejects, so
    // tunnels never actually rendered there; the C++ registry renders them
    // under the generic kind instead.
    object.name = oid;
    object.kind = ObjectKind::Generic;
    object.mode = ObjectMode::Mesh;
    object.verts = tube.verts;
    object.faces = tube.faces;
    object.pickable = false;
    object.opacity = opacity_.count(oid) ? static_cast<float>(opacity_.at(oid)) : 1.0f;
    object.clip_planes = clip_planes_;
    manager.add(std::move(object));
    return std::vector<std::string>{oid};
}

namespace {

pwb::geomodel::MeasurementResult measurement_result_from_domain(
    const DomainObject& measure) {
    pwb::geomodel::MeasurementResult out;
    out.crs = measure.crs;
    out.measurement_kind = measure.measurement_kind;
    out.unit = measure.unit;
    out.points.reserve(measure.points.size());
    for (const auto& p : measure.points) out.points.push_back({p[0], p[1], p[2]});
    out.result = measure.result;
    const Json& extra = measure.extra;
    if (extra.is_object()) {
        if (extra.contains("x")) out.extra_x = extra["x"].get<double>();
        if (extra.contains("y")) out.extra_y = extra["y"].get<double>();
        if (extra.contains("z")) out.extra_z = extra["z"].get<double>();
        if (extra.contains("legs")) out.legs = extra["legs"].get<int>();
        if (extra.contains("dz")) out.dz = extra["dz"].get<double>();
        if (extra.contains("top_id")) out.top_id = extra["top_id"].get<std::string>();
        if (extra.contains("base_id")) out.base_id = extra["base_id"].get<std::string>();
        if (extra.contains("signed")) {
            out.signed_dz = extra["signed"].get<double>();
        } else if (extra.contains("signed_dz")) {
            out.signed_dz = extra["signed_dz"].get<double>();
        }
        if (extra.contains("strike_deg")) out.strike_deg = extra["strike_deg"].get<double>();
        if (extra.contains("dip_deg")) out.dip_deg = extra["dip_deg"].get<double>();
        if (extra.contains("planarity_ratio"))
            out.planarity_ratio = extra["planarity_ratio"].get<double>();
    }
    return out;
}

}  // namespace

std::optional<std::vector<std::string>> GeologicalSceneAdapter::build_measurement(
    SceneObjectManager& manager, const DomainObject& measure) {
    const std::string oid = measure.object_id;
    std::vector<std::array<double, 3>> world;
    world.reserve(measure.points.size());
    for (const auto& p : measure.points) world.push_back({p[0], p[1], p[2]});
    const std::vector<std::array<double, 3>> render = to_render(world);
    if (render.empty()) return std::vector<std::string>{};
    const auto to_f = [](const std::array<double, 3>& p) {
        return Vec3f{static_cast<float>(p[0]), static_cast<float>(p[1]),
                     static_cast<float>(p[2])};
    };
    std::vector<std::string> names;
    SceneObject points;
    points.name = oid;
    points.kind = ObjectKind::Measurement;
    points.mode = ObjectMode::Points;
    points.verts.reserve(render.size());
    for (const auto& p : render) points.verts.push_back(to_f(p));
    points.color = styles_.measurement_color;
    points.size = 8.0f;
    points.clip_planes = clip_planes_;
    manager.add(std::move(points));
    names.push_back(oid);
    if (render.size() >= 2) {
        SceneObject line;
        const std::string line_name = oid + "#line";
        line.name = line_name;
        line.kind = ObjectKind::Measurement;
        line.mode = ObjectMode::Lines;
        line.line_strip = true;
        line.verts.reserve(render.size());
        for (const auto& p : render) line.verts.push_back(to_f(p));
        line.color = styles_.measurement_color;
        line.width = 2.0f;
        line.clip_planes = clip_planes_;
        manager.add(std::move(line));
        names.push_back(line_name);
    }
    SceneObject label;
    const std::string label_name = oid + "#label";
    label.name = label_name;
    label.kind = ObjectKind::Measurement;
    label.mode = ObjectMode::Text;
    label.verts.push_back(to_f(render.back()));
    label.text = pwb::geomodel::format_result(
        measurement_result_from_domain(measure));
    label.color = styles_.measurement_color;
    label.clip_planes = clip_planes_;
    manager.add(std::move(label));
    names.push_back(label_name);
    return names;
}

// ---------------------------------------------------------------------------
// view state
// ---------------------------------------------------------------------------

void GeologicalSceneAdapter::set_visibility(const std::string& object_id,
                                            bool visible) {
    visibility_[object_id] = visible;
    SceneObjectManager* manager = provider_();
    if (manager == nullptr) return;
    const auto it = derived_.find(object_id);
    if (it != derived_.end()) {
        for (const std::string& name : it->second) {
            manager->set_visibility(name, visible);
        }
    }
    // set_clip_planes skips invisible objects; re-apply on reveal so an
    // object hidden during a clip edit is not left unclipped.
    if (visible && clip_planes_.has_value()) {
        if (it != derived_.end()) {
            for (const std::string& name : it->second) {
                manager->set_clip_planes(name, clip_planes_);
            }
        }
    }
}

bool GeologicalSceneAdapter::visibility(const std::string& object_id) const {
    const auto it = visibility_.find(object_id);
    return it == visibility_.end() ? true : it->second;
}

void GeologicalSceneAdapter::set_opacity(const std::string& object_id,
                                         double opacity) {
    opacity_[object_id] = std::clamp(opacity, 0.0, 1.0);
    SceneObjectManager* manager = provider_();
    if (manager == nullptr) return;
    const auto it = derived_.find(object_id);
    if (it == derived_.end()) return;
    for (const std::string& name : it->second) {
        manager->set_opacity(name, static_cast<float>(opacity_[object_id]));
    }
}

void GeologicalSceneAdapter::set_selected(
    const std::optional<std::string>& object_id) {
    const std::optional<std::string> prev = selected_;
    selected_ = object_id;
    SceneObjectManager* manager = provider_();
    if (manager == nullptr) return;
    const std::optional<std::string> targets[2] = {prev, object_id};
    for (const std::optional<std::string>& oid : targets) {
        if (!oid.has_value() || synced_tokens_.count(*oid) == 0) continue;
        const bool is_selected = object_id.has_value() && *oid == *object_id;
        const Rgba color =
            is_selected ? styles_.selected_color : base_color(*oid);
        manager->set_color(*oid, color);
        const auto it = derived_.find(*oid);
        if (it == derived_.end()) continue;
        for (const std::string& name : it->second) {
            if (name == *oid) continue;
            manager->set_color(name, is_selected ? styles_.selected_color
                                                 : base_color(name));
        }
    }
}

void GeologicalSceneAdapter::register_overlay(
    const std::string& key, const std::vector<std::string>& names) {
    overlays_[key] = names;
}

void GeologicalSceneAdapter::remove_overlay(const std::string& key) {
    overlays_.erase(key);
}

void GeologicalSceneAdapter::set_clip_planes(
    const std::optional<std::vector<ClipEquation>>& planes) {
    clip_planes_ = planes;
    SceneObjectManager* manager = provider_();
    if (manager == nullptr) return;
    for (const auto& [oid, names] : derived_) {
        if (!visibility(oid)) continue;  // reapplied on reveal
        for (const std::string& name : names) {
            manager->set_clip_planes(name, planes);
        }
    }
    for (const auto& [key, names] : overlays_) {
        (void)key;
        for (const std::string& name : names) {
            manager->set_clip_planes(name, planes);
        }
    }
}

// ---------------------------------------------------------------------------
// display state (save/restore)
// ---------------------------------------------------------------------------

Json GeologicalSceneAdapter::display_state(const std::string& object_id) const {
    Json state = Json::object();
    state["visible"] = visibility(object_id);
    const auto it = opacity_.find(object_id);
    state["opacity"] = it == opacity_.end() ? 1.0 : it->second;
    return state;
}

void GeologicalSceneAdapter::restore_display(const Json& display) {
    // Python: bool(state.get("visible", True)) — truthiness of ANY JSON
    // value (bool(0) is false, non-empty strings true, ...), not a
    // boolean-only read.
    if (!display.is_object()) return;
    for (auto it = display.begin(); it != display.end(); ++it) {
        const std::string oid = it.key();
        const Json& state = it.value();
        if (!state.is_object()) continue;
        bool visible = true;
        if (state.contains("visible")) {
            const Json& v = state["visible"];
            if (v.is_boolean()) visible = v.get<bool>();
            else if (v.is_number()) visible = v.get<double>() != 0.0;
            else if (v.is_string()) visible = !v.get<std::string>().empty();
            else if (v.is_null()) visible = false;
            else if (v.is_array() || v.is_object()) visible = !v.empty();
        }
        double opacity = 1.0;
        if (state.contains("opacity") && state["opacity"].is_number()) {
            opacity = state["opacity"].get<double>();
        }
        visibility_[oid] = visible;
        opacity_[oid] = std::clamp(opacity, 0.0, 1.0);
    }
}

// ---------------------------------------------------------------------------
// picking
// ---------------------------------------------------------------------------

std::vector<std::string> GeologicalSceneAdapter::derived_names(
    const std::string& object_id) const {
    const auto it = derived_.find(object_id);
    return it == derived_.end() ? std::vector<std::string>{} : it->second;
}

bool GeologicalSceneAdapter::is_synced(const std::string& object_id) const {
    return synced_tokens_.count(object_id) != 0;
}

std::optional<DomainPick> GeologicalSceneAdapter::pick(
    const Ray& ray, const std::vector<ObjectKind>& kinds) const {
    SceneObjectManager* manager = provider_();
    if (manager == nullptr) return std::nullopt;
    const std::optional<PickHit> hit = manager->pick(ray, kinds);
    if (!hit.has_value()) return std::nullopt;
    return resolve_pick(*hit);
}

DomainPick GeologicalSceneAdapter::resolve_pick(const PickHit& hit) const {
    DomainPick out;
    const std::size_t hash_pos = hit.name.find('#');
    out.object_id = hash_pos == std::string::npos
                        ? hit.name
                        : hit.name.substr(0, hash_pos);
    out.kind = hit.kind;
    out.distance = hit.distance;
    try {
        const auto domain = transform_.inverse({hit.point});
        if (!domain.empty()) {
            out.domain_xyz = domain.front();
            out.has_xyz = true;
        }
    } catch (const std::exception&) {
        out.domain_xyz = {std::nan(""), std::nan(""), std::nan("")};
        out.has_xyz = false;
    }
    return out;
}

// ---------------------------------------------------------------------------
// facies colors + tube geometry (geoviz_plots primitives port)
// ---------------------------------------------------------------------------

std::vector<Rgba> facies_face_colors(
    const std::vector<std::int64_t>& facies,
    const std::vector<std::array<std::int64_t, 3>>& faces) {
    const std::vector<Rgba>& palette = facies_palette();
    // palette[facies[vertex]] — the categorical value indexes the palette
    // (clamped into range), never the vertex id.
    const auto vertex_color = [&](std::int64_t vertex) -> const Rgba& {
        const std::int64_t value = facies.at(static_cast<std::size_t>(vertex));
        const std::int64_t clamped =
            std::clamp<std::int64_t>(value, 0,
                                     static_cast<std::int64_t>(palette.size()) - 1);
        return palette[static_cast<std::size_t>(clamped)];
    };
    std::vector<Rgba> out;
    out.reserve(faces.size());
    for (const auto& face : faces) {
        Rgba mean{0.f, 0.f, 0.f, 0.f};
        for (std::int64_t v : face) {
            const Rgba& c = vertex_color(v);
            for (int k = 0; k < 4; ++k) mean[k] += c[k];
        }
        const float n = static_cast<float>(face.size());
        for (int k = 0; k < 4; ++k) mean[k] /= n;
        out.push_back(mean);
    }
    return out;
}

TubeMesh generate_tube_geometry(const std::vector<std::array<double, 3>>& path,
                                double radius, int resolution) {
    TubeMesh out;
    if (path.size() < 2 || resolution < 3) return out;
    const std::size_t res = static_cast<std::size_t>(resolution);
    const auto tangent_at = [&](std::size_t j) {
        std::array<double, 3> t;
        if (j == 0) {
            t = {path[1][0] - path[0][0], path[1][1] - path[0][1],
                 path[1][2] - path[0][2]};
        } else if (j == path.size() - 1) {
            const std::size_t n = path.size();
            t = {path[n - 1][0] - path[n - 2][0], path[n - 1][1] - path[n - 2][1],
                 path[n - 1][2] - path[n - 2][2]};
        } else {
            t = {path[j + 1][0] - path[j - 1][0], path[j + 1][1] - path[j - 1][1],
                 path[j + 1][2] - path[j - 1][2]};
        }
        const double len = std::sqrt(t[0] * t[0] + t[1] * t[1] + t[2] * t[2]);
        if (len == 0.0) return std::array<double, 3>{0.0, 0.0, 1.0};
        return std::array<double, 3>{t[0] / len, t[1] / len, t[2] / len};
    };
    const auto basis = [](const std::array<double, 3>& axis) {
        const std::array<double, 3> seed =
            std::abs(axis[0]) < 0.9 ? std::array<double, 3>{1.0, 0.0, 0.0}
                                    : std::array<double, 3>{0.0, 1.0, 0.0};
        std::array<double, 3> ortho1{
            axis[1] * seed[2] - axis[2] * seed[1],
            axis[2] * seed[0] - axis[0] * seed[2],
            axis[0] * seed[1] - axis[1] * seed[0]};
        const double n = std::sqrt(ortho1[0] * ortho1[0] +
                                   ortho1[1] * ortho1[1] +
                                   ortho1[2] * ortho1[2]);
        ortho1 = {ortho1[0] / n, ortho1[1] / n, ortho1[2] / n};
        const std::array<double, 3> ortho2{
            axis[1] * ortho1[2] - axis[2] * ortho1[1],
            axis[2] * ortho1[0] - axis[0] * ortho1[2],
            axis[0] * ortho1[1] - axis[1] * ortho1[0]};
        return std::make_pair(ortho1, ortho2);
    };
    for (std::size_t j = 0; j < path.size(); ++j) {
        const auto [ortho1, ortho2] = basis(tangent_at(j));
        for (std::size_t i = 0; i < res; ++i) {
            const double theta = 2.0 * 3.14159265358979323846 *
                                 static_cast<double>(i) / static_cast<double>(res);
            const double c = std::cos(theta) * radius;
            const double s = std::sin(theta) * radius;
            out.verts.push_back({static_cast<float>(path[j][0] + c * ortho1[0] +
                                                    s * ortho2[0]),
                                 static_cast<float>(path[j][1] + c * ortho1[1] +
                                                    s * ortho2[1]),
                                 static_cast<float>(path[j][2] + c * ortho1[2] +
                                                    s * ortho2[2])});
        }
    }
    for (std::size_t j = 0; j + 1 < path.size(); ++j) {
        const std::size_t ring = j * res;
        const std::size_t next_ring = (j + 1) * res;
        for (std::size_t i = 0; i < res; ++i) {
            const std::size_t next_i = (i + 1) % res;
            out.faces.push_back({static_cast<std::int64_t>(ring + i),
                                 static_cast<std::int64_t>(ring + next_i),
                                 static_cast<std::int64_t>(next_ring + i)});
            out.faces.push_back({static_cast<std::int64_t>(ring + next_i),
                                 static_cast<std::int64_t>(next_ring + next_i),
                                 static_cast<std::int64_t>(next_ring + i)});
        }
    }
    return out;
}

}  // namespace pwb::geo3d_viz
