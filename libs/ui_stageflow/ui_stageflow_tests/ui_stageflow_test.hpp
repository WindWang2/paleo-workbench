#pragma once

// Minimal deterministic test harness (V14-THREE-STAGE-UX) — same shape as
// libs/ui_workstation/ui_workstation_tests/ui_workstation_test.hpp.

#include <cstdio>
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

inline void check_true(bool condition, const char* file, int line,
                       const char* expression) {
    if (!condition) {
        ++failure_count();
        std::fprintf(stderr, "FAIL %s:%d: expected true: %s\n", file, line,
                     expression);
    }
}

inline void check_msg(bool condition, const char* file, int line,
                      const char* message) {
    if (!condition) {
        ++failure_count();
        std::fprintf(stderr, "FAIL %s:%d: %s\n", file, line, message);
    }
}

inline int run_all(const char* suite_name) {
    for (const auto& test : registry()) {
        const int before = failure_count();
        test.body();
        if (failure_count() == before) {
            std::fprintf(stderr, "PASS %s\n", test.name.c_str());
        } else {
            std::fprintf(stderr, "FAILED %s\n", test.name.c_str());
        }
    }
    std::fprintf(stderr, "[%s] %zu tests, %d failures\n", suite_name,
                 registry().size(), failure_count());
    return failure_count() == 0 ? 0 : 1;
}

}  // namespace pwb_test

#define PWB_TEST(name) \
    static void test_##name(); \
    static ::pwb_test::Registrar registrar_##name(#name, test_##name); \
    static void test_##name()

#define CHECK(cond) \
    ::pwb_test::check_true(static_cast<bool>(cond), __FILE__, __LINE__, #cond)
#define CHECK_MSG(cond, msg) \
    ::pwb_test::check_msg(static_cast<bool>(cond), __FILE__, __LINE__, msg)
