// CONV-32 workflow_interpretation compilation oracle replay test (task I7).
//
// Replays libs/workflow_interpretation/workflow_interpretation_tests/
// fixtures/workflow_interpretation_compilation_oracle.json (frozen from
// the REAL Python implementation — paleo_workbench/workflow/interpretation/
// compilation.py over the evidence + constraint_versions chain — by
// tools/oracle/generate_workflow_interpretation_compilation_fixtures.py)
// through the C++ port and compares against the frozen expectation:
// semantic JSON equality plus raise parity (python_class "ValueError" +
// verbatim message — Chinese text, fullwidth '：'/'；' separators).
//
// Scenario reconstruction: each case's input carries the full document
// Json view, the evidence-catalog version map, and (for the constraint
// floating cases) the repo_setup group list — committed through the REAL
// workflow_runtime commit path into a RuntimeStore, whose deterministic
// id scheme (ver_000001…) is the one the Python fake service used. The
// ResolveContext is assembled exactly like the Python call sites:
//   catalog None            → nullopt resolver + null repository
//   _FakeCatalog(versions)  → map-backed resolver, null repository
//   OracleCatalog(service)  → map resolver + RuntimeStore repository,
//                             constraint verdicts via the real
//                             resolve_constraint_ref.
//
// Includes comparator NEGATIVE SELF-CHECKS: frozen expectations are
// tampered with in memory and the comparator must flag every one — a
// green replay then proves the comparisons can actually fail.

#include <pwb/domain/json.hpp>
#include <pwb/workflow_graph/evidence.hpp>
#include <pwb/workflow_interpretation/compilation.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>
#include <pwb/workflow_runtime/constraint_versions.hpp>

#include <cstdio>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using pwb::domain::Json;
using pwb::workflow_graph::EvidenceValueError;
using pwb::workflow_graph::VersionInfo;
using pwb::workflow_interpretation::CompilationInputSet;
using pwb::workflow_interpretation::CompilationValueError;
using pwb::workflow_interpretation::ResolveContext;
using pwb::workflow_interpretation::active_input_set;
using pwb::workflow_interpretation::create_input_set;
using pwb::workflow_interpretation::create_input_set_shell_from_legacy;
using pwb::workflow_interpretation::evidence_view;
using pwb::workflow_interpretation::freeze_input_set;
using pwb::workflow_interpretation::input_sets_for_document;
using pwb::workflow_interpretation::persist_input_set;
using pwb::workflow_interpretation::validate_input_set;
using pwb::workflow_runtime::CatalogRepository;
using pwb::workflow_runtime::RuntimeStore;

int g_failures = 0;
int g_checks = 0;

Json read_fixture(const char* path) {
    std::ifstream in(path);
    if (!in) {
        throw std::runtime_error(std::string("cannot open fixture: ") + path);
    }
    Json data;
    try {
        in >> data;
    } catch (const std::exception& exc) {
        throw std::runtime_error(std::string("fixture parse error: ") +
                                 exc.what());
    }
    return data;
}

// Compare after a dump/parse round-trip so int/unsigned spellings collapse
// exactly like Python's JSON serialization did for the frozen side.
bool json_eq(const Json& got, const Json& expect) {
    return pwb::domain::json_semantically_equal(Json::parse(got.dump()),
                                                expect);
}

bool compare(const std::string& id, const Json& got, const Json& expect,
             bool quiet) {
    if (json_eq(got, expect)) return true;
    if (!quiet) {
        const auto diff =
            pwb::domain::json_semantic_diff(Json::parse(got.dump()), expect);
        std::printf("FAIL %s at %s: %s\n  got:    %s\n  expect: %s\n",
                    id.c_str(), diff.path.c_str(), diff.reason.c_str(),
                    got.dump().c_str(), expect.dump().c_str());
        ++g_failures;
    }
    return false;
}

// ------------------------------------------------------------- raise parity

Json raise_json(const std::exception& exc) {
    return Json{{"python_class", "ValueError"}, {"message", exc.what()}};
}

// capture(): {"result": <json>} or {"raise": {python_class, message}} —
// the ValueError-parity types of this slice are CompilationValueError
// (freeze refusals) and EvidenceValueError (malformed selectors).
template <typename F>
Json capture(F&& f) {
    try {
        return Json{{"result", f()}};
    } catch (const CompilationValueError& exc) {
        return Json{{"raise", raise_json(exc)}};
    } catch (const EvidenceValueError& exc) {
        return Json{{"raise", raise_json(exc)}};
    }
}

// ------------------------------------------------------ scenario rebuild

// Assemble the ResolveContext the Python call site had. `input` is the
// case (or sub-spec) carrying "catalog" ({versions: {vid: asset_id}} or
// null) and "repo_setup" (committed group list or null). The repository
// (RuntimeStore) is committed through the REAL C++ lifecycle so version
// ids match the Python fake (ver_000001…).
void build_context(const Json& input, ResolveContext& ctx,
                   std::unique_ptr<RuntimeStore>& repo) {
    const Json catalog =
        input.contains("catalog") ? input.at("catalog") : Json(nullptr);
    if (catalog.is_object() && catalog.contains("versions") &&
        catalog.at("versions").is_object()) {
        auto assets =
            std::make_shared<std::map<std::string, std::string>>();
        for (auto it = catalog.at("versions").begin();
             it != catalog.at("versions").end(); ++it) {
            (*assets)[it.key()] = it.value().get<std::string>();
        }
        ctx.catalog =
            [assets](const std::string& version_id)
            -> std::optional<VersionInfo> {
            const auto it = assets->find(version_id);
            if (it == assets->end()) return std::nullopt;
            return VersionInfo{it->second, ""};
        };
    }
    const Json setup =
        input.contains("repo_setup") ? input.at("repo_setup") : Json(nullptr);
    CatalogRepository* repo_ptr = nullptr;
    if (setup.is_array() && !setup.empty()) {
        repo = std::make_unique<RuntimeStore>();
        for (const auto& group : setup) {
            const auto report =
                pwb::workflow_runtime::commit_constraint_group(*repo, group,
                                                               "oracle-setup");
            (void)report;  // committed state is probed via current_constraint
        }
        repo_ptr = repo.get();
    }
    ctx.repository = repo_ptr;
    ctx.constraint_resolver =
        [repo_ptr](const Json& document, const std::string& ref) {
            return pwb::workflow_runtime::resolve_constraint_ref(document,
                                                                 repo_ptr,
                                                                 ref);
        };
}

CompilationInputSet create_from(const Json& spec, const Json& document,
                                const ResolveContext& ctx) {
    std::vector<std::string> selectors;
    for (const auto& s : spec.at("selectors")) {
        selectors.push_back(s.get<std::string>());
    }
    return create_input_set(
        document, selectors, ctx, spec.value("name", std::string("")),
        spec.value("created_by", std::string("")),
        spec.value("set_id", std::string("")),
        spec.value("now", std::string("")));
}

Json pairs_json(const std::vector<std::pair<std::string, std::string>>& pairs) {
    Json out = Json::array();
    for (const auto& [key, value] : pairs) {
        out.push_back(Json::array({key, value}));
    }
    return out;
}

// --------------------------------------------------------------- dispatch

bool dispatch(const std::string& id, const std::string& fn,
              const Json& input, const Json& expect, bool quiet) {
    if (fn == "create_input_set") {
        const Json& document = input.at("document");
        std::unique_ptr<RuntimeStore> repo;
        ResolveContext ctx;
        build_context(input, ctx, repo);
        Json got = capture([&] {
            return create_from(input, document, ctx).to_dict();
        });
        return compare(id, got, expect, quiet);
    }
    if (fn == "create_and_validate") {
        const Json& document = input.at("document");
        std::unique_ptr<RuntimeStore> repo;
        ResolveContext ctx;
        build_context(input, ctx, repo);
        CompilationInputSet set = create_from(input, document, ctx);
        const auto validation = validate_input_set(set, document, ctx);
        return compare(
            id,
            Json{{"created", set.to_dict()},
                 {"validation", validation.to_dict()}},
            expect, quiet);
    }
    if (fn == "freeze") {
        const Json& document = input.at("document");
        std::unique_ptr<RuntimeStore> repo;
        ResolveContext ctx;
        build_context(input, ctx, repo);
        const std::string freeze_now =
            input.value("freeze_now", std::string(""));
        CompilationInputSet set = create_from(input, document, ctx);
        Json created = set.to_dict();
        Json outcome = capture([&] {
            freeze_input_set(set, document, ctx, freeze_now);
            return set.to_dict();
        });
        Json post = Json::object();
        post["frozen"] = set.frozen;
        post["selectors"] = set.selectors();
        Json pins = Json::array();
        for (const auto& entry : set.entries) {
            pins.push_back(entry.pinned_version_id);
        }
        post["pins"] = pins;
        Json second = Json(nullptr);
        if (input.value("second_freeze", false)) {
            second = capture([&] {
                freeze_input_set(set, document, ctx);
                return set.to_dict();
            });
        }
        return compare(id,
                       Json{{"created", std::move(created)},
                            {"outcome", std::move(outcome)},
                            {"post", std::move(post)},
                            {"second", std::move(second)}},
                       expect, quiet);
    }
    if (fn == "persist_and_query") {
        Json document = input.at("document");
        const Json& first_spec = input.at("first");
        std::unique_ptr<RuntimeStore> repo;
        ResolveContext ctx;
        build_context(first_spec, ctx, repo);
        const CompilationInputSet first = create_from(first_spec, document,
                                                      ctx);
        persist_input_set(document, first);
        const CompilationInputSet second =
            CompilationInputSet::from_dict(input.at("second"));
        persist_input_set(document, second);
        const auto active = active_input_set(document);
        Json all_ids = Json::array();
        for (const auto& s : input_sets_for_document(document)) {
            all_ids.push_back(s.id);
        }
        return compare(
            id,
            Json{{"document_sets", document.at("compilation_input_sets")},
                 {"active", active.has_value() ? active->to_dict()
                                               : Json(nullptr)},
                 {"all_ids", all_ids},
                 {"legacy_active", Json(nullptr)}},
            expect, quiet);
    }
    if (fn == "evidence_view_and_shell") {
        // (a) structured: create + persist an active set, then the view.
        const Json& st = input.at("structured");
        Json document = st.at("document");
        std::unique_ptr<RuntimeStore> repo;
        ResolveContext ctx;
        build_context(st, ctx, repo);
        const CompilationInputSet set = create_from(st, document, ctx);
        persist_input_set(document, set);
        const Json structured = pairs_json(evidence_view(document, nullptr));
        // (b) legacy fallback + (c) no workspace → empty.
        const Json& fb = input.at("fallback");
        Json fb_document = fb.at("document");
        const Json ws = fb.at("workspace_state");
        const Json fallback = pairs_json(evidence_view(fb_document, &ws));
        const Json empty = pairs_json(evidence_view(fb_document, nullptr));
        // (d) shell migration from the legacy workspace dict.
        const Json& sh = input.at("shell");
        Json shell_document = sh.at("document");
        const Json ws3 = sh.at("workspace_state");
        const std::string id_suffix = sh.at("id_suffix").get<std::string>();
        const auto shell = create_input_set_shell_from_legacy(
            shell_document, ws3, sh.value("created_by", std::string("")),
            [&id_suffix] { return id_suffix; });
        return compare(
            id,
            Json{{"structured", structured},
                 {"fallback", fallback},
                 {"empty", empty},
                 {"shell",
                  shell.has_value() ? shell->to_dict() : Json(nullptr)},
                 {"shell_document_sets",
                  shell_document.at("compilation_input_sets")}},
            expect, quiet);
    }
    std::printf("FAIL %s: unknown fn '%s'\n", id.c_str(), fn.c_str());
    ++g_failures;
    return false;
}

// --------------------------------------------------- comparator negative run

Json& json_pointer_get(Json& root, const std::vector<std::string>& tokens) {
    Json* cur = &root;
    for (const std::string& token : tokens) {
        if (cur->is_array()) {
            cur = &(*cur)[static_cast<std::size_t>(std::stoul(token))];
        } else {
            cur = &(*cur)[token];
        }
    }
    return *cur;
}

std::vector<std::string> split_pointer(const std::string& json_pointer) {
    std::vector<std::string> tokens;
    std::string rest = json_pointer;
    while (!rest.empty()) {
        const std::size_t slash = rest.find('/');
        if (slash == std::string::npos) {
            tokens.push_back(rest);
            break;
        }
        tokens.push_back(rest.substr(0, slash));
        rest = rest.substr(slash + 1);
    }
    return tokens;
}

bool negative_tamper(const Json& fixture, const std::string& case_id,
                     const std::string& json_pointer,
                     const Json& tampered_value) {
    for (const Json& cs : fixture.at("cases")) {
        if (cs.at("id").get<std::string>() != case_id) continue;
        Json mutated = cs;
        json_pointer_get(mutated.at("expect"), split_pointer(json_pointer)) =
            tampered_value;
        const bool caught = !dispatch(case_id + ".tampered",
                                      cs.at("fn").get<std::string>(),
                                      cs.at("input"), mutated.at("expect"),
                                      /*quiet=*/true);
        if (!caught) {
            std::printf("FAIL negative self-check: tamper of %s at %s was "
                        "NOT caught\n",
                        case_id.c_str(), json_pointer.c_str());
            ++g_failures;
        }
        return caught;
    }
    std::printf("FAIL negative self-check: case %s not found\n",
                case_id.c_str());
    ++g_failures;
    return false;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: %s <fixture.json>\n", argv[0]);
        return 2;
    }
    const Json fixture = read_fixture(argv[1]);

    int cases = 0;
    for (const Json& cs : fixture.at("cases")) {
        ++cases;
        ++g_checks;
        dispatch(cs.at("id").get<std::string>(),
                 cs.at("fn").get<std::string>(), cs.at("input"),
                 cs.at("expect"), /*quiet=*/false);
    }

    int negatives = 0;
    if (negative_tamper(fixture, "create_honest_snapshots",
                        "result/entries/1/status_at_add", Json("floating"))) {
        ++negatives;
    }
    if (negative_tamper(fixture, "freeze_floating_refusal_message",
                        "outcome/raise/message",
                        Json("输入集冻结被拒绝——以下证据无法钉住版本：TAMPERED"))) {
        ++negatives;
    }
    if (negative_tamper(fixture, "freeze_floating_single_group_success",
                        "outcome/result/entries/0/pinned_version_id",
                        Json("ver_999999"))) {
        ++negatives;
    }
    if (negative_tamper(fixture, "persist_active_flip_and_legacy",
                        "document_sets/0/active", Json(true))) {
        ++negatives;
    }

    if (g_failures != 0) {
        std::printf("%d/%d checks FAILED (%d fixture cases)\n", g_failures,
                    g_checks, cases);
        return 1;
    }
    std::printf("ALL %d CHECKS PASSED (+%d negative self-checks)\n", g_checks,
                negatives);
    return 0;
}
