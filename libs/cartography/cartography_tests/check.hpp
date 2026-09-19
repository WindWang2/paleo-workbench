// CONV-27 — shared test harness for the cartography oracle tests.
// Same hand-rolled pattern as libs/mapping_kernel/mapping_kernel_tests
// (no test framework dependency): check() records failures, main returns
// the failure count as the exit code.
#pragma once

#include <pwb/cartography/scalar_style.hpp>
#include <pwb/domain/json.hpp>

#include <cmath>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace cartography_test {

inline int g_failures = 0;

// Load a fixture file whose path arrives as a compile-time macro string.
inline pwb::domain::Json load_fixture(const char* path) {
    std::ifstream stream(path);
    if (!stream) {
        std::printf("FAIL cannot open fixture %s\n", path);
        ++g_failures;
        return pwb::domain::Json();
    }
    std::stringstream buffer;
    buffer << stream.rdbuf();
    return pwb::domain::Json::parse(buffer.str());
}

inline void check(bool ok, const std::string& what) {
    if (!ok) {
        ++g_failures;
        std::printf("FAIL %s\n", what.c_str());
    }
}

inline void check_json_eq(const pwb::domain::Json& got,
                          const pwb::domain::Json& want,
                          const std::string& what) {
    // canonical() re-parse: Python unsigned ints arrive as number_unsigned
    // vs C++ number_integer; json_semantic_diff treats them as type
    // differences, so normalize through a parse/dump round-trip first.
    pwb::domain::Json canonical_got =
        pwb::domain::Json::parse(got.dump());
    pwb::domain::Json canonical_want =
        pwb::domain::Json::parse(want.dump());
    pwb::domain::JsonDiff diff =
        pwb::domain::json_semantic_diff(canonical_got, canonical_want);
    if (!diff.equal) {
        ++g_failures;
        std::printf("FAIL %s (%s: %s)\n", what.c_str(), diff.path.c_str(),
                    diff.reason.c_str());
        std::printf("  got:  %s\n", canonical_got.dump().c_str());
        std::printf("  want: %s\n", canonical_want.dump().c_str());
    }
}

// Non-finite floats freeze as strings ("NaN"/"Infinity"/"-Infinity").
inline double decode_double(const pwb::domain::Json& value) {
    if (value.is_string()) {
        const std::string tag = value.get<std::string>();
        if (tag == "NaN") return std::nan("");
        if (tag == "Infinity") return HUGE_VAL;
        if (tag == "-Infinity") return -HUGE_VAL;
    }
    return value.get<double>();
}

// (breaks, labels) pairs freeze as [array, array]; unpack and compare.
inline void check_breaks(const pwb::cartography::ClassifiedBreaks& got,
                         const pwb::domain::Json& want,
                         const std::string& what) {
    pwb::domain::Json got_json = pwb::domain::Json::array();
    pwb::domain::Json breaks = pwb::domain::Json::array();
    for (double v : got.breaks) {
        if (std::isnan(v)) {
            breaks.push_back("NaN");
        } else if (std::isinf(v)) {
            breaks.push_back(v > 0 ? "Infinity" : "-Infinity");
        } else {
            breaks.push_back(v);
        }
    }
    got_json.push_back(breaks);
    pwb::domain::Json labels = pwb::domain::Json::array();
    for (const std::string& label : got.labels) labels.push_back(label);
    got_json.push_back(std::move(labels));
    check_json_eq(got_json, want, what);
}

}  // namespace cartography_test
