// layout_export.spec_builder — C++ layout-export kernel vs the frozen
// Python oracle (CONV-29).
//
// For every frozen case the C++ kernel must reproduce: the wire spec JSON
// (semantic equality — int vs float is a type difference), the exact
// warning strings, the fail-closed error messages, hybrid classifications,
// export reports (Python-shared keys key-for-key; D-03 fail-closed paths
// per their cpp_policy block), budget messages, and the parity contract.

#include <cstdio>
#include <exception>
#include <filesystem>
#include <fstream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/layout_export/layout_export.hpp>
#include <pwb/mapping_document/composition.hpp>

using pwb::domain::Json;
using namespace pwb::layout_export;

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

void expect_semantic_equal(const Json& got, const Json& want,
                           const std::string& what) {
    const pwb::domain::JsonDiff diff = pwb::domain::json_semantic_diff(got, want);
    check(diff.equal, what + " (" + diff.path + ": " + diff.reason + ")");
}

const Json& fixture() {
    static const Json* cached = [] {
        std::ifstream stream(PWB_LAYOUT_EXPORT_FIXTURE, std::ios::binary);
        if (!stream.good()) {
            std::fprintf(stderr, "FAIL cannot open %s\n",
                         PWB_LAYOUT_EXPORT_FIXTURE);
            std::exit(1);
        }
        std::ostringstream buffer;
        buffer << stream.rdbuf();
        return new Json(Json::parse(buffer.str()));
    }();
    return *cached;
}

// North-arrow temp paths are machine-specific on both sides; replay
// neutralises them exactly like the generator did.
void neutralize_svg_paths(Json& payload) {
    if (!payload.is_object()) return;
    const auto items = payload.find("items");
    if (items == payload.end() || !items->is_array()) return;
    for (Json& item : *items) {
        if (!item.is_object()) continue;
        auto path = item.find("svg_path");
        if (path != item.end()) *path = "<NORTH_ARROW_SVG>";
    }
}

BuildSpecInput read_spec_input(const Json& input) {
    BuildSpecInput in;
    const Json& extent = input.at("map_extent");
    for (int i = 0; i < 4; ++i) {
        in.map_extent[static_cast<std::size_t>(i)] =
            extent.at(static_cast<std::size_t>(i)).get<double>();
    }
    if (input.at("crs").is_string()) in.crs = input.at("crs").get<std::string>();
    in.mirror_layers = input.at("mirror_layers");
    return in;
}

// --- spec cases -------------------------------------------------------------

void run_spec_cases() {
    const Json& cases = fixture()["spec_cases"];
    for (const auto& c : cases) {
        const std::string name = c.at("id").get<std::string>();
        Composition doc;
        try {
            doc = pwb::mapping_document::parse_composition(c.at("input").at("composition"));
        } catch (const std::exception& ex) {
            check(false, name + " composition parse threw: " + ex.what());
            continue;
        }
        const BuildSpecInput input = read_spec_input(c.at("input"));
        std::vector<std::string> warnings;
        Json spec;
        bool threw = false;
        std::string message;
        try {
            spec = build_layout_spec(doc, input, &warnings);
            // Determinism: repeated builds must be byte-identical.
            std::vector<std::string> warnings_again;
            const Json again = build_layout_spec(doc, input, &warnings_again);
            check(spec.dump() == again.dump()
                      && warnings == warnings_again,
                  name + " deterministic output");
        } catch (const std::invalid_argument& ex) {
            threw = true;
            message = ex.what();
        } catch (const std::exception& ex) {
            check(false, name + " unexpected exception type: " + ex.what());
            continue;
        }
        const Json& expected = c.at("cpp_expected");
        if (expected.at("error").is_null()) {
            check(!threw, name + " unexpected throw: " + message);
            if (threw) continue;
            Json got = spec;
            neutralize_svg_paths(got);
            expect_semantic_equal(got, expected.at("spec"), name + " spec");
        } else {
            check(threw, name + " expected fail-closed throw");
            if (threw) {
                check(message == expected.at("error").get<std::string>(),
                      name + " error message: " + message);
            }
        }
        // Warnings accumulate on both throw and success paths.
        Json got_warnings = Json::array();
        for (const std::string& w : warnings) got_warnings.push_back(w);
        expect_semantic_equal(got_warnings, expected.at("warnings"),
                              name + " warnings");
    }
    check(cases.size() >= 30, "at least 30 spec cases exercised");
}

// --- hybrid classification --------------------------------------------------

void run_hybrid_cases() {
    const Json& cases = fixture()["hybrid_cases"];
    for (const auto& c : cases) {
        const std::string name = c.at("id").get<std::string>();
        Composition doc;
        try {
            doc = pwb::mapping_document::parse_composition(c.at("input").at("composition"));
        } catch (const std::exception& ex) {
            check(false, name + " composition parse threw: " + ex.what());
            continue;
        }
        const std::vector<std::string> got =
            hybrid_element_types(doc, c.at("input").at("mirror_layers"));
        Json got_json = Json::array();
        for (const std::string& value : got) got_json.push_back(value);
        expect_semantic_equal(got_json, c.at("cpp_expected"), name);
    }
    check(cases.size() >= 3, "hybrid cases exercised");
}

// --- report cases -----------------------------------------------------------

class FakeExecutor {
 public:
    explicit FakeExecutor(bool fail) : fail_(fail) {}

    Json operator()(const std::string& spec_json, const std::string&,
                    const std::string&, double) {
        if (fail_) throw std::runtime_error("boom");
        recorded_spec_ = Json::parse(spec_json);
        const long long items = recorded_spec_.is_object()
            && recorded_spec_.contains("items")
            && recorded_spec_["items"].is_array()
            ? static_cast<long long>(recorded_spec_["items"].size())
            : 0;
        return Json{{"ok", true}, {"items", items}};
    }

    const Json& recorded_spec() const { return recorded_spec_; }

 private:
    bool fail_;
    Json recorded_spec_;
};

void run_report_cases() {
    const Json& cases = fixture()["report_cases"];
    for (const auto& c : cases) {
        const std::string name = c.at("id").get<std::string>();
        const Json& input = c.at("input");
        Composition doc;
        try {
            doc = pwb::mapping_document::parse_composition(input.at("composition"));
        } catch (const std::exception& ex) {
            check(false, name + " composition parse threw: " + ex.what());
            continue;
        }
        ExportRequest request;
        request.format = input.at("fmt").get<std::string>();
        request.dpi = input.at("dpi").get<double>();
        request.geo_pdf = input.at("geo_pdf").get<bool>();
        request.crs = input.at("crs").is_string()
            ? input.at("crs").get<std::string>()
            : std::string();
        request.mirror_layers = input.at("mirror_layers");
        if (input.at("map_extent").is_array()) {
            request.has_map_extent = true;
            const Json& extent = input.at("map_extent");
            for (int i = 0; i < 4; ++i) {
                request.map_extent[static_cast<std::size_t>(i)] =
                    extent.at(static_cast<std::size_t>(i)).get<double>();
            }
        }

        FakeExecutor executor_instance(input.at("executor").get<std::string>() == "fail");
        std::unique_ptr<LayoutExecutor> executor;
        if (input.at("executor").get<std::string>() != "none") {
            executor = std::make_unique<LayoutExecutor>(
                [&executor_instance](const std::string& spec_json,
                                     const std::string& path,
                                     const std::string& format, double dpi) {
                    return executor_instance(spec_json, path, format, dpi);
                });
        }

        // Machine-specific output path; only the basename is contractual.
        const std::filesystem::path out =
            std::filesystem::temp_directory_path() / "pwb_oracle_page.out";
        const LayoutExportReport report =
            export_composition_reported(doc, out, request, executor.get());
        const Json got = report.to_dict();
        const Json& want = c.at("python_report");

        // Divergent fail-closed paths carry the C++ policy block.
        const bool divergent = c.contains("cpp_policy");
        std::string engine = want.at("engine").get<std::string>();
        bool ok = want.at("ok").get<bool>();
        if (divergent) {
            engine = c.at("cpp_policy").at("engine").get<std::string>();
            ok = c.at("cpp_policy").at("ok").get<bool>();
            const std::string failure_contains =
                c.at("cpp_policy").at("failure_contains").get<std::string>();
            check(got.at("failure").get<std::string>().find(failure_contains)
                      != std::string::npos,
                  name + " failure diagnostics mention '" + failure_contains
                      + "' (got: " + got.at("failure").get<std::string>() + ")");
        }
        check(got.at("engine").get<std::string>() == engine,
              name + " engine (got " + got.at("engine").get<std::string>()
                  + ")");
        check(got.at("ok").get<bool>() == ok, name + " ok flag");

        // Python-shared keys, frozen from the real report.
        check(got.at("format").get<std::string>()
                      == want.at("format").get<std::string>(),
              name + " format");
        check(got.at("dpi").get<double>() == want.at("dpi").get<double>(),
              name + " dpi");
        expect_semantic_equal(got.at("warnings"), want.at("warnings"),
                              name + " warnings");
        expect_semantic_equal(got.at("unmapped_elements"),
                              want.at("unmapped_elements"),
                              name + " unmapped_elements");
        expect_semantic_equal(got.at("hybrid_items"), want.at("hybrid_items"),
                              name + " hybrid_items");
        if (!divergent) {
            expect_semantic_equal(got.at("items"), want.at("items"),
                                  name + " items");
        }
        // geo_pdf must reach the executor spec (recorded by the fake).
        if (c.contains("recorded_geo_pdf")) {
            const Json& recorded = executor_instance.recorded_spec();
            check(recorded.is_object()
                      && recorded.value("geo_pdf", false)
                          == c.at("recorded_geo_pdf").get<bool>(),
                  name + " geo_pdf recorded on the executor spec");
        }
    }
    check(cases.size() >= 8, "report cases exercised");
}

// --- budget -----------------------------------------------------------------

void run_budget_cases() {
    const Json& cases = fixture()["budget_cases"];
    for (const auto& c : cases) {
        const std::string name = c.at("id").get<std::string>();
        Composition doc;
        doc.width_mm = c.at("input").at("width_mm").get<double>();
        doc.height_mm = c.at("input").at("height_mm").get<double>();
        const double dpi = c.at("input").at("dpi").get<double>();
        const Json& expected = c.at("cpp_expected");
        if (expected.at("error").is_null()) {
            bool threw = false;
            try {
                check_pixel_budget(doc, dpi);
            } catch (const std::exception&) {
                threw = true;
            }
            check(!threw, name + " budget unexpectedly breached");
        } else {
            bool threw = false;
            std::string message;
            try {
                check_pixel_budget(doc, dpi);
            } catch (const std::invalid_argument& ex) {
                threw = true;
                message = ex.what();
            }
            check(threw, name + " expected budget breach");
            if (threw) {
                check(message == expected.at("error").get<std::string>(),
                      name + " budget message: " + message);
            }
        }
    }
    check(cases.size() >= 4, "budget cases exercised");
}

// --- parity -----------------------------------------------------------------

void run_parity_cases() {
    const Json& cases = fixture()["parity_cases"];
    for (const auto& c : cases) {
        const std::string name = c.at("id").get<std::string>();
        const ParityReport report = screen_export_parity(
            c.at("input").at("canvas_state"),
            c.at("input").at("export_state"));
        const Json got = report.to_dict();
        const Json& want = c.at("cpp_expected");
        check(got.at("equal").get<bool>() == want.at("equal").get<bool>(),
              name + " overall equal flag");
        const Json& want_aspects = want.at("aspects");
        const Json& got_aspects = got.at("aspects");
        for (auto it = want_aspects.begin(); it != want_aspects.end(); ++it) {
            check(got_aspects.at(it.key()).at("equal").get<bool>()
                          == it.value().at("equal").get<bool>(),
                  name + " aspect " + it.key());
        }
        check(static_cast<long long>(got.at("diffs").size())
                  == want.at("diff_count").get<long long>(),
              name + " diff count (got "
                  + std::to_string(got.at("diffs").size()) + ")");
        check(got.at("style_source").get<std::string>()
                  == want.at("style_source").get<std::string>(),
              name + " style_source disclosure");
    }
    check(cases.size() >= 8, "parity cases exercised");
}

// --- negative self-check ----------------------------------------------------

void corrupt_json(Json& target, const Json& path, const Json& value) {
    Json* node = &target;
    for (std::size_t i = 0; i + 1 < path.size(); ++i) {
        const Json& key = path.at(i);
        node = key.is_string() ? &(*node)[key.get<std::string>()]
                               : &(*node)[static_cast<std::size_t>(
                                     key.get<long long>())];
    }
    const Json& key = path.at(path.size() - 1);
    if (key.is_string()) {
        (*node)[key.get<std::string>()] = value;
    } else {
        (*node)[static_cast<std::size_t>(key.get<long long>())] = value;
    }
}

void run_self_check() {
    const Json& self_check = fixture()["self_check"];
    const std::string case_id = self_check.at("spec_case_id").get<std::string>();
    for (const auto& c : fixture()["spec_cases"]) {
        if (c.at("id").get<std::string>() != case_id) continue;
        Json got = c.at("cpp_expected").at("spec");
        const Json& pristine = got;
        const pwb::domain::JsonDiff baseline =
            pwb::domain::json_semantic_diff(pristine, pristine);
        check(baseline.equal, "self-check comparator sanity (clean diff)");
        corrupt_json(got, self_check.at("corrupt").at("path"),
                     self_check.at("corrupt").at("value"));
        const pwb::domain::JsonDiff corrupted =
            pwb::domain::json_semantic_diff(got, c.at("cpp_expected").at("spec"));
        check(!corrupted.equal,
              "self-check: corrupted expectation must be REJECTED (got "
              + corrupted.path + ")");
        return;
    }
    check(false, "self-check spec case not found: " + case_id);
}

}  // namespace

int main() {
    run_spec_cases();
    run_hybrid_cases();
    run_report_cases();
    run_budget_cases();
    run_parity_cases();
    run_self_check();
    std::printf("%s: %d failure(s) over %d checks\n",
                g_failures == 0 ? "PASS" : "FAIL", g_failures, g_checks);
    return g_failures == 0 ? 0 : 1;
}
