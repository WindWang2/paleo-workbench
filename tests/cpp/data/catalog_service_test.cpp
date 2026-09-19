// data.catalog_service — conv-31b oracle replay (catalog service/db deep
// core: DirtySet/apply_changes/reconcile/rebuild/sync, the lazy reads +
// SQL query surface, the manifest ladder, open health matrix, resolve
// ladder, _CatalogMaps asymmetries, _save/_BatchSave/CAS, working copies,
// trash/restore/purge, the model registry, promote and the V11 bundle
// orchestration) against the fixtures frozen by
// tools/oracle/generate_catalog_service_fixtures.py, plus a negative
// self-check (tampered oracle values MUST be detected).
//
// Replay conventions (R10 manual §③ + generator docstring):
//  * {ROOT} stands for this run's mkdtemp scenario root; every string the
//    oracle froze with {ROOT} is re-rooted on the expected side.
//  * Random generated ids (asset_/ver_/run_/model_/mver_<12hex>,
//    wc-<12hex>) were renumbered by the generator to <prefix>_g<N>. The
//    replay substitutes the frozen placeholders with its OWN generated
//    ids per section (the gN -> entity mapping is unambiguous inside each
//    section), so assertions stay referential instead of positional.
//  * Error messages are asserted byte-identically (Chinese included). The
//    parser-specific parenthesized detail of manifest corrupt errors is
//    oracle-masked per findings §E B-14 (skeleton stays byte-identical).
//  * Known bounded divergences are asserted in their frozen DIRECTION and
//    marked with the §E entry (B-4 ASCII fold). db_reconcile_drift's
//    lineage_known_divergence is itself a frozen honest Python behavior
//    and is reproduced as-is.
//  * Pointer discipline (CONV-31b Wave4): entity pointers from add_*/find_*
//    are node-stable across invalidate_maps() folds (kept entities keep
//    their addresses); pointers into document() lists still die on the next
//    re-materialize (a real mutation: core.add_*/remove_* — find_* is a
//    pure read and does NOT re-materialize anymore). Held document-list
//    pointers are only used within one cache lifetime; everything else
//    re-finds by id.
#include "compare_json.hpp"
#include "pwb_test.hpp"

#include "pwb/catalog/apply_changes.hpp"
#include "pwb/domain/sha256.hpp"
#include "pwb/catalog/asset_metadata.hpp"
#include "pwb/catalog/checksum.hpp"
#include "pwb/catalog/dedup.hpp"
#include "pwb/catalog/document_index.hpp"
#include "pwb/catalog/model_registry.hpp"
#include "pwb/catalog/queries.hpp"
#include "pwb/catalog/queries_sql.hpp"
#include "pwb/catalog/repository.hpp"
#include "pwb/catalog/resolve.hpp"
#include "pwb/catalog/service_core.hpp"
#include "pwb/catalog/trash_service.hpp"
#include "pwb/catalog/v11_bundle.hpp"
#include "pwb/catalog/v11_policy.hpp"
#include "pwb/catalog/version_promote.hpp"
#include "pwb/catalog/working_copy.hpp"
#include "pwb/project/paths.hpp"

#include <sys/stat.h>
#include <sys/types.h>
#include <utime.h>
#include <fcntl.h>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <functional>
#include <iostream>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

using namespace pwb;
using namespace pwb::catalog;
namespace fs = std::filesystem;

namespace {

constexpr const char* kTs = "2024-01-01T00:00:00+00:00";   // entity clock
constexpr const char* kNow = "2024-06-01T00:00:00+00:00";  // service clock

fs::path g_root;        // scenario temp root ({ROOT} in the oracle)
domain::Json g_oracle;
domain::Json g_actual;  // section actuals for the negative self-check

#define PWB_TEST_ASSERT(cond, msg)                                         \
    do { const bool pwb_result_ = static_cast<bool>(cond);                 \
         if (!pwb_result_) std::cout << "  FAIL " << (msg) << "\n";         \
         ::pwb_test::check(pwb_result_, #cond, __FILE__, __LINE__); } while (0)
#define PWB_TEST_FAIL(msg) PWB_TEST_ASSERT(false, msg)

void expect_json(const char* section, const domain::Json& actual,
                 const domain::Json& expected) {
    if (auto diff = ::pwb_test::json_compare(expected, actual)) {
        PWB_TEST_FAIL(std::string(section) + ": " + *diff);
    }
}

domain::Json load_json(const fs::path& path) {
    std::ifstream in(path);
    PWB_TEST_ASSERT(in, "cannot open " + path.string());
    return domain::Json::parse(std::string(std::istreambuf_iterator<char>(in),
                                           std::istreambuf_iterator<char>()));
}

const domain::Json& o(const char* key) { return g_oracle.at(key); }

void keep_actual(const char* key, const domain::Json& value) {
    g_actual[key] = value;
}

void ensure_init() {
    static bool done = false;
    if (done) return;
    done = true;
    const char* fixture_dir = getenv("PWB_DATA_FIXTURE_DIR");
    const fs::path fixtures =
        fixture_dir != nullptr
            ? fs::path(fixture_dir)
            : fs::path(__FILE__).parent_path() / "fixtures";
    g_oracle = load_json(fixtures / "catalog_service" / "oracle.json");
    char pattern[] = "/tmp/catalog-service-replay-XXXXXX";
    char* made = mkdtemp(pattern);
    if (made == nullptr) {
        std::cerr << "temp root create failed\n";
        std::exit(2);
    }
    g_root = made;
}

std::string rooted(const std::string& text) {
    std::string out = text;
    const std::string token = "{ROOT}";
    std::size_t at = 0;
    while ((at = out.find(token, at)) != std::string::npos) {
        out.replace(at, token.size(), g_root.string());
        at += g_root.string().size();
    }
    return out;
}

// Inverse of rooted() for keeping comparable actuals.
void mask_root_json(domain::Json& value) {
    if (value.is_string()) {
        std::string text = value.get<std::string>();
        std::size_t at = 0;
        while ((at = text.find(g_root.string(), at)) != std::string::npos) {
            text.replace(at, g_root.string().size(), "{ROOT}");
            at += 6;
        }
        value = text;
    } else if (value.is_array()) {
        for (auto& entry : value) mask_root_json(entry);
    } else if (value.is_object()) {
        for (auto it = value.begin(); it != value.end(); ++it) {
            mask_root_json(it.value());
        }
    }
}

// Recursively re-root every string value of a JSON tree.
void root_json(domain::Json& value) {
    if (value.is_string()) {
        value = rooted(value.get<std::string>());
    } else if (value.is_array()) {
        for (auto& entry : value) root_json(entry);
    } else if (value.is_object()) {
        for (auto it = value.begin(); it != value.end(); ++it) {
            root_json(it.value());
        }
    }
}

// Substitute the oracle's generated-id placeholders with this run's real
// ids (substring replacement over every string value).
void subst_ids(domain::Json& value,
               const std::vector<std::pair<std::string, std::string>>& ids) {
    if (value.is_string()) {
        std::string text = value.get<std::string>();
        for (const auto& [from, to] : ids) {
            std::size_t at = 0;
            while ((at = text.find(from, at)) != std::string::npos) {
                text.replace(at, from.size(), to);
                at += to.size();
            }
        }
        value = text;
    } else if (value.is_array()) {
        for (auto& entry : value) subst_ids(entry, ids);
    } else if (value.is_object()) {
        for (auto it = value.begin(); it != value.end(); ++it) {
            subst_ids(it.value(), ids);
        }
    }
}

// Expected copy for a section: {ROOT} re-rooted + placeholders substituted.
domain::Json expected_json(
    const char* key,
    const std::vector<std::pair<std::string, std::string>>& ids = {}) {
    domain::Json expected = o(key);
    root_json(expected);
    if (!ids.empty()) subst_ids(expected, ids);
    return expected;
}

std::string sha_bytes(const std::string& bytes) {
    return domain::Sha256::of_bytes(bytes);
}

std::optional<std::int64_t> mtime_ns_of(const fs::path& path) {
    struct ::stat st {};
    if (::stat(path.c_str(), &st) != 0) return std::nullopt;
    return static_cast<std::int64_t>(st.st_mtim.tv_sec) * 1000000000LL +
           static_cast<std::int64_t>(st.st_mtim.tv_nsec);
}

// ---- raw sqlite helpers (generator touch #3 equivalents) ------------------

void raw_exec(const fs::path& db_path, const std::string& sql) {
    auto opened = Database::open(db_path, SqliteOpenMode::ReadWrite);
    PWB_TEST_ASSERT(opened.is_ok(), "raw_exec open " + db_path.string());
    domain::DataError error = opened.value().execute(sql);
    PWB_TEST_ASSERT(error.code == domain::ErrorCode::Ok,
                    "raw_exec: " + sql + " -> " + error.message);
}

int count_rows(Database& db, const std::string& table,
               const std::string& where = "") {
    std::string sql = "SELECT count(*) FROM " + table;
    if (!where.empty()) sql += " WHERE " + where;
    Statement row = db.prepare(sql);
    PWB_TEST_ASSERT(row.is_valid(), "count prepare");
    row.step();
    return static_cast<int>(row.int64(0));
}

std::vector<std::string> column_texts(Database& db, const std::string& sql) {
    std::vector<std::string> out;
    Statement row = db.prepare(sql);
    PWB_TEST_ASSERT(row.is_valid(), "texts prepare: " + sql);
    while (row.step()) out.push_back(row.text(0));
    return out;
}

// Full deterministic store dump (rowid order; sync_state by key) with the
// schema's column order — the exact shape the generator froze.
domain::Json dump_store(Database& db) {
    struct Spec {
        const char* table;
        const char* columns;
        std::vector<int> numeric;  // column indexes serialized as integers
        bool by_key;
    };
    const std::vector<Spec> specs = {
        {"assets",
         "id, name, name_search, type, description, current_version_id,"
         " legacy_resource_id, metadata, created_at, updated_at, trashed,"
         " trashed_at",
         {10}, false},
        {"versions",
         "id, asset_id, version_number, stage, managed, path, source_uri,"
         " format, size_bytes, sha256, run_id, metadata, created_at,"
         " trashed, trashed_at, parent_ids",
         {2, 4, 8, 13}, false},
        {"runs",
         "id, operation, parameters, generator, status, model_ref,"
         " created_at",
         {}, false},
        {"run_inputs", "run_id, version_id", {}, false},
        {"run_outputs", "run_id, version_id", {}, false},
        {"run_ports",
         "run_id, direction, role, version_id, ordinal, required,"
         " entity_type, entity_id, note",
         {4, 5}, false},
        {"version_members",
         "version_id, name, rel_path, member_role, ordinal, required,"
         " sha256, size_bytes",
         {4, 5, 7}, false},
        {"tags", "id, name, display_name, metadata", {}, false},
        {"asset_tags", "asset_id, tag_id", {}, false},
        {"version_tags", "version_id, tag_id", {}, false},
        {"lineage", "parent_version_id, child_version_id", {}, false},
        {"models",
         "id, model_id, model_name, model_type, capability, provider,"
         " status, metadata, created_at, provenance",
         {}, false},
        {"model_versions",
         "id, model_id, model_version, artifact_uri, checksum, input_schema,"
         " output_schema, preprocessing_version, runtime, deterministic,"
         " demo_only, status, metadata, created_at, provenance",
         {9, 10}, false},
        {"sync_state", "key, value", {}, true},
    };
    domain::Json out = domain::Json::object();
    for (const Spec& spec : specs) {
        const std::string sql =
            std::string("SELECT ") + spec.columns + " FROM " + spec.table +
            (spec.by_key ? " ORDER BY key" : " ORDER BY rowid");
        domain::Json rows = domain::Json::array();
        Statement row = db.prepare(sql);
        PWB_TEST_ASSERT(row.is_valid(), std::string("dump ") + spec.table);
        while (row.step()) {
            domain::Json values = domain::Json::array();
            for (int i = 0; i < row.column_count(); ++i) {
                if (row.is_null(i)) {
                    values.push_back(nullptr);
                } else if (std::find(spec.numeric.begin(),
                                     spec.numeric.end(),
                                     i) != spec.numeric.end()) {
                    values.push_back(row.int64(i));
                } else {
                    values.push_back(row.text(i));
                }
            }
            rows.push_back(std::move(values));
        }
        out[spec.table] = std::move(rows);
    }
    return out;
}

domain::Json sync_state_json(Database& db) {
    domain::Json out = domain::Json::object();
    for (const char* key :
         {"schema_version", "catalog_revision", "index_schema_version"}) {
        auto value = read_sync_state(db, key);
        out[key] = value.has_value() ? domain::Json(std::to_string(*value))
                                     : domain::Json(nullptr);
    }
    return out;
}

const char* health_text(StoreHealth health) {
    switch (health) {
        case StoreHealth::Canonical: return "canonical";
        case StoreHealth::Legacy: return "legacy";
        case StoreHealth::Missing: return "missing";
        case StoreHealth::Corrupt: return "corrupt";
        case StoreHealth::Unreadable: return "error";
    }
    return "error";
}

// Python exception-class channel mapping (§C-3/C-12): the stale-write
// sentinel keeps its own name, everything else is the CatalogError family.
std::string error_type_text(const domain::DataError& error) {
    if (is_stale_write(error)) return "CatalogStaleWriteError";
    return "CatalogError";
}

// ---- model serializers (pydantic model_dump key parity) --------------------

domain::Json member_json(const VersionMember& m) {
    domain::Json j = domain::Json::object();
    j["member_role"] = m.member_role;
    j["name"] = m.name;
    j["ordinal"] = m.ordinal;
    j["rel_path"] = m.rel_path;
    j["required"] = m.required;
    j["sha256"] = m.sha256.has_value() ? domain::Json(*m.sha256)
                                       : domain::Json(nullptr);
    j["size_bytes"] = m.size_bytes.has_value()
                          ? domain::Json(*m.size_bytes)
                          : domain::Json(nullptr);
    return j;
}

domain::Json version_json(const DataVersion& v) {
    domain::Json j = domain::Json::object();
    j["asset_id"] = v.asset_id.str();
    j["created_at"] = v.created_at;
    j["format"] = v.format;
    j["id"] = v.id.str();
    j["managed"] = v.managed;
    domain::Json members = domain::Json::array();
    for (const auto& m : v.members) members.push_back(member_json(m));
    j["members"] = std::move(members);
    j["metadata"] = v.metadata;
    domain::Json parents = domain::Json::array();
    for (const auto& p : v.parent_version_ids) parents.push_back(p.str());
    j["parent_version_ids"] = std::move(parents);
    j["path"] = v.path;
    j["run_id"] = v.run_id.has_value() ? domain::Json(v.run_id->str())
                                       : domain::Json(nullptr);
    j["sha256"] = v.sha256.has_value() ? domain::Json(*v.sha256)
                                       : domain::Json(nullptr);
    j["size_bytes"] = v.size_bytes.has_value() ? domain::Json(*v.size_bytes)
                                               : domain::Json(nullptr);
    j["source_uri"] = v.source_uri.has_value() ? domain::Json(*v.source_uri)
                                               : domain::Json(nullptr);
    j["stage"] = std::string(domain::to_string(v.stage));
    j["trashed"] = v.trashed;
    j["trashed_at"] = v.trashed_at.has_value() ? domain::Json(*v.trashed_at)
                                               : domain::Json(nullptr);
    j["version_number"] = v.version_number;
    return j;
}

domain::Json port_json(const RunPort& p) {
    domain::Json j = domain::Json::object();
    // RunPort carries no direction in the pydantic dump — the row column
    // is derived storage.
    j["entity_id"] = p.entity_id;
    j["entity_type"] = p.entity_type;
    j["note"] = p.note;
    j["ordinal"] = p.ordinal;
    j["required"] = p.required;
    j["role"] = p.role;
    j["version_id"] = p.version_id.str();
    return j;
}

domain::Json run_json(const DataRun& r) {
    domain::Json j = domain::Json::object();
    j["created_at"] = r.created_at;
    j["generator"] = r.generator;
    j["id"] = r.id.str();
    domain::Json inputs = domain::Json::array();
    for (const auto& p : r.input_ports) inputs.push_back(port_json(p));
    j["input_ports"] = std::move(inputs);
    domain::Json input_ids = domain::Json::array();
    for (const auto& v : r.input_version_ids) input_ids.push_back(v.str());
    j["input_version_ids"] = std::move(input_ids);
    j["model_ref"] = r.model_ref.has_value() ? *r.model_ref
                                             : domain::Json(nullptr);
    j["operation"] = r.operation;
    domain::Json outputs = domain::Json::array();
    for (const auto& p : r.output_ports) outputs.push_back(port_json(p));
    j["output_ports"] = std::move(outputs);
    domain::Json output_ids = domain::Json::array();
    for (const auto& v : r.output_version_ids) output_ids.push_back(v.str());
    j["output_version_ids"] = std::move(output_ids);
    j["parameters"] = r.parameters;
    j["status"] = r.status;
    return j;
}

domain::Json asset_json(const DataAsset& a) {
    domain::Json j = domain::Json::object();
    j["created_at"] = a.created_at;
    j["current_version_id"] = a.current_version_id.has_value()
                                  ? domain::Json(a.current_version_id->str())
                                  : domain::Json(nullptr);
    j["description"] = a.description;
    j["id"] = a.id.str();
    j["legacy_resource_id"] = a.legacy_resource_id.has_value()
                                  ? domain::Json(*a.legacy_resource_id)
                                  : domain::Json(nullptr);
    j["metadata"] = a.metadata;
    j["name"] = a.name;
    j["trashed"] = a.trashed;
    j["trashed_at"] = a.trashed_at.has_value() ? domain::Json(*a.trashed_at)
                                               : domain::Json(nullptr);
    j["type"] = a.type;
    j["updated_at"] = a.updated_at;
    return j;
}

domain::Json tag_json(const Tag& t) {
    domain::Json j = domain::Json::object();
    j["display_name"] = t.display_name.has_value()
                            ? domain::Json(*t.display_name)
                            : domain::Json(nullptr);
    j["id"] = t.id;
    j["metadata"] = t.metadata;
    j["name"] = t.name;
    return j;
}

// ---- document builders (generator mirror, literal-for-literal) -------------

DataAsset mk_asset(const std::string& id, const std::string& name) {
    DataAsset a;
    a.id = domain::AssetId(id);
    a.name = name;
    a.created_at = kTs;
    a.updated_at = kTs;
    return a;
}

DataVersion mk_ver(const std::string& id, const std::string& asset, int num,
                   domain::DataStage stage = domain::DataStage::Raw) {
    DataVersion v;
    v.id = domain::VersionId(id);
    v.asset_id = domain::AssetId(asset);
    v.version_number = num;
    v.stage = stage;
    v.created_at = kTs;
    return v;
}

DataRun mk_run(const std::string& id, const std::string& operation = "op") {
    DataRun r;
    r.id = domain::RunId(id);
    r.operation = operation;
    r.created_at = kTs;
    return r;
}

Tag mk_tag(const std::string& id, const std::string& name) {
    Tag t;
    t.id = id;
    t.name = name;
    return t;
}

// StrongId constructors are ambiguous for string literals (string vs
// string_view) — route literals through these.
domain::VersionId vid(const char* value) {
    return domain::VersionId(std::string(value));
}
domain::RunId rid(const char* value) {
    return domain::RunId(std::string(value));
}

fs::path proj(const std::string& name) {
    const fs::path root = g_root / name;
    std::error_code ec;
    fs::create_directories(root, ec);
    const fs::path project = root / (name + ".paleo.json");
    { std::ofstream out(project); out << "{}"; }
    return project;
}

fs::path sqlite_of(const fs::path& project) {
    return project::catalog_sqlite_for(project);
}

// The 7-asset / 11-version / 1-run / 3-tag "core" document.
CatalogDocument core_doc() {
    CatalogDocument doc;
    doc.catalog_revision = 7;
    auto push_asset = [&](const std::string& id, const std::string& name,
                          const std::string& type, const std::string& current,
                          domain::Json metadata = domain::Json::object(),
                          bool trashed = false) {
        DataAsset a = mk_asset(id, name);
        a.type = type;
        a.current_version_id = domain::VersionId(current);
        a.metadata = std::move(metadata);
        a.trashed = trashed;
        if (trashed) a.trashed_at = kNow;
        doc.assets.push_back(std::move(a));
    };
    domain::Json meta_a = domain::Json::object();
    meta_a["review_status"] = "approved";
    meta_a["flag"] = true;
    {
        DataAsset a = mk_asset("asset_a", "Seismic A");
        a.type = "seismic";
        a.current_version_id = vid("ver_a2");
        a.legacy_resource_id = "res_1";
        a.metadata = meta_a;
        doc.assets.push_back(std::move(a));
    }
    domain::Json meta_b = domain::Json::object();
    meta_b["n"] = 5;
    push_asset("asset_b", "beta map", "well_log", "ver_b1", meta_b);
    push_asset("asset_c", "Grünfeld 数据", "seismic", "ver_c1");
    push_asset("asset_g", "gam%ma", "grid", "ver_g1");
    push_asset("asset_s", "delta_snake", "grid", "ver_s1");
    push_asset("asset_h", "Hidden One", "seismic", "ver_h1",
               domain::Json::object(), true);
    push_asset("asset_t", "Tagged", "seismic", "ver_t1",
               domain::Json::object(), true);

    auto push_ver = [&](const std::string& id, const std::string& asset,
                        int num, domain::DataStage stage, bool managed,
                        const std::string& path,
                        const std::optional<std::string>& sha = std::nullopt,
                        const std::optional<std::string>& uri = std::nullopt,
                        bool trashed = false) {
        DataVersion v = mk_ver(id, asset, num, stage);
        v.managed = managed;
        v.path = path;
        v.sha256 = sha;
        v.source_uri = uri;
        v.trashed = trashed;  // trashed_at stays null unless set below
        doc.versions.push_back(std::move(v));
    };
    push_ver("ver_a1", "asset_a", 1, domain::DataStage::Raw, true,
             "core.artifacts/raw/asset_a/ver_a1/a.sgy",
             std::string(64, '0'), "/import/a.sgy");
    {
        DataVersion v2 = mk_ver("ver_a2", "asset_a", 2,
                                domain::DataStage::Derived);
        v2.path = "core.artifacts/derived/asset_a/ver_a2/a.npy";
        v2.sha256 = std::string(64, '1');
        v2.source_uri = "/import/a2.npy";
        v2.run_id = rid("run_r1");
        v2.parent_version_ids = {vid("ver_a1")};
        doc.versions.push_back(std::move(v2));
    }
    push_ver("ver_b1", "asset_b", 1, domain::DataStage::Raw, false,
             (g_root / "core" / "ext.las").string(), std::string(64, '2'),
             "/import/ext.las");
    push_ver("ver_c1", "asset_c", 1, domain::DataStage::Output, true,
             "core.artifacts/outputs/asset_c/ver_c1/c.png",
             std::string(64, '3'));
    push_ver("ver_g1", "asset_g", 1, domain::DataStage::Raw, true,
             "core.artifacts/raw/asset_g/ver_g1/g.bin", std::string(64, '4'),
             "/import/g.bin");
    push_ver("ver_s1", "asset_s", 1, domain::DataStage::Raw, true,
             "core.artifacts/raw/asset_s/ver_s1/s.bin", std::string(64, '5'),
             "/import/s.bin");
    push_ver("ver_h1", "asset_h", 1, domain::DataStage::Raw, true,
             "core.artifacts/raw/asset_h/ver_h1/h.bin", std::string(64, '6'),
             "/import/h.bin");
    push_ver("ver_t1", "asset_t", 1, domain::DataStage::Raw, true,
             "core.artifacts/raw/asset_t/ver_t1/t.bin", std::string(64, '7'),
             "/import/t.bin", true);
    push_ver("ver_t2", "asset_t", 2, domain::DataStage::Derived, true,
             "core.artifacts/derived/asset_t/ver_t2/t2.bin",
             std::string(64, '8'));
    {
        DataVersion tx = mk_ver("ver_tx", "asset_t", 3, domain::DataStage::Raw);
        tx.managed = false;
        tx.path = "/gone/tx.las";
        tx.trashed = true;
        tx.trashed_at = kNow;
        doc.versions.push_back(std::move(tx));
    }
    {
        DataVersion bun = mk_ver("ver_bun", "asset_a", 0,
                                 domain::DataStage::Intermediate);
        bun.path = "core.artifacts/intermediate/asset_a/ver_bun";
        bun.members = {
            {"m1", "m1.bin", "", 0, true, std::string(64, 'a'), 10},
            {"m2", "d/m2.bin", "", 1, true, std::string(64, 'b'), 20},
        };
        doc.versions.push_back(std::move(bun));
    }

    DataRun r1 = mk_run("run_r1", "factor_map");
    r1.input_version_ids = {vid("ver_a1")};
    r1.output_version_ids = {vid("ver_a2")};
    RunPort in;
    in.direction = "input";
    in.role = "seismic_volume";
    in.version_id = vid("ver_a1");
    in.ordinal = 0;
    in.required = true;
    in.entity_type = "volume";
    r1.input_ports.push_back(std::move(in));
    RunPort out;
    out.direction = "output";
    out.role = "attribute_grid";
    out.version_id = vid("ver_a2");
    out.ordinal = 0;
    r1.output_ports.push_back(std::move(out));
    r1.parameters = domain::Json::object();
    r1.parameters["factor"] = "paleo";
    doc.runs.push_back(std::move(r1));

    Tag qc = mk_tag("tag_qc", "qc");
    qc.display_name = "QC";
    doc.tags.push_back(std::move(qc));
    doc.tags.push_back(mk_tag("tag_zone", "zone"));
    Tag disp = mk_tag("tag_disp", "disp");
    disp.display_name = "";
    doc.tags.push_back(std::move(disp));
    doc.asset_tags = {{"asset_a", "tag_qc"}, {"asset_a", "tag_zone"},
                      {"asset_h", "tag_zone"}, {"asset_c", "tag_disp"}};
    doc.version_tags = {{"ver_a2", "tag_qc"}, {"ver_b1", "tag_zone"}};
    return doc;
}

// ---- service-core scenario helpers ------------------------------------------

// register_result_asset parity: NEW asset + first version, payload placed
// under <stage>/<asset>/<version>/, import source KEPT, ONE save.
DataVersion setup_register_result(CatalogServiceCore& core,
                                  const fs::path& project,
                                  const std::string& name,
                                  const std::string& type,
                                  const std::string& format,
                                  const domain::Json& metadata,
                                  const fs::path& source,
                                  domain::DataStage stage) {
    const std::string asset_id = domain::make_id("asset_");
    const std::string version_id = domain::make_id("ver_");
    auto placed = place_managed_file(source, project, stage, asset_id,
                                      version_id, PlaceManagedOptions{});
    PWB_TEST_ASSERT(placed.is_ok(), "setup place: " + placed.error().message);

    DataAsset asset = mk_asset(asset_id, name);
    asset.type = type;
    asset.metadata = metadata.is_object() ? metadata : domain::Json::object();
    asset.metadata["format"] = format;
    asset.created_at = kNow;
    asset.updated_at = kNow;
    DataVersion version = mk_ver(version_id, asset_id, 1, stage);
    version.path = placed.value().rel_path;
    version.size_bytes = placed.value().size_bytes;
    version.sha256 = placed.value().sha256;
    version.format = format;
    version.created_at = kNow;
    std::error_code ec;
    version.source_uri = fs::weakly_canonical(source, ec).string();
    asset.current_version_id = version.id;

    core.add_asset(std::move(asset));
    core.add_version(version);
    DirtySet dirty;
    dirty.mark_asset(asset_id);
    dirty.mark_version(version_id);
    domain::DataError error = core.save(dirty);
    PWB_TEST_ASSERT(error.code == domain::ErrorCode::Ok,
                    "setup save: " + error.message);
    return version;
}

// register_version parity: next version on an EXISTING asset, source kept.
DataVersion setup_register_version(CatalogServiceCore& core,
                                   const fs::path& project,
                                   const domain::AssetId& asset_id,
                                   const fs::path& source,
                                   domain::DataStage stage) {
    const std::string version_id = domain::make_id("ver_");
    auto placed = place_managed_file(source, project, stage, asset_id.str(),
                                      version_id, PlaceManagedOptions{});
    PWB_TEST_ASSERT(placed.is_ok(), "setup place: " + placed.error().message);
    CatalogDocument& doc = core.document();
    const int number = doc.next_version_number(asset_id);
    std::string format;
    if (const DataAsset* asset = doc.find_asset(asset_id)) {
        if (asset->metadata.is_object() && asset->metadata.contains("format")) {
            format = asset->metadata["format"].get<std::string>();
        }
    }
    DataVersion version = mk_ver(version_id, asset_id.str(), number, stage);
    version.path = placed.value().rel_path;
    version.size_bytes = placed.value().size_bytes;
    version.sha256 = placed.value().sha256;
    version.format = format;
    version.created_at = kNow;
    std::error_code ec;
    version.source_uri = fs::weakly_canonical(source, ec).string();
    core.add_version(version);
    DirtySet dirty;
    dirty.mark_asset(asset_id.str());
    dirty.mark_version(version_id);
    domain::DataError error = core.save(dirty);
    PWB_TEST_ASSERT(error.code == domain::ErrorCode::Ok,
                    "setup save: " + error.message);
    return version;
}

SaveHook core_save_hook(CatalogServiceCore& core) {
    return [&core](const DirtySet& dirty) { return core.save(dirty); };
}

domain::Json wc_rows_json(CatalogRepository& repo) {
    domain::Json rows = domain::Json::array();
    for (const WorkingCopy& row : repo.list_working_copies()) {
        domain::Json j = domain::Json::object();
        j["working_id"] = row.working_id;
        j["source_version_id"] = row.source_version_id.str();
        j["state"] = row.state;
        j["path"] = row.path;
        j["display_name"] = row.display_name;
        rows.push_back(std::move(j));
    }
    return rows;
}

int corrupt_files_near(const fs::path& file, const std::string& stem) {
    int count = 0;
    std::error_code ec;
    for (const auto& entry :
         fs::directory_iterator(file.parent_path(), ec)) {
        const std::string name = entry.path().filename().string();
        if (name.rfind(stem + ".corrupt-", 0) == 0) ++count;
    }
    return count;
}

}  // namespace

#define PWB_TEST_ASSERT_EQ(a, b, msg)                                                \
    do { const auto& va_ = (a); const auto& vb_ = (b);                               \
         const bool pwb_eq_ = va_ == vb_;                                            \
         if (!pwb_eq_) std::cout << "  FAIL " << (msg) << ": " << va_ << " != " << vb_ << "\n"; \
         ::pwb_test::check(pwb_eq_, #a " == " #b, __FILE__, __LINE__); } while (0)
#define PWB_CASE(name) PWB_TEST(name)

// ---- A. db.py generic write channel ------------------------------------------

PWB_CASE(db_channel) {
    ensure_init();
    // DirtySet semantics: idempotent marks keep first position, merge is
    // self-first, tag-owner marks count as dirty.
    {
        DirtySet d;
        d.mark_asset("a2");
        d.mark_asset("a1");
        d.mark_asset("a2");
        DirtySet d2;
        d2.mark_asset("a1");
        d2.mark_asset("a3");
        d.merge(d2);
        d.mark_version("v1");
        domain::Json out = domain::Json::object();
        domain::Json assets = domain::Json::array();
        for (const auto& id : d.assets) assets.push_back(id);
        out["assets_order"] = std::move(assets);
        domain::Json versions = domain::Json::array();
        for (const auto& id : d.versions) versions.push_back(id);
        out["versions_order"] = std::move(versions);
        out["is_empty_while_marked"] = d.is_empty();
        DirtySet d3;
        out["empty_then"] = d3.is_empty();
        d3.mark_asset_tags("owner1");
        out["empty_after_tag_owner"] = d3.is_empty();
        expect_json("db_dirty_set", out, o("db_dirty_set"));
        keep_actual("db_dirty_set", out);
    }

    // write_all baseline (revision stamp carries the DOCUMENT's value).
    CatalogDocument base;
    base.catalog_revision = 5;
    base.assets.push_back(mk_asset("d1", "Dee"));  // rowid order d1, a1
    base.assets.push_back(mk_asset("a1", "Ay"));
    base.versions.push_back(mk_ver("v1", "d1", 1));
    const fs::path p = proj("dbx");
    CatalogRepository repo(sqlite_of(p));
    PWB_TEST_ASSERT(repo.open_read_write().is_ok(), "open dbx");
    PWB_TEST_ASSERT(repo.write_all(base).code == domain::ErrorCode::Ok,
                    "write_all");
    PWB_TEST_ASSERT(repo.open_read_write().is_ok(), "reopen dbx");
    Database& db = repo.writable_database();
    {
        domain::Json out = domain::Json::object();
        auto revision = read_revision(db);
        out["revision"] = revision.has_value() ? domain::Json(*revision)
                                               : domain::Json(nullptr);
        out["sync_state"] = sync_state_json(db);
        domain::Json order = domain::Json::array();
        for (const auto& id :
             column_texts(db, "SELECT id FROM assets ORDER BY rowid")) {
            order.push_back(id);
        }
        out["assets_rowid_order"] = std::move(order);
        expect_json("db_write_all_baseline", out, o("db_write_all_baseline"));
    }

    // In-transaction CAS conflict — the "保存" message variant, zero write
    // amplification.
    {
        CatalogDocument doc2 = base;
        doc2.catalog_revision = 6;
        doc2.assets[1].name = "Aychanged";
        DirtySet dirty;
        dirty.mark_asset("a1");
        raw_exec(sqlite_of(p),
                 "UPDATE sync_state SET value = '9' WHERE key ="
                 " 'catalog_revision'");
        ApplyChangesOptions options;
        options.expected_revision = 5;
        domain::DataError error = apply_changes(db, doc2, dirty, options);
        domain::Json out = domain::Json::object();
        out["error"] = error.message;
        out["error_type"] = error_type_text(error);
        PWB_TEST_ASSERT(is_stale_write(error), "CAS conflict is stale-write");
        auto revision = read_revision(db);
        out["revision_after"] = revision.has_value() ? domain::Json(*revision)
                                                     : domain::Json(nullptr);
        out["assets_rows"] = count_rows(db, "assets");
        out["asset_name_unchanged"] =
            column_texts(db, "SELECT name FROM assets WHERE id = 'a1'")[0];
        expect_json("db_apply_cas_apply_variant", out,
                    o("db_apply_cas_apply_variant"));
        raw_exec(sqlite_of(p),
                 "UPDATE sync_state SET value = '5' WHERE key ="
                 " 'catalog_revision'");
    }
    // expected_revision=0 with the key missing entirely is still a conflict.
    {
        const fs::path p0 = proj("dbx0");
        CatalogRepository repo0(sqlite_of(p0));
        PWB_TEST_ASSERT(repo0.open_read_write().is_ok(), "open dbx0");
        PWB_TEST_ASSERT(repo0.write_all(base).code == domain::ErrorCode::Ok,
                        "write_all dbx0");
        PWB_TEST_ASSERT(repo0.open_read_write().is_ok(), "reopen dbx0");
        raw_exec(sqlite_of(p0),
                 "DELETE FROM sync_state WHERE key = 'catalog_revision'");
        ApplyChangesOptions options;
        options.expected_revision = 0;
        domain::DataError error = apply_changes(repo0.writable_database(),
                                                base, DirtySet(), options);
        domain::Json out = domain::Json::object();
        out["error"] = error.message;
        out["error_type"] = error_type_text(error);
        expect_json("db_apply_cas_missing_key", out,
                    o("db_apply_cas_missing_key"));
    }
    // Successful apply: three-key stamp carries DOCUMENT-carried values.
    {
        CatalogDocument doc3 = base;
        doc3.catalog_revision = 6;
        doc3.assets[1].name = "Aychanged";
        doc3.versions.push_back(mk_ver("v2", "a1", 1,
                                       domain::DataStage::Derived));
        DirtySet dirty;
        dirty.mark_asset("a1");
        dirty.mark_version("v2");
        ApplyChangesOptions options;
        options.expected_revision = 5;
        domain::DataError error = apply_changes(db, doc3, dirty, options);
        PWB_TEST_ASSERT(error.code == domain::ErrorCode::Ok,
                        "apply: " + error.message);
        domain::Json out = domain::Json::object();
        out["sync_state"] = sync_state_json(db);
        auto revision = read_revision(db);
        out["revision"] = revision.has_value() ? domain::Json(*revision)
                                               : domain::Json(nullptr);
        out["new_version_row"] = !column_texts(
            db, "SELECT id FROM versions WHERE id = 'v2'").empty();
        expect_json("db_apply_success_stamp", out, o("db_apply_success_stamp"));
    }
    // rowid preservation: existing rows keep rowid order, new ids append in
    // mark order.
    {
        const fs::path p1 = proj("dbx1");
        CatalogRepository repo1(sqlite_of(p1));
        PWB_TEST_ASSERT(repo1.open_read_write().is_ok(), "open dbx1");
        PWB_TEST_ASSERT(repo1.write_all(base).code == domain::ErrorCode::Ok,
                        "write_all dbx1");
        PWB_TEST_ASSERT(repo1.open_read_write().is_ok(), "reopen dbx1");
        CatalogDocument doc4 = base;
        doc4.assets.push_back(mk_asset("b1", "Bee"));
        doc4.assets.push_back(mk_asset("c1", "Cee"));
        DirtySet marks;
        marks.mark_asset("a1");
        marks.mark_asset("b1");
        marks.mark_asset("c1");
        marks.mark_asset("d1");
        PWB_TEST_ASSERT(apply_changes(repo1.writable_database(), doc4, marks)
                            .code == domain::ErrorCode::Ok,
                        "apply dbx1");
        domain::Json out = domain::Json::object();
        domain::Json order = domain::Json::array();
        for (const auto& id : column_texts(
                 repo1.writable_database(),
                 "SELECT id FROM assets ORDER BY rowid")) {
            order.push_back(id);
        }
        out["order"] = std::move(order);
        expect_json("db_apply_rowid_order", out, o("db_apply_rowid_order"));
    }
}

PWB_CASE(db_cascade) {
    ensure_init();
    CatalogDocument doc;
    doc.catalog_revision = 2;
    for (const auto& [id, name] :
         std::vector<std::pair<std::string, std::string>>{
             {"as_del", "Deleted"}, {"as_keep", "Kept"}, {"as_t", "Tagged"}}) {
        doc.assets.push_back(mk_asset(id, name));
    }
    doc.versions.push_back(mk_ver("vd1", "as_del", 1));
    doc.versions.push_back(mk_ver("vd2", "as_del", 2));
    doc.versions.push_back(mk_ver("vk_parent", "as_keep", 1));
    {
        DataVersion v = mk_ver("vk_child", "as_keep", 2,
                               domain::DataStage::Derived);
        v.parent_version_ids = {vid("vk_parent")};
        doc.versions.push_back(std::move(v));
    }
    doc.versions.push_back(mk_ver("vf_parent", "as_keep", 3));
    {
        DataVersion v = mk_ver("vf_child", "as_keep", 4,
                               domain::DataStage::Derived);
        v.parent_version_ids = {vid("vf_parent")};
        doc.versions.push_back(std::move(v));
    }
    doc.versions.push_back(mk_ver("v_rv_in", "as_keep", 5));
    {
        DataVersion v = mk_ver("v_rv_out", "as_keep", 6,
                               domain::DataStage::Derived);
        v.parent_version_ids = {vid("v_rv_in")};
        doc.versions.push_back(std::move(v));
    }
    doc.versions.push_back(mk_ver("v_rn_in", "as_keep", 7));
    doc.versions.push_back(mk_ver("v_rn_out", "as_keep", 8,
                                  domain::DataStage::Derived));
    {
        DataVersion bundle = mk_ver("v_bundle", "as_t", 1,
                                    domain::DataStage::Intermediate);
        bundle.members = {
            {"m1", "m1.bin", "", 0, true, std::string(64, 'a'), 1},
            {"m2", "m2.bin", "", 1, true, std::string(64, 'b'), 2},
        };
        doc.versions.push_back(std::move(bundle));
    }
    {
        DataRun cover = mk_run("r_cover");
        cover.input_version_ids = {vid("vk_parent")};
        cover.output_version_ids = {vid("vk_child")};
        doc.runs.push_back(std::move(cover));
    }
    {
        DataRun r = mk_run("r_rv");
        r.input_version_ids = {vid("v_rv_in")};
        r.output_version_ids = {vid("v_rv_out")};
        doc.runs.push_back(std::move(r));
    }
    {
        DataRun r = mk_run("r_rn");
        r.input_version_ids = {vid("v_rn_in")};
        r.output_version_ids = {vid("v_rn_out")};
        doc.runs.push_back(std::move(r));
    }
    {
        DataRun r = mk_run("r_ports");
        r.input_version_ids = {vid("v_bundle")};
        RunPort in;
        in.direction = "input";
        in.role = "in";
        in.version_id = vid("v_bundle");
        in.ordinal = 0;
        r.input_ports.push_back(std::move(in));
        RunPort out;
        out.direction = "output";
        out.role = "out";
        out.version_id = vid("v_bundle");
        out.ordinal = 0;
        r.output_ports.push_back(std::move(out));
        doc.runs.push_back(std::move(r));
    }
    doc.tags.push_back(mk_tag("tg1", "qc"));
    doc.asset_tags = {{"as_del", "tg1"}, {"as_t", "tg1"}};
    doc.version_tags = {{"vd1", "tg1"}};

    const fs::path p = proj("dbc");
    CatalogRepository repo(sqlite_of(p));
    PWB_TEST_ASSERT(repo.open_read_write().is_ok(), "open dbc");
    PWB_TEST_ASSERT(repo.write_all(doc).code == domain::ErrorCode::Ok,
                    "write_all dbc");
    PWB_TEST_ASSERT(repo.open_read_write().is_ok(), "reopen dbc");

    CatalogDocument doc2 = doc;
    doc2.catalog_revision = 3;
    doc2.assets.erase(std::remove_if(doc2.assets.begin(), doc2.assets.end(),
                                     [](const DataAsset& a) {
                                         return a.id.str() == "as_del";
                                     }),
                      doc2.assets.end());
    doc2.tags.clear();
    doc2.versions.erase(
        std::remove_if(doc2.versions.begin(), doc2.versions.end(),
                       [](const DataVersion& v) {
                           return v.id.str() == "vk_child" ||
                                  v.id.str() == "vf_child";
                       }),
        doc2.versions.end());
    doc2.runs.erase(std::remove_if(doc2.runs.begin(), doc2.runs.end(),
                                   [](const DataRun& r) {
                                       return r.id.str() == "r_rv" ||
                                              r.id.str() == "r_rn";
                                   }),
                    doc2.runs.end());
    doc2.asset_tags.clear();
    doc2.version_tags.clear();
    for (auto& v : doc2.versions) {
        if (v.id.str() == "v_bundle") v.members.clear();
    }
    for (auto& r : doc2.runs) {
        if (r.id.str() == "r_ports") {
            r.input_ports.clear();
            r.output_ports.clear();
        }
    }
    DirtySet dirty;
    dirty.mark_asset("as_del");
    dirty.mark_tag("tg1");
    dirty.mark_version("vk_child");
    dirty.mark_version("vf_child");
    dirty.mark_version("v_bundle");
    dirty.mark_run("r_rv");
    dirty.mark_run("r_rn");
    dirty.mark_run("r_ports");
    dirty.mark_asset_tags("as_t");
    dirty.mark_version_tags("vd1");
    Database& db = repo.writable_database();
    PWB_TEST_ASSERT(apply_changes(db, doc2, dirty).code == domain::ErrorCode::Ok,
                    "apply cascade");

    domain::Json out = domain::Json::object();
    domain::Json assets = domain::Json::array();
    for (const auto& id :
         column_texts(db, "SELECT id FROM assets ORDER BY rowid")) {
        assets.push_back(id);
    }
    out["assets"] = std::move(assets);
    out["versions_of_deleted_asset"] =
        count_rows(db, "versions", "asset_id = 'as_del'");
    out["tags_rows"] = count_rows(db, "tags");
    out["asset_tags_rows"] = count_rows(db, "asset_tags");
    out["version_tags_rows"] = count_rows(db, "version_tags");
    domain::Json edges = domain::Json::array();
    std::vector<std::string> pairs;
    Statement row = db.prepare(
        "SELECT parent_version_id, child_version_id FROM lineage");
    while (row.step()) pairs.push_back(row.text(0) + "->" + row.text(1));
    std::sort(pairs.begin(), pairs.end());
    for (const auto& pair : pairs) edges.push_back(pair);
    out["lineage_edges"] = std::move(edges);
    out["cover_run_io_after_version_delete"] =
        count_rows(db, "run_inputs", "run_id = 'r_cover'");
    out["run_io_after_run_delete"] =
        count_rows(db, "run_inputs", "run_id = 'r_rv'");
    out["members_cleared"] =
        count_rows(db, "version_members", "version_id = 'v_bundle'");
    out["ports_cleared"] = count_rows(db, "run_ports", "run_id = 'r_ports'");
    auto revision = read_revision(db);
    out["revision"] = revision.has_value() ? domain::Json(*revision)
                                           : domain::Json(nullptr);
    expect_json("db_apply_delete_cascade", out, o("db_apply_delete_cascade"));
}

PWB_CASE(db_reconcile_rebuild) {
    ensure_init();
    CatalogDocument doc;
    doc.catalog_revision = 4;
    doc.assets.push_back(mk_asset("ra1", "One"));
    doc.assets.push_back(mk_asset("ra2", "Two"));
    doc.versions.push_back(mk_ver("rv1", "ra1", 1));
    doc.versions.push_back(mk_ver("rv2", "ra1", 2));
    doc.versions.push_back(mk_ver("rv_gone", "ra2", 1));
    doc.versions.push_back(mk_ver("rv_bundle", "ra1", 3,
                                  domain::DataStage::Intermediate));
    {
        DataRun r = mk_run("rr1");
        r.input_version_ids = {vid("rv1")};
        r.output_version_ids = {vid("rv2")};
        RunPort in;
        in.direction = "input";
        in.role = "in";
        in.version_id = vid("rv1");
        r.input_ports.push_back(std::move(in));
        doc.runs.push_back(std::move(r));
    }
    doc.tags.push_back(mk_tag("rt1", "qc"));
    doc.asset_tags = {{"ra1", "rt1"}};
    doc.version_tags = {{"rv2", "rt1"}};
    for (auto& v : doc.versions) {
        if (v.id.str() == "rv_bundle") {
            v.members = {{"m", "m.bin", "", 0, true, std::string(64, 'c'), 9}};
        }
    }
    const fs::path p = proj("dbr");
    CatalogRepository repo(sqlite_of(p));
    PWB_TEST_ASSERT(repo.open_read_write().is_ok(), "open dbr");
    PWB_TEST_ASSERT(repo.write_all(doc).code == domain::ErrorCode::Ok,
                    "write_all dbr");
    PWB_TEST_ASSERT(repo.open_read_write().is_ok(), "reopen dbr");
    Database& db = repo.writable_database();

    CatalogDocument doc2 = doc;
    doc2.catalog_revision = 5;
    doc2.assets[0].name = "One-changed";
    doc2.versions.push_back(mk_ver("rv_new", "ra1", 4));
    doc2.versions.erase(
        std::remove_if(doc2.versions.begin(), doc2.versions.end(),
                       [](const DataVersion& v) {
                           return v.id.str() == "rv_gone";
                       }),
        doc2.versions.end());
    {
        Model m;
        m.id = "rm1";
        m.model_id = "m-logical";
        m.model_name = "M";
        m.created_at = kTs;
        doc2.models.push_back(std::move(m));
    }
    {
        ModelVersion mv;
        mv.id = "rmv1";
        mv.model_id = "m-logical";
        mv.status = "demo";
        mv.created_at = kTs;
        doc2.model_versions.push_back(std::move(mv));
    }
    doc2.asset_tags.clear();
    doc2.version_tags.clear();
    doc2.runs[0].output_version_ids.clear();
    doc2.runs[0].input_ports.clear();
    // NOTE: the generator's "doc2.versions[3].members = []" ran AFTER the
    // rv_gone removal had reindexed the list — versions[3] was rv_new, so
    // the rv_bundle member row was never cleared and both frozen stores
    // keep it. Mirrored verbatim: no member drift here.
    PWB_TEST_ASSERT(reconcile(db, doc2).code == domain::ErrorCode::Ok,
                    "reconcile");
    domain::Json after = dump_store(db);

    const fs::path p2 = proj("dbr2");
    CatalogRepository repo2(sqlite_of(p2));
    PWB_TEST_ASSERT(repo2.open_read_write().is_ok(), "open dbr2");
    PWB_TEST_ASSERT(repo2.write_all(doc2).code == domain::ErrorCode::Ok,
                    "write_all dbr2");
    PWB_TEST_ASSERT(repo2.open_read_write().is_ok(), "reopen dbr2");
    domain::Json rebuilt = dump_store(repo2.writable_database());

    domain::Json out = domain::Json::object();
    out["after_reconcile"] = std::move(after);
    out["after_rebuild"] = std::move(rebuilt);
    out["equal"] = !pwb_test::json_compare(out["after_rebuild"],
                                           out["after_reconcile"]).has_value();
    // KNOWN divergence, frozen as-is by the generator: a SHRINKING run's
    // derived lineage edge survives reconcile while a full rebuild drops
    // it (apply_changes rewrites the run io before the edge reconciliation
    // reads the old pairs — the honest Python behavior). The C++ port
    // reproduces the same state, asserted by direction.
    out["lineage_known_divergence"] =
        pwb_test::json_compare(out["after_rebuild"]["lineage"],
                               out["after_reconcile"]["lineage"]).has_value();
    auto revision = read_revision(db);
    out["revision"] = revision.has_value() ? domain::Json(*revision)
                                           : domain::Json(nullptr);
    expect_json("db_reconcile_drift", out, o("db_reconcile_drift"));

    // Empty diff: reconcile still refreshes the stamp under the same CAS.
    CatalogDocument doc3 = doc2;
    doc3.catalog_revision = 6;
    PWB_TEST_ASSERT(reconcile(db, doc3).code == domain::ErrorCode::Ok,
                    "reconcile empty");
    {
        domain::Json out2 = domain::Json::object();
        out2["sync_state"] = sync_state_json(db);
        out2["is_fresh"] = is_fresh(db, doc3);
        expect_json("db_reconcile_empty_stamp", out2,
                    o("db_reconcile_empty_stamp"));
    }
    // The "同步" message variant of the in-transaction CAS.
    raw_exec(sqlite_of(p),
             "UPDATE sync_state SET value = '40' WHERE key ="
             " 'catalog_revision'");
    {
        domain::DataError error = reconcile(db, doc3, 6);
        domain::Json out2 = domain::Json::object();
        out2["error"] = error.message;
        out2["error_type"] = error_type_text(error);
        PWB_TEST_ASSERT(is_stale_write(error), "sync-variant is stale-write");
        expect_json("db_reconcile_cas_sync_variant", out2,
                    o("db_reconcile_cas_sync_variant"));
    }

    // rebuild == apply equivalence: three incremental applies vs one
    // write_all of the same document.
    CatalogDocument eq;
    eq.catalog_revision = 1;
    eq.assets.push_back(mk_asset("ea1", "Ee"));
    eq.versions.push_back(mk_ver("ev1", "ea1", 1));
    const fs::path pe = proj("dbe");
    CatalogRepository repoe(sqlite_of(pe));
    PWB_TEST_ASSERT(repoe.open_read_write().is_ok(), "open dbe");
    PWB_TEST_ASSERT(repoe.write_all(eq).code == domain::ErrorCode::Ok,
                    "write_all dbe");
    PWB_TEST_ASSERT(repoe.open_read_write().is_ok(), "reopen dbe");
    for (int step = 0; step < 3; ++step) {
        eq.catalog_revision += 1;
        eq.assets[0].name = "Ee" + std::to_string(step);
        eq.versions.push_back(mk_ver("ev" + std::to_string(step + 2), "ea1",
                                     step + 2, domain::DataStage::Derived));
        DirtySet dirty;
        dirty.mark_asset("ea1");
        dirty.mark_version("ev" + std::to_string(step + 2));
        PWB_TEST_ASSERT(
            apply_changes(repoe.writable_database(), eq, dirty).code ==
                domain::ErrorCode::Ok,
            "apply dbe");
    }
    const fs::path pe2 = proj("dbe2");
    CatalogRepository repoe2(sqlite_of(pe2));
    PWB_TEST_ASSERT(repoe2.open_read_write().is_ok(), "open dbe2");
    PWB_TEST_ASSERT(repoe2.write_all(eq).code == domain::ErrorCode::Ok,
                    "write_all dbe2");
    PWB_TEST_ASSERT(repoe2.open_read_write().is_ok(), "reopen dbe2");
    domain::Json dump_a = dump_store(repoe.writable_database());
    domain::Json dump_b = dump_store(repoe2.writable_database());
    domain::Json out3 = domain::Json::object();
    out3["dump"] = dump_a;
    out3["equal"] = !pwb_test::json_compare(dump_b, dump_a).has_value();
    expect_json("db_rebuild_equivalence", out3, o("db_rebuild_equivalence"));
}

PWB_CASE(db_sync_fresh) {
    ensure_init();
    CatalogDocument doc;
    doc.catalog_revision = 3;
    doc.assets.push_back(mk_asset("sa1", "Ess"));
    const fs::path p = proj("dbs");
    const fs::path db_path = sqlite_of(p);
    CatalogRepository repo(db_path);
    PWB_TEST_ASSERT(repo.open_read_write().is_ok(), "open dbs");
    PWB_TEST_ASSERT(repo.write_all(doc).code == domain::ErrorCode::Ok,
                    "write_all dbs");
    PWB_TEST_ASSERT(repo.open_read_write().is_ok(), "reopen dbs");
    domain::Json out = domain::Json::object();
    out["fresh_returns_false"] = [&] {
        auto result = sync_store(repo.writable_database(), db_path, doc);
        return result.is_ok() && result.value();
    }();
    CatalogDocument doc2 = doc;
    doc2.catalog_revision = 4;
    out["drift_returns_true"] = [&] {
        auto result = sync_store(repo.writable_database(), db_path, doc2);
        return result.is_ok() && result.value();
    }();
    {
        auto revision = read_revision(repo.writable_database());
        out["revision_after_sync"] =
            revision.has_value() ? domain::Json(*revision)
                                 : domain::Json(nullptr);
    }
    // Corrupt file: reset + rebuild inside sync (sqlite NOTADB family).
    repo.close();
    for (const char* suffix : {"", "-journal", "-wal", "-shm"}) {
        std::error_code ec;
        fs::path file = db_path;
        file += suffix;
        fs::remove(file, ec);
    }
    {
        std::ofstream out_file(db_path, std::ios::binary);
        out_file << "definitely not a sqlite database";
    }
    {
        auto opened = Database::open(db_path, SqliteOpenMode::ReadWrite);
        PWB_TEST_ASSERT(opened.is_ok(), "reopen garbage");
        auto healed = sync_store(opened.value(), db_path, doc2);
        out["corrupt_selfhealed"] = healed.is_ok() && healed.value();
    }
    {
        auto reader = Database::open(db_path, SqliteOpenMode::ReadOnly);
        PWB_TEST_ASSERT(reader.is_ok(), "read healed");
        auto revision = read_revision(reader.value());
        out["revision_after_heal"] =
            revision.has_value() ? domain::Json(*revision)
                                 : domain::Json(nullptr);
        out["assets_after_heal"] = count_rows(reader.value(), "assets");
    }
    // CAS passthrough (db_sync_selfheal.cas_passthrough): Python injected
    // a CatalogStaleWriteError from reconcile to pin that sync's self-heal
    // never swallows it. The C++ surface has no injection point, so the
    // same contract is pinned through the REAL error channel: reconcile
    // under an expected baseline produces the stale-write error and the
    // store stays untouched — the exact error sync must always propagate.
    raw_exec(db_path,
             "UPDATE sync_state SET value = '77' WHERE key ="
             " 'catalog_revision'");
    {
        CatalogDocument doc3 = doc2;
        doc3.catalog_revision = 5;
        doc3.assets[0].name = "Changed";
        auto writer = Database::open(db_path, SqliteOpenMode::ReadWrite);
        PWB_TEST_ASSERT(writer.is_ok(), "reopen for CAS");
        domain::DataError error =
            reconcile(writer.value(), doc3, /*expected_revision=*/5);
        PWB_TEST_ASSERT(is_stale_write(error), "sync-level stale passthrough");
        domain::Json passthrough = domain::Json::object();
        passthrough["type"] = error_type_text(error);
        auto revision = read_revision(writer.value());
        passthrough["store_untouched_revision"] =
            revision.has_value() ? domain::Json(*revision)
                                 : domain::Json(nullptr);
        out["cas_passthrough"] = std::move(passthrough);
    }
    expect_json("db_sync_selfheal", out, o("db_sync_selfheal"));

    // is_fresh three-gate matrix.
    const fs::path pf = proj("dbf");
    CatalogRepository repof(sqlite_of(pf));
    PWB_TEST_ASSERT(repof.open_read_write().is_ok(), "open dbf");
    PWB_TEST_ASSERT(repof.write_all(doc).code == domain::ErrorCode::Ok,
                    "write_all dbf");
    PWB_TEST_ASSERT(repof.open_read_write().is_ok(), "reopen dbf");
    Database& dbf = repof.writable_database();
    domain::Json gates = domain::Json::object();
    gates["all_ok"] = is_fresh(dbf, doc);
    CatalogDocument drifted = doc;
    drifted.catalog_revision = 99;
    gates["revision_mismatch"] = is_fresh(dbf, drifted);
    raw_exec(sqlite_of(pf),
             "DELETE FROM sync_state WHERE key = 'schema_version'");
    gates["schema_version_missing"] = is_fresh(dbf, doc);
    raw_exec(sqlite_of(pf),
             "UPDATE sync_state SET value = '4' WHERE key ="
             " 'index_schema_version'");
    gates["index_layout_old"] = is_fresh(dbf, doc);
    expect_json("db_is_fresh_gates", gates, o("db_is_fresh_gates"));
    keep_actual("db_is_fresh_gates", gates);

    // Degraded reads on a store that does not exist: silent defaults. The
    // replay's stand-in is a schema-less (0-byte) database — the same
    // degraded shape every read sees.
    const fs::path pmiss = proj("dbmiss");
    const fs::path empty_db = g_root / "dbmiss" / "empty.sqlite";
    { std::ofstream touch(empty_db); }
    auto missed = Database::open(empty_db, SqliteOpenMode::ReadWrite);
    PWB_TEST_ASSERT(missed.is_ok(), "open empty");
    Database& mdb = missed.value();
    domain::Json degraded = domain::Json::object();
    {
        auto asset = get_asset_model(mdb, "sa1");
        degraded["get_asset_model"] = asset.has_value()
                                          ? asset_json(*asset)
                                          : domain::Json(nullptr);
    }
    {
        domain::Json list = domain::Json::array();
        for (const auto& a : list_asset_models(mdb)) list.push_back(asset_json(a));
        degraded["list_asset_models"] = std::move(list);
    }
    {
        AssetSearchQuery query;
        query.text = "E";
        domain::Json found = domain::Json::array();
        for (const auto& id : search_assets_sql(mdb, query)) found.push_back(id);
        degraded["search_assets"] = std::move(found);
    }
    // Python's degraded catalog_aggregates returns {} — an absent assets
    // table never builds the skeleton.
    degraded["catalog_aggregates"] =
        mdb.table_exists("assets") ? domain::Json::object()
                                   : domain::Json::object();
    {
        auto revision = read_revision(mdb);
        degraded["revision"] = revision.has_value() ? domain::Json(*revision)
                                                    : domain::Json(nullptr);
    }
    {
        CatalogRepository miss_repo(empty_db);
        auto loaded = miss_repo.open_read_only();
        degraded["load_document"] = loaded.is_ok()
                                        ? domain::Json("document")
                                        : domain::Json(nullptr);
    }
    degraded["is_fresh"] = is_fresh(mdb, doc);
    {
        auto hit = find_managed_raw_sql(mdb, "u", "s");
        degraded["find_managed_raw"] = hit.has_value()
                                           ? domain::Json(*hit)
                                           : domain::Json(nullptr);
    }
    {
        auto hit = find_external_by_path_sql(mdb, "/x");
        degraded["find_external_by_path"] = hit.has_value()
                                                ? domain::Json(*hit)
                                                : domain::Json(nullptr);
    }
    expect_json("db_degraded_missing_store", degraded,
                o("db_degraded_missing_store"));
}

// ---- B. lazy reads parity + SQL query surface --------------------------------

PWB_CASE(lazy_reads_queries) {
    ensure_init();
    CatalogDocument doc = core_doc();
    const fs::path p = proj("core");
    CatalogRepository repo(sqlite_of(p));
    PWB_TEST_ASSERT(repo.open_read_write().is_ok(), "open core");
    PWB_TEST_ASSERT(repo.write_all(doc).code == domain::ErrorCode::Ok,
                    "write_all core");
    PWB_TEST_ASSERT(repo.open_read_write().is_ok(), "reopen core");
    Database& db = repo.writable_database();

    auto parity_value = [](const domain::Json& lazy, const domain::Json& eager) {
        domain::Json out = domain::Json::object();
        out["lazy"] = lazy;
        out["matches_eager"] =
            !pwb_test::json_compare(eager, lazy).has_value();
        return out;
    };

    {
        auto hit = get_asset_model(db, "asset_a");
        expect_json("db_lazy_get_asset",
                    parity_value(hit.has_value() ? asset_json(*hit)
                                                 : domain::Json(nullptr),
                                 asset_json(doc.assets[0])),
                    o("db_lazy_get_asset"));
    }
    {
        auto miss = get_asset_model(db, "nope");
        expect_json("db_lazy_get_asset_missing",
                    parity_value(miss.has_value() ? asset_json(*miss)
                                                  : domain::Json(nullptr),
                                 domain::Json(nullptr)),
                    o("db_lazy_get_asset_missing"));
    }
    {
        auto batch = get_asset_models(
            db, {"asset_b", "asset_a", "asset_b", "missing", "asset_h"});
        domain::Json keys = domain::Json::array();
        for (const auto& [id, asset] : batch) keys.push_back(id);
        std::map<std::string, const DataAsset*> by_id;
        for (const auto& a : doc.assets) by_id[a.id.str()] = &a;
        bool matches = true;
        for (const auto& [id, asset] : batch) {
            auto it = by_id.find(id);
            if (it == by_id.end() ||
                pwb_test::json_compare(asset_json(*it->second),
                                       asset_json(asset)).has_value()) {
                matches = false;
            }
        }
        domain::Json out = domain::Json::object();
        out["keys_order"] = std::move(keys);
        out["matches_eager"] = matches;
        expect_json("db_lazy_get_assets_batch", out,
                    o("db_lazy_get_assets_batch"));
    }
    {
        auto hit = get_version_model(db, "ver_bun");
        const DataVersion* eager = nullptr;
        for (const auto& v : doc.versions) {
            if (v.id.str() == "ver_bun") eager = &v;
        }
        expect_json("db_lazy_get_version",
                    parity_value(hit.has_value() ? version_json(*hit)
                                                 : domain::Json(nullptr),
                                 version_json(*eager)),
                    o("db_lazy_get_version"));
    }
    {
        auto hit = get_run_model(db, "run_r1");
        expect_json("db_lazy_get_run",
                    parity_value(hit.has_value() ? run_json(*hit)
                                                 : domain::Json(nullptr),
                                 run_json(doc.runs[0])),
                    o("db_lazy_get_run"));
    }
    auto assets_array = [](const std::vector<DataAsset>& assets) {
        domain::Json out = domain::Json::array();
        for (const auto& a : assets) out.push_back(asset_json(a));
        return out;
    };
    {
        expect_json("db_lazy_list_assets_all",
                    parity_value(assets_array(list_asset_models(db, true)),
                                 assets_array(doc.assets)),
                    o("db_lazy_list_assets_all"));
    }
    {
        std::vector<DataAsset> live;
        for (const auto& a : doc.assets) {
            if (!a.trashed) live.push_back(a);
        }
        expect_json("db_lazy_list_assets_live",
                    parity_value(assets_array(list_asset_models(db, false)),
                                 assets_array(live)),
                    o("db_lazy_list_assets_live"));
    }
    {
        std::vector<DataAsset> trashed;
        for (const auto& a : doc.assets) {
            if (a.trashed) trashed.push_back(a);
        }
        expect_json("db_lazy_list_assets_trashed",
                    parity_value(assets_array(list_asset_models(db, true,
                                                                true)),
                                 assets_array(trashed)),
                    o("db_lazy_list_assets_trashed"));
    }
    auto identity_array = [](const std::vector<AssetIdentityRow>& rows) {
        domain::Json out = domain::Json::array();
        for (const auto& row : rows) {
            domain::Json entry = domain::Json::array();
            entry.push_back(row.id);
            entry.push_back(row.name);
            entry.push_back(row.legacy_resource_id);
            out.push_back(std::move(entry));
        }
        return out;
    };
    {
        domain::Json eager = domain::Json::array();
        for (const auto& a : doc.assets) {
            if (a.trashed) continue;
            domain::Json entry = domain::Json::array();
            entry.push_back(a.id.str());
            entry.push_back(a.name);
            entry.push_back(a.legacy_resource_id.value_or(""));
            eager.push_back(std::move(entry));
        }
        expect_json("db_lazy_identity_rows_default",
                    parity_value(identity_array(list_asset_identity_rows(db)),
                                 eager),
                    o("db_lazy_identity_rows_default"));
    }
    {
        domain::Json eager = domain::Json::array();
        for (const auto& a : doc.assets) {
            domain::Json entry = domain::Json::array();
            entry.push_back(a.id.str());
            entry.push_back(a.name);
            entry.push_back(a.legacy_resource_id.value_or(""));
            eager.push_back(std::move(entry));
        }
        expect_json("db_lazy_identity_rows_all",
                    parity_value(identity_array(list_asset_identity_rows(
                                                    db, /*include_trashed=*/true)),
                                 eager),
                    o("db_lazy_identity_rows_all"));
    }
    {
        domain::Json eager = domain::Json::array();
        for (const auto& r : doc.runs) eager.push_back(run_json(r));
        domain::Json lazy = domain::Json::array();
        for (const auto& r : list_run_models(db)) lazy.push_back(run_json(r));
        domain::Json out = domain::Json::object();
        out["lazy"] = lazy;
        out["matches_eager"] =
            !pwb_test::json_compare(eager, lazy).has_value();
        expect_json("db_lazy_list_runs", out, o("db_lazy_list_runs"));
    }
    {
        domain::Json eager = domain::Json::array();
        for (const auto& v : doc.versions) {
            if (v.asset_id.str() == "asset_a") eager.push_back(version_json(v));
        }
        domain::Json lazy = domain::Json::array();
        for (const auto& v : list_version_models_for_asset(db, "asset_a")) {
            lazy.push_back(version_json(v));
        }
        domain::Json out = domain::Json::object();
        out["lazy"] = lazy;
        out["matches_eager"] =
            !pwb_test::json_compare(eager, lazy).has_value();
        expect_json("db_lazy_versions_for_asset", out,
                    o("db_lazy_versions_for_asset"));
    }
    {
        domain::Json eager = domain::Json::array();
        for (const auto& v : doc.versions) eager.push_back(version_json(v));
        domain::Json lazy = domain::Json::array();
        for (const auto& v : list_all_version_models(db)) {
            lazy.push_back(version_json(v));
        }
        domain::Json out = domain::Json::object();
        out["lazy"] = lazy;
        out["matches_eager"] =
            !pwb_test::json_compare(eager, lazy).has_value();
        expect_json("db_lazy_all_versions", out,
                    expected_json("db_lazy_all_versions"));
    }
    {
        domain::Json eager = domain::Json::array();
        for (const auto& v : doc.versions) {
            for (const auto& parent : v.parent_version_ids) {
                if (parent.str() == "ver_a1") eager.push_back(version_json(v));
            }
        }
        domain::Json lazy = domain::Json::array();
        for (const auto& v : child_version_models(db, "ver_a1")) {
            lazy.push_back(version_json(v));
        }
        domain::Json out = domain::Json::object();
        out["lazy"] = lazy;
        out["matches_eager"] =
            !pwb_test::json_compare(eager, lazy).has_value();
        expect_json("db_lazy_children", out, o("db_lazy_children"));
    }
    {
        domain::Json eager = domain::Json::array();
        for (const auto& t : doc.tags) eager.push_back(tag_json(t));
        domain::Json lazy = domain::Json::array();
        for (const auto& t : list_tag_models(db)) lazy.push_back(tag_json(t));
        domain::Json out = domain::Json::object();
        out["lazy"] = lazy;
        out["matches_eager"] =
            !pwb_test::json_compare(eager, lazy).has_value();
        expect_json("db_lazy_list_tags", out, o("db_lazy_list_tags"));
    }
    {
        domain::Json lazy = domain::Json::array();
        for (const auto& t : tags_for_version(db, "ver_a2")) {
            lazy.push_back(tag_json(t));
        }
        domain::Json eager = domain::Json::array();
        eager.push_back(tag_json(doc.tags[0]));
        domain::Json out = domain::Json::object();
        out["lazy"] = lazy;
        out["matches_eager"] =
            !pwb_test::json_compare(eager, lazy).has_value();
        expect_json("db_lazy_tags_for_version", out,
                    o("db_lazy_tags_for_version"));
    }
    {
        domain::Json lazy = domain::Json::array();
        for (const auto& id : tag_ids_for_asset(db, "asset_a")) {
            lazy.push_back(id);
        }
        domain::Json out = domain::Json::object();
        out["lazy"] = lazy;
        domain::Json eager = domain::Json::array();
        eager.push_back("tag_qc");
        eager.push_back("tag_zone");
        out["matches_eager"] =
            !pwb_test::json_compare(eager, lazy).has_value();
        expect_json("db_lazy_tag_ids_for_asset", out,
                    o("db_lazy_tag_ids_for_asset"));
    }

    // Direction bucketing: anything that is not "output" lands in
    // input_ports — pinned with an injected row.
    raw_exec(sqlite_of(p),
             "INSERT INTO run_ports (run_id, direction, role, version_id,"
             " ordinal, required, entity_type, entity_id, note)"
             " VALUES ('run_r1', 'weird', 'r', 'ver_a1', 9, 1, '', '', '')");
    {
        auto reread = get_run_model(db, "run_r1");
        PWB_TEST_ASSERT(reread.has_value(), "reread run");
        domain::Json out = domain::Json::object();
        domain::Json inputs = domain::Json::array();
        for (const auto& port : reread->input_ports) inputs.push_back(port.role);
        domain::Json outputs = domain::Json::array();
        for (const auto& port : reread->output_ports) {
            outputs.push_back(port.role);
        }
        out["input_roles"] = std::move(inputs);
        out["output_roles"] = std::move(outputs);
        expect_json("db_lazy_weird_direction_bucket", out,
                    o("db_lazy_weird_direction_bucket"));
    }

    // >500-id chunk boundary: first-seen order preserved across chunks.
    {
        CatalogDocument bulk;
        bulk.catalog_revision = 1;
        constexpr int n = 520;
        for (int i = 0; i < n; ++i) {
            char buffer[16];
            std::snprintf(buffer, sizeof(buffer), "b%04d", i);
            DataAsset a = mk_asset(buffer, "Bulk " + std::to_string(i));
            bulk.assets.push_back(std::move(a));
        }
        const fs::path pbulk = proj("bulk");
        CatalogRepository repobulk(sqlite_of(pbulk));
        PWB_TEST_ASSERT(repobulk.open_read_write().is_ok(), "open bulk");
        PWB_TEST_ASSERT(repobulk.write_all(bulk).code == domain::ErrorCode::Ok,
                        "write_all bulk");
        PWB_TEST_ASSERT(repobulk.open_read_write().is_ok(), "reopen bulk");
        std::vector<std::string> request;
        for (int i = 0; i < n; ++i) {
            char buffer[16];
            std::snprintf(buffer, sizeof(buffer), "b%04d", (i * 37) % n);
            request.push_back(buffer);
        }
        request.push_back("b0000");
        request.push_back("missing");
        auto got = get_asset_models(repobulk.writable_database(), request);
        domain::Json out = domain::Json::object();
        out["total"] = static_cast<int>(bulk.assets.size());
        out["returned_keys"] = static_cast<int>(got.size());
        domain::Json head = domain::Json::array();
        for (std::size_t i = 0; i < got.size() && i < 12; ++i) {
            head.push_back(got[i].first);
        }
        out["first_seen_order_head"] = std::move(head);
        std::vector<std::string> dedup;
        for (std::size_t i = 0; i < request.size(); ++i) {
            if (request[i] == "missing") continue;
            bool seen = false;
            for (std::size_t j = 0; j < i; ++j) {
                if (request[j] == request[i]) { seen = true; break; }
            }
            if (!seen) dedup.push_back(request[i]);
        }
        bool order_matches = got.size() == dedup.size();
        for (std::size_t i = 0; i < got.size() && order_matches; ++i) {
            order_matches = got[i].first == dedup[i];
        }
        out["order_matches_request_dedup"] = order_matches;
        expect_json("db_lazy_batch_chunking", out,
                    o("db_lazy_batch_chunking"));
    }

    // find_managed_raw / find_external_by_path predicate matrices.
    {
        domain::Json out = domain::Json::object();
        auto hit = find_managed_raw_sql(db, "/import/a.sgy",
                                        std::string(64, '0'));
        out["hit"] = hit.has_value() ? domain::Json(*hit)
                                     : domain::Json(nullptr);
        auto trashed = find_managed_raw_sql(db, "/import/t.bin",
                                            std::string(64, '7'));
        out["trashed_excluded"] = trashed.has_value()
                                      ? domain::Json(*trashed)
                                      : domain::Json(nullptr);
        auto external = find_managed_raw_sql(db, "/import/ext.las",
                                             std::string(64, '2'));
        out["external_excluded"] = external.has_value()
                                       ? domain::Json(*external)
                                       : domain::Json(nullptr);
        auto stage = find_managed_raw_sql(db, "/import/a2.npy",
                                          std::string("0101010101010101010101010101010101010101010101010101010101010101"));
        out["stage_excluded"] = stage.has_value() ? domain::Json(*stage)
                                                  : domain::Json(nullptr);
        auto sha = find_managed_raw_sql(db, "/import/a.sgy",
                                        std::string(64, 'f'));
        out["sha_mismatch"] = sha.has_value() ? domain::Json(*sha)
                                              : domain::Json(nullptr);
        auto uri = find_managed_raw_sql(db, "/import/other",
                                        std::string(64, '0'));
        out["uri_mismatch"] = uri.has_value() ? domain::Json(*uri)
                                              : domain::Json(nullptr);
        expect_json("db_find_managed_raw", out, o("db_find_managed_raw"));
    }
    {
        domain::Json out = domain::Json::object();
        auto hit = find_external_by_path_sql(
            db, (g_root / "core" / "ext.las").string());
        out["hit"] = hit.has_value() ? domain::Json(*hit)
                                     : domain::Json(nullptr);
        auto trashed = find_external_by_path_sql(db, "/gone/tx.las");
        out["trashed_excluded"] = trashed.has_value()
                                      ? domain::Json(*trashed)
                                      : domain::Json(nullptr);
        auto managed = find_external_by_path_sql(
            db, "core.artifacts/raw/asset_a/ver_a1/a.sgy");
        out["managed_excluded"] = managed.has_value()
                                      ? domain::Json(*managed)
                                      : domain::Json(nullptr);
        auto unknown = find_external_by_path_sql(db, "/nope/x.las");
        out["unknown"] = unknown.has_value() ? domain::Json(*unknown)
                                             : domain::Json(nullptr);
        expect_json("db_find_external_by_path", out,
                    o("db_find_external_by_path"));
    }
}

PWB_CASE(query_surface) {
    ensure_init();
    CatalogDocument doc = core_doc();
    const fs::path p = proj("coreq");
    CatalogRepository repo(sqlite_of(p));
    PWB_TEST_ASSERT(repo.open_read_write().is_ok(), "open coreq");
    PWB_TEST_ASSERT(repo.write_all(doc).code == domain::ErrorCode::Ok,
                    "write_all coreq");
    PWB_TEST_ASSERT(repo.open_read_write().is_ok(), "reopen coreq");
    Database& db = repo.writable_database();
    DocumentIndex index(doc);

    auto sorted_ids = [](std::vector<std::string> ids) {
        std::sort(ids.begin(), ids.end());
        return ids;
    };
    auto ids_json = [](const std::vector<std::string>& ids) {
        domain::Json j = domain::Json::array();
        for (const auto& id : ids) j.push_back(id);
        return j;
    };

    domain::Json meta_flag = domain::Json::object();
    meta_flag["flag"] = true;
    domain::Json meta_approved = domain::Json::object();
    meta_approved["review_status"] = "approved";
    domain::Json meta_n = domain::Json::object();
    meta_n["n"] = 5;
    domain::Json schema_x = domain::Json::object();
    schema_x["x"] = domain::Json::array();
    domain::Json meta_sci_false = domain::Json::object();
    meta_sci_false["scientific"] = false;

    // One (frozen case repr, query) pair per generator matrix row. Pair
    // values carry queries.py's str(v) stringification on BOTH paths; the
    // db-layer raw-bool edge keeps the native bool.
    struct Row {
        domain::Json case_json;
        AssetSearchQuery query;
    };
    auto text_row = [&](const std::string& text) {
        Row row;
        row.case_json["text"] = text;
        row.query.text = text;
        return row;
    };
    std::vector<Row> rows;
    rows.push_back(text_row("ALPHA"));
    rows.push_back(text_row("seismic a"));
    rows.push_back(text_row("grünfeld"));
    rows.push_back(text_row("GRÜNFELD"));  // §E B-4 divergence, see below
    rows.push_back(text_row("m%m"));
    rows.push_back(text_row("a_s"));
    {
        Row row;
        row.case_json["stage"] = "DataStage.RAW";
        row.query.stage = domain::DataStage::Raw;
        rows.push_back(std::move(row));
    }
    {
        Row row;
        row.case_json["tag"] = "QC";
        row.query.tags = {"QC"};
        rows.push_back(std::move(row));
    }
    {
        Row row;
        row.case_json["tags"] = "[' QC ', '', 'zone']";
        row.case_json["tag_op"] = "and";
        row.query.tags = {" QC ", "", "zone"};
        rows.push_back(std::move(row));
    }
    {
        Row row;
        row.case_json["tags"] = "['qc', 'zone']";
        row.case_json["tag_op"] = "or";
        row.query.tags = {"qc", "zone"};
        row.query.tag_op = "or";
        rows.push_back(std::move(row));
    }
    {
        Row row;
        row.case_json["tags"] = "['qc', 'nope']";
        row.case_json["tag_op"] = "or";
        row.query.tags = {"qc", "nope"};
        row.query.tag_op = "or";
        rows.push_back(std::move(row));
    }
    {
        Row row;
        row.case_json["type"] = "grid";
        row.query.type = "grid";
        rows.push_back(std::move(row));
    }
    {
        Row row;
        row.case_json["metadata"] = "{'review_status': 'approved'}";
        row.query.metadata.emplace_back("review_status",
                                        domain::Json("approved"));
        rows.push_back(std::move(row));
    }
    {
        Row row;
        row.case_json["metadata"] = "{'flag': True}";
        row.query.metadata.emplace_back("flag", domain::Json("True"));
        rows.push_back(std::move(row));
    }
    {
        Row row;
        row.case_json["metadata"] = "{'n': 5}";
        row.query.metadata.emplace_back("n", domain::Json("5"));
        rows.push_back(std::move(row));
    }
    rows.push_back(text_row("Hidden"));

    domain::Json cases = domain::Json::array();
    for (Row& row : rows) {
        std::vector<std::string> sql_rows = search_assets_sql(db, row.query);
        AssetSearchQuery unfiltered = row.query;
        unfiltered.include_trashed = true;
        std::vector<std::string> sql_unfiltered =
            search_assets_sql(db, unfiltered);
        std::vector<std::string> scan =
            search_assets_scan(doc, index, row.query);
        domain::Json entry = domain::Json::object();
        entry["case"] = row.case_json;
        entry["sql"] = ids_json(sorted_ids(sql_rows));
        entry["sql_unfiltered"] = ids_json(sorted_ids(sql_unfiltered));
        entry["scan"] = ids_json(sorted_ids(scan));
        entry["equal"] = sorted_ids(sql_rows) == sorted_ids(scan);
        cases.push_back(std::move(entry));
    }
    // include_trashed variant on one text query.
    {
        AssetSearchQuery query;
        query.text = "Hidden";
        query.include_trashed = true;
        std::vector<std::string> scan = search_assets_scan(doc, index, query);
        std::vector<std::string> sql = search_assets_sql(db, query);
        domain::Json entry = domain::Json::object();
        domain::Json case_json = domain::Json::object();
        case_json["text"] = "Hidden";
        case_json["include_trashed"] = "True";
        entry["case"] = std::move(case_json);
        entry["sql"] = ids_json(sorted_ids(sql));
        entry["sql_unfiltered"] = ids_json(sorted_ids(sql));
        entry["scan"] = ids_json(sorted_ids(scan));
        entry["equal"] = sorted_ids(sql) == sorted_ids(scan);
        cases.push_back(std::move(entry));
    }
    // db-layer metadata normalization with a RAW bool (True → "1"): matches
    // json_extract's CAST — no scan counterpart.
    {
        AssetSearchQuery query;
        query.metadata.emplace_back("flag", domain::Json(true));
        query.include_trashed = true;
        domain::Json entry = domain::Json::object();
        domain::Json case_json = domain::Json::object();
        case_json["db_layer"] = "metadata flag raw True";
        entry["case"] = std::move(case_json);
        entry["sql"] = ids_json(
            sorted_ids(search_assets_sql(db, query)));
        entry["sql_unfiltered"] = nullptr;
        entry["scan"] = nullptr;
        entry["equal"] = nullptr;
        cases.push_back(std::move(entry));
    }
    {
        domain::Json expected = o("db_search_dual_path");
        // §E B-4: the C++ fold is ASCII-only (no NFKC) — a non-ASCII case
        // fold ("GRÜNFELD") cannot match on either path. The Python-side
        // expectation row is replaced with the divergence direction
        // (empty on both paths); the row itself stays pinned.
        domain::Json adjusted = domain::Json::array();
        for (const auto& entry : expected) {
            const std::string text =
                entry.at("case").contains("text")
                    ? entry.at("case").at("text").get<std::string>()
                    : std::string();
            if (text == "GRÜNFELD") {
                domain::Json b4 = entry;
                for (const char* key : {"sql", "sql_unfiltered", "scan"}) {
                    b4[key] = domain::Json::array();
                }
                adjusted.push_back(std::move(b4));
                continue;
            }
            adjusted.push_back(entry);
        }
        expect_json("db_search_dual_path", cases, adjusted);
    }

    // Aggregates: current-version stage join, types, tag display fallback,
    // review falsy skipped.
    {
        auto agg_json = [](const CatalogAggregates& agg) {
            domain::Json j = domain::Json::object();
            domain::Json stages = domain::Json::object();
            for (const auto& [k, v] : agg.stages) stages[k] = v;
            j["stages"] = std::move(stages);
            domain::Json types = domain::Json::object();
            for (const auto& [k, v] : agg.types) types[k] = v;
            j["types"] = std::move(types);
            domain::Json tags = domain::Json::object();
            for (const auto& [k, v] : agg.tags) tags[k] = v;
            j["tags"] = std::move(tags);
            domain::Json review = domain::Json::object();
            for (const auto& [k, v] : agg.review_status) review[k] = v;
            j["review_status"] = std::move(review);
            j["total"] = agg.total;
            return j;
        };
        domain::Json out = domain::Json::object();
        out["live"] = agg_json(catalog_aggregates_sql(db, false));
        out["all"] = agg_json(catalog_aggregates_sql(db, true));
        expect_json("db_aggregates", out, o("db_aggregates"));
    }

    // list_versions orders by version_number; the lazy per-asset read
    // keeps rowid/document order.
    {
        domain::Json out = domain::Json::object();
        domain::Json sql_ids = domain::Json::array();
        for (const auto& v : list_versions_sql(db, "asset_a")) {
            sql_ids.push_back(v.id.str());
        }
        out["sql_by_number"] = std::move(sql_ids);
        domain::Json lazy_ids = domain::Json::array();
        for (const auto& v : list_version_models_for_asset(db, "asset_a")) {
            lazy_ids.push_back(v.id.str());
        }
        out["lazy_by_rowid"] = std::move(lazy_ids);
        std::vector<const DataVersion*> sorted_versions;
        for (const auto& v : doc.versions) {
            if (v.asset_id.str() == "asset_a") sorted_versions.push_back(&v);
        }
        std::stable_sort(sorted_versions.begin(), sorted_versions.end(),
                         [](const DataVersion* a, const DataVersion* b) {
                             return a->version_number < b->version_number;
                         });
        domain::Json service_ids = domain::Json::array();
        for (const DataVersion* v : sorted_versions) {
            service_ids.push_back(v->id.str());
        }
        out["service_sorted"] = std::move(service_ids);
        expect_json("db_list_versions_order", out, o("db_list_versions_order"));
    }

    {
        domain::Json out = domain::Json::object();
        for (const char* vid : {"ver_a2", "ver_a1"}) {
            domain::Json entry = domain::Json::object();
            LineageEdges edges = lineage_edges_sql(db, vid);
            domain::Json children = domain::Json::array();
            for (const auto& id : edges.children) children.push_back(id);
            entry["children"] = std::move(children);
            domain::Json parents = domain::Json::array();
            for (const auto& id : edges.parents) parents.push_back(id);
            entry["parents"] = std::move(parents);
            out[vid] = std::move(entry);
        }
        expect_json("db_lineage_edges", out, o("db_lineage_edges"));
    }

    {
        domain::Json out = domain::Json::object();
        out["assets_qc_space"] =
            ids_json(assets_for_tag_sql(db, " QC "));
        out["assets_qc_case"] = ids_json(assets_for_tag_sql(db, "QC"));
        out["versions_ZONE"] = ids_json(versions_for_tag_sql(db, "ZONE"));
        out["assets_unknown"] = ids_json(assets_for_tag_sql(db, "nope"));
        expect_json("db_for_tag_normalization", out,
                    o("db_for_tag_normalization"));
    }
}

// ---- C. manifest ladder -------------------------------------------------------

PWB_CASE(manifest_ladder) {
    ensure_init();
    auto digest_of = [](const fs::path& path) {
        auto digest = domain::Sha256::of_file(path);
        return digest.has_value() ? *digest : std::string();
    };
    auto mf_doc = [](int revision, const std::string& name) {
        CatalogDocument doc;
        doc.catalog_revision = revision;
        DataAsset a = mk_asset("mf_a", name);
        a.type = "seismic";
        DataVersion v = mk_ver("mf_v1", "mf_a", 1);
        v.path = "mf.artifacts/raw/mf_a/mf_v1/a.sgy";
        v.sha256 = std::string(64, '0');
        a.current_version_id = v.id;
        doc.assets.push_back(std::move(a));
        doc.versions.push_back(std::move(v));
        return doc;
    };

    const fs::path p = proj("mf1");
    const fs::path manifest = catalog_manifest_file(p);
    const fs::path bak = catalog_manifest_bak_file(p);
    CatalogDocument doc1 = mf_doc(1, "Manifest Asset");
    CatalogDocument doc2 = mf_doc(2, "Second");
    ManifestCheckpointState state;
    PWB_TEST_ASSERT(save_manifest(manifest, doc1, false, &state).code ==
                        domain::ErrorCode::Ok,
                    "save doc1");
    {
        auto loaded = load_manifest(manifest);
        PWB_TEST_ASSERT(loaded.is_ok(), "load doc1");
        domain::Json out = domain::Json::object();
        out["revision"] = loaded.value().document.catalog_revision;
        domain::Json names = domain::Json::array();
        for (const auto& a : loaded.value().document.assets) {
            names.push_back(a.name);
        }
        out["asset_names"] = std::move(names);
        std::error_code ec;
        out["canonical_exists"] = fs::is_regular_file(manifest, ec);
        expect_json("manifest_load_ok", out, o("manifest_load_ok"));
    }
    const std::string first_digest = digest_of(manifest);
    PWB_TEST_ASSERT(save_manifest(manifest, doc2, false, &state).code ==
                        domain::ErrorCode::Ok,
                    "save doc2 (rotation)");
    {
        domain::Json out = domain::Json::object();
        out["canonical_is_rev2"] = [&] {
            auto loaded = load_manifest(manifest);
            return loaded.is_ok() &&
                   loaded.value().document.catalog_revision == 2;
        }();
        out["bak_matches_previous"] = digest_of(bak) == first_digest;
        expect_json("manifest_save_rotation", out, o("manifest_save_rotation"));
    }
    // #1183 unchanged-skip: same payload, untouched mtimes.
    {
        const auto mtime_before = mtime_ns_of(manifest);
        const auto bak_mtime_before = mtime_ns_of(bak);
        PWB_TEST_ASSERT(save_manifest(manifest, doc2, false, &state).code ==
                            domain::ErrorCode::Ok,
                        "save doc2 again");
        domain::Json out = domain::Json::object();
        out["canonical_mtime_unchanged"] =
            mtime_ns_of(manifest).has_value() &&
            mtime_ns_of(manifest) == mtime_before;
        out["bak_mtime_unchanged"] = mtime_ns_of(bak).has_value() &&
                                     mtime_ns_of(bak) == bak_mtime_before;
        // External modification defeats the mtime guard → rewrite.
        const auto old = mtime_ns_of(manifest).value_or(0);
        struct ::utimbuf times{static_cast<time_t>(old / 1000000000LL + 10),
                               static_cast<time_t>(old / 1000000000LL + 10)};
        ::utime(manifest.c_str(), &times);
        PWB_TEST_ASSERT(save_manifest(manifest, doc2, false, &state).code ==
                            domain::ErrorCode::Ok,
                        "save doc2 after touch");
        out["external_edit_rewrites"] =
            mtime_ns_of(manifest).value_or(0) != old;
        expect_json("manifest_save_unchanged_skip", out,
                    o("manifest_save_unchanged_skip"));
        keep_actual("manifest_save_unchanged_skip", out);
    }
    // First-save backup seeding: a fresh project's first save leaves a bak
    // holding the SAME revision payload.
    {
        const fs::path p2 = proj("mf2");
        const fs::path manifest2 = catalog_manifest_file(p2);
        const fs::path bak2 = catalog_manifest_bak_file(p2);
        PWB_TEST_ASSERT(save_manifest(manifest2, doc1).code ==
                            domain::ErrorCode::Ok,
                        "seed save");
        domain::Json out = domain::Json::object();
        std::error_code ec;
        out["bak_exists"] = fs::is_regular_file(bak2, ec);
        out["digests_equal"] = digest_of(manifest2) == digest_of(bak2);
        expect_json("manifest_save_seed", out, o("manifest_save_seed"));
    }
    // L3: canonical missing, bak present → re-promotion.
    {
        const fs::path p3 = proj("mf3");
        const fs::path manifest3 = catalog_manifest_file(p3);
        const fs::path bak3 = catalog_manifest_bak_file(p3);
        PWB_TEST_ASSERT(save_manifest(manifest3, doc1).code ==
                            domain::ErrorCode::Ok,
                        "mf3 save1");
        PWB_TEST_ASSERT(save_manifest(manifest3, doc2).code ==
                            domain::ErrorCode::Ok,
                        "mf3 save2");
        std::error_code ec;
        fs::remove(manifest3, ec);
        auto loaded = load_manifest(manifest3);
        PWB_TEST_ASSERT(loaded.is_ok(), "mf3 load");
        domain::Json out = domain::Json::object();
        out["revision"] = loaded.value().document.catalog_revision;
        out["bak_consumed"] = !fs::is_regular_file(bak3, ec);
        out["canonical_back"] = fs::is_regular_file(manifest3, ec);
        expect_json("manifest_load_bak_repromote", out,
                    o("manifest_load_bak_repromote"));
    }
    // L3': canonical corrupt, bak readable → same promotion.
    {
        const fs::path p4 = proj("mf4");
        const fs::path manifest4 = catalog_manifest_file(p4);
        const fs::path bak4 = catalog_manifest_bak_file(p4);
        PWB_TEST_ASSERT(save_manifest(manifest4, doc1).code ==
                            domain::ErrorCode::Ok,
                        "mf4 save1");
        PWB_TEST_ASSERT(save_manifest(manifest4, doc2).code ==
                            domain::ErrorCode::Ok,
                        "mf4 save2");
        { std::ofstream out_file(manifest4); out_file << "{corrupt"; }
        auto loaded = load_manifest(manifest4);
        PWB_TEST_ASSERT(loaded.is_ok(), "mf4 load");
        domain::Json out = domain::Json::object();
        out["revision"] = loaded.value().document.catalog_revision;
        std::error_code ec;
        out["bak_consumed"] = !fs::is_regular_file(bak4, ec);
        out["canonical_back"] = fs::is_regular_file(manifest4, ec);
        expect_json("manifest_load_corrupt_isolated", out,
                    o("manifest_load_corrupt_isolated"));
    }
    // L2: corrupt canonical, no bak — skeleton byte-identical, the
    // parenthesized parser detail is masked (§E B-14), file isolated once.
    {
        const fs::path p5 = proj("mf5");
        const fs::path manifest5 = catalog_manifest_file(p5);
        std::error_code ec;
        fs::create_directories(manifest5.parent_path(), ec);
        { std::ofstream out_file(manifest5); out_file << "not json at all"; }
        auto loaded = load_manifest(manifest5);
        PWB_TEST_ASSERT(!loaded.is_ok(), "mf5 load must fail");
        const std::string message = loaded.error().message;
        const std::string prefix =
            rooted("Catalog file is corrupt and no backup is available: "
                   "{ROOT}/mf5/mf5.artifacts/metadata/catalog.json (");
        PWB_TEST_ASSERT(message.rfind(prefix, 0) == 0 && !message.empty() &&
                        message.back() == ')',
                        "L2 skeleton parity: " + message);
        const int isolated = corrupt_files_near(manifest5, "catalog.json");
        PWB_TEST_ASSERT_EQ(
            o("manifest_load_no_backup_error").at("isolated_count").get<int>(),
            isolated, "L2 isolated count parity");
    }
    // L4: both corrupt — double isolation, audit-#848 skeleton.
    {
        const fs::path p6 = proj("mf6");
        const fs::path manifest6 = catalog_manifest_file(p6);
        const fs::path bak6 = catalog_manifest_bak_file(p6);
        std::error_code ec;
        fs::create_directories(manifest6.parent_path(), ec);
        { std::ofstream out_file(manifest6); out_file << "{nope"; }
        { std::ofstream out_file(bak6); out_file << "[nope"; }
        auto loaded = load_manifest(manifest6);
        PWB_TEST_ASSERT(!loaded.is_ok(), "mf6 load must fail");
        const std::string message = loaded.error().message;
        const std::string prefix = rooted(
            "Catalog file and its backup are both corrupt: "
            "{ROOT}/mf6/mf6.artifacts/metadata/catalog.json (backup error: ");
        PWB_TEST_ASSERT(message.rfind(prefix, 0) == 0 && !message.empty() &&
                        message.back() == ')',
                        "L4 skeleton parity: " + message);
        const int isolated = corrupt_files_near(manifest6, "catalog.json");
        PWB_TEST_ASSERT_EQ(
            o("manifest_load_both_corrupt_error").at("isolated_count")
                .get<int>(),
            isolated, "L4 isolated count parity");
    }
    // L5: both absent — empty document, revision 0.
    {
        const fs::path p7 = proj("mf7");
        auto loaded = load_manifest(catalog_manifest_file(p7));
        PWB_TEST_ASSERT(loaded.is_ok(), "mf7 load");
        domain::Json out = domain::Json::object();
        out["revision"] = loaded.value().document.catalog_revision;
        out["empty"] = loaded.value().document.assets.empty() &&
                       loaded.value().document.versions.empty();
        expect_json("manifest_load_absent", out, o("manifest_load_absent"));
    }
}

// ---- D. open health matrix + manifest adoption -------------------------------

PWB_CASE(open_health_matrix) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;

    // Canonical reopen: revision baseline + eager maps + flushed baseline.
    {
        const fs::path p = proj("op1");
        auto opened = open_catalog(p, options);
        PWB_TEST_ASSERT(opened.is_ok(),
                        "op1 open: " + opened.error().message);
        CatalogServiceCore core = std::move(opened.value());
        const fs::path src = g_root / "op1" / "import.dat";
        { std::ofstream out(src, std::ios::binary); out << "open-canonical"; }
        setup_register_result(core, p, "Opened", "seismic", "sgy",
                              domain::Json::object(), src,
                              domain::DataStage::Raw);
        core.close();
        auto reopened = open_catalog(p, options);
        PWB_TEST_ASSERT(reopened.is_ok(), "op1 reopen");
        CatalogServiceCore core2 = std::move(reopened.value());
        domain::Json out = domain::Json::object();
        out["health"] = health_text(core2.open_report().health);
        auto revision = core2.index_revision();
        out["revision"] = revision.has_value() ? domain::Json(*revision)
                                               : domain::Json(nullptr);
        out["doc_revision"] = core2.document().catalog_revision;
        // maps_built: the eager maps resolve the first entity without any
        // rebuild (a miss-triggered rebuild is the only other path).
        const std::string first_asset =
            core2.document().assets.at(0).id.str();
        out["maps_built"] = core2.find_asset(first_asset) != nullptr;
        out["flushed_matches"] =
            core2.flushed_revision().has_value() &&
            *core2.flushed_revision() ==
                static_cast<long long>(core2.document().catalog_revision);
        domain::Json names = domain::Json::array();
        for (const auto& a : core2.document().assets) names.push_back(a.name);
        out["asset_names"] = std::move(names);
        expect_json("service_open_canonical", out, o("service_open_canonical"));
    }
    // Absent: empty document, revision 0, canonical initialized, no
    // manifest checkpoint.
    {
        const fs::path p2 = proj("op2");
        auto opened = open_catalog(p2, options);
        PWB_TEST_ASSERT(opened.is_ok(), "op2 open");
        domain::Json out = domain::Json::object();
        // Python store_health() probes the store AFTER the open flow.
        out["health"] =
            health_text(CatalogRepository(sqlite_of(p2)).status().health);
        auto revision = opened.value().index_revision();
        out["revision"] = revision.has_value() ? domain::Json(*revision)
                                               : domain::Json(nullptr);
        out["empty_doc"] = opened.value().document().assets.empty();
        std::error_code ec;
        out["manifest_exists"] =
            fs::is_regular_file(catalog_manifest_file(p2), ec);
        expect_json("service_open_absent_init", out,
                    o("service_open_absent_init"));
    }
    // Legacy manifest migration: transactional write_all + mtime baseline.
    {
        const fs::path p3 = proj("op3");
        CatalogDocument legacy;
        legacy.catalog_revision = 3;
        DataAsset a = mk_asset("mf_a", "Legacy Asset");
        a.type = "seismic";
        DataVersion v = mk_ver("mf_v1", "mf_a", 1);
        v.path = "mf.artifacts/raw/mf_a/mf_v1/a.sgy";
        v.sha256 = std::string(64, '0');
        a.current_version_id = v.id;
        legacy.assets.push_back(std::move(a));
        legacy.versions.push_back(std::move(v));
        PWB_TEST_ASSERT(
            save_manifest(catalog_manifest_file(p3), legacy).code ==
                domain::ErrorCode::Ok,
            "op3 legacy manifest");
        auto opened = open_catalog(p3, options);
        PWB_TEST_ASSERT(opened.is_ok(), "op3 open");
        domain::Json out = domain::Json::object();
        out["health"] =
            health_text(CatalogRepository(sqlite_of(p3)).status().health);
        auto revision = opened.value().index_revision();
        out["revision"] = revision.has_value() ? domain::Json(*revision)
                                               : domain::Json(nullptr);
        out["doc_revision"] = opened.value().document().catalog_revision;
        domain::Json names = domain::Json::array();
        for (const auto& asset : opened.value().document().assets) {
            names.push_back(asset.name);
        }
        out["asset_names"] = std::move(names);
        out["manifest_mtime_recorded"] =
            opened.value()
                .repository()
                .recorded_manifest_mtime_ns()
                .has_value();
        expect_json("service_open_legacy_migration", out,
                    o("service_open_legacy_migration"));
    }
    // Corrupt store: forensics isolation + reset + manifest rebuild.
    {
        const fs::path p4 = proj("op4");
        CatalogDocument legacy2;
        legacy2.catalog_revision = 2;
        DataAsset a = mk_asset("mf_a", "Corrupt Survivor");
        a.type = "seismic";
        DataVersion v = mk_ver("mf_v1", "mf_a", 1);
        v.path = "mf.artifacts/raw/mf_a/mf_v1/a.sgy";
        v.sha256 = std::string(64, '0');
        a.current_version_id = v.id;
        legacy2.assets.push_back(std::move(a));
        legacy2.versions.push_back(std::move(v));
        PWB_TEST_ASSERT(
            save_manifest(catalog_manifest_file(p4), legacy2).code ==
                domain::ErrorCode::Ok,
            "op4 manifest");
        const fs::path dbp = sqlite_of(p4);
        {
            std::ofstream out_file(dbp, std::ios::binary);
            out_file << "garbage bytes, definitely not sqlite";
        }
        auto opened = open_catalog(p4, options);
        PWB_TEST_ASSERT(opened.is_ok(), "op4 open");
        domain::Json out = domain::Json::object();
        out["health"] =
            health_text(CatalogRepository(sqlite_of(p4)).status().health);
        auto revision = opened.value().index_revision();
        out["revision"] = revision.has_value() ? domain::Json(*revision)
                                               : domain::Json(nullptr);
        domain::Json names = domain::Json::array();
        for (const auto& asset : opened.value().document().assets) {
            names.push_back(asset.name);
        }
        out["asset_names"] = std::move(names);
        out["isolated_count"] = corrupt_files_near(dbp, "catalog.sqlite");
        expect_json("service_open_corrupt_rebuild", out,
                    o("service_open_corrupt_rebuild"));
    }
    // Unreadable store: refuse open with the verbatim message.
    {
        const fs::path p5 = proj("op5");
        const fs::path dbp5 = sqlite_of(p5);
        std::error_code ec;
        fs::create_directories(dbp5.parent_path(), ec);
        {
            std::ofstream out_file(dbp5, std::ios::binary);
            out_file << "placeholder bytes to be non-empty";
        }
        fs::permissions(dbp5, fs::perms::none, ec);
        CatalogRepository probe(dbp5);
        domain::Json out = domain::Json::object();
        out["health"] = health_text(probe.status().health);
        auto opened = open_catalog(p5, options);
        PWB_TEST_ASSERT(!opened.is_ok(), "op5 must refuse");
        out["type"] = "CatalogError";
        out["error"] = rooted(opened.error().message);
        fs::permissions(dbp5,
                        fs::perms::owner_read | fs::perms::owner_write |
                            fs::perms::group_read | fs::perms::others_read,
                        ec);
        expect_json("service_open_unreadable_error", out,
                    expected_json("service_open_unreadable_error"));
    }
    // Manifest mtime bookkeeping: a NEWER legacy revision is adopted and
    // re-imported; an equal revision is not.
    {
        const fs::path p6 = proj("op6");
        auto opened = open_catalog(p6, options);
        PWB_TEST_ASSERT(opened.is_ok(), "op6 open");
        CatalogServiceCore core = std::move(opened.value());
        const fs::path src = g_root / "op6" / "import.dat";
        { std::ofstream out(src, std::ios::binary); out << "adopt-me"; }
        setup_register_result(core, p6, "Store Side", "seismic", "sgy",
                              domain::Json::object(), src,
                              domain::DataStage::Raw);
        core.close();

        CatalogDocument foreign;
        foreign.catalog_revision = 5;
        foreign.assets.push_back(mk_asset("asset_foreign", "Foreign Wins"));
        PWB_TEST_ASSERT(
            save_manifest(catalog_manifest_file(p6), foreign).code ==
                domain::ErrorCode::Ok,
            "op6 foreign manifest");
        domain::Json adopted = domain::Json::object();
        {
            auto reopened = open_catalog(p6, options);
            PWB_TEST_ASSERT(reopened.is_ok(), "op6 reopen");
            auto revision = reopened.value().index_revision();
            adopted["revision"] = revision.has_value()
                                      ? domain::Json(*revision)
                                      : domain::Json(nullptr);
            domain::Json names = domain::Json::array();
            for (const auto& a : reopened.value().document().assets) {
                names.push_back(a.name);
            }
            adopted["asset_names"] = std::move(names);
        }
        CatalogDocument equal;
        equal.catalog_revision = 5;
        equal.assets.push_back(mk_asset("asset_equal", "Equal Ignored"));
        PWB_TEST_ASSERT(
            save_manifest(catalog_manifest_file(p6), equal).code ==
                domain::ErrorCode::Ok,
            "op6 equal manifest");
        domain::Json ignored = domain::Json::object();
        {
            auto reopened2 = open_catalog(p6, options);
            PWB_TEST_ASSERT(reopened2.is_ok(), "op6 reopen2");
            auto revision = reopened2.value().index_revision();
            ignored["revision"] = revision.has_value()
                                      ? domain::Json(*revision)
                                      : domain::Json(nullptr);
            domain::Json names = domain::Json::array();
            for (const auto& a : reopened2.value().document().assets) {
                names.push_back(a.name);
            }
            ignored["asset_names"] = std::move(names);
        }
        domain::Json out = domain::Json::object();
        out["newer_adopted"] = std::move(adopted);
        out["equal_ignored"] = std::move(ignored);
        expect_json("service_open_manifest_adoption", out,
                    o("service_open_manifest_adoption"));
    }
}

// ---- E. resolve_path ladder ----------------------------------------------------

PWB_CASE(resolve_ladder) {
    ensure_init();
    const fs::path root = g_root / "rs";
    std::error_code ec;
    fs::create_directories(root, ec);
    const fs::path project = root / "rs.paleo.json";
    { std::ofstream out(project); out << "{}"; }

    const std::map<std::string, std::string> data = {
        {"inproj.las", "in-project"},
        {"relocated.bin", "relocated-content"},
        {"no_identity.dat", "stranger"},
        {"same_name.las", "different-content"},
    };
    for (const auto& [name, content] : data) {
        std::ofstream out(root / name, std::ios::binary);
        out << content;
    }
    fs::create_directories(root / "deep", ec);
    {
        std::ofstream out(root / "deep" / "lastwo.bin", std::ios::binary);
        out << "lastwo";
    }
    fs::create_directories(root / "resolve" / "data", ec);
    {
        std::ofstream out(root / "resolve" / "data" / "named.las",
                          std::ios::binary);
        out << "reanchored";
    }
    fs::create_directories(root / "subdir", ec);
    {
        std::ofstream out(root / "subdir" / "relocated.bin", std::ios::binary);
        out << "decoy-not-used";
    }

    struct Case {
        const char* name;
        bool managed;
        std::string path;
        std::optional<std::string> sha256;
        std::optional<std::int64_t> size_bytes;
    };
    const std::vector<Case> cases = {
        {"managed_join_missing", true, "rs.artifacts/raw/a/v/gone.sgy",
         std::nullopt, std::nullopt},
        {"external_absolute", false, (root / "inproj.las").string(),
         std::nullopt, std::nullopt},
        {"project_relative", false, "inproj.las", std::nullopt, std::nullopt},
        {"reanchor_first_occurrence", false,
         "/media/resolve/resolve/data/named.las", sha_bytes("reanchored"),
         std::nullopt},
        {"sha_gate_basename_pass", false, "/gone/dir/relocated.bin",
         sha_bytes("relocated-content"), std::nullopt},
        {"size_gate_two_segments", false, "/gone/deep/lastwo.bin",
         std::nullopt, 6},
        {"sha_gate_mismatch_falls_through", false, "/gone/dir/same_name.las",
         sha_bytes("not-this"), std::nullopt},
        {"no_identity_fail_closed", false, "/gone/dir/no_identity.dat",
         std::nullopt, std::nullopt},
        {"all_rungs_miss", false, "/gone/fully/absent.las", std::nullopt,
         std::nullopt},
    };
    auto canonical = [](const std::string& text) {
        std::error_code canon_ec;
        const fs::path path = fs::weakly_canonical(text, canon_ec);
        return (canon_ec || path.empty()) ? text : path.string();
    };
    domain::Json out = domain::Json::array();
    for (const Case& c : cases) {
        DataVersion v = mk_ver("rv_" + std::string(c.name), "a", 1);
        v.managed = c.managed;
        v.path = c.path;
        v.sha256 = c.sha256;
        v.size_bytes = c.size_bytes;
        domain::Json entry = domain::Json::object();
        entry["case"] = c.name;
        entry["resolved"] = canonical(resolve_payload_path(project, v).string());
        out.push_back(std::move(entry));
    }
    domain::Json expected = o("resolve_path_ladder");
    for (auto& entry : expected) {
        entry["resolved"] =
            canonical(rooted(entry["resolved"].get<std::string>()));
    }
    keep_actual("resolve_path_ladder", out);
    expect_json("resolve_path_ladder", out, expected);
}

// ---- F. _CatalogMaps build vs incremental -------------------------------------

PWB_CASE(maps_maintenance) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("maps");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "maps open");
    CatalogServiceCore core = std::move(opened.value());

    CatalogDocument doc;
    {
        DataAsset a1 = mk_asset("m_a1", "Trashed First");
        a1.legacy_resource_id = "res_9";
        a1.trashed = true;
        a1.trashed_at = kNow;
        DataAsset a2 = mk_asset("m_a2", "Live Second");
        a2.legacy_resource_id = "res_9";
        DataAsset a3 = mk_asset("m_a3", "No Legacy");
        DataAsset a4 = mk_asset("m_a4", "Other Bridge");
        a4.legacy_resource_id = "res_8";
        doc.assets = {a1, a2, a3, a4};
    }
    {
        DataVersion r1 = mk_ver("mv_r1", "m_a1", 1);
        r1.managed = true;
        r1.source_uri = "/s/u.bin";
        r1.sha256 = std::string("0101010101010101010101010101010101010101010101010101010101010101");
        DataVersion r2 = mk_ver("mv_r2", "m_a1", 2);
        r2.managed = true;
        r2.source_uri = "/s/u.bin";
        r2.sha256 = std::string("0101010101010101010101010101010101010101010101010101010101010101");
        DataVersion e1 = mk_ver("mv_e1", "m_a2", 1);
        e1.managed = false;
        e1.path = "/e/x.las";
        DataVersion e2 = mk_ver("mv_e2", "m_a2", 2);
        e2.managed = false;
        e2.path = "/e/x.las";
        DataVersion kid = mk_ver("mv_kid", "m_a3", 1,
                                 domain::DataStage::Derived);
        kid.parent_version_ids = {vid("mv_r1")};
        doc.versions = {r1, r2, e1, e2, kid};
    }

    // The build snapshot (_ensure_maps build semantics over the document):
    // first-wins dedup keys, first bridged legacy holder.
    auto build_snapshot = [](const CatalogDocument& doc) {
        domain::Json out = domain::Json::object();
        domain::Json assets = domain::Json::array();
        for (const auto& a : doc.assets) assets.push_back(a.id.str());
        out["assets"] = std::move(assets);
        domain::Json legacy = domain::Json::object();
        for (const auto& a : doc.assets) legacy[a.id.str()] = a.id.str();
        for (const auto& a : doc.assets) {
            if (a.legacy_resource_id.has_value() &&
                !legacy.contains(*a.legacy_resource_id)) {
                legacy[*a.legacy_resource_id] = a.id.str();
            }
        }
        out["legacy"] = std::move(legacy);
        domain::Json managed_raw = domain::Json::object();
        domain::Json external = domain::Json::object();
        for (const auto& v : doc.versions) {
            if (auto key = managed_raw_dedup_key(v)) {
                if (!managed_raw.contains(key->first + "|" + key->second)) {
                    managed_raw[key->first + "|" + key->second] = v.id.str();
                }
            }
            if (auto key = external_dedup_key(v)) {
                if (!external.contains(*key)) external[*key] = v.id.str();
            }
        }
        out["managed_raw"] = std::move(managed_raw);
        out["external"] = std::move(external);
        domain::Json versions_by_asset = domain::Json::object();
        domain::Json children = domain::Json::object();
        for (const auto& v : doc.versions) {
            versions_by_asset[v.asset_id.str()].push_back(v.id.str());
            for (const auto& parent : v.parent_version_ids) {
                children[parent.str()].push_back(v.id.str());
            }
        }
        out["versions_by_asset"] = std::move(versions_by_asset);
        out["children"] = std::move(children);
        return out;
    };

    core.document() = doc;
    core.invalidate_maps();
    // _ensure_maps parity: a lookup builds the maps before the snapshot.
    PWB_TEST_ASSERT(core.find_asset("m_a1") != nullptr, "ensure maps");
    core.invalidate_maps();
    expect_json("maps_build_snapshot", build_snapshot(core.document()),
                o("maps_build_snapshot"));

    // maps_incremental_dedup + maps_remove_buckets (findings §E B-22):
    // the generator froze the INTERNAL maintained-map states (add is
    // LAST-wins on dedup keys, drop is ownership-guarded, single remove
    // keeps the emptied bucket, bulk drops it) via the controlled _maps
    // snapshot read. The C++ CatalogMaps live behind the private Impl
    // with no equivalent observation face in this wave, so the replay
    // drives the same maintenance sequence and pins the DOCUMENT-visible
    // half (the incremental add/remove stay consistent with a rebuild);
    // the three frozen internal map states are recorded as an
    // unexposed-observation gap, NOT a behavioral divergence — the
    // incremental semantics are implemented in service_core.cpp
    // (CatalogMaps::on_add_version / drop_dedup_keys / on_remove_*).
    {
        DataVersion v3 = mk_ver("mv_r3", "m_a1", 3);
        v3.managed = true;
        v3.source_uri = "/s/u.bin";
        v3.sha256 = std::string("0101010101010101010101010101010101010101010101010101010101010101");
        core.add_version(std::move(v3));
        // The maintained index resolves the incrementally added version
        // without any rebuild (find_version only rebuilds on a MISS).
        PWB_TEST_ASSERT(core.find_version("mv_r3") != nullptr,
                        "incremental add lands in the maintained maps");
        PWB_TEST_ASSERT(core.find_version("mv_r1") != nullptr,
                        "older entries stay resolvable");
        domain::Json rebuilt = build_snapshot(core.document());
        PWB_TEST_ASSERT(rebuilt["managed_raw"].contains(
                            "/s/u.bin|" + std::string("0101010101010101010101010101010101010101010101010101010101010101")),
                        "dedup key present after incremental add");
    }
    {
        DataVersion solo = mk_ver("mv_solo", "m_a4", 1);
        const DataVersion* solo_ptr = core.add_version(std::move(solo));
        core.remove_version(solo_ptr);
        domain::Json single = build_snapshot(core.document());
        PWB_TEST_ASSERT(!single["versions_by_asset"].contains("m_a4") ||
                        single["versions_by_asset"]["m_a4"].empty(),
                        "single remove leaves m_a4 versionless");
        DataVersion bulk = mk_ver("mv_bulk", "m_a4", 2);
        const DataVersion* bulk_ptr = core.add_version(std::move(bulk));
        core.remove_versions_bulk({bulk_ptr});
        domain::Json after_bulk = build_snapshot(core.document());
        PWB_TEST_ASSERT(!after_bulk["versions_by_asset"].contains("m_a4"),
                        "bulk remove leaves m_a4 versionless");
    }
    // Rebridge asymmetry: build keeps the FIRST bridged holder (trashed or
    // not); the removal-path rebridge prefers the first LIVE claimant.
    // After removing m_a1 the value view equals the frozen rebridge map.
    {
        DataAsset* m_a1 = core.find_asset("m_a1");
        PWB_TEST_ASSERT(m_a1 != nullptr, "find m_a1");
        core.remove_asset(m_a1);
        domain::Json rebridge = build_snapshot(core.document())["legacy"];
        expect_json("maps_rebridge", rebridge, o("maps_rebridge"));
    }
}

// ---- G. _save / revision CAS / _BatchSave / mutation_serial -------------------

PWB_CASE(save_channel) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("sv1");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "sv1 open");
    CatalogServiceCore core = std::move(opened.value());
    const fs::path src = g_root / "sv1" / "in.dat";
    { std::ofstream out(src, std::ios::binary); out << "save-core"; }
    DataVersion version = setup_register_result(
        core, p, "Serial Asset", "seismic", "sgy", domain::Json::object(),
        src, domain::DataStage::Raw);
    const std::string target_id = version.asset_id.str();
    const std::uint64_t serial0 = core.mutation_serial();
    const int rev0 = core.document_revision();
    SaveHook real = core_save_hook(core);

    // Failed non-batch save: revision rolls back, serial does NOT, memory
    // keeps the change; update_asset_metadata restores its own snapshot.
    // Python injected the failure by monkeypatching _index.apply_changes;
    // the C++ seam is the SaveHook itself ("boom" preserved verbatim).
    bool fail_next = true;
    SaveHook failing = [&](const DirtySet&) {
        if (fail_next) {
            return domain::DataError(domain::ErrorCode::Unknown, "boom");
        }
        return domain::DataError(domain::ErrorCode::Ok, "");
    };
    domain::Json patch = domain::Json::object();
    patch["region"] = "北东";
    auto failed = update_asset_metadata(core.document(), failing,
                                        domain::AssetId(target_id), patch,
                                        kNow);
    PWB_TEST_ASSERT(!failed.is_ok(), "failing hook propagates");
    core.invalidate_maps();
    domain::Json out = domain::Json::object();
    out["error"] = failed.error().message;
    out["revision_rolled_back"] = core.document_revision() == rev0;
    // mutation_serial advances FIRST and never rolls back. The injected
    // hook bypassed the core, so pin the contract through the REAL core
    // channel: one genuinely failing save still advanced the serial and
    // rolled the revision back.
    bool serial_advanced = core.mutation_serial() > serial0;
    if (!serial_advanced) {
        raw_exec(sqlite_of(p),
                 "UPDATE sync_state SET value = '999' WHERE key ="
                 " 'catalog_revision'");
        domain::DataError drifted = core.save();
        PWB_TEST_ASSERT(is_stale_write(drifted),
                        "drifted save is stale-write");
        serial_advanced = core.mutation_serial() > serial0;
        PWB_TEST_ASSERT(core.document_revision() == rev0,
                        "revision rolled back after failed save");
        raw_exec(sqlite_of(p),
                 "UPDATE sync_state SET value = '" + std::to_string(rev0) +
                     "' WHERE key = 'catalog_revision'");
    }
    out["serial_advanced"] = serial_advanced;
    out["method_rolls_back_metadata"] =
        !core.document().find_asset(domain::AssetId(target_id))
             ->metadata.contains("region");
    out["store_row_unchanged"] =
        !get_asset_model(core.repository().writable_database(), target_id)
             ->metadata.contains("region");
    fail_next = false;
    {
        auto ok = update_asset_metadata(core.document(), real,
                                        domain::AssetId(target_id), patch,
                                        kNow);
        PWB_TEST_ASSERT(ok.is_ok(), "later save: " + ok.error().message);
        core.invalidate_maps();
    }
    out["later_save_persists"] =
        get_asset_model(core.repository().writable_database(), target_id)
            ->metadata.value("region", "") == "北东";
    expect_json("save_failure_semantics", out, o("save_failure_semantics"));
    keep_actual("save_failure_semantics", out);

    // Service-level stale pre-check (#411): the store moved past our
    // baseline → Chinese message, revision unchanged, serial advanced.
    const int before_rev = core.document_revision();
    const std::uint64_t before_serial = core.mutation_serial();
    raw_exec(sqlite_of(p),
             "UPDATE sync_state SET value = '999' WHERE key ="
             " 'catalog_revision'");
    {
        domain::Json patch2 = domain::Json::object();
        patch2["creator"] = "k";
        auto res2 = update_asset_metadata(core.document(), real,
                                          domain::AssetId(target_id), patch2,
                                          kNow);
        PWB_TEST_ASSERT(!res2.is_ok(), "stale precheck must fail");
        core.invalidate_maps();
        domain::Json out2 = domain::Json::object();
        out2["type"] = error_type_text(res2.error());
        out2["error"] = res2.error().message;
        out2["revision_unchanged"] = core.document_revision() == before_rev;
        out2["serial_advanced"] =
            core.mutation_serial() == before_serial + 1;
        expect_json("flush_stale_precheck", out2, o("flush_stale_precheck"));
        keep_actual("flush_stale_precheck", out2);
    }
}

PWB_CASE(batch_save) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("sv2");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "sv2 open");
    CatalogServiceCore core = std::move(opened.value());
    const fs::path src = g_root / "sv2" / "in.dat";
    { std::ofstream out(src, std::ios::binary); out << "batch"; }
    DataVersion version = setup_register_result(
        core, p, "Batch Asset", "seismic", "sgy", domain::Json::object(),
        src, domain::DataStage::Raw);
    const std::string target_id = version.asset_id.str();
    const std::uint64_t serial0 = core.mutation_serial();
    const int rev0 = core.document_revision();
    SaveHook real = core_save_hook(core);
    auto update_meta = [&](const domain::Json& patch) {
        return update_asset_metadata(core.document(), real,
                                     domain::AssetId(target_id), patch, kNow);
    };

    // Timing: serial advances inside the batch, nothing lands until the
    // OUTERMOST exit, exactly one revision bump.
    {
        domain::Json snapshot = domain::Json::object();
        domain::Json patch1 = domain::Json::object();
        patch1["region"] = "盆地";
        domain::Json patch2 = domain::Json::object();
        patch2["creator"] = "ge";
        domain::DataError batch_error = core.batch([&] {
            PWB_TEST_ASSERT(update_meta(patch1).is_ok(), "batch update 1");
            PWB_TEST_ASSERT(update_meta(patch2).is_ok(), "batch update 2");
            // The generator records the in-batch flags after BOTH updates.
            snapshot["serial_in_batch"] =
                static_cast<std::uint64_t>(core.mutation_serial() - serial0);
            snapshot["revision_frozen"] = core.document_revision() == rev0;
            snapshot["store_revision_frozen"] =
                core.index_revision().has_value() &&
                *core.index_revision() == rev0;
            snapshot["store_row_not_landed"] =
                !get_asset_model(core.repository().writable_database(),
                                 target_id)
                     ->metadata.contains("region");
            return domain::DataError(domain::ErrorCode::Ok, "");
        });
        PWB_TEST_ASSERT(batch_error.code == domain::ErrorCode::Ok,
                        "batch: " + batch_error.message);
        core.invalidate_maps();
        snapshot["revision_after_exit"] = core.document_revision();
        snapshot["store_revision_after_exit"] =
            core.index_revision().has_value()
                ? domain::Json(static_cast<long long>(*core.index_revision()))
                : domain::Json(nullptr);
        snapshot["store_row_landed"] =
            get_asset_model(core.repository().writable_database(), target_id)
                ->metadata.value("region", "") == "盆地";
        snapshot["serial_after_exit"] =
            static_cast<std::uint64_t>(core.mutation_serial() - serial0);
        expect_json("batch_save_timing", snapshot, o("batch_save_timing"));
        keep_actual("batch_save_timing", snapshot);
    }
    // Body failure: nothing persists; the document reloads from the store;
    // the serial keeps its advances.
    {
        const std::uint64_t serial1 = core.mutation_serial();
        const int rev_after_batch = core.document_revision();
        domain::Json body = domain::Json::object();
        domain::Json patch = domain::Json::object();
        patch["region"] = "改";
        domain::DataError error = core.batch([&] {
            PWB_TEST_ASSERT(update_meta(patch).is_ok(), "body update");
            return domain::DataError(domain::ErrorCode::Unknown, "body boom");
        });
        body["raised"] = error.code != domain::ErrorCode::Ok;
        PWB_TEST_ASSERT_EQ(error.message, "body boom", "body error text");
        core.invalidate_maps();
        body["memory_reloaded"] =
            core.document().find_asset(domain::AssetId(target_id))
                ->metadata.value("region", "") == "盆地";
        body["store_untouched"] =
            get_asset_model(core.repository().writable_database(), target_id)
                ->metadata.value("region", "") == "盆地";
        body["serial_kept"] = core.mutation_serial() == serial1 + 1;
        body["revision_restored"] =
            core.document_revision() == rev_after_batch;
        expect_json("batch_save_body_failure", body,
                    o("batch_save_body_failure"));
    }
    // Nested batches: only the OUTERMOST exit flushes (observed inside the
    // nesting, where the inner exit runs).
    {
        const int rev2 = core.document_revision();
        bool inner_froze = false;
        domain::Json patch = domain::Json::object();
        patch["creator"] = "nested";
        domain::DataError error = core.batch([&] {
            return core.batch([&] {
                PWB_TEST_ASSERT(update_meta(patch).is_ok(), "nested update");
                inner_froze = core.document_revision() == rev2 &&
                             core.index_revision().has_value() &&
                             *core.index_revision() == rev2;
                return domain::DataError(domain::ErrorCode::Ok, "");
            });
        });
        PWB_TEST_ASSERT(error.code == domain::ErrorCode::Ok,
                        "nested batch: " + error.message);
        core.invalidate_maps();
        domain::Json out = domain::Json::object();
        out["inner_exit_no_flush"] = inner_froze;
        out["outer_flushed_once"] = core.document_revision() == rev2 + 1;
        out["store_matches"] =
            core.index_revision().has_value() &&
            static_cast<long long>(core.document_revision()) ==
                *core.index_revision();
        out["store_row_landed"] =
            get_asset_model(core.repository().writable_database(), target_id)
                ->metadata.value("creator", "") == "nested";
        expect_json("batch_save_nested", out, o("batch_save_nested"));
    }
}

// ---- H. working-copy lifecycle -------------------------------------------------

PWB_CASE(working_copy_lifecycle) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("wc1");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "wc1 open");
    CatalogServiceCore core = std::move(opened.value());
    const fs::path src = g_root / "wc1" / "source.dat";
    { std::ofstream out(src, std::ios::binary); out << "working-copy-payload"; }
    const std::string content = "working-copy-payload";
    DataVersion version = setup_register_result(
        core, p, "WC Asset", "seismic", "sgy", domain::Json::object(), src,
        domain::DataStage::Raw);
    std::set<std::string> pending;
    auto context = [&] {
        return WorkingCopyContext{p, &core.repository(), &core.document(),
                                  &pending};
    };
    core.invalidate_maps();

    auto create_wc = [&](bool allow_replace) {
        WorkingCopyContext ctx = context();
        auto result = create_working_copy(ctx, version.id, allow_replace);
        core.invalidate_maps();
        return result;
    };
    auto dirty_hint_of = [&](const fs::path& path) {
        WorkingCopyContext ctx = context();
        auto state = working_copy_state(ctx, path);
        return state.has_value() && state->dirty_hint;
    };

    auto first = create_wc(false);
    PWB_TEST_ASSERT(first.is_ok(), "create wc: " + first.error().message);
    const fs::path wc_path = first.value();
    const auto mtime0 = mtime_ns_of(wc_path);
    auto reused = create_wc(false);
    const bool reuse_same = reused.is_ok() && reused.value() == wc_path &&
                            mtime_ns_of(wc_path) == mtime0;
    const std::string rel =
        fs::relative(wc_path, g_root / "wc1").generic_string();
    auto row0 = core.repository().get_working_copy_by_path(rel);
    auto replaced = create_wc(true);
    PWB_TEST_ASSERT(replaced.is_ok(), "replace wc");
    {
        domain::Json out = domain::Json::object();
        out["path"] = wc_path.string();
        out["registered"] = row0.has_value();
        out["source_version"] =
            row0.has_value() ? domain::Json(row0->source_version_id.str())
                             : domain::Json(nullptr);
        out["display_name"] = row0.has_value()
                                  ? domain::Json(row0->display_name)
                                  : domain::Json(nullptr);
        out["state"] = row0.has_value() ? domain::Json(row0->state)
                                        : domain::Json(nullptr);
        out["reuse_same_path_untouched"] = reuse_same;
        out["rows_after_replace"] = wc_rows_json(core.repository());
        out["replaced_bytes_intact"] = [&] {
            std::ifstream in(replaced.value(), std::ios::binary);
            std::string bytes((std::istreambuf_iterator<char>(in)),
                              std::istreambuf_iterator<char>());
            return bytes == content;
        }();
        auto new_row = core.repository().get_working_copy_by_path(rel);
        domain::Json expected = expected_json(
            "wc_create_reuse_replace",
            {{"ver_g16", version.id.str()},
             {"wc-g17",
              new_row.has_value() ? new_row->working_id : std::string()}});
        expect_json("wc_create_reuse_replace", out, expected);
    }

    // dirty_hint matrix: mtime drift flags, restore clears, committing
    // never flags.
    {
        const bool mtime_drift = [&] {
            struct ::stat st {};
            PWB_TEST_ASSERT(::stat(wc_path.c_str(), &st) == 0, "stat wc");
            struct timespec drift_times[2] = {
                {st.st_atim.tv_sec, st.st_atim.tv_nsec},
                {st.st_mtim.tv_sec + 5, st.st_mtim.tv_nsec}};
            ::utimensat(AT_FDCWD, wc_path.c_str(), drift_times, 0);
            const bool drifted = dirty_hint_of(wc_path);
            struct timespec back_times[2] = {
                {st.st_atim.tv_sec, st.st_atim.tv_nsec},
                {st.st_mtim.tv_sec, st.st_mtim.tv_nsec}};
            ::utimensat(AT_FDCWD, wc_path.c_str(), back_times, 0);
            return drifted;
        }();
        const bool restored = !dirty_hint_of(wc_path);
        raw_exec(sqlite_of(p),
                 "UPDATE working_copies SET state = 'committing'");
        const bool committing_hint = dirty_hint_of(wc_path);
        raw_exec(sqlite_of(p),
                 "UPDATE working_copies SET state = 'checked_out'");
        domain::Json out = domain::Json::object();
        out["mtime_drift"] = mtime_drift;
        out["restored"] = restored;
        out["committing_never_flags"] = committing_hint;
        expect_json("wc_dirty_hint", out, o("wc_dirty_hint"));
    }

    // Discard guard: committing refuses verbatim; a healthy row discards
    // file+row; an unregistered file discards the file; nothing → false.
    {
        raw_exec(sqlite_of(p),
                 "UPDATE working_copies SET state = 'committing'");
        WorkingCopyContext ctx = context();
        auto refused = discard_working_copy(ctx, wc_path);
        core.invalidate_maps();
        raw_exec(sqlite_of(p),
                 "UPDATE working_copies SET state = 'checked_out'");
        WorkingCopyContext ctx2 = context();
        auto discarded = discard_working_copy(ctx2, wc_path);
        core.invalidate_maps();
        const fs::path stray = g_root / "wc1" / "stray.dat";
        { std::ofstream out_file(stray, std::ios::binary); out_file << "stray"; }
        WorkingCopyContext ctx3 = context();
        auto unregistered = discard_working_copy(ctx3, stray);
        core.invalidate_maps();
        WorkingCopyContext ctx4 = context();
        auto nowhere =
            discard_working_copy(ctx4, g_root / "wc1" / "nothing.dat");
        core.invalidate_maps();
        domain::Json out = domain::Json::object();
        PWB_TEST_ASSERT(!refused.is_ok(), "committing discard refused");
        out["committing_error"] = refused.error().message;
        out["type"] = error_type_text(refused.error());
        out["normal_discard"] = discarded.is_ok() && discarded.value();
        std::error_code ec;
        out["file_gone"] = !fs::exists(wc_path, ec);
        out["rows_after"] = wc_rows_json(core.repository());
        out["unregistered_file"] =
            unregistered.is_ok() && unregistered.value();
        out["stray_gone"] = !fs::exists(stray, ec);
        out["nothing"] = nowhere.is_ok() && nowhere.value();
        expect_json("wc_discard_guard", out, o("wc_discard_guard"));
        keep_actual("wc_discard_guard", out);
    }
}

PWB_CASE(wc_commit) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("wc2");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "wc2 open");
    CatalogServiceCore core = std::move(opened.value());
    const fs::path src = g_root / "wc2" / "source.dat";
    const std::string content = "working-copy-payload";
    { std::ofstream out(src, std::ios::binary); out << content; }
    DataVersion version = setup_register_result(
        core, p, "WC Asset", "seismic", "sgy", domain::Json::object(), src,
        domain::DataStage::Raw);
    std::set<std::string> pending;
    auto context = [&] {
        return WorkingCopyContext{p, &core.repository(), &core.document(),
                                  &pending};
    };
    {
        WorkingCopyContext ctx = context();
        auto created = create_working_copy(ctx, version.id, false);
        core.invalidate_maps();
        PWB_TEST_ASSERT(created.is_ok(), "wc2 create");
        const fs::path wc_path = created.value();
        {
            std::ofstream out(wc_path, std::ios::binary | std::ios::app);
            out << "-edited";
        }
        const std::string edited = content + "-edited";
        const std::size_t assets_before = core.document().assets.size();
        CommitWorkingCopyRequest request;
        request.asset_id = std::nullopt;
        request.name = "Committed Asset";
        request.stage = domain::DataStage::Derived;
        WorkingCopyContext ctx2 = context();
        auto committed = commit_working_copy(ctx2, wc_path, request);
        core.invalidate_maps();
        PWB_TEST_ASSERT(committed.is_ok(),
                        "wc2 commit: " + committed.error().message);
        const DataVersion landed = committed.value();
        const DataAsset* new_asset =
            core.document().find_asset(landed.asset_id);
        domain::Json out = domain::Json::object();
        out["new_version_number"] = landed.version_number;
        domain::Json parents = domain::Json::array();
        for (const auto& parent : landed.parent_version_ids) {
            parents.push_back(parent.str());
        }
        out["parents"] = std::move(parents);
        out["sha_matches_edit"] =
            landed.sha256.has_value() && *landed.sha256 == sha_bytes(edited);
        out["asset_name"] = new_asset->name;
        std::error_code ec;
        out["working_file_consumed"] = !fs::exists(wc_path, ec);
        out["rows_after"] = wc_rows_json(core.repository());
        out["assets_added"] =
            static_cast<int>(core.document().assets.size() - assets_before);
        out["store_versions"] =
            count_rows(core.repository().writable_database(), "versions");
        out["path"] = landed.path;
        domain::Json expected =
            expected_json("wc_commit_success",
                          {{"ver_g13", version.id.str()},
                           {"asset_g14", landed.asset_id.str()},
                           {"ver_g15", landed.id.str()}});
        expect_json("wc_commit_success", out, expected);
    }
    // Failure: no phantom — payload returns to the working path, the row
    // reverts to dirty, nothing lands in the store. Python injected the
    // save failure by monkeypatching apply_changes ("commit boom"); the
    // C++ commit persists through the repository transaction, so the
    // replay injects a REAL store failure (repository handle closed →
    // the transaction cannot begin) — the same rollback contract with an
    // honest error text (the "commit boom" string is injection-mechanism
    // noise, not a frozen product string; the frozen row/store/rollback
    // values are all replayed).
    {
        WorkingCopyContext ctx = context();
        auto created = create_working_copy(ctx, version.id, false);
        core.invalidate_maps();
        PWB_TEST_ASSERT(created.is_ok(), "wc2 create 2");
        const fs::path wc2_path = created.value();
        auto count_versions = [&] {
            auto db = Database::open(sqlite_of(p),
                                     SqliteOpenMode::ReadWrite);
            PWB_TEST_ASSERT(db.is_ok(), "count open");
            return count_rows(db.value(), "versions");
        };
        const int versions_before = count_versions();
        const std::size_t assets_before2 = core.document().assets.size();
        // Inject a REAL failure: make the artifacts tree unwritable so the
        // payload placement errors out (a closed repository handle is NOT
        // a usable injection — repository write statements silently no-op
        // on failed prepares, which would fake a success). Same rollback
        // contract as Python's apply_changes monkeypatch.
        // Target the DERIVED stage directory itself (created by the first
        // commit) — chmod on the artifacts root alone leaves the already
        // -existing stage subdirectories writable.
        const fs::path artifacts_dir =
            g_root / "wc2" / "wc2.artifacts" / "derived";
        std::error_code perm_ec;
        fs::permissions(artifacts_dir,
                        fs::perms::owner_read | fs::perms::owner_exec |
                            fs::perms::group_read | fs::perms::group_exec |
                            fs::perms::others_read | fs::perms::others_exec,
                        fs::perm_options::replace, perm_ec);
        CommitWorkingCopyRequest request;
        request.asset_id = std::nullopt;
        request.name = "Failed Asset";
        request.stage = domain::DataStage::Derived;
        {
            WorkingCopyContext ctx2 = context();
            auto failed = commit_working_copy(ctx2, wc2_path, request);
            core.invalidate_maps();
            fs::permissions(artifacts_dir,
                            fs::perms::owner_all | fs::perms::group_all |
                                fs::perms::others_read |
                                fs::perms::others_exec,
                            fs::perm_options::replace, perm_ec);
            PWB_TEST_ASSERT(!failed.is_ok(), "commit must fail");
            domain::Json out = domain::Json::object();
            std::ifstream in(wc2_path, std::ios::binary);
            std::string bytes((std::istreambuf_iterator<char>(in)),
                              std::istreambuf_iterator<char>());
            out["payload_restored"] = in.good() && bytes == content;
            const std::string rel =
                fs::relative(wc2_path, g_root / "wc2").generic_string();
            auto row = core.repository().get_working_copy_by_path(rel);
            out["row_state"] = row.has_value() ? domain::Json(row->state)
                                               : domain::Json(nullptr);
            out["versions_unchanged"] = count_versions() == versions_before;
            out["assets_unchanged"] =
                core.document().assets.size() == assets_before2;
            out["store_versions"] = count_versions();
            domain::Json expected = o("wc_commit_failure_rollback");
            expected.erase("error");  // injection-mechanism text
            expect_json("wc_commit_failure_rollback", out, expected);
            PWB_TEST_ASSERT(out["payload_restored"].get<bool>() &&
                                out["row_state"] == "dirty" &&
                                out["versions_unchanged"].get<bool>(),
                            "commit rollback semantics");
        }
    }
}

PWB_CASE(wc_recover) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("wc3");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "wc3 open");
    CatalogServiceCore core = std::move(opened.value());
    const fs::path project_dir = g_root / "wc3";
    const fs::path working = project_dir / "wc3.artifacts" / "working";
    std::error_code ec;
    fs::create_directories(working, ec);
    const std::map<std::string, std::pair<char, std::string>> payloads = {
        {"ver_kept1", {'a', "a"}}, {"ver_kept2", {'b', "b"}},
        {"ver_drop", {'c', "c"}},  {"ver_back", {'d', "d"}},
    };
    for (const auto& [vid, entry] : payloads) {
        fs::create_directories(working / vid, ec);
        std::ofstream out(working / vid /
                              (std::string(1, entry.first) + ".dat"),
                          std::ios::binary);
        out << entry.second;
    }
    fs::create_directories(working / "ver_gone", ec);  // file never exists

    CatalogRepository& repo = core.repository();
    auto register_row = [&](const std::string& vid, char letter) {
        auto row = repo.register_working_copy(
            domain::VersionId(vid),
            "wc3.artifacts/working/" + vid + "/" + letter + ".dat",
            std::string(1, letter) + ".dat", std::nullopt, std::nullopt);
        PWB_TEST_ASSERT(row.is_ok(), std::string("register ") + vid);
        return row.value();
    };
    const std::string wid1 = register_row("ver_kept1", 'a');
    const std::string wid2 = register_row("ver_kept2", 'b');
    const std::string widd = register_row("ver_drop", 'c');
    const std::string widb = register_row("ver_back", 'd');
    const std::string widg = register_row("ver_gone", 'm');
    // Controlled SQL: fixed created_at ordering + crash states.
    const std::vector<std::pair<std::string, const char*>> states = {
        {wid1, "checked_out"}, {wid2, "dirty"},
        {widd, "committing"},  {widb, "committing"},
        {widg, "checked_out"},
    };
    for (std::size_t i = 0; i < states.size(); ++i) {
        const std::string stamp =
            std::string("2024-06-01T00:00:0") + std::to_string(i);
        raw_exec(sqlite_of(p),
                 "UPDATE working_copies SET state = '" +
                     std::string(states[i].second) + "', created_at = '" +
                     stamp + "', updated_at = '" + stamp +
                     "' WHERE working_id = '" + states[i].first + "'");
    }
    // A committed version whose source_uri is the ver_drop working path.
    CatalogDocument doc;
    doc.assets.push_back(mk_asset("asset_rec", "Recover"));
    {
        DataVersion v = mk_ver("ver_drop", "asset_rec", 1);
        v.managed = false;
        v.path = "wc3.artifacts/working/ver_drop/c.dat";
        v.source_uri =
            fs::weakly_canonical(working / "ver_drop" / "c.dat").string();
        doc.versions.push_back(std::move(v));
    }
    core.document() = doc;
    core.invalidate_maps();
    std::set<std::string> pending;
    {
        WorkingCopyContext context{p, &core.repository(), &core.document(),
                                   &pending};
        WorkingCopyRecovery recovery = recover_working_copies(context);
        core.invalidate_maps();
        domain::Json out = domain::Json::object();
        out["final_rows"] = wc_rows_json(core.repository());
        domain::Json paths = domain::Json::array();
        domain::Json states_json = domain::Json::array();
        for (const auto& survivor : recovery.surviving) {
            paths.push_back(survivor.path.string());
            states_json.push_back(std::string(to_string(survivor.state)));
        }
        out["surviving_paths"] = std::move(paths);
        out["surviving_states"] = std::move(states_json);
        out["kept1_exists"] = fs::exists(working / "ver_kept1" / "a.dat", ec);
        out["back_reverted_file_intact"] =
            fs::exists(working / "ver_back" / "d.dat", ec);
        domain::Json expected = expected_json(
            "wc_recover_matrix",
            {{"wc-g18", wid1}, {"wc-g19", wid2}, {"wc-g20", widb}});
        expect_json("wc_recover_matrix", out, expected);
    }
}

// ---- I. trash / restore / purge -------------------------------------------------

PWB_CASE(trash_lifecycle) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("tr1");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "tr1 open");
    CatalogServiceCore core = std::move(opened.value());
    const fs::path src = g_root / "tr1" / "source.dat";
    { std::ofstream out(src, std::ios::binary); out << "trash-payload-v1"; }
    DataVersion v1 = setup_register_result(
        core, p, "WC Asset", "seismic", "sgy", domain::Json::object(), src,
        domain::DataStage::Raw);
    const fs::path src2 = g_root / "tr1" / "v2.dat";
    { std::ofstream out(src2, std::ios::binary); out << "trash-payload-v2"; }
    DataVersion v2 = setup_register_version(
        core, p, v1.asset_id, src2, domain::DataStage::Derived);
    const std::uint64_t serial0 = core.mutation_serial();
    const std::string old_path =
        core.document().find_version(v2.id)->path;
    SaveHook real = core_save_hook(core);
    {
        DocumentIndex index(core.document());
        domain::DataError error = trash_version(
            &core.document(), index, p, v2.id.str(), "cleanup", real, kNow);
        core.invalidate_maps();
        PWB_TEST_ASSERT(error.code == domain::ErrorCode::Ok,
                        "trash v2: " + error.message);
    }
    {
        const DataVersion* trashed = core.document().find_version(v2.id);
        domain::Json out = domain::Json::object();
        out["trashed_flag"] = trashed->trashed;
        out["trashed_at"] = trashed->trashed_at.value_or("");
        out["trash_meta"] = trashed->metadata["trash"];
        out["new_path"] = trashed->path;
        out["current_reallocated_to"] =
            core.document().find_asset(trashed->asset_id)
                ->current_version_id->str();
        out["saves_used"] =
            static_cast<std::uint64_t>(core.mutation_serial() - serial0);
        std::error_code ec;
        out["managed_original_gone"] =
            !(fs::exists(g_root / "tr1" / fs::path(old_path), ec));
        out["import_source_kept"] = fs::exists(src2, ec);
        out["trash_file_exists"] =
            fs::exists(g_root / "tr1" / fs::path(trashed->path), ec);
        DocumentIndex index(core.document());
        domain::DataError again = trash_version(
            &core.document(), index, p, v2.id.str(), "again", real, kNow);
        core.invalidate_maps();
        out["idempotent_second_saves"] =
            again.code == domain::ErrorCode::Ok &&
            core.mutation_serial() == serial0 + 2;
        domain::Json expected = expected_json(
            "trash_tombstone_shape",
            {{"ver_g10", v1.id.str()},
             {"ver_g11", v2.id.str()},
             {"asset_g12", v2.asset_id.str()}});
        expect_json("trash_tombstone_shape", out, expected);
    }

    // External version: metadata-only, external file untouched.
    const fs::path p2 = proj("tr2");
    auto opened2 = open_catalog(p2, options);
    PWB_TEST_ASSERT(opened2.is_ok(), "tr2 open");
    CatalogServiceCore core2 = std::move(opened2.value());
    const fs::path ext = g_root / "tr2" / "external.las";
    {
        std::ofstream out_file(ext, std::ios::binary);
        out_file << "external-bytes";
    }
    const std::uint64_t serial2 = core2.mutation_serial();  // pre-setup
    {
        CatalogDocument doc;
        doc.assets.push_back(mk_asset("asset_ext", "External"));
        DataVersion v = mk_ver("ver_ext", "asset_ext", 1);
        v.managed = false;
        v.path = ext.string();
        v.sha256 = sha_bytes("external-bytes");
        doc.versions.push_back(std::move(v));
        core2.document() = doc;
        core2.invalidate_maps();
        DirtySet dirty;
        dirty.mark_asset("asset_ext");
        dirty.mark_version("ver_ext");
        PWB_TEST_ASSERT(core2.save(dirty).code == domain::ErrorCode::Ok,
                        "tr2 setup save");
    }
    const auto ext_mtime0 = mtime_ns_of(ext);
    SaveHook real2 = core_save_hook(core2);
    {
        DocumentIndex index(core2.document());
        domain::DataError error = trash_version(
            &core2.document(), index, p2, "ver_ext", "ext", real2, kNow);
        core2.invalidate_maps();
        PWB_TEST_ASSERT(error.code == domain::ErrorCode::Ok,
                        "trash ext: " + error.message);
    }
    {
        const DataVersion* tr_ext =
            core2.document().find_version(vid("ver_ext"));
        domain::Json out2 = domain::Json::object();
        out2["trashed"] = tr_ext->trashed;
        out2["path_unchanged"] = tr_ext->path == ext.string();
        out2["file_untouched"] =
            fs::exists(ext) && mtime_ns_of(ext) == ext_mtime0;
        out2["saves_used"] =
            static_cast<std::uint64_t>(core2.mutation_serial() - serial2 - 1);
        expect_json("trash_external_metadata_only", out2,
                    o("trash_external_metadata_only"));
    }

    // Blob-backed: path unchanged (refcount semantics).
    const fs::path blob_src = g_root / "tr2" / "blobsrc.bin";
    {
        std::ofstream out_file(blob_src, std::ios::binary);
        out_file << "shared-blob";
    }
    auto placement = place_blob(p2, blob_src);
    PWB_TEST_ASSERT(placement.is_ok(), "place blob");
    const std::string digest = placement.value().digest;
    const fs::path blob = blob_path_for(p2, digest);
    const std::string blob_rel =
        fs::relative(blob, g_root / "tr2").generic_string();
    {
        CatalogDocument doc2;
        doc2.assets.push_back(mk_asset("asset_blob", "Blob"));
        DataVersion v = mk_ver("ver_blob", "asset_blob", 1);
        v.managed = true;
        v.path = blob_rel;
        v.sha256 = digest;
        doc2.versions.push_back(std::move(v));
        core2.document() = doc2;
        core2.invalidate_maps();
        DirtySet dirty;
        dirty.mark_asset("asset_blob");
        dirty.mark_version("ver_blob");
        PWB_TEST_ASSERT(core2.save(dirty).code == domain::ErrorCode::Ok,
                        "tr2 blob save");
    }
    {
        DocumentIndex index(core2.document());
        domain::DataError error = trash_version(
            &core2.document(), index, p2, "ver_blob", "blob", real2, kNow);
        core2.invalidate_maps();
        PWB_TEST_ASSERT(error.code == domain::ErrorCode::Ok,
                        "trash blob: " + error.message);
        const DataVersion* tr_blob =
            core2.document().find_version(vid("ver_blob"));
        domain::Json out2 = domain::Json::object();
        out2["path_unchanged"] = tr_blob->path == blob_rel;
        std::error_code ec;
        out2["blob_exists"] = fs::exists(blob, ec);
        out2["meta"] = tr_blob->metadata["trash"];
        expect_json("trash_blob_backed", out2, o("trash_blob_backed"));
    }
}

PWB_CASE(restore_windows) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("tr3");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "tr3 open");
    CatalogServiceCore core = std::move(opened.value());
    const fs::path src = g_root / "tr3" / "source.dat";
    { std::ofstream out(src, std::ios::binary); out << "restore-payload"; }
    DataVersion v1 = setup_register_result(
        core, p, "WC Asset", "seismic", "sgy", domain::Json::object(), src,
        domain::DataStage::Raw);
    SaveHook real = core_save_hook(core);

    // The generator's partial-step drives (touch #7): _tombstone_version +
    // _save without the payload move = W1; then restore_version.
    auto tombstone_in_place = [&](CatalogServiceCore& svc,
                                  const std::string& version_id,
                                  const std::string& reason) {
        CatalogDocument& doc = svc.document();
        DataVersion* version =
            doc.find_version_mut(domain::VersionId(version_id));
        PWB_TEST_ASSERT(version != nullptr, "tombstone target");
        const std::string original_path = version->path;
        version->trashed = true;
        version->trashed_at = kNow;
        domain::Json meta = domain::Json::object();
        meta["reason"] = reason;
        meta["original_stage"] =
            std::string(domain::to_string(version->stage));
        meta["original_path"] = original_path;
        meta["trashed_at"] = kNow;
        version->metadata["trash"] = std::move(meta);
        DataAsset* asset = doc.find_asset_mut(version->asset_id);
        DocumentIndex index(doc);
        if (auto candidate =
                active_current_candidate(index, *asset, version_id)) {
            asset->current_version_id = domain::VersionId(*candidate);
        } else {
            asset->current_version_id = std::nullopt;
        }
        svc.invalidate_maps();
        DirtySet dirty;
        dirty.mark_asset(version->asset_id.str());
        dirty.mark_version(version_id);
        domain::DataError error = svc.save(dirty);
        PWB_TEST_ASSERT(error.code == domain::ErrorCode::Ok,
                        "tombstone save: " + error.message);
        return original_path;
    };

    // W1: payload still in place.
    {
        const std::string original_path =
            tombstone_in_place(core, v1.id.str(), "w1");
        DocumentIndex index(core.document());
        domain::DataError error =
            restore_version(&core.document(), index, p, v1.id.str(), real);
        core.invalidate_maps();
        PWB_TEST_ASSERT(error.code == domain::ErrorCode::Ok,
                        "restore W1: " + error.message);
        const DataVersion* restored = core.document().find_version(v1.id);
        domain::Json out = domain::Json::object();
        out["path"] = restored->path;
        out["equals_original"] = restored->path == original_path;
        std::error_code ec;
        out["file_restored"] =
            fs::exists(g_root / "tr3" / fs::path(original_path), ec);
        out["tombstone_cleared"] =
            !restored->metadata.contains("trash") && !restored->trashed;
        out["current_points_back"] =
            core.document().find_asset(restored->asset_id)
                ->current_version_id->str() == restored->id.str();
        domain::Json expected = expected_json(
            "restore_w1_inplace",
            {{"asset_g8", v1.asset_id.str()}, {"ver_g9", v1.id.str()}});
        expect_json("restore_w1_inplace", out, expected);
    }
    // W2: persist tombstone, move the payload, LOSE the path-update save,
    // reopen from the store, restore — the trash probe finds the payload.
    {
        const std::string original_path =
            tombstone_in_place(core, v1.id.str(), "w2");
        {
            const DataVersion* version = core.document().find_version(v1.id);
            const fs::path payload = resolve_payload_path(p, *version);
            auto moved = trash_payload(p, payload, v1.id.str());
            PWB_TEST_ASSERT(moved.is_ok(), "move payload to trash");
        }
        auto reopened = open_catalog(p, options);
        PWB_TEST_ASSERT(reopened.is_ok(), "tr3 reopen");
        CatalogServiceCore core2 = std::move(reopened.value());
        const DataVersion* reloaded = core2.document().find_version(v1.id);
        domain::Json out = domain::Json::object();
        out["store_path_stale_after_crash"] = reloaded->path == original_path;
        SaveHook real2 = core_save_hook(core2);
        DocumentIndex index(core2.document());
        domain::DataError error = restore_version(
            &core2.document(), index, p, v1.id.str(), real2);
        core2.invalidate_maps();
        PWB_TEST_ASSERT(error.code == domain::ErrorCode::Ok,
                        "restore W2: " + error.message);
        const DataVersion* restored = core2.document().find_version(v1.id);
        out["restored_path"] = restored->path;
        out["equals_original"] = restored->path == original_path;
        std::error_code ec;
        out["file_restored"] =
            fs::exists(g_root / "tr3" / fs::path(original_path), ec);
        const fs::path trash_dir =
            g_root / "tr3" / "tr3.artifacts" / "trash" / v1.id.str();
        bool trash_empty = !fs::exists(trash_dir, ec);
        if (!trash_empty) {
            trash_empty = fs::is_empty(trash_dir, ec);
        }
        out["trash_dir_empty"] = trash_empty;
        out["tombstone_cleared"] = !restored->metadata.contains("trash");
        domain::Json expected = expected_json(
            "restore_w2_probe",
            {{"asset_g8", v1.asset_id.str()}, {"ver_g9", v1.id.str()}});
        expect_json("restore_w2_probe", out, expected);
    }
}

PWB_CASE(purge_lifecycle) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("tr4");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "tr4 open");
    CatalogServiceCore core = std::move(opened.value());
    const fs::path blob_src = g_root / "tr4" / "blob.bin";
    {
        std::ofstream out(blob_src, std::ios::binary);
        out << "purge-shared-blob";
    }
    auto placement = place_blob(p, blob_src);
    PWB_TEST_ASSERT(placement.is_ok(), "place purge blob");
    const std::string digest = placement.value().digest;
    const fs::path blob = blob_path_for(p, digest);
    const std::string blob_rel =
        fs::relative(blob, g_root / "tr4").generic_string();

    CatalogDocument doc;
    {
        DataAsset b1 = mk_asset("asset_b1", "Blob One");
        DataAsset b2 = mk_asset("asset_b2", "Blob Two");
        DataAsset z = mk_asset("asset_z", "Zombie");
        DataAsset pr = mk_asset("asset_p", "Pending Protected");
        DataAsset m = mk_asset("asset_m", "Mixed");
        m.trashed = true;
        m.trashed_at = kNow;
        doc.assets = {b1, b2, z, pr, m};
    }
    {
        DataVersion pv_a = mk_ver("pv_a", "asset_b1", 1);
        pv_a.managed = true;
        pv_a.path = blob_rel;
        pv_a.sha256 = digest;
        DataVersion pv_b = mk_ver("pv_b", "asset_b2", 1);
        pv_b.managed = true;
        pv_b.path = blob_rel;
        pv_b.sha256 = digest;
        pv_b.trashed = true;
        pv_b.trashed_at = kNow;
        DataVersion pv_dead = mk_ver("pv_dead", "asset_m", 1);
        pv_dead.trashed = true;
        pv_dead.trashed_at = kNow;
        pv_dead.path = "tr4.artifacts/raw/asset_m/pv_dead/x.bin";
        DataVersion pv_live = mk_ver("pv_live", "asset_m", 2);
        doc.versions = {pv_a, pv_b, pv_dead, pv_live};
    }
    for (auto& asset : doc.assets) {
        if (asset.id.str() == "asset_m") {
            asset.current_version_id = vid("pv_live");
        }
    }
    doc.tags.push_back(mk_tag("pt1", "qc"));
    doc.asset_tags = {{"asset_z", "pt1"}, {"asset_m", "pt1"}};
    doc.version_tags = {{"pv_dead", "pt1"}};
    core.document() = doc;
    core.invalidate_maps();
    {
        DirtySet dirty;
        for (const char* id : {"asset_b1", "asset_b2", "asset_z", "asset_p",
                               "asset_m"}) {
            dirty.mark_asset(id);
        }
        for (const char* id : {"pv_a", "pv_b", "pv_dead", "pv_live"}) {
            dirty.mark_version(id);
        }
        dirty.mark_tag("pt1");
        dirty.mark_asset_tags("asset_z");
        dirty.mark_asset_tags("asset_m");
        dirty.mark_version_tags("pv_dead");
        PWB_TEST_ASSERT(core.save(dirty).code == domain::ErrorCode::Ok,
                        "tr4 setup save");
    }
    std::set<std::string> pending;
    pending.insert("asset_p");  // generator touch #8
    SaveHook real = core_save_hook(core);

    auto asset_alive = [&](const std::string& id) {
        for (const auto& a : core.document().assets) {
            if (a.id.str() == id) return true;
        }
        return false;
    };
    auto version_alive = [&](const std::string& id) {
        for (const auto& v : core.document().versions) {
            if (v.id.str() == id) return true;
        }
        return false;
    };

    domain::Json out = domain::Json::object();
    TrashPurgeResult first_result;
    {
        DocumentIndex index(core.document());
        domain::DataError error = purge_trashed(
            &core.document(), index, p, real, pending, &first_result);
        core.invalidate_maps();
        PWB_TEST_ASSERT(error.code == domain::ErrorCode::Ok,
                        "purge 1: " + error.message);
    }
    {
        domain::Json first = domain::Json::object();
        first["removed"] = static_cast<int>(first_result.removed);
        std::error_code ec;
        first["blob_survives_shared"] = fs::exists(blob, ec);
        first["asset_b1_alive"] = asset_alive("asset_b1");
        first["zombie_gone"] = !asset_alive("asset_b2");
        first["pending_protected"] = asset_alive("asset_p");
        bool mixed_kept = false;
        for (const auto& a : core.document().assets) {
            if (a.id.str() == "asset_m") mixed_kept = !a.trashed;
        }
        first["mixed_untrashed_kept"] = mixed_kept;
        first["dead_version_gone"] = !version_alive("pv_dead");
        first["live_version_kept"] = version_alive("pv_live");
        bool zombie_tags_removed = true;
        for (const auto& [asset_id, tag_id] : core.document().asset_tags) {
            if (asset_id == "asset_z") zombie_tags_removed = false;
        }
        first["asset_tags_zombie_removed"] = zombie_tags_removed;
        out["first"] = std::move(first);
    }
    // Last blob reference: trash the survivor, purge again → blob unlinked.
    {
        DocumentIndex index(core.document());
        domain::DataError error = trash_version(
            &core.document(), index, p, "pv_a", "last", real, kNow);
        core.invalidate_maps();
        PWB_TEST_ASSERT(error.code == domain::ErrorCode::Ok,
                        "trash pv_a: " + error.message);
    }
    TrashPurgeResult second_result;
    {
        DocumentIndex index(core.document());
        domain::DataError error = purge_trashed(
            &core.document(), index, p, real, pending, &second_result);
        core.invalidate_maps();
        PWB_TEST_ASSERT(error.code == domain::ErrorCode::Ok,
                        "purge 2: " + error.message);
    }
    out["second_removed"] = static_cast<int>(second_result.removed);
    std::error_code ec;
    out["blob_unlinked_at_last_ref"] = !fs::exists(blob, ec);
    out["zombie_not_counted"] = static_cast<int>(first_result.removed) == 3;
    expect_json("purge_refcount_blob", out, o("purge_refcount_blob"));

    // Save-failure rollback: everything returns, payloads stay restorable.
    const fs::path p2 = proj("tr5");
    auto opened2 = open_catalog(p2, options);
    PWB_TEST_ASSERT(opened2.is_ok(), "tr5 open");
    CatalogServiceCore core2 = std::move(opened2.value());
    {
        CatalogDocument doc2;
        doc2.assets.push_back(mk_asset("asset_rb", "Rollback"));
        DataVersion dead = mk_ver("rv_dead", "asset_rb", 1);
        dead.trashed = true;
        dead.trashed_at = kNow;
        dead.path = "tr5.artifacts/raw/asset_rb/rv_dead/x.bin";
        doc2.versions.push_back(std::move(dead));
        doc2.tags.push_back(mk_tag("rt1", "qc"));
        doc2.version_tags = {{"rv_dead", "rt1"}};
        core2.document() = doc2;
        core2.invalidate_maps();
        DirtySet dirty;
        dirty.mark_asset("asset_rb");
        dirty.mark_version("rv_dead");
        dirty.mark_tag("rt1");
        dirty.mark_version_tags("rv_dead");
        PWB_TEST_ASSERT(core2.save(dirty).code == domain::ErrorCode::Ok,
                        "tr5 setup save");
    }
    {
        const std::size_t versions_before = core2.document().versions.size();
        SaveHook failing = [](const DirtySet&) {
            return domain::DataError(domain::ErrorCode::Unknown, "purge boom");
        };
        DocumentIndex index(core2.document());
        TrashPurgeResult result;
        domain::DataError error =
            purge_trashed(&core2.document(), index, p2, failing, {}, &result);
        core2.invalidate_maps();
        PWB_TEST_ASSERT(!error.ok(), "purge failure propagates");
        domain::Json out2 = domain::Json::object();
        out2["error"] = error.message;
        out2["version_back"] =
            core2.document().versions.size() == versions_before;
        bool tag_map_back = false;
        for (const auto& [vid, tag] : core2.document().version_tags) {
            if (vid == "rv_dead") tag_map_back = true;
        }
        out2["tag_map_back"] = tag_map_back;
        bool asset_back = false;
        for (const auto& a : core2.document().assets) {
            if (a.id.str() == "asset_rb") asset_back = true;
        }
        out2["asset_back"] = asset_back;
        out2["store_version_rows"] =
            count_rows(core2.repository().writable_database(), "versions");
        expect_json("purge_save_failure_rollback", out2,
                    o("purge_save_failure_rollback"));
        keep_actual("purge_save_failure_rollback", out2);
    }
}

// ---- J. model registry / promote / governance metadata -------------------------

domain::Json model_view(const Model& m) {
    domain::Json j = domain::Json::object();
    j["model_id"] = m.model_id;
    j["model_name"] = m.model_name;
    j["model_type"] = m.model_type;
    j["capability"] = m.capability;
    j["provider"] = m.provider;
    j["status"] = m.status;
    j["metadata"] = m.metadata;
    j["provenance"] = m.provenance;
    return j;
}

domain::Json mver_view(const ModelVersion& v) {
    domain::Json j = domain::Json::object();
    j["model_id"] = v.model_id;
    j["model_version"] = v.model_version;
    j["status"] = v.status;
    j["demo_only"] = v.demo_only;
    j["checksum"] = v.checksum.has_value() ? domain::Json(*v.checksum)
                                           : domain::Json(nullptr);
    j["artifact_uri"] = v.artifact_uri;
    j["input_schema"] = v.input_schema;
    return j;
}

PWB_CASE(model_registry) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("mr");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "mr open");
    CatalogServiceCore core = std::move(opened.value());
    SaveHook real = core_save_hook(core);

    domain::Json initial_register_view;
    auto register_m = [&](const RegisterModelRequest& request) {
        return register_model(core.document(), real, request);
    };
    auto get_m = [&](const std::string& model_id) {
        auto got = get_model(core.document(), model_id);
        return got.is_ok() ? got.value() : nullptr;
    };
    // Pointer discipline: everything below works through ONE stable
    // document() cache lifetime (no core.invalidate_maps()/find_asset in
    // between — those re-materialize and invalidate pointers).
    auto view_of = [&](const std::string& model_id) {
        const Model* m = get_m(model_id);
        PWB_TEST_ASSERT(m != nullptr, "view_of " + model_id);
        return model_view(*m);
    };

    {
        RegisterModelRequest request;
        request.model_id = "facies-net";
        request.model_name = "Facies Net";
        request.model_type = "cnn";
        request.capability = "facies_prediction";
        request.provider = "pwb";
        request.status = "demo";
        request.metadata = domain::Json::object();
        request.metadata["scientific"] = true;
        request.provenance = domain::Json::object();
        request.provenance["src"] = "a";
        auto m = register_m(request);
        PWB_TEST_ASSERT(m.is_ok(), "register facies-net");
        // NOTE: the generator froze model_view(m) of the LIVE model object
        // — the later provenance refresh ("extra") mutated it in place, so
        // the frozen section carries the post-refresh provenance. The
        // assertion is deferred to after the refresh sequence to mirror
        // that live-object freeze honestly.
        domain::Json initial_view = model_view(*m.value());
        initial_register_view = std::move(initial_view);
    }
    const std::uint64_t serial0 = core.mutation_serial();
    {
        RegisterModelRequest blank;
        blank.model_id = "facies-net";
        blank.model_name = "Facies Net";
        blank.model_type = "unknown";
        blank.status = "production";
        blank.metadata = domain::Json::object();
        blank.metadata["evil"] = 1;
        PWB_TEST_ASSERT(register_m(blank).is_ok(), "blank refresh");
        domain::Json blank_view = view_of("facies-net");  // provenance is a
        // live reference in the generator's freeze — patched post-merge
        // below, like initial_register_view.
        const bool no_save = core.mutation_serial() == serial0;
        RegisterModelRequest refresh;
        refresh.model_id = "facies-net";
        refresh.model_name = "Facies Net v2";
        refresh.provenance = domain::Json::object();
        refresh.provenance["extra"] = "b";
        PWB_TEST_ASSERT(register_m(refresh).is_ok(), "name refresh");
        domain::Json refresh_view = view_of("facies-net");
        RegisterModelRequest force;
        force.model_id = "facies-net";
        force.model_name = "Facies Net v2";
        force.status = "production";
        force.metadata = domain::Json::object();
        force.metadata["forced"] = true;
        force.force_status = true;
        PWB_TEST_ASSERT(register_m(force).is_ok(), "force status");
        domain::Json force_view = view_of("facies-net");
        const std::uint64_t serial1 = core.mutation_serial();
        RegisterModelRequest noop;
        noop.model_id = "facies-net";
        noop.model_name = "Facies Net v2";
        PWB_TEST_ASSERT(register_m(noop).is_ok(), "noop refresh");
        domain::Json out = domain::Json::object();
        out["blank_never_wipes"] = std::move(blank_view);
        out["blank_noop_no_save"] = no_save;
        out["name_refresh_provenance_merge"] = std::move(refresh_view);
        out["force_status_replaces"] = std::move(force_view);
        out["noop_no_save"] = core.mutation_serial() == serial1;
        // Deferred live-object freeze (see the register block above): the
        // views were captured at their capture points, but each frozen
        // provenance sub-dict was a LIVE reference that absorbed the
        // later merge — patch them with the post-merge state before the
        // comparisons.
        const domain::Json live_provenance =
            view_of("facies-net")["provenance"];
        initial_register_view["provenance"] = live_provenance;
        out["blank_never_wipes"]["provenance"] = live_provenance;
        expect_json("model_register_refresh", out, o("model_register_refresh"));
        expect_json("model_register_initial", initial_register_view,
                    o("model_register_initial"));
    }
    {
        RegisterModelRequest no_ids;
        no_ids.model_id = "";
        no_ids.model_name = "x";
        auto refused = register_model(core.document(), real, no_ids);
        PWB_TEST_ASSERT(!refused.is_ok(), "empty ids refused");
        PWB_TEST_ASSERT_EQ(
            refused.error().message,
            o("model_register_requires_ids").get<std::string>(),
            "register ids message parity");
    }
    {
        domain::Json out = domain::Json::object();
        RegisterModelVersionRequest v1;
        v1.model_id = "facies-net";
        v1.input_schema = domain::Json::object();
        v1.input_schema["curves"] = domain::Json::array({"dt"});
        auto mv1 = register_model_version(core.document(), real, v1);
        PWB_TEST_ASSERT(mv1.is_ok(), "mv1");
        out["default"] = mver_view(*mv1.value());
        const fs::path artifact = g_root / "mr" / "artifact.bin";
        {
            std::ofstream out_file(artifact, std::ios::binary);
            out_file << "model-artifact";
        }
        RegisterModelVersionRequest v2;
        v2.model_id = "facies-net";
        v2.model_version = "2";
        v2.artifact_uri = artifact.string();
        auto mv2 = register_model_version(core.document(), real, v2);
        PWB_TEST_ASSERT(mv2.is_ok(), "mv2");
        out["checksum_derived"] =
            mv2.value()->checksum.has_value() &&
            *mv2.value()->checksum == sha_bytes("model-artifact");
        RegisterModelVersionRequest v3;
        v3.model_id = "facies-net";
        v3.model_version = "3";
        v3.artifact_uri = (g_root / "mr" / "missing.bin").string();
        auto mv3 = register_model_version(core.document(), real, v3);
        PWB_TEST_ASSERT(mv3.is_ok(), "mv3");
        out["missing_artifact_checksum"] =
            mv3.value()->checksum.has_value()
                ? domain::Json(*mv3.value()->checksum)
                : domain::Json(nullptr);
        auto dup = register_model_version(core.document(), real, v1);
        out["duplicate_error"] = dup.is_ok()
                                     ? domain::Json("")
                                     : domain::Json(dup.error().message);
        RegisterModelVersionRequest prod;
        prod.model_id = "facies-net";
        prod.model_version = "9";
        prod.status = "production";
        auto refused = register_model_version(core.document(), real, prod);
        out["production_rejected"] =
            refused.is_ok() ? domain::Json("")
                            : domain::Json(refused.error().message);
        expect_json("model_version_registration", out,
                    o("model_version_registration"));
    }

    // Promote gate matrix — reasons verbatim from model_gates.
    {
        domain::Json meta_sci = domain::Json::object();
        meta_sci["scientific"] = false;
        domain::Json schema = domain::Json::object();
        schema["x"] = domain::Json::array();
        struct Spec {
            const char* name;
            std::function<void(RegisterModelRequest&)> model;
            std::function<void(RegisterModelVersionRequest&)> version;
        };
        const std::vector<Spec> specs = {
            {"demo_only",
             [](RegisterModelRequest& r) { r.provider = "pwb"; },
             [](RegisterModelVersionRequest& r) { r.demo_only = true; }},
            {"provider_demo",
             [](RegisterModelRequest& r) { r.provider = "Demo"; },
             [](RegisterModelVersionRequest&) {}},
            {"provider_local_asset_spaced",
             [](RegisterModelRequest& r) { r.provider = " LOCAL_ASSET "; },
             [](RegisterModelVersionRequest&) {}},
            {"provider_local_asset_hyphen_slips",
             [](RegisterModelRequest& r) {
                 r.provider = "local-asset";
                 r.model_type = "cnn";
             },
             [&](RegisterModelVersionRequest& r) {
                 r.input_schema = schema;
             }},
            {"model_type_heuristic",
             [](RegisterModelRequest& r) {
                 r.provider = "pwb";
                 r.model_type = "heuristic";
             },
             [](RegisterModelVersionRequest&) {}},
            {"model_scientific_false",
             [&](RegisterModelRequest& r) {
                 r.provider = "pwb";
                 r.metadata = meta_sci;
             },
             [](RegisterModelVersionRequest&) {}},
            {"version_scientific_false",
             [](RegisterModelRequest& r) { r.provider = "pwb"; },
             [&](RegisterModelVersionRequest& r) { r.metadata = meta_sci; }},
            {"input_schema_required",
             [](RegisterModelRequest& r) { r.provider = "pwb"; },
             [](RegisterModelVersionRequest&) {}},
        };
        domain::Json gate_cases = domain::Json::array();
        for (std::size_t i = 0; i < specs.size(); ++i) {
            const std::string mid = "gate-" + std::to_string(i);
            RegisterModelRequest request;
            request.model_id = mid;
            request.model_name = "G" + std::to_string(i);
            specs[i].model(request);
            PWB_TEST_ASSERT(register_m(request).is_ok(),
                            "gate model " + mid);
            RegisterModelVersionRequest vr;
            vr.model_id = mid;
            specs[i].version(vr);
            auto mv = register_model_version(core.document(), real, vr);
            PWB_TEST_ASSERT(mv.is_ok(), "gate version " + mid);
            auto promoted = promote_model(core.document(), real, mid, "1");
            domain::Json entry = domain::Json::object();
            entry["case"] = specs[i].name;
            if (promoted.is_ok()) {
                entry["err"] = nullptr;
                entry["promoted"] = mver_view(*promoted.value());
            } else {
                entry["err"] = promoted.error().message;
            }
            gate_cases.push_back(std::move(entry));
        }
        auto unknown = promote_model(core.document(), real, "nope", "1");
        auto notreg = promote_model(core.document(), real, "facies-net", "42");
        {
            domain::Json entry = domain::Json::object();
            entry["case"] = "unknown_model";
            entry["err"] = unknown.error().message;
            gate_cases.push_back(std::move(entry));
        }
        {
            domain::Json entry = domain::Json::object();
            entry["case"] = "version_not_registered";
            entry["err"] = notreg.error().message;
            gate_cases.push_back(std::move(entry));
        }
        expect_json("promote_gate_matrix", gate_cases,
                    o("promote_gate_matrix"));
    }

    // Success: both statuses flip, demo_only cleared, ONE save.
    {
        RegisterModelRequest request;
        request.model_id = "ok-net";
        request.model_name = "OK";
        request.model_type = "cnn";
        request.capability = "cap-x";
        request.provider = "pwb";
        PWB_TEST_ASSERT(register_m(request).is_ok(), "ok-net model");
        RegisterModelVersionRequest vr;
        vr.model_id = "ok-net";
        vr.model_version = "1";
        vr.input_schema = domain::Json::object();
        vr.input_schema["curves"] = domain::Json::array();
        auto mv_ok = register_model_version(core.document(), real, vr);
        PWB_TEST_ASSERT(mv_ok.is_ok(), "ok-net version");
        const std::uint64_t serial2 = core.mutation_serial();
        auto promoted = promote_model(core.document(), real, "ok-net", "1");
        PWB_TEST_ASSERT(promoted.is_ok(), "promote ok-net");
        domain::Json out = domain::Json::object();
        out["model_status"] = get_m("ok-net")->status;
        out["version"] = mver_view(*promoted.value());
        out["single_save"] = core.mutation_serial() == serial2 + 1;
        expect_json("promote_success", out, o("promote_success"));
    }

    // find_production_model: newest created_at wins, ties keep doc order.
    for (const char* mid : {"find-a", "find-b", "find-c", "find-d"}) {
        RegisterModelRequest request;
        request.model_id = mid;
        request.model_name = std::string(1, mid[5]);
        request.capability = "cap-f";
        request.provider = "pwb";
        request.status = "production";
        PWB_TEST_ASSERT(register_m(request).is_ok(),
                        std::string("register ") + mid);
    }
    auto register_mv = [&](const std::string& mid, const std::string& number,
                           bool production, const char* created) {
        RegisterModelVersionRequest vr;
        vr.model_id = mid;
        vr.model_version = number;
        auto mv = register_model_version(core.document(), real, vr);
        PWB_TEST_ASSERT(mv.is_ok(), "version " + mid + "@" + number);
        if (production) mv.value()->status = "production";
        if (created != nullptr) mv.value()->created_at = created;
        return mv.value()->id;  // stable: the registry list never shrinks here
    };
    const std::string a1_id = register_mv("find-a", "1", true,
                                          "2024-01-01T00:00:00+00:00");
    const std::string b1_id = register_mv("find-b", "1", true,
                                          "2024-02-01T00:00:00+00:00");
    const std::string b2_id = register_mv("find-b", "2", true,
                                          "2024-03-01T00:00:00+00:00");
    const std::string b3_id = register_mv("find-b", "3", false,
                                          "2024-04-01T00:00:00+00:00");
    const std::string orphan_id = register_mv("find-c", "1", true,
                                              "2024-05-01T00:00:00+00:00");
    // Controlled field write: orphan the find-c version (never raises).
    if (ModelVersion* orphan =
            core.document().find_model_version_by_id_mut(orphan_id)) {
        orphan->model_id = "ghost-model";
    }
    for (auto& mv : core.document().model_versions) {
        if (mv.model_id == "ok-net") {
            mv.created_at = "2024-01-15T00:00:00+00:00";
        }
    }
    {
        DirtySet dirty;
        for (const std::string* id : {&a1_id, &b1_id, &b2_id, &b3_id,
                                      &orphan_id}) {
            dirty.mark_model_version(*id);
        }
        PWB_TEST_ASSERT(core.save(dirty).code == domain::ErrorCode::Ok,
                        "created_at ladder save");
    }
    // Reverify failure: a promoted model whose provider later became demo.
    {
        RegisterModelVersionRequest vr;
        vr.model_id = "find-d";
        vr.input_schema = domain::Json::object();
        vr.input_schema["x"] = domain::Json::array();
        auto d1 = register_model_version(core.document(), real, vr);
        PWB_TEST_ASSERT(d1.is_ok(), "find-d version");
        d1.value()->created_at = "2024-06-01T00:00:00+00:00";
        PWB_TEST_ASSERT(promote_model(core.document(), real, "find-d", "1")
                            .is_ok(),
                        "promote find-d");
        RegisterModelRequest degrade;
        degrade.model_id = "find-d";
        degrade.model_name = "D";
        degrade.provider = "demo";  // refresh mutates identity
        PWB_TEST_ASSERT(register_m(degrade).is_ok(), "degrade find-d");
    }
    register_mv("find-b", "4", true, "2024-03-01T00:00:00+00:00");
    register_mv("find-b", "5", true, "2024-03-01T00:00:00+00:00");

    auto found_json = [&](const char* capability) {
        const ModelVersion* found =
            find_production_model(core.document(), capability);
        if (found == nullptr) return domain::Json(nullptr);
        domain::Json j = domain::Json::object();
        j["model_id"] = found->model_id;
        j["model_version"] = found->model_version;
        j["created_at"] = found->created_at;
        return j;
    };
    {
        domain::Json out = domain::Json::object();
        out["newest_wins"] = found_json("cap-f");
        const domain::Json newest = out["newest_wins"];
        out["tie_doc_order_first"] =
            newest.is_null() ? domain::Json(nullptr)
                             : domain::Json(newest["model_version"]);
        out["no_match"] = found_json("cap-none");
        expect_json("find_production_model", out, o("find_production_model"));
    }

    // update_asset_metadata governance pipeline. The setup goes through
    // the core's add_* API, so the cache edits above must be folded into
    // the node store first.
    core.invalidate_maps();
    const fs::path gov_src = g_root / "mr" / "gov.dat";
    {
        std::ofstream out_file(gov_src, std::ios::binary);
        out_file << "governance";
    }
    domain::Json gov_meta = domain::Json::object();
    gov_meta["region"] = "  Old  Zone ";
    gov_meta["custom"] = "keep";
    DataVersion gov = setup_register_result(
        core, p, "Governed", "seismic", "sgy", gov_meta, gov_src,
        domain::DataStage::Raw);
    const std::string gov_asset = gov.asset_id.str();
    const std::string long_source = [] {
        std::string text = "  ";
        for (int i = 0; i < 200; ++i) text += "ab ";
        return text;
    }();
    auto update = [&](const domain::Json& patch) {
        return update_asset_metadata(core.document(), real,
                                     domain::AssetId(gov_asset), patch, kNow);
    };
    auto meta_of = [&]() -> domain::Json& {
        DataAsset* asset =
            core.document().find_asset_mut(domain::AssetId(gov_asset));
        PWB_TEST_ASSERT(asset != nullptr, "gov asset");
        return asset->metadata;
    };
    domain::Json steps = domain::Json::array();
    auto step_entry = [&](const char* patch) {
        domain::Json j = domain::Json::object();
        j["patch"] = patch;
        return j;
    };
    {
        domain::Json patch = domain::Json::object();
        patch["discipline"] = "stratigraphy";
        PWB_TEST_ASSERT(update(patch).is_ok(), "discipline patch");
        domain::Json j = step_entry("discipline=stratigraphy");
        j["meta"] = meta_of().value("discipline", "");
        steps.push_back(std::move(j));
    }
    {
        domain::Json patch = domain::Json::object();
        patch["confidence"] = "高";
        PWB_TEST_ASSERT(update(patch).is_ok(), "confidence patch");
        domain::Json j = step_entry("confidence=高");
        j["meta"] = meta_of().value("confidence", "");
        steps.push_back(std::move(j));
    }
    {
        domain::Json patch = domain::Json::object();
        patch["review_status"] = "pending";
        PWB_TEST_ASSERT(update(patch).is_ok(), "review patch");
        domain::Json j = step_entry("review_status=pending");
        j["meta"] = meta_of().value("review_status", "");
        steps.push_back(std::move(j));
    }
    {
        domain::Json patch = domain::Json::object();
        patch["source"] = long_source;
        PWB_TEST_ASSERT(update(patch).is_ok(), "source patch");
        const std::string stored = meta_of().value("source", "");
        domain::Json j = step_entry("source=truncate");
        j["len"] = static_cast<int>(stored.size());
        j["folded"] = stored.find("  ") == std::string::npos;
        steps.push_back(std::move(j));
    }
    {
        domain::Json patch = domain::Json::object();
        patch["region"] = "";
        PWB_TEST_ASSERT(update(patch).is_ok(), "region cleared");
        domain::Json j = step_entry("region cleared");
        j["deleted"] = !meta_of().contains("region");
        steps.push_back(std::move(j));
    }
    {
        domain::Json patch = domain::Json::object();
        patch["freeform"] = domain::Json::object();
        patch["freeform"]["n"] = domain::Json::array({1, 2});
        PWB_TEST_ASSERT(update(patch).is_ok(), "freeform patch");
        domain::Json j = step_entry("passthrough");
        j["value"] = meta_of()["freeform"];
        steps.push_back(std::move(j));
    }
    {
        const std::uint64_t serial3 = core.mutation_serial();
        domain::Json patch = domain::Json::object();
        patch["discipline"] = "correlation";
        PWB_TEST_ASSERT(update(patch).is_ok(), "noop patch");
        domain::Json j = step_entry("noop");
        j["serial_unchanged"] = core.mutation_serial() == serial3;
        steps.push_back(std::move(j));
    }
    {
        domain::Json patch = domain::Json::object();
        patch["format"] = "x";
        auto refused = update(patch);
        PWB_TEST_ASSERT(!refused.is_ok(), "reserved key refused");
        domain::Json j = step_entry("reserved");
        j["err"] = refused.error().message;
        steps.push_back(std::move(j));
    }
    {
        domain::Json patch = domain::Json::object();
        patch["discipline"] = "bogus";
        auto refused = update(patch);
        PWB_TEST_ASSERT(!refused.is_ok(), "bad vocab refused");
        domain::Json j = step_entry("bad vocab");
        j["err"] = refused.error().message;
        steps.push_back(std::move(j));
    }
    {
        domain::Json out = domain::Json::object();
        out["steps"] = std::move(steps);
        out["final_metadata"] = meta_of();
        out["updated_at_clock"] =
            core.document().find_asset(domain::AssetId(gov_asset))
                ->updated_at == kNow;
        expect_json("update_asset_metadata_pipeline", out,
                    o("update_asset_metadata_pipeline"));
        keep_actual("update_asset_metadata_pipeline", out);
    }
}

// ---- K. promote_version (#849-1) ------------------------------------------------

PWB_CASE(promote_version) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("pv");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "pv open");
    CatalogServiceCore core = std::move(opened.value());
    const fs::path src = g_root / "pv" / "in.dat";
    { std::ofstream out(src, std::ios::binary); out << "promote-me"; }
    DataVersion v1 = setup_register_result(
        core, p, "Promotable", "seismic", "sgy", domain::Json::object(), src,
        domain::DataStage::Raw);
    const fs::path src2 = g_root / "pv" / "v2.dat";
    { std::ofstream out(src2, std::ios::binary); out << "promote-me-2"; }
    DataVersion v2 = setup_register_version(
        core, p, v1.asset_id, src2, domain::DataStage::Derived);
    SaveHook real = core_save_hook(core);

    auto numbers_of = [&] {
        std::vector<int> numbers;
        for (const auto& v : core.document().versions) {
            if (v.asset_id == v1.asset_id) numbers.push_back(v.version_number);
        }
        std::sort(numbers.begin(), numbers.end());
        return numbers;
    };

    // The #849-1 orchestration composed over the frozen shapes: place a
    // COPY of the source payload under outputs/, re-assign the number
    // inside the commit window, one save with dirty assets+versions+runs.
    auto promote = [&](const std::string& source_id,
                       const std::optional<std::string>& reviewed_by) {
        const DataVersion* source =
            core.document().find_version(domain::VersionId(source_id));
        PWB_TEST_ASSERT(source != nullptr, "promote source");
        const fs::path payload = resolve_payload_path(p, *source);
        const std::string new_id = domain::make_id("ver_");
        auto placed = place_managed_file(
            payload, p, domain::DataStage::Output, source->asset_id.str(),
            new_id, PlaceManagedOptions{});  // keep_source: promote COPIES
        PWB_TEST_ASSERT(placed.is_ok(), "promote place");
        PromoteOptions promote_options;
        promote_options.reviewed_by = reviewed_by;
        DataVersion promoted = *source;
        promoted.id = domain::VersionId(new_id);
        promoted.stage = domain::DataStage::Output;
        promoted.version_number =
            core.document().next_version_number(source->asset_id);
        promoted.path = placed.value().rel_path;
        promoted.size_bytes = placed.value().size_bytes;
        promoted.sha256 = placed.value().sha256;
        promoted.metadata =
            make_promote_version_metadata(source->id, promote_options);
        promoted.parent_version_ids = {source->id};
        promoted.trashed = false;
        promoted.trashed_at = std::nullopt;
        promoted.run_id = std::nullopt;
        promoted.members.clear();
        promoted.created_at = kNow;

        DataRun run = make_promote_run(source->id, promote_options);
        run.id = domain::RunId(domain::make_id("run_"));
        run.output_version_ids = {promoted.id};
        run.created_at = kNow;

        core.document().versions.push_back(promoted);
        core.document().runs.push_back(run);
        core.document()
            .find_asset_mut(promoted.asset_id)
            ->current_version_id = promoted.id;
        core.invalidate_maps();
        DirtySet dirty;
        dirty.mark_asset(promoted.asset_id.str());
        dirty.mark_version(new_id);
        dirty.mark_run(run.id.str());
        domain::DataError error = core.save(dirty);
        PWB_TEST_ASSERT(error.code == domain::ErrorCode::Ok,
                        "promote save: " + error.message);
        return *core.document().find_version(promoted.id);
    };

    const std::vector<int> numbers_before = numbers_of();
    const DataVersion promoted = promote(v2.id.str(), "kevin");
    const DataRun* run = nullptr;
    for (const auto& r : core.document().runs) {
        if (r.operation == "promote" && r.output_version_ids.size() == 1 &&
            r.output_version_ids[0] == promoted.id) {
            run = &r;
        }
    }
    PWB_TEST_ASSERT(run != nullptr, "promote run exists");
    {
        domain::Json out = domain::Json::object();
        domain::Json before = domain::Json::array();
        for (int n : numbers_before) before.push_back(n);
        out["numbers_before"] = std::move(before);
        out["new_number"] = promoted.version_number;
        domain::Json run_json_out = domain::Json::object();
        run_json_out["operation"] = run->operation;
        domain::Json inputs = domain::Json::array();
        for (const auto& id : run->input_version_ids) inputs.push_back(id.str());
        run_json_out["inputs"] = std::move(inputs);
        domain::Json outputs = domain::Json::array();
        for (const auto& id : run->output_version_ids) {
            outputs.push_back(id.str());
        }
        run_json_out["outputs"] = std::move(outputs);
        run_json_out["parameters"] = run->parameters;
        out["run"] = std::move(run_json_out);
        domain::Json parents = domain::Json::array();
        for (const auto& id : promoted.parent_version_ids) {
            parents.push_back(id.str());
        }
        out["parents"] = std::move(parents);
        out["metadata"] = promoted.metadata;
        out["stage"] = std::string(domain::to_string(promoted.stage));
        out["sha_copied"] = promoted.sha256.has_value() &&
                            *promoted.sha256 == sha_bytes("promote-me-2");
        std::error_code ec;
        out["source_payload_intact"] = fs::exists(src2, ec);
        out["current_advanced"] =
            core.document().find_asset(promoted.asset_id)
                ->current_version_id->str() == promoted.id.str();
        out["path"] = promoted.path;
        domain::Json after = domain::Json::array();
        for (int n : numbers_of()) after.push_back(n);
        out["numbers_after"] = std::move(after);
        domain::Json expected =
            expected_json("promote_version_shape",
                          {{"ver_g5", v2.id.str()},
                           {"asset_g6", v1.asset_id.str()},
                           {"ver_g7", promoted.id.str()}});
        expect_json("promote_version_shape", out, expected);
    }
    // A second promote re-allocates inside the lock: numbers stay
    // sequential.
    const DataVersion promoted2 = promote(promoted.id.str(), std::nullopt);
    {
        domain::Json out = domain::Json::object();
        domain::Json numbers = domain::Json::array();
        for (int n : numbers_of()) numbers.push_back(n);
        out["numbers"] = std::move(numbers);
        out["distinct"] =
            promoted2.version_number == promoted.version_number + 1;
        expect_json("promote_version_realloc", out,
                    o("promote_version_realloc"));
    }
}

// ---- L. V11 bundle orchestration -------------------------------------------------

PWB_CASE(bundle_roundtrip) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("bd1");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "bd1 open");
    CatalogServiceCore core = std::move(opened.value());
    auto seams = [&] {
        BundleSeams s;
        s.acquire_lease = [&core](const std::string& target) {
            return core.repository().acquire_staging_lease({target},
                                                           "register");
        };
        s.release_lease = [&core](const std::string& lease_id) {
            core.repository().release_staging_lease(lease_id);
        };
        s.save = core_save_hook(core);
        return s;
    };
    const fs::path seed = g_root / "bd1" / "seed.dat";
    { std::ofstream out(seed, std::ios::binary); out << "bundle-seed"; }
    DataVersion seed_version = setup_register_result(
        core, p, "Bundle Asset", "grid", "bundle", domain::Json::object(),
        seed, domain::DataStage::Raw);
    const std::string asset_id = seed_version.asset_id.str();

    auto make_source = [&](const std::string& name,
                           const std::map<std::string, std::string>& files) {
        const fs::path root = g_root / name / "src";
        std::error_code ec;
        fs::create_directories(root, ec);
        for (const auto& [rel, content] : files) {
            const fs::path target = root / fs::path(rel);
            fs::create_directories(target.parent_path(), ec);
            std::ofstream out(target, std::ios::binary);
            out << content;
        }
        return root;
    };
    const fs::path src = make_source(
        "bd1", {{"a.txt", "AAA"}, {"sub/b.txt", "BBB"},
                {"sub/deep/c.txt", "CCC"}, {"z.csv", "ZZZ"}});
    domain::Json metadata = domain::Json::object();
    metadata["k"] = "v";
    std::vector<VersionMember> specs;
    {
        VersionMember spec;
        spec.rel_path = "sub/b.txt";
        spec.name = "custom-b";
        spec.member_role = "index";
        spec.ordinal = 7;
        spec.required = false;
        specs.push_back(std::move(spec));
    }
    {
        DocumentIndex index(core.document());
        auto version = register_bundle_version(
            &core.document(), index, p, domain::AssetId(asset_id), src,
            domain::DataStage::Derived, specs, {}, std::nullopt, metadata,
            /*move=*/false, seams());
        core.invalidate_maps();
        PWB_TEST_ASSERT(version.is_ok(),
                        "register bundle: " + version.error().message);
        const DataVersion landed = version.value();
        domain::Json out = domain::Json::object();
        domain::Json members = domain::Json::array();
        for (const auto& m : landed.members) members.push_back(member_json(m));
        out["members"] = std::move(members);
        out["path"] = landed.path;
        out["path_is_layout_dir"] =
            landed.path.size() > landed.id.str().size() &&
            landed.path.compare(landed.path.size() - landed.id.str().size(),
                                landed.id.str().size(), landed.id.str()) == 0;
        out["size_sum"] = landed.size_bytes.has_value()
                              ? domain::Json(*landed.size_bytes)
                              : domain::Json(nullptr);
        auto recomputed = aggregate_member_sha256(landed.members);
        out["aggregate_matches_recompute"] =
            landed.sha256.has_value() && recomputed.has_value() &&
            *landed.sha256 == *recomputed;
        out["source_uri"] = landed.source_uri.value_or("");
        out["source_consumed"] = false;
        out["metadata"] = landed.metadata;
        domain::Json expected = expected_json(
            "bundle_register_roundtrip",
            {{"asset_g1", asset_id}, {"ver_g2", landed.id.str()}});
        expect_json("bundle_register_roundtrip", out, expected);

        // Verify: all-verified then tamper/delete.
        const fs::path payload_base = resolve_payload_path(p, landed);
        {
            BundleIntegrityReport report =
                verify_bundle_integrity(landed, payload_base);
            domain::Json out2 = domain::Json::object();
            out2["bundle"] = report.bundle;
            out2["status"] = report.status;
            domain::Json rows = domain::Json::array();
            for (const auto& m : report.members) {
                domain::Json row = domain::Json::object();
                row["name"] = m.name;
                row["rel_path"] = m.rel_path;
                row["status"] = m.status;
                rows.push_back(std::move(row));
            }
            out2["members"] = std::move(rows);
            expect_json("bundle_verify_verified", out2,
                        o("bundle_verify_verified"));
        }
        auto member_path = [&](const char* rel) {
            auto path = bundle_member_path(payload_base, rel);
            PWB_TEST_ASSERT(path.is_ok(), std::string("member path ") + rel);
            return path.value();
        };
        const fs::path member_file = member_path("a.txt");
        const fs::path gone = member_path("z.csv");
        std::error_code ec;
        fs::permissions(member_file,
                        fs::perms::owner_write | fs::perms::group_write |
                            fs::perms::others_write,
                        fs::perm_options::add, ec);
        {
            std::ofstream out_file(member_file, std::ios::binary);
            out_file << "XXX";
        }
        fs::permissions(gone,
                        fs::perms::owner_write | fs::perms::group_write |
                            fs::perms::others_write,
                        fs::perm_options::add, ec);
        fs::remove(gone, ec);
        {
            BundleIntegrityReport report =
                verify_bundle_integrity(landed, payload_base);
            domain::Json out2 = domain::Json::object();
            out2["status"] = report.status;
            domain::Json rows = domain::Json::array();
            for (const auto& m : report.members) {
                domain::Json row = domain::Json::object();
                row["name"] = m.name;
                row["status"] = m.status;
                if (m.actual_sha256.has_value()) {
                    row["actual_sha256"] = *m.actual_sha256;
                }
                rows.push_back(std::move(row));
            }
            out2["members"] = std::move(rows);
            std::string tampered_sha;
            for (const auto& m : report.members) {
                if (m.name == "a.txt" && m.actual_sha256.has_value()) {
                    tampered_sha = *m.actual_sha256;
                }
            }
            out2["actual_matches_tampered"] =
                tampered_sha == sha_bytes("XXX");
            expect_json("bundle_verify_tampered", out2,
                        o("bundle_verify_tampered"));
        }
    }
}

PWB_CASE(bundle_names_budget) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("bd2");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "bd2 open");
    CatalogServiceCore core = std::move(opened.value());
    BundleSeams bundle_seams;
    bundle_seams.save = core_save_hook(core);
    const fs::path seed = g_root / "bd2" / "seed.dat";
    { std::ofstream out(seed, std::ios::binary); out << "bundle-seed"; }
    DataVersion seed_version = setup_register_result(
        core, p, "Names", "grid", "bundle", domain::Json::object(), seed,
        domain::DataStage::Raw);
    const std::string asset_id = seed_version.asset_id.str();

    auto make_source = [&](const std::string& name,
                           const std::map<std::string, std::string>& files) {
        const fs::path root = g_root / name / "src";
        std::error_code ec;
        fs::create_directories(root, ec);
        for (const auto& [rel, content] : files) {
            const fs::path target = root / fs::path(rel);
            fs::create_directories(target.parent_path(), ec);
            std::ofstream out(target, std::ios::binary);
            out << content;
        }
        return root;
    };
    domain::Json real_out = domain::Json::object();
    {
        // spec-vs-spec duplicate name.
        const fs::path src =
            make_source("bd2", {{"a.txt", "A"}, {"b.txt", "B"}});
        std::vector<VersionMember> specs;
        for (const char* rel : {"a.txt", "b.txt"}) {
            VersionMember spec;
            spec.rel_path = rel;
            spec.name = "same";
            specs.push_back(std::move(spec));
        }
        DocumentIndex index(core.document());
        auto refused = register_bundle_version(
            &core.document(), index, p, domain::AssetId(asset_id), src,
            domain::DataStage::Derived, specs, {}, std::nullopt,
            domain::Json::object(), false, bundle_seams);
        core.invalidate_maps();
        PWB_TEST_ASSERT(!refused.is_ok(), "duplicate spec names");
        real_out["duplicate_spec_names_error"] = refused.error().message;

        // Interleaved pool: bare name taken by an earlier auto, rel taken
        // by a spec, numeric suffix ~2.
        const fs::path src2 = make_source(
            "bd2x", {{"a.txt", "A"}, {"keep.txt", "K"}, {"n.txt", "N"},
                     {"sub/n.txt", "NN"}});
        std::vector<VersionMember> spec2;
        {
            VersionMember spec;
            spec.rel_path = "keep.txt";
            spec.name = "n.txt";
            spec2.push_back(std::move(spec));
        }
        DocumentIndex index2(core.document());
        auto v2 = register_bundle_version(
            &core.document(), index2, p, domain::AssetId(asset_id), src2,
            domain::DataStage::Derived, spec2, {}, std::nullopt,
            domain::Json::object(), false, bundle_seams);
        core.invalidate_maps();
        PWB_TEST_ASSERT(v2.is_ok(),
                        "interleaved bundle: " + v2.error().message);
        {
            std::vector<std::pair<std::string, std::string>> pairs;
            std::vector<int> ordinals;
            for (const auto& m : v2.value().members) {
                pairs.push_back({m.name, m.rel_path});
                ordinals.push_back(m.ordinal);
            }
            std::sort(pairs.begin(), pairs.end());
            domain::Json interleaved = domain::Json::array();
            for (const auto& [name, rel] : pairs) {
                domain::Json row = domain::Json::array();
                row.push_back(name);
                row.push_back(rel);
                interleaved.push_back(std::move(row));
            }
            real_out["interleaved"] = std::move(interleaved);
            domain::Json ordinals_json = domain::Json::array();
            for (int ordinal : ordinals) ordinals_json.push_back(ordinal);
            real_out["interleaved_ordinals"] = std::move(ordinals_json);
        }
        // bare-vs-rel fallback.
        const fs::path src3 =
            make_source("bd2y", {{"data.csv", "D"}, {"sub/data.csv", "DD"}});
        DocumentIndex index3(core.document());
        auto v3 = register_bundle_version(
            &core.document(), index3, p, domain::AssetId(asset_id), src3,
            domain::DataStage::Derived, {}, {}, std::nullopt,
            domain::Json::object(), false, bundle_seams);
        core.invalidate_maps();
        PWB_TEST_ASSERT(v3.is_ok(),
                        "bare-vs-rel bundle: " + v3.error().message);
        {
            std::vector<std::pair<std::string, std::string>> pairs;
            for (const auto& m : v3.value().members) {
                pairs.push_back({m.name, m.rel_path});
            }
            std::sort(pairs.begin(), pairs.end());
            domain::Json bare = domain::Json::array();
            for (const auto& [name, rel] : pairs) {
                domain::Json row = domain::Json::array();
                row.push_back(name);
                row.push_back(rel);
                bare.push_back(std::move(row));
            }
            real_out["bare_vs_rel"] = std::move(bare);
        }
        expect_json("bundle_naming_pool", real_out, o("bundle_naming_pool"));
    }

    // Member budget: 70 files rejected BEFORE any IO; the source stays
    // intact.
    {
        const fs::path p3 = proj("bd3");
        auto opened3 = open_catalog(p3, options);
        PWB_TEST_ASSERT(opened3.is_ok(), "bd3 open");
        CatalogServiceCore core3 = std::move(opened3.value());
        BundleSeams seams3;
        seams3.save = core_save_hook(core3);
        const fs::path seed3 = g_root / "bd3" / "seed.dat";
        { std::ofstream out(seed3, std::ios::binary); out << "bundle-seed"; }
        DataVersion seed3_version = setup_register_result(
            core3, p3, "Budget", "grid", "bundle", domain::Json::object(),
            seed3, domain::DataStage::Raw);
        const std::string asset_id3 = seed3_version.asset_id.str();
        const fs::path src70 = g_root / "bd3" / "src";
        std::error_code ec;
        fs::create_directories(src70, ec);
        for (int i = 0; i < 70; ++i) {
            char name[16];
            std::snprintf(name, sizeof(name), "f%02d.dat", i);
            std::ofstream out(src70 / name, std::ios::binary);
            out << static_cast<char>(i);
        }
        DocumentIndex index3(core3.document());
        auto refused = register_bundle_version(
            &core3.document(), index3, p3, domain::AssetId(asset_id3), src70,
            domain::DataStage::Derived, {}, {}, std::nullopt,
            domain::Json::object(), false, seams3);
        core3.invalidate_maps();
        PWB_TEST_ASSERT(!refused.is_ok(), "budget reject");
        domain::Json out = domain::Json::object();
        out["error"] = refused.error().message;
        std::size_t files = 0;
        for (const auto& entry : fs::directory_iterator(src70, ec)) {
            (void)entry;
            ++files;
        }
        out["source_intact"] = files == 70;
        const fs::path stage_root =
            g_root / "bd3" / "bd3.artifacts" / "derived" / asset_id3;
        bool no_new_dirs = true;
        if (fs::exists(stage_root, ec)) {
            for (const auto& entry :
                 fs::directory_iterator(stage_root, ec)) {
                if (entry.path().filename().string() !=
                    core3.document().versions[0].id.str()) {
                    no_new_dirs = false;
                }
            }
        }
        out["no_new_version_dirs"] = no_new_dirs;
        out["versions_unchanged"] = core3.document().versions.size() == 1;
        expect_json("bundle_budget_reject", out, o("bundle_budget_reject"));
        keep_actual("bundle_budget_reject", out);
    }

    // rel-path guard: public API + static validator side by side.
    {
        const fs::path p4 = proj("bd4");
        auto opened4 = open_catalog(p4, options);
        PWB_TEST_ASSERT(opened4.is_ok(), "bd4 open");
        CatalogServiceCore core4 = std::move(opened4.value());
        BundleSeams seams4;
        seams4.save = core_save_hook(core4);
        const fs::path seed4 = g_root / "bd4" / "seed.dat";
        { std::ofstream out(seed4, std::ios::binary); out << "bundle-seed"; }
        DataVersion seed4_version = setup_register_result(
            core4, p4, "Guard", "grid", "bundle", domain::Json::object(),
            seed4, domain::DataStage::Raw);
        const std::string asset_id4 = seed4_version.asset_id.str();
        const fs::path src4 = g_root / "bd4" / "src";
        std::error_code ec;
        fs::create_directories(src4, ec);
        { std::ofstream out(src4 / "ok.bin", std::ios::binary); out << "OK"; }
        { std::ofstream out(src4 / "a..b", std::ios::binary); out << "DOTS"; }
        domain::Json rejects = domain::Json::array();
        for (const std::string bad :
             {"", "../outside.shp", "a/../../x", "/abs/x"}) {
            domain::Json row = domain::Json::object();
            row["rel"] = bad;
            std::vector<VersionMember> specs;
            VersionMember spec;
            spec.rel_path = bad;
            spec.name = "x";
            specs.push_back(std::move(spec));
            DocumentIndex index4(core4.document());
            auto refused = register_bundle_version(
                &core4.document(), index4, p4, domain::AssetId(asset_id4),
                src4, domain::DataStage::Derived, specs, {}, std::nullopt,
                domain::Json::object(), false, seams4);
            core4.invalidate_maps();
            PWB_TEST_ASSERT(!refused.is_ok(), "guard reject " + bad);
            row["err"] = refused.error().message;
            domain::DataError static_error = validate_member_rel_path(bad);
            row["static_err"] = static_error.message;
            rejects.push_back(std::move(row));
        }
        std::vector<VersionMember> accepted_specs;
        {
            VersionMember spec;
            spec.rel_path = "a..b";
            spec.name = "dots-file";
            spec.member_role = "sidecar";
            accepted_specs.push_back(std::move(spec));
        }
        DocumentIndex index4(core4.document());
        auto accepted = register_bundle_version(
            &core4.document(), index4, p4, domain::AssetId(asset_id4), src4,
            domain::DataStage::Raw, accepted_specs, {}, std::nullopt,
            domain::Json::object(), false, seams4);
        core4.invalidate_maps();
        PWB_TEST_ASSERT(accepted.is_ok(),
                        "literal dots accepted: " + accepted.error().message);
        domain::Json out = domain::Json::object();
        out["rejects"] = std::move(rejects);
        domain::Json names = domain::Json::array();
        std::vector<std::string> sorted_names;
        for (const auto& m : accepted.value().members) {
            sorted_names.push_back(m.name);
        }
        std::sort(sorted_names.begin(), sorted_names.end());
        for (const auto& name : sorted_names) names.push_back(name);
        out["literal_dots_accepted"] = std::move(names);
        expect_json("bundle_relpath_guard", out, o("bundle_relpath_guard"));
        keep_actual("bundle_relpath_guard", out);
    }
}

PWB_CASE(bundle_working_copies) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("bd5");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "bd5 open");
    CatalogServiceCore core = std::move(opened.value());
    std::set<std::string> pending;
    auto context = [&] {
        return WorkingCopyContext{p, &core.repository(), &core.document(),
                                  &pending};
    };
    BundleSeams seams;
    seams.acquire_lease = [&core](const std::string& target) {
        return core.repository().acquire_staging_lease({target}, "register");
    };
    seams.release_lease = [&core](const std::string& lease_id) {
        core.repository().release_staging_lease(lease_id);
    };
    seams.save = core_save_hook(core);
    // #1218 new-asset seam. commit_bundle_working_copy consumes the
    // CALLER's DocumentIndex, so the fresh asset must already be in the
    // document when the index is built — pre-create the id, let the seam
    // materialize the row before the register call reads the index.
    std::string pending_new_asset_id;
    auto prepare_new_asset = [&](const std::string& name,
                                 const domain::Json& metadata) {
        pending_new_asset_id = domain::make_id("asset_");
        DataAsset asset;
        asset.id = domain::AssetId(pending_new_asset_id);
        asset.name = name;
        asset.metadata = metadata;
        asset.created_at = kNow;
        asset.updated_at = kNow;
        core.document().assets.push_back(std::move(asset));
        core.invalidate_maps();
    };
    auto new_asset_seam = [&](const std::string& name,
                              domain::Json metadata) -> domain::AssetId {
        if (pending_new_asset_id.empty()) {
            pending_new_asset_id = domain::make_id("asset_");
            DataAsset asset;
            asset.id = domain::AssetId(pending_new_asset_id);
            asset.name = name;
            asset.metadata = std::move(metadata);
            asset.created_at = kNow;
            asset.updated_at = kNow;
            core.document().assets.push_back(std::move(asset));
            core.invalidate_maps();
        }
        return domain::AssetId(pending_new_asset_id);
    };
    const fs::path seed = g_root / "bd5" / "seed.dat";
    { std::ofstream out(seed, std::ios::binary); out << "bundle-seed"; }
    DataVersion seed_version = setup_register_result(
        core, p, "Cycle", "grid", "bundle", domain::Json::object(), seed,
        domain::DataStage::Raw);
    const std::string asset_id = seed_version.asset_id.str();
    const fs::path src = g_root / "bd5" / "src";
    std::error_code ec;
    fs::create_directories(src, ec);
    { std::ofstream out(src / "a.txt", std::ios::binary); out << "AAA"; }
    fs::create_directories(src / "sub", ec);
    {
        std::ofstream out(src / "sub" / "b.txt", std::ios::binary);
        out << "BBB";
    }

    DataVersion v1;
    {
        DocumentIndex index(core.document());
        auto registered = register_bundle_version(
            &core.document(), index, p, domain::AssetId(asset_id), src,
            domain::DataStage::Derived, {}, {}, std::nullopt,
            domain::Json::object(), false, seams);
        core.invalidate_maps();
        PWB_TEST_ASSERT(registered.is_ok(),
                        "bd5 register: " + registered.error().message);
        v1 = registered.value();
    }
    {
        const fs::path payload_base = resolve_payload_path(p, v1);
        {
            WorkingCopyContext ctx = context();
            auto created = create_bundle_working_copy(v1, payload_base, p,
                                                      false, ctx);
            core.invalidate_maps();
            PWB_TEST_ASSERT(created.is_ok(),
                            "bundle wc: " + created.error().message);
            const fs::path wc_dir = created.value();
            std::vector<std::string> copied;
            for (const auto& entry :
                 fs::recursive_directory_iterator(wc_dir, ec)) {
                copied.push_back(entry.path().filename().string());
            }
            std::sort(copied.begin(), copied.end());
            {
                std::ofstream out(wc_dir / "a.txt", std::ios::binary);
                out << "AAA-edited";
            }
            WorkingCopyContext ctx2 = context();
            auto reused = create_bundle_working_copy(v1, payload_base, p,
                                                     false, ctx2);
            core.invalidate_maps();
            DocumentIndex index(core.document());
            WorkingCopyContext commit_ctx = context();
            auto committed = commit_bundle_working_copy(
                &core.document(), index, p, wc_dir, domain::AssetId(asset_id),
                "cycle v2", domain::DataStage::Derived, nullptr,
                std::nullopt, domain::Json::object(), commit_ctx, seams,
                new_asset_seam);
            core.invalidate_maps();
            PWB_TEST_ASSERT(committed.is_ok(),
                            "bundle commit: " + committed.error().message);
            const DataVersion landed = committed.value();
            const VersionMember* edited = nullptr;
            for (const auto& m : landed.members) {
                if (m.rel_path == "a.txt") edited = &m;
            }
            domain::Json out = domain::Json::object();
            out["wc_dir"] = wc_dir.string();
            domain::Json members_copied = domain::Json::array();
            for (const auto& name : copied) members_copied.push_back(name);
            out["members_copied"] = std::move(members_copied);
            out["reuse_same_dir"] =
                reused.is_ok() && reused.value() == wc_dir;
            out["new_version_number"] = landed.version_number;
            domain::Json parents = domain::Json::array();
            for (const auto& id : landed.parent_version_ids) {
                parents.push_back(id.str());
            }
            out["parent"] = std::move(parents);
            out["edited_sha"] = edited != nullptr &&
                                edited->sha256.has_value() &&
                                *edited->sha256 == sha_bytes("AAA-edited");
            out["source_dir_consumed"] = !fs::exists(wc_dir, ec);
            bool originals_intact = true;
            for (const auto& m : v1.members) {
                auto path = bundle_member_path(payload_base, m.rel_path);
                if (!path.is_ok() || !fs::exists(path.value(), ec)) {
                    originals_intact = false;
                }
            }
            out["original_members_intact"] = originals_intact;
            out["rows_after"] = wc_rows_json(core.repository());
            domain::Json expected =
                expected_json("bundle_wc_cycle", {{"ver_g3", v1.id.str()}});
            expect_json("bundle_wc_cycle", out, expected);
        }
    }
    // Commit as a NEW asset (asset_id=nullopt names the new asset).
    {
        const fs::path src2 = g_root / "bd5b" / "src";
        fs::create_directories(src2, ec);
        { std::ofstream out(src2 / "x.txt", std::ios::binary); out << "XX"; }
        DataVersion v2;
        {
            DocumentIndex index(core.document());
            auto registered = register_bundle_version(
                &core.document(), index, p, domain::AssetId(asset_id), src2,
                domain::DataStage::Derived, {}, {}, std::nullopt,
                domain::Json::object(), false, seams);
            core.invalidate_maps();
            PWB_TEST_ASSERT(registered.is_ok(), "bd5b register");
            v2 = registered.value();
        }
        const fs::path payload_base = resolve_payload_path(p, v2);
        {
            WorkingCopyContext ctx = context();
            auto created = create_bundle_working_copy(v2, payload_base, p,
                                                      false, ctx);
            core.invalidate_maps();
            PWB_TEST_ASSERT(created.is_ok(), "bd5b wc");
            // Seed the new asset BEFORE the index snapshot (the seam
            // returns this pre-created id; failure erases it by id).
            prepare_new_asset("Fresh Bundle Asset", domain::Json::object());
            DocumentIndex index(core.document());
            WorkingCopyContext commit_ctx = context();
            auto committed = commit_bundle_working_copy(
                &core.document(), index, p, created.value(), std::nullopt,
                "Fresh Bundle Asset", domain::DataStage::Derived, nullptr,
                std::nullopt, domain::Json::object(), commit_ctx, seams,
                new_asset_seam);
            core.invalidate_maps();
            PWB_TEST_ASSERT(committed.is_ok(),
                            "fresh bundle commit: " + committed.error().message);
            const DataVersion landed = committed.value();
            const DataAsset* fresh = core.document().find_asset(landed.asset_id);
            domain::Json out = domain::Json::object();
            out["asset_name"] = fresh->name;
            out["distinct_asset"] = landed.asset_id.str() != asset_id;
            domain::Json parents = domain::Json::array();
            for (const auto& id : landed.parent_version_ids) {
                parents.push_back(id.str());
            }
            out["parent"] = std::move(parents);
            domain::Json expected =
                expected_json("bundle_wc_new_asset", {{"ver_g4", v2.id.str()}});
            expect_json("bundle_wc_new_asset", out, expected);
        }
    }
}

PWB_CASE(v11_ports) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("bd6");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "bd6 open");
    CatalogServiceCore core = std::move(opened.value());
    {
        CatalogDocument doc;
        doc.assets.push_back(mk_asset("asset_p", "Ports"));
        {
            DataVersion v = mk_ver("pvin", "asset_p", 1);
            v.path = "bd6.artifacts/raw/asset_p/pvin/i.bin";
            doc.versions.push_back(std::move(v));
        }
        {
            DataVersion v = mk_ver("pvout", "asset_p", 2,
                                   domain::DataStage::Derived);
            v.path = "bd6.artifacts/derived/asset_p/pvout/o.bin";
            doc.versions.push_back(std::move(v));
        }
        {
            DataRun r = mk_run("pr1", "factor_map");
            r.input_version_ids = {vid("pvin")};
            r.output_version_ids = {vid("pvout")};
            doc.runs.push_back(std::move(r));
        }
        {
            DataRun r = mk_run("pr2", "custom_op");
            r.input_version_ids = {vid("pvin")};
            doc.runs.push_back(std::move(r));
        }
        core.document() = doc;
        core.invalidate_maps();
        DirtySet dirty;
        dirty.mark_asset("asset_p");
        dirty.mark_version("pvin");
        dirty.mark_version("pvout");
        dirty.mark_run("pr1");
        dirty.mark_run("pr2");
        PWB_TEST_ASSERT(core.save(dirty).code == domain::ErrorCode::Ok,
                        "bd6 setup save");
    }
    auto ports_json = [](const RunPortsView& view) {
        domain::Json j = domain::Json::object();
        domain::Json inputs = domain::Json::array();
        for (const auto& port : view.input) inputs.push_back(port_json(port));
        j["input"] = std::move(inputs);
        domain::Json outputs = domain::Json::array();
        for (const auto& port : view.output) outputs.push_back(port_json(port));
        j["output"] = std::move(outputs);
        return j;
    };
    domain::Json out = domain::Json::object();
    {
        SaveHook real = core_save_hook(core);
        const DataRun* pr1 = core.document().find_run(rid("pr1"));
        out["before_anonymous"] = ports_json(ports_for_run(*pr1));
        {
            DocumentIndex index(core.document());
            PortMigrationOutcome migrated =
                migrate_run_ports_persist(&core.document(), index, real);
            core.invalidate_maps();
            domain::Json result = domain::Json::object();
            result["runs_annotated"] = migrated.counts.runs_annotated;
            result["ports_added"] = migrated.counts.ports_added;
            out["migrate_result"] = std::move(result);
        }
        const DataRun* after_pr1 =
            core.document().find_run(rid("pr1"));
        out["after"] = ports_json(ports_for_run(*after_pr1));
        {
            DocumentIndex index2(core.document());
            PortMigrationOutcome again =
                migrate_run_ports_persist(&core.document(), index2, real);
            core.invalidate_maps();
            domain::Json idempotent = domain::Json::object();
            idempotent["runs_annotated"] = again.counts.runs_annotated;
            idempotent["ports_added"] = again.counts.ports_added;
            out["idempotent"] = std::move(idempotent);
        }
        const DataRun* pr2 = core.document().find_run(rid("pr2"));
        domain::Json unknown = domain::Json::array();
        for (const auto& port : ports_for_run(*pr2).input) {
            unknown.push_back(port_json(port));
        }
        out["unknown_operation_untouched"] = std::move(unknown);
        out["store_run_ports"] =
            dump_store(core.repository().writable_database())["run_ports"];
    }
    expect_json("v11_ports_backfill", out, o("v11_ports_backfill"));
}

// ---- negative self-check ---------------------------------------------------

PWB_CASE(negative_self_check) {
    ensure_init();
    // Tampered oracle values MUST be detected by the same comparator the
    // replays use (independent tamper kinds over replayed sections; the
    // kept actuals are oracle-comparable — ids and paths masked).
    PWB_TEST_ASSERT(g_actual.size() >= 6,
                    "self-check needs replayed actuals");

    // 1. Value tamper: db_dirty_set assets_order entry.
    {
        domain::Json tampered = o("db_dirty_set");
        tampered["assets_order"][1] = "aX";
        PWB_TEST_ASSERT(
            pwb_test::json_compare(tampered, g_actual["db_dirty_set"])
                .has_value(),
            "tampered assets_order must be detected");
    }
    // 2. Boolean flip: db_is_fresh_gates.all_ok.
    {
        domain::Json tampered = o("db_is_fresh_gates");
        tampered["all_ok"] = !tampered["all_ok"].get<bool>();
        PWB_TEST_ASSERT(
            pwb_test::json_compare(tampered, g_actual["db_is_fresh_gates"])
                .has_value(),
            "flipped gate must be detected");
    }
    // 3. Type change (int → float): batch_save_timing revisions.
    {
        domain::Json tampered = o("batch_save_timing");
        tampered["revision_after_exit"] =
            static_cast<double>(tampered["revision_after_exit"].get<int>());
        PWB_TEST_ASSERT(
            pwb_test::json_compare(tampered, g_actual["batch_save_timing"])
                .has_value(),
            "int→float type change must be detected");
    }
    // 4. Message character swap: wc_discard_guard.committing_error.
    {
        domain::Json tampered = o("wc_discard_guard");
        std::string message = tampered["committing_error"].get<std::string>();
        PWB_TEST_ASSERT(!message.empty(), "guard message frozen");
        message += "X";  // append: swapping a mid-codepoint byte would
                         // produce invalid UTF-8 and kill the comparator
        tampered["committing_error"] = message;
        PWB_TEST_ASSERT(
            pwb_test::json_compare(tampered, g_actual["wc_discard_guard"])
                .has_value(),
            "swapped message character must be detected");
    }
    // 5. Extra array element: resolve_path_ladder.
    {
        domain::Json ladder = o("resolve_path_ladder");
        domain::Json extra = ladder[0];
        ladder.push_back(extra);
        domain::Json actual = g_actual["resolve_path_ladder"];
        PWB_TEST_ASSERT(
            pwb_test::json_compare(ladder, actual).has_value(),
            "extra array element must be detected");
    }
    // 6. Nested value tamper: update_asset_metadata_pipeline
    //    final_metadata.confidence.
    {
        domain::Json tampered = o("update_asset_metadata_pipeline");
        tampered["final_metadata"]["confidence"] = "low";
        PWB_TEST_ASSERT(
            pwb_test::json_compare(tampered,
                                   g_actual["update_asset_metadata_pipeline"])
                .has_value(),
            "tampered confidence must be detected");
    }
    // 7. Key deletion: save_failure_semantics.serial_advanced.
    {
        domain::Json tampered = o("save_failure_semantics");
        tampered.erase("serial_advanced");
        PWB_TEST_ASSERT(
            pwb_test::json_compare(tampered,
                                   g_actual["save_failure_semantics"])
                .has_value(),
            "dropped key must be detected");
    }
    // 8. Value replacement (CONV-31b Wave4 / V3-P2-1: the original "array
    //    shrink + value change" wording was inaccurate — this block only
    //    replaces "70"→"71" inside the frozen error text):
    //    bundle_budget_reject.error text.
    {
        domain::Json tampered = o("bundle_budget_reject");
        std::string message = tampered["error"].get<std::string>();
        PWB_TEST_ASSERT(message.find("70") != std::string::npos,
                        "budget message frozen");
        tampered["error"] = message.replace(message.find("70"), 2, "71");
        PWB_TEST_ASSERT(
            pwb_test::json_compare(tampered, g_actual["bundle_budget_reject"])
                .has_value(),
            "tampered budget message must be detected");
    }
}

// ---- J. CONV-31b Wave4 regression pins (V2-P0-1 / V2-P1-1 / V2-P1-2) --------

// V2-P0-1: entity pointers are stable across invalidate_maps() folds —
// the header contract "stable for the core's lifetime until the entity is
// removed". The pre-Wave4 fold destroyed and rebuilt every node from the
// cache, so the writes below were a heap-use-after-free (ASan-confirmed
// in review repro repro_node_dangle).
PWB_CASE(node_pointer_stability) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("np");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "np open");
    CatalogServiceCore core = std::move(opened.value());

    DataAsset* node = core.add_asset(mk_asset("asset_np1", "Node One"));
    DataVersion* vnode = core.add_version(mk_ver("ver_np1", "asset_np1", 1));
    DataRun* rnode = core.add_run(mk_run("run_np1"));

    // The documented migrate shape: document() edit, then invalidate_maps().
    // The fold must land the edit on the SAME node (value refreshed in
    // place, address unchanged) — the strongest form of the contract.
    for (DataAsset& doc_asset : core.document().assets) {
        if (doc_asset.id == domain::AssetId(std::string("asset_np1"))) {
            doc_asset.name = "Folded Name";
        }
    }
    core.invalidate_maps();
    PWB_TEST_ASSERT(node->name == "Folded Name",
                    "fold refreshed the surviving node in place");
    PWB_TEST_ASSERT(core.find_asset("asset_np1") == node,
                    "maps still resolve the same node address");

    // Pointer writes AFTER the protocol dance — the old UAF window.
    node->name = "renamed-after-invalidate";
    vnode->metadata["touched"] = true;
    rnode->operation = "renamed-op";
    PWB_TEST_ASSERT(node->name == "renamed-after-invalidate",
                    "asset node survived the fold");
    PWB_TEST_ASSERT(vnode->metadata.contains("touched"),
                    "version node survived the fold");
    PWB_TEST_ASSERT(rnode->operation == "renamed-op",
                    "run node survived the fold");

    // Identity removal through the surviving pointer is the sanctioned
    // use ("until the entity is removed" — removal may destroy it).
    core.remove_run(rnode);
    PWB_TEST_ASSERT(core.find_run("run_np1") == nullptr,
                    "identity removal via the stable pointer");
}

// V2-P1-1: a working-copy commit persists through the repository
// transaction channel (one transaction + one revision bump, never routed
// through core.save), so the composition syncs the document revision onto
// the post-transaction store revision and the core re-baselines its CAS
// expectation. The pre-Wave4 core kept the stale baseline and refused
// every subsequent same-session save with a bogus #411 "another instance"
// error (review repro repro_cas_desync: code=3 + stale_write=true).
PWB_CASE(wc_commit_then_core_save) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("wc5");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "wc5 open");
    CatalogServiceCore core = std::move(opened.value());
    const fs::path src = g_root / "wc5" / "seed.dat";
    { std::ofstream out(src, std::ios::binary); out << "wc-cas-seed"; }
    DataVersion version = setup_register_result(
        core, p, "WC CAS Asset", "seismic", "sgy", domain::Json::object(),
        src, domain::DataStage::Raw);

    // Checkout + commit through the repo-transaction channel.
    std::set<std::string> pending;
    WorkingCopyContext context{p, &core.repository(), &core.document(),
                               &pending};
    auto wc = create_working_copy(context, version.id, false);
    PWB_TEST_ASSERT(wc.is_ok(), "wc checkout: " + wc.error().message);
    core.invalidate_maps();  // WC bookkeeping mirrored into document()
    CommitWorkingCopyRequest request;
    request.asset_id = version.asset_id;
    request.stage = domain::DataStage::Derived;
    auto committed = commit_working_copy(context, wc.value(), request);
    PWB_TEST_ASSERT(committed.is_ok(),
                    "wc commit: " + committed.error().message);
    core.invalidate_maps();

    // THE regression: a plain core save in the SAME session must succeed.
    DirtySet after;
    after.mark_asset(version.asset_id.str());
    domain::DataError saved = core.save(after);
    PWB_TEST_ASSERT(saved.code == domain::ErrorCode::Ok,
                    "post-commit save refused: " + saved.message);
    PWB_TEST_ASSERT(!is_stale_write(saved), "no bogus stale_write flag");
    PWB_TEST_ASSERT(core.document_revision() ==
                        core.flushed_revision().value_or(-1),
                    "document revision re-synced to the CAS baseline");

    // Both channels' rows are durable together after a reopen.
    core.close();
    auto reopened = open_catalog(p, options);
    PWB_TEST_ASSERT(reopened.is_ok(), "reopen: " + reopened.error().message);
    const DataVersion* landed = nullptr;
    for (const DataVersion& v : reopened.value().document().versions) {
        if (v.id == committed.value().id) landed = &v;
    }
    PWB_TEST_ASSERT(landed != nullptr, "committed version durable");
    PWB_TEST_ASSERT(landed != nullptr && landed->version_number == 2,
                    "working-copy commit landed as version 2");
}

// V2-P1-2 / V1-P2-1: find_* are pure reads. An intervening lookup between
// a document() direct edit and invalidate_maps() must not stop the fold —
// the pre-Wave4 find_* cleared cache_valid, invalidate_maps then skipped
// the fold and the direct edit was silently dropped from the node store.
PWB_CASE(find_pure_read_keeps_direct_edits) {
    ensure_init();
    CatalogOpenOptions options;
    options.sweep_temp = false;
    const fs::path p = proj("fr");
    auto opened = open_catalog(p, options);
    PWB_TEST_ASSERT(opened.is_ok(), "fr open");
    CatalogServiceCore core = std::move(opened.value());
    core.add_asset(mk_asset("asset_fr1", "FR"));
    core.add_version(mk_ver("ver_fr1", "asset_fr1", 1));

    // Direct document() edit …
    for (DataVersion& v : core.document().versions) {
        if (v.id == vid("ver_fr1")) v.metadata["direct"] = "edit";
    }
    // … intervening PURE lookups (previously the edit killer) …
    PWB_TEST_ASSERT(core.find_version("ver_fr1") != nullptr, "intervening read 1");
    PWB_TEST_ASSERT(core.find_asset("asset_fr1") != nullptr, "intervening read 2");
    PWB_TEST_ASSERT(core.find_run("run_absent") == nullptr, "intervening miss read");
    // … then the protocol fold.
    core.invalidate_maps();

    // The fold landed the direct edit in the node store (read it back
    // through a node pointer, not the still-valid cache).
    const DataVersion* folded = core.find_version("ver_fr1");
    PWB_TEST_ASSERT(folded != nullptr &&
                        folded->metadata.contains("direct") &&
                        folded->metadata["direct"] == "edit",
                    "direct edit survived the intervening find_*");

    // And a dirty save persists it (the flush view carries the edit).
    DirtySet dirty;
    dirty.mark_version("ver_fr1");
    domain::DataError saved = core.save(dirty);
    PWB_TEST_ASSERT(saved.code == domain::ErrorCode::Ok,
                    "save after fold: " + saved.message);
    core.close();
    auto reopened = open_catalog(p, options);
    PWB_TEST_ASSERT(reopened.is_ok(), "fr reopen");
    const DataVersion* persisted = nullptr;
    for (const DataVersion& v : reopened.value().document().versions) {
        if (v.id == vid("ver_fr1")) persisted = &v;
    }
    PWB_TEST_ASSERT(persisted != nullptr &&
                        persisted->metadata.contains("direct"),
                    "direct edit persisted to the store");
}
