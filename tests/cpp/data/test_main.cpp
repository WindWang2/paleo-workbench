// Shared main for every data.* test executable.
#include "pwb_test.hpp"

int main(int argc, char** argv) {
    ::pwb_test::set_args(argc, argv);
    return ::pwb_test::run_all();
}
