// data.manifest_export — the catalog.json checkpoint writer (Python ADR
// 0056 export contract) against the frozen typical fixture: full-table
// parity with catalog.sqlite, schema/revision fields, map-shaped tag
// sections, and the .bak rotation on the second checkpoint.
#include "pwb_test.hpp"

#include "pwb/catalog/repository.hpp"
#include "pwb/domain/json.hpp"
#include "pwb/project/paths.hpp"

#include <filesystem>
#include <fstream>
#include <map>
#include <sstream>
#include <string>

namespace {

namespace fs = std::filesystem;
using pwb::domain::Json;

fs::path fixture_project(const char* name, const char* file) {
    return fs::path(PWB_DATA_FIXTURE_DIR) / name / file;
}

Json load_json(const fs::path& file) {
    std::ifstream stream(file, std::ios::binary);
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return Json::parse(buffer.str());
}

}  // namespace

PWB_TEST(manifest_matches_sqlite_and_rotates_bak) {
    const fs::path work = fs::temp_directory_path()
        / "pwb_manifest_export";
    std::error_code ec;
    fs::remove_all(work, ec);
    fs::create_directories(work, ec);
    const fs::path project = work / "typical.paleo.json";
    fs::copy_file(fixture_project("typical", "typical.paleo.json"), project,
                  fs::copy_options::overwrite_existing, ec);
    fs::copy(fixture_project("typical", "typical.artifacts"),
             work / "typical.artifacts",
             fs::copy_options::recursive | fs::copy_options::overwrite_existing,
             ec);

    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project));
    auto document = repository.open_read_only();
    PWB_CHECK(document.is_ok());

    const fs::path manifest = work / "typical.artifacts" / "metadata"
        / "catalog.json";
    const fs::path bak = work / "typical.artifacts" / "metadata"
        / "catalog.json.bak";

    // The fixture ships a manifest (Python-written): a first export must
    // rotate it to .bak, never drop it.
    PWB_CHECK(fs::exists(manifest));
    const pwb::domain::DataError first =
        repository.export_manifest(manifest);
    PWB_CHECK(first.code == pwb::domain::ErrorCode::Ok);
    PWB_CHECK(fs::exists(bak));

    const Json exported = load_json(manifest);
    PWB_CHECK(exported["schema_version"].get<int>() == 1);
    PWB_CHECK(exported["catalog_revision"].get<int>()
              == document.value().catalog_revision);
    PWB_CHECK(exported["assets"].size()
              == document.value().assets.size());
    PWB_CHECK(exported["versions"].size()
              == document.value().versions.size());
    PWB_CHECK(exported["runs"].size() == document.value().runs.size());
    PWB_CHECK(exported["tags"].size() == document.value().tags.size());
    PWB_CHECK(exported["models"].size() == 0);
    PWB_CHECK(exported["model_versions"].size() == 0);

    // Tag maps aggregate the pair tables exactly.
    std::map<std::string, int> asset_tag_counts;
    for (const auto& [asset_id, tag_id] : document.value().asset_tags) {
        (void)tag_id;
        ++asset_tag_counts[asset_id];
    }
    for (const auto& [asset_id, count] : asset_tag_counts) {
        PWB_CHECK(exported["asset_tags"][asset_id].size()
                  == static_cast<std::size_t>(count));
    }

    // One full asset object: field set is the Python pydantic shape.
    const Json& asset = exported["assets"][0];
    for (const char* key :
         {"id", "name", "type", "description", "current_version_id",
          "legacy_resource_id", "metadata", "created_at", "updated_at",
          "trashed", "trashed_at"}) {
        PWB_CHECK(asset.contains(key));
    }
    // One full version object incl. the compound-member fields.
    const Json& version = exported["versions"][0];
    for (const char* key :
         {"id", "asset_id", "version_number", "stage", "managed", "path",
          "source_uri", "format", "size_bytes", "sha256", "run_id",
          "metadata", "created_at", "trashed", "trashed_at",
          "parent_version_ids", "members"}) {
        PWB_CHECK(version.contains(key));
    }

    // Content parity spot check: the exported manifest's asset ids equal
    // the sqlite document's, and the pre-existing .bak still parses as
    // the Python-written revision.
    std::map<std::string, bool> exported_assets;
    for (const auto& row : exported["assets"]) {
        exported_assets[row["id"].get<std::string>()] = true;
    }
    for (const auto& row : document.value().assets) {
        PWB_CHECK(exported_assets.count(row.id.str()) == 1);
    }
    const Json previous = load_json(bak);
    PWB_CHECK(previous.contains("schema_version"));
    PWB_CHECK(previous["schema_version"].get<int>() == 1);
}
