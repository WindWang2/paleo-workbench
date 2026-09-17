#pragma once

// Minimal deterministic test harness for the science suite. One executable
// per test file; tests self-register; a failing check aborts with the file
// and line. Zero external dependencies (network fetch of Catch2/GTest is not
// reliable in this environment); swapping the harness later only touches the
// TEST/PWB_* macros.

#include <cstdio>
#include <cstdlib>
#include <functional>
#include <string>
#include <vector>

namespace pwb_test {

struct TestCase {
    std::string name;
    std::function<void()> body;
};

inline std::vector<TestCase>& registry() {
    static std::vector<TestCase> cases;
    return cases;
}

inline int& failure_count() {
    static int count = 0;
    return count;
}

struct Registrar {
    Registrar(std::string name, std::function<void()> body) {
        registry().push_back(TestCase{std::move(name), std::move(body)});
    }
};

[[noreturn]] inline void fail(const char* file, int line, const std::string& message) {
    ++failure_count();
    std::fprintf(stderr, "FAIL %s:%d: %s\n", file, line, message.c_str());
    std::fflush(stderr);
    std::abort();
}

inline void check_true(bool condition, const char* file, int line,
                       const char* expression) {
    if (!condition) {
        fail(file, line, std::string("expected true: ") + expression);
    }
}

} // namespace pwb_test

#define TEST(name)                                                             \
    static void pwb_test_body_##name();                                        \
    static ::pwb_test::Registrar pwb_test_registrar_##name(#name,              \
                                                           &pwb_test_body_##name); \
    static void pwb_test_body_##name()

#define PWB_CHECK(cond) ::pwb_test::check_true((cond), __FILE__, __LINE__, #cond)
#define PWB_CHECK_MSG(cond, msg)                                               \
    ::pwb_test::check_true((cond), __FILE__, __LINE__, (msg))
#define PWB_FAIL(msg) ::pwb_test::fail(__FILE__, __LINE__, (msg))
