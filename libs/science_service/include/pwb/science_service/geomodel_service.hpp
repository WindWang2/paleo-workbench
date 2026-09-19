#pragma once

// pwb::science_service — geomodel runtime services (CONV-28): typed
// request/result envelopes over the frozen geomodel kernels (CONV-12) and
// contract cores (CONV-22). Small-model scope by design: the resource guard
// bounds vertices, and the acceptance fixture is a compact two-horizon
// model — no 100 GB 3-D volumes (out of scope for the whole direction).
//
//   geomodel.build  — two horizon grids (+ optional boundary ring) ->
//     build_volume_shell (thicknesses + ShellQc) and optionally
//     build_columnar_hex_mesh; volume via closed_mesh_volume; QC numbers via
//     mesh_qc (degenerate fraction / edge manifold / components).
//   geomodel.section — axis or general plane vs a horizon grid or the built
//     shell mesh -> chained section polylines (horizon_plane_intersection /
//     mesh_plane_intersection + chain_segments).
//   geomodel.fault_displacement — apply_fault_throw over mesh vertices.
//   geomodel.export  — DomainObject + format name -> export_contract
//     writers (bytes + provenance sidecar; the caller persists), gated by
//     the QC ladder (blockers refuse the export, mirroring
//     assert_exportable semantics).
//
// Exports return BYTES; this service never writes the filesystem — the
// publisher seam owns persistence.

#include <pwb/geomodel/builders.hpp>
#include <pwb/geomodel/domain_contract.hpp>
#include <pwb/geomodel/fault_displacement.hpp>
#include <pwb/geomodel/section.hpp>
#include <pwb/science/algorithm.hpp>
#include <pwb/science/outcome.hpp>

#include <stop_token>

#include <array>
#include <optional>
#include <string>
#include <vector>

#include "envelope.hpp"
#include "limits.hpp"

namespace pwb::science_service {

// ---------------------------------------------------------------------------
// build
// ---------------------------------------------------------------------------

// Horizon grid DTO shape (JSON):
//   {"rows": int, "cols": int, "origin": [x, y], "spacing": [dy, dx],
//    "vertical_domain": "depth|twt|tvdss", "unit": "m", "z": [[...]]}
// z is row-major rows*cols; NaN = hole (the kernel contract).

struct GeomodelBuildRequest {
    pwb::domain::Json top;
    pwb::domain::Json base;
    // Boundary ring for the shell column test; nullopt = full grid extent
    // rectangle (production default for unclipped models).
    std::optional<std::vector<std::array<double, 2>>> boundary;
    std::string object_id = "vol:service";
    bool build_hex = false;
    int hex_layers = 4;
};

struct GeomodelBuildResult {
    ScienceEnvelope envelope;
    pwb::geomodel::HorizonGrid top_grid;
    pwb::geomodel::HorizonGrid base_grid;
    pwb::geomodel::VolumeShell shell;
    std::optional<pwb::geomodel::HexMesh> hex;
};

class GeomodelBuildService {
public:
    explicit GeomodelBuildService(
        std::string build_identity = "local",
        ResourceLimits limits = ResourceLimits::defaults());

    [[nodiscard]] science::Result<GeomodelBuildResult> run(
        const GeomodelBuildRequest& request,
        science::ProgressSink progress = nullptr,
        std::stop_token stop = {});

private:
    std::string build_identity_;
    ResourceLimits limits_;
};

// ---------------------------------------------------------------------------
// section extraction
// ---------------------------------------------------------------------------

struct GeomodelSectionRequest {
    // Either a horizon grid DTO (see GeomodelBuildRequest) or a mesh
    // {"verts": [[x,y,z],...], "faces": [[i,j,k],...]}.
    pwb::domain::Json source;
    // Plane: {"axis": "x"|"y"|"z", "value": v} or
    // {"normal": [nx,ny,nz], "point": [px,py,pz]}.
    pwb::domain::Json plane;
};

struct GeomodelSectionResult {
    ScienceEnvelope envelope;
    std::vector<std::vector<pwb::geomodel::Vec3>> polylines;
};

class GeomodelSectionService {
public:
    explicit GeomodelSectionService(
        std::string build_identity = "local",
        ResourceLimits limits = ResourceLimits::defaults());

    [[nodiscard]] science::Result<GeomodelSectionResult> run(
        const GeomodelSectionRequest& request,
        science::ProgressSink progress = nullptr,
        std::stop_token stop = {});

private:
    std::string build_identity_;
    ResourceLimits limits_;
};

// ---------------------------------------------------------------------------
// fault displacement
// ---------------------------------------------------------------------------

struct FaultDisplacementRequest {
    // Mesh DTO: {"verts": [[x,y,z],...], "faces": [[i,j,k],...]}.
    pwb::domain::Json mesh;
    // {"fault_line": [[x,y],...], "throw_z": m, "throw_x": m,
    //  "dip_deg": 60, "strike_deg": 0, "decay_radius": m}
    pwb::domain::Json spec;
};

class FaultDisplacementService {
public:
    explicit FaultDisplacementService(
        std::string build_identity = "local",
        ResourceLimits limits = ResourceLimits::defaults());

    // Envelope payload carries the displaced vertices (float64 triples,
    // non-finite guarded to null — the kernel never emits them).
    [[nodiscard]] science::Result<ScienceEnvelope> run(
        const FaultDisplacementRequest& request,
        science::ProgressSink progress = nullptr,
        std::stop_token stop = {});

private:
    std::string build_identity_;
    ResourceLimits limits_;
};

// ---------------------------------------------------------------------------
// export (bytes + provenance sidecar; QC-gated)
// ---------------------------------------------------------------------------

struct GeomodelExportRequest {
    // DomainObject spec dict (geomodel domain_contract shape) or the compact
    // build form: {"kind": "volume", "top": {...grid...}, "base": {...},
    // "boundary": [[x,y],...], "object_id": "..."} — the service assembles
    // the DomainObject either way.
    pwb::domain::Json object;
    // "obj" | "stl" | "vtp" | "flac3d" | "abaqus"
    std::string format;
    std::string out_name;  // file name used in the sidecar ("model.obj")
    int hex_layers = 4;    // volume exporters only
};

struct GeomodelExportResult {
    ScienceEnvelope envelope;
    std::string file_bytes;
    std::string sidecar_name;
    pwb::domain::Json sidecar;
};

class GeomodelExportService {
public:
    explicit GeomodelExportService(
        std::string build_identity = "local",
        ResourceLimits limits = ResourceLimits::defaults());

    [[nodiscard]] science::Result<GeomodelExportResult> run(
        const GeomodelExportRequest& request,
        science::ProgressSink progress = nullptr,
        std::stop_token stop = {});

private:
    std::string build_identity_;
    ResourceLimits limits_;
};

// Parse the horizon grid DTO shared by build/section (throws
// std::invalid_argument with a stable message on a foreign shape).
[[nodiscard]] pwb::geomodel::HorizonGrid horizon_grid_from_json(
    const pwb::domain::Json& spec);

// Assemble a DomainObject from the export request's object dict (throws with
// a stable message on a foreign shape). "kind" selects the assembly path;
// volume objects may inline top/base grids + boundary.
[[nodiscard]] pwb::geomodel::DomainObject domain_object_from_request(
    const pwb::domain::Json& object);

}  // namespace pwb::science_service
