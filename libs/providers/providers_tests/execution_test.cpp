// providers.execution — the guarded pipeline: envelope defaults, schema and
// input validation ordering, admission lease ownership (incl. #1146
// inheritance), provenance DataRun lifecycle (#1137 cancellation as
// first-class outcome), error wrapping, and the fail-closed verify hook.

#include <cstdio>
#include <deque>
#include <functional>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/providers/errors.hpp>
#include <pwb/providers/execution.hpp>
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

template <typename E, typename Fn>
bool expect(Fn&& fn, std::string* message = nullptr) {
    try {
        fn();
    } catch (const E& exc) {
        if (message != nullptr) *message = exc.what();
        return true;
    } catch (...) {
        return false;
    }
    return false;
}

// Recording catalog port: DataRun lifecycle bookkeeping.
class FakeCatalog : public pp::ICatalogPort {
public:
    struct RunRecord {
        std::string run_id;
        std::string operation;
        std::vector<std::string> input_version_ids;
        Json parameters = Json::object();
        std::string generator_version;
        std::string status;
    };
    std::vector<RunRecord> runs;
    bool fail_begin = false;
    int registered_intermediates = 0;

    std::optional<RunRef> begin_run(const RunSpec& spec) override {
        if (fail_begin) throw std::runtime_error("catalog offline");
        RunRecord record;
        record.run_id = "run-" + std::to_string(runs.size() + 1);
        record.operation = spec.operation;
        record.input_version_ids = spec.input_version_ids;
        record.parameters = spec.parameters;
        record.generator_version = spec.generator_version;
        record.status = "open";
        runs.push_back(std::move(record));
        return RunRef{runs.back().run_id};
    }
    void complete_run(const std::string& run_id, const std::string& status) override {
        for (auto& run : runs) {
            if (run.run_id == run_id) run.status = status;
        }
    }
    std::optional<Json> register_intermediate(const std::string& /*run_id*/,
                                              const std::string& /*name*/,
                                              const std::string& /*path*/,
                                              const std::string& /*kind*/,
                                              const std::string& /*format*/) override {
        ++registered_intermediates;
        Json version = Json::object();
        version["version_id"] = "v-intermediate";
        return version;
    }
};

// Admission port recording leases. Records live in a deque: admit() hands
// out Record pointers, which must stay valid across reallocation.
class FakeAdmission : public pp::IAdmissionPort {
public:
    struct Record {
        pp::AdmissionRequest request;
        bool released = false;
    };
    std::deque<Record> admitted;
    bool reject = false;

    std::unique_ptr<pp::IAdmissionLease> admit(const pp::AdmissionRequest& request) override {
        if (reject) throw pp::AdmissionRejected("pressure shedding");
        struct Lease : pp::IAdmissionLease {
            explicit Lease(Record* r) : record(r) {}
            void release() override { record->released = true; }
            const pp::AdmissionRequest& request() const override { return record->request; }
            Record* record;
        };
        admitted.push_back(Record{});
        admitted.back().request = request;
        return std::make_unique<Lease>(&admitted.back());
    }
};

// Configurable provider used by the pipeline cases.
class StubProvider : public pp::IProvider {
public:
    StubProvider(std::string id, std::string family = "exporter") {
        descriptor_.provider_id = std::move(id);
        auto parsed = pp::family_from_string(family);
        descriptor_.family = parsed.value_or(pp::ProviderFamily::Exporter);
        descriptor_.version = "1.0.0";
        descriptor_.display_name = "stub";
        Json schema = Json::object();
        schema["type"] = "object";
        Json props = Json::object();
        Json say = Json::object();
        say["type"] = "string";
        props["say"] = say;
        schema["properties"] = props;
        descriptor_.parameters_schema = schema;
    }

    void set_input_types(std::vector<std::string> types) {
        descriptor_.input_types = std::move(types);
    }
    void set_ram_bytes(long long bytes) {
        descriptor_.resource_profile.estimated_ram_bytes = bytes;
    }

    const pp::ProviderDescriptor& descriptor() const override { return descriptor_; }

    std::function<pp::ProviderResult(pp::ProviderContext&)> on_execute =
        [](pp::ProviderContext&) { return pp::ProviderResult{}; };
    std::function<std::optional<pp::Verification>(const pp::ProviderResult&,
                                                  pp::ProviderContext&)>
        on_verify = [](const pp::ProviderResult&, pp::ProviderContext&) {
            return std::optional<pp::Verification>{};
        };

    pp::ProviderResult execute(const pp::ProviderInputs& inputs, const Json& parameters,
                               pp::ProviderContext& context) override {
        (void)parameters;
        return on_execute(context);
    }
    std::optional<pp::Verification> verify(const pp::ProviderResult& result,
                                           pp::ProviderContext& context) override {
        return on_verify(result, context);
    }

private:
    pp::ProviderDescriptor descriptor_;
};

int main() {
    // --- happy path: envelope defaults + provenance run bookkeeping ---------
    pp::ProviderRegistry registry;
    registry.register_provider(std::make_unique<StubProvider>("export.happy"));

    pp::TypedInput volume;
    volume.type_name = "SeismicVolumeRef";
    Json volume_payload = Json::object();
    volume_payload["volume_id"] = "v1";
    volume_payload["version_id"] = "ver-42";
    volume.payload = volume_payload;
    pp::ProviderInputs inputs;
    inputs.set("volume", volume);

    Json parameters = Json::object();
    parameters["say"] = "hi";
    FakeCatalog catalog;
    pp::ProviderContext context;
    context.catalog = &catalog;
    context.work_dir = "/tmp/pwb-providers-test";

    pp::ProviderResult result = pp::execute_provider(registry, "export.happy", inputs,
                                                     parameters, &context);
    check(result.metrics.contains("elapsed_ms"), "elapsed_ms recorded");
    check(result.provenance.at("provider_id") == "export.happy" &&
              result.provenance.at("provider_version") == "1.0.0" &&
              result.provenance.at("operation") == "provider.exporter.export.happy" &&
              result.provenance.at("parameters") == parameters,
          "provenance defaults");
    check(result.provenance.at("run_id") == "run-1", "run id in provenance");
    check(context.run_id == "run-1", "context.run_id set by executor");
    check(catalog.runs.size() == 1 && catalog.runs.front().status == "complete",
          "DataRun completed");
    check(catalog.runs.front().input_version_ids ==
              std::vector<std::string>{"ver-42"},
          "input version ids feed the run");
    check(catalog.runs.front().generator_version == "1.0.0", "generator version recorded");

    // --- validate-before-execute ordering ----------------------------------
    // 1) invalid parameters: InvalidParametersError, no admission, no run.
    {
        StubProvider p("export.strict");
        FakeAdmission admission;
        Json bad = Json::object();
        bad["say"] = 5;
        Json empty_inputs_json = Json::object();
        (void)empty_inputs_json;
        pp::ProviderInputs no_inputs;
        std::string message;
        check(expect<pp::InvalidParametersError>(
                  [&] { pp::execute_provider(p, no_inputs, bad, nullptr, &admission); },
                  &message),
              "invalid parameters throw");
        check(message ==
                  "parameters for 'export.strict' failed schema validation: "
                  "parameters.say: expected string, got int",
              "InvalidParametersError message parity: " + message);
        check(admission.admitted.empty(), "no admission before validation");
    }
    // 2) undeclared input type: ProviderRejectedInputError.
    {
        StubProvider p("export.typed");
        p.set_input_types({"SeismicVolumeRef"});
        pp::ProviderInputs bad_inputs;
        pp::TypedInput wrong;
        wrong.type_name = "PathRef";
        bad_inputs.set("volume", wrong);
        std::string message;
        check(expect<pp::ProviderRejectedInputError>(
                  [&] {
                      Json empty_params = Json::object();
                      pp::execute_provider(p, bad_inputs, empty_params, nullptr, nullptr);
                  },
                  &message),
              "rejected input throw");
        check(message ==
                  "provider 'export.typed' rejected inputs: input 'volume' has type "
                  "PathRef, declared input types: ['SeismicVolumeRef']",
              "rejected-input message parity: " + message);
    }

    // --- error wrapping + failed run status --------------------------------
    {
        StubProvider p("export.boom");
        p.on_execute = [](pp::ProviderContext&) -> pp::ProviderResult {
            throw std::invalid_argument("boom");
        };
        FakeCatalog c;
        pp::ProviderContext ctx;
        ctx.catalog = &c;
        std::string message;
        check(expect<pp::ProviderExecutionError>(
                  [&] {
                      Json empty_params = Json::object();
                      pp::ProviderInputs no_inputs;
                      pp::execute_provider(p, no_inputs, empty_params, &ctx, nullptr);
                  },
                  &message),
              "execution wrap throw");
        check(message == "provider 'export.boom' failed: ValueError: boom",
              "ProviderExecutionError message parity: " + message);
        check(c.runs.front().status == "failed", "DataRun marked failed");
    }
    // ProviderError subclasses pass through unwrapped.
    {
        StubProvider p("export.sdk_error");
        p.on_execute = [](pp::ProviderContext&) -> pp::ProviderResult {
            throw pp::ProviderRejectedInputError("export.sdk_error", "bad refs");
        };
        std::string message;
        check(expect<pp::ProviderRejectedInputError>(
                  [&] {
                      Json empty_params = Json::object();
                      pp::ProviderInputs no_inputs;
                      pp::execute_provider(p, no_inputs, empty_params, nullptr, nullptr);
                  },
                  &message),
              "SDK error passthrough");
        check(message == "provider 'export.sdk_error' rejected inputs: bad refs",
              "SDK error unwrapped: " + message);
    }

    // --- cancellation (#1137): first-class outcome, cancelled run ----------
    {
        StubProvider p("export.cancelled");
        pp::CancelToken token;
        p.on_execute = [&token](pp::ProviderContext& ctx) -> pp::ProviderResult {
            token.cancel();
            ctx.check_cancelled();  // throws TaskCancelled
            return pp::ProviderResult{};
        };
        FakeCatalog c;
        pp::ProviderContext ctx;
        ctx.catalog = &c;
        ctx.cancel = &token;
        bool cancelled_thrown = false;
        try {
            Json empty_params = Json::object();
            pp::ProviderInputs no_inputs;
            pp::execute_provider(p, no_inputs, empty_params, &ctx, nullptr);
        } catch (const pp::TaskCancelled& exc) {
            cancelled_thrown = true;
            check(std::string(exc.what()) == "provider execution cancelled",
                  "TaskCancelled message parity");
        }
        check(cancelled_thrown, "cancellation propagates unwrapped");
        check(c.runs.front().status == "cancelled", "DataRun marked cancelled");
    }

    // --- admission: lease ownership + #1146 inheritance ---------------------
    {
        StubProvider p("export.admitted");
        p.set_ram_bytes(512LL * 1024 * 1024);
        FakeAdmission admission;
        Json empty_params = Json::object();
        pp::ProviderInputs no_inputs;
        auto admitted_result =
            pp::execute_provider(p, no_inputs, empty_params, nullptr, &admission);
        (void)admitted_result;
        check(admission.admitted.size() == 1, "admitted once");
        check(admission.admitted.front().request.title == "provider:export.admitted",
              "admission title parity");
        check(admission.admitted.front().request.estimated_ram_bytes ==
                  512LL * 1024 * 1024,
              "admission carries the resource profile");
        check(admission.admitted.front().released, "owned lease released");
    }
    {
        // Enclosing lease inherited: no second admission, no release by the
        // executor (the enclosing scope keeps owning it).
        StubProvider p("export.nested");
        p.set_ram_bytes(512LL * 1024 * 1024);
        FakeAdmission admission;
        pp::ProviderContext ctx;
        struct EnclosingLease : pp::IAdmissionLease {
            pp::AdmissionRequest req;
            const pp::AdmissionRequest& request() const override { return req; }
            void release() override { released = true; }
            bool released = false;
        } enclosing_lease;
        enclosing_lease.req.estimated_ram_bytes = 256LL * 1024 * 1024;
        ctx.admission_lease = &enclosing_lease;
        Json empty_params = Json::object();
        pp::ProviderInputs no_inputs;
        pp::execute_provider(p, no_inputs, empty_params, &ctx, &admission);
        check(admission.admitted.empty(), "enclosing lease inherited (no re-admit)");
        check(!enclosing_lease.released, "executor does not release the enclosing lease");
    }
    // Pressure shedding propagates unwrapped.
    {
        StubProvider p("export.shed");
        FakeAdmission admission;
        admission.reject = true;
        Json empty_params = Json::object();
        pp::ProviderInputs no_inputs;
        check(expect<pp::AdmissionRejected>(
                  [&] { pp::execute_provider(p, no_inputs, empty_params, nullptr, &admission); }),
              "AdmissionRejected propagates");
    }

    // --- verify hook (Harness 2.0, fail-closed) -----------------------------
    {
        // Verifier pass with reasons → warnings; extra keys → metrics.
        StubProvider p("export.verified");
        p.on_verify = [](const pp::ProviderResult&, pp::ProviderContext&) {
            pp::Verification v;
            v.verdict = "pass";
            v.reasons = {"rendered in 2 layers"};
            v.extra = Json::object();
            v.extra["depth"] = 2;
            return v;
        };
        Json empty_params = Json::object();
        pp::ProviderInputs no_inputs;
        auto verified = pp::execute_provider(p, no_inputs, empty_params, nullptr, nullptr);
        check(verified.warnings.size() == 1 &&
                  verified.warnings.front() == "rendered in 2 layers",
              "verifier warnings ride along");
        check(verified.metrics.contains("verification") &&
                  verified.metrics.at("verification").at("depth") == 2,
              "verifier extras land in metrics");
    }
    {
        // Python setdefault parity: a dict verification with only a verdict
        // still inserts an (empty) metrics["verification"] object.
        StubProvider p("export.verified.empty");
        p.on_verify = [](const pp::ProviderResult&, pp::ProviderContext&) {
            return pp::Verification{};  // verdict pass, no reasons, no extras
        };
        Json empty_params = Json::object();
        pp::ProviderInputs no_inputs;
        auto verified = pp::execute_provider(p, no_inputs, empty_params, nullptr, nullptr);
        check(verified.metrics.contains("verification") &&
                  verified.metrics.at("verification").is_object() &&
                  verified.metrics.at("verification").empty(),
              "empty verification still recorded (setdefault parity)");
    }
    {
        StubProvider p("export.reject");
        p.on_verify = [](const pp::ProviderResult&, pp::ProviderContext&) {
            pp::Verification v;
            v.verdict = "fail";
            v.reasons = {"mean outside range"};
            return v;
        };
        FakeCatalog c;
        pp::ProviderContext ctx;
        ctx.catalog = &c;
        std::string message;
        check(expect<pp::ProviderVerificationError>(
                  [&] {
                      Json empty_params = Json::object();
                      pp::ProviderInputs no_inputs;
                      pp::execute_provider(p, no_inputs, empty_params, &ctx, nullptr);
                  },
                  &message),
              "verify fail throws");
        check(message == "provider 'export.reject' verification failed: mean outside range",
              "verification message parity: " + message);
        check(c.runs.front().status == "failed", "verification failure marks run failed");
    }
    {
        // Empty reasons fall back to the generic reason; verdict "false" fails.
        StubProvider p("export.reject.quiet");
        p.on_verify = [](const pp::ProviderResult&, pp::ProviderContext&) {
            pp::Verification v;
            v.verdict = "false";
            return v;
        };
        std::string message;
        check(expect<pp::ProviderVerificationError>(
                  [&] {
                      Json empty_params = Json::object();
                      pp::ProviderInputs no_inputs;
                      pp::execute_provider(p, no_inputs, empty_params, nullptr, nullptr);
                  },
                  &message),
              "verdict 'false' also fails");
        check(message ==
                  "provider 'export.reject.quiet' verification failed: verification failed",
              "generic verification reason: " + message);
    }
    {
        // Crashed verifier is fail-closed.
        StubProvider p("export.verify_crash");
        p.on_verify = [](const pp::ProviderResult&, pp::ProviderContext&)
            -> std::optional<pp::Verification> {
            throw std::runtime_error("checksum unavailable");
        };
        std::string message;
        check(expect<pp::ProviderVerificationError>(
                  [&] {
                      Json empty_params = Json::object();
                      pp::ProviderInputs no_inputs;
                      pp::execute_provider(p, no_inputs, empty_params, nullptr, nullptr);
                  },
                  &message),
              "verifier crash fail-closed");
        check(message ==
                  "provider 'export.verify_crash' verification failed: verifier "
                  "crashed: RuntimeError: checksum unavailable",
              "verifier crash message parity: " + message);
    }

    // --- catalog failures never block execution -----------------------------
    {
        StubProvider p("export.catalog_down");
        FakeCatalog c;
        c.fail_begin = true;
        pp::ProviderContext ctx;
        ctx.catalog = &c;
        Json empty_params = Json::object();
        pp::ProviderInputs no_inputs;
        auto degraded = pp::execute_provider(p, no_inputs, empty_params, &ctx, nullptr);
        check(!degraded.provenance.contains("run_id"), "no run id without a DataRun");
        check(degraded.provenance.at("provider_id") == "export.catalog_down",
              "provenance still present");
        check(c.runs.empty(), "no run records after begin failure");
    }

    // --- unknown provider ----------------------------------------------------
    {
        std::string message;
        check(expect<pp::UnknownProviderError>(
                  [&] { pp::execute_provider(registry, "missing.provider"); },
                  &message),
              "unknown provider throws");
        check(message == "no provider 'missing.provider'", "unknown message parity");
    }

    if (g_failures != 0) {
        std::fprintf(stderr, "providers.execution: %d checks, %d failures\n", g_checks,
                     g_failures);
        return 1;
    }
    std::printf("providers.execution: %d checks passed\n", g_checks);
    return 0;
}
