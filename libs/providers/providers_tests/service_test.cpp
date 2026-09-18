// providers.service — the Application/Workflow-facing ProviderService
// facade: builtin-seeded capability report, family filter, quarantine
// report, and one guarded run() entry point.

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/extract.hpp>
#include <pwb/providers/builtin.hpp>
#include <pwb/providers/builtin_adapters.hpp>
#include <pwb/providers/errors.hpp>
#include <pwb/providers/service.hpp>

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

int main() {
    pp::ProviderService service;

    // Capability report covers the seeded builtins with full envelopes.
    const Json report = service.capability_report();
    check(report.is_array() && report.size() == 2, "capability report lists builtins");
    check(report.at(0).at("provider_id") == "export.map_thumbnail" &&
              report.at(0).at("family") == "exporter" &&
              report.at(0).at("version") == "1.0.0" &&
              report.at(0).at("resource_profile").at("category") == "export",
          "envelope fields present in order");

    // Family filter narrows.
    const Json exporters = service.capability_report(std::string("exporter"));
    check(exporters.size() == 1 &&
              exporters.at(0).at("provider_id") == "export.map_thumbnail",
          "family filter");
    bool threw = false;
    try {
        (void)service.capability_report(std::string("bogus_family"));
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    check(threw, "unknown family rejected loudly");

    // Quarantine report starts empty and reflects registry state.
    check(service.quarantine_report().is_object() &&
              service.quarantine_report().empty(),
          "quarantine report empty on a clean host");

    // Duplicate protection holds through the service facade: re-registering
    // the builtin id is rejected and leaves the registry unchanged.
    bool duplicate_rejected = false;
    try {
        service.registry().register_provider(std::make_unique<pp::FactorStatsProvider>());
    } catch (const pp::DuplicateProviderError&) {
        duplicate_rejected = true;
    }
    check(duplicate_rejected, "duplicate protection through the service");
    check(service.capability_report().size() == 2,
          "registry unchanged after duplicate attempt");

    // run() is the guarded pipeline: unknown id surfaces the SDK error.
    bool unknown = false;
    try {
        (void)service.run("missing.provider");
    } catch (const pp::UnknownProviderError&) {
        unknown = true;
    }
    check(unknown, "run resolves through the registry");

    // End-to-end through the service: factor stats into a work dir.
    std::filesystem::path work = std::filesystem::temp_directory_path() / "pwb-service-test";
    std::filesystem::create_directories(work);
    auto dataset = pwb::mapping::FactorDataset{};
    pwb::mapping::FactorPoint point;
    point.value = 2.0;
    point.qc_flag = "ok";
    dataset.factor_name = "sand_ratio";
    dataset.points = {point, point};
    pp::ProviderInputs inputs;
    inputs.set("dataset", pp::make_dataset_typed_input("dataset", dataset));
    pp::ProviderContext context;
    context.work_dir = work.generic_string();
    const pp::ProviderResult result = service.run("geology.factor_stats", inputs,
                                                  Json::object(), &context, nullptr);
    check(result.metrics.at("count") == 2, "service run executed the provider");
    check(!result.provenance.at("provider_id").get<std::string>().empty(),
          "provenance populated through the service");
    std::error_code ec;
    std::filesystem::remove_all(work, ec);

    if (g_failures != 0) {
        std::fprintf(stderr, "providers.service: %d checks, %d failures\n", g_checks,
                     g_failures);
        return 1;
    }
    std::printf("providers.service: %d checks passed\n", g_checks);
    return 0;
}
