// data.cli_inspect — exit-code contract of pwb-inspect (contracts.md §8).
// Usage: cli_inspect --exe <pwb-inspect> .
#include "pwb_test.hpp"

#include <array>
#include <cstdio>
#ifndef _WIN32
#include <sys/wait.h>
#endif  // sys/wait.h is POSIX-only (WIFEXITED); the Windows path uses _pclose directly
#include <filesystem>
#include <string>

namespace {

namespace fs = std::filesystem;

std::string g_exe;

int run_capture(const std::string& args, std::string& output) {
#ifdef _WIN32
    // cmd /c strips the outermost quote pair, so wrap the whole command
    // once more when paths contain spaces.
    std::string command = "\"\"" + g_exe + "\" " + args + "\"";
#else
    std::string command = "'" + g_exe + "' " + args;
#endif
    std::array<char, 4096> chunk{};
    output.clear();
#ifdef _WIN32
    FILE* pipe = _popen(command.c_str(), "r");
#else
    FILE* pipe = popen(command.c_str(), "r");
#endif
    if (pipe == nullptr) return -1;
    while (fgets(chunk.data(), static_cast<int>(chunk.size()), pipe) !=
           nullptr) {
        output += chunk.data();
    }
#ifdef _WIN32
    const int status = _pclose(pipe);
#else
    const int raw = pclose(pipe);
    const int status = WIFEXITED(raw) ? WEXITSTATUS(raw) : 128 + raw;
#endif
    return status;
}

std::string fixture(const char* dir, const char* file) {
    return (fs::path(PWB_DATA_FIXTURE_DIR) / dir / file).generic_string();
}

}  // namespace

PWB_TEST(inspect_json_ok) {
    for (int i = 1; i + 1 < ::pwb_test::g_argc; i += 2) {
        if (std::string(::pwb_test::g_argv[i]) == "--exe") {
            g_exe = ::pwb_test::g_argv[i + 1];
        }
    }
    PWB_CHECK(!g_exe.empty());
    std::string output;
    const int status =
        run_capture("--project \"" + fixture("minimal", "minimal.paleo.json") +
                        "\" --format json",
                    output);
    PWB_CHECK(status == 0);
    PWB_CHECK(output.find("\"schema_version\"") != std::string::npos);
}

PWB_TEST(inspect_text_ok) {
    std::string output;
    const int status =
        run_capture("--project \"" + fixture("minimal", "minimal.paleo.json") +
                        "\" --format text",
                    output);
    PWB_CHECK(status == 0);
    PWB_CHECK(output.find("project:") != std::string::npos);
}

PWB_TEST(inspect_missing_project_is_3) {
    std::string output;
    const int status =
        run_capture("--project \"no_such_file.paleo.json\"", output);
    PWB_CHECK(status == 3);
}

PWB_TEST(inspect_usage_is_2) {
    std::string output;
    PWB_CHECK(run_capture("--bogus-flag", output) == 2);
}

PWB_TEST(inspect_future_schema_is_4) {
    std::string output;
    const int status =
        run_capture("--project \"" +
                        fixture("future_schema", "typical.paleo.json") + "\"",
                    output);
    PWB_CHECK(status == 4);
    PWB_CHECK(output.find("future_schema") != std::string::npos);
}
