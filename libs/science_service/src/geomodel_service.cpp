// pwb::science_service — geomodel service implementation.

#include <pwb/science_service/geomodel_service.hpp>

#include <pwb/geomodel/export_contract.hpp>
#include <pwb/geomodel/mesh_qc.hpp>
#include <pwb/geomodel/volume.hpp>
#include <pwb/factor_host/fingerprint.hpp>

#include <algorithm>
#include <cmath>
#include <set>
#include <utility>

#include "support.hpp"

namespace pwb::science_service {

using pwb::domain::Json;
using pwb::geomodel::Vec3;

namespace {

[[nodiscard]] std::vector<double> double_array(const Json& v,
                                               const std::string& what) {
    if (!v.is_array()) {
        throw std::invalid_argument(what + " must be an array");
    }
    std::vector<double> out;
    out.reserve(v.size());
    for (const auto& item : v) {
        if (!item.is_number()) {
            throw std::invalid_argument(what + " must contain only numbers");
        }
        out.push_back(item.get<double>());
    }
    return out;
}

[[nodiscard]] std::vector<std::array<double, 2>> ring_from_json(
    const Json& v, const std::string& what) {
    if (!v.is_array()) {
        throw std::invalid_argument(what + " must be an array of [x, y]");
    }
    std::vector<std::array<double, 2>> out;
    out.reserve(v.size());
    for (const auto& item : v) {
        const auto xy = double_array(item, what);
        if (xy.size() != 2) {
            throw std::invalid_argument(what + " entries must be [x, y] pairs");
        }
        out.push_back({xy[0], xy[1]});
    }
    return out;
}

// Lattice vertex sheet of a horizon grid (row-major), z from the grid
// (NaN holes ride along — closed_mesh_volume keeps them out of faces by
// construction when used through the shell; here we mirror the sheet the
// volume kernel expects: top/base vertex arrays of rows*cols).
[[nodiscard]] std::vector<Vec3> horizon_sheet(
    const pwb::geomodel::HorizonGrid& g) {
    std::vector<Vec3> out;
    out.reserve(static_cast<std::size_t>(g.rows) * g.cols);
    for (int i = 0; i < g.rows; ++i) {
        for (int j = 0; j < g.cols; ++j) {
            out.push_back(
                {g.origin_x + j * g.spacing_x, g.origin_y + i * g.spacing_y,
                 g.at(i, j)});
        }
    }
    return out;
}

// Full-extent rectangle in grid walk order (origin -> +x -> +y). The shell
// kernel requires M >= 3 boundary points, so "no boundary given" means the
// whole lattice, never an error.
[[nodiscard]] std::vector<std::array<double, 2>> default_boundary(
    const pwb::geomodel::HorizonGrid& g) {
    const double x0 = g.origin_x;
    const double y0 = g.origin_y;
    const double x1 = x0 + (g.cols - 1) * g.spacing_x;
    const double y1 = y0 + (g.rows - 1) * g.spacing_y;
    return {{x0, y0}, {x1, y0}, {x1, y1}, {x0, y1}};
}

[[nodiscard]] std::vector<Vec3> verts_from_json(const Json& mesh) {
    if (!mesh.is_object() || !mesh.contains("verts")) {
        throw std::invalid_argument("mesh must be an object with 'verts'");
    }
    std::vector<Vec3> out;
    for (const auto& v : mesh.at("verts")) {
        const auto xyz = double_array(v, "verts");
        if (xyz.size() != 3) {
            throw std::invalid_argument("verts entries must be [x, y, z]");
        }
        out.push_back({xyz[0], xyz[1], xyz[2]});
    }
    return out;
}

[[nodiscard]] std::vector<std::array<std::int64_t, 3>> faces_from_json(
    const Json& mesh) {
    if (!mesh.is_object() || !mesh.contains("faces")) {
        throw std::invalid_argument("mesh must be an object with 'faces'");
    }
    std::vector<std::array<std::int64_t, 3>> out;
    for (const auto& f : mesh.at("faces")) {
        if (!f.is_array() || f.size() != 3 || !f.at(0).is_number_integer()
            || !f.at(1).is_number_integer() || !f.at(2).is_number_integer()) {
            throw std::invalid_argument(
                "faces entries must be integer [i, j, k] triples");
        }
        out.push_back({f.at(0).get<std::int64_t>(),
                       f.at(1).get<std::int64_t>(),
                       f.at(2).get<std::int64_t>()});
    }
    return out;
}

Json shell_qc_json(const pwb::geomodel::ShellQc& qc) {
    Json out = Json::object();
    out["column_count"] = qc.column_count;
    out["dropped_crossed"] = qc.dropped_crossed;
    out["dropped_nan_nodes"] = qc.dropped_nan_nodes;
    out["negative_thickness_count"] = qc.negative_thickness_count;
    out["min_thickness"] = std::isfinite(qc.min_thickness) ? Json(qc.min_thickness)
                                                           : Json(nullptr);
    out["max_thickness"] = std::isfinite(qc.max_thickness) ? Json(qc.max_thickness)
                                                           : Json(nullptr);
    out["mean_thickness"] = std::isfinite(qc.mean_thickness)
                                ? Json(qc.mean_thickness)
                                : Json(nullptr);
    out["closed"] = qc.closed;
    out["unit"] = qc.unit;
    return out;
}

}  // namespace

pwb::geomodel::HorizonGrid horizon_grid_from_json(const Json& spec) {
    if (!spec.is_object() || !spec.contains("rows") || !spec.contains("cols")
        || !spec.contains("z")) {
        throw std::invalid_argument(
            "horizon grid must be an object with rows / cols / z");
    }
    const int rows = spec.at("rows").get<int>();
    const int cols = spec.at("cols").get<int>();
    std::array<double, 2> origin{0.0, 0.0};
    std::array<double, 2> spacing{1.0, 1.0};
    if (spec.contains("origin")) {
        const auto v = double_array(spec.at("origin"), "origin");
        if (v.size() == 2) origin = {v[0], v[1]};
    }
    if (spec.contains("spacing")) {
        const auto v = double_array(spec.at("spacing"), "spacing");
        if (v.size() == 2) spacing = {v[0], v[1]};  // [dy, dx]
    }
    const std::string vertical_domain =
        spec.value("vertical_domain", std::string("depth"));
    const std::string unit = spec.value("unit", std::string("m"));
    const std::string object_id =
        spec.value("object_id", std::string("horizon:service"));

    std::vector<double> z;
    const Json& z_json = spec.at("z");
    if (z_json.is_array() && !z_json.empty() && z_json.at(0).is_array()) {
        for (const auto& row : z_json) {
            for (double v : double_array(row, "z")) {
                z.push_back(v);
            }
        }
    } else {
        z = double_array(z_json, "z");
    }
    // build_horizon_from_grid carries the frozen finite/shape validation
    // (NaN is the only allowed hole; rows*cols must match z length).
    return pwb::geomodel::build_horizon_from_grid(
        rows, cols, origin[0], origin[1], spacing[0], spacing[1],
        std::move(z), vertical_domain, unit, object_id);
}

pwb::geomodel::DomainObject domain_object_from_request(const Json& object) {
    if (!object.is_object()) {
        throw std::invalid_argument("object must be a JSON object");
    }
    const std::string kind = object.value("kind", std::string());
    if (kind == "volume" && object.contains("top") && object.contains("base")) {
        // Compact build form: assemble the volume DomainObject from the two
        // horizon grids + boundary, mesh via build_volume_shell (contract:
        // volume objects carry the shell mesh + grid metadata).
        auto top = horizon_grid_from_json(object.at("top"));
        auto base = horizon_grid_from_json(object.at("base"));
        std::vector<std::array<double, 2>> boundary;
        if (object.contains("boundary") && !object.at("boundary").is_null()) {
            boundary = ring_from_json(object.at("boundary"), "boundary");
        } else {
            boundary = default_boundary(top);
        }
        const std::string object_id =
            object.value("object_id", std::string("volume:service"));
        auto shell = pwb::geomodel::build_volume_shell(top, base, boundary,
                                                       object_id);
        pwb::geomodel::DomainObject obj;
        obj.object_id = object_id;
        obj.name = object.value("name", object_id);
        obj.crs = object.value("crs", std::string("unknown"));
        obj.vertical_domain = top.vertical_domain;
        obj.unit = top.unit;
        obj.verts = std::move(shell.mesh.verts);
        obj.faces = std::move(shell.mesh.faces);
        obj.top_id = object.value("top_id", std::string("horizon:top"));
        obj.base_id = object.value("base_id", std::string("horizon:base"));
        obj.boundary = boundary;
        return obj;
    }
    // Full domain_contract spec path (object_from_spec carries the frozen
    // validation + error texts).
    return pwb::geomodel::object_from_spec(object);
}

// ---------------------------------------------------------------------------
// GeomodelBuildService
// ---------------------------------------------------------------------------

GeomodelBuildService::GeomodelBuildService(std::string build_identity,
                                           ResourceLimits limits)
    : build_identity_(std::move(build_identity)), limits_(limits) {}

science::Result<GeomodelBuildResult> GeomodelBuildService::run(
    const GeomodelBuildRequest& request, science::ProgressSink progress,
    std::stop_token stop) {
    if (detail::stage_guard(stop, progress, 0.05, "validate")) {
        return science::TaskCancelled{"validate"};
    }
    auto top_res = detail::catch_kernel<pwb::geomodel::HorizonGrid>(
        "geomodel.grid", [&] { return horizon_grid_from_json(request.top); });
    if (top_res.is_error()) {
        return top_res.error();
    }
    auto base_res = detail::catch_kernel<pwb::geomodel::HorizonGrid>(
        "geomodel.grid", [&] { return horizon_grid_from_json(request.base); });
    if (base_res.is_error()) {
        return base_res.error();
    }
    auto& top = top_res.value();
    auto& base = base_res.value();
    const std::size_t lattice =
        static_cast<std::size_t>(top.rows) * top.cols;
    if (lattice > limits_.max_geomodel_vertices) {
        return detail::make_error(
            limit_code("geomodel_vertices"),
            "horizon lattice of " + std::to_string(lattice)
                + " nodes exceeds limit "
                + std::to_string(limits_.max_geomodel_vertices));
    }

    std::vector<std::array<double, 2>> boundary =
        request.boundary ? *request.boundary : default_boundary(top);
    if (detail::stage_guard(stop, progress, 0.3, "grids")) {
        return science::TaskCancelled{"grids"};
    }
    auto shell_res = detail::catch_kernel<pwb::geomodel::VolumeShell>(
        "geomodel.build", [&] {
            return pwb::geomodel::build_volume_shell(top, base, boundary,
                                                     request.object_id);
        });
    if (shell_res.is_error()) {
        return shell_res.error();
    }
    if (detail::stage_guard(stop, progress, 0.6, "shell")) {
        return science::TaskCancelled{"shell"};
    }
    auto shell = std::move(shell_res.value());

    std::optional<pwb::geomodel::HexMesh> hex;
    if (request.build_hex) {
        auto hex_res = detail::catch_kernel<pwb::geomodel::HexMesh>(
            "geomodel.build_hex", [&] {
                return pwb::geomodel::build_columnar_hex_mesh(
                    top, base, boundary, request.hex_layers);
            });
        if (hex_res.is_error()) {
            return hex_res.error();
        }
        hex = std::move(hex_res.value());
    }
    if (detail::stage_guard(stop, progress, 0.8, "hex")) {
        return science::TaskCancelled{"hex"};
    }

    // Volume between the two lattice sheets (float64 divergence theorem).
    const double volume = pwb::geomodel::closed_mesh_volume(
        horizon_sheet(top), horizon_sheet(base),
        static_cast<std::size_t>(top.rows),
        static_cast<std::size_t>(top.cols));

    // Mesh QC numerics (mesh_qc kernels).
    const double degenerate =
        pwb::geomodel::tri_degenerate_fraction(shell.mesh.verts,
                                               shell.mesh.faces);
    const auto manifold = pwb::geomodel::edge_manifold_stats(shell.mesh.faces);
    const int components = pwb::geomodel::connected_components(
        static_cast<int>(shell.mesh.verts.size()), shell.mesh.faces);

    ScienceEnvelope envelope;
    envelope.result_type = "geomodel_build";
    envelope.units = top.unit;
    Json quality = Json::object();
    quality["shell"] = shell_qc_json(shell.qc);
    quality["mesh"] = Json{
        {"degenerate_fraction", degenerate},
        {"boundary_edges", manifold.boundary},
        {"nonmanifold_edges", manifold.nonmanifold},
        {"connected_components", components},
        {"n_vertices", static_cast<std::uint64_t>(shell.mesh.verts.size())},
        {"n_faces", static_cast<std::uint64_t>(shell.mesh.faces.size())},
    };
    quality["volume"] = volume;
    envelope.quality = std::move(quality);
    envelope.extent = std::array<double, 4>{
        top.origin_x, top.origin_y,
        top.origin_x + (top.cols - 1) * top.spacing_x,
        top.origin_y + (top.rows - 1) * top.spacing_y};

    Json payload = Json::object();
    payload["object_id"] = request.object_id;
    payload["vertical_domain"] = top.vertical_domain;
    payload["n_thicknesses"] =
        static_cast<std::uint64_t>(shell.thicknesses.size());
    Json thicknesses = Json::array();
    for (double t : shell.thicknesses) {
        thicknesses.push_back(std::isfinite(t) ? Json(t) : Json(nullptr));
    }
    payload["thicknesses"] = std::move(thicknesses);
    if (hex) {
        payload["hex"] = Json{
            {"n_cells", hex->info.n_cells},
            {"n_layers", hex->info.n_layers},
            {"n_hexes", hex->info.n_hexes},
            {"skipped_crossed", hex->info.skipped_crossed},
            {"n_nodes", static_cast<std::uint64_t>(hex->nodes.size())},
        };
    }
    envelope.payload = std::move(payload);
    Json provenance = Json::object();
    provenance["algorithm_id"] = "geomodel.build";
    provenance["algorithm_version"] = "1.0.0";
    provenance["build_identity"] = build_identity_;
    provenance["top_object_id"] = top.object_id;
    provenance["base_object_id"] = base.object_id;
    provenance["boundary_points"] = static_cast<int>(boundary.size());
    envelope.provenance = std::move(provenance);
    envelope.compute_fingerprint();

    GeomodelBuildResult result;
    result.envelope = std::move(envelope);
    result.top_grid = std::move(top);
    result.base_grid = std::move(base);
    result.shell = std::move(shell);
    result.hex = std::move(hex);
    detail::stage_guard(stop, progress, 1.0, "envelope");
    return result;
}

// ---------------------------------------------------------------------------
// GeomodelSectionService
// ---------------------------------------------------------------------------

GeomodelSectionService::GeomodelSectionService(std::string build_identity,
                                               ResourceLimits limits)
    : build_identity_(std::move(build_identity)), limits_(limits) {}

science::Result<GeomodelSectionResult> GeomodelSectionService::run(
    const GeomodelSectionRequest& request, science::ProgressSink progress,
    std::stop_token stop) {
    if (detail::stage_guard(stop, progress, 0.1, "validate")) {
        return science::TaskCancelled{"validate"};
    }
    // Plane.
    auto plane_res = detail::catch_kernel<pwb::geomodel::Plane>(
        "geomodel.plane", [&]() -> pwb::geomodel::Plane {
            if (!request.plane.is_object()) {
                throw std::invalid_argument("plane must be an object");
            }
            if (request.plane.contains("axis")) {
                return pwb::geomodel::axis_plane(
                    request.plane.at("axis").get<std::string>(),
                    request.plane.value("value", 0.0));
            }
            if (request.plane.contains("normal")
                && request.plane.contains("point")) {
                const auto n = double_array(request.plane.at("normal"), "normal");
                const auto p = double_array(request.plane.at("point"), "point");
                if (n.size() != 3 || p.size() != 3) {
                    throw std::invalid_argument(
                        "normal / point must be 3-vectors");
                }
                return pwb::geomodel::plane_from_normal_point(
                    {n[0], n[1], n[2]}, {p[0], p[1], p[2]});
            }
            throw std::invalid_argument(
                "plane needs 'axis'+'value' or 'normal'+'point'");
        });
    if (plane_res.is_error()) {
        return plane_res.error();
    }
    const auto& plane = plane_res.value();

    // Source: horizon grid or mesh.
    auto section_res = detail::catch_kernel<
        std::vector<std::vector<Vec3>>>(
        "geomodel.section", [&]() -> std::vector<std::vector<Vec3>> {
            if (!request.source.is_object()) {
                throw std::invalid_argument("source must be an object");
            }
            if (request.source.contains("z") && request.source.contains("rows")) {
                const auto grid = horizon_grid_from_json(request.source);
                return pwb::geomodel::horizon_plane_intersection(plane, grid);
            }
            const auto verts = verts_from_json(request.source);
            const auto faces = faces_from_json(request.source);
            if (verts.size() > limits_.max_geomodel_vertices) {
                throw std::invalid_argument(
                    "mesh exceeds vertex limit "
                    + std::to_string(limits_.max_geomodel_vertices));
            }
            return pwb::geomodel::mesh_plane_intersection(plane, verts, faces);
        });
    if (section_res.is_error()) {
        return section_res.error();
    }
    if (detail::stage_guard(stop, progress, 0.8, "section")) {
        return science::TaskCancelled{"section"};
    }
    auto polylines = std::move(section_res.value());

    ScienceEnvelope envelope;
    envelope.result_type = "geomodel_section";
    Json payload = Json::object();
    payload["plane"] = request.plane;
    payload["n_polylines"] = static_cast<std::uint64_t>(polylines.size());
    Json lines = Json::array();
    for (const auto& line : polylines) {
        Json pts = Json::array();
        for (const Vec3& p : line) {
            pts.push_back(Json::array({p[0], p[1], p[2]}));
        }
        lines.push_back(std::move(pts));
    }
    payload["polylines"] = std::move(lines);
    envelope.payload = std::move(payload);
    Json provenance = Json::object();
    provenance["algorithm_id"] = "geomodel.section";
    provenance["algorithm_version"] = "1.0.0";
    provenance["build_identity"] = build_identity_;
    envelope.provenance = std::move(provenance);
    envelope.compute_fingerprint();

    GeomodelSectionResult result;
    result.envelope = std::move(envelope);
    result.polylines = std::move(polylines);
    detail::stage_guard(stop, progress, 1.0, "envelope");
    return result;
}

// ---------------------------------------------------------------------------
// FaultDisplacementService
// ---------------------------------------------------------------------------

FaultDisplacementService::FaultDisplacementService(std::string build_identity,
                                                   ResourceLimits limits)
    : build_identity_(std::move(build_identity)), limits_(limits) {}

science::Result<ScienceEnvelope> FaultDisplacementService::run(
    const FaultDisplacementRequest& request, science::ProgressSink progress,
    std::stop_token stop) {
    if (detail::stage_guard(stop, progress, 0.1, "validate")) {
        return science::TaskCancelled{"validate"};
    }
    auto displaced = detail::catch_kernel<std::vector<Vec3>>(
        "geomodel.fault_displacement", [&]() -> std::vector<Vec3> {
            const auto verts = verts_from_json(request.mesh);
            if (verts.size() > limits_.max_geomodel_vertices) {
                throw std::invalid_argument(
                    "mesh exceeds vertex limit "
                    + std::to_string(limits_.max_geomodel_vertices));
            }
            if (!request.spec.is_object()
                || !request.spec.contains("fault_line")) {
                throw std::invalid_argument(
                    "spec must be an object with 'fault_line'");
            }
            const auto line =
                ring_from_json(request.spec.at("fault_line"), "fault_line");
            if (line.empty()) {
                throw std::invalid_argument(
                    "spec fault_line must carry at least one [x, y] anchor");
            }
            pwb::geomodel::FaultSpec spec;
            // The kernel takes a single anchor point; the production
            // adapter reduces the trace to its first vertex.
            spec.fault_line_x = line.front()[0];
            spec.fault_line_y = line.front()[1];
            spec.throw_z = request.spec.value("throw_z", 0.0);
            spec.throw_x = request.spec.value("throw_x", 0.0);
            spec.dip_deg = request.spec.value("dip_deg", 60.0);
            spec.strike_deg = request.spec.value("strike_deg", 0.0);
            spec.decay_radius = request.spec.value("decay_radius", 100.0);
            return pwb::geomodel::apply_fault_throw(verts, spec);
        });
    if (displaced.is_error()) {
        return displaced.error();
    }
    if (detail::stage_guard(stop, progress, 0.8, "displace")) {
        return science::TaskCancelled{"displace"};
    }

    ScienceEnvelope envelope;
    envelope.result_type = "geomodel_fault_displacement";
    envelope.units = "m";
    Json payload = Json::object();
    payload["spec"] = request.spec;
    payload["n_vertices"] =
        static_cast<std::uint64_t>(displaced.value().size());
    Json verts = Json::array();
    for (const Vec3& p : displaced.value()) {
        verts.push_back(Json::array({p[0], p[1], p[2]}));
    }
    payload["verts"] = std::move(verts);
    envelope.payload = std::move(payload);
    Json provenance = Json::object();
    provenance["algorithm_id"] = "geomodel.fault_displacement";
    provenance["algorithm_version"] = "1.0.0";
    provenance["build_identity"] = build_identity_;
    envelope.provenance = std::move(provenance);
    envelope.compute_fingerprint();
    detail::stage_guard(stop, progress, 1.0, "envelope");
    return envelope;
}

// ---------------------------------------------------------------------------
// GeomodelExportService
// ---------------------------------------------------------------------------

GeomodelExportService::GeomodelExportService(std::string build_identity,
                                             ResourceLimits limits)
    : build_identity_(std::move(build_identity)), limits_(limits) {}

science::Result<GeomodelExportResult> GeomodelExportService::run(
    const GeomodelExportRequest& request, science::ProgressSink progress,
    std::stop_token stop) {
    if (detail::stage_guard(stop, progress, 0.1, "validate")) {
        return science::TaskCancelled{"validate"};
    }
    auto written = detail::catch_kernel<pwb::geomodel::ExportWritten>(
        "geomodel.export", [&]() -> pwb::geomodel::ExportWritten {
            auto obj = domain_object_from_request(request.object);
            if (obj.verts.size() > limits_.max_geomodel_vertices) {
                throw std::invalid_argument(
                    "object exceeds vertex limit "
                    + std::to_string(limits_.max_geomodel_vertices));
            }
            // QC gate first (assert_exportable semantics: blockers refuse).
            pwb::geomodel::assert_exportable({obj}, std::nullopt);
            const std::string& fmt = request.format;
            if (fmt == "obj") {
                return pwb::geomodel::export_mesh_obj(obj, request.out_name);
            }
            if (fmt == "stl") {
                return pwb::geomodel::export_mesh_stl(obj, request.out_name);
            }
            if (fmt == "vtp") {
                return pwb::geomodel::export_mesh_vtp(obj, request.out_name);
            }
            if (fmt == "flac3d") {
                return pwb::geomodel::export_volume_flac3d(
                    obj, request.out_name, std::nullopt, std::nullopt,
                    request.hex_layers);
            }
            if (fmt == "abaqus") {
                return pwb::geomodel::export_volume_abaqus(
                    obj, request.out_name, std::nullopt, std::nullopt,
                    request.hex_layers);
            }
            throw std::invalid_argument(
                "unknown export format '" + fmt
                + "' (obj | stl | vtp | flac3d | abaqus)");
        });
    if (written.is_error()) {
        return written.error();
    }
    if (detail::stage_guard(stop, progress, 0.85, "write")) {
        return science::TaskCancelled{"write"};
    }

    ScienceEnvelope envelope;
    envelope.result_type = "geomodel_export";
    Json payload = Json::object();
    payload["format"] = request.format;
    payload["out_name"] = request.out_name;
    payload["sidecar_name"] = written.value().sidecar_name;
    payload["sidecar"] = written.value().sidecar;
    payload["file_size_bytes"] = written.value().file.size();
    payload["file_sha256"] = pwb::factor_host::stable_sha256(
        Json(written.value().file));
    envelope.payload = std::move(payload);
    Json provenance = Json::object();
    provenance["algorithm_id"] = "geomodel.export";
    provenance["algorithm_version"] = "1.0.0";
    provenance["build_identity"] = build_identity_;
    envelope.provenance = std::move(provenance);
    envelope.compute_fingerprint();

    GeomodelExportResult result;
    result.envelope = std::move(envelope);
    result.file_bytes = std::move(written.value().file);
    result.sidecar_name = written.value().sidecar_name;
    result.sidecar = written.value().sidecar;
    detail::stage_guard(stop, progress, 1.0, "envelope");
    return result;
}

}  // namespace pwb::science_service
