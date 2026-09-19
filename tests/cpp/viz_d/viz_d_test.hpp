#pragma once

// Minimal deterministic test harness for the viz_d suite (same
// zero-dependency pattern as the seismic_viewer sv_test.hpp) plus fixture
// loading: every oracle JSON is frozen by tools/oracle/generate_viz_d_*.py
// from the REAL Python/native reference paths.

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <functional>
#include <limits>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

namespace viz_d_test {

struct TestCase {
    std::string name;
    std::function<void()> body;
};

inline std::vector<TestCase>& registry() {
    static std::vector<TestCase> cases;
    return cases;
}

inline void fail(const char* file, int line, const std::string& message) {
    std::fprintf(stderr, "FAIL %s:%d: %s\n", file, line, message.c_str());
    std::fflush(stderr);
    std::abort();
}

inline void check_true(bool condition, const char* file, int line,
                       const char* expression) {
    if (!condition) {
        fail(file, line, std::string("expected true: ") + expression);
    }
}

struct Registrar {
    Registrar(std::string name, std::function<void()> body) {
        registry().push_back(TestCase{std::move(name), std::move(body)});
    }
};

inline std::filesystem::path fixture_root() {
    const char* env = std::getenv("VIZ_D_FIXTURES");
    return std::filesystem::path(env != nullptr && *env != '\0'
                                     ? env
                                     : "tests/cpp/viz_d/fixtures");
}

inline nlohmann::json load_fixture(const char* file_name) {
    const auto path = fixture_root() / file_name;
    std::FILE* handle = std::fopen(path.string().c_str(), "rb");
    if (handle == nullptr) {
        fail(__FILE__, __LINE__, "cannot open fixture " + path.string());
    }
    std::string text;
    char buffer[4096];
    std::size_t n = 0;
    while ((n = std::fread(buffer, 1, sizeof(buffer), handle)) > 0) {
        text.append(buffer, n);
    }
    std::fclose(handle);
    return nlohmann::json::parse(text);
}

// Oracle floats are frozen with Python repr (exact double round-trip);
// non-finite values are tagged strings ("nan"/"inf"/"-inf").
inline double num_from(const nlohmann::json& value) {
    if (value.is_string()) {
        const std::string tag = value.get<std::string>();
        if (tag == "nan") {
            return std::numeric_limits<double>::quiet_NaN();
        }
        if (tag == "inf") {
            return std::numeric_limits<double>::infinity();
        }
        if (tag == "-inf") {
            return -std::numeric_limits<double>::infinity();
        }
    }
    return value.get<double>();
}

inline bool close_or_both_nan(double a, double b, double tol) {
    if (std::isnan(a) && std::isnan(b)) {
        return true;
    }
    if (std::isnan(a) != std::isnan(b)) {
        return false;
    }
    const double scale = std::max(1.0, std::max(std::abs(a), std::abs(b)));
    return std::abs(a - b) <= tol * scale;
}

inline std::vector<double> nums_from(const nlohmann::json& values) {
    std::vector<double> out;
    out.reserve(values.size());
    for (const auto& value : values) {
        out.push_back(num_from(value));
    }
    return out;
}

} // namespace viz_d_test

#define TEST(name)                                                              \
    static void viz_d_test_body_##name();                                       \
    static ::viz_d_test::Registrar viz_d_test_registrar_##name(                 \
        #name, &viz_d_test_body_##name);                                        \
    static void viz_d_test_body_##name()

#define PWB_CHECK(cond) ::viz_d_test::check_true((cond), __FILE__, __LINE__, #cond)
#define PWB_CHECK_MSG(cond, msg) \
    ::viz_d_test::check_true((cond), __FILE__, __LINE__, (msg))
#define PWB_FAIL(msg) ::viz_d_test::fail(__FILE__, __LINE__, (msg))
