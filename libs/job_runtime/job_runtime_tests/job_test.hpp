#pragma once

// Minimal deterministic test harness for the job runtime (CONV-30).
// Same shape as tests/cpp/science/pwb_test.hpp (self-registering TEST,
// zero external dependencies) but with counted — not aborting — failures
// so a failed contract check still lets the teardown join the workers.

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

inline void check_eq_str(const std::string& actual, const std::string& expected,
                         const char* file, int line, const char* expression) {
    if (actual != expected) {
        ++failure_count();
        std::fprintf(stderr, "FAIL %s:%d: %s — actual %s, expected %s\n", file,
                     line, expression, actual.c_str(), expected.c_str());
    }
}

}  // namespace pwb_test

#define TEST(name)                                                             \
    static void pwb_test_body_##name();                                        \
    static ::pwb_test::Registrar pwb_test_registrar_##name(#name,              \
                                                           &pwb_test_body_##name); \
    static void pwb_test_body_##name()

#define PWB_CHECK(cond) ::pwb_test::check_true((cond), __FILE__, __LINE__, #cond)
#define PWB_CHECK_EQ_STR(actual, expected)                                     \
    ::pwb_test::check_eq_str((actual), (expected), __FILE__, __LINE__, #actual)

#define PWB_CHECK_THROWS_AS(stmt, ExType)                                      \
    do {                                                                       \
        bool thrown = false;                                                   \
        try {                                                                  \
            stmt;                                                              \
        } catch (const ExType&) {                                              \
            thrown = true;                                                     \
        } catch (...) {                                                        \
        }                                                                      \
        PWB_CHECK(thrown);                                                     \
    } while (false)

inline int pwb_test_main() {
    for (const auto& test : ::pwb_test::registry()) {
        const int before = ::pwb_test::failure_count();
        test.body();
        const int after = ::pwb_test::failure_count();
        std::printf("%-6s %s\n", after == before ? "ok" : "FAIL",
                    test.name.c_str());
    }
    const int failures = ::pwb_test::failure_count();
    if (failures == 0) {
        std::printf("ALL PASS (%zu tests)\n", ::pwb_test::registry().size());
        return 0;
    }
    std::printf("FAILED: %d check(s)\n", failures);
    return 1;
}
