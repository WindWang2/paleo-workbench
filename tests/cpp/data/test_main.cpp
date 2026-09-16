// Shared main for every data.* test executable.
#include "pwb_test.hpp"

#include <cstdio>

int main(int argc, char** argv) {
    // Unbuffered stdout: a crash must never swallow earlier PASS lines.
    setvbuf(stdout, nullptr, _IONBF, 0);
    ::pwb_test::set_args(argc, argv);
    return ::pwb_test::run_all();
}
