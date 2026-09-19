#pragma once

// UI-10 — geoviz_preview_provider.py port + the geoviz contract types the
// provider and the engine-preview resolve path share.
//
// LocalVisualizationProvider wraps a GeoVizEngine behind preview-provider
// semantics: non-seismic resources get a canonical PreviewRequest, the
// engine is probed (supports / prepare), GeoVizError failures degrade to
// the base preview with merged warnings (never a fake success), and
// seismic assets always take the base path. The engine stays an injected
// seam (GeoVizEngineApi) — this library ships no renderer.

#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <pwb/ui_data_core/asset_view.hpp>
#include <pwb/ui_data_core/preview_provider.hpp>
#include <pwb/ui_data_core/preview_types.hpp>

namespace pwb::ui_seqviz {

using ui_data_core::AssetObjectData;
using ui_data_core::GeovizPreviewOptions;
using ui_data_core::PreviewResult;
using ui_data_core::PreviewSettings;
using ui_data_core::ResourceItem;

// ---------------------------------------------------------------------------
// geoviz/contracts.py — PreviewRequest / PreparedPreview value types
// ---------------------------------------------------------------------------

// Canonical versioned engine request (geoviz PreviewRequest).
struct PreviewRequestData {
    std::string resource_id;
    std::string path;
    std::string semantic_type;
    std::string format;
    std::string label;
    std::string source_version;
    std::string source_crs;
    std::string coordinate_units;
    std::string comparison_crs;

    // normalized_format: lower/lstrip(".") format else path suffix.
    std::string normalized_format() const;
};

// geoviz PreparedPreview — the portable fields the UI consumes; `payload`
// stays an opaque engine handle (never inspected by this layer).
struct PreparedPreviewData {
    std::string kind;
    std::string title;
    std::shared_ptr<void> payload;
    std::vector<std::pair<std::string, std::string>> summary_rows;
    std::string warning;
    long long estimated_bytes = 0;
};

// viz/preview_request.py request_from_resource — canonical request build:
// checksum + (size, mtime_ns) stat version parts, parsed_summary metadata
// for units/crs fallbacks.
PreviewRequestData request_from_resource(
    const ResourceItem& resource,
    std::optional<std::string> path = std::nullopt,
    std::optional<std::string> semantic_type = std::nullopt,
    std::optional<std::string> label = std::nullopt,
    std::optional<std::string> comparison_crs = std::nullopt);

// ---------------------------------------------------------------------------
// geoviz/errors.py — GeoVizError + ErrorCode
// ---------------------------------------------------------------------------

enum class GeoVizErrorCode {
    Unsupported,
    InvalidData,
    DependencyMissing,
    IoError,
    ResourceLimit,
    RenderError,
};

// GeoVizError(RuntimeError): code + message + detail. what() is the message
// (str(exc) parity); detail_or_message() mirrors `_error_text`.
struct GeoVizError : std::runtime_error {
    GeoVizError(GeoVizErrorCode code, std::string message,
                std::string detail = "")
        : std::runtime_error(message),
          code_(code),
          detail_(std::move(detail)) {}
    [[nodiscard]] GeoVizErrorCode code() const noexcept { return code_; }
    [[nodiscard]] const std::string& detail() const noexcept {
        return detail_;
    }
    // _error_text: error.detail or str(error).
    [[nodiscard]] std::string detail_or_message() const {
        return detail_.empty() ? what() : detail_;
    }

private:
    GeoVizErrorCode code_;
    std::string detail_;
};

// ---------------------------------------------------------------------------
// The engine seam — GeoVizEngine (supports / prepare)
// ---------------------------------------------------------------------------

class GeoVizEngineApi {
public:
    virtual ~GeoVizEngineApi() = default;
    // geoviz GeoVizEngine.supports — may throw GeoVizError.
    virtual bool supports(const PreviewRequestData& request) = 0;
    // geoviz GeoVizEngine.prepare — may throw GeoVizError.
    virtual PreparedPreviewData prepare(
        const PreviewRequestData& request,
        const GeovizPreviewOptions& options) = 0;
};

// ---------------------------------------------------------------------------
// LocalVisualizationProvider (geoviz_preview_provider.py)
// ---------------------------------------------------------------------------

// Wraps the base preview builder + engine. `base_builder` is the Python
// ``super()._build_preview`` seam (the parser-registry preview); the engine
// is optional — absent = "不支持" behavior on every request (the honest
// fallback Python reaches only via GeoVizError(UNSUPPORTED)).
class LocalVizProvider {
public:
    // super()._build_preview — the default registry build seam.
    using BuildFn = ui_data_core::PreviewProvider::BuildFn;

    explicit LocalVizProvider(
        BuildFn base_builder,
        PreviewSettings settings = PreviewSettings::defaults(),
        std::shared_ptr<GeoVizEngineApi> engine = {},
        std::string comparison_crs = "");

    // Python attribute surface (page writes provider.comparison_crs).
    void set_comparison_crs(std::string crs);
    const std::string& comparison_crs() const;
    const PreviewSettings& settings() const;
    void set_engine(std::shared_ptr<GeoVizEngineApi> engine);
    std::shared_ptr<GeoVizEngineApi> engine() const;

    // with_settings — copy.copy parity: the snapshot shares the engine and
    // the comparison_crs; only settings differ.
    LocalVizProvider with_settings(const PreviewSettings& settings) const;

    // PreviewProvider surface:
    PreviewResult preview(const AssetObjectData* asset) const;
    PreviewResult preview_summary(const AssetObjectData* asset) const;
    PreviewResult preview_visualization(const AssetObjectData* asset) const;

    // Produce a PreviewProvider configured so PreviewRequestCore's
    // kind dispatch (preview / preview_summary / preview_visualization)
    // reaches THIS provider — the engine-aware preview for the
    // visualization page's request_kind="visualization" controller.
    ui_data_core::PreviewProvider request_provider() const;

private:
    struct Impl;
    std::shared_ptr<Impl> impl_;
};

// ---------------------------------------------------------------------------
// Shared text helpers (verbatim statics)
// ---------------------------------------------------------------------------

// _merge_warning: " · ".join of the non-empty parts.
std::string merge_preview_warning(const std::string& existing,
                                  const std::string& engine_message);

// _engine_result: the geoviz-mode PreviewResult for a prepared asset.
PreviewResult engine_preview_result(const ResourceItem& asset,
                                    const PreparedPreviewData& prepared);

// The seismic shortcut check (format in {"sgy","segy"} or type=="seismic").
bool is_seismic_asset(const ResourceItem& resource);

}  // namespace pwb::ui_seqviz
