// providers.registry — registration semantics: explicit install, duplicate
// protection (same-version vs version-conflict quarantine), replace, sorted
// descriptors, family queries, quarantine isolation, unregister, unknown id,
// and the builtin-seeded singleton.

#include <cstdio>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/providers/builtin.hpp>
#include <pwb/providers/errors.hpp>
#include <pwb/providers/registry.hpp>

using pwb::domain::Json;
namespace pp = pwb::providers;

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

template <typename Fn>
std::string expect_throw(Fn&& fn) {
    try {
        fn();
    } catch (const std::exception& exc) {
        return exc.what();
    }
    return "<no throw>";
}

// Minimal echo provider standing in for a real extension.
class EchoProvider : public pp::IProvider {
public:
    EchoProvider(std::string id, std::string version = "1.0.0") {
        descriptor_.provider_id = std::move(id);
        descriptor_.family = pp::ProviderFamily::Exporter;
        descriptor_.version = std::move(version);
        descriptor_.display_name = "echo";
        Json schema = Json::object();
        schema["type"] = "object";
        descriptor_.parameters_schema = schema;
    }
    const pp::ProviderDescriptor& descriptor() const override { return descriptor_; }
    pp::ProviderResult execute(const pp::ProviderInputs& inputs, const Json& parameters,
                               pp::ProviderContext& context) override {
        pp::ProviderResult result;
        result.metrics["echo"] = parameters.value("say", "");
        return result;
    }

private:
    pp::ProviderDescriptor descriptor_;
};

int main() {
    pp::ProviderRegistry registry;

    // Register + lookup.
    pp::ProviderDescriptor installed =
        registry.register_provider(std::make_unique<EchoProvider>("export.echo"));
    check(installed.provider_id == "export.echo", "register returns descriptor");
    check(registry.size() == 1, "size after first register");
    check(registry.find("export.echo") != nullptr, "find installed");
    check(&registry.get("export.echo") != nullptr, "get installed");

    // Duplicate, same version: DuplicateProviderError, no quarantine note.
    std::string error = expect_throw(
        [&] { registry.register_provider(std::make_unique<EchoProvider>("export.echo")); });
    check(error == "provider 'export.echo' already registered (version 1.0.0)",
          "duplicate message parity: " + error);
    check(registry.quarantined().empty(), "same-version duplicate leaves no note");

    // Duplicate with a different version: quarantine carries the conflict.
    error = expect_throw([&] {
        registry.register_provider(std::make_unique<EchoProvider>("export.echo", "2.0.0"));
    });
    check(error == "provider 'export.echo' already registered (version 1.0.0)",
          "version-conflict duplicate message parity");
    auto quarantined = registry.quarantined();
    check(quarantined.size() == 1 &&
              quarantined.count("export.echo") &&
              quarantined.at("export.echo") == "version conflict 2.0.0 vs registered 1.0.0",
          "version-conflict quarantine note");

    // replace=true admits the new version and clears the quarantine note.
    registry.register_provider(std::make_unique<EchoProvider>("export.echo", "2.0.0"), true);
    check(registry.quarantined().empty(), "replace clears quarantine");
    check(registry.get("export.echo").descriptor().version == "2.0.0",
          "replace installs the new version");

    // Invalid descriptor: quarantined, never installed, message parity.
    EchoProvider invalid("Export.Bad");  // uppercase id fails the id rule
    error = expect_throw([&] {
        registry.register_provider(std::make_unique<EchoProvider>("Export.Bad"));
    });
    check(error.find("failed validation: provider_id 'Export.Bad' must match") !=
              std::string::npos,
          "invalid descriptor message parity: " + error);
    check(registry.find("Export.Bad") == nullptr, "invalid provider not installed");
    check(registry.quarantined().at("Export.Bad").rfind("invalid descriptor:", 0) == 0,
          "invalid provider quarantined with reason");
    // Quarantine is inspectable but the registry keeps working.
    registry.register_provider(std::make_unique<EchoProvider>("export.other"));
    check(registry.size() == 2, "registry survives a bad provider");

    // descriptors() sorted by (family value, provider_id).
    registry.register_provider(std::make_unique<EchoProvider>("geology.factor_stats"));
    auto descriptors = registry.descriptors();
    check(descriptors.size() == 3, "descriptors lists all");
    bool sorted = true;
    for (std::size_t i = 1; i < descriptors.size(); ++i) {
        const auto prev = std::make_pair(pp::to_string(descriptors[i - 1].family),
                                         descriptors[i - 1].provider_id);
        const auto curr = std::make_pair(pp::to_string(descriptors[i].family),
                                         descriptors[i].provider_id);
        if (!(prev < curr)) sorted = false;
    }
    check(sorted, "descriptors sorted by (family, id)");

    // by_family filters, preserving insertion order.
    const auto exporters = registry.by_family(pp::ProviderFamily::Exporter);
    check(exporters.size() == 3, "by_family filters");
    for (const auto* provider : exporters) {
        check(provider->descriptor().family == pp::ProviderFamily::Exporter,
              "by_family family filter");
    }

    // Unknown id: UnknownProviderError with the Python message.
    error = expect_throw([&] { registry.get("missing.provider"); });
    check(error == "no provider 'missing.provider'", "unknown provider message parity");

    // unregister.
    check(registry.unregister("export.other"), "unregister installed id");
    check(!registry.unregister("export.other"), "unregister unknown id is false");
    check(registry.size() == 2, "size after unregister");

    // Builtin seeding: factories register both real providers.
    pp::ProviderRegistry builtin_registry;
    const auto registered = pp::register_builtin_providers(builtin_registry);
    check(registered.size() == 2, "builtin factories register two providers");
    check(builtin_registry.find("geology.factor_stats") != nullptr,
          "factor stats builtin registered");
    check(builtin_registry.find("export.map_thumbnail") != nullptr,
          "map thumbnail builtin registered");
    // Idempotent (replace=true path).
    const auto again = pp::register_builtin_providers(builtin_registry);
    check(again.size() == 2, "builtin registration idempotent");
    check(builtin_registry.size() == 2, "no duplicates after idempotent re-register");

    // The global singleton is builtin-seeded and usable.
    check(pp::get_provider_registry().find("geology.factor_stats") != nullptr,
          "global registry seeded with builtins");

    if (g_failures != 0) {
        std::fprintf(stderr, "providers.registry: %d checks, %d failures\n", g_checks,
                     g_failures);
        return 1;
    }
    std::printf("providers.registry: %d checks passed\n", g_checks);
    return 0;
}
