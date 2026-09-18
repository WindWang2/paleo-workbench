#pragma once

// pwb::interchange — 3D model export adapters (conv-14b). Link note: these
// symbols require the geomodel-enabled build (CMake compiles
// model_adapters.cpp/service.cpp only when Pwb::GeoModel is configured).
// Faithful port of
// paleo_workbench/interchange/adapters/model_adapter.py (FLAC3D .f3grid and
// Abaqus .inp) plus the narrow slice of registry.py / contracts.py those
// adapters consume.
//
// These are *write-only* formats in this repository (structured hex grids
// from viz/geomodel.exporters, already ported by CONV-22 as
// pwb::geomodel::export_contract::legacy_export_to_* — reused here, never
// duplicated). The adapter adds the missing half: structural verification
// that re-parses the written file — gridpoint/zone counts, 1-based
// contiguous numbering, node-reference range checks, finite coordinates —
// plus a structural inspect for existing files (single strict pass).
//
// VTK family / OBJ / STL have no reader or writer anywhere in the repo; the
// Python side declares them capability-unavailable (adapters/unavailable.py)
// and this port mirrors that honesty by simply not registering them.

#include <pwb/domain/json.hpp>
#include <pwb/interchange/contracts.hpp>
#include <pwb/interchange/preflight.hpp>  // InspectionResult / ImportPlan

#include <filesystem>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace pwb::interchange {

using pwb::domain::Json;

struct MeshFacts {
    long long gridpoints = 0;
    long long zones = 0;
    std::vector<std::string> problems;

    bool operator==(const MeshFacts&) const = default;
};

// Strict grammar scan of this repo's FLAC3D writer output (streaming
// semantics preserved: line numbers from 1, universal newlines, UTF-8 with
// U+FFFD replacement for invalid bytes — Python errors="replace").
MeshFacts parse_flac3d_text(std::string_view utf8_text);
MeshFacts parse_abaqus_text(std::string_view utf8_text);
MeshFacts parse_flac3d(const std::filesystem::path& path);
MeshFacts parse_abaqus(const std::filesystem::path& path);

// Shared behaviour for the FLAC3D / Abaqus structured-hex writers
// (registry.FormatAdapter narrow surface + the model half).
class ModelAdapter {
public:
    std::string format_id;
    std::string display_name;
    std::vector<std::string> extensions;

    ModelAdapter(std::string id, std::string name, std::vector<std::string> exts)
        : format_id(std::move(id)), display_name(std::move(name)),
          extensions(std::move(exts)) {}
    virtual ~ModelAdapter() = default;

    virtual FormatCapability capability() const = 0;
    virtual MeshFacts parse(const std::filesystem::path& path) const = 0;

    // Structured inspect (model_adapter._StructuredModelAdapter.inspect).
    InspectionResult inspect(const std::filesystem::path& path) const;

    // registry.FormatAdapter.plan_import default + the model override
    // (action forced to "unsupported", honest warning appended).
    ImportPlan plan_import(const std::filesystem::path& path,
                           const InspectionResult& inspection, bool managed = true,
                           const std::optional<std::string>& asset_name = std::nullopt,
                           Json options = Json::object()) const;

    // Always throws FormatNotSupportedError("...: 模型网格无导入路径（仅导出）").
    [[noreturn]] void import_data() const;

    ExportPlan plan_export(const std::filesystem::path& source_path,
                           const std::filesystem::path& target_path,
                           Json options = Json::object()) const;

    // Writes through AtomicOutputFile using the CONV-22 geomodel writer
    // bytes; returns the target path.
    std::filesystem::path export_data(const ExportPlan& plan,
                                      const CancelToken& cancel = null_cancel(),
                                      ProgressCallback progress = {}) const;

    ExportVerification verify_output(const std::filesystem::path& target_path,
                                     const ExportPlan& plan) const;

protected:
    // The CONV-22 geomodel writer producing the exact Python bytes.
    virtual std::string write_grid(int nx, int ny, int nz, double dx, double dy,
                                   double dz) const = 0;
};

class Flac3dAdapter final : public ModelAdapter {
public:
    Flac3dAdapter()
        : ModelAdapter("flac3d_f3grid", "FLAC3D 角点网格", {"f3grid"}) {}
    FormatCapability capability() const override;
    MeshFacts parse(const std::filesystem::path& path) const override;

protected:
    std::string write_grid(int nx, int ny, int nz, double dx, double dy,
                           double dz) const override;
};

class AbaqusAdapter final : public ModelAdapter {
public:
    AbaqusAdapter()
        : ModelAdapter("abaqus_inp", "Abaqus 有限元网格", {"inp"}) {}
    FormatCapability capability() const override;
    MeshFacts parse(const std::filesystem::path& path) const override;

protected:
    std::string write_grid(int nx, int ny, int nz, double dx, double dy,
                           double dz) const override;
};

// registry.InterchangeRegistry mirror for model adapters: register / get /
// adapters / adapter_for_extension / capability_matrix (insertion order kept,
// extension lookup takes the FIRST match).
class ModelAdapterRegistry {
public:
    void register_adapter(std::shared_ptr<ModelAdapter> adapter, bool replace = false);
    const ModelAdapter* get(const std::string& format_id) const;
    const std::vector<std::shared_ptr<ModelAdapter>>& adapters() const { return adapters_; }
    const ModelAdapter* adapter_for_extension(const std::string& extension) const;
    Json capability_matrix() const;  // registry.py capability_matrix rows

private:
    std::vector<std::shared_ptr<ModelAdapter>> adapters_;
};

// Registry with every built-in model adapter registered (flac3d, abaqus).
ModelAdapterRegistry build_model_adapter_registry();

}  // namespace pwb::interchange
