#include <pwb/geo3d_viz/scene_object_manager.hpp>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>

namespace pwb::geo3d_viz {

const char* object_mode_name(ObjectMode mode) {
    switch (mode) {
        case ObjectMode::Mesh: return "mesh";
        case ObjectMode::Lines: return "lines";
        case ObjectMode::Points: return "points";
        case ObjectMode::Text: return "text";
    }
    return "mesh";
}

ObjectMode object_mode_from_name(const std::string& name) {
    if (name == "mesh") return ObjectMode::Mesh;
    if (name == "lines") return ObjectMode::Lines;
    if (name == "points") return ObjectMode::Points;
    if (name == "text") return ObjectMode::Text;
    throw SceneObjectError("unknown object mode: " + name);
}

const char* object_kind_name(ObjectKind kind) {
    switch (kind) {
        case ObjectKind::Generic: return "generic";
        case ObjectKind::Well: return "well";
        case ObjectKind::Horizon: return "horizon";
        case ObjectKind::Fault: return "fault";
        case ObjectKind::Volume: return "volume";
        case ObjectKind::Annotation: return "annotation";
        case ObjectKind::Measurement: return "measurement";
    }
    return "generic";
}

ObjectKind object_kind_from_name(const std::string& name) {
    if (name == "generic") return ObjectKind::Generic;
    if (name == "well") return ObjectKind::Well;
    if (name == "horizon") return ObjectKind::Horizon;
    if (name == "fault") return ObjectKind::Fault;
    if (name == "volume") return ObjectKind::Volume;
    if (name == "annotation") return ObjectKind::Annotation;
    if (name == "measurement") return ObjectKind::Measurement;
    throw SceneObjectError("unknown object kind: " + name);
}

const std::vector<Rgba>& facies_palette() {
    static const std::vector<Rgba> palette = {
        {0.65f, 0.81f, 0.89f, 1.0f},  // 0 sand-ish
        {0.94f, 0.90f, 0.55f, 1.0f},  // 1 silt
        {0.74f, 0.62f, 0.42f, 1.0f},  // 2 shale-ish
        {0.55f, 0.71f, 0.49f, 1.0f},  // 3 carbonate-ish
        {0.80f, 0.52f, 0.45f, 1.0f},  // 4 coal/organic
        {0.62f, 0.62f, 0.72f, 1.0f},  // 5 volcaniclastic
        {0.85f, 0.85f, 0.85f, 1.0f},  // 6 other
        {0.45f, 0.55f, 0.70f, 1.0f},  // 7 other
    };
    return palette;
}

// ---------------------------------------------------------------------------
// SceneObject
// ---------------------------------------------------------------------------

std::optional<std::pair<std::array<double, 3>, std::array<double, 3>>>
SceneObject::bounds() const {
    if (verts.empty()) return std::nullopt;
    std::array<double, 3> lo{std::numeric_limits<double>::infinity(),
                             std::numeric_limits<double>::infinity(),
                             std::numeric_limits<double>::infinity()};
    std::array<double, 3> hi{-lo[0], -lo[1], -lo[2]};
    for (const Vec3f& v : verts) {
        for (int k = 0; k < 3; ++k) {
            lo[k] = std::min(lo[k], static_cast<double>(v[k]));
            hi[k] = std::max(hi[k], static_cast<double>(v[k]));
        }
    }
    return std::make_pair(lo, hi);
}

// ---------------------------------------------------------------------------
// pick math
// ---------------------------------------------------------------------------

std::optional<std::pair<double, std::int64_t>> ray_triangles_first_hit(
    const std::array<double, 3>& origin, const std::array<double, 3>& direction,
    const std::vector<Vec3f>& verts,
    const std::vector<std::array<std::int64_t, 3>>& faces,
    std::optional<double> max_distance) {
    if (faces.empty() || verts.empty()) return std::nullopt;
    constexpr double kEps = 1e-12;
    std::optional<std::pair<double, std::int64_t>> best;
    for (std::size_t fi = 0; fi < faces.size(); ++fi) {
        const auto& f = faces[fi];
        const auto index = [&](std::int64_t i) -> std::array<double, 3> {
            const Vec3f& v = verts[static_cast<std::size_t>(i)];
            return {v[0], v[1], v[2]};
        };
        const std::array<double, 3> a = index(f[0]);
        const std::array<double, 3> b = index(f[1]);
        const std::array<double, 3> c = index(f[2]);
        const auto sub = [](const std::array<double, 3>& p,
                            const std::array<double, 3>& q) {
            return std::array<double, 3>{p[0] - q[0], p[1] - q[1], p[2] - q[2]};
        };
        const auto cross = [](const std::array<double, 3>& p,
                              const std::array<double, 3>& q) {
            return std::array<double, 3>{p[1] * q[2] - p[2] * q[1],
                                         p[2] * q[0] - p[0] * q[2],
                                         p[0] * q[1] - p[1] * q[0]};
        };
        const auto dot = [](const std::array<double, 3>& p,
                            const std::array<double, 3>& q) {
            return p[0] * q[0] + p[1] * q[1] + p[2] * q[2];
        };
        const std::array<double, 3> e1 = sub(b, a);
        const std::array<double, 3> e2 = sub(c, a);
        const std::array<double, 3> pvec = cross(direction, e2);
        const double det = dot(e1, pvec);
        if (std::abs(det) <= kEps) continue;  // degenerate / parallel
        const double inv_det = 1.0 / det;
        const std::array<double, 3> tvec = sub(origin, a);
        const double u = dot(tvec, pvec) * inv_det;
        const std::array<double, 3> qvec = cross(tvec, e1);
        const double v = dot(direction, qvec) * inv_det;
        const double t = dot(e2, qvec) * inv_det;
        const bool hit = u >= -1e-9 && v >= -1e-9 && u + v <= 1.0 + 1e-9 &&
                         t >= 0.0 &&
                         (!max_distance.has_value() || t <= *max_distance);
        if (hit && (!best.has_value() || t < best->first)) {
            best = std::make_pair(t, static_cast<std::int64_t>(fi));
        }
    }
    return best;
}

std::optional<std::pair<double, std::int64_t>> ray_segments_closest(
    const std::array<double, 3>& origin, const std::array<double, 3>& direction,
    const std::vector<Vec3f>& verts, double pick_radius,
    std::optional<double> max_distance) {
    const std::size_t seg_count = verts.size() < 2 ? 0 : verts.size() - 1;
    if (seg_count == 0 || pick_radius <= 0.0) return std::nullopt;
    const auto sub = [](const std::array<double, 3>& p,
                        const std::array<double, 3>& q) {
        return std::array<double, 3>{p[0] - q[0], p[1] - q[1], p[2] - q[2]};
    };
    const auto dot = [](const std::array<double, 3>& p,
                        const std::array<double, 3>& q) {
        return p[0] * q[0] + p[1] * q[1] + p[2] * q[2];
    };
    double best_dist = std::numeric_limits<double>::infinity();
    std::size_t best_seg = seg_count;
    double best_t = 0.0;
    for (std::size_t s = 0; s < seg_count; ++s) {
        const std::array<double, 3> a{verts[s][0], verts[s][1], verts[s][2]};
        const std::array<double, 3> u = sub(
            {verts[s + 1][0], verts[s + 1][1], verts[s + 1][2]}, a);
        const double seg_len2 = dot(u, u);
        if (!(seg_len2 > 1e-24)) continue;  // ok mask
        // two clamped sweeps of the closest-point parameters (sc, tc)
        double sc = 0.5;
        double tc = 0.0;
        for (int sweep = 0; sweep < 2; ++sweep) {
            const std::array<double, 3> p_seg{a[0] + sc * u[0], a[1] + sc * u[1],
                                              a[2] + sc * u[2]};
            tc = std::max(0.0, dot(sub(p_seg, origin), direction));
            const std::array<double, 3> p_ray{origin[0] + tc * direction[0],
                                              origin[1] + tc * direction[1],
                                              origin[2] + tc * direction[2]};
            const std::array<double, 3> w = sub(p_ray, p_seg);
            sc = std::clamp(dot(w, u) / seg_len2, 0.0, 1.0);
        }
        const std::array<double, 3> p_seg{a[0] + sc * u[0], a[1] + sc * u[1],
                                          a[2] + sc * u[2]};
        tc = std::max(0.0, dot(sub(p_seg, origin), direction));
        const std::array<double, 3> p_ray{origin[0] + tc * direction[0],
                                          origin[1] + tc * direction[1],
                                          origin[2] + tc * direction[2]};
        const double dist = std::sqrt(dot(sub(p_ray, p_seg), sub(p_ray, p_seg)));
        if (max_distance.has_value() && tc > *max_distance) continue;
        if (dist < best_dist) {
            best_dist = dist;
            best_seg = s;
            best_t = tc;
        }
    }
    if (best_seg == seg_count || !std::isfinite(best_dist) ||
        best_dist > pick_radius) {
        return std::nullopt;
    }
    return std::make_pair(best_t, static_cast<std::int64_t>(best_seg));
}

// ---------------------------------------------------------------------------
// 4x4 matrix helpers (column-major, QMatrix4x4 memory order)
// ---------------------------------------------------------------------------

namespace {

Mat4 mat4_multiply(const Mat4& a, const Mat4& b) {
    // out[col*4 + row] = sum_k a[k*4 + row] * b[col*4 + k]
    Mat4 out{};
    for (int col = 0; col < 4; ++col) {
        for (int row = 0; row < 4; ++row) {
            float sum = 0.0f;
            for (int k = 0; k < 4; ++k) {
                sum += a[static_cast<std::size_t>(k) * 4 + row] *
                       b[static_cast<std::size_t>(col) * 4 + k];
            }
            out[static_cast<std::size_t>(col) * 4 + row] = sum;
        }
    }
    return out;
}

bool mat4_invert(const Mat4& m, Mat4& inv_out) {
    // General Gauss-Jordan inverse with partial pivoting (QMatrix4x4
    // .inverted() falls back to the general inverse for projection stacks).
    double a[4][8];
    for (int col = 0; col < 4; ++col) {
        for (int row = 0; row < 4; ++row) {
            a[row][col] = m[static_cast<std::size_t>(col) * 4 + row];
            a[row][4 + col] = (row == col) ? 1.0 : 0.0;
        }
    }
    for (int col = 0; col < 4; ++col) {
        int pivot = col;
        for (int row = col + 1; row < 4; ++row) {
            if (std::abs(a[row][col]) > std::abs(a[pivot][col])) pivot = row;
        }
        if (std::abs(a[pivot][col]) < 1e-12) return false;
        if (pivot != col) {
            for (int k = 0; k < 8; ++k) std::swap(a[col][k], a[pivot][k]);
        }
        const double diag = a[col][col];
        for (int k = 0; k < 8; ++k) a[col][k] /= diag;
        for (int row = 0; row < 4; ++row) {
            if (row == col) continue;
            const double factor = a[row][col];
            if (factor == 0.0) continue;
            for (int k = 0; k < 8; ++k) a[row][k] -= factor * a[col][k];
        }
    }
    for (int col = 0; col < 4; ++col) {
        for (int row = 0; row < 4; ++row) {
            inv_out[static_cast<std::size_t>(col) * 4 + row] =
                static_cast<float>(a[row][4 + col]);
        }
    }
    return true;
}

std::array<double, 4> mat4_map(const Mat4& m, const std::array<double, 4>& v) {
    std::array<double, 4> out{};
    for (int row = 0; row < 4; ++row) {
        out[row] = v[0] * m[row] + v[1] * m[4 + row] + v[2] * m[8 + row] +
                   v[3] * m[12 + row];
    }
    return out;
}

}  // namespace

std::optional<Ray> screen_point_to_ray(double px, double py, double width,
                                       double height, const Mat4& view,
                                       const Mat4& projection) {
    if (width <= 0 || height <= 0) return std::nullopt;
    const double ndc_x = (2.0 * px / width) - 1.0;
    const double ndc_y = 1.0 - (2.0 * py / height);
    Mat4 inv{};
    if (!mat4_invert(mat4_multiply(projection, view), inv)) return std::nullopt;
    const auto unproject = [&](double z) -> std::optional<std::array<double, 3>> {
        const std::array<double, 4> p = mat4_map(inv, {ndc_x, ndc_y, z, 1.0});
        if (std::abs(p[3]) < 1e-8) return std::nullopt;  // w-division guard
        return std::array<double, 3>{p[0] / p[3], p[1] / p[3], p[2] / p[3]};
    };
    const auto near_p = unproject(-1.0);
    const auto far_p = unproject(1.0);
    if (!near_p.has_value() || !far_p.has_value()) return std::nullopt;
    std::array<double, 3> direction{far_p->at(0) - near_p->at(0),
                                    far_p->at(1) - near_p->at(1),
                                    far_p->at(2) - near_p->at(2)};
    const double norm = std::sqrt(direction[0] * direction[0] +
                                  direction[1] * direction[1] +
                                  direction[2] * direction[2]);
    if (norm < 1e-9) return std::nullopt;
    direction = {direction[0] / norm, direction[1] / norm, direction[2] / norm};
    return Ray{*near_p, direction};
}

// ---------------------------------------------------------------------------
// SceneObjectManager
// ---------------------------------------------------------------------------

namespace {

void require_finite_verts(const std::vector<Vec3f>& verts) {
    for (const Vec3f& v : verts) {
        for (int k = 0; k < 3; ++k) {
            if (!std::isfinite(v[k])) {
                throw SceneObjectError("verts contain non-finite coordinates");
            }
        }
    }
}

}  // namespace

void SceneObjectManager::validate_mesh_arrays(SceneObject& object) {
    require_finite_verts(object.verts);
    if (object.mode == ObjectMode::Mesh && object.faces.empty() &&
        !object.verts.empty()) {
        throw SceneObjectError(
            "mesh objects require faces (or empty verts)");
    }
    if (object.faces.empty()) return;
    std::int64_t min_index = std::numeric_limits<std::int64_t>::max();
    std::int64_t max_index = std::numeric_limits<std::int64_t>::min();
    for (const auto& f : object.faces) {
        for (std::int64_t i : f) {
            min_index = std::min(min_index, i);
            max_index = std::max(max_index, i);
        }
    }
    const std::int64_t vert_count =
        static_cast<std::int64_t>(object.verts.size());
    if (min_index < 0 || max_index >= std::max(vert_count, static_cast<std::int64_t>(1))) {
        throw SceneObjectError(
            "faces reference vertex index out of range [" +
            std::to_string(min_index) + ", " + std::to_string(max_index) +
            "] with " + std::to_string(vert_count) + " vertices");
    }
}

void SceneObjectManager::validate_clip_planes(SceneObject& object) {
    if (!object.clip_planes.has_value()) return;
    if (object.clip_planes->size() > kMaxClipPlanes) {
        throw SceneObjectError("at most " + std::to_string(kMaxClipPlanes) +
                               " clip planes per object, got " +
                               std::to_string(object.clip_planes->size()));
    }
    for (const ClipEquation& eq : *object.clip_planes) {
        if (eq[0] == 0.0 && eq[1] == 0.0 && eq[2] == 0.0) {
            throw SceneObjectError("clip plane normal is zero");
        }
    }
}

const SceneObject& SceneObjectManager::add(SceneObject object) {
    if (object.name.empty()) {
        throw SceneObjectError("object name must not be empty");
    }
    validate_mesh_arrays(object);
    validate_clip_planes(object);
    if (object.opacity < 0.0f) object.opacity = 0.0f;
    if (object.opacity > 1.0f) object.opacity = 1.0f;
    const auto existing = objects_.find(object.name);
    if (existing != objects_.end()) {
        existing->second = std::move(object);  // replace keeps insertion order
        touch();
        return existing->second;
    }
    const std::string name = object.name;
    objects_.emplace(name, std::move(object));
    order_.push_back(name);
    touch();
    return objects_.at(name);
}

bool SceneObjectManager::remove(const std::string& name) {
    const auto it = objects_.find(name);
    if (it == objects_.end()) return false;
    objects_.erase(it);
    order_.erase(std::remove(order_.begin(), order_.end(), name), order_.end());
    touch();
    return true;
}

int SceneObjectManager::clear(const std::optional<ObjectKind>& kind) {
    std::vector<std::string> doomed;
    for (const std::string& name : order_) {
        if (!kind.has_value() || objects_.at(name).kind == *kind) {
            doomed.push_back(name);
        }
    }
    for (const std::string& name : doomed) remove(name);
    return static_cast<int>(doomed.size());
}

bool SceneObjectManager::has(const std::string& name) const {
    return objects_.count(name) != 0;
}

const SceneObject* SceneObjectManager::get(const std::string& name) const {
    const auto it = objects_.find(name);
    return it == objects_.end() ? nullptr : &it->second;
}

std::vector<std::string> SceneObjectManager::names(
    const std::optional<ObjectKind>& kind) const {
    std::vector<std::string> out;
    for (const std::string& name : order_) {
        if (!kind.has_value() || objects_.at(name).kind == *kind) {
            out.push_back(name);
        }
    }
    return out;
}

std::size_t SceneObjectManager::count(const std::optional<ObjectKind>& kind) const {
    return names(kind).size();
}

void SceneObjectManager::set_visibility(const std::string& name, bool visible) {
    const auto it = objects_.find(name);
    if (it == objects_.end() || it->second.visible == visible) return;
    it->second.visible = visible;
    // Appearance state (visibility/opacity/color/pickable) is read live
    // from the registry at draw time — no GL rebuild needed, so the
    // geometry revision stays untouched (opacity sliders must not re-upload
    // whole meshes).
}

void SceneObjectManager::set_opacity(const std::string& name, float opacity) {
    const auto it = objects_.find(name);
    if (it == objects_.end()) return;
    it->second.opacity = std::clamp(opacity, 0.0f, 1.0f);
}

void SceneObjectManager::set_color(const std::string& name, const Rgba& color) {
    const auto it = objects_.find(name);
    if (it == objects_.end()) return;
    it->second.color = color;  // read live at draw time
}

void SceneObjectManager::set_pickable(const std::string& name, bool pickable) {
    const auto it = objects_.find(name);
    if (it == objects_.end()) return;
    it->second.pickable = pickable;
}

void SceneObjectManager::set_clip_planes(
    const std::string& name,
    const std::optional<std::vector<ClipEquation>>& planes) {
    const auto it = objects_.find(name);
    if (it == objects_.end()) return;
    // Validate before writing: a rejected payload never lands in state
    // (Python _validate_clip_planes runs ahead of the assignment).
    SceneObject probe = it->second;
    probe.clip_planes = planes;
    validate_clip_planes(probe);
    it->second.clip_planes = planes;
    touch();
}

std::optional<std::pair<std::array<double, 3>, std::array<double, 3>>>
SceneObjectManager::bounds(const std::vector<ObjectKind>& kinds,
                           bool visible_only) const {
    bool any = false;
    std::array<double, 3> lo{0, 0, 0};
    std::array<double, 3> hi{0, 0, 0};
    for (const std::string& name : order_) {
        const SceneObject& object = objects_.at(name);
        if (visible_only && !object.visible) continue;
        if (!kinds.empty() &&
            std::find(kinds.begin(), kinds.end(), object.kind) == kinds.end()) {
            continue;
        }
        const auto b = object.bounds();
        if (!b.has_value()) continue;
        if (!any) {
            lo = b->first;
            hi = b->second;
            any = true;
            continue;
        }
        for (int k = 0; k < 3; ++k) {
            lo[k] = std::min(lo[k], b->first[k]);
            hi[k] = std::max(hi[k], b->second[k]);
        }
    }
    if (!any) return std::nullopt;
    return std::make_pair(lo, hi);
}

std::optional<PickHit> SceneObjectManager::pick(
    const Ray& ray, const std::vector<ObjectKind>& kinds) const {
    std::optional<PickHit> best;
    for (const std::string& name : order_) {
        const SceneObject& object = objects_.at(name);
        if (!object.visible || !object.pickable) continue;
        if (!kinds.empty() &&
            std::find(kinds.begin(), kinds.end(), object.kind) == kinds.end()) {
            continue;
        }
        std::optional<std::pair<double, std::int64_t>> hit;
        if (object.mode == ObjectMode::Mesh && !object.faces.empty()) {
            hit = ray_triangles_first_hit(ray.origin, ray.direction,
                                          object.verts, object.faces);
        } else if (object.mode == ObjectMode::Lines) {
            hit = ray_segments_closest(ray.origin, ray.direction, object.verts,
                                       object.pick_radius);
        }
        if (!hit.has_value()) continue;
        if (!best.has_value() || hit->first < best->distance) {
            PickHit out;
            out.name = object.name;
            out.kind = object_kind_name(object.kind);
            out.distance = hit->first;
            out.face_index = hit->second;
            out.point = {ray.origin[0] + hit->first * ray.direction[0],
                         ray.origin[1] + hit->first * ray.direction[1],
                         ray.origin[2] + hit->first * ray.direction[2]};
            best = out;
        }
    }
    return best;
}

}  // namespace pwb::geo3d_viz
