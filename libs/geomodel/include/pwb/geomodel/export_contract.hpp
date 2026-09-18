#pragma once

// pwb::geomodel — export contract layer (CONV-22): faithful C++ port of
// paleo_workbench/viz/geomodel/exporters.py — the V2 domain exporters
// (FLAC3D grid / Abaqus INP / OBJ / binary STL / VTK XML PolyData), the
// read-back parser validators, validate_export, the provenance sidecar and
// the legacy synthetic GridSpec exports.
//
// File I/O is a thin shell: the API returns the exact bytes the Python
// writer emits plus the sidecar JSON text — the caller (or the test)
// decides where to write. read_* take the bytes back and return the same
// structure the Python parsers return (as Json; arrays -> lists).
//
// Frozen against geomodel_contract_oracle.json.

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/geomodel/builders.hpp>      // HorizonGrid, HexMesh
#include <pwb/geomodel/domain_contract.hpp>
#include <pwb/geomodel/qc_contract.hpp>

namespace pwb::geomodel {

using pwb::domain::Json;

struct ExportError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

struct ExportWritten {
    std::string file;         // exact bytes (text formats are utf-8)
    std::string sidecar_name; // "<stem>.provenance.json"
    Json sidecar;             // the provenance dict the writer persists
};

// _sheet_horizons: explicit top/base grids when provided; otherwise the
// shell's own vertex sheets regridded onto their lattice. Returns the
// HorizonGrid pair the hex builder consumes.
std::pair<HorizonGrid, HorizonGrid> sheet_horizons(
    const DomainObject& volume,
    const std::optional<HorizonGrid>& top,
    const std::optional<HorizonGrid>& base);

// V2 exporters — gate on assert_exportable (QCBlockerError passes through),
// ExportError on contract violations.
ExportWritten export_volume_flac3d(
    const DomainObject& volume, const std::string& out_name,
    const std::optional<HorizonGrid>& top = std::nullopt,
    const std::optional<HorizonGrid>& base = std::nullopt, int n_layers = 4,
    const std::string& zone_name = "GEOMODEL");

ExportWritten export_volume_abaqus(
    const DomainObject& volume, const std::string& out_name,
    const std::optional<HorizonGrid>& top = std::nullopt,
    const std::optional<HorizonGrid>& base = std::nullopt, int n_layers = 4,
    const std::string& part_name = "GEOMODEL");

ExportWritten export_mesh_obj(const DomainObject& obj,
                              const std::string& out_name,
                              const std::optional<std::string>& label =
                                  std::nullopt);

ExportWritten export_mesh_stl(const DomainObject& obj,
                              const std::string& out_name);

// point_data keeps Python Mapping insertion order (empty = no PointData
// element, matching `if point_data:` truthiness).
ExportWritten export_mesh_vtp(
    const DomainObject& obj, const std::string& out_name,
    const std::vector<std::pair<std::string, std::vector<double>>>&
        point_data = {});

// Parser validators — same dict shape as the Python readers (arrays as
// Json lists). `name` is the path text used in error messages.
Json read_flac3d_grid(std::string_view text, const std::string& name);
Json read_abaqus_inp(std::string_view text, const std::string& name);
Json read_obj(std::string_view text, const std::string& name);
Json read_stl(std::string_view bytes, const std::string& name);
Json read_vtp(std::string_view text, const std::string& name);

// validate_export — suffix dispatch on `name`; mesh formats also check the
// source object's counts/bounds (atol=1e-4).
Json validate_export(const std::string& name, std::string_view bytes,
                     const DomainObject& obj);

// _generate_structured_grid: (nodes (N,3), elements (M,8)) for GridSpec.
struct StructuredGrid {
    std::vector<Vec3> nodes;
    std::vector<std::array<std::int64_t, 8>> elements;
};
StructuredGrid generate_structured_grid(int nx, int ny, int nz, double dx,
                                        double dy, double dz);

// Legacy exports — synthetic GridSpec files; the Python functions return
// True on success (they re-raise on failure).
std::string legacy_export_to_flac3d(int nx, int ny, int nz, double dx,
                                    double dy, double dz);
std::string legacy_export_to_abaqus(int nx, int ny, int nz, double dx,
                                    double dy, double dz);

}  // namespace pwb::geomodel
