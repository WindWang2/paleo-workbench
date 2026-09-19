// Shared check() helpers — same convention as providers_tests.
#pragma once

#include <cstdio>
#include <stdexcept>
#include <string>

inline int g_failures = 0;
inline int g_checks = 0;

inline void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

template <typename Fn>
std::string expect_throw(Fn&& fn) {
    try {
        fn();
    } catch (const std::exception& exc) {
        return exc.what();
    }
    return "<no throw>";
}

inline int test_exit(const char* name) {
    if (g_failures == 0) {
        std::printf("%s: all %d checks passed\n", name, g_checks);
        return 0;
    }
    std::fprintf(stderr, "%s: %d/%d checks FAILED\n", name, g_failures, g_checks);
    return 1;
}
