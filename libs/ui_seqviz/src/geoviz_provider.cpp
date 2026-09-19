#include <pwb/ui_seqviz/geoviz_provider.hpp>

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <utility>

#include <pwb/ui_data_core/json_util.hpp>
#include <pwb/ui_data_core/preview_cache.hpp>

namespace pwb::ui_seqviz {

namespace {

namespace fs = std::filesystem;

std::string lower_ascii(std::string text) {
    std::transform(text.begin(), text.end(), text.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return text;
}

std::string format_lower(const ResourceItem& resource) {
    // resource.format mirrors Python's format extraction (suffix w/o dot).
    return lower_ascii(resource.format);
}

std::string abs_path(const std::string& path) {
    if (path.empty()) {
        return {};
    }
    std::error_code ec;
    const fs::path resolved = fs::absolute(fs::path(path), ec);
    return ec ? path : resolved.lexically_normal().string();
}

}  // namespace

// ---------------------------------------------------------------------------
// PreviewRequestData
// ---------------------------------------------------------------------------

std::string PreviewRequestData::normalized_format() const {
    std::string out = lower_ascii(format);
    while (!out.empty() && out.front() == '.') {
        out.erase(out.begin());
    }
    if (!out.empty()) {
        return out;
    }
    return lower_ascii(fs::path(path).extension().string());
}

// ---------------------------------------------------------------------------
// request_from_resource (viz/preview_request.py)
// ---------------------------------------------------------------------------

PreviewRequestData request_from_resource(
    const ResourceItem& resource, std::optional<std::string> path,
    std::optional<std::string> semantic_type, std::optional<std::string> label,
    std::optional<std::string> comparison_crs) {
    const std::string resolved_path = abs_path(path.value_or(resource.path));
    std::vector<std::string> version_parts{resource.checksum.value_or("")};
    if (const auto stat = ui_data_core::safe_file_stat(resolved_path);
        stat.has_value()) {
        version_parts.push_back(std::to_string(stat->first));
        version_parts.push_back(std::to_string(stat->second));
    }
    std::string joined;
    for (std::size_t i = 0; i < version_parts.size(); ++i) {
        if (i != 0U) {
            joined += ':';
        }
        joined += version_parts[i];
    }
    // metadata = resource.parsed_summary() — parsed dict or {}.
    const domain::Json metadata = resource.parsed_summary.is_object()
                                      ? resource.parsed_summary
                                      : domain::Json::object();
    const auto meta_text = [&metadata](const char* key) -> std::string {
        return ui_data_core::json_get_string(metadata, key);
    };
    PreviewRequestData request;
    request.resource_id =
        !resource.id.empty() ? resource.id : resolved_path;
    request.path = resolved_path;
    request.semantic_type = semantic_type.value_or(resource.type);
    request.format = resource.format.empty()
                         ? fs::path(resolved_path).extension().string()
                         : resource.format;
    request.label = label.value_or(resource.name);
    request.source_version = joined;
    request.source_crs = meta_text("source_crs");
    request.coordinate_units = meta_text("coordinate_units");
    request.comparison_crs = comparison_crs.value_or("");
    return request;
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

std::string merge_preview_warning(const std::string& existing,
                                  const std::string& engine_message) {
    std::string merged = existing;
    if (!engine_message.empty()) {
        if (!merged.empty()) {
            merged += " · ";
        }
        merged += engine_message;
    }
    return merged;
}

PreviewResult engine_preview_result(const ResourceItem& asset,
                                    const PreparedPreviewData& prepared) {
    PreviewResult result;
    result.mode = ui_data_core::preview_mode::kGeoviz;
    result.title = asset.name;
    result.path = asset.path;
    result.format = asset.format;
    result.status = asset.status;
    result.type_label = asset.type;
    result.warning = prepared.warning;
    result.summary_rows = prepared.summary_rows;
    result.engine_preview = prepared.payload;
    result.estimated_bytes = prepared.estimated_bytes;
    result.visualization_available = true;
    return result;
}

bool is_seismic_asset(const ResourceItem& resource) {
    const std::string fmt = format_lower(resource);
    return fmt == "sgy" || fmt == "segy" || resource.type == "seismic";
}

// ---------------------------------------------------------------------------
// LocalVizProvider
// ---------------------------------------------------------------------------

struct LocalVizProvider::Impl {
    ui_data_core::PreviewProvider base;  // super() parity
    PreviewSettings settings;
    std::shared_ptr<GeoVizEngineApi> engine;
    std::string comparison_crs;

    PreviewResult build(const AssetObjectData& asset,
                        const PreviewSettings& active_settings) const {
        if (const ResourceItem* resource =
                std::get_if<ResourceItem>(&asset)) {
            if (!is_seismic_asset(*resource)) {
                const PreviewRequestData request = request_from_resource(
                    *resource, std::nullopt, std::nullopt, std::nullopt,
                    comparison_crs.empty()
                        ? std::nullopt
                        : std::optional<std::string>(comparison_crs));
                // supports() outside try — mirrors Python (propagates).
                if (engine != nullptr && engine->supports(request)) {
                    try {
                        const PreparedPreviewData prepared = engine->prepare(
                            request, active_settings.to_geoviz_options());
                        return engine_preview_result(*resource, prepared);
                    } catch (const GeoVizError& error) {
                        PreviewResult fallback = base.preview(&asset);
                        fallback.warning = merge_preview_warning(
                            fallback.warning, error.detail_or_message());
                        return fallback;
                    }
                }
            }
        }
        return base.preview(&asset);
    }

    PreviewResult summary(const AssetObjectData* asset,
                          const PreviewSettings& active_settings) const {
        (void)active_settings;
        if (asset == nullptr) {
            return base.preview(nullptr);
        }
        PreviewResult result = base.preview(asset);
        const ResourceItem* resource = std::get_if<ResourceItem>(asset);
        if (resource == nullptr || result.status == "missing") {
            return result;
        }
        if (is_seismic_asset(*resource)) {
            return result;
        }
        const PreviewRequestData request = request_from_resource(
            *resource, std::nullopt, std::nullopt, std::nullopt,
            comparison_crs.empty()
                ? std::nullopt
                : std::optional<std::string>(comparison_crs));
        bool available = false;
        try {
            available = engine != nullptr && engine->supports(request);
        } catch (const GeoVizError& error) {
            result.warning =
                merge_preview_warning(result.warning, error.what());
            return result;
        }
        result.visualization_available = available;
        return result;
    }

    PreviewResult visualization(const AssetObjectData* asset,
                                const PreviewSettings& active_settings) const {
        const ResourceItem* resource =
            asset == nullptr ? nullptr : std::get_if<ResourceItem>(asset);
        if (resource == nullptr) {
            return base.preview_visualization(asset);
        }
        if (is_seismic_asset(*resource)) {
            return base.preview_visualization(asset);
        }
        const PreviewRequestData request = request_from_resource(
            *resource, std::nullopt, std::nullopt, std::nullopt,
            comparison_crs.empty()
                ? std::nullopt
                : std::optional<std::string>(comparison_crs));
        try {
            const PreparedPreviewData prepared =
                engine == nullptr
                    ? throw_engine_missing(request)
                    : engine->prepare(request,
                                      active_settings.to_geoviz_options());
            return engine_preview_result(*resource, prepared);
        } catch (const GeoVizError& error) {
            PreviewResult fallback = base.preview_visualization(asset);
            if (error.code() == GeoVizErrorCode::Unsupported) {
                return fallback;
            }
            const std::string text = error.detail_or_message();
            fallback.message = text;
            fallback.warning = text;
            fallback.cacheable = false;
            fallback.retryable = error.code() == GeoVizErrorCode::IoError ||
                                 error.code() == GeoVizErrorCode::RenderError;
            return fallback;
        }
    }

    // No engine configured → behave as GeoVizError(UNSUPPORTED): the honest
    // "unsupported" fallback branch (never fabricate a preview).
    [[noreturn]] static PreparedPreviewData throw_engine_missing(
        const PreviewRequestData& request) {
        throw GeoVizError(
            GeoVizErrorCode::Unsupported,
            "引擎不支持此资源类型: " + request.semantic_type + "/" +
                request.normalized_format());
    }
};

LocalVizProvider::LocalVizProvider(BuildFn base_builder,
                                   PreviewSettings settings,
                                   std::shared_ptr<GeoVizEngineApi> engine,
                                   std::string comparison_crs)
    : impl_(std::make_shared<Impl>(Impl{
          ui_data_core::PreviewProvider(std::move(base_builder), settings),
          std::move(settings), std::move(engine),
          std::move(comparison_crs)})) {}

void LocalVizProvider::set_comparison_crs(std::string crs) {
    impl_->comparison_crs = std::move(crs);
}

const std::string& LocalVizProvider::comparison_crs() const {
    return impl_->comparison_crs;
}

const PreviewSettings& LocalVizProvider::settings() const {
    return impl_->settings;
}

void LocalVizProvider::set_engine(std::shared_ptr<GeoVizEngineApi> engine) {
    impl_->engine = std::move(engine);
}

std::shared_ptr<GeoVizEngineApi> LocalVizProvider::engine() const {
    return impl_->engine;
}

LocalVizProvider LocalVizProvider::with_settings(
    const PreviewSettings& settings) const {
    // copy.copy parity — share engine + comparison_crs, reconfigure the
    // base provider and impl settings (the base builder flows through).
    LocalVizProvider copy(BuildFn{}, settings, impl_->engine,
                          impl_->comparison_crs);
    copy.impl_->base = impl_->base.with_settings(settings);
    copy.impl_->settings = settings;
    return copy;
}

PreviewResult LocalVizProvider::preview(
    const AssetObjectData* asset) const {
    if (asset == nullptr) {
        return impl_->base.preview(nullptr);
    }
    return impl_->build(*asset, impl_->settings);
}

PreviewResult LocalVizProvider::preview_summary(
    const AssetObjectData* asset) const {
    return impl_->summary(asset, impl_->settings);
}

PreviewResult LocalVizProvider::preview_visualization(
    const AssetObjectData* asset) const {
    return impl_->visualization(asset, impl_->settings);
}

ui_data_core::PreviewProvider LocalVizProvider::request_provider() const {
    auto impl = impl_;
    ui_data_core::PreviewProvider provider(
        [impl](const AssetObjectData& asset, const PreviewSettings& s) {
            return impl->build(asset, s);
        },
        impl_->settings);
    provider.set_summary_hook(
        [impl](const AssetObjectData* asset, const PreviewSettings& s) {
            return impl->summary(asset, s);
        });
    provider.set_visualization_hook(
        [impl](const AssetObjectData* asset, const PreviewSettings& s) {
            return impl->visualization(asset, s);
        });
    return provider;
}

}  // namespace pwb::ui_seqviz
