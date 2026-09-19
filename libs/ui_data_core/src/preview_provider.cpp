#include "pwb/ui_data_core/preview_provider.hpp"

#include "pwb/ui_data_core/json_util.hpp"

#include <stdexcept>
#include <utility>

namespace pwb::ui_data_core {

PreviewResult empty_preview_result() {
    PreviewResult result;
    result.mode = preview_mode::kEmpty;
    result.title = "请选择数据项";
    result.message = "从列表中选择一个数据、成果或文件";
    return result;
}

PreviewProvider::PreviewProvider(BuildFn builder, PreviewSettings settings)
    : builder_(std::move(builder)), settings_(std::move(settings)) {}

PreviewResult PreviewProvider::preview(const AssetObjectData* asset) const {
    if (asset == nullptr) {
        return empty_preview_result();
    }
    // _build_preview → default_registry().build_preview(asset, settings).
    return builder_(*asset, settings_);
}

PreviewResult PreviewProvider::preview_summary(
    const AssetObjectData* asset) const {
    return preview(asset);
}

PreviewResult PreviewProvider::preview_visualization(
    const AssetObjectData* asset) const {
    if (asset == nullptr) {
        return preview(nullptr);
    }
    PreviewResult result;
    result.mode = preview_mode::kMessage;
    result.message = "此数据不支持可视化预览";
    if (const auto* resource = std::get_if<ResourceItem>(asset)) {
        result.title = resource->name;
        result.path = resource->path;
        result.format = resource->format;
        result.status = resource->status;
        result.type_label = resource->type;
        return result;
    }
    if (const auto* artifact = std::get_if<ExportArtifact>(asset)) {
        // Path(output_path).name or output_path — a bare-name fallback.
        const std::string name = python_path_name(artifact->output_path);
        result.title = name.empty() ? artifact->output_path : name;
        result.path = artifact->output_path;
        result.format = artifact->format;
        result.status = "generated";
        result.type_label = "成果";
        return result;
    }
    // The Python type contract admits only ResourceItem | ExportArtifact;
    // any other variant mirrors the AttributeError branch.
    throw std::invalid_argument(
        "preview_visualization: unsupported asset variant");
}

}  // namespace pwb::ui_data_core
