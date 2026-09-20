// ui_data_core.facies_groups — CONV-35 replay of the frozen Python oracle
// (facies_groups_oracle.json, generated from the REAL
// paleo_workbench/resources/geojson_layers.py by
// tools/oracle/generate_facies_groups_oracle.py).
//
// Covered: role normalization + filename convention, document summaries,
// group annotation (complete/incomplete groups, warnings, tag rewriting,
// parse-failure non-promotion, subdir scoping, explicit product ids), and
// member ordering.

#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_data_core/facies_groups.hpp>

using pwb::domain::Json;
using namespace pwb::ui_data_core;

#ifndef PWB_FACIES_ORACLE
#error "PWB_FACIES_ORACLE must point at facies_groups_oracle.json"
#endif

static int checks = 0;
static int failures = 0;

#define CHECK(cond)                                                        \
    do {                                                                   \
        ++checks;                                                          \
        if (!(cond)) {                                                     \
            ++failures;                                                    \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);    \
        }                                                                  \
    } while (0)

static Json load_oracle() {
    std::ifstream in(PWB_FACIES_ORACLE);
    if (!in) {
        std::fprintf(stderr, "cannot open oracle: %s\n", PWB_FACIES_ORACLE);
        std::exit(2);
    }
    std::stringstream buffer;
    buffer << in.rdbuf();
    return Json::parse(buffer.str());
}

static bool json_eq(const Json& a, const Json& b) { return a == b; }

static ResourceItem res_from_json(const Json& d) {
    ResourceItem r;
    r.name = d["name"].get<std::string>();
    r.path = d.value("path", r.name);
    r.type = d.value("type", "geojson");
    r.format = d.value("format", "geojson");
    if (d.contains("tags")) {
        for (const auto& t : d["tags"]) r.tags.push_back(t.get<std::string>());
    }
    if (d.contains("parsed_summary")) r.parsed_summary = d["parsed_summary"];
    if (d.contains("artifact_role") && !d["artifact_role"].is_null()) {
        r.artifact_role = d["artifact_role"].get<std::string>();
    }
    return r;
}

static std::optional<std::string> opt_str(const Json& v) {
    return v.is_string() ? std::optional<std::string>(v.get<std::string>())
                         : std::nullopt;
}

int main() {
    const Json oracle = load_oracle();
    CHECK(oracle["schema"] == "pwb.facies_groups_oracle/1");

    // ------------------------------------------------------ normalize --
    for (const auto& row : oracle["normalize"]) {
        const Json& value = row["value"];
        const auto role = normalize_facies_layer_role(value);
        CHECK(opt_str(row["role"]) == role);
    }

    // ------------------------------------------------------ from_name --
    for (const auto& row : oracle["from_name"]) {
        const std::string filename = row["filename"].get<std::string>();
        CHECK(opt_str(row["role"]) == facies_layer_role_from_name(filename));
        CHECK(json_eq(facies_layer_summary_from_name(filename),
                      row["summary"]));
    }

    // ---------------------------------------------------- doc_summary --
    for (const auto& row : oracle["doc_summary"]) {
        const Json summary = geojson_document_summary(
            row["payload"], row["filename"].get<std::string>());
        if (!json_eq(summary, row["summary"])) {
            ++failures;
            std::printf("FAIL doc_summary %s\n  actual   %s\n  expected %s\n",
                        row["name"].get<std::string>().c_str(),
                        summary.dump().c_str(), row["summary"].dump().c_str());
        }
        ++checks;
    }

    // ------------------------------------------------------- grouping --
    for (const auto& row : oracle["grouping"]) {
        std::vector<ResourceItem> added_store;
        std::vector<ResourceItem> existing_store;
        for (const auto& d : row["added"]) added_store.push_back(res_from_json(d));
        for (const auto& d : row["existing"])
            existing_store.push_back(res_from_json(d));
        std::vector<ResourceItem*> added, existing;
        for (auto& r : added_store) added.push_back(&r);
        for (auto& r : existing_store) existing.push_back(&r);

        const std::vector<std::string> warnings =
            annotate_facies_product_groups(added, existing);
        const Json want_warnings = row["warnings"];
        CHECK(warnings.size() == want_warnings.size());
        for (std::size_t i = 0;
             i < std::min(warnings.size(), want_warnings.size()); ++i) {
            CHECK(warnings[i] == want_warnings[i].get<std::string>());
        }

        const Json& after = row["after"];
        CHECK(added.size() == after["added"].size());
        for (std::size_t i = 0; i < added.size(); ++i) {
            const Json& want = after["added"][i];
            CHECK(json_eq(added[i]->parsed_summary, want["parsed_summary"]));
            CHECK(opt_str(want["artifact_role"]) == added[i]->artifact_role);
            Json got_tags = Json(added[i]->tags);
            CHECK(json_eq(got_tags, want["tags"]));
        }
        CHECK(existing.size() == after["existing"].size());
        for (std::size_t i = 0; i < existing.size(); ++i) {
            const Json& want = after["existing"][i];
            CHECK(json_eq(existing[i]->parsed_summary,
                          want["parsed_summary"]));
            CHECK(opt_str(want["artifact_role"]) ==
                  existing[i]->artifact_role);
            CHECK(json_eq(Json(existing[i]->tags), want["tags"]));
        }
    }

    // -------------------------------------------------------- members --
    for (const auto& row : oracle["members"]) {
        std::vector<ResourceItem> pool_store;
        for (const auto& d : row["pool"]) pool_store.push_back(res_from_json(d));
        std::vector<const ResourceItem*> pool;
        for (const auto& r : pool_store) pool.push_back(&r);
        const ResourceItem clicked = res_from_json(row["clicked"]);
        const auto members = facies_group_members(clicked, pool);
        const Json& want = row["member_names"];
        CHECK(members.size() == want.size());
        for (std::size_t i = 0; i < std::min(members.size(), want.size()); ++i) {
            CHECK(members[i]->name == want[i].get<std::string>());
        }
    }

    std::printf("facies_groups: %zu checks, %d failure(s)\n",
                static_cast<std::size_t>(checks), failures);
    return failures == 0 ? 0 : 1;
}
