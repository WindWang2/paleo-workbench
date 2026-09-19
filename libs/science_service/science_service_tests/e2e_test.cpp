// science_service.e2e — the CONV-28 acceptance loop:
//   catalog-like input DTO (InMemoryPayloadSource) ->
//   AlgorithmRegistry (service adapters) ->
//   pwb::workflow::TaskRuntime execution ->
//   DirectoryEnvelopePublisher (local persistence) ->
//   envelope files verifiable by a workflow adapter (node_request mapper).
// Plus the failure and cancelled publication paths (publish-before-terminal).

#include <unistd.h>

#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>

#include <pwb/domain/json.hpp>
#include <pwb/science_service/payload.hpp>
#include <pwb/science_service/publisher.hpp>
#include <pwb/science_service/registry.hpp>
#include <pwb/workflow/task_runtime.hpp>

using namespace pwb::science_service;
namespace science = pwb::science;
using pwb::domain::Json;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

Json read_json_file(const std::filesystem::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream.good()) {
        return Json(nullptr);
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return Json::parse(buffer.str());
}

Json catalog_like_dto() {
    // The "catalog-like input DTO": a well-table version exactly as the
    // workflow line would resolve it from task sample points / well tables.
    Json records = Json::array();
    for (int i = 0; i < 6; ++i) {
        records.push_back(
            Json{{"well_id", "w" + std::to_string(i + 1)},
                 {"name", "Well-" + std::to_string(i + 1)},
                 {"x", static_cast<double>(i % 3) * 10.0},
                 {"y", static_cast<double>(i / 3) * 10.0},
                 {"value", 10.0 + 5.0 * static_cast<double>(i)}});
    }
    return records;
}

}  // namespace

int main() {
    const std::filesystem::path tmp =
        std::filesystem::temp_directory_path()
        / ("pwb-science-service-e2e-" + std::to_string(::getpid()));
    std::filesystem::remove_all(tmp);

    // --- assemble the service closure --------------------------------------
    auto source = std::make_shared<InMemoryPayloadSource>();
    source->put_table("dver_wells_1", catalog_like_dto());
    // An empty table version: a legitimate payload that yields no samples.
    source->put_table("dver_empty_1", Json::array());

    science::AlgorithmRegistry registry;
    const auto ids = register_science_services(registry, source, "e2e-build");
    check(ids.size() == 10, "e2e: services registered");

    // Host-owned adapter instance (the AlgorithmRunner pattern: the host
    // keeps shared ownership for TaskRuntime submission; the registry above
    // mirrors the descriptors for discovery/validation).
    std::shared_ptr<pwb::science::IAlgorithm> factor_algorithm(
        make_factor_interpolation_adapter(source, "e2e-build"));
    check(factor_algorithm->descriptor().algorithm_id
              == "mapping.factor_interpolate",
          "e2e: factor adapter id");

    auto publisher = std::make_shared<DirectoryEnvelopePublisher>(tmp);
    pwb::workflow::TaskRuntime runtime;

    // --- success path: factor interpolation via a workflow node request ----
    // The workflow-adapter entry: catalog-like input ref + node params ->
    // AlgorithmRequestV1 (node_request is the function a workflow node
    // adapter calls; the payload source resolves the ref).
    science::VersionRef input_ref;
    input_ref.asset_id = "ast_wells";
    input_ref.version_id = "dver_wells_1";
    input_ref.path = "artifacts/raw/ast_wells/dver_wells_1/wells.json";
    const Json node_params = Json{{"factor_name", "gr"},
                                  {"method", "idw"},
                                  {"grid_n", 10},
                                  {"power", 2.0},
                                  {"duplicate_policy", "mean"},
                                  {"include_layer_products", true},
                                  {"metadata", Json{{"task_id", "ftask_e2e"}}}};
    auto request = node_request("mapping.factor_interpolate", node_params,
                                {input_ref}, "req_e2e_ok");

    auto handle = runtime.submit(factor_algorithm, request, publisher);
    handle.wait();
    auto snapshot = handle.snapshot();
    check(snapshot.status == pwb::workflow::TaskStatus::succeeded,
          "e2e: task succeeded");
    check(snapshot.published, "e2e: publication completed");

    const std::filesystem::path ok_dir = tmp / "req_e2e_ok";
    check(std::filesystem::exists(ok_dir / "envelope.json"),
          "e2e: envelope.json persisted");
    check(std::filesystem::exists(ok_dir / "result.json"),
          "e2e: result.json persisted");

    const Json envelope = read_json_file(ok_dir / "envelope.json");
    check(!envelope.is_null(), "e2e: envelope parses");
    check(envelope.at("result_type") == "factor_grid", "e2e: envelope type");
    check(envelope.at("schema_version") == 1, "e2e: envelope schema");
    check(envelope.at("payload").contains("descriptor"), "e2e: descriptor");
    check(envelope.at("payload").contains("grid"), "e2e: grid embedded");
    check(envelope.at("payload").contains("contour_layer"),
          "e2e: contour products");
    check(envelope.at("quality").at("grid").contains("mean"),
          "e2e: quality grid stats");
    check(envelope.at("provenance").at("algorithm_id")
              == "mapping.factor_interpolate",
          "e2e: provenance algorithm");
    check(envelope.at("fingerprint").get<std::string>().size() == 64,
          "e2e: fingerprint sha256");

    // Round-trip through the envelope codec: fingerprint verifies.
    ScienceEnvelope parsed = ScienceEnvelope::from_json(envelope);
    check(parsed.fingerprint_of_payload() == parsed.fingerprint,
          "e2e: persisted fingerprint verifies");

    const Json result_dump = read_json_file(ok_dir / "result.json");
    check(result_dump.at("records").size() == 1,
          "e2e: result record index");
    check(result_dump.at("outputs").size() == 1
              && result_dump.at("outputs").at(0).at("name") == "factor_grid",
          "e2e: grid volume output declared");
    check(result_dump.at("provenance").at("input_refs").at(0).at(1)
              == "dver_wells_1",
          "e2e: input ref carried into provenance");

    // --- failure path: unknown factor -> publish_failure + failure.json ----
    science::VersionRef empty_ref;
    empty_ref.asset_id = "ast_empty";
    empty_ref.version_id = "dver_empty_1";
    const Json bad_params = Json{{"factor_name", "gr"}};
    auto bad_request =
        node_request("mapping.factor_interpolate", bad_params, {empty_ref},
                     "req_e2e_fail");
    auto bad_handle = runtime.submit(factor_algorithm, bad_request, publisher);
    bad_handle.wait();
    auto bad_snapshot = bad_handle.snapshot();
    check(bad_snapshot.status == pwb::workflow::TaskStatus::failed,
          "e2e: bad factor fails");
    check(bad_snapshot.published, "e2e: failure published");
    check(std::filesystem::exists(tmp / "req_e2e_fail" / "failure.json"),
          "e2e: failure.json persisted");
    const Json failure = read_json_file(tmp / "req_e2e_fail" / "failure.json");
    check(!failure.is_null(), "e2e: failure.json parses");
    check(!failure.is_null() && failure.at("code") == "factor.no_samples",
          "e2e: failure code stable");
    check(!std::filesystem::exists(tmp / "req_e2e_fail" / "envelope.json"),
          "e2e: no envelope on failure");

    // --- cancelled path: pre-stopped task never runs the algorithm ---------
    // (queued-cancel linearization: publish_failure with cancelled=true)
    auto cancel_request = node_request(
        "mapping.factor_interpolate", node_params, {input_ref}, "req_e2e_cancel");
    auto cancel_handle =
        runtime.submit(factor_algorithm, cancel_request, publisher);
    cancel_handle.cancel();
    cancel_handle.wait();
    auto cancel_snapshot = cancel_handle.snapshot();
    check(cancel_snapshot.status == pwb::workflow::TaskStatus::cancelled,
          "e2e: task cancelled");
    const Json cancel_failure =
        read_json_file(tmp / "req_e2e_cancel" / "failure.json");
    check(!cancel_failure.is_null(), "e2e: cancelled failure.json parses");
    check(!cancel_failure.is_null()
              && cancel_failure.at("cancelled") == true,
          "e2e: cancelled published as failure");

    // --- pure-compute mode (null publisher) still succeeds ------------------
    auto direct_request = node_request(
        "mapping.factor_interpolate", node_params, {input_ref}, "req_e2e_direct");
    auto direct_handle =
        runtime.submit(factor_algorithm, direct_request, nullptr);
    direct_handle.wait();
    check(direct_handle.snapshot().status
              == pwb::workflow::TaskStatus::succeeded,
          "e2e: pure-compute mode succeeds");

    runtime.shutdown();

    std::filesystem::remove_all(tmp);
    if (g_failures != 0) {
        std::fprintf(stderr, "science_service.e2e: %d failure(s)\n",
                     g_failures);
        return 1;
    }
    std::printf("science_service.e2e OK\n");
    return 0;
}
