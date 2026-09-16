// data.oracle_compare — C++ pipeline output vs the committed Python oracle
// dumps, compared semantically (test-plan.md §3): project/model trees,
// catalog rows for every table the C++ side loads, resolve entries.
//
// Known round-1 boundary (handoff §5, test-plan §5): lineage, models,
// model_versions, staging_leases and sync_state have no C++ read model —
// they are reported, not compared. name_search is a derived column, also
// reported only.
#include "compare_json.hpp"
#include "pwb_test.hpp"

#include "pwb/catalog/repository.hpp"
#include "pwb/data/facade.hpp"
#include "pwb/project/manager.hpp"

#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <vector>

namespace {

namespace fs = std::filesystem;
using pwb::domain::Json;

fs::path fixture_dir(const char* name) {
    return fs::path(PWB_DATA_FIXTURE_DIR) / name;
}

Json load_json_file(const fs::path& file) {
    std::ifstream stream(file, std::ios::binary);
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return Json::parse(buffer.str());
}

int g_compared_rows = 0;
int g_skipped_tables = 0;

void check_rows(const Json& tables, const std::string& table,
                const std::map<std::string, Json>& projected,
                const std::vector<std::string>& pk_fields) {
    // Missing table in the oracle dump = empty table (fixtures without a
    // catalog); operator[] would insert null and break iteration.
    const auto found = tables.find(table);
    const Json empty = Json::array();
    const Json& oracle_table = found != tables.end() ? *found : empty;
    PWB_CHECK(oracle_table.size() == projected.size());
    for (const auto& row : oracle_table) {
        // Primary key composed from the table's key columns (const access:
        // a missing key is a hard failure, never an accidental insert).
        std::string key;
        bool key_ok = true;
        for (const auto& field : pk_fields) {
            const auto found = row.find(field);
            if (found == row.end() || !found->is_string()) {
                key_ok = false;
                break;
            }
            if (!key.empty()) key += "\x1f";
            key += found->get<std::string>();
        }
        PWB_CHECK(key_ok);
        if (!key_ok) continue;
        const auto it = projected.find(key);
        PWB_CHECK(it != projected.end());
        if (it == projected.end()) continue;
        // Compare the projected key subset (derived columns excluded).
        for (auto member = it->second.begin(); member != it->second.end();
             ++member) {
            if (!row.contains(member.key())) continue;  // oracle-only column
            const auto diff =
                pwb_test::json_compare(member.value(), row.at(member.key()),
                                       "$." + table + "." + key + "." +
                                           member.key());
            if (diff.has_value()) std::cout << "  DIFF " << *diff << "\n";
            PWB_CHECK(!diff.has_value());
        }
        ++g_compared_rows;
    }
}

Json opt_str(const std::optional<std::string>& value) {
    return value.has_value() ? Json(*value) : Json(nullptr);
}

template <typename Id>
Json opt_id(const std::optional<Id>& value) {
    return value.has_value() ? Json(value->str()) : Json(nullptr);
}

Json project_asset(const pwb::catalog::DataAsset& asset) {
    Json row = Json::object();
    row["id"] = asset.id.str();
    row["name"] = asset.name;
    row["type"] = asset.type;
    row["description"] = asset.description;
    row["current_version_id"] = opt_id(asset.current_version_id);
    row["legacy_resource_id"] = opt_str(asset.legacy_resource_id);
    row["metadata"] = asset.metadata;
    row["created_at"] = asset.created_at;
    row["updated_at"] = asset.updated_at;
    row["trashed"] = asset.trashed ? 1 : 0;
    row["trashed_at"] = opt_str(asset.trashed_at);
    return row;
}

Json project_version(const pwb::catalog::DataVersion& version) {
    Json row = Json::object();
    row["id"] = version.id.str();
    row["asset_id"] = version.asset_id.str();
    row["version_number"] = version.version_number;
    row["stage"] = std::string(pwb::domain::to_string(version.stage));
    row["managed"] = version.managed ? 1 : 0;
    row["path"] = version.path;
    row["source_uri"] = opt_str(version.source_uri);
    row["format"] = version.format;
    row["size_bytes"] =
        version.size_bytes.has_value() ? Json(*version.size_bytes)
                                       : Json(nullptr);
    row["sha256"] = opt_str(version.sha256);
    row["run_id"] = opt_id(version.run_id);
    row["metadata"] = version.metadata;
    row["created_at"] = version.created_at;
    row["trashed"] = version.trashed ? 1 : 0;
    row["trashed_at"] = opt_str(version.trashed_at);
    Json parents = Json::array();
    for (const auto& parent : version.parent_version_ids) {
        parents.push_back(parent.str());
    }
    row["parent_ids"] = std::move(parents);
    return row;
}

Json project_run(const pwb::catalog::DataRun& run) {
    Json row = Json::object();
    row["id"] = run.id.str();
    row["operation"] = run.operation;
    row["parameters"] = run.parameters;
    row["generator"] = run.generator;
    row["status"] = run.status;
    row["model_ref"] = run.model_ref.has_value() ? *run.model_ref
                                                 : Json(nullptr);
    row["created_at"] = run.created_at;
    return row;
}

Json project_tag(const pwb::catalog::Tag& tag) {
    Json row = Json::object();
    row["id"] = tag.id;
    row["name"] = tag.name;
    row["display_name"] = opt_str(tag.display_name);
    row["metadata"] = tag.metadata;
    return row;
}

Json project_member(const std::string& version_id,
                    const pwb::catalog::VersionMember& member) {
    Json row = Json::object();
    row["version_id"] = version_id;
    row["name"] = member.name;
    row["rel_path"] = member.rel_path;
    row["member_role"] = member.member_role;
    row["ordinal"] = member.ordinal;
    row["required"] = member.required ? 1 : 0;
    row["sha256"] = opt_str(member.sha256);
    row["size_bytes"] =
        member.size_bytes.has_value() ? Json(*member.size_bytes)
                                      : Json(nullptr);
    return row;
}

Json project_port(const std::string& run_id, const std::string& direction,
                  const pwb::catalog::RunPort& port) {
    Json row = Json::object();
    row["run_id"] = run_id;
    row["direction"] = direction;
    row["role"] = port.role;
    row["version_id"] = port.version_id.str();
    row["ordinal"] = port.ordinal;
    row["required"] = port.required ? 1 : 0;
    row["entity_type"] = port.entity_type;
    row["entity_id"] = port.entity_id;
    row["note"] = port.note;
    return row;
}

Json project_copy(const pwb::catalog::WorkingCopy& copy) {
    Json row = Json::object();
    row["working_id"] = copy.working_id;
    row["source_version_id"] = copy.source_version_id.str();
    row["path"] = copy.path;
    row["state"] = copy.state;
    row["display_name"] = copy.display_name;
    row["created_at"] = copy.created_at;
    row["updated_at"] = copy.updated_at;
    row["payload_mtime_ns"] =
        copy.payload_mtime_ns.has_value() ? Json(*copy.payload_mtime_ns)
                                          : Json(nullptr);
    row["source_size_bytes"] =
        copy.source_size_bytes.has_value() ? Json(*copy.source_size_bytes)
                                           : Json(nullptr);
    return row;
}

void compare_fixture(const char* name, const char* project_file) {
    const fs::path dir = fixture_dir(name);
    // ---- project/model trees: C++ normalized root vs Python model dump.
    pwb::project::ProjectManager manager(dir / project_file);
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());
    if (!loaded.is_ok()) return;
    const Json oracle_model =
        load_json_file(dir / "oracle_model_dump.json")["model"];
    const auto tree_diff = pwb_test::json_compare(
        loaded.value().document.root(), oracle_model, "$.model");
    PWB_CHECK(!tree_diff.has_value());
    // ---- resolve entries.
    pwb::data::DataFacade facade(dir / project_file);
    auto snapshot = facade.open_snapshot();
    PWB_CHECK(snapshot.is_ok());
    if (!snapshot.is_ok()) return;
    const Json oracle_resolve = load_json_file(dir / "oracle_resolve.json");
    const Json& entries = oracle_resolve.contains("entries")
                              ? oracle_resolve["entries"]
                              : oracle_resolve;
    std::map<std::string, const pwb::data::ResourceStatusV1*> by_id;
    for (const auto& resource : snapshot.value().resources) {
        by_id[resource.id] = &resource;
    }
    for (const auto& entry : entries) {
        const std::string id = entry["id"].get<std::string>();
        const auto it = by_id.find(id);
        PWB_CHECK(it != by_id.end());
        if (it == by_id.end()) continue;
        PWB_CHECK(it->second->stored_path ==
                  entry["stored"].get<std::string>());
        PWB_CHECK(it->second->resolved_path ==
                  entry["resolved"].get<std::string>());
        PWB_CHECK(it->second->exists == entry["exists"].get<bool>());
        ++g_compared_rows;
    }
    // ---- catalog rows.
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(dir / project_file));
    auto document = repository.open_read_only();
    if (!document.is_ok()) {
        // Fixtures without a catalog (minimal) have nothing to compare.
        return;
    }
    const Json tables =
        load_json_file(dir / "oracle_catalog_dump.json")["tables"];
    std::map<std::string, Json> assets, versions, runs, tags, members,
        inputs, outputs, ports, copies,atag,vtag;
    for (const auto& asset : document.value().assets) {
        assets[asset.id.str()] = project_asset(asset);
    }
    for (const auto& version : document.value().versions) {
        versions[version.id.str()] = project_version(version);
        for (const auto& member : version.members) {
            members[version.id.str() + "\x1f" + member.name] =
                project_member(version.id.str(), member);
        }
    }
    for (const auto& run : document.value().runs) {
        runs[run.id.str()] = project_run(run);
        for (const auto& input : run.input_version_ids) {
            inputs[run.id.str() + "\x1f" + input.str()] =
                Json{{"run_id", run.id.str()},
                     {"version_id", input.str()}};
        }
        for (const auto& output : run.output_version_ids) {
            outputs[run.id.str() + "\x1f" + output.str()] =
                Json{{"run_id", run.id.str()},
                     {"version_id", output.str()}};
        }
        for (const auto& port : run.input_ports) {
            ports[run.id.str() + "\x1finput\x1f" +
                  std::to_string(port.ordinal)] =
                project_port(run.id.str(), "input", port);
        }
        for (const auto& port : run.output_ports) {
            ports[run.id.str() + "\x1foutput\x1f" +
                  std::to_string(port.ordinal)] =
                project_port(run.id.str(), "output", port);
        }
    }
    for (const auto& tag : document.value().tags) {
        tags[tag.id] = project_tag(tag);
    }
    for (const auto& pair : document.value().asset_tags) {
        atag[pair.first + "\x1f" + pair.second] =
            Json{{"asset_id", pair.first}, {"tag_id", pair.second}};
    }
    for (const auto& pair : document.value().version_tags) {
        vtag[pair.first + "\x1f" + pair.second] =
            Json{{"version_id", pair.first}, {"tag_id", pair.second}};
    }
    for (const auto& copy : document.value().working_copies) {
        copies[copy.working_id] = project_copy(copy);
    }
    check_rows(tables, "assets", assets, {"id"});
    check_rows(tables, "versions", versions, {"id"});
    check_rows(tables, "runs", runs, {"id"});
    check_rows(tables, "tags", tags, {"id"});
    check_rows(tables, "asset_tags", atag, {"asset_id", "tag_id"});
    check_rows(tables, "version_tags", vtag, {"version_id", "tag_id"});
    check_rows(tables, "version_members", members, {"version_id", "name"});
    check_rows(tables, "working_copies", copies, {"working_id"});
    // run_inputs/outputs keyed by (run_id, version_id).
    check_rows(tables, "run_inputs", inputs, {"run_id", "version_id"});
    check_rows(tables, "run_outputs", outputs, {"run_id", "version_id"});
    // run_ports keyed by (run_id, direction, ordinal) here vs oracle rows
    // keyed (run_id, version_id): re-key oracle side for the comparison.
    {
        std::map<std::string, Json> oracle_ports;
        const auto ports_found = tables.find("run_ports");
        const Json ports_empty = Json::array();
        const Json& oracle_table =
            ports_found != tables.end() ? *ports_found : ports_empty;
        for (const auto& row : oracle_table) {
            // ordinal is unique per (run, direction) in the fixture.
            int ordinal = row["ordinal"].get<int>();
            std::string direction = row["direction"].get<std::string>();
            oracle_ports[row["run_id"].get<std::string>() + "\x1f" +
                         direction + "\x1f" + std::to_string(ordinal)] = row;
        }
        PWB_CHECK(oracle_ports.size() == ports.size());
        for (const auto& [key, projected] : ports) {
            const auto it = oracle_ports.find(key);
            PWB_CHECK(it != oracle_ports.end());
            if (it == oracle_ports.end()) continue;
            for (auto member = projected.begin();
                 member != projected.end(); ++member) {
                if (!it->second.contains(member.key())) continue;
                const auto diff = pwb_test::json_compare(
                    member.value(), it->second.at(member.key()),
                    "$.run_ports." + key + "." + member.key());
                if (diff.has_value()) std::cout << "  DIFF " << *diff << "\n";
                PWB_CHECK(!diff.has_value());
            }
            ++g_compared_rows;
        }
    }
    // Documented round-1 boundary: no C++ read model for these tables.
    for (const char* table :
         {"lineage", "models", "model_versions", "staging_leases",
          "sync_state"}) {
        if (tables.contains(table)) ++g_skipped_tables;
    }
}

}  // namespace

PWB_TEST(compare_typical) {
    compare_fixture("typical", "typical.paleo.json");
}
PWB_TEST(compare_minimal) {
    compare_fixture("minimal", "minimal.paleo.json");
}
PWB_TEST(compare_unicode_paths) {
    compare_fixture("unicode_paths", "unicode_paths.paleo.json");
}
PWB_TEST(compare_legacy_abs_paths) {
    compare_fixture("legacy_abs_paths", "legacy_abs_paths.paleo.json");
}
PWB_TEST(compare_missing_resource) {
    compare_fixture("missing_resource", "typical.paleo.json");
}
PWB_TEST(compare_future_schema) {
    compare_fixture("future_schema", "typical.paleo.json");
}

PWB_TEST(report_coverage) {
    std::cout << "  compared rows/entries: " << g_compared_rows
              << ", unloaded tables reported: " << g_skipped_tables << "\n";
    PWB_CHECK(g_compared_rows > 50);
}
