#include "pwb/interchange/service.hpp"

#include <stdexcept>

namespace pwb::interchange {

NativeInterchangeService::NativeInterchangeService() {
    registry_ = build_model_adapter_registry();
}

Json NativeInterchangeService::capability_matrix() const {
    return registry_.capability_matrix();
}

const ModelAdapter* NativeInterchangeService::adapter(const std::string& format_id) const {
    return registry_.get(format_id);
}

const ModelAdapter* NativeInterchangeService::adapter_for_extension(
    const std::string& extension) const {
    return registry_.adapter_for_extension(extension);
}

InspectionResult NativeInterchangeService::inspect(
    const std::string& format_id, const std::filesystem::path& path) const {
    const ModelAdapter* resolved = registry_.get(format_id);
    if (resolved == nullptr) {
        throw FormatNotSupportedError("no adapter for format: " + format_id);
    }
    return resolved->inspect(path);
}

ImportPlan NativeInterchangeService::plan_import(
    const std::string& format_id, const std::filesystem::path& path,
    const InspectionResult& inspection, bool managed,
    const std::optional<std::string>& asset_name, Json options) const {
    const ModelAdapter* resolved = registry_.get(format_id);
    if (resolved == nullptr) {
        throw FormatNotSupportedError("no adapter for format: " + format_id);
    }
    return resolved->plan_import(path, inspection, managed, asset_name,
                                 std::move(options));
}

ExportPlan NativeInterchangeService::plan_export(const std::string& format_id,
                                                 const std::filesystem::path& source_path,
                                                 const std::filesystem::path& target_path,
                                                 Json options) const {
    const ModelAdapter* resolved = registry_.get(format_id);
    if (resolved == nullptr) {
        throw FormatNotSupportedError("no adapter for format: " + format_id);
    }
    return resolved->plan_export(source_path, target_path, std::move(options));
}

std::filesystem::path NativeInterchangeService::export_data(const ExportPlan& plan,
                                                            const CancelToken& cancel,
                                                            ProgressCallback progress) const {
    const ModelAdapter* resolved = registry_.get(plan.format_id);
    if (resolved == nullptr) {
        throw FormatNotSupportedError("no adapter for format: " + plan.format_id);
    }
    return resolved->export_data(plan, cancel, std::move(progress));
}

ExportVerification NativeInterchangeService::verify_output(
    const std::filesystem::path& target_path, const ExportPlan& plan) const {
    const ModelAdapter* resolved = registry_.get(plan.format_id);
    if (resolved == nullptr) {
        throw FormatNotSupportedError("no adapter for format: " + plan.format_id);
    }
    return resolved->verify_output(target_path, plan);
}

}  // namespace pwb::interchange
