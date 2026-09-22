// E-1 regression: the C++ canonical snapshot dump must be byte-identical
// to the Python prediction service's
// json.dumps(payload, sort_keys=True, ensure_ascii=False) — golden strings
// below were produced by CPython 3.14. A compact dump (no ", " / ": ")
// hashed differently and mixed Python/C++ snapshot generations were always
// judged stale.

#include <cstdio>

#include <nlohmann/json.hpp>

#include "../src/inference_hash.hpp"

namespace {

int failures = 0;

void expect(const std::string& actual, const std::string& expected,
            const char* label) {
    if (actual != expected) {
        ++failures;
        std::printf("FAIL %s\n  actual:   %s\n  expected: %s\n", label,
                    actual.c_str(), expected.c_str());
    }
}

}  // namespace

int main() {
    using nlohmann::json;
    using pwb::closure_science::detail::dump_canonical;

    expect(dump_canonical(json{
                {"a", json{1, 2.5, "x"}},
                {"b", 2},
                {"nested", json{{"j", nullptr}, {"k", "v"}}},
            }),
           R"({"a": [1, 2.5, "x"], "b": 2, "nested": {"j": null, "k": "v"}})",
           "mixed object/array golden");

    expect(dump_canonical(json{
                {"x", json::object()},
                {"y", json::array()},
                {"z", true},
                {"空格", "中文值"},
            }),
           R"({"x": {}, "y": [], "z": true, "空格": "中文值"})",
           "unicode + empty containers golden (ensure_ascii=False)");

    expect(dump_canonical(json{1.0, -0.5, 3, "s"}),
           R"([1.0, -0.5, 3, "s"])", "scalar array golden");

    if (failures == 0) {
        std::printf("inference-hash: all golden dumps passed\n");
        return 0;
    }
    std::printf("inference-hash: %d failure(s)\n", failures);
    return 1;
}
