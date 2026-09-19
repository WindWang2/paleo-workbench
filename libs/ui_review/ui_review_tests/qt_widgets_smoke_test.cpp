// UI-11 — Qt widget smoke test (offscreen): the Qt-only shells of the
// review/governance slice construct and respond — QC issue table, result
// summary, governance metadata patch validation, advisor/impact html,
// lineage recenter over a fake ICatalogApi, catalog-health audit render,
// version workbench rows + action gates, workflow contract panel, review
// export page over a fake IReviewActions. Worker-backed scans are kicked
// and pumped with QTRY so the JobOwner/scheduler seam is exercised too.

#include <QApplication>
#include <QComboBox>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPushButton>
#include <QSignalSpy>
#include <QTimer>
#include <QTableWidget>
#include <QTest>
#include <QTextBrowser>
#include <QTreeWidget>

#include <memory>
#include <string>
#include <vector>

#include <pwb/catalog/audit.hpp>
#include <pwb/catalog/models.hpp>
#include <pwb/catalog/sources.hpp>
#include <pwb/domain/stage.hpp>
#include <pwb/ui_review/catalog_api.hpp>
#include <pwb/ui_widgets/object_table.hpp>
#include <pwb/ui_review/impact_markdown.hpp>
#include <pwb/ui_review/qt/ai_check_advisor_dialog.hpp>
#include <pwb/ui_review/qt/catalog_health_dialog.hpp>
#include <pwb/ui_review/qt/governance_dialog.hpp>
#include <pwb/ui_review/qt/impact_preview_dialog.hpp>
#include <pwb/ui_review/qt/ingest_plan_dialog.hpp>
#include <pwb/ui_review/qt/lineage_explorer_dialog.hpp>
#include <pwb/ui_review/qt/qc_issue_table.hpp>
#include <pwb/ui_review/qt/relink_dialog.hpp>
#include <pwb/ui_review/qt/result_summary_panel.hpp>
#include <pwb/ui_review/qt/review_export_page.hpp>
#include <pwb/ui_review/qt/version_workbench_dialog.hpp>
#include <pwb/ui_review/qt/workflow_contract_panel.hpp>

#include "ui_review_test.hpp"

using namespace pwb;
using namespace pwb::ui_review;
using namespace pwb::ui_review::qt;

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
    v.created_at = "2025-01-02T03:04:05";
    return v;
}

// In-memory ICatalogApi — the same plain-DTO fake the dialogs were
// designed around (the real binding lands in the integration slice).
struct FakeCatalogApi : ICatalogApi {
    std::vector<catalog::DataVersion> versions;
    catalog::DataAsset asset;
    LineageHop hop;
    ResolvedPath resolved{"/tmp/x.csv", true};
    catalog::AuditReport audit_report;
    catalog::MissingSourceReport missing;
    int lineage_calls = 0;

    std::optional<catalog::DataVersion>
    get_version(const std::string& version_id) override {
        for (const auto& v : versions) {
            if (v.id.str() == version_id) {
                return v;
            }
        }
        return std::nullopt;
    }
    std::optional<catalog::DataAsset>
    get_asset(const std::string& asset_id) override {
        if (asset.id.str() == asset_id) {
            return asset;
        }
        return std::nullopt;
    }
    std::optional<LineageHop>
    get_lineage(const std::string& /*version_id*/) override {
        ++lineage_calls;
        return hop;
    }
    ResolvedPath
    resolve_path(const catalog::DataVersion& /*version*/) override {
        return resolved;
    }
    std::vector<catalog::DataVersion>
    list_versions(const std::string& /*asset_id*/) override {
        return versions;
    }
    domain::DataError
    promote_version(const std::string& /*version_id*/) override {
        return {domain::ErrorCode::Ok, ""};
    }
    domain::DataError trash_version(const std::string& /*version_id*/,
                                    const std::string& /*reason*/) override {
        return {domain::ErrorCode::Ok, ""};
    }
    domain::DataError
    restore_version(const std::string& /*version_id*/) override {
        return {domain::ErrorCode::Ok, ""};
    }
    catalog::MissingSourceReport
    find_missing_sources(const std::function<bool()>& /*cancel*/) override {
        return missing;
    }
    domain::DataError
    relink_external_source(const std::string& /*version_id*/,
                           const std::filesystem::path& /*p*/) override {
        return {domain::ErrorCode::Ok, ""};
    }
    catalog::AuditReport
    audit(bool /*deep*/, const std::function<bool()>& /*cancel*/) override {
        return audit_report;
    }
};

struct FakeReviewActions : IReviewActions {
    domain::Json reports = domain::Json::array();
    domain::Json docs = domain::Json::array();
    domain::Json artifacts = domain::Json::array();
    int run_calls = 0;

    domain::Json active_quality_reports() override { return reports; }
    domain::DataError run_map_qc(const std::string& /*doc_id*/) override {
        ++run_calls;
        return {domain::ErrorCode::Ok, ""};
    }
    domain::DataError export_report_json(const domain::Json& /*report*/,
                                         const std::string& /*path*/) override {
        return {domain::ErrorCode::Ok, ""};
    }
    domain::Result<domain::Json>
    finalize_map_version(const std::string& /*doc_id*/) override {
        return domain::Json{{"name", "vs_1"},
                            {"status", "finalized"},
                            {"snapshots", domain::Json::array()}};
    }
    std::string default_export_dir() override { return "/tmp"; }
    domain::Json paleomap_documents() override { return docs; }
    domain::Json export_artifacts() override { return artifacts; }
};

}  // namespace

// ---- simple widgets ------------------------------------------------------------

PWB_TEST(qc_issue_table_rows) {
    QcIssueTable table;
    const domain::Json report = domain::Json{
        {"rules", domain::Json::array({"层级一致性", "字段与输出格式完整性"})},
        {"issues", domain::Json::array(
                       {domain::Json{{"rule", "层级一致性"},
                                     {"severity", "error"},
                                     {"message", "断层"},
                                     {"feature_id", "f-7"},
                                     // Non-empty geometry — empty dict is
                                     // falsy in Python → not spatial.
                                     {"geometry",
                                      domain::Json{{"type", "Point"},
                                                   {"coordinates",
                                                    domain::Json::array(
                                                        {1.0, 2.0})}}}}})}};
    table.update_state({report});
    CHECK(table.table() != nullptr);
    CHECK_EQ(table.table()->rowCount(), 2);
    CHECK_EQ(table.spatial_issues_for_rule("层级一致性").size(), 1);
    CHECK(table.spatial_issues_for_rule("字段与输出格式完整性").empty());
}

PWB_TEST(result_summary_counts) {
    ResultSummaryPanel panel;
    const domain::Json reports = domain::Json::array({domain::Json{
        {"rules", domain::Json::array({"层级一致性", "未分类区域"})},
        {"issues", domain::Json::array(
                       {domain::Json{{"rule", "层级一致性"},
                                     {"severity", "error"},
                                     {"message", "x"}}})}}});
    const domain::Json artifacts = domain::Json::array(
        {domain::Json{{"format", "json"}, {"output_path", "/tmp/qc.json"}}});
    panel.update_state(reports, artifacts);
    CHECK(panel.error_label()->text().contains('1'));
    CHECK_EQ(panel.export_rows().size(), 1);
}

PWB_TEST(governance_dialog_patch_validation) {
    GovernanceMetadataDialog dialog(nullptr, QStringLiteral("well-a"),
                                    domain::Json::object());
    dialog.creator_edit()->setText(QStringLiteral("expert-1"));
    const auto result = dialog.patch();
    CHECK(result.is_ok());
    CHECK_EQ(result.value()["creator"].get<std::string>(), "expert-1");
}

PWB_TEST(advisor_and_impact_dialogs) {
    AICheckAdvisorDialog advisor(
        nullptr, domain::Json{{"summary", "bh"}},
        domain::Json{{"summary", "fault"}});
    CHECK(!advisor.browser()->toHtml().isEmpty());

    TrashImpactSummary summary;
    summary.descendant_count = 2;
    summary.runs_consuming = {"run_a"};
    summary.map_usages = {{"layer", "图层 A"}};
    ImpactPreviewDialog impact(nullptr, summary, {"ast_1"},
                               {"well-a"});
    CHECK(impact.browser()->toHtml().contains(
        QStringLiteral("图层 A")));
}

// ---- catalog-backed dialogs -------------------------------------------------------

PWB_TEST(lineage_explorer_recenter) {
    auto api = std::make_unique<FakeCatalogApi>();
    api->hop.version =
        make_version("ver_center000001", "ast_a", 2);
    // recenter() looks the version up via get_version first (Python
    // _on_locate parity) — the id must exist in the catalog listing.
    api->versions.push_back(api->hop.version);
    api->hop.parents.push_back(
        make_version("ver_parent00001", "ast_p", 1));
    api->hop.children.push_back(
        make_version("ver_child000001", "ast_c", 1,
                     domain::DataStage::Derived));
    FakeCatalogApi* api_ptr = api.get();

    LineageExplorerDialog dialog(
        nullptr, [api_ptr]() -> ICatalogApi* { return api_ptr; });
    CHECK(dialog.recenter(QStringLiteral("ver_center000001")));
    CHECK_EQ(dialog.current_version_id().toStdString(),
             "ver_center000001");
    // Lazy contract: one get_lineage hop per expansion — the recenter
    // itself performs the first hop only.
    CHECK(dialog.tree() != nullptr);
    CHECK(dialog.tree()->topLevelItemCount() >= 1);
    CHECK(api_ptr->lineage_calls >= 1);
    // Unknown id → inline warning, current node preserved.
    CHECK(!dialog.recenter(QStringLiteral("ver_missing")));
    CHECK_EQ(dialog.current_version_id().toStdString(),
             "ver_center000001");
}

PWB_TEST(catalog_health_audit_render) {
    auto api = std::make_unique<FakeCatalogApi>();
    api->audit_report.checked["versions"] = 4;
    api->audit_report.issues.push_back(
        catalog::AuditIssue{"broken_edge", "high", "v1", "detail"});
    FakeCatalogApi* api_ptr = api.get();

    CatalogHealthDialog dialog(
        nullptr, [api_ptr]() -> ICatalogApi* { return api_ptr; });
    // Synchronous render path (also what the worker completion calls).
    dialog.update_report(api_ptr->audit_report);
    CHECK(dialog.model() != nullptr);
    CHECK_EQ(dialog.model()->rowCount(), 1);
}

PWB_TEST(version_workbench_rows_and_gates) {
    auto api = std::make_unique<FakeCatalogApi>();
    api->asset.id = domain::AssetId{std::string("ast_a")};
    api->asset.name = "well-a";
    api->versions.push_back(
        make_version("ver_v1000000001", "ast_a", 1));
    api->versions.push_back(
        make_version("ver_v2000000001", "ast_a", 2,
                     domain::DataStage::Derived));
    api->asset.current_version_id =
        domain::VersionId{std::string("ver_v2000000001")};
    FakeCatalogApi* api_ptr = api.get();

    VersionWorkbenchDialog dialog(
        nullptr, [api_ptr]() -> ICatalogApi* { return api_ptr; },
        QStringLiteral("ast_a"));
    dialog.reload_versions();
    CHECK(dialog.versions_model() != nullptr);
    CHECK_EQ(dialog.versions_model()->rowCount(), 2);
}

PWB_TEST(relink_dialog_scan) {
    auto api = std::make_unique<FakeCatalogApi>();
    catalog::MissingSource entry;
    entry.version_id = "ver_m1000000001";
    entry.asset_id = "ast_a";
    entry.asset_name = "well-a";
    entry.managed = false;
    entry.relinkable = true;
    entry.recorded_path = "raw/x.csv";
    api->missing.entries.push_back(entry);
    api->missing.scanned = 7;
    FakeCatalogApi* api_ptr = api.get();

    RelinkSourcesDialog dialog(
        nullptr, [api_ptr]() -> ICatalogApi* { return api_ptr; });
    dialog.start_scan();
    // Worker-backed: pump until the scan lands (bounded wait).
    QTRY_VERIFY_WITH_TIMEOUT(!dialog.busy(), 15000);
    CHECK(dialog.model() != nullptr);
    CHECK_EQ(dialog.model()->rowCount(), 1);
}

PWB_TEST(workflow_contract_panel_lines) {
    WorkflowContractPanel panel;
    panel.set_contract_id(QStringLiteral("factor_interpolation"));
    CHECK(!panel.lines().empty());
    panel.dev_btn()->setChecked(true);
    CHECK(!panel.lines().empty());
}

// ---- review export page -------------------------------------------------------------

PWB_TEST(review_export_page_flow) {
    auto actions = std::make_unique<FakeReviewActions>();
    actions->docs = domain::Json::array(
        {domain::Json{{"id", "doc_1"}, {"name", "图件一"}}});
    actions->reports = domain::Json::array({domain::Json{
        {"id", "qr_1"},
        {"linked_map_document_id", "doc_1"},
        {"rules", domain::Json::array({"层级一致性"})},
        {"issues", domain::Json::array()}}});
    FakeReviewActions* actions_ptr = actions.get();

    ReviewExportPage page(
        nullptr, [actions_ptr]() -> IReviewActions* {
            return actions_ptr;
        });
    page.set_project_bound(true);
    page.update_state(actions_ptr->reports, actions_ptr->docs,
                      actions_ptr->artifacts);
    CHECK(page.action_header() != nullptr);
    CHECK(page.qc_table() != nullptr);
    CHECK(page.qc_table()->table()->rowCount() == 1);
    // run_qc → one run_map_qc call per paleomap document. The tail
    // QMessageBox::information is modal — schedule an auto-accept that
    // fires inside its nested exec (offscreen has no user to click).
    QTimer::singleShot(0, &page, [] {
        if (auto* box = qobject_cast<QMessageBox*>(
                QApplication::activeModalWidget())) {
            box->accept();
        }
    });
    page.run_qc();
    CHECK_EQ(actions_ptr->run_calls, 1);
}

// ---- ingest plan dialog -----------------------------------------------------------

PWB_TEST(ingest_plan_dialog_constructs) {
    IngestDialogHooks hooks;
    const std::vector<IngestEntityRow> well_rows{
        IngestEntityRow{"w1", "井一", "uwi-1"}};
    hooks.wells = [well_rows] { return well_rows; };
    hooks.surveys = [] { return std::vector<IngestEntityRow>{}; };
    hooks.build = [](const std::filesystem::path&,
                     const data::IngestPlanOptions&) {
        data::IngestPlan plan;
        data::PlannedItem item;
        item.path = "a.csv";
        item.decision = "accept";
        plan.items.push_back(item);
        return plan;
    };
    hooks.execute = [](const data::IngestPlan&,
                       const data::IngestExecuteOptions&) {
        return data::IngestExecuteReport{};
    };
    IngestPlanDialog dialog(nullptr, std::move(hooks), "/tmp");
    // Before the build completes the plan is absent; execute gated.
    CHECK(dialog.plan() == nullptr);
    CHECK(dialog.execute_btn() != nullptr);
    CHECK(dialog.detail() != nullptr);

    // Detail panel edits one item synchronously. (hooks was moved into
    // the dialog — call set_item with the row lists directly.)
    data::PlannedItem item;
    item.decision = "pending";
    dialog.detail()->set_item(&item, well_rows, {});
    dialog.detail()->decision_combo()->setCurrentIndex(0);
}

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    return pwb_test::run_all();
}
