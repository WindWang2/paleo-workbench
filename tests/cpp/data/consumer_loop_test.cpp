// data.consumer_loop — the A-line consumption example runs the full
// production loop (open → base version → staged edit → run register →
// publish → close/reopen) against a real fixture copy, twice in a row;
// pwb-inspect --recover on the healthy project reports nothing pending.
//
// args: --loop <pwb-data-loop> --inspect <pwb-inspect>
#include "pwb_test.hpp"

#include "pwb/catalog/repository.hpp"
#include "pwb/data/run_contracts.hpp"
#include "pwb/domain/json.hpp"
#include "pwb/project/manager.hpp"

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#if !defined(_WIN32)
#include <unistd.h>
#endif

namespace {

namespace fs = std::filesystem;
using pwb::domain::Json;

std::string arg_value(const char* flag) {
    for (int i = 1; i < pwb_test::g_argc - 1; ++i) {
        if (pwb_test::g_argv[i] == std::string(flag)) {
            return pwb_test::g_argv[i + 1];
        }
    }
    return "";
}

int run_capture(const std::string& command, std::string* out) {
    const fs::path out_file = fs::temp_directory_path() /
        ("pwb_consumer_" + std::to_string(::getpid()) + ".txt");
    const std::string full = command + " >'" + out_file.string() + "' 2>&1";
    const int code = std::system(full.c_str());
    if (out != nullptr) {
        std::ifstream stream(out_file, std::ios::binary);
        std::ostringstream buffer;
        buffer << stream.rdbuf();
        *out = buffer.str();
    }
    std::error_code ec;
    fs::remove(out_file, ec);
    return code;
}

}  // namespace

PWB_TEST(consumer_example_full_loop_twice) {
    const std::string loop = arg_value("--loop");
    const std::string inspect = arg_value("--inspect");
    PWB_CHECK(!loop.empty());
    PWB_CHECK(!inspect.empty());

    const fs::path root = fs::temp_directory_path() / "pwb_consumer_loop";
    std::error_code ec;
    fs::remove_all(root, ec);
    fs::copy(fs::path(PWB_DATA_FIXTURE_DIR) / "typical", root,
             fs::copy_options::recursive | fs::copy_options::overwrite_existing,
             ec);
    const fs::path project = root / "typical.paleo.json";

    for (int round = 1; round <= 2; ++round) {
        std::string out;
        const int code =
            run_capture("'" + loop + "' '" + project.string() + "'", &out);
        if (code != 0) {
            std::cout << "round " << round << " output: " << out << "\n";
        }
        PWB_CHECK(code == 0);
        Json summary = Json::parse(out, nullptr, false);
        PWB_CHECK(!summary.is_discarded());
        if (summary.is_discarded()) return;  // value() would throw below
        PWB_CHECK(summary.value("run_status", "") == "complete");
        PWB_CHECK(!summary.value("edit_version_id", "").empty());
        PWB_CHECK(!summary.value("result_version_id", "").empty());
        PWB_CHECK(!summary.value("result_asset_id", "").empty());
        PWB_CHECK(!summary.value("result_sha256", "").empty());
    }

    // Two rounds → two edit versions + two result versions/assets/runs.
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project));
    auto document = repository.open_read_only();
    PWB_CHECK(document.is_ok());
    PWB_CHECK(document.value().versions.size() == 9);  // 5 fixture + 2×2
    PWB_CHECK(document.value().assets.size() == 4);    // 2 fixture + 2×new
    PWB_CHECK(document.value().runs.size() == 5);      // 1 fixture + 2×(edit+algo)
    for (const auto& run : document.value().runs) {
        if (run.operation == "demo.consumer_loop") {
            PWB_CHECK(run.status == pwb::data::kRunStatusComplete);
            PWB_CHECK(run.output_version_ids.size() == 1);
        }
        if (run.operation == "manual_edit") {
            PWB_CHECK(run.output_version_ids.size() == 1);  // the edit version
        }
    }

    // Healthy project: recovery is a no-op with nothing pending.
    std::string out;
    const int recover_code = run_capture(
        "'" + inspect + "' --project '" + project.string() + "' --recover",
        &out);
    PWB_CHECK(recover_code == 0);
    Json report = Json::parse(out, nullptr, false);
    PWB_CHECK(!report.is_discarded());
    PWB_CHECK(report.value("pending", std::vector<std::string>{}).empty());

    fs::remove_all(root, ec);
}
