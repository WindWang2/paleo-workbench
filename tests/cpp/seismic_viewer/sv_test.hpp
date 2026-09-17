#pragma once

// Minimal deterministic test harness for the seismic_viewer suite (same
// zero-dependency pattern as the science suite's pwb_test.hpp; kept local so
// this test tree stays independently consumable).

#include <cstdio>
#include <cstdlib>
#include <functional>
#include <string>
#include <vector>

namespace sv_test {

struct TestCase {
    std::string name;
    std::function<void()> body;
};

inline std::vector<TestCase>& registry() {
    static std::vector<TestCase> cases;
    return cases;
}

inline void fail(const char* file, int line, const std::string& message) {
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

struct Registrar {
    Registrar(std::string name, std::function<void()> body) {
        registry().push_back(TestCase{std::move(name), std::move(body)});
    }
};

} // namespace sv_test

#define TEST(name)                                                              \
    static void sv_test_body_##name();                                          \
    static ::sv_test::Registrar sv_test_registrar_##name(#name,                 \
                                                         &sv_test_body_##name); \
    static void sv_test_body_##name()

#define PWB_CHECK(cond) ::sv_test::check_true((cond), __FILE__, __LINE__, #cond)
#define PWB_CHECK_MSG(cond, msg) ::sv_test::check_true((cond), __FILE__, __LINE__, (msg))
#define PWB_FAIL(msg) ::sv_test::fail(__FILE__, __LINE__, (msg))
