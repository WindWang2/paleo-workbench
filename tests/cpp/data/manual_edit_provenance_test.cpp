// data.manual_edit — V14-DATA-LINEAGE manual-edit provenance assembly
// (catalog/lifecycle.py register_manual_edit_run /
// complete_manual_edit_run pure halves) plus the artifact lifecycle
// enforcement layer (intermediate_policy.py decision table wired into the
// publish funnel: fail-closed gate, stage resolution, idempotent stamping).
#include "pwb_test.hpp"

#include "pwb/catalog/manual_edit.hpp"
#include "pwb/catalog/models.hpp"
#include "pwb/data/lifecycle_enforcement.hpp"
#include "pwb/domain/json.hpp"
#include "pwb/domain/stage.hpp"

#include <string>
#include <vector>

namespace {

using pwb::catalog::CatalogDocument;
using pwb::catalog::DataRun;
using pwb::catalog::DataVersion;
using pwb::catalog::ManualEditCompletion;
using pwb::catalog::ManualEditRequest;

DataVersion version(const std::string& id, const std::string& asset_id) {
    DataVersion row;
    row.id = pwb::domain::VersionId(id);
    row.asset_id = pwb::domain::AssetId(asset_id);
    row.version_number = 1;
    return row;
}

CatalogDocument document_with_versions() {
    CatalogDocument document;
    document.versions.push_back(version("ver_000000000001", "asset_1"));
    document.versions.push_back(version("ver_000000000002", "asset_2"));
    return document;
}

}  // namespace

// ---- port role mapping ---------------------------------------------------------

PWB_TEST(port_role_for_business_role_is_open_vocabulary) {
    PWB_CHECK(pwb::catalog::port_role_for_business_role("well_log") ==
              "well_logs");
    PWB_CHECK(pwb::catalog::port_role_for_business_role("fault") == "faults");
    PWB_CHECK(pwb::catalog::port_role_for_business_role("trajectory") ==
              "trajectory");
    // Unknown business roles pass through verbatim; "" maps to "".
    PWB_CHECK(pwb::catalog::port_role_for_business_role("custom_thing") ==
              "custom_thing");
    PWB_CHECK(pwb::catalog::port_role_for_business_role("").empty());
}

// ---- register (build_manual_edit_run) -------------------------------------------

PWB_TEST(build_manual_edit_run_registers_a_running_run_with_typed_inputs) {
    const CatalogDocument document = document_with_versions();

    ManualEditRequest request;
    request.source_version_ids = {"ver_000000000001", "ver_000000000002"};
    request.entity_type = "well";
    request.entity_id = "W1";
    request.business_role = "tops";
    request.actor = "王工";
    request.note = "修正分层深度";
    request.as_new_asset = false;
    request.extra_parameters = pwb::domain::Json::object();
    request.extra_parameters["layer"] = "T2b";

    auto result = pwb::catalog::build_manual_edit_run(document, request);
    PWB_CHECK(result.is_ok());
    const DataRun& run = result.value();
    PWB_CHECK(run.operation == "manual_edit");
    PWB_CHECK(run.generator == "paleo-workbench/manual-edit");
    PWB_CHECK(run.status == "running");
    PWB_CHECK(!run.id.str().empty());

    // Input ids in request order, one typed input port per version.
    PWB_CHECK(run.input_version_ids.size() == 2);
    PWB_CHECK(run.input_version_ids[0].str() == "ver_000000000001");
    PWB_CHECK(run.input_version_ids[1].str() == "ver_000000000002");
    PWB_CHECK(run.input_ports.size() == 2);
    for (std::size_t i = 0; i < run.input_ports.size(); ++i) {
        PWB_CHECK(run.input_ports[i].direction == "input");
        PWB_CHECK(run.input_ports[i].role == "tops");
        PWB_CHECK(run.input_ports[i].ordinal ==
                  static_cast<int>(i));
        PWB_CHECK(run.input_ports[i].required);
        PWB_CHECK(run.input_ports[i].version_id.str() ==
                  run.input_version_ids[i].str());
    }
    // No outputs yet — the run is registered BEFORE committing.
    PWB_CHECK(run.output_ports.empty());
    PWB_CHECK(run.output_version_ids.empty());

    // Parameters carry the business context + actor/note + extra keys.
    PWB_CHECK(run.parameters.value("entity_type", std::string()) == "well");
    PWB_CHECK(run.parameters.value("entity_id", std::string()) == "W1");
    PWB_CHECK(run.parameters.value("business_role", std::string()) == "tops");
    PWB_CHECK(run.parameters.value("as_new_asset", true) == false);
    PWB_CHECK(run.parameters.value("actor", std::string()) == "王工");
    PWB_CHECK(run.parameters.value("note", std::string()) == "修正分层深度");
    PWB_CHECK(run.parameters.value("layer", std::string()) == "T2b");
}

PWB_TEST(build_manual_edit_run_omits_actor_and_note_when_empty) {
    const CatalogDocument document = document_with_versions();
    ManualEditRequest request;
    request.source_version_ids = {"ver_000000000002"};
    request.entity_type = "well";
    request.entity_id = "W2";
    request.business_role = "well_log";  // maps to a distinct port role

    auto result = pwb::catalog::build_manual_edit_run(document, request);
    PWB_CHECK(result.is_ok());
    const DataRun& run = result.value();
    // The actor is never fabricated — absent user stays absent.
    PWB_CHECK(!run.parameters.contains("actor"));
    PWB_CHECK(!run.parameters.contains("note"));
    PWB_CHECK(run.input_ports.size() == 1);
    PWB_CHECK(run.input_ports[0].role == "well_logs");

    // Empty source id strings are dropped (lifecycle.py) — no port, no id.
    ManualEditRequest with_blank;
    with_blank.source_version_ids = {"", "ver_000000000001"};
    with_blank.business_role = "tops";
    auto blank = pwb::catalog::build_manual_edit_run(document, with_blank);
    PWB_CHECK(blank.is_ok());
    PWB_CHECK(blank.value().input_version_ids.size() == 1);
    PWB_CHECK(blank.value().input_ports.size() == 1);
}

PWB_TEST(build_manual_edit_run_unknown_source_fails_closed) {
    const CatalogDocument document = document_with_versions();
    ManualEditRequest request;
    request.source_version_ids = {"ver_000000000001", "ver_missing_999"};
    request.business_role = "tops";

    auto result = pwb::catalog::build_manual_edit_run(document, request);
    PWB_CHECK(!result.is_ok());
    PWB_CHECK(result.error().code == pwb::domain::ErrorCode::NotFound);
    PWB_CHECK(result.error().message.find("ver_missing_999") !=
              std::string::npos);

    // Multiple unknown ids are all reported.
    ManualEditRequest multi;
    multi.source_version_ids = {"ver_x1", "ver_x2"};
    auto multi_result = pwb::catalog::build_manual_edit_run(document, multi);
    PWB_CHECK(!multi_result.is_ok());
    PWB_CHECK(multi_result.error().message.find("ver_x1") !=
              std::string::npos);
    PWB_CHECK(multi_result.error().message.find("ver_x2") !=
              std::string::npos);
}

// ---- complete (apply_manual_edit_completion) --------------------------------------

PWB_TEST(apply_manual_edit_completion_attaches_outputs_and_closes) {
    const CatalogDocument document = document_with_versions();
    ManualEditRequest request;
    request.source_version_ids = {"ver_000000000001", "ver_000000000002"};
    request.business_role = "well_log";
    auto built = pwb::catalog::build_manual_edit_run(document, request);
    PWB_CHECK(built.is_ok());

    ManualEditCompletion completion;
    completion.committed_version_ids = {"ver_c1", "ver_c2", "ver_c3"};
    completion.business_role = "well_log";

    auto done = pwb::catalog::apply_manual_edit_completion(built.value(),
                                                           completion);
    PWB_CHECK(done.is_ok());
    const DataRun& run = done.value();
    PWB_CHECK(run.status == "complete");

    // Output ports carry the MANUAL_EDIT role (the business role only
    // gates whether ports attach) with per-commit ordinals.
    PWB_CHECK(run.output_ports.size() == 3);
    for (std::size_t i = 0; i < run.output_ports.size(); ++i) {
        PWB_CHECK(run.output_ports[i].direction == "output");
        PWB_CHECK(run.output_ports[i].role == "manual_edit");
        PWB_CHECK(run.output_ports[i].ordinal == static_cast<int>(i));
        PWB_CHECK(run.output_ports[i].required);
    }
    // The flat output list is set to the committed ids.
    PWB_CHECK(run.output_version_ids.size() == 3);
    PWB_CHECK(run.output_version_ids[0].str() == "ver_c1");
    PWB_CHECK(run.output_version_ids[1].str() == "ver_c2");
    PWB_CHECK(run.output_version_ids[2].str() == "ver_c3");
    // Inputs survive completion untouched.
    PWB_CHECK(run.input_version_ids.size() == 2);
    PWB_CHECK(run.input_ports.size() == 2);
    PWB_CHECK(run.input_ports[0].role == "well_logs");
    PWB_CHECK(!run.parameters.contains("failed_checkouts"));
}

PWB_TEST(apply_manual_edit_completion_records_failed_checkouts) {
    const CatalogDocument document = document_with_versions();
    ManualEditRequest request;
    request.source_version_ids = {"ver_000000000001"};
    request.business_role = "tops";
    auto built = pwb::catalog::build_manual_edit_run(document, request);
    PWB_CHECK(built.is_ok());

    ManualEditCompletion completion;
    completion.committed_version_ids = {"ver_c1"};
    completion.business_role = "tops";
    completion.failed_count = 2;

    auto done = pwb::catalog::apply_manual_edit_completion(built.value(),
                                                           completion);
    PWB_CHECK(done.is_ok());
    PWB_CHECK(done.value().status == "complete");
    PWB_CHECK(done.value().parameters.value("failed_checkouts", 0) == 2);
    PWB_CHECK(done.value().output_ports.size() == 1);
}

PWB_TEST(apply_manual_edit_completion_without_commits_fails_the_run) {
    const CatalogDocument document = document_with_versions();
    ManualEditRequest request;
    request.source_version_ids = {"ver_000000000001"};
    request.business_role = "tops";
    auto built = pwb::catalog::build_manual_edit_run(document, request);
    PWB_CHECK(built.is_ok());

    ManualEditCompletion empty;
    empty.business_role = "tops";
    auto done = pwb::catalog::apply_manual_edit_completion(built.value(),
                                                           empty);
    PWB_CHECK(done.is_ok());
    PWB_CHECK(done.value().status == "failed");
    PWB_CHECK(done.value().output_ports.empty());
    PWB_CHECK(done.value().output_version_ids.empty());

    // Blank strings in the committed list count as nothing landed.
    ManualEditCompletion blanks;
    blanks.committed_version_ids = {"", ""};
    blanks.business_role = "tops";
    auto blanked = pwb::catalog::apply_manual_edit_completion(built.value(),
                                                              blanks);
    PWB_CHECK(blanked.is_ok());
    PWB_CHECK(blanked.value().status == "failed");
    PWB_CHECK(blanked.value().output_ports.empty());
    PWB_CHECK(blanked.value().output_version_ids.empty());
}

// ---- lifecycle enforcement ---------------------------------------------------------

PWB_TEST(lifecycle_for_artifact_intermediate_kind_applies_and_registers) {
    const auto decision =
        pwb::data::lifecycle_for_artifact("prediction_intermediate");
    PWB_CHECK(decision.applies);
    PWB_CHECK(decision.known_kind);
    PWB_CHECK(decision.artifact_class == "intermediate");
    PWB_CHECK(decision.must_register);
    PWB_CHECK(decision.stage.has_value());
    PWB_CHECK(*decision.stage == pwb::domain::DataStage::Intermediate);
    PWB_CHECK(decision.retention_class == "recomputable");
    // Registered kinds pass the fail-closed gate.
    PWB_CHECK(!pwb::data::lifecycle_registration_error(
                  "prediction_intermediate")
                  .has_value());
}

PWB_TEST(lifecycle_registration_error_refuses_non_registering_kinds) {
    const auto decision = pwb::data::lifecycle_for_artifact("render_temp_svg");
    PWB_CHECK(decision.applies);
    PWB_CHECK(decision.known_kind);
    PWB_CHECK(decision.artifact_class == "ephemeral");
    PWB_CHECK(!decision.must_register);

    const auto error = pwb::data::lifecycle_registration_error(
        "render_temp_svg");
    PWB_CHECK(error.has_value());
    PWB_CHECK(error->find("render_temp_svg") != std::string::npos);
    PWB_CHECK(error->find("ephemeral") != std::string::npos);
    // Cache kinds are also refused by the managed store.
    PWB_CHECK(pwb::data::lifecycle_registration_error("preview_cache")
                  .has_value());

    // Empty kind → non-applying decision, no gate error (caller defaults).
    const auto none = pwb::data::lifecycle_for_artifact("");
    PWB_CHECK(!none.applies);
    PWB_CHECK(!pwb::data::lifecycle_registration_error("").has_value());
}

PWB_TEST(lifecycle_for_artifact_unknown_kind_uses_intermediate_fallback) {
    const auto decision = pwb::data::lifecycle_for_artifact("zzz");
    PWB_CHECK(decision.applies);
    PWB_CHECK(!decision.known_kind);
    PWB_CHECK(decision.artifact_class == "intermediate");
    PWB_CHECK(decision.must_register);
    PWB_CHECK(decision.stage.has_value());
    PWB_CHECK(*decision.stage == pwb::domain::DataStage::Intermediate);
    PWB_CHECK(decision.retention_class == "recomputable");
    PWB_CHECK(!decision.rationale.empty());
    // The honest 未登记 rationale names the kind.
    PWB_CHECK(decision.rationale.find("zzz") != std::string::npos);
    PWB_CHECK(!pwb::data::lifecycle_registration_error("zzz").has_value());
}

PWB_TEST(resolve_publish_stage_policy_wins_over_caller_default) {
    using pwb::domain::DataStage;
    // Known kinds: the classification stage IS the point of the kind.
    PWB_CHECK(pwb::data::resolve_publish_stage("prediction_intermediate",
                                               DataStage::Raw) ==
              DataStage::Intermediate);
    PWB_CHECK(pwb::data::resolve_publish_stage("export", DataStage::Raw) ==
              DataStage::Output);
    PWB_CHECK(pwb::data::resolve_publish_stage("seismic_attribute",
                                               DataStage::Intermediate) ==
              DataStage::Derived);
    // Unknown and empty kinds keep the caller's stage.
    PWB_CHECK(pwb::data::resolve_publish_stage("zzz", DataStage::Derived) ==
              DataStage::Derived);
    PWB_CHECK(pwb::data::resolve_publish_stage("", DataStage::Raw) ==
              DataStage::Raw);
}

PWB_TEST(stamp_lifecycle_metadata_is_idempotent_and_existing_wins) {
    const auto decision =
        pwb::data::lifecycle_for_artifact("prediction_intermediate");

    pwb::domain::Json metadata = pwb::domain::Json::object();
    pwb::data::stamp_lifecycle_metadata(metadata, decision);
    PWB_CHECK(metadata.contains("lifecycle"));
    PWB_CHECK(metadata["lifecycle"].value("class", std::string()) ==
              "intermediate");
    PWB_CHECK(metadata["lifecycle"].value("retention_class",
                                          std::string()) == "recomputable");
    PWB_CHECK(metadata["lifecycle"].value("known_kind", false));
    PWB_CHECK(metadata["lifecycle"].value("artifact_kind_present", false));

    // An explicit pre-existing lifecycle object is never overwritten.
    pwb::domain::Json curated = pwb::domain::Json::object();
    curated["lifecycle"] = pwb::domain::Json{{"class", "custom"}};
    pwb::data::stamp_lifecycle_metadata(curated, decision);
    PWB_CHECK(curated["lifecycle"].value("class", std::string()) == "custom");
    PWB_CHECK(curated["lifecycle"].size() == 1);

    // Stamping twice does not duplicate or mutate the record.
    pwb::data::stamp_lifecycle_metadata(metadata, decision);
    PWB_CHECK(metadata["lifecycle"].value("class", std::string()) ==
              "intermediate");

    // Non-applying decisions never stamp.
    pwb::domain::Json untouched = pwb::domain::Json::object();
    pwb::data::stamp_lifecycle_metadata(
        untouched, pwb::data::lifecycle_for_artifact(""));
    PWB_CHECK(!untouched.contains("lifecycle"));
}
