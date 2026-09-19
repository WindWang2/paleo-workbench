// Included once per test executable (at the end of the single test TU).

int main() {
    // Any failing check aborts the process (non-zero exit); reaching this
    // loop's end means every registered test passed.
    if (::viz_d_test::registry().empty()) {
        std::fprintf(stderr, "no tests registered\n");
        return 2;
    }
    for (const auto& test_case : ::viz_d_test::registry()) {
        std::printf("[ RUN  ] %s\n", test_case.name.c_str());
        std::fflush(stdout);
        test_case.body();
        std::printf("[ PASS ] %s\n", test_case.name.c_str());
        std::fflush(stdout);
    }
    std::printf("ALL %zu TESTS PASSED\n", ::viz_d_test::registry().size());
    return 0;
}
