// model_transport.cpp — RemoteChatModel + RecordedChatModel implementations.
#include <pwb/closure_agent/model_transport.hpp>

#include <pwb/domain/sha256.hpp>

#include <cstdlib>

namespace pwb::closure_agent {

// ------------------------------------------------------- RemoteChatModel --
RemoteChatModel::RemoteChatModel(RemoteChatModelConfig config,
                                 HttpExchange exchange)
    : config_(std::move(config)), exchange_(std::move(exchange)) {}

Json RemoteChatModel::complete(const Json& messages, const Json* tools) {
    if (!has_transport()) {
        // Honest unavailability: no TLS/network stack in this build, no
        // faked replies. The session surfaces this as action status
        // "unavailable"; configure a native transport to enable the online
        // path.
        throw ModelUnavailableError(
            "remote chat model '" + config_.model +
            "' has no native transport in this build (no TLS/network stack); "
            "inject an HttpExchange at construction to enable it — recorded "
            "replay remains the verified offline path");
    }
    const char* key = config_.api_key_env.empty()
                          ? nullptr
                          : std::getenv(config_.api_key_env.c_str());
    if (key == nullptr || std::string(key).empty()) {
        throw ModelUnavailableError(
            "remote chat model '" + config_.model + "' has no API key: set " +
            (config_.api_key_env.empty() ? "<api_key_env>"
                                         : config_.api_key_env));
    }
    Json request = Json::object();
    request["model"] = config_.model;
    request["messages"] = messages;
    if (tools != nullptr) request["tools"] = *tools;
    std::string error_out;
    const std::string response = exchange_(config_.endpoint, request.dump(),
                                           key, error_out);
    if (!error_out.empty()) {
        throw ModelUnavailableError("remote chat model exchange failed: " +
                                    error_out);
    }
    try {
        return Json::parse(response);
    } catch (const std::exception& exc) {
        throw ModelUnavailableError(std::string("remote reply is not JSON: ") +
                                    exc.what());
    }
}

// ------------------------------------------------------ RecordedChatModel --
RecordedChatModel::RecordedChatModel(Json script) {
    if (!script.is_object() || !script.contains("responses") ||
        !script["responses"].is_array()) {
        throw std::runtime_error(
            "recorded chat script must be an object with a responses array");
    }
    // Integrity gate: a declared checksum over the recorded responses is
    // verified at construction — a tampered script never replays.
    const auto checksum = script.find("checksum_sha256");
    if (checksum != script.end() && !checksum->is_null()) {
        if (!checksum->is_string()) {
            throw std::runtime_error(
                "recorded chat script checksum_sha256 must be a hex string");
        }
        pwb::domain::Sha256 digest;
        const std::string canonical = script["responses"].dump();
        digest.update(canonical.data(), canonical.size());
        if (digest.hex_digest() != checksum->get<std::string>()) {
            throw std::runtime_error(
                "recorded chat script checksum mismatch (tampered or stale "
                "record): expected " + checksum->get<std::string>());
        }
    }
    const auto id = script.find("model_id");
    model_id_ = id != script.end() && id->is_string()
                    ? id->get<std::string>()
                    : std::string("recorded");
    for (const auto& response : script["responses"]) {
        responses_.push_back(response);
    }
}

Json RecordedChatModel::complete(const Json& messages, const Json* tools) {
    (void)messages;
    (void)tools;
    if (cursor_ >= responses_.size()) {
        // Fail-closed: the script did not model this turn.
        throw ModelUnavailableError(
            "recorded chat script for '" + model_id_ + "' exhausted at turn " +
            std::to_string(cursor_));
    }
    return responses_[cursor_++];
}

std::size_t RecordedChatModel::remaining() const {
    return responses_.size() - cursor_;
}

}  // namespace pwb::closure_agent
