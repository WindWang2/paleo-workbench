#pragma once

// LLM provider seam — C++ port of paleo_workbench/harness/llm.py (P2-C).
// The harness is model-agnostic by construction: an external agent runtime
// (LLM or otherwise) binds through IChatModel to expose actions and drive
// them. No vendor client lives here; adapters for any vendor implement
// IChatModel where that vendor's client is configured.
//
// Honesty contract: RecordedChatModel deterministically replays recorded
// responses (tests / air-gapped runs). RemoteChatModelConfig names a remote
// endpoint for an out-of-process native transport; this build ships no TLS
// stack, so complete() reports honest unavailability instead of faking an
// online capability.

#include <pwb/domain/json.hpp>

#include <functional>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace pwb::closure_agent {

using Json = pwb::domain::Json;

// Vendor-neutral chat model seam (messages in, tool calls / text out).
// messages: JSON array of {"role","content"} objects (provider-native shapes
// pass through); tools: the registry-derived tool schemas. Returns the raw
// model response envelope as JSON.
class IChatModel {
public:
    virtual ~IChatModel() = default;
    virtual const std::string& model_id() const = 0;
    // Throws std::runtime_error on transport failure (never a fake reply).
    virtual Json complete(const Json& messages, const Json* tools) = 0;
};

// ModelResponseUnavailable — the honest-unavailability error the remote
// adapter raises when no transport can actually serve the request.
class ModelUnavailableError : public std::runtime_error {
public:
    explicit ModelUnavailableError(const std::string& message)
        : std::runtime_error(message) {}
};

struct RemoteChatModelConfig {
    std::string endpoint;      // e.g. "https://api.example.com/v1/chat/completions"
    std::string model;         // vendor model name
    std::string api_key_env;   // env var NAME holding the key (never the key)
};

// Configuration-driven remote adapter. This build has no TLS/network stack:
// complete() raises ModelUnavailableError with the precise reason. When a
// host process provides a native transport (injected callable performing
// the HTTP round trip), this same class performs the real exchange.
using HttpExchange = std::function<std::string(
    const std::string& endpoint, const std::string& request_body,
    const std::string& api_key, std::string& error_out)>;

class RemoteChatModel : public IChatModel {
public:
    RemoteChatModel(RemoteChatModelConfig config, HttpExchange exchange);

    const std::string& model_id() const override { return config_.model; }
    Json complete(const Json& messages, const Json* tools) override;

    // True when a real transport was injected (online-capable build).
    bool has_transport() const { return static_cast<bool>(exchange_); }

private:
    RemoteChatModelConfig config_;
    HttpExchange exchange_;
};

// Deterministic recorded replay: responses are consumed in recorded order;
// each entry is the exact JSON the model "answered". When the script record
// carries "checksum_sha256" (over the canonical dump of the "responses"
// array), the constructor verifies it — a tampered script is refused before
// the first turn. Exhausting the script is a fail-closed error — a session
// can never silently continue on an unmodelled turn.
class RecordedChatModel : public IChatModel {
public:
    // script: {"model_id": "...", "responses": [ {...}, ... ],
    //          "checksum_sha256": "<hex>" (optional)}
    explicit RecordedChatModel(Json script);

    const std::string& model_id() const override { return model_id_; }

    // Returns the next recorded response in recorded order.
    Json complete(const Json& messages, const Json* tools) override;

    std::size_t remaining() const;

private:
    std::string model_id_;
    std::vector<Json> responses_;
    std::size_t cursor_ = 0;
};

}  // namespace pwb::closure_agent
