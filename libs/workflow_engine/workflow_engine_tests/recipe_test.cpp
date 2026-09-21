// workflow_engine.recipe — CONV-33 oracle replay: C++ recipe port vs the
// frozen Python fixture (workflow_recipe_oracle.json, generated from the
// REAL implementation by tools/oracle/generate_workflow_recipe_fixtures.py).
// Covers the 13 frozen case families: save/load round-trip with EXACT file
// bytes (indent=1, ensure_ascii=False, no trailing newline) + nested
// parent mkdir, forbidden-key and absolute-path structural gates (verbatim
// messages incl. Python repr quoting and the em-dash), corrupt-JSON load
// refusals with the CPython JSONDecodeError detail, migrate v1 identity +
// nested schema_version injection + fail-closed unknown version, the .json
// suffix rewrite, clone identity, diff (nodes/slots/max_concurrency),
// inspect shape, recipe_from_run slot-default promotion, recipe_from_spec
// slug ids, from_dict coercions and the save/load refusal gates. Negative
// self-checks tamper frozen expectations in memory and assert the
// comparators catch them.

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <functional>
#include <map>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/domain/sha256.hpp>
#include <pwb/workflow_engine/recipe.hpp>
#include <pwb/workflow_spec/model.hpp>
#include <pwb/workflow_spec/validation.hpp>

using pwb::domain::Json;
namespace we = pwb::workflow_engine;
namespace ws = pwb::workflow_spec;

namespace {

int g_failures = 0;
int g_checks = 0;
int g_negative = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
    }
}

// A negative self-check: `detected` must be TRUE (the tampered expectation
// must trip the comparator). A missed tamper is a harness failure.
void negative_check(bool detected, const std::string& what) {
    ++g_negative;
    if (!detected) {
        ++g_failures;
        std::fprintf(stderr, "FAIL negative self-check missed: %s\n",
                     what.c_str());
    }
}

// ------------------------------------------------------------- helpers --

std::string read_file(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary);
    std::ostringstream buffer;
    buffer << in.rdbuf();
    return buffer.str();
}

void write_file(const std::filesystem::path& path, const std::string& text) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    out << text;
}

std::filesystem::path make_root() {
    static std::vector<std::filesystem::path> roots;
    static const bool cleanup_registered =
        std::atexit([] {
            for (const std::filesystem::path& root : roots) {
                std::error_code ec;
                std::filesystem::remove_all(root, ec);
            }
        }) == 0;
    (void)cleanup_registered;
#if defined(_WIN32)
    // mkdtemp is POSIX-only - same contract through temp_directory_path.
    static unsigned seq = 0;
    for (;;) {
        const std::filesystem::path root =
            std::filesystem::temp_directory_path() /
            ("pwb-recipe-test-" + std::to_string(seq++));
        std::error_code ec;
        if (std::filesystem::create_directory(root, ec)) {
            roots.push_back(root);
            return root;
        }
    }
#else
    std::string tmpl = "/tmp/pwb-recipe-test-XXXXXX";
    if (char* dir = ::mkdtemp(tmpl.data())) {
        const std::filesystem::path root(dir);
        roots.push_back(root);
        return root;
    }
#endif
    std::fprintf(stderr, "FAIL cannot create temp recipe root\n");
    std::exit(2);
}

we::Clock fixed(double value) {
    return [value] { return value; };
}

// ------------------------------------------------------- json comparators --
// Value-wise oracle comparison (store_test.cpp model): signed/unsigned
// unify (both are Python ints), floats compare exactly, int vs float stays
// a type difference (Python 1 vs 1.0), null/missing never coerce.
struct ValueDiff {
    bool equal = true;
    std::string path;
    std::string reason;
};

ValueDiff value_diff(const Json& left, const Json& right,
                     const std::string& path) {
    if (left.is_object() && right.is_object()) {
        for (const auto& [key, item] : left.items()) {
            if (!right.contains(key)) {
                return {false, path + "." + key, "key missing on right"};
            }
            const ValueDiff child =
                value_diff(item, right.at(key), path + "." + key);
            if (!child.equal) return child;
        }
        for (const auto& [key, item] : right.items()) {
            (void)item;
            if (!left.contains(key)) {
                return {false, path + "." + key, "key missing on left"};
            }
        }
        return {};
    }
    if (left.is_array() && right.is_array()) {
        if (left.size() != right.size()) {
            return {false, path, "array length differs"};
        }
        for (std::size_t i = 0; i < left.size(); ++i) {
            const ValueDiff child = value_diff(
                left[i], right[i], path + "[" + std::to_string(i) + "]");
            if (!child.equal) return child;
        }
        return {};
    }
    if (left.is_number_integer() && right.is_number_integer()) {
        if (left.get<long long>() == right.get<long long>()) return {};
        return {false, path, "int value differs"};
    }
    if (left.is_number_float() && right.is_number_float()) {
        if (left.get<double>() == right.get<double>()) return {};
        return {false, path, "float value differs"};
    }
    if (left.type() == right.type() && left == right) return {};
    return {false, path, "type differs"};
}

bool values_equal(const Json& left, const Json& right) {
    return value_diff(left, right, "$").equal;
}

// Recursive ordered key-sequence walk: pins the Python dict KEY ORDER the
// ordered_json parse of the fixture preserves (setdefault appends LAST).
void collect_key_orders(const Json& value,
                        std::vector<std::vector<std::string>>& out) {
    if (value.is_object()) {
        std::vector<std::string> keys;
        for (const auto& [key, item] : value.items()) {
            keys.push_back(key);
        }
        out.push_back(std::move(keys));
        for (const auto& [key, item] : value.items()) {
            collect_key_orders(item, out);
        }
    } else if (value.is_array()) {
        for (const auto& item : value) {
            collect_key_orders(item, out);
        }
    }
}

bool key_orders_equal(const Json& left, const Json& right) {
    std::vector<std::vector<std::string>> a;
    std::vector<std::vector<std::string>> b;
    collect_key_orders(left, a);
    collect_key_orders(right, b);
    return a == b;
}

void check_json(const Json& frozen, const Json& got, const std::string& label) {
    const ValueDiff diff = value_diff(frozen, got, "$");
    check(diff.equal,
          label + ": values" +
              (diff.equal ? "" : " — " + diff.path + ": " + diff.reason));
    check(key_orders_equal(frozen, got), label + ": key order");
}

bool strings_equal(const Json& frozen_array,
                   const std::vector<std::string>& got) {
    if (!frozen_array.is_array() || frozen_array.size() != got.size()) {
        return false;
    }
    for (std::size_t i = 0; i < frozen_array.size(); ++i) {
        if (!frozen_array[i].is_string() ||
            frozen_array[i].get<std::string>() != got[i]) {
            return false;
        }
    }
    return true;
}

// Capture a RecipeError message from a callable (threw == true).
template <typename Fn>
std::pair<bool, std::string> recipe_error_of(Fn&& fn) {
    try {
        fn();
    } catch (const we::RecipeError& exc) {
        return {true, exc.what()};
    } catch (...) {
        return {true, "WRONG-EXCEPTION-TYPE"};
    }
    return {false, {}};
}

int file_count(const std::filesystem::path& dir) {
    int count = 0;
    std::error_code ec;
    for (const auto& entry :
         std::filesystem::directory_iterator(dir, ec)) {
        (void)entry;
        ++count;
    }
    return count;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr,
                     "usage: workflow_engine_recipe_test "
                     "<workflow_recipe_oracle.json>\n");
        return 2;
    }
    Json fixture;
    try {
        fixture = Json::parse(read_file(argv[1]));
    } catch (const std::exception& exc) {
        std::fprintf(stderr, "FAIL cannot parse fixture: %s\n", exc.what());
        return 2;
    }

    const ws::WorkflowSpec spec =
        ws::WorkflowSpec::from_dict(fixture.at("spec"));
    const ws::WorkflowSpec run_spec =
        ws::WorkflowSpec::from_dict(fixture.at("run_spec"));
    check(spec.spec_hash() == fixture.at("spec_hash").get<std::string>(),
          "spec_hash parity");
    check(run_spec.spec_hash() ==
              fixture.at("run_spec_hash").get<std::string>(),
          "run spec_hash parity");

    const double fixed_clock = fixture.at("fixed_clock").get<double>();
    const double second_clock = fixture.at("second_clock").get<double>();

    ws::ActionCatalog registry;
    for (const auto& [action_id, risk] : fixture.at("registry").items()) {
        registry[action_id] = risk.get<std::string>();
    }

    // ---------------------------------------------- 1. round-trip + bytes --
    {
        const Json& frozen = fixture.at("case01_roundtrip");
        we::RecipeDocument recipe = we::recipe_from_spec(
            spec, std::nullopt, "round-trip recipe", {"demo", "parity"},
            fixed(fixed_clock));
        check(recipe.created_at.has_value() &&
                  *recipe.created_at == fixed_clock,
              "c01 injected created_at clock");
        check_json(frozen.at("recipe_to_dict"), recipe.to_dict(),
                   "c01 recipe to_dict");
        const std::filesystem::path path =
            we::save_recipe(recipe, make_root() / "wf-recipe-parity.json");
        check(path.filename().string() ==
                  frozen.at("filename").get<std::string>(),
              "c01 returned filename");
        const std::string text = read_file(path);
        const std::string want = frozen.at("bytes").get<std::string>();
        check(text == want, "c01 exact file bytes (indent=1, no newline)");
        if (text != want) {
            std::size_t at = 0;
            while (at < text.size() && at < want.size() &&
                   text[at] == want[at]) {
                ++at;
            }
            std::fprintf(stderr, "  first byte diff at %zu\n", at);
        }
        // The temp file must be GONE after the atomic rename.
        check(file_count(path.parent_path()) == 1,
              "c01 no .tmp-recipe- leftovers");
        const we::RecipeDocument loaded = we::load_recipe(path);
        check_json(frozen.at("loaded_to_dict"), loaded.to_dict(),
                   "c01 loaded to_dict");
        check(ws::canonical_hash(loaded.to_dict()) ==
                  frozen.at("loaded_hash").get<std::string>(),
              "c01 loaded canonical_hash");
        // save into a NOT-yet-existing nested parent (mkdir parents=True)
        const std::filesystem::path root2 = make_root();
        const std::filesystem::path nested = we::save_recipe(
            recipe, root2 / "sub" / "dir" / "nested.paleo-workflow.json");
        check(read_file(nested) ==
                  frozen.at("nested_bytes").get<std::string>(),
              "c01 nested parent exact bytes");
        check(std::filesystem::is_directory(root2 / "sub" / "dir") ==
                  frozen.at("nested_created").get<bool>(),
              "c01 nested parent created");
    }

    // ------------------------------------- 2. forbidden-key structural gate --
    {
        const Json& frozen = fixture.at("case02_forbidden_keys");
        for (std::size_t i = 0; i < frozen.size(); ++i) {
            check(strings_equal(frozen[i].at("problems"),
                                we::structural_problems(frozen[i].at("data"))),
                  "c02 forbidden case " + std::to_string(i));
        }
        // validate_recipe = structural + validate_workflow_spec
        const Json& frozen_v = fixture.at("case02_validate_recipe");
        Json spec_data = fixture.at("spec");
        spec_data["nodes"] = Json::array({spec_data["nodes"][0]});
        spec_data["nodes"][0]["action_id"] = "no.such.action";
        const ws::WorkflowSpec bad =
            ws::WorkflowSpec::from_dict(spec_data);
        check(bad.workflow_id ==
                  frozen_v.at("recipe_workflow_id").get<std::string>(),
              "c02 validate_recipe workflow id");
        const we::RecipeDocument bad_recipe =
            we::recipe_from_spec(bad, std::nullopt, "", {},
                                 fixed(fixed_clock));
        check(strings_equal(frozen_v.at("problems"),
                            we::validate_recipe(bad_recipe, registry)),
              "c02 validate_recipe problems (structural + spec)");
    }

    // ---------------------------------------- 3. absolute-path gate --
    {
        const Json& frozen = fixture.at("case03_absolute_paths");
        for (std::size_t i = 0; i < frozen.size(); ++i) {
            check(strings_equal(frozen[i].at("problems"),
                                we::structural_problems(frozen[i].at("data"))),
                  "c03 absolute path case " + std::to_string(i));
        }
    }

    // ------------------------------------------ 4. corrupt JSON load --
    {
        const Json& frozen = fixture.at("case04_corrupt_json");
        const std::filesystem::path root = make_root();
        for (std::size_t i = 0; i < frozen.size(); ++i) {
            const std::string name = frozen[i].at("filename").get<std::string>();
            write_file(root / name, frozen[i].at("raw").get<std::string>());
            const auto [threw, message] = recipe_error_of([&] {
                (void)we::load_recipe(root / name);
            });
            check(threw, "c04 corrupt " + std::to_string(i) + " refused");
            check(message == frozen[i].at("message").get<std::string>(),
                  "c04 corrupt " + std::to_string(i) +
                      " frozen message (CPython detail)");
            if (message != frozen[i].at("message").get<std::string>()) {
                std::fprintf(stderr, "  got:      %s\n  expected: %s\n",
                             message.c_str(),
                             frozen[i].at("message").get<std::string>().c_str());
            }
        }
    }

    // --------------------------------------------------- 5. migrate --
    {
        const Json& frozen = fixture.at("case05_migrate");
        for (std::size_t i = 0; i < frozen.size(); ++i) {
            const Json migrated =
                we::migrate_recipe(frozen[i].at("data"));
            check_json(frozen[i].at("migrated"), migrated,
                       "c05 migrate case " + std::to_string(i) +
                           " (setdefault appends last)");
        }
        const Json& refusals = fixture.at("case05_migrate_refusals");
        for (std::size_t i = 0; i < refusals.size(); ++i) {
            const auto [threw, message] = recipe_error_of([&] {
                (void)we::migrate_recipe(refusals[i].at("data"));
            });
            check(threw, "c05 refusal " + std::to_string(i) + " refused");
            check(message == refusals[i].at("message").get<std::string>(),
                  "c05 refusal " + std::to_string(i) + " frozen message");
        }
    }

    // -------------------------------------------- 6. suffix rewrite --
    {
        const Json& frozen = fixture.at("case06_suffix_rewrite");
        const std::filesystem::path root = make_root();
        const we::RecipeDocument recipe = we::recipe_from_spec(
            spec, std::string("suffix-demo"), "", {}, fixed(fixed_clock));
        for (std::size_t i = 0; i < frozen.size(); ++i) {
            const std::string given = frozen[i].at("given").get<std::string>();
            const std::filesystem::path out =
                we::save_recipe(recipe, root / given);
            check(out.filename().string() ==
                      frozen[i].at("returned").get<std::string>(),
                  "c06 " + given + " -> rewritten name");
            check(out.filename().string() ==
                      frozen[i].at("expected").get<std::string>(),
                  "c06 " + given + " -> expected name");
            check(std::filesystem::exists(out) ==
                      frozen[i].at("exists").get<bool>(),
                  "c06 " + given + " written");
        }
    }

    // ---------------------------------------------------- 7. clone --
    {
        const Json& frozen = fixture.at("case07_clone");
        we::RecipeDocument original = we::recipe_from_spec(
            spec, std::nullopt, "clone me", {"t1"}, fixed(fixed_clock));
        original.source_run_id = "run-abcd1234ef567890";
        check_json(frozen.at("original_to_dict"), original.to_dict(),
                   "c07 original to_dict");
        const we::RecipeDocument clone =
            we::clone_recipe(original, std::nullopt, fixed(second_clock));
        check_json(frozen.at("default"), clone.to_dict(),
                   "c07 default clone to_dict");
        const we::RecipeDocument named = we::clone_recipe(
            original, std::string("custom-id"), fixed(second_clock));
        check_json(frozen.at("named"), named.to_dict(),
                   "c07 named clone to_dict");
        const we::RecipeDocument renamed = we::clone_recipe(
            original, std::string(""), fixed(second_clock));
        check(renamed.recipe_id ==
                  frozen.at("empty_id_falls_back").get<std::string>(),
              "c07 empty-string id falls back to <id>-clone");
        // Deep copy: the clone's workflow must not alias the original.
        check(&clone.workflow.nodes[0] != &original.workflow.nodes[0] &&
                  clone.workflow.nodes[0].parameters ==
                      original.workflow.nodes[0].parameters,
              "c07 independent workflow copy");
        // clone of a recipe whose name is "" -> from_dict re-coerces
        // name = workflow.name (str(data.get("name") or workflow.name)).
        const Json& frozen_empty = fixture.at("case07_clone_empty_name");
        we::RecipeDocument empty_named = we::recipe_from_spec(
            spec, std::string("empty-name"), "", {}, fixed(fixed_clock));
        empty_named.name = "";
        const we::RecipeDocument clone_empty =
            we::clone_recipe(empty_named, std::nullopt, fixed(second_clock));
        check(clone_empty.name ==
                  frozen_empty.at("cloned_name").get<std::string>(),
              "c07 empty-name clone falls back to workflow.name");
        check_json(frozen_empty.at("to_dict"), clone_empty.to_dict(),
                   "c07 empty-name clone to_dict");
    }

    // ---------------------------------------------------- 8. diff --
    {
        const Json& frozen = fixture.at("case08_diff");
        const we::RecipeDocument base =
            we::recipe_from_spec(spec, std::nullopt, "", {},
                                 fixed(fixed_clock));
        // changed spec: max_concurrency 4, slot grid_n retuned, extra slot
        // added, interp node description+retry changed, report node added.
        Json changed_data = fixture.at("spec");
        changed_data["max_concurrency"] = 4;
        changed_data["slots"][1]["default"] = 16;
        changed_data["slots"][1]["required"] = true;
        changed_data["slots"].push_back(Json{
            {"name", "extra"},
            {"schema", Json{{"type", "string"}}},
            {"required", false},
            {"default", nullptr},
            {"description", "added slot"},
        });
        changed_data["nodes"][1]["description"] = "changed interp";
        changed_data["nodes"][1]["retry"] =
            Json{{"max_attempts", 3}, {"backoff_seconds", 0.5}};
        changed_data["nodes"].push_back(Json{
            {"node_id", "report"},
            {"action_id", "test.noop"},
            {"parameters", Json::object()},
            {"depends_on", Json::array({"extract", "interp"})},
            {"condition", nullptr},
            {"retry", Json{{"max_attempts", 1}, {"backoff_seconds", 0.0}}},
            {"description", ""},
        });
        Json removed_data = fixture.at("spec");
        removed_data["slots"] = Json::array({removed_data["slots"][0]});
        const ws::WorkflowSpec changed_spec =
            ws::WorkflowSpec::from_dict(changed_data);
        const ws::WorkflowSpec removed_spec =
            ws::WorkflowSpec::from_dict(removed_data);
        const we::RecipeDocument other = we::recipe_from_spec(
            changed_spec, std::string("wf-recipe-parity"), "", {},
            fixed(fixed_clock));
        const we::RecipeDocument removed = we::recipe_from_spec(
            removed_spec, std::string("wf-recipe-parity"), "", {},
            fixed(fixed_clock));
        const we::RecipeDocument self_diff = we::recipe_from_spec(
            spec, std::string("wf-recipe-parity"), "", {},
            fixed(fixed_clock));
        check_json(frozen.at("changed"), we::diff_recipes(base, other),
                   "c08 diff changed");
        check_json(frozen.at("slot_removed"),
                   we::diff_recipes(base, removed), "c08 diff slot removed");
        check_json(frozen.at("reverse_changed"),
                   we::diff_recipes(other, base), "c08 diff reversed");
        check_json(frozen.at("empty"), we::diff_recipes(base, self_diff),
                   "c08 identical -> empty diff");
    }

    // -------------------------------------------------- 9. inspect --
    {
        const Json& frozen = fixture.at("case09_inspect");
        we::RecipeDocument recipe = we::recipe_from_spec(
            spec, std::nullopt, "inspect me", {"a", "b"}, fixed(fixed_clock));
        recipe.source_run_id = "run-1234567890abcdef";
        check_json(frozen, we::inspect_recipe(recipe),
                   "c09 inspect shape (no parameters in nodes)");
    }

    // ------------------------------------------- 10. recipe_from_run --
    {
        const Json& frozen = fixture.at("case10_from_run");
        ws::WorkflowRun run = ws::create_run(
            run_spec,
            Json{{"horizon", "H9"}, {"unknown_slot", 42}},
            frozen.at("run_id").get<std::string>(), fixed_clock);
        const we::RecipeDocument from_run =
            we::recipe_from_run(run, {"from-run"}, fixed(fixed_clock));
        check_json(frozen.at("recipe_to_dict"), from_run.to_dict(),
                   "c10 from_run to_dict (slot defaults promoted)");
        check_json(frozen.at("slots"),
                   [&] {
                       Json slots = Json::array();
                       for (const auto& slot : from_run.workflow.slots) {
                           slots.push_back(slot.to_dict());
                       }
                       return slots;
                   }(),
                   "c10 promoted slots");
        check(values_equal(run.slot_values, frozen.at("slot_values")),
              "c10 run slot values carried");
    }

    // ------------------------------------------- 11. recipe_from_spec --
    {
        const Json& frozen = fixture.at("case11_from_spec");
        const we::RecipeDocument default_id = we::recipe_from_spec(
            spec, std::nullopt, "", {}, fixed(fixed_clock));
        check(default_id.recipe_id ==
                  frozen.at("default_id").get<std::string>(),
              "c11 slug id from workflow_id");
        check(default_id.created_at.has_value() &&
                  *default_id.created_at ==
                      frozen.at("default_created_at").get<double>(),
              "c11 clock-injected created_at");
        const we::RecipeDocument custom_id = we::recipe_from_spec(
            spec, std::string("Custom ID!!"), "", {}, fixed(fixed_clock));
        check(custom_id.recipe_id ==
                  frozen.at("custom_id").get<std::string>(),
              "c11 explicit id kept verbatim");
        const we::RecipeDocument empty_id = we::recipe_from_spec(
            spec, std::string(""), "", {}, fixed(fixed_clock));
        check(empty_id.recipe_id ==
                  frozen.at("empty_id_falls_back").get<std::string>(),
              "c11 empty id falls back to slug");
        check(default_id.description ==
                  frozen.at("desc_fallback").get<std::string>(),
              "c11 empty description falls back to workflow.description");
        const we::RecipeDocument with_desc = we::recipe_from_spec(
            spec, std::nullopt, "explicit", {"x"}, fixed(fixed_clock));
        check(with_desc.description ==
                  frozen.at("explicit_desc").get<std::string>(),
              "c11 explicit description kept");
        check(strings_equal(frozen.at("tags"), with_desc.tags),
              "c11 tags carried");
        check(values_equal(default_id.workflow.to_dict(), spec.to_dict()),
              "c11 workflow carried unchanged");
        // unicode slug: "WF.Ünicode 2024" -> "wf.-nicode-2024"
        Json unicode_data = fixture.at("run_spec");
        unicode_data["workflow_id"] = "WF.\xC3\x9C""nicode 2024";
        unicode_data["description"] = "fallback description";
        const ws::WorkflowSpec unicode_spec =
            ws::WorkflowSpec::from_dict(unicode_data);
        const we::RecipeDocument unicode_recipe = we::recipe_from_spec(
            unicode_spec, std::nullopt, "", {}, fixed(fixed_clock));
        check(unicode_recipe.recipe_id ==
                  frozen.at("unicode_slug").get<std::string>(),
              "c11 unicode slug (non-ascii run collapses)");
        check(unicode_recipe.description ==
                  frozen.at("unicode_desc_fallback").get<std::string>(),
              "c11 unicode description fallback");
    }

    // ---------------------------------------------- 12. refusal gates --
    {
        const Json& frozen = fixture.at("case12_refusal_gates");
        // (a) structural refusal at save — nothing written.
        const std::filesystem::path root = make_root();
        we::RecipeDocument smuggler = we::recipe_from_spec(
            spec, std::string("smuggler"), "", {}, fixed(fixed_clock));
        smuggler.workflow.nodes[0].parameters["api_key"] = "k";
        smuggler.workflow.nodes[1].parameters["output_path"] = "/etc/passwd";
        const auto structural = recipe_error_of([&] {
            (void)we::save_recipe(
                smuggler, root / "smuggler.paleo-workflow.json");
        });
        check(structural.first, "c12 structural save refused");
        check(structural.second ==
                  frozen.at("save_structural_message").get<std::string>(),
              "c12 structural save frozen message (\"; \" joined)");
        check(file_count(root) == 0, "c12 structural save wrote nothing");
        // (b) registry validation refusal at save.
        Json unknown_data = fixture.at("spec");
        unknown_data["nodes"] = Json::array({unknown_data["nodes"][0]});
        unknown_data["nodes"][0]["action_id"] = "no.such.action";
        const we::RecipeDocument unknown_action = we::recipe_from_spec(
            ws::WorkflowSpec::from_dict(unknown_data),
            std::string("unknown-action"), "", {}, fixed(fixed_clock));
        const auto registry_refusal = recipe_error_of([&] {
            we::SaveRecipeOptions options;
            options.registry = &registry;
            (void)we::save_recipe(
                unknown_action, root / "unknown.paleo-workflow.json",
                options);
        });
        check(registry_refusal.first, "c12 registry save refused");
        check(registry_refusal.second ==
                  frozen.at("save_registry_message").get<std::string>(),
              "c12 registry save frozen message");
        check(file_count(root) == 0, "c12 registry save wrote nothing");
        // (c) same recipe without a registry -> allowed.
        const std::filesystem::path out = we::save_recipe(
            unknown_action, root / "unknown.paleo-workflow.json");
        check(std::filesystem::exists(out) ==
                  frozen.at("save_no_registry_ok").get<bool>(),
              "c12 registry=None skips spec validation");
        const std::vector<std::string> spec_problems =
            ws::validate_workflow_spec(unknown_action.workflow, registry);
        const std::vector<std::string> recipe_problems =
            we::validate_recipe(unknown_action, registry);
        check(spec_problems == recipe_problems,
              "c12 validate_recipe == structural(empty) + validate_spec");
        // (d) load missing file.
        const auto missing = recipe_error_of([&] {
            (void)we::load_recipe(root / "ghost.paleo-workflow.json");
        });
        check(missing.first, "c12 missing load refused");
        check(missing.second ==
                  frozen.at("load_missing_message").get<std::string>(),
              "c12 missing load frozen message");
        // (e) structural refusal at load (hand-crafted evil payload,
        // mirroring the generator's file).
        Json evil;
        evil["recipe_schema_version"] = "1.0";
        evil["recipe_id"] = "evil";
        evil["name"] = "Evil";
        evil["description"] = "";
        evil["created_at"] = nullptr;
        evil["source_run_id"] = nullptr;
        evil["tags"] = Json::array();
        Json evil_workflow;
        evil_workflow["schema_version"] = "1.0";
        evil_workflow["workflow_id"] = "wf-evil";
        evil_workflow["name"] = "Evil";
        evil_workflow["description"] = "";
        evil_workflow["max_concurrency"] = 1;
        evil_workflow["slots"] = Json::array();
        evil_workflow["nodes"] = Json::array({Json{
            {"node_id", "n1"},
            {"action_id", "test.noop"},
            {"parameters", Json{{"token", "t"}}},
            {"depends_on", Json::array()},
            {"condition", nullptr},
            {"retry", Json{{"max_attempts", 1}, {"backoff_seconds", 0.0}}},
            {"description", ""},
        }});
        evil["workflow"] = std::move(evil_workflow);
        write_file(root / "evil.paleo-workflow.json",
                   evil.dump(1, ' ', false));
        const auto evil_load = recipe_error_of([&] {
            (void)we::load_recipe(root / "evil.paleo-workflow.json");
        });
        check(evil_load.first, "c12 structural load refused");
        check(evil_load.second ==
                  frozen.at("load_structural_message").get<std::string>(),
              "c12 structural load frozen message");
    }

    // -------------------------------------------- 13. from_dict coercions --
    {
        const Json& frozen = fixture.at("case13_from_dict");
        we::RecipeDocument recipe = we::recipe_from_spec(
            spec, std::string("coerce"), "", {"t"}, fixed(fixed_clock));
        recipe.source_run_id = "run-coerce00000000";
        Json d = recipe.to_dict();
        d.erase("name");                       // -> workflow.name
        d.erase("description");                // -> ""
        d.erase("tags");                       // -> ()
        d.erase("source_run_id");              // -> None
        d.erase("created_at");                 // -> None
        d.erase("recipe_schema_version");      // -> "1.0"
        d["workflow"].erase("schema_version");  // migrate injects "1.0"
        // Python's from_dict migrates the input dict IN PLACE (setdefault
        // re-appends workflow.schema_version at the END); the frozen
        // "input" snapshot reflects that post-migration state. The frozen
        // C++ signature returns a migrated COPY, so replay the same
        // observable view explicitly.
        const Json migrated_view = we::migrate_recipe(d);
        check(values_equal(frozen.at("input"), migrated_view),
              "c13 stripped input (post-migrate view)");
        const we::RecipeDocument coerced = we::RecipeDocument::from_dict(d);
        check(coerced.name == frozen.at("name_fallback").get<std::string>(),
              "c13 name falls back to workflow.name");
        check(coerced.description ==
                  frozen.at("description").get<std::string>(),
              "c13 description falls back to ''");
        check(frozen.at("created_at").is_null() &&
                  !coerced.created_at.has_value(),
              "c13 missing created_at -> None");
        check(frozen.at("source_run_id").is_null() &&
                  !coerced.source_run_id.has_value(),
              "c13 missing source_run_id -> None");
        check(strings_equal(frozen.at("tags"), coerced.tags),
              "c13 missing tags -> ()");
        check(coerced.schema_version ==
                  frozen.at("schema_version").get<std::string>(),
              "c13 missing recipe_schema_version -> default");
        check(coerced.workflow.schema_version ==
                  frozen.at("workflow_schema_version").get<std::string>(),
              "c13 migrate injected workflow schema_version");
        check_json(frozen.at("to_dict"), coerced.to_dict(),
                   "c13 coerced to_dict");
    }

    // ------------------------------------------------ negative self-checks --
    // Tamper frozen expectations in memory: every comparator below MUST
    // report a mismatch (proves the frozen comparisons have teeth).
    {
        // (1) tampered checkpoint bytes (c01): one character flip.
        std::string tampered_bytes =
            fixture.at("case01_roundtrip").at("bytes").get<std::string>();
        const std::size_t at = tampered_bytes.find("\"recipe_id\"");
        tampered_bytes.replace(at, 11, "\"recipe_ld\"");
        const we::RecipeDocument recipe1 = we::recipe_from_spec(
            spec, std::nullopt, "round-trip recipe", {"demo", "parity"},
            fixed(fixed_clock));
        negative_check(
            read_file(we::save_recipe(
                recipe1, make_root() / "wf-recipe-parity.json")) !=
                tampered_bytes,
            "tampered c01 bytes must differ");

        // (2) tampered corrupt-JSON message detail (c04): column shift.
        std::string tampered_message =
            fixture.at("case04_corrupt_json")[0].at("message")
                .get<std::string>();
        tampered_message.replace(tampered_message.find("column 2"), 8,
                                 "column 3");
        const std::filesystem::path root4 = make_root();
        write_file(root4 / "broken1.paleo-workflow.json",
                   fixture.at("case04_corrupt_json")[0]
                       .at("raw")
                       .get<std::string>());
        const auto [threw4, message4] = recipe_error_of([&] {
            (void)we::load_recipe(root4 / "broken1.paleo-workflow.json");
        });
        negative_check(threw4 && message4 != tampered_message,
                       "tampered c04 message must differ");

        // (3) tampered diff result (c08): drop the nodes_added entry while
        // the real diff adds one node.
        Json tampered_diff =
            fixture.at("case08_diff").at("changed");
        tampered_diff.erase("nodes_added");
        const we::RecipeDocument base = we::recipe_from_spec(
            spec, std::nullopt, "", {}, fixed(fixed_clock));
        Json changed_data = fixture.at("spec");
        Json extra_node = fixture.at("spec").at("nodes")[0];
        extra_node["node_id"] = "extra_node";
        changed_data["nodes"].push_back(std::move(extra_node));
        negative_check(!values_equal(
                           tampered_diff,
                           we::diff_recipes(
                               base,
                               we::recipe_from_spec(
                                   ws::WorkflowSpec::from_dict(changed_data),
                                   std::string("wf-recipe-parity"), "", {},
                                   fixed(fixed_clock)))),
                       "tampered c08 diff must differ");

        // (4) tampered migrate output (c05): reorder the injected key so
        // only the ORDER comparator can catch it.
        Json reordered = Json::object();
        std::vector<std::string> keys;
        for (const auto& [key, value] :
             fixture.at("case05_migrate")[1].at("migrated").items()) {
            (void)value;
            keys.push_back(key);
        }
        std::swap(keys[keys.size() - 2], keys[keys.size() - 1]);
        for (const std::string& key : keys) {
            reordered[key] =
                fixture.at("case05_migrate")[1].at("migrated").at(key);
        }
        negative_check(
            !key_orders_equal(reordered, we::migrate_recipe(
                                             fixture.at("case05_migrate")[1]
                                                 .at("data"))),
            "tampered c05 key order must be caught");
    }

    if (g_failures == 0) {
        std::printf("ALL %d CHECKS PASSED (+%d negative self-checks)\n",
                    g_checks, g_negative);
        return 0;
    }
    std::printf("FAIL: %d failure(s) of %d checks (+%d negative self-checks)\n",
                g_failures, g_checks, g_negative);
    return 1;
}
