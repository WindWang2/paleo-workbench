// interchange.preflight — replay of the frozen Python oracle for the
// interchange kernel: path_safety, package manifest, preflight decisions.
// Every expectation in fixtures/interchange_oracle.json was produced by
// running the real paleo_workbench modules (see
// tools/oracle/generate_interchange_fixtures.py); nothing here is hand-written.

#include <pwb/domain/json.hpp>
#include <pwb/interchange/manifest.hpp>
#include <pwb/interchange/path_safety.hpp>
#include <pwb/interchange/preflight.hpp>
#include <pwb/interchange/unicode.hpp>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <unistd.h>
#include <vector>

using pwb::domain::Json;
using pwb::domain::JsonDiff;
using pwb::domain::json_semantic_diff;
using namespace pwb::interchange;

#ifndef PWB_INTERCHANGE_FIXTURE
#define PWB_INTERCHANGE_FIXTURE "interchange_oracle.json"
#endif

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

Json load_oracle() {
    std::ifstream stream(PWB_INTERCHANGE_FIXTURE, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open oracle fixture\n");
        std::exit(1);
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return Json::parse(buffer.str());
}

std::string diff_text(const Json& got, const Json& want) {
    // Normalize through dump/parse: Python has one int type, so oracle
    // numbers parse as unsigned while C++ to_dict writes signed — same JSON
    // text, and int-vs-float stays a real type difference.
    Json got_norm = Json::parse(got.dump());
    Json want_norm = Json::parse(want.dump());
    const JsonDiff diff = json_semantic_diff(want_norm, got_norm);
    if (diff.equal) {
        return "";
    }
    return diff.path + ": " + diff.reason;
}

std::vector<std::string> sorted_list(const Json& array) {
    std::vector<std::string> out;
    for (const auto& item : array) {
        out.push_back(item.get<std::string>());
    }
    std::sort(out.begin(), out.end());
    return out;
}

// ---------------------------------------------------------------- sections --

void run_unicode(const Json& oracle) {
    int n = 0;
    for (const auto& entry : oracle["unicode"]) {
        ++n;
        const std::string input = entry["input"].get<std::string>();
        check(nfc_normalize_utf8(input) == entry["nfc"].get<std::string>(),
              entry["id"].get<std::string>() + " nfc");
        check(casefold_utf8(input) == entry["casefold"].get<std::string>(),
              entry["id"].get<std::string>() + " casefold");
    }
    check(n == 32, "32 unicode cases");
    std::printf("unicode: %d cases\n", n);
}

void run_fuzz_nfc(const Json& oracle) {
    int n = 0;
    for (const auto& entry : oracle["fuzz_nfc"]) {
        ++n;
        const std::string input = entry["input"].get<std::string>();
        check(nfc_normalize_utf8(input) == entry["nfc"].get<std::string>(),
              entry["id"].get<std::string>() + " nfc");
        check(casefold_utf8(input) == entry["casefold"].get<std::string>(),
              entry["id"].get<std::string>() + " casefold");
    }
    std::printf("fuzz_nfc: %d cases\n", n);
}

void run_safe_path(const Json& oracle) {
    int n = 0;
    for (const auto& entry : oracle["safe_path"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        const std::string name = entry["name"].get<std::string>();
        const std::string what = entry["what"].get<std::string>();
        if (entry["ok"].get<bool>()) {
            try {
                const std::string path = safe_relative_path(name, what);
                check(path == entry["path"].get<std::string>(),
                      id + " path: " + path + " want "
                          + entry["path"].get<std::string>());
            } catch (const std::exception& ex) {
                check(false, id + " unexpectedly threw: " + ex.what());
            }
        } else {
            try {
                safe_relative_path(name, what);
                check(false, id + " should have been rejected");
            } catch (const UnsafePathError& ex) {
                check(std::string(ex.what())
                              == entry["error"].get<std::string>(),
                      id + " message: " + ex.what());
            } catch (const std::exception& ex) {
                check(false, id + " wrong exception type: " + ex.what());
            }
        }
    }
    for (const auto& entry : oracle["reserved_helper"]) {
        ++n;
        check(is_reserved_or_unsafe(entry["name"].get<std::string>())
                  == entry["unsafe"].get<bool>(),
              entry["id"].get<std::string>() + " helper");
    }
    std::printf("safe_path: %d cases\n", n);
}

void run_collision(const Json& oracle) {
    int n = 0;
    for (const auto& entry : oracle["collision"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        std::set<std::string> seen_casefold;
        std::set<std::string> seen_nfc;
        std::string failure;
        int failed_at = -1;
        for (int index = 0; index < static_cast<int>(entry["names"].size());
             ++index) {
            const std::string name =
                entry["names"][static_cast<std::size_t>(index)].get<std::string>();
            try {
                const std::string pure = safe_relative_path(name);
                check_collision(pure, seen_casefold, seen_nfc);
            } catch (const UnsafePathError& ex) {
                failure = ex.what();
                failed_at = index;
                break;
            }
        }
        const bool expect_fail = !entry["fail_index"].is_null();
        check(failed_at == (expect_fail ? entry["fail_index"].get<int>() : -1),
              id + " fail_index");
        check(!expect_fail
                  || failure == entry["error"].get<std::string>(),
              id + " message: " + failure);
    }
    std::printf("collision: %d sequences\n", n);
}

void run_sanitize(const Json& oracle) {
    int n = 0;
    for (const auto& entry : oracle["sanitize"]) {
        ++n;
        const std::string got = sanitize_filename(
            entry["stem"].get<std::string>(), entry["fallback"].get<std::string>());
        check(got == entry["expected"].get<std::string>(),
              entry["id"].get<std::string>() + ": got " + got);
    }
    std::printf("sanitize: %d cases\n", n);
}

// POSIX only: the oracle layouts and symlink replay assume create_symlink
// (documented in ledgers/14-decisions.md D14-8).
bool make_symlink(const std::filesystem::path& link,
                  const std::filesystem::path& target) {
    std::error_code ec;
    std::filesystem::create_symlink(target, link, ec);
    return !ec;
}

void run_within_root(const Json& oracle) {
    const std::filesystem::path base =
        std::filesystem::temp_directory_path()
        / ("pwb-conv14-replay-" + std::to_string(::getpid()));
    std::filesystem::create_directories(base);
    int n = 0;
    for (const auto& scenario : oracle["within_root"]) {
        ++n;
        const std::string id = scenario["id"].get<std::string>();
        std::filesystem::path work = base / id;
        std::filesystem::create_directories(work);
        for (const auto& dir : scenario["layout"]["dirs"]) {
            std::filesystem::create_directories(work / dir.get<std::string>());
        }
        for (const auto& file : scenario["layout"]["files"]) {
            std::ofstream(work / file.get<std::string>()) << "x";
        }
        for (auto it = scenario["layout"]["symlinks"].begin();
             it != scenario["layout"]["symlinks"].end(); ++it) {
            check(make_symlink(work / it.key(),
                               std::filesystem::path(it.value().get<std::string>())),
                  id + " symlink setup");
        }
        const std::filesystem::path root = work / scenario["root"].get<std::string>();
        const std::filesystem::path candidate =
            work / scenario["candidate"].get<std::string>();
        const std::string expect = scenario["expect"].get<std::string>();
        try {
            const std::filesystem::path resolved =
                ensure_within_root(root, candidate);
            check(expect == "inside", id + " expected rejection, got inside");
            if (expect == "inside") {
                std::error_code ec;
                const std::string rel =
                    resolved.lexically_relative(
                        std::filesystem::weakly_canonical(root, ec))
                        .generic_string();
                check(rel == scenario["observed_rel"].get<std::string>(),
                      id + " rel: " + rel);
            }
        } catch (const UnsafePathError& ex) {
            const std::string message = ex.what();
            check(expect != "inside"
                      && message.rfind(
                             scenario["message_prefix"].get<std::string>(), 0)
                      == 0,
                  id + " message: " + message);
        }
        std::filesystem::remove_all(work);
    }
    std::filesystem::remove(base);
    std::printf("within_root: %d scenarios\n", n);
}

void run_manifest(const Json& oracle) {
    const Json& section = oracle["manifest"];
    check(section["filename"].get<std::string>() == kManifestFilename,
          "manifest filename");
    check(section["kind"].get<std::string>() == kManifestKind, "manifest kind");
    check(section["schema_version"].get<int>() == kManifestSchemaVersion,
          "manifest schema version");

    int n = 0;
    for (const auto& entry : section["build"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        try {
            const PackageManifest revived = PackageManifest::from_dict(entry["dict"]);
            const std::string dumped = revived.dumps();
            if (dumped != entry["dumps"].get<std::string>()) {
                check(false, id + " dumps mismatch:\n--- got ---\n" + dumped
                    + "\n--- want ---\n" + entry["dumps"].get<std::string>());
            }
        } catch (const std::exception& ex) {
            check(false, id + " threw: " + ex.what());
        }
    }
    for (const auto& entry : section["from_dict"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        if (entry["ok"].get<bool>()) {
            try {
                const PackageManifest revived =
                    PackageManifest::from_dict(entry["input"]);
                const std::string mismatch =
                    diff_text(revived.to_dict(), entry["dict"]);
                check(mismatch.empty(), id + " dict mismatch: " + mismatch);
            } catch (const std::exception& ex) {
                check(false, id + " threw: " + ex.what());
            }
        } else {
            try {
                PackageManifest::from_dict(entry["input"]);
                check(false, id + " should have failed");
            } catch (const std::invalid_argument& ex) {
                check(std::string(ex.what()) == entry["error"].get<std::string>(),
                      id + " message: " + ex.what());
            } catch (const std::exception& ex) {
                check(false, id + " wrong exception type: " + ex.what());
            }
        }
    }
    for (const auto& entry : section["validate"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        try {
            const PackageManifest revived = PackageManifest::from_dict(entry["input"]);
            try {
                revived.validate_paths();
                check(entry["ok"].get<bool>(), id + " should have failed");
            } catch (const UnsafePathError& ex) {
                check(!entry["ok"].get<bool>()
                          && std::string(ex.what())
                              == entry["error"].get<std::string>(),
                      id + " message: " + ex.what());
            }
        } catch (const std::exception& ex) {
            check(false, id + " from_dict threw: " + ex.what());
        }
    }
    for (const auto& entry : section["entry_paths"]) {
        ++n;
        // rebuild a manifest whose entries carry exactly the frozen paths
        Json data = Json::object();
        Json entries = Json::array();
        for (const auto& path : entry["paths"]) {
            Json one = Json::object();
            one["path"] = path.get<std::string>();
            one["sha256"] = "00";
            one["size_bytes"] = 0;
            one["kind"] = "artifact";
            entries.push_back(one);
        }
        data["entries"] = entries;
        const PackageManifest manifest = PackageManifest::from_dict(data);
        const auto paths = manifest.entry_paths();
        const auto want = sorted_list(entry["paths"]);
        const std::vector<std::string> got(paths.begin(), paths.end());
        check(got == want, entry["id"].get<std::string>() + " entry_paths");
    }

    // write + read round trip through the real filesystem helpers.
    const Json& roundtrip = section["write_read_roundtrip"];
    {
        const std::filesystem::path root = std::filesystem::temp_directory_path()
            / "pwb-conv14-manifest";
        std::filesystem::create_directories(root);
        const PackageManifest manifest = PackageManifest::from_dict(roundtrip["dict"]);
        const auto target = write_manifest(manifest, root);
        check(target.filename().string() == kManifestFilename, "manifest target");
        const PackageManifest reread = read_manifest(root);
        check(reread.dumps() == roundtrip["dumps"].get<std::string>(),
              "manifest write/read roundtrip bytes");
        check(reread == manifest, "manifest roundtrip equality");
        std::filesystem::remove_all(root);
    }
    std::printf("manifest: %d cases\n", n);
}

ImportPreflightService::Sniffer make_sniffer(const Json& frozen_sniff) {
    return [frozen_sniff](const std::filesystem::path&) {
        SniffResult sniff;
        sniff.format_id = frozen_sniff["format_id"].get<std::string>();
        sniff.confidence = frozen_sniff["confidence"].get<std::string>();
        sniff.evidence = frozen_sniff["evidence"].get<std::string>();
        return sniff;
    };
}

AdapterSpec spec_from_stub(const Json& stub) {
    AdapterSpec spec;
    spec.format_id = stub["format_id"].get<std::string>();
    spec.display_name = stub.value("display_name", spec.format_id);
    for (const auto& ext : stub["extensions"]) {
        spec.extensions.push_back(ext.get<std::string>());
    }
    spec.import_data = stub["import"].get<bool>();
    if (stub.contains("notes")) {
        spec.notes = stub["notes"].get<std::string>();
    }
    if (stub.contains("inspect") && !stub["inspect"].is_null()) {
        Json frozen = stub["inspect"];
        spec.inspect = [frozen](const std::string&) {
            InspectionResult result;
            result.ok = frozen["ok"].get<bool>();
            result.size_bytes = frozen["size_bytes"].get<long long>();
            if (frozen.contains("metadata")) {
                result.metadata = frozen["metadata"];
            }
            for (const auto& w : frozen.value("warnings", Json::array())) {
                result.warnings.push_back(w.get<std::string>());
            }
            for (const auto& e : frozen.value("errors", Json::array())) {
                result.errors.push_back(e.get<std::string>());
            }
            return result;
        };
    }
    return spec;
}

Registry registry_for_case(const Json& entry, const Json& oracle) {
    Registry registry;
    if (entry["registry"].get<std::string>() == "default") {
        for (const auto& row : oracle["adapters"]) {
            AdapterSpec spec;
            spec.format_id = row["format_id"].get<std::string>();
            spec.display_name = row["display_name"].get<std::string>();
            spec.import_data = row["import"].get<bool>();
            spec.notes = row["notes"].get<std::string>();
            for (const auto& ext : row["extensions"]) {
                spec.extensions.push_back(ext.get<std::string>());
            }
            registry.register_adapter(std::move(spec));
        }
    } else {
        for (const auto& stub : entry["stub"]) {
            registry.register_adapter(spec_from_stub(stub));
        }
    }
    return registry;
}

void run_preflight(const Json& oracle) {
    const Json& section = oracle["preflight"];
    const std::filesystem::path base =
        std::filesystem::temp_directory_path() / "pwb-conv14-preflight";
    std::filesystem::create_directories(base);
    int n = 0;
    for (const auto& entry : section["cases"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        const std::string kind = entry["fs"]["kind"].get<std::string>();
        const std::filesystem::path path = base / entry["file_name"].get<std::string>();
        if (kind == "file") {
            const std::string b64 = entry["fs"]["content_b64"].get<std::string>();
            // small base64 decoder (fixture sizes are tiny)
            static constexpr char kAlphabet[] =
                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
            std::string bytes;
            int buffer = 0;
            int bits = 0;
            for (const char ch : b64) {
                if (ch == '=') {
                    break;
                }
                const char* at = std::strchr(kAlphabet, ch);
                buffer = (buffer << 6) | static_cast<int>(at - kAlphabet);
                bits += 6;
                if (bits >= 8) {
                    bits -= 8;
                    bytes.push_back(static_cast<char>((buffer >> bits) & 0xFF));
                }
            }
            std::ofstream stream(path, std::ios::binary);
            stream << bytes;
        } else if (kind == "dir") {
            std::filesystem::create_directories(path);
        }

        Registry registry = registry_for_case(entry, oracle);
        ImportPreflightService service(std::move(registry),
                                       make_sniffer(entry["report"]["sniff"]));
        if (kind != "missing") {
            check(path_suffix_lower(path) == entry["fs"]["suffix"].get<std::string>(),
                  id + " suffix");
        }
        const PreflightReport report = service.inspect(path);
        Json want = entry["report"];
        want["path"] = path.string();
        const std::string mismatch = diff_text(report.to_dict(), want);
        check(mismatch.empty(), id + " report: " + mismatch);
    }

    for (const auto& entry : section["plans"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        const Json& base_case = *std::find_if(
            section["cases"].begin(), section["cases"].end(),
            [&](const Json& candidate) {
                return candidate["id"] == entry["case"];
            });
        const std::filesystem::path path = base / base_case["file_name"].get<std::string>();
        Registry registry = registry_for_case(base_case, oracle);
        ImportPreflightService service(
            std::move(registry), make_sniffer(base_case["report"]["sniff"]));
        std::optional<bool> managed;
        if (!entry["managed"].is_null()) {
            managed = entry["managed"].get<bool>();
        }
        std::optional<std::string> asset_name;
        if (!entry["asset_name"].is_null()) {
            asset_name = entry["asset_name"].get<std::string>();
        }
        try {
            const ImportPlan plan_value = service.plan(path, managed, asset_name,
                                                       entry["options"]);
            if (!entry["ok"].get<bool>()) {
                check(false, id + " should have failed");
                continue;
            }
            Json want = entry["plan"];
            want["source_path"] = path.string();
            const std::string mismatch = diff_text(plan_value.to_dict(), want);
            check(mismatch.empty(), id + " plan: " + mismatch);
        } catch (const std::runtime_error& ex) {
            check(!entry["ok"].get<bool>()
                      && std::string(ex.what()) == entry["error"].get<std::string>(),
                  id + " error: " + ex.what());
        }
    }
    std::filesystem::remove_all(base);
    std::printf("preflight: %d cases\n", n);
}

void run_fuzz(const Json& oracle) {
    int n = 0;
    for (const auto& entry : oracle["fuzz"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        const std::string name = entry["name"].get<std::string>();
        if (entry["ok"].get<bool>()) {
            try {
                const std::string path = safe_relative_path(name);
                check(path == entry["path"].get<std::string>(),
                      id + " path: " + path + " want "
                          + entry["path"].get<std::string>());
            } catch (const std::exception& ex) {
                check(false, id + " unexpectedly threw: " + ex.what());
            }
        } else {
            try {
                safe_relative_path(name);
                check(false, id + " should have been rejected");
            } catch (const UnsafePathError& ex) {
                check(std::string(ex.what()) == entry["error"].get<std::string>(),
                      id + " message: " + ex.what());
            } catch (const std::exception& ex) {
                check(false, id + " wrong exception type: " + ex.what());
            }
        }
    }
    std::printf("fuzz: %d cases\n", n);
}

void run_registry(const Json& oracle) {
    int n = 0;
    for (const auto& entry : oracle["registry"]) {
        if (entry["id"] == "replace") {
            continue;  // replayed below with the frozen expectations
        }
        ++n;
        Registry registry;
        AdapterSpec spec;
        spec.format_id = entry["id"] == "blank" ? "" : "demo";
        spec.extensions = {"demo"};
        try {
            registry.register_adapter(std::move(spec));
            if (entry["id"] == "duplicate") {
                AdapterSpec again;
                again.format_id = "demo";
                again.extensions = {"demo"};
                registry.register_adapter(std::move(again));
            }
            check(entry["id"] == "blank", entry["id"].get<std::string>()
                + " should have failed");
        } catch (const std::invalid_argument& ex) {
            check(std::string(ex.what()) == entry["error"].get<std::string>(),
                  entry["id"].get<std::string>() + " message: " + ex.what());
        }
    }
    // frozen replace-case semantics (registry["registry"] "replace" entry)
    for (const auto& entry : oracle["registry"]) {
        if (entry["id"] != "replace") {
            continue;
        }
        ++n;
        AdapterSpec spec;
        spec.format_id = "demo";
        spec.extensions = {"demo"};
        Registry registry;
        registry.register_adapter(spec);
        AdapterSpec updated;
        updated.format_id = "demo";
        updated.extensions = {"demo"};
        registry.register_adapter(std::move(updated), true);
        const AdapterSpec* adapter = registry.get("demo");
        check(adapter != nullptr, "replace keeps format_id reachable");
        const AdapterSpec* by_ext =
            registry.adapter_for_extension("demo");
        check(by_ext != nullptr
                  && by_ext->format_id
                      == entry["ext_lookup"].get<std::string>(),
              "replace ext lookup");
    }
    std::printf("registry: %d cases\n", n);
}

}  // namespace

int main() {
    const Json oracle = load_oracle();
    run_unicode(oracle);
    run_fuzz_nfc(oracle);
    run_safe_path(oracle);
    run_collision(oracle);
    run_sanitize(oracle);
    run_within_root(oracle);
    run_manifest(oracle);
    run_preflight(oracle);
    run_fuzz(oracle);
    run_registry(oracle);
    std::printf("%s: %d failure(s)\n", g_failures == 0 ? "PASS" : "FAIL",
                g_failures);
    return g_failures == 0 ? 0 : 1;
}
