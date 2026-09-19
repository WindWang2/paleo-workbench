// preview_provider.py port — thin dispatcher over the parser-registry seam.
//
// Python delegates to ``default_registry().build_preview(asset, settings)``;
// here the registry is an injected BuildFn so the Qt-free core never reaches
// into the parser package. ``with_settings`` mirrors ``copy.copy(self)`` —
// the snapshot shares the engine.
#pragma once

#include "pwb/ui_data_core/asset_view.hpp"
#include "pwb/ui_data_core/preview_types.hpp"

#include <functional>

namespace pwb::ui_data_core {

// The "please select an item" empty result (provider.preview(None)).
PreviewResult empty_preview_result();

class PreviewProvider {
public:
    // default_registry().build_preview(asset, settings) — injected seam.
    using BuildFn = std::function<PreviewResult(
        const AssetObjectData& asset, const PreviewSettings& settings)>;

    explicit PreviewProvider(
        BuildFn builder,
        PreviewSettings settings = PreviewSettings::defaults());

    // with_settings: request-local provider snapshot sharing the engine.
    PreviewProvider with_settings(const PreviewSettings& settings) const {
        PreviewProvider copy = *this;
        copy.settings_ = settings;
        return copy;
    }

    const PreviewSettings& settings() const { return settings_; }

    // Optional per-kind overrides (UI-10 LocalVisualizationProvider parity:
    // Python subclasses PreviewProvider and overrides preview_summary /
    // preview_visualization — the hooks carry the provider's CURRENT
    // settings so a with_settings copy never calls back into stale state).
    using SummaryFn = std::function<PreviewResult(
        const AssetObjectData* asset, const PreviewSettings& settings)>;
    using VisualizationFn = std::function<PreviewResult(
        const AssetObjectData* asset, const PreviewSettings& settings)>;
    void set_summary_hook(SummaryFn hook) { summary_fn_ = std::move(hook); }
    void set_visualization_hook(VisualizationFn hook) {
        visualization_fn_ = std::move(hook);
    }

    // asset == nullptr → the empty result (Python preview(None)).
    PreviewResult preview(const AssetObjectData* asset) const;
    // preview_summary — the lightweight reader payload (== preview today).
    PreviewResult preview_summary(const AssetObjectData* asset) const;
    // preview_visualization — stable "unsupported" message result when no
    // professional backend is available.
    PreviewResult preview_visualization(const AssetObjectData* asset) const;

private:
    BuildFn builder_;
    PreviewSettings settings_;
    SummaryFn summary_fn_;
    VisualizationFn visualization_fn_;
};

}  // namespace pwb::ui_data_core
