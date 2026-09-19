#include <pwb/providers/registry.hpp>

#include <pwb/providers/builtin.hpp>
#include <pwb/providers/errors.hpp>

#include <algorithm>

namespace pwb::providers {

namespace {
}  // namespace

ProviderDescriptor ProviderRegistry::register_provider(std::unique_ptr<IProvider> provider,
                                                       bool replace) {
    if (provider == nullptr) {
        throw InvalidProviderError("", {"provider has no descriptor attribute"});
    }
    ProviderDescriptor descriptor = provider->descriptor();
    auto problems = validate_descriptor(descriptor);
    if (!problems.empty()) {
        std::string reason = "invalid descriptor: ";
        for (std::size_t i = 0; i < problems.size(); ++i) {
            if (i != 0) reason += "; ";
            reason += problems[i];
        }
        {
            std::lock_guard<std::mutex> lock(mutex_);
            quarantine_[descriptor.provider_id] = reason;
        }
        throw InvalidProviderError(descriptor.provider_id, std::move(problems));
    }

    std::lock_guard<std::mutex> lock(mutex_);
    auto it = std::find_if(order_.begin(), order_.end(),
                           [&](const auto& entry) {
                               return entry.first == descriptor.provider_id;
                           });
    if (it != order_.end() && !replace) {
        const std::string existing_version = it->second->descriptor().version;
        if (existing_version != descriptor.version) {
            quarantine_[descriptor.provider_id] =
                "version conflict " + descriptor.version + " vs registered " +
                existing_version;
        }
        throw DuplicateProviderError(descriptor.provider_id, existing_version);
    }
    if (it != order_.end()) {
        it->second = std::move(provider);
    } else {
        order_.emplace_back(descriptor.provider_id, std::move(provider));
    }
    quarantine_.erase(descriptor.provider_id);
    return descriptor;
}

bool ProviderRegistry::unregister(const std::string& provider_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = std::find_if(order_.begin(), order_.end(),
                           [&](const auto& entry) { return entry.first == provider_id; });
    if (it == order_.end()) return false;
    order_.erase(it);
    return true;
}

IProvider& ProviderRegistry::get(const std::string& provider_id) const {
    IProvider* provider = find(provider_id);
    if (provider == nullptr) {
        throw UnknownProviderError(provider_id);
    }
    return *provider;
}

IProvider* ProviderRegistry::find(const std::string& provider_id) const {
    std::lock_guard<std::mutex> lock(mutex_);
    for (const auto& [id, provider] : order_) {
        if (id == provider_id) return provider.get();
    }
    return nullptr;
}

std::vector<IProvider*> ProviderRegistry::by_family(ProviderFamily family) const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<IProvider*> out;
    for (const auto& [id, provider] : order_) {
        if (provider->descriptor().family == family) out.push_back(provider.get());
    }
    return out;
}

std::vector<ProviderDescriptor> ProviderRegistry::descriptors(
    std::optional<ProviderFamily> family) const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<ProviderDescriptor> out;
    for (const auto& [id, provider] : order_) {
        if (family.has_value() && provider->descriptor().family != *family) continue;
        out.push_back(provider->descriptor());
    }
    std::sort(out.begin(), out.end(),
              [](const ProviderDescriptor& a, const ProviderDescriptor& b) {
                  const std::string fa = to_string(a.family);
                  const std::string fb = to_string(b.family);
                  if (fa != fb) return fa < fb;
                  return a.provider_id < b.provider_id;
              });
    return out;
}

std::size_t ProviderRegistry::size() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return order_.size();
}

std::map<std::string, std::string> ProviderRegistry::quarantined() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return quarantine_;
}

std::vector<std::string> register_builtin_providers(ProviderRegistry& registry) {
    std::vector<std::string> registered;
    for (const auto& factory : builtin_provider_factories()) {
        std::vector<std::unique_ptr<IProvider>> made;
        try {
            made = factory();
        } catch (...) {
            continue;  // one unavailable engine never blocks the others
        }
        for (auto& provider : made) {
            if (provider == nullptr) continue;
            try {
                ProviderDescriptor descriptor = registry.register_provider(std::move(provider), true);
                registered.push_back(descriptor.provider_id);
            } catch (...) {
                // Registration failure is quarantined inside the registry;
                // builtins keep booting.
            }
        }
    }
    return registered;
}

ProviderRegistry& get_provider_registry() {
    // Heap-held: ProviderRegistry is mutex-guarded and therefore non-movable.
    static const std::unique_ptr<ProviderRegistry> registry = [] {
        auto seeded = std::make_unique<ProviderRegistry>();
        register_builtin_providers(*seeded);
        return seeded;
    }();
    return *registry;
}

}  // namespace pwb::providers
