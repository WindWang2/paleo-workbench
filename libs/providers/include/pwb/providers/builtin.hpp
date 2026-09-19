// Built-in production providers — the C++ counterparts of the Python
// built-ins and example plugins that the product actually invokes today:
//
// - geology.factor_stats   (port of examples/provider_plugins/geology_factor_stats.py)
// - export.map_thumbnail   (port of examples/provider_plugins/export_map_thumbnail.py)
//
// The heavier Python built-ins (interpolation.kriging/.idw, seismic
// attribute kernels, tiled ONNX inference, QGIS-preferred export.map_product
// and the viz render backends) stay on the Python side until their engine
// closures land; see docs/development/cpp-providers/.
#pragma once

#include <pwb/providers/registry.hpp>

#include <functional>
#include <memory>
#include <vector>

namespace pwb::providers {

// INTERPOLATION-adjacent compute: factor dataset summary statistics
// (count/finite/min/max/mean/stdev) with a fail-closed verify hook.
class FactorStatsProvider : public IProvider {
public:
    FactorStatsProvider();
    const ProviderDescriptor& descriptor() const override { return descriptor_; }
    ProviderResult execute(const ProviderInputs& inputs, const Json& parameters,
                           ProviderContext& context) override;
    std::optional<Verification> verify(const ProviderResult& result,
                                       ProviderContext& context) override;

private:
    ProviderDescriptor descriptor_;
};

// EXPORTER: MapDocument → workspace-contained PNG thumbnail rendered by the
// native software rasterizer, with PNG-signature verification.
class MapThumbnailProvider : public IProvider {
public:
    MapThumbnailProvider();
    const ProviderDescriptor& descriptor() const override { return descriptor_; }
    ProviderResult execute(const ProviderInputs& inputs, const Json& parameters,
                           ProviderContext& context) override;
    std::optional<Verification> verify(const ProviderResult& result,
                                       ProviderContext& context) override;

private:
    ProviderDescriptor descriptor_;
};

// The static factory table replacing Python's BUILTIN_PROVIDER_FACTORIES.
std::vector<std::unique_ptr<IProvider>> make_builtin_factor_stats();
std::vector<std::unique_ptr<IProvider>> make_builtin_map_thumbnail();
std::vector<std::function<std::vector<std::unique_ptr<IProvider>>()>>&
builtin_provider_factories();

}  // namespace pwb::providers
