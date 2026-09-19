// viz_a.las_preview_wle — oracle replay for the WLE-backed LAS preview.
// Each case in las_preview_oracle.json was frozen from the REAL Python
// production preview (well_log_parsers.las_preview + geoviz + lasio) and
// the WLE SDK parser contract; adjudicated divergences are recorded per
// case (docs/development/cpp-viz-a/reconciliation.md). This test drives
// the registry LAS branch end-to-end, verifies fixture integrity (sha256),
// and re-checks that the frozen expectations are load-bearing (an in-memory
// byte flip must diverge).

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/domain/sha256.hpp>
// sha256: pwb::domain::Sha256::of_bytes (byte-identical to hashlib).
#include <pwb/ingest/preview/las_preview.hpp>
#include <pwb/ingest/preview/las_wle_bridge.hpp>
#include <pwb/ingest/preview/registry.hpp>

using pwb::domain::Json;
using namespace pwb::ingest::preview;

namespace {

int g_cases = 0;
int g_failures = 0;

void fail(const std::string& what) {
    std::fprintf(stderr, "FAIL %s\n", what.c_str());
    ++g_failures;
}

std::string read_file(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return {};
    return std::string((std::istreambuf_iterator<char>(in)),
                       std::istreambuf_iterator<char>());
}

Json project(const PreviewResult& r) {
    Json::array_t summary;
    for (const auto& [k, v] : r.summary_rows) {
        summary.push_back(Json::array({Json(k), Json(v)}));
    }
    Json::array_t table_rows;
    for (const auto& row : r.table_rows) {
        Json::array_t cells;
        for (const auto& cell : row) cells.push_back(Json(cell));
        table_rows.push_back(Json(cells));
    }
    Json::array_t data_rows;
    for (const auto& row : r.data_rows) {
        Json::array_t cells;
        for (const auto& cell : row) cells.push_back(Json(cell));
        data_rows.push_back(Json(cells));
    }
    return Json::object({
        {"mode", Json(r.mode)},
        {"type_label", Json(r.type_label)},
        {"message", Json(r.message)},
        {"warning", Json(r.warning)},
        {"truncated", Json(r.truncated)},
        {"summary_rows", Json(summary)},
        {"table_headers", Json(r.table_headers)},
        {"table_rows", Json(table_rows)},
        {"data_headers", Json(r.data_headers)},
        {"data_rows", Json(data_rows)},
    });
}

PreviewResult preview_of(const std::string& repo_root, const std::string& rel,
                         const std::string& name) {
    ResourceRef asset;
    asset.name = name;
    asset.path = repo_root + "/" + rel;
    asset.format = "las";
    asset.type = "well_log";
    asset.status = "active";
    return build_preview(asset, PreviewSettings{}, std::nullopt, {});
}

}  // namespace

int main() {
    namespace fs = std::filesystem;
    const fs::path fixture_root = PWB_VIZ_A_FIXTURE_ROOT;
    const fs::path oracle_path = fixture_root / "las_preview_oracle.json";
    const fs::path repo_root = fixture_root.parent_path().parent_path()
                                   .parent_path().parent_path();

    std::ifstream oracle_in(oracle_path);
    if (!oracle_in) {
        std::fprintf(stderr, "cannot open %s\n", oracle_path.c_str());
        return 2;
    }
    Json oracle = Json::parse(oracle_in);
    if (oracle["schema"].get<std::string>() != "pwb.viz_a.las_preview_oracle/1") {
        std::fprintf(stderr, "unexpected oracle schema\n");
        return 2;
    }

    install_wle_las_preview_provider();

    int agree_cases = 0;
    int adjudicated_cases = 0;
    for (const auto& case_json : oracle["cases"]) {
        const std::string id = case_json["id"].get<std::string>();
        const std::string rel = case_json["file"].get<std::string>();
        const fs::path path = repo_root / rel;
        const std::string bytes = read_file(path.string());
        if (bytes.empty()) {
            fail(id + ": cannot read " + path.string());
            continue;
        }
        // Fixture integrity: the frozen expectation belongs to these bytes.
        const std::string sha = pwb::domain::Sha256::of_bytes(bytes);
        if (sha != case_json["sha256"].get<std::string>()) {
            fail(id + ": sha256 mismatch (fixture drifted from oracle)");
            continue;
        }

        const std::string name = path.filename().string();
        Json expected = case_json["wle_expected"];
        // "<stem>" placeholders (empty WELL. fallback) resolve to the path
        // stem with the same rule the core uses (Python Path.stem parity).
        if (expected.contains("summary_rows") &&
            expected["summary_rows"].is_array() &&
            !expected["summary_rows"].empty() &&
            expected["summary_rows"][0].is_array() &&
            expected["summary_rows"][0].size() == 2 &&
            expected["summary_rows"][0][1].get<std::string>() == "<stem>") {
            std::string stem = name;
            const auto dot = stem.find_last_of('.');
            if (dot != std::string::npos && dot != 0) stem = stem.substr(0, dot);
            expected["summary_rows"][0][1] = Json(stem);
        }
        const PreviewResult result = preview_of(repo_root.string(), rel, name);
        Json actual = project(result);
        auto diff = pwb::domain::json_semantic_diff(expected, actual);
        ++g_cases;
        if (!diff.equal) {
            fail(id + " @ " + diff.path + ": " + diff.reason +
                 "\n  expected: " + expected.dump() +
                 "\n  actual:   " + actual.dump());
            continue;
        }

        if (case_json["references_agree"].get<bool>()) {
            ++agree_cases;
        } else {
            ++adjudicated_cases;
            if (case_json["adjudication"].get<std::string>().empty()) {
                fail(id + ": references disagree without an adjudication note");
            }
        }

        // Negative self-check: flip one byte at a time across the WHOLE
        // file in a TEMP COPY (the registry re-reads from disk); the
        // preview must diverge for at least one flip — for rejected/no-curve
        // cases the load-bearing bytes live in the HEADER (well name, ~C),
        // not only after ~A. The no_curve_headers verdict is content-
        // invariant BY CONSTRUCTION (stem + zeros, nothing parsed), so the
        // tamper check does not apply there — that branch's discrimination
        // is covered cross-case (every other fixture produces a different
        // result shape).
        if (case_json["wle_verdict"].get<std::string>() == "no_curve_headers") {
            continue;
        }
        const fs::path corrupt_dir = fs::temp_directory_path() / "viz_a_corrupt";
        fs::create_directories(corrupt_dir);
        const fs::path corrupt_path = corrupt_dir / path.filename();
        bool diverged = false;
        for (std::size_t i = 0; i < bytes.size() && !diverged; ++i) {
            const char original = bytes[i];
            if (original == '\n' || original == ' ' || original == '\t' ||
                original == '\r') {
                continue;
            }
            std::string corrupted = bytes;
            corrupted[i] = static_cast<char>(original == '5' ? '6' : '5');
            if (corrupted == bytes) continue;
            {
                std::ofstream out(corrupt_path,
                                  std::ios::binary | std::ios::trunc);
                out.write(corrupted.data(),
                          static_cast<std::streamsize>(corrupted.size()));
            }
            const PreviewResult corrupt_result = preview_of(
                corrupt_dir.parent_path().string(),
                (corrupt_dir.filename() / path.filename()).string(), name);
            if (!pwb::domain::json_semantic_diff(actual,
                                                 project(corrupt_result))
                     .equal) {
                diverged = true;
            }
        }
        std::error_code ec;
        fs::remove(corrupt_path, ec);
        if (!diverged) {
            fail(id + ": tampering did not change the preview (frozen "
                     "expectation not load-bearing)");
        }
    }

    // Capability honesty: clearing the provider must flip the LAS branch to
    // the unavailable message (never a fabricated Python error).
    set_las_preview_provider(nullptr);
    const PreviewResult unavailable = preview_of(
        repo_root.string(), "tests/cpp/viz_a/fixtures/las/01_normal_multisection.las",
        "01_normal_multisection.las");
    if (unavailable.mode != "message" ||
        unavailable.message.find("ModuleNotFoundError") != std::string::npos ||
        unavailable.message.find("WLE") == std::string::npos) {
        fail("provider-less registry branch is not the honest capability result");
    }
    install_wle_las_preview_provider();

    if (g_failures == 0) {
        std::printf("viz_a.las_preview_wle: OK (%d checks, %d exact-agree, "
                    "%d adjudicated)\n",
                    g_cases, agree_cases, adjudicated_cases);
        return 0;
    }
    std::printf("viz_a.las_preview_wle: %d failure(s) over %d checks\n",
                g_failures, g_cases);
    return 1;
}
