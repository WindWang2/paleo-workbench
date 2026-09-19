// Static builtin factory table (Python BUILTIN_PROVIDER_FACTORIES
// counterpart). Each factory individually guarded at the registration site
// so one unavailable engine never blocks the others.
#include <pwb/providers/builtin.hpp>

namespace pwb::providers {

std::vector<std::unique_ptr<IProvider>> make_builtin_factor_stats() {
    std::vector<std::unique_ptr<IProvider>> made;
    made.push_back(std::make_unique<FactorStatsProvider>());
    return made;
}

std::vector<std::unique_ptr<IProvider>> make_builtin_map_thumbnail() {
    std::vector<std::unique_ptr<IProvider>> made;
    made.push_back(std::make_unique<MapThumbnailProvider>());
    return made;
}

std::vector<std::function<std::vector<std::unique_ptr<IProvider>>()>>&
builtin_provider_factories() {
    static std::vector<std::function<std::vector<std::unique_ptr<IProvider>>()>>
        factories = {make_builtin_factor_stats, make_builtin_map_thumbnail};
    return factories;
}

}  // namespace pwb::providers
