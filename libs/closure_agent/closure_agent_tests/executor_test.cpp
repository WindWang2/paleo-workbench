// closure_agent.executor — the guarded pipeline contracts: guard order and
// rejection reasons, status mapping (six canonical states), verification
// hooks, provider-backed actions through the REAL provider SDK, admission
// ports, and cancellation.
#include "test_util.hpp"

#include <pwb/closure_agent/executor.hpp>
#include <pwb/providers/builtin.hpp>
#include <pwb/providers/errors.hpp>
#include <pwb/providers/execution.hpp>

#include <algorithm>
#include <atomic>
#include <filesystem>
#include <memory>

using namespace pwb::closure_agent;
namespace pp = pwb::providers;

namespace {

ActionSpec simple_action(const std::string& id, ActionRisk risk,
                         ActionHandler handler) {
    ActionSpec spec;
    spec.action_id = id;
    spec.description = "test action " + id;
    spec.risk = risk;
    spec.handler = std::move(handler);
    return spec;
}

// Real (minimal) capability provider for provider-backed spec dispatch:
// doubles the "value" parameter. Real computation, no result faking.
class DoublerProvider : public pp::IProvider {
public:
    DoublerProvider() {
        descriptor_.provider_id = "test.doubler";
        descriptor_.family = pp::ProviderFamily::Interpolation;
        descriptor_.version = "1.0.0";
        descriptor_.display_name = "test doubler";
        Json schema = Json::object();
        schema["type"] = "object";
        Json value = Json::object();
        value["type"] = "integer";
        descriptor_.parameters_schema = schema;
        descriptor_.parameters_schema["properties"] = Json::object();
        descriptor_.parameters_schema["properties"]["value"] = value;
        descriptor_.parameters_schema["additionalProperties"] = false;
        descriptor_.input_types = {};
        descriptor_.output_types = {"PathRef"};
    }
    const pp::ProviderDescriptor& descriptor() const override {
        return descriptor_;
    }
    pp::ProviderResult execute(const pp::ProviderInputs&, const Json& parameters,
                               pp::ProviderContext&) override {
        pp::ProviderResult result;
        pp::ArtifactRef artifact;
        artifact.name = "doubled";
        artifact.kind = "file";
        artifact.value = parameters.at("value").get<long long>() * 2;
        result.artifacts.push_back(artifact);
        return result;
    }
    std::optional<pp::Verification> verify(const pp::ProviderResult&,
                                           pp::ProviderContext&) override {
        return std::nullopt;
    }

private:
    pp::ProviderDescriptor descriptor_;
};

struct RecordingAdmission : pp::IAdmissionPort {
    std::atomic<int> admitted{0};
    std::atomic<int> released{0};
    bool reject = false;
    std::unique_ptr<pp::IAdmissionLease> admit(
        const pp::AdmissionRequest& request) override {
        if (reject) throw pp::AdmissionRejected("governor: memory pressure");
        ++admitted;
        struct Lease : pp::IAdmissionLease {
            RecordingAdmission* owner;
            pp::AdmissionRequest req;
            explicit Lease(RecordingAdmission* o, pp::AdmissionRequest r)
                : owner(o), req(std::move(r)) {}
            void release() override { ++owner->released; }
            const pp::AdmissionRequest& request() const override { return req; }
        };
        return std::make_unique<Lease>(this, request);
    }
};

}  // namespace

int main() {
    using Json = Json;
    ActionRegistry registry;

    // ---- registration gates ------------------------------------------------
    ActionSpec destructive = simple_action("map.purge_all", ActionRisk::Destructive,
                                           [](void*, const Json&) { return Json(); });
    check(expect_throw([&] { registry.register_spec(destructive); }).find(
              "DESTRUCTIVE actions are not installable") != std::string::npos,
          "DESTRUCTIVE refused by the default registry");
    check(expect_throw([&] { registry.register_spec(destructive); }).find(
              "invalid action spec 'map.purge_all'") != std::string::npos,
          "DESTRUCTIVE refusal carries the invalid-spec message");
    ActionSpec duplicate = simple_action("map.render", ActionRisk::Read,
                                         [](void*, const Json&) { return Json(); });
    registry.register_spec(duplicate);
    check(expect_throw([&] { registry.register_spec(duplicate); }).find(
              "already registered") != std::string::npos,
          "duplicate id refused");
    check(registry.register_spec(duplicate, true).action_id == "map.render",
          "replace=true re-registers");

    // ---- guard: unknown action -> rejected ---------------------------------
    HarnessExecutor executor(registry);
    {
        const ActionResult result = executor.execute("no.such_action");
        check(result.status == "rejected", "unknown action rejected");
        check(result.error.value_or("").find("unknown harness action 'no.such_action'") !=
                  std::string::npos,
              "unknown action message parity");
    }

    // ---- guard: schema validation -> rejected -------------------------------
    {
        ActionSpec spec = simple_action("map.render", ActionRisk::Read,
                                        [](void*, const Json& p) { return p; });
        spec.input_schema = Json::object();
        spec.input_schema["type"] = "object";
        Json dpi = Json::object();
        dpi["type"] = "integer";
        spec.input_schema["properties"] = Json::object();
        spec.input_schema["properties"]["dpi"] = dpi;
        spec.input_schema["required"] = std::vector<std::string>{"dpi"};
        spec.input_schema["additionalProperties"] = false;
        registry.register_spec(spec, true);
        const ActionResult missing = executor.execute("map.render", Json::object());
        check(missing.status == "rejected", "missing required param rejected");
        check(missing.error.value_or("").find(
                  "parameters for 'map.render' invalid: parameters.dpi: "
                  "required") !=
                  std::string::npos,
              "validation error message parity");
        Json bad = Json::object();
        bad["dpi"] = "high";
        const ActionResult wrong_type = executor.execute("map.render", bad);
        check(wrong_type.status == "rejected", "wrong param type rejected");
    }

    // ---- guard: permission + required context -------------------------------
    {
        ActionSpec write_spec = simple_action("map.export_png", ActionRisk::Write,
                                              [](void*, const Json&) {
                                                  return Json{{"ok", true}};
                                              });
        registry.register_spec(write_spec);
        const ActionResult result = executor.execute("map.export_png");
        check(result.status == "rejected", "WRITE without grant rejected");
        check(result.error.value_or("").find(
                  "action 'map.export_png' requires write permission") !=
                  std::string::npos,
              "permission message parity");

        ActionSpec context_spec =
            simple_action("well.correlate", ActionRisk::Read,
                          [](void*, const Json&) { return Json{{"tops", 3}}; });
        context_spec.required_context = {"active_well_id"};
        registry.register_spec(context_spec);
        const ActionResult missing = executor.execute("well.correlate");
        check(missing.status == "rejected", "missing context rejected");
        check(missing.error.value_or("").find(
                  "requires context.active_well_id") != std::string::npos,
              "context message parity");
        ActionContext context;
        context.active_well_id = "well-1";
        const ActionResult present = executor.execute("well.correlate", Json::object(), &context);
        check(present.status == "success", "context satisfied -> success");
    }

    // ---- cancellation before + during ---------------------------------------
    {
        pp::CancelToken token;
        ActionContext context;
        context.cancel = &token;
        token.cancel();
        const ActionResult result = executor.execute("well.correlate", Json::object(), &context);
        check(result.status == "cancelled", "pre-cancelled guard -> cancelled");
    }
    {
        // The workflow adapter's bridge seam: a foreign token type surfaces
        // through cancel_probe; the guard must land `cancelled`, not failed.
        ActionContext context;
        bool probe_cancelled = false;
        context.cancel_probe = [&] { return probe_cancelled; };
        probe_cancelled = true;
        const ActionResult result = executor.execute("well.correlate", Json::object(), &context);
        check(result.status == "cancelled",
              "cancel_probe (workflow token bridge) -> cancelled");
    }
    {
        ActionSpec slow = simple_action(
            "seismic.extract", ActionRisk::Compute,
            [](void*, const Json&) -> Json {
                throw pp::TaskCancelled("seismic slice cancelled");
            });
        registry.register_spec(slow);
        ActionContext context;
        const ActionResult result = executor.execute("seismic.extract", Json::object(), &context);
        check(result.status == "cancelled",
              "handler TaskCancelled lands terminal cancelled");
        check(result.error.value_or("") == "cancelled: seismic slice cancelled",
              "cancelled error text parity");
    }

    // ---- statuses: failed / unavailable / degraded ---------------------------
    {
        ActionSpec boom = simple_action(
            "gis.analyze", ActionRisk::Compute,
            [](void*, const Json&) -> Json { throw std::runtime_error("topology broken"); });
        registry.register_spec(boom);
        check(executor.execute("gis.analyze").status == "failed",
              "handler exception -> failed");
    }
    {
        ActionSpec unavailable = simple_action(
            "onnx.infer", ActionRisk::Compute,
            [](void*, const Json&) -> Json {
                throw ActionUnavailableError("inference backend missing");
            });
        registry.register_spec(unavailable);
        const ActionResult result = executor.execute("onnx.infer");
        check(result.status == "unavailable", "missing backend -> unavailable");
        check(result.error.value_or("").find("unavailable:") == 0,
              "unavailable error prefixed");
    }
    {
        ActionSpec verifier_warning = simple_action(
            "carto.interpolate", ActionRisk::Compute,
            [](void*, const Json&) { return Json{{"grid", Json::array()}}; });
        verifier_warning.verifier =
            [](const Json&, const Json&, void*) {
                return Json{{"verdict", "warning"},
                            {"reasons", std::vector<std::string>{"thin coverage"}}};
            };
        registry.register_spec(verifier_warning);
        const ActionResult result = executor.execute("carto.interpolate");
        check(result.status == "degraded", "verifier warning -> degraded");
        check(result.warnings.size() == 1 &&
                  result.warnings[0] == "thin coverage",
              "degraded carries the warning reason");
    }
    {
        // A grid output failing the scientific gate -> failed, never ok.
        ActionSpec degenerate = simple_action(
            "carto.grid", ActionRisk::Compute,
            [](void*, const Json&) { return Json::array(); });
        registry.register_spec(degenerate);
        const ActionResult result = executor.execute("carto.grid");
        check(result.status == "failed", "degenerate grid fails the action");
        check(result.error.value_or("").find("verification failed") == 0,
              "scientific failure message");
    }

    // ---- provider-backed spec dispatch through the REAL registry ------------
    {
        pp::ProviderRegistry providers;
        providers.register_provider(std::make_unique<DoublerProvider>());
        ExecutorConfig config;
        config.providers = &providers;
        HarnessExecutor provider_executor(registry, config);
        ActionSpec spec = simple_action("test.double_it", ActionRisk::Compute,
                                        nullptr);
        spec.provider_id = "test.doubler";
        spec.input_schema = Json::object();
        spec.input_schema["type"] = "object";
        Json value_schema = Json::object();
        value_schema["type"] = "integer";
        spec.input_schema["properties"] = Json::object();
        spec.input_schema["properties"]["value"] = value_schema;
        spec.input_schema["required"] = std::vector<std::string>{"value"};
        spec.input_schema["additionalProperties"] = false;
        registry.register_spec(spec);
        Json params = Json::object();
        params["value"] = 21;
        const ActionResult result = provider_executor.execute("test.double_it", params);
        check(result.status == "success", "provider-backed action succeeds");
        check(result.outputs["values"].is_array() &&
                  result.outputs["values"].size() == 1 &&
                  result.outputs["values"][0] == 42,
              "real provider computed 42");
        check(result.outputs["artifacts"][0]["name"] == "doubled",
              "artifact metadata projected");
        check(result.metrics.contains("provenance"),
              "provider provenance recorded");
        // Unknown provider id -> honest unavailability, never a fake result.
        ActionSpec missing_provider = simple_action("test.missing", ActionRisk::Compute, nullptr);
        missing_provider.provider_id = "no.such_provider";
        registry.register_spec(missing_provider);
        const ActionResult unavailable = provider_executor.execute("test.missing");
        check(unavailable.status == "unavailable",
              "unknown provider -> unavailable");
    }

    // ---- real builtin provider consumed through a handler -------------------
    {
        pp::ProviderRegistry providers;
        pp::register_builtin_providers(providers);
        ExecutorConfig config;
        config.providers = &providers;
        HarnessExecutor builtin_executor(registry, config);
        // The handler reaches the registry through the context extras (the
        // host's service-injection seam) and drives the REAL builtin
        // geology.factor_stats through the guarded provider pipeline.
        ActionSpec stats = simple_action(
            "geology.factor_stats", ActionRisk::Compute,
            [](void* ctx, const Json& p) {
                auto* context = static_cast<ActionContext*>(ctx);
                const auto* providers = reinterpret_cast<const pp::ProviderRegistry*>(
                    context->extras["provider_registry"].get<long long>());
                pp::ProviderInputs inputs;
                pp::TypedInput dataset;
                dataset.type_name = "GeologicalFactorDataset";
                dataset.payload = p["dataset"];
                inputs.set("dataset", std::move(dataset));
                pp::ProviderContext provider_context = context->provider_context();
                provider_context.work_dir =
                    std::filesystem::temp_directory_path().string() +
                    "/closure-agent-test";
                const pp::ProviderResult result = pp::execute_provider(
                    *providers, "geology.factor_stats", inputs, Json::object(),
                    &provider_context, nullptr);
                Json payload = Json::object();
                Json artifacts = Json::array();
                for (const auto& artifact : result.artifacts) {
                    artifacts.push_back(artifact.to_json());
                }
                payload["artifacts"] = artifacts;
                payload["provenance"] = result.provenance;
                return payload;
            });
        registry.register_spec(stats);
        Json clean_params = Json::object();
        Json dataset = Json::object();
        dataset["factor_name"] = "砂地比";
        dataset["unit"] = "1";
        dataset["target_horizon"] = "长8段";
        dataset["crs"] = "EPSG:4326";
        Json points = Json::array();
        for (const auto& [name, value] :
             std::vector<std::pair<const char*, double>>{
                 {"w1", 0.31}, {"w2", 0.42}, {"w3", 0.55},
                 {"w4", 0.38}, {"w5", 0.60}}) {
            Json point = Json::object();
            point["name"] = name;
            point["value"] = value;
            point["qc_flag"] = "ok";
            points.push_back(point);
        }
        dataset["points"] = points;
        clean_params["dataset"] = dataset;
        ActionContext context;
        context.extras["provider_registry"] =
            reinterpret_cast<long long>(&providers);
        const ActionResult result =
            builtin_executor.execute("geology.factor_stats", clean_params, &context);
        check(result.status == "success", "builtin factor_stats action succeeds");
        check(result.outputs["artifacts"].is_array() &&
                  !result.outputs["artifacts"].empty(),
              "factor stats produced real artifacts");
        check(result.outputs.contains("provenance"),
              "factor stats provenance recorded");
    }

    // ---- admission port ------------------------------------------------------
    {
        RecordingAdmission admission;
        ExecutorConfig config;
        config.admission = &admission;
        HarnessExecutor admitted_executor(registry, config);
        Json params = Json::object();
        params["dpi"] = 300;
        const ActionResult ok = admitted_executor.execute("map.render", params);
        check(ok.status == "success", "admitted action succeeds");
        check(admission.admitted.load() == 1 && admission.released.load() == 1,
              "lease admitted once and released");
        admission.reject = true;
        const ActionResult rejected =
            admitted_executor.execute("map.render", params);
        check(rejected.status == "rejected",
              "admission refusal (pressure shedding) -> rejected");
    }

    return test_exit("closure_agent.executor");
}
