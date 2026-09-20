// closure_agent.model — the model transport seam and the tool-source
// binding: deterministic recorded replay (fail-closed on exhaustion), honest
// remote unavailability without a native transport or credentials, the
// injected-exchange online path, and the guarded tool execution surface.
#include "test_util.hpp"

#include <pwb/closure_agent/executor.hpp>
#include <pwb/closure_agent/model_transport.hpp>
#include <pwb/closure_agent/tool_source.hpp>

#include <cstdlib>

#include <pwb/domain/sha256.hpp>

using namespace pwb::closure_agent;

namespace {

ActionRegistry& shared_registry() {
    static ActionRegistry registry;
    static const bool initialized = [] {
        ActionSpec spec;
        spec.action_id = "geology.factor_stats";
        spec.description = "Factor statistics summary";
        spec.risk = ActionRisk::Read;
        spec.handler = [](void*, const Json& p) {
            return Json{{"count", p.value("count", 0)},
                        {"mean", 0.452}};
        };
        registry.register_spec(spec);
        return true;
    }();
    (void)initialized;
    return registry;
}

}  // namespace

int main() {
    // ---- recorded replay: deterministic, fail-closed on exhaustion ----------
    {
        Json script = Json::object();
        script["model_id"] = "recorded-geologist-v1";
        Json responses = Json::array();
        Json first = Json::object();
        first["content"] = "turn-1";
        responses.push_back(first);
        Json second = Json::object();
        Json calls = Json::array();
        Json call = Json::object();
        call["name"] = "geology__factor_stats";
        call["arguments"] = Json::object();
        calls.push_back(call);
        second["tool_calls"] = calls;
        responses.push_back(second);
        script["responses"] = responses;

        RecordedChatModel model(script);
        check(model.model_id() == "recorded-geologist-v1", "model id seam");
        Json messages = Json::array();
        const Json reply_one = model.complete(messages, nullptr);
        check(reply_one["content"] == "turn-1", "first recorded response");
        const Json reply_two = model.complete(messages, nullptr);
        check(reply_two["tool_calls"].size() == 1, "second recorded response");
        check(model.remaining() == 0, "script exhausted");
        const std::string message =
            expect_throw([&] { model.complete(messages, nullptr); });
        check(message.find("exhausted") != std::string::npos,
              "exhausted script fails closed: " + message);
    }

    // ---- recorded script integrity: checksum verified at construction -----
    {
        Json responses = Json::array();
        Json first = Json::object();
        first["content"] = "turn-1";
        responses.push_back(first);
        pwb::domain::Sha256 digest;
        const std::string canonical = responses.dump();
        digest.update(canonical.data(), canonical.size());
        Json script = Json::object();
        script["model_id"] = "recorded-geologist-v1";
        script["responses"] = responses;
        script["checksum_sha256"] = digest.hex_digest();
        RecordedChatModel good(script);
        Json messages = Json::array();
        check(good.complete(messages, nullptr)["content"] == "turn-1",
              "checksum-valid script replays");
        // Tamper: flip the content, keep the stale checksum.
        script["responses"][0]["content"] = "tampered";
        const std::string message = expect_throw([&] { RecordedChatModel bad(script); });
        check(message.find("checksum mismatch") != std::string::npos,
              "tampered script refused: " + message);
    }

    // ---- remote model: honest unavailability without transport/credentials --
    {
        RemoteChatModelConfig config;
        config.endpoint = "https://model.example.invalid/v1/chat/completions";
        config.model = "external-geologist";
        config.api_key_env = "PWB_CLOSURE_AGENT_TEST_KEY";
        RemoteChatModel no_transport(config, nullptr);
        check(!no_transport.has_transport(), "no transport injected");
        Json messages = Json::array();
        const std::string message =
            expect_throw([&] { no_transport.complete(messages, nullptr); });
        check(message.find("no native transport") != std::string::npos,
              "missing transport reported honestly: " + message);
        check(message.find("recorded replay remains") != std::string::npos,
              "unavailability names the verified offline path");

        // Transport injected but no credentials -> honest unavailability, and
        // the endpoint is never contacted.
        ::setenv("PWB_CLOSURE_AGENT_TEST_KEY", "", 1);
        bool contacted = false;
        RemoteChatModel no_key(config, [&](const std::string&, const std::string&,
                                           const std::string&, std::string&) {
            contacted = true;
            return "{}";
        });
        check(no_key.has_transport(), "transport injected");
        const std::string key_error =
            expect_throw([&] { no_key.complete(messages, nullptr); });
        check(key_error.find("no API key") != std::string::npos,
              "missing credentials reported honestly: " + key_error);
        check(!contacted, "no exchange attempted without credentials");

        // Transport + credentials: the real exchange path (this is the seam a
        // TLS-enabled host build injects; online verification requires real
        // credentials and is honestly reported as not executed in the
        // line-11 acceptance ledger).
        ::setenv("PWB_CLOSURE_AGENT_TEST_KEY", "test-key-123", 1);
        std::string seen_endpoint;
        std::string seen_key;
        RemoteChatModel online(config,
                               [&](const std::string& endpoint,
                                   const std::string& body,
                                   const std::string& key,
                                   std::string& error_out) {
                                   seen_endpoint = endpoint;
                                   seen_key = key;
                                   Json response = Json::object();
                                   response["content"] = "remote-ok";
                                   return response.dump();
                               });
        const Json reply = online.complete(messages, nullptr);
        check(reply["content"] == "remote-ok", "injected exchange round trip");
        check(seen_endpoint == config.endpoint, "exchange hit the endpoint");
        check(seen_key == "test-key-123", "exchange carried the env key");
        ::unsetenv("PWB_CLOSURE_AGENT_TEST_KEY");
    }

    // ---- tool source: schemas + guarded execution ---------------------------
    {
        HarnessExecutor executor(shared_registry());
        HarnessToolSource source(executor, shared_registry());
        const auto schemas = source.tool_schemas();
        check(schemas.size() == 1, "tool schemas derived from the registry");
        check(schemas[0]["function"]["name"] == "geology__factor_stats",
              "tool name mapping . -> __");
        const Json result = source.execute_tool("geology__factor_stats",
                                                Json{{"count", 5}});
        check(result["status"] == "success", "tool executed through the guards");
        check(result["outputs"]["mean"] == 0.452, "tool result payload");
        const Json unknown = source.execute_tool("no__such_tool", Json::object());
        check(unknown["status"] == "rejected", "unknown tool rejected, not thrown");
    }

    return test_exit("closure_agent.model");
}
