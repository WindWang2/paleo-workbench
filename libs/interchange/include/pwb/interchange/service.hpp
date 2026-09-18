#pragma once

// pwb::interchange — native import/export service (conv-14b): the C++
// entry point that composes the interchange adapter kernels so the
// Qt/platform layer never touches the Python runtime for these flows.
//
// Scope parity note: the Python service layer (executor.py / batch.py /
// delivery.py) stays the Qt/catalog-backed orchestrator; this facade exposes
// the adapter half — capability discovery, structured inspect, export
// planning/execution/verification for the model formats. The portable
// package runtime (build/verify/materialize/open) is exposed directly by
// package_runtime.hpp's free functions and is equally Python-free.

#include <pwb/interchange/contracts.hpp>
#include <pwb/interchange/model_adapters.hpp>
#include <pwb/interchange/package_runtime.hpp>
#include <pwb/interchange/preflight.hpp>

#include <filesystem>
#include <memory>
#include <string>
#include <vector>

namespace pwb::interchange {

// Native import/export service over the registered model adapters.
class NativeInterchangeService {
public:
    NativeInterchangeService();

    // registry.capability_matrix() rows (JSON, insertion order).
    Json capability_matrix() const;

    const ModelAdapter* adapter(const std::string& format_id) const;
    const ModelAdapter* adapter_for_extension(const std::string& extension) const;

    // Structured inspect through the adapter (never writes).
    InspectionResult inspect(const std::string& format_id,
                             const std::filesystem::path& path) const;

    ImportPlan plan_import(const std::string& format_id,
                           const std::filesystem::path& path,
                           const InspectionResult& inspection, bool managed = true,
                           const std::optional<std::string>& asset_name = std::nullopt,
                           Json options = Json::object()) const;

    ExportPlan plan_export(const std::string& format_id,
                           const std::filesystem::path& source_path,
                           const std::filesystem::path& target_path,
                           Json options = Json::object()) const;

    std::filesystem::path export_data(const ExportPlan& plan,
                                      const CancelToken& cancel = null_cancel(),
                                      ProgressCallback progress = {}) const;

    ExportVerification verify_output(const std::filesystem::path& target_path,
                                     const ExportPlan& plan) const;

private:
    ModelAdapterRegistry registry_;
};

}  // namespace pwb::interchange
