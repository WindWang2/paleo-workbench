#pragma once

// Minimal deterministic test harness for ui_pages_mapedit tests (UI-08).
// Same shape as libs/ui_map/ui_map_tests/ui_map_test.hpp —
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
    if (std::fabs(actual - expected) > tolerance) {
        ++failure_count();
        std::fprintf(stderr, "FAIL %s:%d: expected %g (±%g), got %g\n", file,
                     line, expected, tolerance, actual);
    }
}

}  // namespace pwb_test

#define PWB_TEST(name)                                                      \
    static void pwb_test_##name();                                          \
    static ::pwb_test::Registrar pwb_reg_##name(#name, pwb_test_##name);    \
    static void pwb_test_##name()

#define PWB_CHECK(expr) \
    ::pwb_test::check_true(static_cast<bool>(expr), __FILE__, __LINE__, #expr)

#define PWB_CHECK_EQ(actual, expected) \
    ::pwb_test::check_eq((actual), (expected), __FILE__, __LINE__)

#define PWB_CHECK_NEAR(actual, expected, tol) \
    ::pwb_test::check_near((actual), (expected), (tol), __FILE__, __LINE__)

#define PWB_TEST_MAIN()                                                   \
    int main() {                                                          \
        for (const auto& test : ::pwb_test::registry()) {                 \
            test.body();                                                  \
        }                                                                 \
        if (::pwb_test::failure_count() != 0) {                           \
            std::fprintf(stderr, "%d check(s) failed\n",                  \
                         ::pwb_test::failure_count());                    \
            return 1;                                                     \
        }                                                                 \
        std::printf("%zu test(s) passed\n",                               \
                    ::pwb_test::registry().size());                       \
        return 0;                                                         \
    }

#define PWB_TEST_MAIN_QAPP()                                              \
    int main(int argc, char** argv) {                                     \
        QApplication app(argc, argv);                                     \
        for (const auto& test : ::pwb_test::registry()) {                 \
            test.body();                                                  \
        }                                                                 \
        if (::pwb_test::failure_count() != 0) {                           \
            std::fprintf(stderr, "%d check(s) failed\n",                  \
                         ::pwb_test::failure_count());                    \
            return 1;                                                     \
        }                                                                 \
        std::printf("%zu test(s) passed\n",                               \
                    ::pwb_test::registry().size());                       \
        return 0;                                                         \
    }
