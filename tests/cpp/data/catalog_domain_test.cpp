// data.catalog_domain — conv-31 oracle replay (catalog policy / lineage /
// impact / explain / sources / queries / tags / migration / audit / V11
// policy core) against the fixtures frozen by
// tools/oracle/generate_catalog_domain_fixtures.py, plus a negative
// self-check (tampered oracle values MUST be detected).
#include "compare_json.hpp"
#include "pwb_test.hpp"

#include "pwb/catalog/audit.hpp"
#include "pwb/catalog/checksum.hpp"
#include "pwb/catalog/document_index.hpp"
#include "pwb/catalog/explain.hpp"
#include "pwb/catalog/impact.hpp"
#include "pwb/catalog/legacy_migration.hpp"
#include "pwb/catalog/lineage_graph.hpp"
#include "pwb/catalog/policies.hpp"
#include "pwb/catalog/queries.hpp"
#include "pwb/catalog/sources.hpp"
#include "pwb/catalog/refs.hpp"
#include "pwb/catalog/tags.hpp"
#include "pwb/catalog/v11_policy.hpp"

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <regex>

using namespace pwb;
using namespace pwb::catalog;
namespace fs = std::filesystem;

namespace {

fs::path g_root;       // scenario temp root ({ROOT} in the oracle)
domain::Json g_oracle;

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

void ensure_init() {
    static bool done = false;
    if (done) return;
    done = true;
    const char* fixture_dir = getenv("PWB_DATA_FIXTURE_DIR");
    const fs::path fixtures =
        fixture_dir != nullptr
            ? fs::path(fixture_dir)
            : fs::path(__FILE__).parent_path() / "fixtures";
    g_oracle = load_json(fixtures / "catalog_domain" / "oracle.json");
    char pattern[] = "/tmp/catalog-domain-replay-XXXXXX";
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


CatalogDocument build_document() {
    CatalogDocument doc;
    auto asset = [](const char* id, const char* name, const char* type,
                    const char* current) {
        DataAsset a;
        a.id = domain::AssetId(std::string(id));
        a.name = name;
        a.type = type;
        a.current_version_id = domain::VersionId(std::string(current));
        return a;
    };
    doc.assets.push_back(asset("asset_a", "Seismic A", "seismic", "ver_a2"));
    doc.assets.push_back(asset("asset_b", "Log B", "well_log", "ver_b5"));
    doc.assets.push_back(asset("asset_d", "Derived D", "seismic_attribute", "ver_d3"));

    auto version = [](const char* id, const char* aid, int number,
                      domain::DataStage stage, bool managed, const char* path,
                      const char* sha, const char* created) {
        DataVersion v;
        v.id = domain::VersionId(std::string(id));
        v.asset_id = domain::AssetId(std::string(aid));
        v.version_number = number;
        v.stage = stage;
        v.managed = managed;
        v.path = path;
        v.sha256 = sha ? std::optional<std::string>(std::string(sha)) : std::nullopt;
        v.created_at = created;
        return v;
    };
    DataVersion a1 = version("ver_a1", "asset_a", 1, domain::DataStage::Raw, true,
                             "demo.artifacts/raw/asset_a/ver_a1/a.sgy", "0000",
                             "2024-01-01T00:00:00+00:00");
    a1.sha256 = std::string(64, '0');
    DataVersion a2 = version("ver_a2", "asset_a", 2, domain::DataStage::Raw, true,
                             "demo.artifacts/raw/asset_a/ver_a2/a.sgy", nullptr,
                             "2024-01-02T00:00:00+00:00");
    a2.sha256 = std::string(64, '1');
    DataVersion b5 = version("ver_b5", "asset_b", 5, domain::DataStage::Raw, false,
                             (g_root / "gone.las").string().c_str(), nullptr,
                             "2024-01-03T00:00:00+00:00");
    b5.sha256 = std::string(64, '2');
    DataVersion d3 = version("ver_d3", "asset_d", 1, domain::DataStage::Derived,
                             true, "demo.artifacts/derived/asset_d/ver_d3/d.npy",
                             nullptr, "2024-01-04T00:00:00+00:00");
    d3.sha256 = std::string(64, '3');
    d3.run_id = domain::RunId(std::string("run_r1"));
    d3.parent_version_ids = {domain::VersionId(std::string("ver_a1")),
                             domain::VersionId(std::string("ver_missing"))};
    DataVersion e4 = version("ver_e4", "asset_d", 2, domain::DataStage::Output,
                             true, "demo.artifacts/outputs/asset_d/ver_e4/e.png",
                             nullptr, "2024-01-05T00:00:00+00:00");
    e4.run_id = domain::RunId(std::string("run_r1"));
    e4.parent_version_ids = {domain::VersionId(std::string("ver_d3"))};
    domain::Json pin = domain::Json::object();
    pin["reason"] = "保图";
    pin["pinned_at"] = "2024-01-06T00:00:00+00:00";
    e4.metadata = domain::Json::object();
    e4.metadata["pin"] = pin;
    doc.versions.push_back(std::move(a1));
    doc.versions.push_back(std::move(a2));
    doc.versions.push_back(std::move(b5));
    doc.versions.push_back(std::move(d3));
    doc.versions.push_back(std::move(e4));

    DataRun run;
    run.id = domain::RunId(std::string("run_r1"));
    run.operation = "factor_map";
    run.input_version_ids = {domain::VersionId(std::string("ver_a1"))};
    run.output_version_ids = {domain::VersionId(std::string("ver_d3")),
                              domain::VersionId(std::string("ver_e4"))};
    RunPort input;
    input.direction = "input";
    input.role = "seismic_volume";
    input.version_id = domain::VersionId(std::string("ver_a1"));
    input.ordinal = 0;
    input.required = true;
    run.input_ports.push_back(std::move(input));
    run.parameters = domain::Json::object();
    run.parameters["factor"] = "paleo";
    run.generator = "pwb 0.2";
    run.status = "completed";
    run.created_at = "2024-01-04T00:00:00+00:00";
    doc.runs.push_back(std::move(run));

    Tag tag;
    tag.id = "tag_t1";
    tag.name = "qc";
    tag.display_name = "QC";
    doc.tags.push_back(std::move(tag));
    doc.asset_tags.push_back({"asset_a", "tag_t1"});
    doc.version_tags.push_back({"ver_d3", "tag_t1"});
    return doc;
}

fs::path write_payload() {
    const fs::path payload = g_root / "hash.bin";
    const std::string unit = std::string("paleo") + std::string(1, '\0') + "workbench";
    std::string bytes;
    for (int i = 0; i < 10000; ++i) bytes += unit;
    std::ofstream out(payload, std::ios::binary);
    out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    return payload;
}

domain::Json run_port_json(const RunPort& port) {
    domain::Json j = domain::Json::object();
    j["role"] = port.role;
    j["version_id"] = port.version_id.str();
    j["ordinal"] = port.ordinal;
    j["required"] = port.required;
    j["entity_type"] = port.entity_type;
    j["entity_id"] = port.entity_id;
    j["note"] = port.note;
    return j;
}

}  // namespace

#define PWB_TEST_ASSERT_EQ(a, b, msg)                                                \
    do { const auto& va_ = (a); const auto& vb_ = (b);                               \
         const bool pwb_eq_ = va_ == vb_;                                            \
         if (!pwb_eq_) std::cout << "  FAIL " << (msg) << ": " << va_ << " != " << vb_ << "\n"; \
         ::pwb_test::check(pwb_eq_, #a " == " #b, __FILE__, __LINE__); } while (0)
#define PWB_CASE(name) PWB_TEST(name)

// ---- policy layers ----------------------------------------------------------

PWB_CASE(governance) {
    ensure_init();
    domain::Json out = domain::Json::array();
    for (const auto& row : o("governance_normalize")) {
        domain::Json entry = domain::Json::object();
        entry["key"] = row.at("key");
        entry["value"] = row.at("value");
        auto normalized = normalize_governance_value(
            row.at("key").get<std::string>(), row.at("value"));
        if (normalized.is_ok()) {
            entry["ok"] = normalized.value();
        } else {
            entry["ok"] = nullptr;
            entry["err"] = normalized.error().message;
        }
        out.push_back(entry);
    }
    expect_json("governance_normalize", out, o("governance_normalize"));

    domain::Json bad = domain::Json::object();
    bad["format"] = "x";
    auto patch = normalize_governance_patch(bad);
    PWB_TEST_ASSERT(!patch.is_ok(), "reserved key must be rejected");
    PWB_TEST_ASSERT_EQ(patch.error().message, o("governance_patch_reserved").get<std::string>(),
                       "reserved-key message parity");

    domain::Json metadata = domain::Json::object();
    metadata["source"] = "野外";
    metadata["discipline"] = "seismic";
    metadata["confidence"] = "high";
    metadata["creator"] = "";
    metadata["format"] = "sgy";
    domain::Json rows = domain::Json::array();
    for (const auto& [label, display] : governance_display_rows(metadata)) {
        domain::Json row = domain::Json::array();
        row.push_back(label);
        row.push_back(display);
        rows.push_back(row);
    }
    expect_json("governance_display_rows", rows, o("governance_display_rows"));
    domain::Json keys = domain::Json::array();
    for (const auto& spec : governance_fields()) keys.push_back(spec.key);
    expect_json("governance_keys", keys, o("governance_keys"));
}

PWB_CASE(artifact_policy) {
    ensure_init();
    domain::Json table = domain::Json::object();
    for (const auto& [kind, policy] : known_artifact_policies()) {
        domain::Json row = domain::Json::object();
        row["artifact_class"] = policy->artifact_class;
        row["must_register"] = policy->must_register;
        row["data_stage"] = policy->data_stage.has_value()
                                ? domain::Json(std::string(
                                      domain::to_string(*policy->data_stage)))
                                : domain::Json();
        row["retention_class"] = policy->retention_class;
        row["rationale"] = policy->rationale;
        table[kind] = row;
    }
    expect_json("artifact_policy_table", table, o("artifact_policy_table"));

    const ArtifactPolicy fallback = artifact_policy_for("brand_new_kind");
    domain::Json row = domain::Json::object();
    row["artifact_class"] = fallback.artifact_class;
    row["must_register"] = fallback.must_register;
    row["data_stage"] = domain::Json(std::string(domain::to_string(*fallback.data_stage)));
    row["retention_class"] = fallback.retention_class;
    row["rationale"] = fallback.rationale;
    expect_json("artifact_policy_fallback", row, o("artifact_policy_fallback"));

    domain::Json registered = domain::Json::array();
    registered.push_back(is_registered_artifact_kind("map_product"));
    registered.push_back(is_registered_artifact_kind("brand_new_kind"));
    registered.push_back(is_registered_artifact_kind(" map_product "));
    expect_json("artifact_policy_registered", registered, o("artifact_policy_registered"));
}

PWB_CASE(port_roles) {
    ensure_init();
    domain::Json out = domain::Json::object();
    for (const char* role : {"well_logs", "sonic", "faults", "manual_edit",
                             "foreign_role", ""}) {
        out[role] = port_role_display(role);
    }
    expect_json("port_roles_display", out, o("port_roles_display"));
}

PWB_CASE(model_gates) {
    ensure_init();
    struct Case {
        const char* name;
        const char* provider;
        const char* model_type;
        domain::Json model_metadata;
        bool demo_only;
        domain::Json version_metadata;
        bool has_schema;
        bool require_schema;
        bool error;
    };
    auto obj = []() { return domain::Json::object(); };
    domain::Json sci_false = obj();
    sci_false["scientific"] = false;
    std::vector<Case> cases = {
        {"ok", "pwb", "xgboost", obj(), false, obj(), true, true, false},
        {"demo", "Demo", "xgboost", obj(), false, obj(), false, true, false},
        {"local", "local-asset", "xgboost", obj(), false, obj(), false, true, false},
        {"heuristic", "pwb", "HEURISTIC", obj(), false, obj(), false, true, false},
        {"demo_only", "", "", obj(), true, obj(), false, true, false},
        {"sci_false", "", "", sci_false, false, obj(), false, true, false},
        {"ver_sci_false", "", "", obj(), false, sci_false, false, true, false},
        {"no_schema", "", "", obj(), false, obj(), false, true, false},
        {"no_schema_read", "", "", obj(), false, obj(), false, false, false},
        {"lookup_error", "", "", obj(), false, obj(), false, true, true},
    };
    domain::Json out = domain::Json::array();
    for (const auto& c : cases) {
        ModelGateFacts model;
        model.provider = c.provider;
        model.model_type = c.model_type;
        model.metadata = c.model_metadata;
        ModelVersionGateFacts version;
        version.demo_only = c.demo_only;
        version.metadata = c.version_metadata;
        if (c.has_schema) {
            version.input_schema = obj();
            version.input_schema["curves"] = domain::Json::array();
        }
        std::optional<std::string> error;
        // Python surfaced str(KeyError(...)) — the repr, quoted.
        if (c.error) error = std::string("'get_model failed: no row'");
        auto [ok, reason] = can_promote_to_production(model, version, error,
                                                      c.require_schema);
        domain::Json row = domain::Json::object();
        row["case"] = c.name;
        row["ok"] = ok;
        row["reason"] = reason;
        out.push_back(row);
    }
    expect_json("model_gates", out, o("model_gates"));
}

PWB_CASE(checksum) {
    ensure_init();
    const fs::path payload = write_payload();
    auto digest = sha256_file(payload);
    PWB_TEST_ASSERT(digest.is_ok(), "hash must succeed");
    PWB_TEST_ASSERT_EQ(digest.value(), o("checksum_file").get<std::string>(),
                       "file digest parity");
    auto streamed = sha256_file(payload, 64);
    PWB_TEST_ASSERT_EQ(streamed.value(),
                       o("checksum_file_streamed").get<std::string>(),
                       "chunked digest parity");
    PWB_TEST_ASSERT_EQ(sha256_text("a\r\nb\rc\nd"),
                       o("checksum_text").at(0).get<std::string>(),
                       "text normalization parity");
    PWB_TEST_ASSERT_EQ(sha256_text("国际\r\n化"),
                       o("checksum_text").at(1).get<std::string>(),
                       "UTF-8 text parity");
    // Cancellation: no partial digest ever escapes.
    int polls = 0;
    auto cancelled = sha256_file(payload, 64, [&]() { return ++polls >= 3; });
    PWB_TEST_ASSERT(!cancelled.is_ok(), "cancelled hash must error");
    PWB_TEST_ASSERT_EQ(cancelled.error().message,
                       "hash cancelled: " + payload.string(), "cancel text parity");
}

// ---- document graph services ---------------------------------------------------

PWB_CASE(lineage) {
    ensure_init();
    CatalogDocument doc = build_document();
    DocumentIndex index(doc);
    auto summaries = compute_lineage_summaries(doc, index);
    domain::Json out = domain::Json::object();
    for (const auto& [id, summary] : summaries) {
        domain::Json row = domain::Json::object();
        row["to_raw"] = summary.to_raw.has_value() ? domain::Json(*summary.to_raw)
                                                   : domain::Json();
        row["broken"] = summary.broken;
        row["has_parents"] = summary.has_parents;
        out[id] = row;
    }
    expect_json("lineage_summaries", out, o("lineage_summaries"));

    auto chain = build_lineage_chain(doc, index, "ver_e4", "ancestors");
    PWB_TEST_ASSERT(chain.is_ok(), "chain must build");
    std::function<domain::Json(const LineageChainNode&)> node_json =
        [&](const LineageChainNode& node) {
            domain::Json j = domain::Json::object();
            j["version_id"] = node.version_id;
            j["asset_name"] = node.asset_name;
            j["depth"] = node.depth;
            domain::Json tags = domain::Json::array();
            for (const auto& tag : node.tags) tags.push_back(tag);
            j["tags"] = tags;
            j["run_operation"] = node.run_operation.has_value()
                                     ? domain::Json(*node.run_operation)
                                     : domain::Json();
            domain::Json children = domain::Json::array();
            for (const auto& child : node.children) children.push_back(node_json(child));
            j["children"] = children;
            return j;
        };
    domain::Json chain_json = domain::Json::object();
    chain_json["node_count"] = chain.value().node_count;
    chain_json["truncated"] = chain.value().truncated;
    chain_json["root"] = node_json(chain.value().root);
    expect_json("lineage_chain_ver_e4", chain_json, o("lineage_chain_ver_e4"));

    auto bad = build_lineage_chain(doc, index, "ver_e4", "sideways");
    PWB_TEST_ASSERT(!bad.is_ok(), "bad direction must error");
    PWB_TEST_ASSERT_EQ(bad.error().message,
                       o("lineage_bad_direction").get<std::string>(),
                       "bad-direction text parity");
}

PWB_CASE(impact) {
    ensure_init();
    CatalogDocument doc = build_document();
    DocumentIndex index(doc);
    ImpactService service(doc, index);
    auto stale_json = [](const std::vector<StaleItem>& items) {
        domain::Json out = domain::Json::array();
        for (const auto& i : items) {
            domain::Json row = domain::Json::object();
            row["version_id"] = i.version_id;
            row["direct"] = i.direct;
            domain::Json nearest = domain::Json::array();
            if (i.nearest_changed_ancestor.has_value()) {
                nearest.push_back(std::get<0>(*i.nearest_changed_ancestor));
                nearest.push_back(std::get<1>(*i.nearest_changed_ancestor));
                nearest.push_back(std::get<2>(*i.nearest_changed_ancestor));
            }
            row["nearest"] = nearest;
            row["reason"] = i.reason;
            row["pinned"] = i.pinned;
            row["classification"] = i.classification();
            row["reproducible"] = i.reproducible;
            row["stage"] = i.stage;
            out.push_back(row);
        }
        return out;
    };
    expect_json("impact_downstream", stale_json(service.downstream_stale()),
                o("impact_downstream"));
    expect_json("impact_downstream_trashed",
                stale_json(service.downstream_stale(std::nullopt, true)),
                o("impact_downstream_trashed"));
    auto [stale, reason] = service.is_stale("ver_d3");
    domain::Json is_stale_json = domain::Json::array();
    is_stale_json.push_back(stale);
    is_stale_json.push_back(reason);
    expect_json("impact_is_stale", is_stale_json, o("impact_is_stale"));

    UpstreamImpact up = service.upstream_impact("ver_e4");
    domain::Json up_json = domain::Json::object();
    auto ids_json = [](const std::vector<std::string>& ids) {
        domain::Json out = domain::Json::array();
        for (const auto& id : ids) out.push_back(id);
        return out;
    };
    up_json["ancestor_version_ids"] = ids_json(up.ancestor_version_ids);
    up_json["ancestor_asset_ids"] = ids_json(up.ancestor_asset_ids);
    up_json["runs_involved"] = ids_json(up.runs_involved);
    up_json["missing_ancestors"] = ids_json(up.missing_ancestors);
    up_json["trashed_ancestors"] = ids_json(up.trashed_ancestors);
    expect_json("impact_upstream", up_json, o("impact_upstream"));

    DeleteImpact del = service.delete_impact("ver_a1");
    domain::Json del_json = domain::Json::object();
    del_json["target_version_ids"] = ids_json(del.target_version_ids);
    del_json["target_asset_ids"] = ids_json(del.target_asset_ids);
    del_json["broken_lineage_edges"] = del.broken_lineage_edges;
    del_json["runs_consuming"] = ids_json(del.runs_consuming);
    del_json["runs_producing"] = ids_json(del.runs_producing);
    del_json["live_descendants"] = stale_json(del.live_descendants);
    del_json["cascade_advice"] = ids_json(del.cascade_advice);
    expect_json("impact_delete", del_json, o("impact_delete"));
}

PWB_CASE(v11_policy) {
    ensure_init();
    CatalogDocument doc = build_document();
    DocumentIndex index(doc);
    RunPortsView ports = ports_for_run(doc.runs[0]);
    domain::Json ports_json = domain::Json::object();
    domain::Json inputs = domain::Json::array();
    for (const auto& port : ports.input) inputs.push_back(run_port_json(port));
    domain::Json outputs = domain::Json::array();
    for (const auto& port : ports.output) outputs.push_back(run_port_json(port));
    ports_json["input"] = inputs;
    ports_json["output"] = outputs;
    expect_json("v11_ports_for_run", ports_json, o("v11_ports_for_run"));

    auto eligibility_json = [](const CleanupEligibility& e) {
        domain::Json j = domain::Json::object();
        j["version_id"] = e.version_id;
        j["eligible"] = e.eligible;
        domain::Json blockers = domain::Json::array();
        for (const auto& b : e.blockers) blockers.push_back(b);
        j["blockers"] = blockers;
        j["retention_class"] = e.retention_class;
        j["downstream_count"] = e.downstream_count;
        return j;
    };
    expect_json("v11_eligibility_ver_d3",
                eligibility_json(cleanup_eligibility(doc, index, "ver_d3", false)),
                o("v11_eligibility_ver_d3"));
    expect_json("v11_eligibility_ver_e4",
                eligibility_json(cleanup_eligibility(doc, index, "ver_e4", false)),
                o("v11_eligibility_ver_e4"));
    expect_json("v11_lifecycle_ver_e4",
                version_lifecycle_status(doc, index, "ver_e4", false),
                o("v11_lifecycle_ver_e4"));
    domain::Json retention = domain::Json::array();
    for (const char* id : {"ver_a1", "ver_d3", "ver_e4"}) {
        retention.push_back(retention_class_of(*index.version(id)));
    }
    expect_json("v11_retention", retention, o("v11_retention"));

    PortBackfillCounts counts = migrate_run_ports(&doc, index);
    domain::Json migrate_json = domain::Json::object();
    migrate_json["runs_annotated"] = counts.runs_annotated;
    migrate_json["ports_added"] = counts.ports_added;
    expect_json("v11_migrate_ports", migrate_json, o("v11_migrate_ports"));
    domain::Json after = domain::Json::array();
    for (const auto& port : doc.runs[0].output_ports) {
        after.push_back(run_port_json(port));
    }
    expect_json("v11_ports_after_backfill", after, o("v11_ports_after_backfill"));

    // apply_run_ports invariant: ports stay ⊆ flat lists, budget enforced.
    DataRun probe = doc.runs[0];
    RunPort unknown;
    unknown.role = "sonic";
    unknown.version_id = domain::VersionId(std::string("ver_nope"));
        std::vector<RunPort> unknown_list{unknown};
    domain::DataError error = apply_run_ports(&probe, &index, unknown_list, std::nullopt);
    PWB_TEST_ASSERT(!error.ok(), "unknown port version must be rejected");
    PWB_TEST_ASSERT_EQ(error.message, "Port references unknown version ver_nope",
                       "port validation message parity");
    std::vector<RunPort> ok_ports = doc.runs[0].input_ports;
    error = apply_run_ports(&probe, &index, ok_ports, std::nullopt);
    PWB_TEST_ASSERT(error.ok(), "valid ports must apply");
}

PWB_CASE(queries_and_sources) {
    ensure_init();
    CatalogDocument doc = build_document();
    DocumentIndex index(doc);
    domain::Json found = domain::Json::array();
    for (const auto& id : find_assets_by_tag(doc, "QC")) found.push_back(id);
    expect_json("queries_find_assets_by_tag", found, o("queries_find_assets_by_tag"));

    IntegrityReport integrity = verify_integrity(
        doc, "ver_b5",
        [&](const DataVersion&) { return fs::path(rooted("{ROOT}/gone.las")); });
    domain::Json statuses = domain::Json::object();
    for (const auto& [id, status] : integrity.statuses) statuses[id] = status;
    expect_json("queries_integrity_ver_b5", statuses, o("queries_integrity_ver_b5"));

    const fs::path project = g_root / "demo.paleo.json";
    MissingSourceReport report = find_missing_sources(doc, index, project);
    domain::Json entries = domain::Json::array();
    for (const auto& e : report.entries) {
        domain::Json row = domain::Json::object();
        row["version_id"] = e.version_id;
        row["relinkable"] = e.relinkable;
        row["recorded_path"] = rooted(e.recorded_path);
        row["scanned"] = report.scanned;
        entries.push_back(row);
    }
    domain::Json sources_expected = o("sources_missing");
    for (auto& row : sources_expected) {
        row["recorded_path"] = rooted(row["recorded_path"].get<std::string>());
    }
    expect_json("sources_missing", entries, sources_expected);

    // Relink fail-closed proof: a stranger with the right basename refuses.
    const fs::path stranger = g_root / "gone.las";
    { std::ofstream out(stranger); out << "not the same data"; }
    auto proof = relink_identity_proof(*index.version("ver_b5"), stranger);
    PWB_TEST_ASSERT(!proof.has_value(), "stranger must not pass identity proof");
    std::error_code cleanup_ec;
    fs::remove(stranger, cleanup_ec);  // keep the later audit scenario pristine
}

PWB_CASE(tags) {
    ensure_init();
    CatalogDocument doc = build_document();
    DocumentIndex index(doc);
    TagStore store(&doc, [] { return domain::DataError(domain::ErrorCode::Ok, ""); });

    auto added = store.add_tag("  实验  Zone ", "asset_b", std::nullopt);
    PWB_TEST_ASSERT(added.is_ok(), "add_tag must succeed");
    domain::Json add_json = domain::Json::object();
    add_json["name"] = added.value().name;
    add_json["display"] = added.value().display_name;
    // id is a generated uuid on both sides — name/display are the contract.
    expect_json("tags_add", add_json,
                [&] {
                    domain::Json expected = o("tags_add");
                    expected.erase("id");
                    return expected;
                }());

    PWB_TEST_ASSERT(store.bulk_add_tag("batch", {}, {"ver_a1", "ver_b5"}).is_ok(),
                    "bulk add must succeed");
    auto renamed = store.rename_tag("qc", "quality control");
    PWB_TEST_ASSERT(renamed.is_ok(), "rename must succeed");

    domain::Json usage = domain::Json::object();
    for (const auto& [id, entry] : store.tag_usage()) {
        domain::Json pair = domain::Json::array();
        pair.push_back(entry["assets"]);
        pair.push_back(entry["versions"]);
        usage[entry["name"].get<std::string>()] = pair;
    }
    expect_json("tags_usage_names", usage, o("tags_usage_names"));

    PWB_TEST_ASSERT(store.bulk_remove_tag("batch", {}, {"ver_a1"}).ok(),
                    "bulk remove must succeed");
    domain::Json pruned = domain::Json::array();
    for (const auto& tag : store.prune_unused_tags()) pruned.push_back(tag.name);
    expect_json("tags_pruned", pruned, o("tags_pruned"));

    domain::Json search = domain::Json::array();
    for (const auto& tag : store.search_tags("qua")) search.push_back(tag.name);
    expect_json("tags_search", search, o("tags_search"));

    // Journaled rollback: a failing save hook restores the pre-call state.
    CatalogDocument rollback_doc = build_document();
    TagStore failing(&rollback_doc, [] {
        return domain::DataError(domain::ErrorCode::IoError, "boom");
    });
    const std::size_t tags_before = rollback_doc.tags.size();
    const std::size_t assoc_before = rollback_doc.asset_tags.size();
    auto failed = failing.add_tag("rollback", "asset_a", std::nullopt);
    PWB_TEST_ASSERT(!failed.is_ok(), "failed save must propagate");
    PWB_TEST_ASSERT_EQ(rollback_doc.tags.size(), tags_before,
                       "created tag must be rolled back");
    PWB_TEST_ASSERT_EQ(rollback_doc.asset_tags.size(), assoc_before,
                       "association must be rolled back");
}

PWB_CASE(migration) {
    ensure_init();
    const fs::path project = g_root / "demo.paleo.json";
    fs::create_directories(g_root / "data");
    { std::ofstream out(g_root / "data" / "old.sgy", std::ios::binary); out << "legacy"; }

    std::vector<LegacyResourceRow> legacy;
    {
        LegacyResourceRow row;
        row.id = "res_1";
        row.name = "Old seismic";
        row.type = "seismic";
        row.path = "data/old.sgy";
        row.format = "sgy";
        row.tags = {"legacy"};
        row.parsed_summary = domain::Json::object();
        row.parsed_summary["path"] = (g_root / "old.sgy").string();
        row.status = "active";
        legacy.push_back(row);
    }
    {
        LegacyResourceRow row;
        row.id = "asset_a";  // already present → skipped
        row.name = "dup";
        legacy.push_back(row);
    }
    {
        LegacyResourceRow row;
        row.id = "../evil";  // unsafe id → sanitized asset id
        row.name = "evil";
        row.type = "x";
        row.path = "y";  // relative + missing → not-found warning
        legacy.push_back(row);
    }

    CatalogDocument doc;
    DataAsset existing;
    existing.id = domain::AssetId(std::string("asset_a"));
    existing.name = "Seismic A";
    existing.type = "seismic";
    doc.assets.push_back(std::move(existing));

    std::string stamp = "2024-02-01T00:00:00+00:00";
    MigrationReport report = migrate_resources(legacy, project, &doc,
                                               [&] { return stamp; });
    domain::Json out = domain::Json::object();
    out["migrated"] = report.migrated_count;
    out["skipped"] = report.skipped_count;
    // Both sides warn about ../evil twice (not found + sanitized id); the
    // sanitized warning embeds a random asset id — masked on both sides.
    auto mask_ids = [](std::string text) {
        static const std::regex generated("asset_[0-9a-f]+");
        return std::regex_replace(text, generated, "asset_<generated>");
    };
    domain::Json warnings = domain::Json::array();
    for (const auto& warning : report.warnings) {
        warnings.push_back(mask_ids(rooted(warning)));
    }
    const std::size_t warning_count = warnings.size();
    out["warnings"] = warnings;
    domain::Json versions = domain::Json::array();
    domain::Json assets = domain::Json::array();
    for (const auto& version : doc.versions) {
        if (version.asset_id == domain::AssetId(std::string("asset_a"))) continue;
        domain::Json row = domain::Json::object();
        row["id"] = version.id.str();
        row["asset"] = version.asset_id.str();
        row["managed"] = version.managed;
        row["path"] = rooted(version.path);
        row["stage"] = std::string(domain::to_string(version.stage));
        row["has_stat"] = version.metadata.is_object() &&
                          version.metadata.contains("external_stat");
        versions.push_back(row);
    }
    for (const auto& asset : doc.assets) {
        if (asset.id == domain::AssetId(std::string("asset_a"))) continue;
        domain::Json row = domain::Json::object();
        row["id"] = asset.id.str();
        row["legacy"] = asset.legacy_resource_id.value_or("");
        assets.push_back(row);
    }
    out["versions"] = versions;
    out["assets"] = assets;
    domain::Json expected = o("migration");
    for (auto& row : expected["warnings"]) {
        row = mask_ids(rooted(row.get<std::string>()));
    }
    for (auto& row : expected["versions"]) {
        row["path"] = rooted(row["path"].get<std::string>());
        row["id"] = mask_ids(row["id"].get<std::string>());
        row["asset"] = mask_ids(row["asset"].get<std::string>());
    }
    PWB_TEST_ASSERT_EQ(warning_count, expected.at("warnings").size(),
                       "warning count parity");
    for (auto& row : expected["assets"]) {
        row["id"] = mask_ids(row["id"].get<std::string>());
    }
    for (auto& row : out["assets"]) {
        row["id"] = mask_ids(row["id"].get<std::string>());
    }
    for (auto& row : out["versions"]) {
        row["id"] = mask_ids(row["id"].get<std::string>());
        row["asset"] = mask_ids(row["asset"].get<std::string>());
    }
    expect_json("migration", out, expected);
}

PWB_CASE(audit_and_explain) {
    ensure_init();
    CatalogDocument doc = build_document();
    DocumentIndex index(doc);
    TagStore store(&doc, [] { return domain::DataError(domain::ErrorCode::Ok, ""); });
    PWB_TEST_ASSERT(store.add_tag("  实验  Zone ", "asset_b", std::nullopt).is_ok(),
                    "setup add");
    PWB_TEST_ASSERT(store.bulk_add_tag("batch", {}, {"ver_a1", "ver_b5"}).is_ok(),
                    "setup bulk");
    PWB_TEST_ASSERT(store.rename_tag("qc", "quality control").is_ok(), "setup rename");
    PWB_TEST_ASSERT(store.bulk_remove_tag("batch", {}, {"ver_a1"}).ok(), "setup remove");
    store.prune_unused_tags();
    DocumentIndex index2(doc);
    migrate_run_ports(&doc, index2);

    const fs::path project = g_root / "demo.paleo.json";
    AuditContext context;
    context.document = &doc;
    context.index = &index2;
    context.project_path = project;
    context.resolve_path = [&](const DataVersion& v) {
        fs::path raw(v.path);
        if (raw.is_absolute()) return raw;
        return g_root / raw;
    };
    DocumentIndex index3(doc);
    context.index = &index3;
    AuditReport report = audit_catalog(context, false);
    domain::Json out = domain::Json::object();
    out["checked"] = report.checked;
    domain::Json issues = domain::Json::array();
    for (const auto& issue : report.issues) {
        domain::Json row = domain::Json::object();
        row["kind"] = issue.kind;
        row["severity"] = issue.severity;
        row["ref_id"] = issue.ref_id;
        row["detail"] = rooted(issue.detail);
        issues.push_back(row);
    }
    out["issues"] = issues;
    out["ok"] = report.ok();
    domain::Json expected = o("audit");
    for (auto& row : expected["issues"]) {
        row["detail"] = rooted(row["detail"].get<std::string>());
    }
    expect_json("audit", out, expected);

    ExplainService explain(doc, index3);
    auto explanation = explain.explain_version("ver_e4");
    PWB_TEST_ASSERT(explanation.is_ok(), "explain must succeed");
    domain::Json explain_expected = o("explain_ver_e4");
    explain_expected.erase("asset_name");
    domain::Json actual = explanation.value().to_dict();
    actual.erase("asset_name");
    expect_json("explain_ver_e4", actual, explain_expected);
}

PWB_CASE(negative_self_check) {
    ensure_init();
    // A tampered oracle value MUST be detected by the same comparator the
    // replays use (5 independent tamper points).
    CatalogDocument doc = build_document();
    DocumentIndex index(doc);
    auto summaries = compute_lineage_summaries(doc, index);
    domain::Json out = domain::Json::object();
    for (const auto& [id, summary] : summaries) {
        domain::Json row = domain::Json::object();
        row["to_raw"] = summary.to_raw.has_value() ? domain::Json(*summary.to_raw)
                                                   : domain::Json();
        row["broken"] = summary.broken;
        row["has_parents"] = summary.has_parents;
        out[id] = row;
    }
    domain::Json tampered = o("lineage_summaries");
    tampered["ver_d3"]["to_raw"] = 99;
    PWB_TEST_ASSERT(::pwb_test::json_compare(tampered, out).has_value(),
                    "tampered to_raw must be detected");
    tampered = o("lineage_summaries");
    tampered["ver_d3"]["broken"] = false;
    PWB_TEST_ASSERT(::pwb_test::json_compare(tampered, out).has_value(),
                    "tampered broken flag must be detected");
    tampered = o("lineage_summaries");
    tampered["ver_d3"].erase("has_parents");
    PWB_TEST_ASSERT(::pwb_test::json_compare(tampered, out).has_value(),
                    "dropped key must be detected");
    tampered = o("lineage_summaries");
    tampered["ver_d3"]["to_raw"] = 1.0;  // int vs float is a TYPE difference
    PWB_TEST_ASSERT(::pwb_test::json_compare(tampered, out).has_value(),
                    "type difference must be detected");
    tampered = o("lineage_summaries");
    tampered["ver_ghost"] = tampered["ver_d3"];
    PWB_TEST_ASSERT(::pwb_test::json_compare(tampered, out).has_value(),
                    "extra key must be detected");
}
