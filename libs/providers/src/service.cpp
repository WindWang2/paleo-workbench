#include <pwb/providers/service.hpp>

#include <stdexcept>

namespace pwb::providers {

ProviderService::ProviderService() { register_builtin_providers(registry_); }

Json ProviderService::capability_report(std::optional<std::string> family) const {
    std::optional<ProviderFamily> parsed;
    if (family.has_value()) {
        parsed = family_from_string(*family);
        if (!parsed.has_value()) {
            throw std::invalid_argument("unknown provider family: " + *family);
        }
    }
    Json report = Json::array();
    for (const auto& descriptor : registry_.descriptors(parsed)) {
        report.push_back(descriptor.to_json());
    }
    return report;
}

Json ProviderService::quarantine_report() const {
    Json report = Json::object();
    for (const auto& [id, reason] : registry_.quarantined()) {
        report[id] = reason;
    }
    return report;
}

}  // namespace pwb::providers
