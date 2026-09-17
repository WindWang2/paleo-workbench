// data.build_hygiene — the data kernel links no Qt/QGIS/Python runtime
// (contracts.md §1, Oracle 1). Runs dumpbin /DEPENDENTS (MSVC) or ldd
// (ELF) over the data executables and fails on any banned dependency.
//
// Usage: data_build_hygiene [--dumpbin <dumpbin.exe>] [--mode dumpbin|elf]
//        <binary...> .
#include "pwb_test.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdio>
#include <string>
#include <vector>

namespace {

std::string run_capture(const std::string& command) {
    std::string output;
    std::array<char, 4096> chunk{};
#ifdef _WIN32
    FILE* pipe = _popen(command.c_str(), "r");
#else
    FILE* pipe = popen(command.c_str(), "r");
#endif
    if (pipe == nullptr) return output;
    while (fgets(chunk.data(), static_cast<int>(chunk.size()), pipe) !=
           nullptr) {
        output += chunk.data();
    }
#ifdef _WIN32
    _pclose(pipe);
#else
    pclose(pipe);
#endif
    return output;
}

std::string lower(std::string text) {
    std::transform(text.begin(), text.end(), text.begin(),
                   [](unsigned char c) {
                       return static_cast<char>(std::tolower(c));
                   });
    return text;
}

const char* kBanned[] = {"python", "pyside", "shiboken", "pybind",
                         "qgis",   "qt6",    "qt5",      "conda"};

}  // namespace

PWB_TEST(no_gui_or_python_runtime_linkage) {
    std::string dumpbin;
    std::string mode = "dumpbin";
    std::vector<std::string> binaries;
    for (int i = 1; i < ::pwb_test::g_argc; ++i) {
        const std::string arg = ::pwb_test::g_argv[i];
        if (arg == "--dumpbin" && i + 1 < ::pwb_test::g_argc) {
            dumpbin = ::pwb_test::g_argv[++i];
        } else if (arg == "--mode" && i + 1 < ::pwb_test::g_argc) {
            mode = ::pwb_test::g_argv[++i];
        } else {
            binaries.push_back(arg);
        }
    }
    PWB_CHECK(!binaries.empty());
    PWB_CHECK(mode == "dumpbin" || mode == "elf");
    if (mode == "dumpbin") {
        PWB_CHECK(!dumpbin.empty());
    }
    for (const auto& binary : binaries) {
        std::string output;
        if (mode == "dumpbin") {
            // cmd /c strips the outermost quote pair, so wrap the whole
            // command once more when paths contain spaces.
            output = lower(run_capture(
                "\"\"" + dumpbin + "\" /DEPENDENTS \"" + binary + "\"\""));
            PWB_CHECK(output.find("dump of file") != std::string::npos);
        } else {
            output = lower(run_capture("ldd \"" + binary + "\""));
            // ldd must actually have run: dynamic binaries list at least
            // the vdso/loader or an "=>" resolution line.
            PWB_CHECK(output.find("=>") != std::string::npos ||
                      output.find("linux-vdso") != std::string::npos ||
                      output.find("statically linked") != std::string::npos);
        }
        for (const char* banned : kBanned) {
            PWB_CHECK(output.find(banned) == std::string::npos);
        }
    }
}
