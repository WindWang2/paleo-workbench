// data.oracle_readback — the C++ kernel writes an isolated project copy
// (edit commit + run registration + publish), then the FIXED Python
// oracle reopens it READ-ONLY and verifies every new row with the legacy
// stack (pydantic project + mode=ro sqlite). The copy's hashes before and
// after the Python read must be identical; the original fixture directory
// is never touched.
//
// args: --loop <pwb-data-loop> --python <python3> --readback <readback_v3.py>
//       --inspect <pwb-inspect>
#include "pwb_test.hpp"

#include "pwb/domain/json.hpp"
#include "pwb/domain/sha256.hpp"

#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <sys/types.h>
#include <vector>
#if !defined(_WIN32)
#include <unistd.h>
#endif

namespace {

namespace fs = std::filesystem;
using pwb::domain::Json;

struct Args {
    std::string loop;
    std::string python;
    std::string readback;
    std::string inspect;
};

Args parse_args() {
    Args args;
    for (int i = 1; i < pwb_test::g_argc; ++i) {
        const std::string flag = pwb_test::g_argv[i];
        if (flag == "--loop" && i + 1 < pwb_test::g_argc) {
            args.loop = pwb_test::g_argv[++i];
        } else if (flag == "--python" && i + 1 < pwb_test::g_argc) {
            args.python = pwb_test::g_argv[++i];
        } else if (flag == "--readback" && i + 1 < pwb_test::g_argc) {
            args.readback = pwb_test::g_argv[++i];
        } else if (flag == "--inspect" && i + 1 < pwb_test::g_argc) {
            args.inspect = pwb_test::g_argv[++i];
        }
    }
    return args;
}

// Captured process output.
struct RunResult {
    int code = -1;
    std::string out;
    std::string err;
};

std::string quote(const std::string& value) {
    return "'" + value + "'";
}

RunResult run_command(const std::string& command) {
    RunResult result;
#if defined(_WIN32)
    const long pid = _getpid();
#else
    const long pid = static_cast<long>(::getpid());
#endif
    const std::string out_file = (std::filesystem::temp_directory_path() /
                                  ("pwb_readback_out_" +
                                   std::to_string(pid) + ".txt"))
                                     .string();
    const std::string err_file = (std::filesystem::temp_directory_path() /
                                  ("pwb_readback_err_" +
                                   std::to_string(pid) + ".txt"))
                                     .string();
    const std::string full =
        command + " >" + quote(out_file) + " 2>" + quote(err_file);
    result.code = std::system(full.c_str());
    auto read = [](const std::string& path) {
        std::ifstream stream(path, std::ios::binary);
        std::ostringstream buffer;
        buffer << stream.rdbuf();
        return buffer.str();
    };
    result.out = read(out_file);
    result.err = read(err_file);
    std::error_code ec;
    fs::remove(out_file, ec);
    fs::remove(err_file, ec);
    return result;
}

// Stable directory digest: relative path + sha256 of every file, sorted.
std::string tree_digest(const fs::path& root) {
    std::vector<std::pair<std::string, std::string>> entries;
    std::error_code ec;
    for (fs::recursive_directory_iterator it(root, ec), end; it != end;
         it.increment(ec)) {
        if (!it->is_regular_file(ec)) continue;
        const auto digest = pwb::domain::Sha256::of_file(it->path());
        entries.emplace_back(
            fs::relative(it->path(), root, ec).generic_string(),
            digest.value_or("unreadable"));
    }
    std::sort(entries.begin(), entries.end());
    std::ostringstream lines;
    for (const auto& [path, hash] : entries) {
        lines << path << ':' << hash << '\n';
    }
    pwb::domain::Sha256 total;
    total.update(lines.str());
    return total.hex_digest();
}

}  // namespace

PWB_TEST(python_oracle_readback_verifies_cpp_writes) {
    const Args args = parse_args();
    PWB_CHECK(!args.loop.empty());
    PWB_CHECK(!args.python.empty());
    PWB_CHECK(!args.readback.empty());
    PWB_CHECK(!args.inspect.empty());

    // Isolated copy of the real fixture.
    const fs::path root =
        fs::temp_directory_path() / "pwb_oracle_readback";
    std::error_code ec;
    fs::remove_all(root, ec);
    fs::copy(fs::path(PWB_DATA_FIXTURE_DIR) / "typical", root,
             fs::copy_options::recursive |
                 fs::copy_options::overwrite_existing, ec);
    const fs::path project = root / "typical.paleo.json";
    const fs::path fixture_source = fs::path(PWB_DATA_FIXTURE_DIR) / "typical";
    const std::string fixture_before = tree_digest(fixture_source);

    // 1. The C++ kernel performs the writes (production example path).
    const RunResult looped =
        run_command(quote(args.loop) + " " + quote(project.string()));
    PWB_CHECK(looped.code == 0);
    Json summary = Json::parse(looped.out, nullptr, false);
    PWB_CHECK(!summary.is_discarded());
    if (summary.is_discarded()) return;  // value() would throw below
    PWB_CHECK(summary.contains("base_version_id"));
    PWB_CHECK(summary.contains("edit_version_id"));
    PWB_CHECK(summary.contains("result_version_id"));
    PWB_CHECK(summary.contains("result_asset_id"));
    PWB_CHECK(summary.contains("run_id"));
    PWB_CHECK(summary.contains("result_sha256"));
    PWB_CHECK(summary.value("run_status", "") == "complete");

    // 2. Read-only CLI queries work over the written project and DO NOT
    //    mutate anything (digest must not move).
    const std::string before_python = tree_digest(root);
    const std::string run_id = summary.value("run_id", "");
    const std::string result_version = summary.value("result_version_id", "");
    const RunResult run_query =
        run_command(quote(args.inspect) + " --project " +
                    quote(project.string()) + " --run " + quote(run_id));
    PWB_CHECK(run_query.code == 0);
    Json run_json = Json::parse(run_query.out, nullptr, false);
    PWB_CHECK(!run_json.is_discarded());
    if (run_json.is_discarded()) return;
    PWB_CHECK(run_json.value("status", "") == "complete");
    const RunResult provenance_query =
        run_command(quote(args.inspect) + " --project " +
                    quote(project.string()) + " --provenance " +
                    quote(result_version));
    PWB_CHECK(provenance_query.code == 0);
    Json provenance = Json::parse(provenance_query.out, nullptr, false);
    PWB_CHECK(!provenance.is_discarded());
    if (provenance.is_discarded()) return;
    PWB_CHECK(provenance.contains("file"));
    PWB_CHECK(provenance["file"].value("exists", false));
    PWB_CHECK(provenance["file"].value("sha256_measured", "") ==
              summary.value("result_sha256", ""));
    PWB_CHECK(provenance.contains("run"));
    PWB_CHECK(provenance["run"].value("operation", "") ==
              "demo.consumer_loop");
    PWB_CHECK(tree_digest(root) == before_python);

    // 3. The fixed Python oracle reopens READ-ONLY and verifies the rows.
    const RunResult readback = run_command(
        quote(args.python) + " " + quote(args.readback) +
        " --project " + quote(project.string()) +
        " --base-version " + quote(summary.value("base_version_id", "")) +
        " --edit-version " + quote(summary.value("edit_version_id", "")) +
        " --result-asset " + quote(summary.value("result_asset_id", "")) +
        " --result-version " + quote(result_version) +
        " --run-id " + quote(run_id) +
        " --result-sha256 " + quote(summary.value("result_sha256", "")) +
        " --layer-id " + quote(summary.value("layer_id", "")) +
        " --edit-run-id " + quote(summary.value("edit_run_id", "")));
    if (readback.code != 0) {
        std::cout << "readback stderr: " << readback.err << "\n";
        std::cout << "readback stdout: " << readback.out << "\n";
    }
    PWB_CHECK(readback.code == 0);
    Json verdict = Json::parse(readback.out, nullptr, false);
    PWB_CHECK(!verdict.is_discarded());
    if (verdict.is_discarded()) return;
    PWB_CHECK(verdict.value("ok", false));

    // 4. The Python read wrote NOTHING: identical tree digest.
    PWB_CHECK(tree_digest(root) == before_python);

    // 5. The original fixture directory is untouched.
    PWB_CHECK(tree_digest(fixture_source) == fixture_before);

    fs::remove_all(root, ec);
}
