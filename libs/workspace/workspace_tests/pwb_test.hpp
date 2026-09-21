// Minimal dependency-free test harness (test-plan.md §0): registration
// macro + assertions + process exit code. One CTest entry per executable;
// no external framework, no network.
#pragma once

#include <functional>
#include <iostream>
#include <string>
#include <vector>

namespace pwb_test {

struct Case {
    std::string name;
    std::function<void()> fn;
};

inline std::vector<Case>& registry() {
    static std::vector<Case> cases;
    return cases;
}

struct Registrar {
    Registrar(const char* name, std::function<void()> fn) {
        registry().push_back({name, std::move(fn)});
    }
};

inline int g_argc = 0;
inline char** g_argv = nullptr;

inline void set_args(int argc, char** argv) {
    g_argc = argc;
    g_argv = argv;
}

inline int& failures() {
    static int count = 0;
    return count;
}

inline std::string& current() {
    static std::string name;
    return name;
}

inline int& case_failures() {
    static int count = 0;
    return count;
}

inline void check(bool condition, const char* expression, const char* file,
                  int line) {
    if (!condition) {
        ++failures();
        ++case_failures();
        std::cout << "  FAIL [" << file << ":" << line << "] " << expression
                  << "\n";
    }
}

inline int run_all() {
    int total = 0;
    for (const auto& test : registry()) {
        current() = test.name;
        case_failures() = 0;
        ++total;
        test.fn();
        std::cout << (case_failures() == 0 ? "PASS " : "FAIL ") << test.name
                  << "\n";
    }
    std::cout << total << " cases, " << failures() << " failures\n";
    return failures() == 0 ? 0 : 1;
}

}  // namespace pwb_test

#define PWB_TEST(name)                                                     \
    static void pwb_test_fn_##name();                                      \
    static ::pwb_test::Registrar pwb_test_reg_##name(                      \
        #name, pwb_test_fn_##name);                                        \
    static void pwb_test_fn_##name()

#define PWB_CHECK(condition) \
    ::pwb_test::check(static_cast<bool>(condition), #condition, __FILE__, __LINE__)
