#pragma once

// Minimal test harness (same shape as tests/cpp/platform/test_framework.hpp:
// one counter, honest reporting, no framework dependency — the build
// closure stays Qt + QGIS only).

#include <cstdio>
#include <string>

namespace pwb::test {

inline int& failure_count() {
    static int count = 0;
    return count;
}

inline void check(bool condition, const char* expression, const char* file,
                  int line, const std::string& detail = std::string()) {
    if (condition) return;
    ++failure_count();
    std::fprintf(stderr, "FAIL %s:%d: %s%s%s\n", file, line, expression,
                 detail.empty() ? "" : " -- ", detail.c_str());
}

inline int report(const char* test_name) {
    const int failures = failure_count();
    if (failures == 0) {
        std::printf("PASS %s\n", test_name);
        return 0;
    }
    std::printf("FAIL %s (%d assertion(s) failed)\n", test_name, failures);
    return 1;
}

}  // namespace pwb::test

#define PWB_CHECK(cond) \
    (::pwb::test::check((cond), #cond, __FILE__, __LINE__))
#define PWB_CHECK_MSG(cond, msg) \
    (::pwb::test::check((cond), #cond, __FILE__, __LINE__, (msg)))
