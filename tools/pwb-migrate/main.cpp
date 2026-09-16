// pwb-migrate — preflight-first migration tool.
//
// Default: preflight (dry-run report). An actual conversion REQUIRES
// --input (a COPY of the project) and --output-dir (never equal to the
// input directory, never an existing real project — the original is never
// touched in place).
//
// Exit codes (contracts.md §8): 0 ok / 1 migration items found (preflight)
// / 2 usage / 3 IO-corrupt / 4 future schema / 5 internal.
#include "pwb/data/contracts.hpp"
#include "pwb/data/facade.hpp"
#include "pwb/domain/diagnostics.hpp"
#include "pwb/project/manager.hpp"
#include "pwb/workspace/state.hpp"

#include <filesystem>
#include <iostream>
#include <string>

namespace {

namespace fs = std::filesystem;

int usage() {
    std::cerr << "usage: pwb-migrate --input <copy.paleo.json> "
                 "[--output-dir <dir>]\n"
                 "       pwb-migrate --check --input <project.paleo.json>\n"
                 "       (no --output-dir: preflight/dry-run only)\n";
    return 2;
}

}  // namespace

int main(int argc, char** argv) {
    std::string input_arg;
    std::string output_arg;
    bool preflight = true;
    for (int i = 1; i < argc; ++i) {
        const std::string flag = argv[i];
        if (flag == "--input" && i + 1 < argc) {
            input_arg = argv[++i];
        } else if (flag == "--output-dir" && i + 1 < argc) {
            output_arg = argv[++i];
        } else if (flag == "--check") {
            preflight = true;
        } else {
            return usage();
        }
    }
    if (input_arg.empty()) return usage();
    const fs::path input(input_arg);
    if (!fs::is_regular_file(input)) {
        std::cerr << "pwb-migrate: input project not found: " << input_arg
                  << "\n";
        return 3;
    }
    pwb::data::DataFacade facade(input);
    auto snapshot = facade.open_snapshot();
    if (!snapshot.is_ok()) {
        std::cerr << "pwb-migrate: " << snapshot.error().message << "\n";
        return 3;
    }

    pwb::domain::Json report = pwb::domain::Json::object();
    report["input"] = input.generic_string();
    report["mode"] = output_arg.empty() ? "preflight" : "convert";
    report["schema_version"] = snapshot.value().schema_version;
    pwb::domain::Json items = pwb::domain::Json::array();
    int blocking = 0;
    for (const auto& diagnostic : snapshot.value().diagnostics) {
        items.push_back(diagnostic.to_json());
        if (diagnostic.severity ==
            pwb::domain::Diagnostic::Severity::Error) {
            ++blocking;
        }
    }
    report["items"] = std::move(items);
    report["blocking"] = blocking;

    if (output_arg.empty()) {
        std::cout << report.dump(2) << "\n";
        if (snapshot.value().read_only) return 4;
        // Preflight "1" means: items found that a conversion would address
        // (unknown sections, missing resources, findings …).
        return items.empty() ? 0 : 1;
    }

    // ---- actual conversion: copy-in/copy-out only ------------------------
    const fs::path output_dir(output_arg);
    std::error_code ec;
    const fs::path input_abs = fs::weakly_canonical(input, ec);
    const fs::path output_abs =
        fs::weakly_canonical(output_dir, ec).empty()
            ? fs::absolute(output_dir)
            : fs::weakly_canonical(output_dir, ec);
    if (output_abs == input_abs.parent_path()) {
        std::cerr << "pwb-migrate: refusing to write into the input's own "
                     "directory (would overwrite the source copy)\n";
        return 2;
    }
    if (fs::is_regular_file(output_abs /
                            (input_abs.filename().generic_string()))) {
        std::cerr << "pwb-migrate: target project already exists: "
                  << (output_abs / input_abs.filename()).generic_string()
                  << "\n";
        return 2;
    }
    if (snapshot.value().read_only) {
        std::cerr << "pwb-migrate: future schema — conversion refused\n";
        return 4;
    }
    fs::create_directories(output_abs, ec);
    if (ec) {
        std::cerr << "pwb-migrate: cannot create output dir: "
                  << ec.message() << "\n";
        return 3;
    }
    // Backup the INPUT copy before any rewrite (never the original asset:
    // the contract requires --input to already be a copy).
    const fs::path backup =
        input_abs.parent_path() /
        (input_abs.filename().generic_string() + ".migrate-bak");
    fs::copy_file(input_abs, backup, fs::copy_options::overwrite_existing,
                  ec);
    if (ec) {
        std::cerr << "pwb-migrate: backup failed: " << ec.message() << "\n";
        return 3;
    }
    // Round-trip through the C++ writer (normalizes path sections to
    // portable form + materializes defaults) into the output dir.
    pwb::project::ProjectManager manager(input_abs);
    auto loaded = manager.load();
    if (!loaded.is_ok()) {
        std::cerr << "pwb-migrate: load failed: "
                  << loaded.error().message << "\n";
        return 3;
    }
    auto saved = manager.save(loaded.value().document);
    if (!saved.is_ok()) {
        std::cerr << "pwb-migrate: save failed: " << saved.error().message
                  << "\n";
        return 3;
    }
    const fs::path out_project =
        output_abs / input_abs.filename().generic_string();
    fs::copy_file(input_abs, out_project, ec);
    if (ec) {
        std::cerr << "pwb-migrate: output copy failed: " << ec.message()
                  << "\n";
        return 3;
    }
    report["output"] = out_project.generic_string();
    report["backup"] = backup.generic_string();
    std::cout << report.dump(2) << "\n";
    return 0;
}
