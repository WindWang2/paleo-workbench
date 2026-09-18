#include <pwb/geomodel/qc_contract.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <map>
#include <set>

#include <pwb/geomodel/builders.hpp>   // triangulate_heightfield, HorizonGrid
#include <pwb/geomodel/mesh_qc.hpp>    // numeric cores (CONV-12)

namespace pwb::geomodel {

namespace {

const std::map<std::string, int>& severity_order() {
    static const std::map<std::string, int> order = {
        {"info", 0}, {"warning", 1}, {"error", 2}, {"blocker", 3}};
    return order;
}

int sev(const std::string& s, int dflt = 0) {
    auto it = severity_order().find(s);
    return it == severity_order().end() ? dflt : it->second;
}

// f"{v:.N%}" — percent with N decimals, Python rounding (printf %.Nf is
// already half-even under FE_TONEAREST).
std::string pct(double v, int decimals) {
    char buf[64];
    std::snprintf(buf, sizeof buf, "%.*f%%", decimals, v * 100.0);
    return buf;
}

double seg_norm3(const Vec3& a, const Vec3& b) {
    const double dx = b[0] - a[0], dy = b[1] - a[1], dz = b[2] - a[2];
    return std::sqrt(dx * dx + dy * dy + dz * dz);
}

bool missing_crs(const std::string& crs) {
    return crs.empty() || crs == "unknown";
}

// v[f] fancy indexing — the first out-of-range id crashes the audit with
// numpy's IndexError text (negative ids wrap, like numpy).
void check_face_bounds(const std::vector<Vec3>& verts,
                       const std::vector<std::array<std::int64_t, 3>>& faces) {
    const std::int64_t n = static_cast<std::int64_t>(verts.size());
    for (const auto& f : faces)
        for (std::int64_t i : f)
            if (i >= n || i < -n)
                throw IndexError("index " + std::to_string(i) +
                                 " is out of bounds for axis 0 with size " +
                                 std::to_string(n));
}

// Python's qc triangulation entry: builders.triangulate_heightfield over
// the (already ported) C++ kernel — identical semantics, frozen in CONV-12.
TriMesh triangulate(const DomainObject& hor) {
    HorizonGrid g;
    g.rows = static_cast<int>(hor.z_grid.size());
    g.cols = hor.z_grid.empty() ? 0 : static_cast<int>(hor.z_grid[0].size());
    g.origin_x = hor.origin[0];
    g.origin_y = hor.origin[1];
    g.spacing_y = hor.spacing[0];
    g.spacing_x = hor.spacing[1];
    g.vertical_domain = hor.vertical_domain;
    g.unit = hor.unit;
    g.object_id = hor.object_id;
    g.z.reserve(static_cast<std::size_t>(g.rows) *
                static_cast<std::size_t>(g.cols));
    for (const auto& row : hor.z_grid)
        for (double v : row) g.z.push_back(v);
    return triangulate_heightfield(g);
}

QCReport qc_well(const DomainObject& well) {
    QCReport r;
    const std::string& oid = well.object_id;
    if (missing_crs(well.crs))
        r.add({"MISSING_CRS", "blocker",
               "CRS unknown — coordinates cannot be geo-referenced", oid,
               std::nullopt});
    if (well.stations.empty()) {
        r.add({"NO_STATIONS", "blocker", "no stations", oid, std::nullopt});
        return r;
    }
    bool nonfinite = false;
    for (const auto& s : well.stations)
        for (double c : s)
            if (!std::isfinite(c)) nonfinite = true;
    if (nonfinite)
        r.add({"NON_FINITE_STATIONS", "error", "non-finite station values",
               oid, std::nullopt});
    if (well.stations.size() >= 2) {
        double min_diff = well.stations[1][0] - well.stations[0][0];
        bool nonmono = false;
        for (std::size_t i = 1; i < well.stations.size(); ++i) {
            const double d = well.stations[i][0] - well.stations[i - 1][0];
            min_diff = std::min(min_diff, d);
            if (d <= 0) nonmono = true;
        }
        if (nonmono)
            r.add({"NON_MONOTONIC_MD", "blocker",
                   "MD is not strictly increasing (duplicate / unordered "
                   "stations)",
                   oid, min_diff});
        // zero-length xyz segments
        int zero = 0;
        for (std::size_t i = 1; i < well.stations.size(); ++i) {
            const Vec3 a{well.stations[i - 1][1], well.stations[i - 1][2],
                         well.stations[i - 1][3]};
            const Vec3 b{well.stations[i][1], well.stations[i][2],
                         well.stations[i][3]};
            if (seg_norm3(a, b) <= 1e-12) ++zero;
        }
        if (zero)
            r.add({"ZERO_LENGTH_SEGMENTS", "warning",
                   std::to_string(zero) +
                       " zero-length station interval(s)",
                   oid, static_cast<double>(zero)});
    }
    if (well.representation == "measured" && well.stations.size() < 3)
        r.add({"SPARSE_TRAJECTORY", "warning",
               "measured trajectory has fewer than 3 stations", oid,
               static_cast<double>(well.stations.size())});
    if (well.representation == "simplified_vertical")
        r.add({"SIMPLIFIED_VERTICAL", "info",
               "simplified vertical indicator (no measured survey data)",
               oid, std::nullopt});
    if (well.z_unit && !well.z_unit->empty() && *well.z_unit != well.unit)
        r.add({"MIXED_UNITS", "warning",
               "horizontal unit " + well.unit +
                   " differs from z unit " + *well.z_unit,
               oid, std::nullopt});
    return r;
}

QCReport qc_horizon(const DomainObject& hor) {
    QCReport r;
    const std::string& oid = hor.object_id;
    std::size_t total = 0, finite = 0;
    bool has_inf = false;
    for (const auto& row : hor.z_grid)
        for (double v : row) {
            ++total;
            if (std::isfinite(v))
                ++finite;
            else if (std::isinf(v))
                has_inf = true;
        }
    if (total == 0) {
        r.add({"NO_GEOMETRY", "blocker",
               "empty grid (artifact not loaded?)", oid, std::nullopt});
        return r;
    }
    const double nan_fraction = 1.0 - static_cast<double>(finite) / total;
    if (nan_fraction > 0.5)
        r.add({"LARGELY_MISSING", "warning",
               pct(nan_fraction, 0) + " of nodes are NaN holes", oid,
               nan_fraction});
    else if (nan_fraction > 0.0)
        r.add({"NAN_HOLES", "info",
               pct(nan_fraction, 1) +
                   " of nodes are NaN holes (kept as holes)",
               oid, nan_fraction});
    if (has_inf)
        r.add({"NON_FINITE_GRID", "error", "grid contains +/-inf", oid,
               std::nullopt});
    if (missing_crs(hor.crs) && hor.grid_crs.empty())
        r.add({"MISSING_CRS", "blocker",
               "neither world CRS nor grid CRS stated", oid, std::nullopt});
    const TriMesh mesh = triangulate(hor);
    if (mesh.faces.empty()) {
        r.add({"NO_GEOMETRY", "blocker", "no finite triangulable area", oid,
               std::nullopt});
        return r;
    }
    const double degenerate =
        tri_degenerate_fraction(mesh.verts, mesh.faces);
    if (degenerate > 0.0)
        r.add({"DEGENERATE_TRIANGLES",
               degenerate > 0.01 ? "error" : "warning",
               pct(degenerate, 2) + " degenerate triangles", oid,
               degenerate});
    const EdgeManifoldStats em = edge_manifold_stats(mesh.faces);
    if (em.nonmanifold)
        r.add({"NON_MANIFOLD_EDGES", "error",
               std::to_string(em.nonmanifold) +
                   " non-manifold edge usage(s)",
               oid, static_cast<double>(em.nonmanifold)});
    r.add({"MESH_INFO", "info",
           std::to_string(mesh.verts.size()) + " nodes, " +
               std::to_string(mesh.faces.size()) + " triangles, " +
               std::to_string(em.boundary) + " boundary edges, " +
               std::to_string(connected_components(mesh.verts.size(),
                                                   mesh.faces)) +
               " component(s)",
           oid, std::nullopt});
    if (hor.provenance.source_version_ids.empty() &&
        hor.horizon_asset_id.empty() && !hor.provenance.demo)
        r.add({"NO_PROVENANCE", "warning",
               "no source version or asset id recorded", oid, std::nullopt});
    return r;
}

QCReport qc_fault(const DomainObject& fault) {
    QCReport r;
    const std::string& oid = fault.object_id;
    if (missing_crs(fault.crs))
        r.add({"MISSING_CRS", "blocker", "CRS unknown", oid, std::nullopt});
    if (fault.verts.empty() || fault.faces.empty()) {
        r.add({"NO_GEOMETRY", "blocker", "no fault geometry", oid,
               std::nullopt});
        return r;
    }
    if (fault.representation == "curtain_2p5d")
        r.add({"CURTAIN_REPRESENTATION", "info",
               "2.5-D curtain swept from a 2-D trace — not a mapped 3-D "
               "surface",
               oid, std::nullopt});
    check_face_bounds(fault.verts, fault.faces);  // v[f] in degenerate
    const double degenerate =
        tri_degenerate_fraction(fault.verts, fault.faces);
    if (degenerate > 0.0)
        r.add({"DEGENERATE_TRIANGLES",
               degenerate > 0.01 ? "error" : "warning",
               pct(degenerate, 2) + " degenerate triangles", oid,
               degenerate});
    const EdgeManifoldStats em = edge_manifold_stats(fault.faces);
    if (em.nonmanifold)
        r.add({"NON_MANIFOLD_EDGES", "warning",
               std::to_string(em.nonmanifold) +
                   " non-manifold edge usage(s)",
               oid, static_cast<double>(em.nonmanifold)});
    return r;
}

QCReport qc_volume(const DomainObject& vol) {
    QCReport r;
    const std::string& oid = vol.object_id;
    if (missing_crs(vol.crs))
        r.add({"MISSING_CRS", "blocker", "CRS unknown", oid, std::nullopt});
    if (vol.top_id.empty() || vol.base_id.empty())
        r.add({"MISSING_BOUNDING_SURFACES", "error",
               "top/base surface references missing", oid, std::nullopt});
    if (vol.verts.empty() || vol.faces.empty()) {
        r.add({"NO_GEOMETRY", "blocker",
               "no shell geometry (build failed or not loaded)", oid,
               std::nullopt});
        return r;
    }
    const EdgeManifoldStats em = edge_manifold_stats(vol.faces);
    if (em.nonmanifold)
        r.add({"NON_MANIFOLD_EDGES", "error",
               std::to_string(em.nonmanifold) +
                   " non-manifold edge usage(s)",
               oid, static_cast<double>(em.nonmanifold)});
    const bool closed = em.nonmanifold == 0 && em.boundary == 0;
    if (!closed)
        r.add({"SHEET_NOT_CLOSED", "blocker",
               "shell not watertight: " + std::to_string(em.boundary) +
                   " boundary edges, " + std::to_string(em.nonmanifold) +
                   " non-manifold",
               oid,
               static_cast<double>(em.boundary + em.nonmanifold)});
    else
        r.add({"WATERTIGHT", "info", "shell is edge-manifold closed", oid,
               std::nullopt});
    check_face_bounds(vol.verts, vol.faces);  // v[f] in degenerate
    const double degenerate =
        tri_degenerate_fraction(vol.verts, vol.faces);
    if (degenerate > 0.0)
        r.add({"DEGENERATE_TRIANGLES",
               degenerate > 0.01 ? "error" : "warning",
               pct(degenerate, 2) + " degenerate triangles", oid,
               degenerate});
    const int components =
        connected_components(vol.verts.size(), vol.faces);
    if (components > 1)
        r.add({"DISCONNECTED_COMPONENTS", "warning",
               std::to_string(components) +
                   " disconnected shell components",
               oid, static_cast<double>(components)});
    const Json q = vol.quality.is_object() ? vol.quality : Json::object();
    const auto qint = [&q](const char* key, std::int64_t dflt) {
        if (!q.contains(key) || q[key].is_null()) return dflt;
        return q[key].get<std::int64_t>();
    };
    const auto qfloat = [&q](const char* key, double dflt) {
        if (!q.contains(key) || q[key].is_null()) return dflt;
        return q[key].get<double>();
    };
    const std::int64_t crossed = qint("dropped_crossed", 0);
    if (crossed)
        r.add({"CROSSED_COLUMNS",
               crossed < qint("column_count", 1) ? "warning" : "error",
               std::to_string(crossed) +
                   " crossed column(s) dropped at build time",
               oid, static_cast<double>(crossed)});
    const double thickness = qfloat("min_thickness", 0.0);
    if (thickness <= 0.0)
        r.add({"ZERO_MIN_THICKNESS", "warning",
               "minimum kept-column thickness is zero (pinch-out)", oid,
               thickness});
    if (vol.provenance.source_version_ids.empty() && !vol.provenance.demo)
        r.add({"NO_PROVENANCE", "warning", "no source version recorded",
               oid, std::nullopt});
    return r;
}

QCReport qc_tunnel(const DomainObject& tunnel) {
    QCReport r;
    const std::string& oid = tunnel.object_id;
    if (tunnel.path.size() < 2)
        r.add({"NO_GEOMETRY", "blocker", "path needs >= 2 points", oid,
               std::nullopt});
    if (missing_crs(tunnel.crs))
        r.add({"MISSING_CRS", "blocker", "CRS unknown", oid, std::nullopt});
    return r;
}

QCReport qc_measure(const DomainObject& m) {
    QCReport r;
    const std::string& oid = m.object_id;
    if (missing_crs(m.crs))
        r.add({"MISSING_CRS", "blocker", "CRS unknown", oid, std::nullopt});
    if (!m.result && m.measurement_kind != "point")
        r.add({"NO_RESULT", "warning",
               "measurement has no computed result", oid, std::nullopt});
    return r;
}

}  // namespace

// ---------------------------------------------------------------------------
// QCIssue / QCReport
// ---------------------------------------------------------------------------

Json QCIssue::to_meta() const {
    return Json{{"code", code},
                {"severity", severity},
                {"message", message},
                {"object_id", object_id},
                {"metric", metric ? Json(*metric) : Json(nullptr)}};
}

void QCReport::add(QCIssue i) { issues.push_back(std::move(i)); }

void QCReport::extend(const QCReport& other) {
    issues.insert(issues.end(), other.issues.begin(), other.issues.end());
}

std::vector<QCIssue> QCReport::of(const std::string& object_id) const {
    std::vector<QCIssue> out;
    for (const auto& i : issues)
        if (i.object_id == object_id) out.push_back(i);
    return out;
}

Json QCReport::severities(const std::optional<std::string>& object_id) const {
    Json counts = Json::object();
    for (const auto& [k, _] : severity_order()) counts[k] = 0;
    for (const auto& i : issues) {
        if (object_id && i.object_id != *object_id) continue;
        counts[i.severity] = counts.value(i.severity, 0) + 1;
    }
    return counts;
}

std::string QCReport::worst(
    const std::optional<std::string>& object_id) const {
    std::string w = "ok";
    for (const auto& i : issues) {
        if (object_id && i.object_id != *object_id) continue;
        if (sev(i.severity) > sev(w, -1)) w = i.severity;
    }
    return w;
}

std::vector<const QCIssue*> QCReport::blockers() const {
    std::vector<const QCIssue*> out;
    for (const auto& i : issues)
        if (i.severity == "blocker") out.push_back(&i);
    return out;
}

Json QCReport::to_meta() const {
    Json arr = Json::array();
    for (const auto& i : issues) arr.push_back(i.to_meta());
    return Json{{"issues", std::move(arr)},
                {"worst", worst()},
                {"severities", severities()}};
}

QCReport QCReport::from_meta(const Json& meta) {
    QCReport r;
    if (meta.contains("issues"))
        for (const auto& e : meta["issues"]) {
            QCIssue i;
            i.code = e.value("code", std::string{});
            i.severity = e.value("severity", std::string{"info"});
            i.message = e.value("message", std::string{});
            i.object_id = e.value("object_id", std::string{});
            if (e.contains("metric") && !e["metric"].is_null())
                i.metric = e["metric"].get<double>();
            r.add(std::move(i));
        }
    return r;
}

// ---------------------------------------------------------------------------
// dispatch
// ---------------------------------------------------------------------------

QCReport qc_object(const DomainObject& obj) {
    const std::string k = obj.kind();
    // Python: except (IndexError, ValueError, TypeError) — DomainError is a
    // ValueError subclass; builders' std::invalid_argument is its C++ twin;
    // std::out_of_range is the C++ IndexError twin.
    auto audit_failed = [&obj](const std::exception& e) {
        QCReport r;
        r.add({"QC_AUDIT_FAILED", "blocker",
               std::string("audit crashed on inconsistent geometry: ") +
                   e.what(),
               obj.object_id, std::nullopt});
        return r;
    };
    try {
        if (k == "well") return qc_well(obj);
        if (k == "horizon") return qc_horizon(obj);
        if (k == "fault") return qc_fault(obj);
        if (k == "volume") return qc_volume(obj);
        if (k == "tunnel") return qc_tunnel(obj);
        if (k == "measure") return qc_measure(obj);
        QCReport r;
        r.add({"UNKNOWN_KIND", "error", "unknown object kind",
               obj.object_id, std::nullopt});
        return r;
    } catch (const IndexError& e) {
        return audit_failed(e);
    } catch (const ValueError& e) {
        return audit_failed(e);
    } catch (const TypeError& e) {
        return audit_failed(e);
    } catch (const std::invalid_argument& e) {
        return audit_failed(e);
    } catch (const std::out_of_range& e) {
        return audit_failed(e);
    }
}

QCReport qc_assembly(
    const ModelAssembly& assembly,
    const std::optional<std::unordered_set<std::string>>& known_source_ids) {
    QCReport r;
    for (const auto& obj : assembly.objects()) {
        r.extend(qc_object(obj));
        if (known_source_ids && !obj.provenance.source_version_ids.empty()) {
            bool any = false;
            for (const auto& id : obj.provenance.source_version_ids)
                if (known_source_ids->count(id)) any = true;
            if (!any) {
                std::set<std::string> sorted(
                    obj.provenance.source_version_ids.begin(),
                    obj.provenance.source_version_ids.end());
                // f"{sorted(ids)}" renders a Python list repr: ['a', 'b']
                std::string ids;
                for (const auto& id : sorted)
                    ids += (ids.empty() ? "" : ", ") + py_repr(Json(id));
                r.add({"STALE_SOURCE", "warning",
                       "source versions [" + ids +
                           "] not resolvable in catalog",
                       obj.object_id, std::nullopt});
            }
        }
    }
    return r;
}

QCReport assert_exportable(const std::vector<DomainObject>& objects,
                           std::optional<QCReport> report) {
    QCReport r = report ? std::move(*report) : QCReport{};
    if (!report)
        for (const auto& o : objects) r.extend(qc_object(o));
    std::set<std::string> blocked;
    for (const auto* i : r.blockers()) blocked.insert(i->object_id);
    if (!blocked.empty()) {
        std::string ids;
        for (const auto& id : blocked)
            ids += (ids.empty() ? "" : ", ") + id;
        std::string msg =
            "export refused: blocker-level QC issues in " + ids + "\n";
        bool first = true;
        for (const auto* i : r.blockers()) {
            if (!first) msg += "\n";
            msg += "  [" + i->object_id + "] " + i->code + ": " + i->message;
            first = false;
        }
        throw QCBlockerError(msg);
    }
    return r;
}

}  // namespace pwb::geomodel
