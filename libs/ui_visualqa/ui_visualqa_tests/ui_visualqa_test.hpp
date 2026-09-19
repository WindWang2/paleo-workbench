#pragma once

// Minimal deterministic test harness for ui_visualqa tests (UI-16).
// Same shape as libs/ui_wellseis/ui_wellseis_tests/ui_wellseis_test.hpp —
// self-registering TEST, counted (not aborting) failures.

#include <cmath>
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

inline void check_eq(const std::string& actual, const std::string& expected,
                     const char* file, int line) {
    if (actual != expected) {
        ++failure_count();
        std::fprintf(stderr, "FAIL %s:%d: expected %s, got %s\n", file, line,
                     expected.c_str(), actual.c_str());
    }
}

inline void check_eq(long long actual, long long expected, const char* file,
                     int line) {
    if (actual != expected) {
        ++failure_count();
        std::fprintf(stderr, "FAIL %s:%d: expected %lld, got %lld\n", file,
                     line, expected, actual);
    }
}

inline void check_near(double actual, double expected, double tolerance,
                       const char* file, int line) {
    if (std::abs(actual - expected) > tolerance) {
        ++failure_count();
        std::fprintf(stderr,
                     "FAIL %s:%d: expected %g (+-%g), got %g\n", file, line,
                     expected, tolerance, actual);
    }
}

inline int run_all() {
    for (const auto& test : registry()) {
        const int before = failure_count();
        test.body();
        if (failure_count() == before) {
            std::fprintf(stderr, "PASS %s\n", test.name.c_str());
        } else {
            std::fprintf(stderr, "FAILED %s\n", test.name.c_str());
        }
    }
    std::fprintf(stderr, "%zu tests, %d failures\n", registry().size(),
                 failure_count());
    return failure_count() == 0 ? 0 : 1;
}

}  // namespace pwb_test

#define PWB_TEST(name) \
    static void test_##name(); \
    static ::pwb_test::Registrar registrar_##name(#name, test_##name); \
    static void test_##name()

#define CHECK(cond) ::pwb_test::check_true(static_cast<bool>(cond), __FILE__, \
                                           __LINE__, #cond)
#define CHECK_EQ(actual, expected) \
    ::pwb_test::check_eq((actual), (expected), __FILE__, __LINE__)
#define CHECK_NEAR(actual, expected, tol) \
    ::pwb_test::check_near((actual), (expected), (tol), __FILE__, __LINE__)
