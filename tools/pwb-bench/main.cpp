// pwb-bench — native benchmark harness (cpp-close wave line 14).
//
// Qt-free measurement tool: each scenario returns a JSON report with raw
// per-sample ms, median/p95, peak RSS, /proc/self/io deltas, and a global
// heap-allocation counter (bench binary only). Fixed conditions are part of
// the report (build type, compiler, thread env, machine) so ledger entries
// stay replayable.
//
//   pwb-bench --list
//   pwb-bench tiled --shape 96,256,256 --samples 5 --work bench-out/tiled
//   pwb-bench all --samples 5            # every scenario, one report
//
// Cold vs warm cache: sample 1 is reported separately (`first_ms`) as the
// cold-ish signal; the OS page cache cannot be dropped without privileges,
// so "cold" here means first touch within this process, not a dropped
// system cache. Documented as a limitation in the ledger.
#include "bench_common.hpp"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sys/utsname.h>
#include <unistd.h>
#include <vector>

namespace pwb::bench {

void register_tiled_scenarios(ScenarioMap&);
void register_catalog_scenarios(ScenarioMap&);
void register_seismic_scenarios(ScenarioMap&);
void register_project_scenarios(ScenarioMap&);

namespace {

Json environment_block() {
    Json env = Json::object();
    struct utsname uts {};
    if (::uname(&uts) == 0) {
        env["sysname"] = uts.sysname;
        env["release"] = uts.release;
        env["machine"] = uts.machine;
        env["nodename"] = uts.nodename;
    }
    env["cpu_count"] =
        static_cast<long>(::sysconf(_SC_NPROCESSORS_ONLN));
    env["cxx_compiler"] =
#if defined(__clang__)
        "clang " + std::to_string(__clang_major__) + "."
        + std::to_string(__clang_minor__);
#elif defined(__GNUC__)
        "gcc " + std::to_string(__GNUC__) + "."
        + std::to_string(__GNUC_MINOR__);
#else
        "unknown";
#endif
#ifdef NDEBUG
    env["build_flavor"] = "ndebug";
#else
    env["build_flavor"] = "debug";
#endif
    for (const char* var :
         {"OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
          "CMAKE_BUILD_PARALLEL_LEVEL", "CTEST_PARALLEL_LEVEL"}) {
        const char* v = std::getenv(var);
        env["thread_env"][var] = v != nullptr ? v : "";
    }
    env["pid"] = static_cast<long>(::getpid());
    return env;
}

int usage() {
    std::cerr << "usage: pwb-bench --list\n"
                 "       pwb-bench <scenario[,scenario...]|all> "
                 "[--samples N] [--work DIR] [--out FILE] [scenario args]\n";
    return 64;
}

}  // namespace
}  // namespace pwb::bench

int main(int argc, char** argv) {
    using namespace pwb::bench;
    const Args args = parse_args(argc, argv);

    ScenarioMap scenarios;
    register_tiled_scenarios(scenarios);
    register_catalog_scenarios(scenarios);
    register_seismic_scenarios(scenarios);
    register_project_scenarios(scenarios);

    if (args.has("list")) {
        for (const auto& [name, fn] : scenarios) {
            std::cout << name << "\n";
        }
        return 0;
    }
    if (args.positional.empty()) {
        return usage();
    }

    // Resolve the requested set (comma-separated names or "all").
    std::vector<std::string> wanted;
    for (const std::string& token : args.positional) {
        std::size_t pos = 0;
        while (pos <= token.size()) {
            const std::size_t comma = token.find(',', pos);
            wanted.push_back(token.substr(
                pos, comma == std::string::npos ? std::string::npos
                                                : comma - pos));
            if (comma == std::string::npos) break;
            pos = comma + 1;
        }
    }
    if (wanted.size() == 1 && wanted[0] == "all") {
        wanted.clear();
        for (const auto& [name, fn] : scenarios) wanted.push_back(name);
        std::sort(wanted.begin(), wanted.end());
    }

    Json report = Json::object();
    report["tool"] = "pwb-bench";
    report["format_version"] = 1;
    report["environment"] = environment_block();
    report["scenarios"] = Json::object();

    int rc = 0;
    for (const std::string& name : wanted) {
        const auto it = scenarios.find(name);
        if (it == scenarios.end()) {
            std::cerr << "pwb-bench: unknown scenario '" << name << "'\n";
            rc = 64;
            continue;
        }
        try {
            report["scenarios"][name] = it->second(args);
        } catch (const std::exception& e) {
            std::cerr << "pwb-bench: scenario '" << name
                      << "' failed: " << e.what() << "\n";
            report["scenarios"][name]["error"] = e.what();
            rc = 1;
        }
    }

    const std::string text = report.dump(2) + "\n";
    const std::string out_path = args.get("out");
    if (out_path.empty()) {
        std::cout << text;
    } else {
        std::error_code ec;
        std::filesystem::create_directories(
            std::filesystem::path(out_path).parent_path(), ec);
        std::ofstream out(out_path, std::ios::trunc);
        out << text;
    }
    return rc;
}
