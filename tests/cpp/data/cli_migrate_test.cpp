// data.cli_migrate — exit-code contract of pwb-migrate (contracts.md §8).
// Usage: cli_migrate --exe <pwb-migrate> .
#include "pwb_test.hpp"

#include <array>
#include <cstdio>
#include <sys/wait.h>
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

PWB_TEST(migrate_arg_parsing) {
    for (int i = 1; i + 1 < ::pwb_test::g_argc; i += 2) {
        if (std::string(::pwb_test::g_argv[i]) == "--exe") {
            g_exe = ::pwb_test::g_argv[i + 1];
        }
    }
    PWB_CHECK(!g_exe.empty());
    std::string output;
    PWB_CHECK(run_capture("", output) == 2);
    PWB_CHECK(run_capture("--input no_such_file.paleo.json", output) == 3);
}

PWB_TEST(migrate_preflight_reports) {
    std::string output;
    const int status =
        run_capture("--check --input \"" +
                        fixture("typical", "typical.paleo.json") + "\"",
                    output);
    // 0 = clean, 1 = migration items found — both are honest preflights.
    PWB_CHECK(status == 0 || status == 1);
    PWB_CHECK(output.find("\"mode\"") != std::string::npos);
    PWB_CHECK(output.find("preflight") != std::string::npos);
}

PWB_TEST(migrate_refuses_input_dir) {
    const fs::path input = fs::path(PWB_DATA_FIXTURE_DIR) / "typical" /
                           "typical.paleo.json";
    std::string output;
    const int status = run_capture(
        "--input \"" + input.generic_string() + "\" --output-dir \"" +
            input.parent_path().generic_string() + "\"",
        output);
    PWB_CHECK(status == 2);
}

PWB_TEST(migrate_converts_copy_to_fresh_dir) {
    const fs::path root =
        fs::temp_directory_path() / "pwb_migrate_cli_test";
    std::error_code ec;
    fs::remove_all(root, ec);
    fs::create_directories(root, ec);
    const fs::path input = root / "typical.paleo.json";
    fs::copy_file(fs::path(PWB_DATA_FIXTURE_DIR) / "typical" /
                      "typical.paleo.json",
                  input, ec);
    PWB_CHECK(!ec);
    const fs::path output = root / "out";
    std::string text;
    const int status =
        run_capture("--input \"" + input.generic_string() +
                        "\" --output-dir \"" + output.generic_string() + "\"",
                    text);
    PWB_CHECK(status == 0);
    PWB_CHECK(fs::is_regular_file(output / "typical.paleo.json"));
    PWB_CHECK(text.find("\"output\"") != std::string::npos);
    fs::remove_all(root, ec);
}
