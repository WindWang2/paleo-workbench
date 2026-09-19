#pragma once

// Minimal deterministic test harness for ui_seqviz tests (UI-10).
// Same shape as libs/ui_seqviz/ui_seqviz_tests/ui_seqviz_test.hpp —
// self-registering TEST, counted (not aborting) failures.

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

inline void check_ll(long long actual, long long expected, const char* file,
                     int line) {
    if (actual != expected) {
        ++failure_count();
        std::fprintf(stderr, "FAIL %s:%d: expected %lld, got %lld\n", file,
                     line, expected, actual);
    }
}

inline void check_double(double actual, double expected, double tol,
                         const char* file, int line) {
    const double diff = actual > expected ? actual - expected
                                          : expected - actual;
    if (diff > tol) {
        ++failure_count();
        std::fprintf(stderr, "FAIL %s:%d: expected %g, got %g\n", file, line,
                     expected, actual);
    }
}

inline int run_all() {
    int passed = 0;
    for (const auto& tc : registry()) {
        const int before = failure_count();
        tc.body();
        if (failure_count() == before) {
            ++passed;
            std::fprintf(stdout, "PASS %s\n", tc.name.c_str());
        } else {
            std::fprintf(stdout, "FAIL %s\n", tc.name.c_str());
        }
    }
    std::fprintf(stdout, "%d/%zu tests passed, %d failures\n", passed,
                 registry().size(), failure_count());
    return failure_count() == 0 ? 0 : 1;
}

}  // namespace pwb_test

#define PWB_TEST(name)                                                   \
    static void test_##name();                                           \
    static ::pwb_test::Registrar registrar_##name(#name, test_##name);   \
    static void test_##name()

#define CHECK(expr) \
    ::pwb_test::check_true(static_cast<bool>(expr), __FILE__, __LINE__, #expr)
#define CHECK_EQ(actual, expected) \
    ::pwb_test::check_eq((actual), (expected), __FILE__, __LINE__)
#define CHECK_LL(actual, expected) \
    ::pwb_test::check_ll((actual), (expected), __FILE__, __LINE__)
#define CHECK_NEAR(actual, expected, tol) \
    ::pwb_test::check_double((actual), (expected), (tol), __FILE__, __LINE__)
