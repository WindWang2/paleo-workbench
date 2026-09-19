// closure_agent.checkpoint — atomic persistence + integrity envelope:
// roundtrip, corruption refusal, missing-session refusal, atomic tmp cleanup.
#include "test_util.hpp"

#include <pwb/closure_agent/checkpoint.hpp>

#include <filesystem>
#include <fstream>

using namespace pwb::closure_agent;

namespace {

std::filesystem::path dir(const std::string& name) {
    return std::filesystem::temp_directory_path() /
           ("closure-agent-checkpoint-test-" + name);
}

std::string read_file(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary);
    return std::string((std::istreambuf_iterator<char>(in)),
                       std::istreambuf_iterator<char>());
}

}  // namespace

int main() {
    // Roundtrip.
    {
        const std::filesystem::path root = dir("roundtrip");
        std::error_code ec;
        std::filesystem::remove_all(root, ec);
        SessionCheckpointStore store(root);
        Json payload = Json::object();
        payload["state"] = "running";
        payload["plan_nodes"] = std::vector<std::string>{"a", "b"};
        const CheckpointRecord record = store.save("session-a", payload);
        check(!record.checkpoint_id.empty(), "checkpoint id assigned");
        check(record.checksum_sha256.size() == 64, "sha256 hex checksum");
        const CheckpointRecord loaded = store.load("session-a");
        check(loaded.payload == payload, "payload roundtrip");
        check(loaded.checkpoint_id == record.checkpoint_id, "id roundtrip");
        // Newest write wins (single file per session).
        Json second = Json::object();
        second["state"] = "completed";
        store.save("session-a", second);
        check(store.load("session-a").payload == second, "newest checkpoint wins");
        std::filesystem::remove_all(root, ec);
    }

    // Corruption refusal: parse error.
    {
        const std::filesystem::path root = dir("corrupt-parse");
        std::error_code ec;
        std::filesystem::remove_all(root, ec);
        SessionCheckpointStore store(root);
        store.save("session-a", Json::object());
        const std::filesystem::path path = root / "session-a.json";
        std::ofstream out(path, std::ios::binary | std::ios::trunc);
        out << "{not json";
        out.close();
        const std::string message =
            expect_throw([&] { store.load("session-a"); });
        check(message.find("checkpoint is corrupted") == 0,
              "unparseable checkpoint refused: " + message);
        std::filesystem::remove_all(root, ec);
    }

    // Corruption refusal: checksum mismatch (tampered payload).
    {
        const std::filesystem::path root = dir("corrupt-checksum");
        std::error_code ec;
        std::filesystem::remove_all(root, ec);
        SessionCheckpointStore store(root);
        Json payload = Json::object();
        payload["state"] = "running";
        payload["marker"] = "executed";
        store.save("session-a", payload);
        const std::filesystem::path path = root / "session-a.json";
        std::string body = read_file(path);
        const auto pos = body.find("executed");
        check(pos != std::string::npos, "tamper target present");
        if (pos != std::string::npos) body[pos] = 'X';
        std::ofstream out(path, std::ios::binary | std::ios::trunc);
        out.write(body.data(), static_cast<std::streamsize>(body.size()));
        out.close();
        const std::string message =
            expect_throw([&] { store.load("session-a"); });
        check(message.find("checksum mismatch") != std::string::npos,
              "tampered payload refused: " + message);
        std::filesystem::remove_all(root, ec);
    }

    // Missing session + atomic tmp cleanup.
    {
        const std::filesystem::path root = dir("missing");
        std::error_code ec;
        std::filesystem::remove_all(root, ec);
        SessionCheckpointStore store(root);
        const std::string message = expect_throw([&] { store.load("ghost"); });
        check(message.find("no checkpoint for session ghost") != std::string::npos,
              "missing session refused");
        store.save("session-a", Json::object());
        bool tmp_left = false;
        for (const auto& entry : std::filesystem::directory_iterator(root)) {
            if (entry.path().filename().string().find(".tmp-") !=
                std::string::npos) {
                tmp_left = true;
            }
        }
        check(!tmp_left, "atomic write leaves no tmp files");
        std::filesystem::remove_all(root, ec);
    }

    return test_exit("closure_agent.checkpoint");
}
