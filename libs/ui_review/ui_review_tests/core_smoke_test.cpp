// UI-11 — core smoke test (Qt-free): exercises every Qt-free semantic
// core of the review/governance slice against hand-built DTOs — lineage
// expansion (run interleave, cycles, broken links, caps), impact
// fail-closed counting, audit/relink summaries, version view + action
// gates, QC issue rows, contract lines, ingest columns, review flow
// texts, composite layer mutations, advisor html.

#include <pwb/catalog/impact.hpp>
#include <pwb/catalog/models.hpp>
#include <pwb/domain/stage.hpp>
#include <pwb/ui_review/advisor_html.hpp>
#include <pwb/ui_review/audit_summary.hpp>
#include <pwb/ui_review/composite_layers.hpp>
#include <pwb/ui_review/contract_lines.hpp>
#include <pwb/ui_review/impact_markdown.hpp>
#include <pwb/ui_review/ingest_columns.hpp>
#include <pwb/ui_review/lineage_expand.hpp>
#include <pwb/ui_review/qc_issue_rows.hpp>
#include <pwb/ui_review/relink_summary.hpp>
#include <pwb/ui_review/review_core.hpp>
#include <pwb/ui_review/version_view.hpp>

#include <stdexcept>
#include <string>
#include <vector>

#include "ui_review_test.hpp"

using namespace pwb;
using namespace pwb::ui_review;

namespace {

catalog::DataVersion make_version(const std::string& id,
                                  const std::string& asset_id, int number,
                                  domain::DataStage stage =
                                      domain::DataStage::Raw) {
    catalog::DataVersion v;
    v.id = domain::VersionId{id};
    v.asset_id = domain::AssetId{asset_id};
    v.version_number = number;
    v.stage = stage;
    v.path = "raw/wells/x.csv";
    v.format = "csv";
    v.created_at = "2025-01-02T03:04:05";
    return v;
}

std::string asset_name_of(const std::string& asset_id) {
    return "asset-" + asset_id;
}

struct FakeDeleteImpact : IDeleteImpact {
    catalog::DeleteImpact next;
    bool throw_on_call = false;
    int calls = 0;
    catalog::DeleteImpact
    delete_impact(const std::string& /*asset_id*/) override {
        ++calls;
        if (throw_on_call) {
            throw std::runtime_error("catalog gone");
        }
        return next;
    }
};

struct FakeMapUsage : IMapUsageSource {
    std::vector<std::pair<std::string, std::string>> usages;
    std::vector<std::pair<std::string, std::string>>
    usages_of_asset(const std::string& /*asset_id*/) override {
        return usages;
    }
};

}  // namespace

// ---- lineage_expand ---------------------------------------------------------

PWB_TEST(lineage_expand_inputs_interleaves_run) {
    LineageHop hop;
    hop.version = make_version("ver_child0001", "ast_child", 3,
                               domain::DataStage::Derived);
    catalog::DataRun run;
    run.id = domain::RunId{std::string("run_0000000001")};
    run.operation = "factor_interpolation";
    hop.run = run;
    hop.parents.push_back(
        make_version("ver_parent0001", "ast_parent", 1));
    // Python iterates version.parent_version_ids and resolves each id
    // against lineage["parents"] — the id list drives the rows.
    hop.version.parent_version_ids.push_back(
        domain::VersionId{std::string("ver_parent0001")});

    const auto specs =
        expand_inputs(&hop, {"ver_child0001"}, asset_name_of);
    // Run node first, then the parent version row beneath it.
    CHECK(specs.size() >= 2);
    CHECK(specs[0].kind == LineageNodeSpec::Kind::Run);
    CHECK(specs[0].run_id == "run_0000000001");
    CHECK(specs[1].kind == LineageNodeSpec::Kind::Version);
    CHECK(specs[1].version_id == "ver_parent0001");
    CHECK(specs[1].direction == "up");
    CHECK(specs[1].lazy);
}

PWB_TEST(lineage_expand_cycle_and_terminal_notes) {
    // Cycle: the parent id is already on the ancestor path.
    LineageHop hop;
    hop.version = make_version("ver_a", "ast_a", 1);
    hop.parents.push_back(make_version("ver_a", "ast_a", 1));
    hop.version.parent_version_ids.push_back(
        domain::VersionId{std::string("ver_a")});
    const auto specs = expand_inputs(&hop, {"ver_a"}, asset_name_of);
    bool saw_cycle = false;
    for (const auto& spec : specs) {
        if (spec.kind == LineageNodeSpec::Kind::Note &&
            spec.label.find("↺") != std::string::npos) {
            saw_cycle = true;
        }
    }
    CHECK(saw_cycle);

    // Empty parents → terminal "no upstream" note.
    LineageHop leaf;
    leaf.version = make_version("ver_root", "ast_root", 1);
    const auto leaf_specs =
        expand_inputs(&leaf, {"ver_root"}, asset_name_of);
    bool saw_terminal = false;
    for (const auto& spec : leaf_specs) {
        if (spec.kind == LineageNodeSpec::Kind::Note &&
            spec.label.find("无上游") != std::string::npos) {
            saw_terminal = true;
        }
    }
    CHECK(saw_terminal);

    // No children → terminal "no downstream" note on expand_outputs.
    const auto down_specs =
        expand_outputs(&leaf, {"ver_root"}, asset_name_of);
    bool saw_down_terminal = false;
    for (const auto& spec : down_specs) {
        if (spec.kind == LineageNodeSpec::Kind::Note &&
            spec.label.find("无下游") != std::string::npos) {
            saw_down_terminal = true;
        }
    }
    CHECK(saw_down_terminal);
}

PWB_TEST(lineage_expand_null_hop_and_overflow) {
    // hop == nullptr → the single "无法读取血缘" note.
    const auto null_specs =
        expand_inputs(nullptr, {"ver_x"}, asset_name_of);
    CHECK_EQ(null_specs.size(), 1);
    CHECK(null_specs[0].label.find("无法读取血缘") != std::string::npos);

    // More than kMaxChildrenPerNode children → bounded + overflow row.
    LineageHop hop;
    hop.version = make_version("ver_hub", "ast_hub", 1);
    for (int i = 0; i < kMaxChildrenPerNode + 5; ++i) {
        hop.children.push_back(make_version(
            "ver_c" + std::to_string(i), "ast_c" + std::to_string(i), 1,
            domain::DataStage::Derived));
    }
    const auto specs =
        expand_outputs(&hop, {"ver_hub"}, asset_name_of);
    bool saw_overflow = false;
    int versions = 0;
    for (const auto& spec : specs) {
        if (spec.kind == LineageNodeSpec::Kind::Version) {
            ++versions;
        }
        if (spec.kind == LineageNodeSpec::Kind::Overflow) {
            saw_overflow = true;
            CHECK(spec.disabled);
        }
    }
    CHECK(saw_overflow);
    CHECK(versions <= kMaxChildrenPerNode);
}

PWB_TEST(lineage_labels_and_cards) {
    const auto v = make_version("ver_abcdef123456789", "ast_a", 2,
                                domain::DataStage::Intermediate);
    const std::string label = version_item_label(v, "well-x");
    CHECK(label.find("v2") != std::string::npos);
    CHECK(label.find("well-x") != std::string::npos);
    // short id is 12 chars.
    CHECK(label.find("ver_abcdef12") != std::string::npos);
    CHECK(label.find("ver_abcdef1234567") == std::string::npos);

    const auto cur = current_item_spec(v, "well-x");
    CHECK(cur.kind == LineageNodeSpec::Kind::Version);
    CHECK(cur.direction.empty());
    CHECK(!cur.lazy);
    CHECK(cur.label.find("当前") != std::string::npos);

    const auto up = branch_spec("up", "ver_x");
    CHECK(up.kind == LineageNodeSpec::Kind::Branch);
    CHECK(up.lazy);
    CHECK(!up.selectable);

    const auto card = summary_card_text(v, "well-x", false);
    CHECK(card.path.find("缺失") != std::string::npos);

    catalog::DataRun run;
    run.id = domain::RunId{std::string("run_9")};
    run.operation = "map_qc";
    const auto run_card = run_card_text(&run);
    CHECK(run_card.has_run);
    CHECK(run_card.title.find("map_qc") != std::string::npos);
    const auto no_run = run_card_text(nullptr);
    CHECK(!no_run.has_run);
    CHECK(no_run.title.find("无生成运行") != std::string::npos);
}

// ---- impact_markdown ----------------------------------------------------------

PWB_TEST(impact_collect_counts_and_fail_closed) {
    FakeDeleteImpact impact;
    catalog::StaleItem stale;
    stale.version_id = "ver_d1";
    stale.asset_id = "ast_d1";
    stale.direct = true;
    impact.next.live_descendants.push_back(stale);
    impact.next.runs_consuming.push_back("run_x");
    impact.next.broken_lineage_edges = 2;
    impact.next.cascade_advice.push_back("advice-a");
    FakeMapUsage usage;
    usage.usages = {{"layer", "图层 A"}, {"print", "打印 B"}};

    const auto summary =
        collect_trash_impact(impact, &usage, {"ast_1", "ast_2"});
    CHECK_EQ(impact.calls, 2);
    CHECK_EQ(summary.descendant_count, 2);
    CHECK_EQ(summary.runs_consuming.size(), 2);
    CHECK_EQ(summary.broken_edges, 4);
    CHECK_EQ(summary.cascade_advice.size(), 2);
    CHECK_EQ(summary.map_usages.size(), 4);
    CHECK_EQ(summary.computation_errors, 0);
    CHECK(summary.has_downstream());

    const std::string md = summary.render_markdown();
    CHECK(md.find("下游") != std::string::npos);
    CHECK(md.find("图层 A") != std::string::npos);

    // Fail-closed: a throwing impact hop counts as computation_errors and
    // STILL forces the downstream-confirmation contract.
    FakeDeleteImpact broken;
    broken.throw_on_call = true;
    const auto failed = collect_trash_impact(broken, nullptr, {"ast_1"});
    CHECK_EQ(failed.computation_errors, 1);
    CHECK(failed.has_downstream());
    CHECK(failed.render_markdown().find("失败") != std::string::npos);
}

// ---- audit_summary ------------------------------------------------------------

PWB_TEST(audit_summary_ordering_and_text) {
    catalog::AuditReport report;
    report.checked["versions"] = 10;
    report.issues.push_back(
        catalog::AuditIssue{"missing_payload", "low", "v1", "d1"});
    report.issues.push_back(
        catalog::AuditIssue{"broken_edge", "high", "v2", "d2"});
    report.issues.push_back(
        catalog::AuditIssue{"stale_link", "medium", "v3", "d3"});

    const auto sorted = audit_issues_sorted(report.issues);
    CHECK_EQ(sorted.size(), 3);
    CHECK_EQ(sorted[0].severity, "high");
    CHECK_EQ(sorted[1].severity, "medium");
    CHECK_EQ(sorted[2].severity, "low");

    CHECK_EQ(std::string(audit_severity_label("high")), "高");
    CHECK_EQ(std::string(audit_severity_label("medium")), "中");
    CHECK_EQ(std::string(audit_severity_label("low")), "低");

    const std::string line = audit_summary_line(report);
    CHECK(!line.empty());
    CHECK_EQ(std::string(audit_verdict(false)),
             std::string("⚠️ 发现需要处理的健康问题"));
    CHECK_EQ(std::string(audit_verdict(true)),
             std::string("✅ 目录结构健康（低级别问题仅供参考）"));
}

// ---- qc_issue_rows ------------------------------------------------------------

PWB_TEST(qc_issue_rows_from_report) {
    const domain::Json rules = domain::Json::array(
        {"边界完整性", "未知规则X"});
    const domain::Json issues = domain::Json::array({
        domain::Json{{"rule", "边界完整性"},
                     {"severity", "error"},
                     {"message", "缺口 3 处"},
                     {"feature_id", "f-1"},
                     // Non-empty geometry — Python truthiness: an empty
                     // dict is NOT spatial (issue.get("geometry") falsy).
                     {"geometry",
                      domain::Json{{"type", "Point"},
                                   {"coordinates",
                                    domain::Json::array({105.0, 32.0})}}}},
        domain::Json{{"rule", "未知规则X"},
                     {"severity", "warning"},
                     {"message", "提示"},
                     {"ref", "well-9"}},
    });
    const auto rows = qc_issue_rows(rules, issues);
    CHECK_EQ(rows.size(), 2);
    CHECK_EQ(rows[0].rule, "边界完整性");
    CHECK_EQ(rows[0].severity, "error");
    CHECK(rows[0].location.find("f-1") != std::string::npos);
    CHECK_EQ(rows[1].severity, "warning");
    // Spatial filter: only the geometry-carrying issue is locatable.
    const auto spatial = spatial_issues_of(issues);
    CHECK_EQ(spatial.size(), 1);
    const auto by_rule = spatial_issues_by_rule(issues);
    CHECK_EQ(by_rule.at("边界完整性").size(), 1);
}

// ---- relink_summary ------------------------------------------------------------

PWB_TEST(relink_summary_text) {
    catalog::MissingSource entry;
    entry.relinkable = true;
    entry.managed = false;
    entry.stage = domain::DataStage::Raw;
    CHECK_EQ(relink_entry_status(entry), "可重链接");
    entry.relinkable = false;
    entry.managed = false;
    CHECK_EQ(relink_entry_status(entry), "不支持重链接");
    entry.managed = true;
    CHECK_EQ(relink_entry_status(entry), "需重新导入");

    const std::string none = relink_scan_summary(12, 0, 0);
    CHECK(none.find("未发现缺失源") != std::string::npos);
    const std::string some = relink_scan_summary(12, 3, 2);
    CHECK(some.find("缺失 3") != std::string::npos);
    CHECK(some.find("2") != std::string::npos);

    RelinkBatchResult ok;
    ok.ok = 2;
    CHECK(relink_result_message(ok).find("成功重链接 2") !=
          std::string::npos);
    RelinkBatchResult mixed;
    mixed.ok = 1;
    mixed.reasons.push_back("well-a: 身份无法证明");
    const std::string mixed_msg = relink_result_message(mixed);
    CHECK(mixed_msg.find("成功重链接 1") != std::string::npos);
    CHECK(mixed_msg.find("拒绝 1") != std::string::npos);
    CHECK(mixed_msg.find("well-a") != std::string::npos);
    // Python does not special-case "cancelled" in the result message —
    // the flag lives in the result dict but the text stays
    // "成功重链接 {ok} 个".
    RelinkBatchResult cancelled;
    cancelled.cancelled = true;
    CHECK(relink_result_message(cancelled).find("成功重链接 0 个") !=
          std::string::npos);
}

// ---- version_view ----------------------------------------------------------------

PWB_TEST(version_view_text_and_gates) {
    auto v = make_version("ver_abcdef123456", "ast_a", 4,
                          domain::DataStage::Output);
    // _STAGE_DISPLAY shows the enum token, not the Chinese stage_label.
    CHECK_EQ(stage_display(v), "OUTPUT");
    v.trashed = true;
    CHECK_EQ(stage_display(v), "已删除");

    CHECK_EQ(checksum_display(std::nullopt), "—");
    CHECK_EQ(checksum_display(std::string("abcdef0123456789zz")),
             "abcdef012345");
    CHECK_EQ(short_id(std::nullopt), "—");
    CHECK_EQ(short_id(std::string("ver_abcdef123456")), "ver_abcdef12");

    CHECK_EQ(version_cell(v, "ver_abcdef123456"), "v4（当前）");
    CHECK_EQ(version_cell(v, "ver_other"), "v4");

    catalog::DataAsset asset;
    asset.id = domain::AssetId{std::string("ast_a")};
    asset.name = "well-a";
    const auto header = workbench_header_text(asset, 4);
    CHECK(header.find("well-a") != std::string::npos);
    CHECK_EQ(workbench_count_text(3), "共 3 个版本");

    // Action gates: single non-trashed → promote+trash; trashed → restore;
    // two rows → compare; payload → open.
    auto gate = version_action_gate(1, false, true);
    CHECK(gate.promote && gate.trash && gate.open);
    CHECK(!gate.restore && !gate.compare);
    gate = version_action_gate(1, true, false);
    CHECK(gate.restore && !gate.promote && !gate.trash);
    gate = version_action_gate(2, false, false);
    CHECK(gate.compare && !gate.promote && !gate.trash);
    gate = version_action_gate(0, false, false);
    CHECK(!gate.promote && !gate.trash && !gate.restore && !gate.compare &&
          !gate.open);

    // Detail text — resolved path vs missing payload.
    v.trashed = false;
    LineageHop hop;
    hop.version = v;
    catalog::DataRun run;
    run.id = domain::RunId{std::string("run_1")};
    run.operation = "qc";
    hop.run = run;
    ResolvedPath resolved{"/tmp/x.csv", true};
    const auto detail = version_detail_text(&v, &hop, resolved);
    CHECK(detail.title.find("v4") != std::string::npos);
    CHECK(detail.run.find("qc") != std::string::npos);
    CHECK(detail.resolved.find("/tmp/x.csv") != std::string::npos);
    const auto missing =
        version_detail_text(&v, &hop, ResolvedPath{"/tmp/x.csv", false});
    CHECK(missing.resolved.find("缺失") != std::string::npos);

    // Compare rows — differing fields flagged.
    auto older = v;
    older.version_number = 3;
    older.stage = domain::DataStage::Intermediate;
    const auto rows = version_compare_rows(v, older);
    CHECK(!rows.empty());
    bool saw_differ = false;
    for (const auto& row : rows) {
        if (row.differ) {
            saw_differ = true;
        }
    }
    CHECK(saw_differ);
    CHECK(compare_title(v, older).find("v4") != std::string::npos);
}

// ---- ingest_columns ---------------------------------------------------------------

PWB_TEST(ingest_columns_and_bulk_edits) {
    CHECK(!decision_labels().empty());

    data::IngestPlan plan;
    data::PlannedItem item;
    item.decision = "pending";
    item.note = "note-a";
    plan.items.push_back(item);
    data::PlannedItem dup;
    dup.decision = "pending";
    dup.duplicate_of_version = "ver_dup00000001";
    dup.duplicate_of_asset = "ast_dup0000001";
    plan.items.push_back(dup);
    data::PlannedItem unresolved;
    unresolved.decision = "pending";
    unresolved.identity.strategy = "ambiguous";
    plan.items.push_back(unresolved);

    // Displays.
    CHECK_EQ(ingest_status_display(plan.items[1]), "⚠ 重复");
    CHECK_EQ(ingest_status_display(plan.items[2]), "? 待确认");
    CHECK_EQ(ingest_note_display(plan.items[1]),
             "重复: ast_dup00000");
    CHECK_EQ(ingest_note_display(plan.items[0]), "note-a");
    CHECK_EQ(ingest_entity_display(plan.items[0]), "—");

    // Bulk edits: accept_all skips duplicates; skip_unresolved marks
    // ambiguous-strategy items.
    ingest_accept_all(plan);
    CHECK_EQ(plan.items[0].decision, "accept");
    CHECK_EQ(plan.items[1].decision, "pending");
    CHECK_EQ(plan.items[2].decision, "accept");

    CHECK(!ingest_unresolved_skipped(plan));
    ingest_skip_unresolved(plan);
    CHECK(ingest_unresolved_skipped(plan));
    CHECK_EQ(plan.items[2].decision, "skip");

    const std::string summary = ingest_plan_summary_text(plan);
    CHECK(summary.find("共 3 个数据项") != std::string::npos);
}

// ---- review_core -----------------------------------------------------------------

PWB_TEST(review_core_flow_texts) {
    CHECK(review_config_text().find("内置规则") != std::string::npos);
    CHECK_EQ(review_run_done_text(3), "已检查 3 幅图件");

    const domain::Json report =
        domain::Json{{"id", "qr_1"}, {"linked_map_document_id", "doc_9"}};
    CHECK_EQ(review_report_filename(report), "qc_doc_9.json");
    const domain::Json bare = domain::Json{{"id", "qr_7"}};
    CHECK_EQ(review_report_filename(bare), "qc_qr_7.json");

    const domain::Json reports =
        domain::Json::array({report});
    const domain::Json docs = domain::Json::array(
        {domain::Json{{"id", "doc_1"}},
         domain::Json{{"id", "doc_9"}, {"name", "图件九"}}});
    const auto target = review_finalize_target(reports, docs);
    CHECK(target.has_value());
    CHECK_EQ((*target)["id"].get<std::string>(), "doc_9");
    // No matching id → the LAST doc (Python docs[-1]).
    const auto fallback = review_finalize_target(
        domain::Json::array({bare}), docs);
    CHECK(fallback.has_value());
    CHECK_EQ((*fallback)["id"].get<std::string>(), "doc_9");
    CHECK(!review_finalize_target(reports, domain::Json::array())
               .has_value());

    const std::string done = review_finalize_done_text(
        "图件九", domain::Json{{"name", "vs_1"},
                              {"status", "finalized"},
                              {"snapshots", domain::Json::array({1, 2})}});
    CHECK(done.find("图件九") != std::string::npos);
    CHECK(done.find("vs_1") != std::string::npos);
}

// ---- contract_lines ---------------------------------------------------------------

PWB_TEST(contract_lines_unknown_contract) {
    const auto lines = contract_panel_lines(nullptr, nullptr, false);
    CHECK_EQ(lines.size(), 1);
    CHECK(lines[0].warn);
    CHECK(lines[0].text.find("未知") != std::string::npos);
    CHECK(contract_title_text(nullptr).empty());
}

// ---- composite_layers -----------------------------------------------------------------

PWB_TEST(composite_layers_mutations) {
    CompositeLayers layers;
    layers.push_back(domain::Json{{"id", "l1"},
                                 {"name", "边界"},
                                 {"visible", true},
                                 {"opacity", 0.8}});
    layers.push_back(domain::Json{{"id", "l2"},
                                 {"name", "井"},
                                 {"visible", true},
                                 {"opacity", 0.5}});

    CHECK_EQ(composite_layer_index(layers, "l2"), 1);
    CHECK(composite_set_visible(layers, "l2", false));
    CHECK(!composite_layer_visible(layers[1]));
    // Opacity floor: values clamp to 0.05 minimum (Python parity).
    CHECK(composite_set_opacity(layers, "l2", 0.0));
    CHECK(composite_layer_opacity(layers[1]) >= 0.05);
    // Move +1 raises draw order (toward the top of the list).
    CHECK(composite_move_layer(layers, "l2", 1));
    CHECK_EQ(composite_layer_index(layers, "l2"), 0);
    // Unknown id → no mutation.
    CHECK(!composite_set_visible(layers, "nope", false));

    const domain::Json snapshot =
        composite_snapshot_json("EPSG:4326", layers);
    CHECK_EQ(snapshot["project_crs"].get<std::string>(), "EPSG:4326");
    CHECK_EQ(snapshot["layers"].size(), 2);
    // Untouched fields preserved verbatim.
    CHECK_EQ(snapshot["layers"][0]["name"].get<std::string>(), "井");
}

// ---- advisor_html -----------------------------------------------------------------

PWB_TEST(advisor_html_renders) {
    const domain::Json bh =
        domain::Json{{"summary", "BH ok"},
                     {"issues", domain::Json::array()}};
    const domain::Json fault =
        domain::Json{{"summary", "fault ok"},
                     {"issues", domain::Json::array()}};
    const std::string html = build_advisor_html(bh, fault);
    CHECK(html.find("<") != std::string::npos);
    CHECK(!html.empty());
}

int main() { return pwb_test::run_all(); }
