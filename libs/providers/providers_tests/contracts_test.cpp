// providers.contracts — descriptor contracts: validation rules table, JSON
// envelope parity, family round-trip, ResourceProfile defaults, and
// assert_valid_descriptor's exception shape (Python parity of messages).

#include <cstdio>
#include <stdexcept>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/providers/contracts.hpp>
#include <pwb/providers/errors.hpp>

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

pp::ProviderDescriptor valid_descriptor() {
    pp::ProviderDescriptor d;
    d.provider_id = "geology.factor_stats";
    d.family = pp::ProviderFamily::Interpolation;
    d.version = "1.0.0";
    d.display_name = "地质因子统计摘要";
    d.capabilities = {"factor_stats"};
    d.input_types = {"GeologicalFactorDataset", "FactorDatasetRef"};
    d.output_types = {"PathRef"};
    Json schema = Json::object();
    schema["type"] = "object";
    schema["properties"] = Json::object();
    d.parameters_schema = schema;
    d.resource_profile.estimated_cpu_cores = 0.5;
    d.resource_profile.estimated_ram_bytes = 67108864;
    d.resource_profile.io_weight = 0.2;
    d.build_identity = "cpp/libs/providers@2026-09-19";
    return d;
}

int main() {
    // Family vocabulary round-trips and the C++ typed-ref vocabulary is the
    // frozen Python one (9 entries).
    check(pp::typed_refs().size() == 9, "typed_refs size");
    for (int i = 0; i < 9; ++i) {
        const auto family = static_cast<pp::ProviderFamily>(i);
        auto parsed = pp::family_from_string(pp::to_string(family));
        check(parsed.has_value() && *parsed == family, "family round-trip");
    }
    check(!pp::family_from_string("nope").has_value(), "unknown family rejected");

    // A valid descriptor validates clean and serializes with the Python
    // to_dict() key order.
    const pp::ProviderDescriptor valid = valid_descriptor();
    check(pp::validate_descriptor(valid).empty(), "valid descriptor has no problems");
    const Json envelope = valid.to_json();
    std::string keys;
    for (auto it = envelope.begin(); it != envelope.end(); ++it) {
        if (!keys.empty()) keys += ",";
        keys += it.key();
    }
    check(keys ==
              "provider_id,family,version,display_name,description,capabilities,"
              "input_types,output_types,parameters_schema,resource_profile,"
              "supports_cancel,supports_resume,deterministic,threading_model,"
              "build_identity",
          "to_json key order matches Python to_dict");

    // Validation rule table: one structural deviation per case, expected
    // first problem verbatim.
    const struct {
        std::string id;
        std::function<pp::ProviderDescriptor()> make;
        std::string expected_problem;
    } cases[] = {
        {"empty-id", [] { auto d = valid_descriptor(); d.provider_id = ""; return d; },
         "provider_id '' must match ^[a-z0-9][a-z0-9._-]{1,63}$"},
        {"uppercase-id",
         [] {
             auto d = valid_descriptor();
             d.provider_id = "Geology.Stats";
             return d;
         },
         "provider_id 'Geology.Stats' must match ^[a-z0-9][a-z0-9._-]{1,63}$"},
        {"short-id", [] { auto d = valid_descriptor(); d.provider_id = "a"; return d; },
         "provider_id 'a' must match ^[a-z0-9][a-z0-9._-]{1,63}$"},
        {"bad-version",
         [] {
             auto d = valid_descriptor();
             d.version = "1.0.x";
             return d;
         },
         "version '1.0.x' must be numeric dotted (e.g. 1.0.0)"},
        {"five-segment-version",
         [] {
             auto d = valid_descriptor();
             d.version = "1.2.3.4.5";
             return d;
         },
         "version '1.2.3.4.5' must be numeric dotted (e.g. 1.0.0)"},
        {"blank-display-name",
         [] {
             auto d = valid_descriptor();
             d.display_name = "  \t ";
             return d;
         },
         "display_name must be a non-empty string"},
        {"schema-non-object",
         [] {
             auto d = valid_descriptor();
             d.parameters_schema = Json("nope");
             return d;
         },
         "parameters_schema must be a dict (JSON schema)"},
        {"schema-wrong-top-type",
         [] {
             auto d = valid_descriptor();
             Json s = Json::object();
             s["type"] = "string";
             d.parameters_schema = s;
             return d;
         },
         "parameters_schema must describe an object at the top level"},
        {"schema-properties-not-dict",
         [] {
             auto d = valid_descriptor();
             Json s = Json::object();
             s["properties"] = Json::array();
             d.parameters_schema = s;
             return d;
         },
         "parameters_schema.properties must be a dict"},
        {"schema-required-not-list",
         [] {
             auto d = valid_descriptor();
             Json s = Json::object();
             s["required"] = "width";
             d.parameters_schema = s;
             return d;
         },
         "parameters_schema.required must be a list"},
        {"unknown-input-ref",
         [] {
             auto d = valid_descriptor();
             d.input_types = {"BogusRef"};
             return d;
         },
         "input_types entry 'BogusRef' is not a known typed ref ['DataVersionRef', "
         "'FactorDatasetRef', 'FactorGridRef', 'GeologicalFactorDataset', "
         "'MapDocument', 'MapDocumentRef', 'PathRef', 'SeismicVolumeRef', 'WellRef']"},
        {"unknown-output-ref",
         [] {
             auto d = valid_descriptor();
             d.output_types = {"BogusRef"};
             return d;
         },
         "output_types entry 'BogusRef' is not a known typed ref ['DataVersionRef', "
         "'FactorDatasetRef', 'FactorGridRef', 'GeologicalFactorDataset', "
         "'MapDocument', 'MapDocumentRef', 'PathRef', 'SeismicVolumeRef', 'WellRef']"},
        {"bad-threading-model",
         [] {
             auto d = valid_descriptor();
             d.threading_model = "main_loop";
             return d;
         },
         "threading_model 'main_loop' invalid"},
        {"cpu-cores-zero",
         [] {
             auto d = valid_descriptor();
             d.resource_profile.estimated_cpu_cores = 0.0;
             return d;
         },
         "resource_profile.estimated_cpu_cores must be > 0"},
        {"io-weight-negative",
         [] {
             auto d = valid_descriptor();
             d.resource_profile.io_weight = -0.1;
             return d;
         },
         "resource_profile.io_weight must be >= 0"},
    };
    for (const auto& c : cases) {
        const auto problems = pp::validate_descriptor(c.make());
        check(!problems.empty(), c.id + ": has problems");
        check(!problems.empty() && problems.front() == c.expected_problem,
              c.id + ": first problem == '" + c.expected_problem + "' (got '" +
                  (problems.empty() ? "<none>" : problems.front()) + "')");
    }

    // ResourceProfile defaults (Python parity).
    const pp::ResourceProfile profile;
    check(profile.estimated_cpu_cores == 1.0 && profile.estimated_ram_bytes == 0 &&
              profile.estimated_vram_bytes == 0 && profile.io_weight == 1.0 &&
              profile.category == "background.compute",
          "ResourceProfile defaults");

    // assert_valid_descriptor throws InvalidProviderError with the joined
    // message and carries the problem list.
    pp::ProviderDescriptor broken = valid_descriptor();
    broken.provider_id = "BAD ID";
    broken.threading_model = "coroutine";
    bool threw = false;
    try {
        pp::assert_valid_descriptor(broken);
    } catch (const pp::InvalidProviderError& exc) {
        threw = true;
        check(exc.problems().size() == 2, "InvalidProviderError carries both problems");
        check(exc.provider_id() == "BAD ID", "InvalidProviderError carries id");
        check(std::string(exc.what()) ==
                  "provider 'BAD ID' failed validation: provider_id 'BAD ID' must "
                  "match ^[a-z0-9][a-z0-9._-]{1,63}$; threading_model 'coroutine' invalid",
              "InvalidProviderError message parity");
    }
    check(threw, "assert_valid_descriptor throws");

    if (g_failures != 0) {
        std::fprintf(stderr, "providers.contracts: %d checks, %d failures\n", g_checks,
                     g_failures);
        return 1;
    }
    std::printf("providers.contracts: %d checks passed\n", g_checks);
    return 0;
}
