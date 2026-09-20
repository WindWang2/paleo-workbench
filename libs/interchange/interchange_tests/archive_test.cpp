// interchange.archive — replay of the frozen Python oracle for the
// conv-14b kernels: native zip container (safe_members / extract_archive),
// atomic file publication, package build/verify/materialize runtime and the
// FLAC3D/Abaqus model adapters. Every expectation in
// fixtures/interchange_archive_oracle.json was produced by running the real
// paleo_workbench modules (see
// tools/oracle/generate_interchange_archive_fixtures.py); nothing here is
// hand-written except the C++-only seam checks at the end (cancel seam,
// decompression-bomb guard, native service), which assert OUR documented
// behavior, not Python's.

#include <pwb/domain/json.hpp>
#include <pwb/domain/sha256.hpp>
#include <pwb/interchange/atomic_file.hpp>
#include <pwb/interchange/contracts.hpp>
#include <pwb/interchange/manifest.hpp>
#include <pwb/interchange/model_adapters.hpp>
#include <pwb/interchange/package_runtime.hpp>
#include <pwb/interchange/path_safety.hpp>
#include <pwb/interchange/service.hpp>
#include <pwb/interchange/zip_archive.hpp>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>
#if defined(_WIN32)
#include <process.h>
inline int pwb_test_pid() { return _getpid(); }
#else
#include <unistd.h>
inline int pwb_test_pid() { return static_cast<int>(::getpid()); }
#endif

using pwb::domain::Json;
using pwb::domain::JsonDiff;
using pwb::domain::json_semantic_diff;
using namespace pwb::interchange;

#ifndef PWB_INTERCHANGE_ARCHIVE_FIXTURE
#define PWB_INTERCHANGE_ARCHIVE_FIXTURE "interchange_archive_oracle.json"
#endif

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

Json load_oracle() {
    std::ifstream stream(PWB_INTERCHANGE_ARCHIVE_FIXTURE, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open oracle fixture\n");
        std::exit(1);
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return Json::parse(buffer.str());
}

std::string diff_text(const Json& got, const Json& want) {
    Json got_norm = Json::parse(got.dump());
    Json want_norm = Json::parse(want.dump());
    const JsonDiff diff = json_semantic_diff(want_norm, got_norm);
    if (diff.equal) return "";
    return diff.path + ": " + diff.reason;
}

std::vector<std::string> sorted_list(const Json& array) {
    std::vector<std::string> out;
    for (const auto& item : array) out.push_back(item.get<std::string>());
    std::sort(out.begin(), out.end());
    return out;
}

// --- filesystem helpers ------------------------------------------------------

std::string read_file(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return {};
    std::ostringstream buffer;
    buffer << in.rdbuf();
    return buffer.str();
}

void write_file(const std::filesystem::path& path, std::string_view bytes) {
    std::filesystem::create_directories(path.parent_path());
    std::ofstream out(path, std::ios::binary);
    out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}

std::optional<std::string> file_digest(const std::filesystem::path& path) {
    return pwb::domain::Sha256::of_file(path);
}

std::string un_substitute_root(std::string text, const std::filesystem::path& root) {
    const std::string token = "{ROOT}";
    const std::string real = root.string();
    std::size_t pos = 0;
    while ((pos = text.find(real, pos)) != std::string::npos) {
        text.replace(pos, real.size(), token);
        pos += token.size();
    }
    return text;
}

Json un_substitute_root_json(Json value, const std::filesystem::path& root) {
    if (value.is_string()) {
        return Json(un_substitute_root(value.get<std::string>(), root));
    }
    if (value.is_array()) {
        Json out = Json::array();
        for (const auto& item : value) {
            out.push_back(un_substitute_root_json(item, root));
        }
        return out;
    }
    if (value.is_object()) {
        Json out = Json::object();
        for (auto it = value.begin(); it != value.end(); ++it) {
            out[it.key()] = un_substitute_root_json(it.value(), root);
        }
        return out;
    }
    return value;
}

std::string substitute_root(std::string text, const std::filesystem::path& root) {
    const std::string token = "{ROOT}";
    std::size_t pos = 0;
    while ((pos = text.find(token, pos)) != std::string::npos) {
        text.replace(pos, token.size(), root.string());
        pos += root.string().size();
    }
    return text;
}

Json substitute_root_json(Json value, const std::filesystem::path& root) {
    if (value.is_string()) {
        return Json(substitute_root(value.get<std::string>(), root));
    }
    if (value.is_array()) {
        Json out = Json::array();
        for (const auto& item : value) {
            out.push_back(substitute_root_json(item, root));
        }
        return out;
    }
    if (value.is_object()) {
        Json out = Json::object();
        for (auto it = value.begin(); it != value.end(); ++it) {
            out[it.key()] = substitute_root_json(it.value(), root);
        }
        return out;
    }
    return value;
}

// Forward declaration: bomb-guard helper (defined below).
const ZipEntryInfo* reader_find_read(ZipReader& reader, const std::string& name);

std::vector<std::string> list_rel_files(const std::filesystem::path& dir) {
    std::vector<std::string> rels;
    std::error_code ec;
    for (auto it = std::filesystem::recursive_directory_iterator(dir);
         it != std::filesystem::recursive_directory_iterator(); it.increment(ec)) {
        if (it->is_regular_file()) {
            rels.push_back(it->path().lexically_relative(dir).generic_string());
        }
    }
    std::sort(rels.begin(), rels.end());
    return rels;
}

// Python's residue freeze is sorted(rglob(*)) — directories included.
std::vector<std::string> list_rel_entries(const std::filesystem::path& dir) {
    std::vector<std::string> rels;
    std::error_code ec;
    for (auto it = std::filesystem::recursive_directory_iterator(dir);
         it != std::filesystem::recursive_directory_iterator(); it.increment(ec)) {
        rels.push_back(it->path().lexically_relative(dir).generic_string());
    }
    std::sort(rels.begin(), rels.end());
    return rels;
}

// Interpreter-specific JSON/OSError tails: compare the stable prefix through
// the first ": " separator only.
bool message_prefix_match(const std::string& got, const std::string& want) {
    const std::size_t cut = want.find(": ");
    if (cut == std::string::npos) return got == want;
    return got.compare(0, cut + 2, want, 0, cut + 2) == 0;
}

bool issue_equal(const Json& got, const Json& want) {
    if (got.at("severity") != want.at("severity") || got.at("code") != want.at("code")) {
        return false;
    }
    const std::string code = want.at("code").get<std::string>();
    const bool parser_tail = code == "corrupt-manifest" || code == "corrupt-project" ||
                             code == "corrupt-catalog";
    const std::string got_message = got.at("message").get<std::string>();
    const std::string want_message = want.at("message").get<std::string>();
    return parser_tail ? message_prefix_match(got_message, want_message)
                       : got_message == want_message;
}

// Compares verify reports; issues may be parser-tail-prefixed, so diff the
// envelope and pair the issues manually.
void check_report_issues(const Json& got, const Json& want, const std::string& what) {
    const Json& got_issues = got.at("issues");
    const Json& want_issues = want.at("issues");
    check(got_issues.size() == want_issues.size(),
          what + " issue count (got " + std::to_string(got_issues.size()) +
              ", want " + std::to_string(want_issues.size()) + ")");
    const std::size_t count = std::min(got_issues.size(), want_issues.size());
    for (std::size_t i = 0; i < count; ++i) {
        check(issue_equal(got_issues[i], want_issues[i]),
              what + " issue " + std::to_string(i) + " (got " +
                  got_issues[i].dump() + ", want " + want_issues[i].dump() + ")");
    }
}

void check_report_envelope(const Json& got, const Json& want,
                           const std::string& what) {
    for (const char* key : {"ok", "checked_entries", "total_size_bytes",
                            "project_name"}) {
        check(got.at(key) == want.at(key), std::string(what) + " " + key +
                                               " (got " + got.at(key).dump() +
                                               ", want " + want.at(key).dump() + ")");
    }
}

// --- zip helpers --------------------------------------------------------------

std::string base64_decode(const std::string& text) {
    static const std::string table =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out;
    int val = 0;
    int bits = 0;
    for (unsigned char c : text) {
        if (c == '=' || c == '\n' || c == '\r') continue;
        const std::size_t index = table.find(static_cast<char>(c));
        if (index == std::string::npos) continue;
        val = (val << 6) + static_cast<int>(index);
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            out.push_back(static_cast<char>((val >> bits) & 0xFF));
        }
    }
    return out;
}

std::filesystem::path write_zip_file(const std::filesystem::path& dir,
                                     const std::string& name,
                                     const std::string& zip_bytes) {
    const std::filesystem::path path = dir / name;
    write_file(path, zip_bytes);
    return path;
}

void build_tree(const std::filesystem::path& base, const Json& ops) {
    // cases reuse the "proj/" project name: clear the previous tree first,
    // mirroring the generator's build_tree cleanup.
    if (!ops.empty()) {
        const std::string first = ops[0]["path"].get<std::string>();
        const std::size_t slash = first.find('/');
        if (slash != std::string::npos) {
            std::error_code clean_ec;
            std::filesystem::remove_all(base / first.substr(0, slash), clean_ec);
        }
    }
    for (const auto& op : ops) {
        const std::string kind = op.at("op").get<std::string>();
        const std::filesystem::path path =
            base / op.at("path").get<std::string>();
        if (kind == "mkdir") {
            std::filesystem::create_directories(path);
        } else if (kind == "file") {
            std::filesystem::create_directories(path.parent_path());
            write_file(path, base64_decode(op.at("content_b64").get<std::string>()));
        } else if (kind == "symlink") {
            std::filesystem::create_directories(path.parent_path());
            std::filesystem::create_symlink(op.at("target").get<std::string>(), path);
        }
    }
}

std::string g_frozen_created_at;
std::string g_application_version;

Json options_from(const Json& frozen) {
    Json out = Json::object();
    out["external_policy"] = frozen.at("external_policy");
    out["include_outputs_only"] = frozen.at("include_outputs_only");
    out["include_formats"] = frozen.at("include_formats");
    out["include_provenance"] = frozen.at("include_provenance");
    return out;
}

PackageOptions to_options(const Json& frozen) {
    PackageOptions options;
    const std::string policy = frozen.at("external_policy").get<std::string>();
    if (policy == "vendor") options.external_policy = ExternalPolicy::VENDOR;
    else if (policy == "exclude") options.external_policy = ExternalPolicy::EXCLUDE;
    else options.external_policy = ExternalPolicy::KEEP;
    options.include_outputs_only =
        frozen.at("include_outputs_only").get<bool>();
    if (frozen.at("include_formats").is_array()) {
        std::vector<std::string> formats;
        for (const auto& item : frozen.at("include_formats")) {
            formats.push_back(item.get<std::string>());
        }
        options.include_formats = std::move(formats);
    }
    options.include_provenance = frozen.at("include_provenance").get<bool>();
    return options;
}

class StubCatalogSource final : public CatalogSource {
public:
    StubCatalogSource(const Json& spec, const std::filesystem::path& root) {
        for (const auto& asset : spec.at("assets")) {
            CatalogAssetRef ref;
            ref.id = asset.at("id").get<std::string>();
            ref.name = asset.at("name").get<std::string>();
            ref.type = asset.value("type", "table");
            assets_.push_back(ref);
        }
        for (const auto& version : spec.at("versions")) {
            CatalogVersionRef ref;
            ref.id = version.at("id").get<std::string>();
            ref.asset_id = version.at("asset_id").get<std::string>();
            ref.path = version.at("path").get<std::string>();
            ref.stage = version.at("stage").get<std::string>();
            ref.managed = version.at("managed").get<bool>();
            ref.size_bytes = version.value("size_bytes", -1LL);
            ref.format = version.value("format", "csv");
            by_asset_[ref.asset_id].push_back(ref);
        }
        for (auto it = spec.at("payloads").begin();
             it != spec.at("payloads").end(); ++it) {
            payloads_[it.key()] = root / it.value().get<std::string>();
        }
        for (const auto& run : spec.value("runs", Json::array())) {
            CatalogRunRef ref;
            ref.id = run.at("id").get<std::string>();
            ref.operation = run.at("operation").get<std::string>();
            ref.status = run.at("status").get<std::string>();
            runs_.push_back(ref);
        }
    }

    std::vector<CatalogAssetRef> list_assets() override { return assets_; }
    std::vector<CatalogVersionRef> list_versions(
        const std::string& asset_id) override {
        auto it = by_asset_.find(asset_id);
        return it == by_asset_.end() ? std::vector<CatalogVersionRef>{}
                                     : it->second;
    }
    std::filesystem::path resolve_path(const CatalogVersionRef& version) override {
        return payloads_.at(version.id);
    }
    void export_manifest() override { ++exported_; }
    std::vector<CatalogRunRef> list_runs() override { return runs_; }

private:
    std::vector<CatalogAssetRef> assets_;
    std::map<std::string, std::vector<CatalogVersionRef>> by_asset_;
    std::map<std::string, std::filesystem::path> payloads_;
    std::vector<CatalogRunRef> runs_;
    std::vector<CatalogVersionRef> all_versions_;

public:
    int exported_ = 0;
};

}  // namespace

// ---------------------------------------------------------------- sections --

namespace {

void run_safe_members(const Json& oracle, const std::filesystem::path& work) {
    int n = 0;
    for (const auto& entry : oracle["safe_members"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        const std::string zip_bytes =
            base64_decode(entry["zip_b64"].get<std::string>());
        const std::filesystem::path path =
            write_zip_file(work, "safe_" + id + ".zip", zip_bytes);
        try {
            ZipReader reader(path);
            const std::vector<std::string> names =
                safe_members(reader, entry["what"].get<std::string>());
            Json got = Json::array();
            for (const auto& name : names) got.push_back(name);
            check(diff_text(got, entry["expect"]["names"]).empty() &&
                      entry["expect"]["ok"].get<bool>(),
                  "safe_members/" + id);
        } catch (const UnsafePathError& exc) {
            check(!entry["expect"]["ok"].get<bool>() &&
                      exc.what() == entry["expect"]["message"].get<std::string>(),
                  "safe_members/" + id + " (got '" + exc.what() + "', want '" +
                      entry["expect"]["message"].get<std::string>() + "')");
        }
        std::error_code ec;
        std::filesystem::remove(path, ec);
    }
    std::printf("safe_members: %d cases\n", n);
}

void run_zip_reader(const Json& oracle, const std::filesystem::path& work) {
    int n = 0;
    for (const auto& entry : oracle["zip_reader"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        const std::filesystem::path path = write_zip_file(
            work, "reader_" + id + ".zip",
            base64_decode(entry["zip_b64"].get<std::string>()));
        ZipReader reader(path);
        Json names = Json::array();
        Json sizes = Json::array();
        Json crcs = Json::array();
        for (const auto& info : reader.infolist()) {
            names.push_back(info.name);
            sizes.push_back(static_cast<long long>(info.size));
            crcs.push_back(static_cast<long long>(info.crc32));
        }
        check(diff_text(names, entry["expect"]["names"]).empty() &&
                  diff_text(sizes, entry["expect"]["sizes"]).empty() &&
                  diff_text(crcs, entry["expect"]["crcs"]).empty(),
              "zip_reader/" + id);
    }
    std::printf("zip_reader: %d cases\n", n);
}

void run_zip_writer(const Json& oracle, const std::filesystem::path& work) {
    const Json& spec = oracle["zip_writer"];
    const std::filesystem::path path = work / "writer_out.zip";
    std::error_code ec;
    std::filesystem::remove(path, ec);
    {
        ZipWriter writer(path);
        for (const auto& member : spec["members"]) {
            writer.add_bytes(member["name"].get<std::string>(),
                             base64_decode(member["content_b64"].get<std::string>()));
        }
        writer.finish();
    }
    ZipReader reader(path);
    int n = 0;
    for (const auto& member : spec["members"]) {
        ++n;
        const std::string name = member["name"].get<std::string>();
        const ZipEntryInfo* info = reader.find(name);
        check(info != nullptr, "zip_writer missing member " + name);
        if (info == nullptr) continue;
        check(static_cast<long long>(info->crc32) ==
                  member["crc32"].get<long long>(),
              "zip_writer crc " + name);
        check(static_cast<long long>(info->size) == member["size"].get<long long>(),
              "zip_writer size " + name);
        check(static_cast<long long>(info->flags) ==
                  member["flag_bits"].get<long long>(),
              "zip_writer flag_bits " + name);
        check(static_cast<long long>(info->dos_time) == 0 &&
                  static_cast<long long>(info->dos_date) == 0x0021,
              "zip_writer fixed dos stamp " + name);
        const std::string payload = reader.read_entry_bytes(*info);
        check(pwb::domain::Sha256::of_bytes(payload) ==
                  pwb::domain::Sha256::of_bytes(
                      base64_decode(member["content_b64"].get<std::string>())),
              "zip_writer content " + name);
    }
    std::printf("zip_writer: %d members\n", n);
}

void run_extract(const Json& oracle, const std::filesystem::path& work) {
    int n = 0;
    for (const auto& entry : oracle["extract"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        const std::filesystem::path zip_path = write_zip_file(
            work, "extract_" + id + ".zip",
            base64_decode(entry["zip_b64"].get<std::string>()));
        const std::filesystem::path dest = work / ("extract_dest_" + id);
        std::filesystem::create_directories(dest);
        try {
            ZipReader reader(zip_path);
            const std::vector<std::filesystem::path> written =
                extract_archive(reader, dest, "package");
            Json rels = Json::array();
            for (const auto& path : written) {
                rels.push_back(std::filesystem::relative(path, dest).generic_string());
            }
            std::sort(rels.begin(), rels.end());
            Json digests = Json::object();
            for (const auto& rel : list_rel_files(dest)) {
                digests[rel] = *file_digest(dest / rel);
            }
            check(entry["expect"]["ok"].get<bool>() &&
                      diff_text(rels, entry["expect"]["written"]).empty() &&
                      diff_text(digests, entry["expect"]["digests"]).empty(),
                  "extract/" + id);
        } catch (const UnsafePathError& exc) {
            check(!entry["expect"]["ok"].get<bool>() &&
                      exc.what() == entry["expect"]["message"].get<std::string>(),
                  "extract/" + id + " message");
            const std::vector<std::string> residue = list_rel_entries(dest);
            check(residue == sorted_list(entry["expect"]["residue"]),
                  "extract/" + id + " zero residue (got " +
                      std::to_string(residue.size()) + " entries)");
        }
    }
    std::printf("extract: %d cases\n", n);
}

void run_atomic(const Json& oracle, const std::filesystem::path& work) {
    int n = 0;
    for (const auto& entry : oracle["atomic"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        if (id == "replace_ok") {
            const std::filesystem::path temp = work / ".atomic_target.txt.tmp123";
            const std::filesystem::path target = work / "atomic_target.txt";
            write_file(temp, "temp payload");
            std::error_code ec;
            std::filesystem::remove(target, ec);
            os_replace_atomic(temp, target);
            check(!std::filesystem::exists(temp) &&
                      *file_digest(target) ==
                          entry["expect"]["target_digest"].get<std::string>(),
                  "atomic/" + id);
        } else if (id == "replace_missing_src") {
            bool threw = false;
            try {
                os_replace_atomic(work / ".atomic_missing.tmp",
                                  work / "atomic_out2.txt");
            } catch (const std::exception&) {
                threw = true;
            }
            const bool expect_error =
                entry["expect"]["decision"].get<std::string>() == "error";
            check(threw == expect_error, "atomic/" + id);
        } else if (id == "atomic_output_pending") {
            const std::filesystem::path out = work / "ao_out.dat";
            std::error_code ec;
            std::filesystem::remove(out, ec);
            {
                AtomicOutputFile guard(out);
                check(!std::filesystem::exists(out), "atomic/pending absent");
                const std::string payload = std::string("atomic-bytes-\x00\x01", 15);
                write_file(guard.temp_path(), payload);
                guard.commit();
            }
            std::vector<std::string> leftovers;
            std::error_code ec2;
            for (auto it = std::filesystem::directory_iterator(work);
                 it != std::filesystem::directory_iterator(); it.increment(ec2)) {
                const std::string name = it->path().filename().string();
                if (name.rfind(".ao_out.dat.", 0) == 0) leftovers.push_back(name);
            }
            check(*file_digest(out) ==
                          entry["expect"]["target_digest"].get<std::string>() &&
                      leftovers.empty(),
                  "atomic/" + id);
        } else if (id == "atomic_output_rollback") {
            const std::filesystem::path out = work / "ao_failed.dat";
            std::error_code ec;
            std::filesystem::remove(out, ec);
            try {
                AtomicOutputFile guard(out);
                write_file(guard.temp_path(), "partial");
                throw std::runtime_error("boom");
            } catch (const std::runtime_error&) {
            }
            std::vector<std::string> leftovers;
            std::error_code ec2;
            for (auto it = std::filesystem::directory_iterator(work);
                 it != std::filesystem::directory_iterator(); it.increment(ec2)) {
                const std::string name = it->path().filename().string();
                if (name.rfind(".ao_failed.dat.", 0) == 0) leftovers.push_back(name);
            }
            check(!std::filesystem::exists(out) && leftovers.empty(),
                  "atomic/" + id);
        }
    }
    std::printf("atomic: %d cases\n", n);
}

void run_verify_zip(const Json& oracle, const std::filesystem::path& work) {
    int n = 0;
    for (const auto& entry : oracle["verify_zip"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        const std::filesystem::path path = write_zip_file(
            work, id + ".zip", base64_decode(entry["zip_b64"].get<std::string>()));
        const PackageVerifyReport report =
            verify_zip_container(path, entry["deep"].get<bool>());
        Json got = report.to_dict();
        got["package_path"] = substitute_root(
            entry["expect"]["package_path"].get<std::string>(), work);
        check_report_envelope(got, entry["expect"], "verify_zip/" + id);
        check_report_issues(got, entry["expect"], "verify_zip/" + id);
    }
    std::printf("verify_zip: %d cases\n", n);
}

void run_verify_dir(const Json& oracle, const std::filesystem::path& work) {
    int n = 0;
    for (const auto& entry : oracle["verify_dir"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        const std::filesystem::path tree_root = work / id;
        build_tree(tree_root, entry["tree"]);
        const PackageVerifyReport report =
            verify_package(tree_root, entry["deep"].get<bool>());
        Json got = report.to_dict();
        const Json want = substitute_root_json(entry["expect"], work);
        got["package_path"] = want["package_path"];
        check_report_envelope(got, want, "verify_dir/" + id);
        check_report_issues(got, want, "verify_dir/" + id);
    }
    std::printf("verify_dir: %d cases\n", n);
}

void run_materialize(const Json& oracle, const std::filesystem::path& work) {
    int n = 0;
    for (const auto& entry : oracle["materialize"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        const Json& spec = entry["spec"];
        const std::filesystem::path source = work / entry["source_name"].get<std::string>();
        if (spec.contains("zip_b64")) {
            write_file(source, base64_decode(spec["zip_b64"].get<std::string>()));
        } else if (spec.contains("tree")) {
            build_tree(source, spec["tree"]);
        }
        // else: the source is intentionally absent (unrecognized package)
        const std::filesystem::path dest = work / ("dest_" + id);
        std::filesystem::create_directories(dest);
        if (spec.contains("pre_dest")) {
            build_tree(dest, spec["pre_dest"]);
        }
        try {
            const std::filesystem::path target = materialize_package(source, dest);
            if (id == "open_package" || id == "open_fail_closed") {
                check(entry["expect"]["ok"].get<bool>() &&
                          target.filename().string() ==
                              entry["expect"]["target_name"].get<std::string>(),
                      "materialize/" + id + " target name");
                // verify runs on the materialized tree; compare the report
                const PackageVerifyReport report = verify_package(target, true);
                check(report.ok() ==
                          entry["expect"]["report_ok"].get<bool>(),
                      "materialize/" + id + " report_ok");
                check(report.checked_entries ==
                          entry["expect"]["checked_entries"].get<long long>(),
                      "materialize/" + id + " checked_entries");
                if (entry["expect"].contains("issue_codes")) {
                    std::vector<std::string> got_codes;
                    for (const auto& issue : report.errors()) {
                        got_codes.push_back(issue.code);
                    }
                    check(diff_text(Json(got_codes),
                                    entry["expect"]["issue_codes"]).empty(),
                          "materialize/" + id + " issue codes");
                }
                continue;
            }
            std::vector<std::string> rels;
            std::error_code ec;
            for (auto it = std::filesystem::recursive_directory_iterator(target);
                 it != std::filesystem::recursive_directory_iterator();
                 it.increment(ec)) {
                if (it->is_regular_file()) {
                    rels.push_back(
                        it->path().lexically_relative(target).generic_string());
                }
            }
            std::sort(rels.begin(), rels.end());
            Json got = Json::object();
            got["ok"] = true;
            got["target_name"] = target.filename().string();
            got["files"] = rels;
            Json want = Json::object();
            want["ok"] = entry["expect"]["ok"];
            want["target_name"] = entry["expect"]["target_name"];
            want["files"] = entry["expect"]["files"];
            check(diff_text(got, want).empty(),
                  "materialize/" + id + " " + diff_text(got, want));
        } catch (const std::exception& exc) {
            const Json want = substitute_root_json(entry["expect"], work);
            if (want["ok"].get<bool>()) {
                check(false, "materialize/" + id +
                                 " unexpected throw: " + exc.what());
            } else {
                check(std::string(exc.what()) ==
                          want["message"].get<std::string>(),
                      "materialize/" + id + " (got '" + exc.what() + "', want '" +
                          want["message"].get<std::string>() + "')");
            }
            if (!want["ok"].get<bool>() && want.contains("residue")) {
                const std::vector<std::string> residue = list_rel_entries(dest);
                check(diff_text(Json(residue), want["residue"]).empty(),
                      "materialize/" + id + " residue");
            }
        }
        if (id == "open_package") {
            // covered by the generic flow above; nothing extra
        }
    }
    std::printf("materialize: %d cases\n", n);
}

void run_build_package(const Json& oracle, const std::filesystem::path& work) {
    int n = 0;
    for (const auto& entry : oracle["build_package"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        const std::string flow = entry["flow"].get<std::string>();
        if (entry.contains("tree") && !entry["tree"].is_null()) {
            build_tree(work, entry["tree"]);
        }
        const std::filesystem::path project_file = work / "proj/proj.paleo.json";
        std::unique_ptr<StubCatalogSource> catalog;
        if (!entry["catalog"].is_null()) {
            catalog = std::make_unique<StubCatalogSource>(entry["catalog"], work);
        }
        const PackageOptions options = to_options(entry["options"]);
        PackageBuilder builder(project_file, catalog.get(), options,
                               g_application_version);
        builder.set_created_at_provider(
            [] { return g_frozen_created_at; });

        // Python froze these flow dir names inside the expect messages.
        const std::string flow_dir =
            id == "publish_conflict" ? "out_conflict"
            : id == "symlink_artifact" ? "out_symlink"
            : id == "zip_dir_symlink" ? "out_zipsym"
                                      : "out_" + id;
        if (flow == "build") {
            const PackagePlan plan = builder.plan();
            const std::filesystem::path out_dir = work / flow_dir;
            const BuildResult result = builder.build(out_dir);
            const std::string manifest_text =
                read_file(result.package_dir / "manifest.json");
            Json got = Json::object();
            got["plan_summary"] = plan.summary();
            got["manifest_json"] =
                un_substitute_root_json(Json::parse(manifest_text), work);
            got["files"] = list_rel_files(result.package_dir);
            const PackageVerifyReport verify = verify_package(result.package_dir, true);
            Json want = entry["expect"];
            check(diff_text(got["plan_summary"], want["plan_summary"]).empty(),
                  "build_package/" + id + " plan " +
                      diff_text(got["plan_summary"], want["plan_summary"]));
            check(diff_text(got["manifest_json"], want["manifest_json"]).empty(),
                  "build_package/" + id + " manifest " +
                      diff_text(got["manifest_json"], want["manifest_json"]));
            // Full byte-layout freeze: dumps() must be byte-identical to
            // Python's json.dumps(..., ensure_ascii=False, indent=1), with
            // machine-local absolute paths normalized to {ROOT}.
            const std::string manifest_normalized =
                un_substitute_root(manifest_text, work);
            check(manifest_normalized == want["manifest_text"].get<std::string>(),
                  "build_package/" + id + " manifest bytes");
            check(diff_text(got["files"], want["files"]).empty(),
                  "build_package/" + id + " files " +
                      diff_text(got["files"], want["files"]));
            check(verify.ok() == want["verify_ok"].get<bool>(),
                  "build_package/" + id + " verify_ok");
            check(result.package_dir.filename().string() ==
                      want["package_dir_name"].get<std::string>(),
                  "build_package/" + id + " dir name");
            Json got_wrapper = Json::object();
            got_wrapper["issues"] = verify.to_dict()["issues"];
            Json want_wrapper = Json::object();
            want_wrapper["issues"] = want["verify_issues"];
            check_report_issues(got_wrapper, want_wrapper, "build_package/" + id);
        } else if (flow == "build_twice") {
            const std::filesystem::path out_dir = work / flow_dir;
            (void)builder.build(out_dir);
            Json issues = Json::array();
            std::string message;
            try {
                (void)builder.build(out_dir);
            } catch (const std::exception& exc) {
                message = exc.what();
            }
            check(message == substitute_root(
                                  entry["expect"]["message"].get<std::string>(),
                                  work),
                  "build_package/" + id + " conflict message (got '" + message +
                      "')");
            std::vector<std::string> listing;
            std::error_code ec;
            for (auto it = std::filesystem::directory_iterator(out_dir);
                 it != std::filesystem::directory_iterator(); it.increment(ec)) {
                listing.push_back(it->path().filename().string());
            }
            std::sort(listing.begin(), listing.end());
            check(diff_text(Json(listing), entry["expect"]["dir_listing"]).empty(),
                  "build_package/" + id + " dir listing");
        } else if (flow == "build_fail") {
            const std::filesystem::path out_dir = work / flow_dir;
            std::string message;
            try {
                (void)builder.build(out_dir);
            } catch (const std::exception& exc) {
                message = exc.what();
            }
            check(message == substitute_root(
                                  entry["expect"]["message"].get<std::string>(),
                                  work),
                  "build_package/" + id + " fail message (got '" + message + "')");
            std::vector<std::string> residue;
            std::error_code ec;
            if (std::filesystem::exists(out_dir)) {
                for (auto it = std::filesystem::directory_iterator(out_dir);
                     it != std::filesystem::directory_iterator();
                     it.increment(ec)) {
                    residue.push_back(it->path().filename().string());
                }
            }
            std::sort(residue.begin(), residue.end());
            check(diff_text(Json(residue), entry["expect"]["residue"]).empty(),
                  "build_package/" + id + " residue");
        } else if (flow == "build_zip_symlink") {
            const std::filesystem::path out_dir = work / flow_dir;
            const BuildResult result = builder.build(out_dir);
            std::filesystem::create_symlink(
                "/etc/hostname",
                result.package_dir / "proj.artifacts/raw/link.bin");
            std::string message;
            try {
                (void)zip_package_dir(
                    result.package_dir,
                    work / "proj-sym.paleopkg.zip");
            } catch (const std::exception& exc) {
                message = exc.what();
            }
            check(message == substitute_root(
                                  entry["expect"]["message"].get<std::string>(),
                                  work),
                  "build_package/" + id + " zipsym message (got '" + message +
                      "')");
            check(!std::filesystem::exists(work / "proj-sym.paleopkg.zip") ==
                      entry["expect"]["zip_absent"].get<bool>(),
                  "build_package/" + id + " zip absent");
            check(!std::filesystem::exists(
                      work / ".proj-sym.paleopkg.zip.tmp") ==
                      entry["expect"]["tmp_absent"].get<bool>(),
                  "build_package/" + id + " tmp absent");
        } else if (flow == "build_zip") {
            const std::filesystem::path out_dir = work / flow_dir;
            const BuildResult result = builder.build(out_dir);
            const std::filesystem::path zip_path =
                zip_package_dir(result.package_dir,
                                work / entry["expect"]["zip_name"].get<std::string>());
            check(zip_path.filename().string() ==
                      entry["expect"]["zip_name"].get<std::string>(),
                  "build_package/" + id + " zip name");
            ZipReader reader(zip_path);
            std::vector<std::string> members;
            for (const auto& info : reader.infolist()) {
                members.push_back(info.name);
            }
            std::sort(members.begin(), members.end());
            check(diff_text(Json(members), entry["expect"]["members"]).empty(),
                  "build_package/" + id + " members");
            const Json& want_crcs = entry["expect"]["crcs"];
            int crc_checked = 0;
            for (auto it = want_crcs.begin(); it != want_crcs.end(); ++it) {
                const ZipEntryInfo* info = reader.find(it.key());
                check(info != nullptr, "build_package/" + id + " member " + it.key());
                if (info == nullptr) continue;
                check(static_cast<long long>(info->crc32) ==
                          it.value().get<long long>(),
                      "build_package/" + id + " crc " + it.key());
                ++crc_checked;
            }
            check(crc_checked > 0, "build_package/" + id + " crcs present");
            check(verify_zip_container(zip_path, true).ok() ==
                      entry["expect"]["verify_ok"].get<bool>(),
                  "build_package/" + id + " zip verify");
            check(!std::filesystem::exists(out_dir / ".proj.staging"),
                  "build_package/" + id + " staging removed");
        }
    }
    std::printf("build_package: %d cases\n", n);
}

void run_model_parse(const Json& oracle, const std::filesystem::path& work) {
    int n = 0;
    for (const auto& entry : oracle["model_parse"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        const std::string fmt = entry["format"].get<std::string>();
        const std::filesystem::path path =
            work / (id + "." + fmt);
        write_file(path, base64_decode(entry["content_b64"].get<std::string>()));
        const MeshFacts facts =
            fmt == "inp" ? parse_abaqus(path) : parse_flac3d(path);
        Json got = Json::object();
        got["gridpoints"] = facts.gridpoints;
        got["zones"] = facts.zones;
        got["problems"] = facts.problems;
        check(diff_text(got, entry["expect"]).empty(),
              "model_parse/" + id + " " + diff_text(got, entry["expect"]));
    }
    std::printf("model_parse: %d cases\n", n);
}

const ModelAdapter* adapter_for(const ModelAdapterRegistry& registry,
                                const std::string& format_id) {
    return registry.get(format_id);
}

void run_model_adapter(const Json& oracle, const std::filesystem::path& work) {
    const ModelAdapterRegistry registry = build_model_adapter_registry();
    const std::filesystem::path work_root = work / "adapter_work";
    std::filesystem::create_directories(work_root);
    for (auto it = oracle["model_adapter_pre_files"].begin();
         it != oracle["model_adapter_pre_files"].end(); ++it) {
        write_file(work / it.key(),
                   base64_decode(it.value().get<std::string>()));
    }

    int n = 0;
    for (const auto& entry : oracle["model_adapter"]) {
        ++n;
        const std::string id = entry["id"].get<std::string>();
        const std::string kind = entry["kind"].get<std::string>();
        const ModelAdapter* adapter = entry["format_id"].is_string()
            ? adapter_for(registry, entry["format_id"].get<std::string>())
            : nullptr;
        const Json expect = substitute_root_json(entry["expect"], work);

        if (kind == "capability") {
            Json got = adapter->capability().to_dict();
            check(diff_text(got, expect["capability"]).empty(),
                  "model_adapter/" + id + " " + diff_text(got, expect["capability"]));
        } else if (kind == "plan_export") {
            const std::filesystem::path source = work / "writer/plan.f3grid";
            const std::filesystem::path target =
                substitute_root(entry["target"].get<std::string>(), work);
            try {
                const ExportPlan plan = adapter->plan_export(
                    source, target, entry["options"]);
                check(expect["ok"].get<bool>() &&
                          diff_text(plan.to_dict(), expect["value"]).empty(),
                      "model_adapter/" + id + " " +
                          diff_text(plan.to_dict(), expect["value"]));
            } catch (const FormatNotSupportedError& exc) {
                check(!expect["ok"].get<bool>() &&
                          expect["error"].get<std::string>() ==
                              "format-not-supported" &&
                          exc.what() == expect["message"].get<std::string>(),
                      "model_adapter/" + id + " (got '" + exc.what() + "')");
            }
        } else if (kind == "plan_import") {
            const std::filesystem::path source =
                substitute_root(entry["source"].get<std::string>(), work);
            const InspectionResult inspection = adapter->inspect(source);
            const ImportPlan plan = adapter->plan_import(
                source, inspection, entry["managed"].get<bool>());
            check(diff_text(plan.to_dict(), expect["value"]).empty(),
                  "model_adapter/" + id + " " +
                      diff_text(plan.to_dict(), expect["value"]));
        } else if (kind == "import") {
            bool threw = false;
            std::string message;
            try {
                adapter->import_data();
            } catch (const FormatNotSupportedError& exc) {
                threw = true;
                message = exc.what();
            }
            check(threw && message == expect["message"].get<std::string>(),
                  "model_adapter/" + id + " (got '" + message + "')");
        } else if (kind == "export") {
            const std::filesystem::path target =
                substitute_root(entry["target"].get<std::string>(), work);
            ExportPlan plan;
            plan.format_id = entry["format_id"].get<std::string>();
            plan.target_path = target.string();
            plan.options = entry["options"];
            const std::filesystem::path written =
                adapter->export_data(plan);
            const std::string payload = read_file(written);
            Json got = Json::object();
            got["target_name"] = written.filename().string();
            got["digest"] = pwb::domain::Sha256::of_bytes(payload);
            std::vector<std::string> leftovers;
            std::error_code ec;
            for (auto it = std::filesystem::directory_iterator(work_root);
                 it != std::filesystem::directory_iterator(); it.increment(ec)) {
                const std::string name = it->path().filename().string();
                if (name.rfind(".exported.f3grid.", 0) == 0) leftovers.push_back(name);
            }
            got["temp_cleaned"] = leftovers.empty();
            const MeshFacts facts = parse_flac3d(written);
            Json facts_json = Json::object();
            facts_json["gridpoints"] = facts.gridpoints;
            facts_json["zones"] = facts.zones;
            facts_json["problems"] = facts.problems;
            got["facts"] = facts_json;
            check(diff_text(got, expect["value"]).empty(),
                  "model_adapter/" + id + " " + diff_text(got, expect["value"]));
        } else if (kind == "verify_output") {
            const std::filesystem::path target =
                substitute_root(entry["target"].get<std::string>(), work);
            if (entry.contains("file_content") && !entry["file_content"].is_null()) {
                write_file(target,
                           base64_decode(entry["file_content"].get<std::string>()));
            }
            ExportPlan plan;
            plan.format_id = entry["format_id"].get<std::string>();
            plan.target_path = target.string();
            plan.options = entry["options"];
            const ExportVerification verification =
                adapter->verify_output(target, plan);
            check(diff_text(verification.summary(), expect["value"]).empty(),
                  "model_adapter/" + id + " " +
                      diff_text(verification.summary(), expect["value"]));
        } else if (kind == "inspect") {
            const std::filesystem::path source =
                substitute_root(entry["source"].get<std::string>(), work);
            if (entry.contains("file_content") && !entry["file_content"].is_null()) {
                write_file(source,
                           base64_decode(entry["file_content"].get<std::string>()));
            }
            const InspectionResult inspection = adapter->inspect(source);
            if (expect.value("prefix", false)) {
                // OSError strerror tails are platform-specific: assert the
                // frozen stable prefix ("无法读取文件状态: ") only.
                check(!inspection.ok && !inspection.errors.empty() &&
                          !expect["value"]["errors"].empty() &&
                          message_prefix_match(
                              inspection.errors[0],
                              expect["value"]["errors"][0].get<std::string>()),
                      "model_adapter/" + id + " prefix (got '" +
                          (inspection.errors.empty() ? std::string()
                                                     : inspection.errors[0]) +
                          "')");
            } else {
                check(diff_text(inspection.summary(entry["format_id"].get<std::string>()),
                                expect["value"])
                          .empty(),
                      "model_adapter/" + id + " " +
                          diff_text(
                              inspection.summary(entry["format_id"].get<std::string>()),
                              expect["value"]));
            }
        } else if (kind == "registry_matrix") {
            check(diff_text(registry.capability_matrix(), expect["value"]).empty(),
                  "model_adapter/" + id + " " +
                      diff_text(registry.capability_matrix(), expect["value"]));
        }
    }
    std::printf("model_adapter: %d cases\n", n);
}

// C++-only seam checks (documented behavior beyond the Python surface).
void run_seam_checks(const Json& oracle, const std::filesystem::path& work) {
    // cancel seam: extraction aborts before writing anything when cancelled
    const std::filesystem::path zip_path = write_zip_file(
        work, "cancel.zip",
        base64_decode(oracle["extract"][0]["zip_b64"].get<std::string>()));
    ZipReader reader(zip_path);
    CancelToken token;
    token.cancel("test");
    const std::filesystem::path dest = work / "cancel_dest";
    std::filesystem::create_directories(dest);
    bool cancelled = false;
    try {
        (void)extract_archive(reader, dest, "package", token);
    } catch (const CancelledError&) {
        cancelled = true;
    }
    check(cancelled && list_rel_files(dest).empty(),
          "seam: cancel leaves nothing written");

    // decompression-bomb guard: central directory lies about the size
    const std::filesystem::path lie_path = work / "bomb.zip";
    {
        ZipWriter writer(lie_path);
        writer.add_bytes("big.bin", std::string(256 * 1024, 'A'));
        writer.finish();
    }
    std::string lie_bytes = read_file(lie_path);
    const std::size_t cd_pos = lie_bytes.rfind("PK\x01\x02");
    check(cd_pos != std::string::npos, "seam: bomb zip has central directory");
    if (cd_pos != std::string::npos) {
        // uncompressed size lives at cd_pos+24 (LE32)
        const unsigned tiny = 16;
        std::memcpy(&lie_bytes[cd_pos + 24], &tiny, sizeof(tiny));
        write_file(lie_path, lie_bytes);
        ZipReader liar(lie_path);
        bool guarded = false;
        try {
            (void)reader_find_read(liar, "big.bin");
        } catch (const ZipError& exc) {
            guarded = std::string(exc.what()).find("exceeds declared") !=
                      std::string::npos;
        }
        check(guarded, "seam: bomb guard rejects undersized declaration");
    }

    // native service facade
    NativeInterchangeService service;
    const Json* frozen_matrix = nullptr;
    for (const auto& entry : oracle["model_adapter"]) {
        if (entry["id"] == "capability_matrix") frozen_matrix = &entry["expect"]["value"];
    }
    check(frozen_matrix != nullptr &&
              diff_text(service.capability_matrix(), *frozen_matrix).empty(),
          "seam: service capability matrix matches frozen registry");
    check(service.adapter_for_extension("f3grid") != nullptr &&
              service.adapter_for_extension("f3grid")->format_id ==
                  "flac3d_f3grid",
          "seam: service extension lookup");
    bool import_throws = false;
    try {
        service.adapter("flac3d_f3grid")->import_data();
    } catch (const FormatNotSupportedError&) {
        import_throws = true;
    }
    check(import_throws, "seam: service import path throws");

    // unknown format surfaces as FormatNotSupportedError, never a crash
    bool unknown_throws = false;
    try {
        (void)service.inspect("nope", work / "whatever");
    } catch (const FormatNotSupportedError&) {
        unknown_throws = true;
    }
    check(unknown_throws, "seam: unknown format rejected loudly");
}

const ZipEntryInfo* reader_find_read(ZipReader& reader, const std::string& name) {
    const ZipEntryInfo* info = reader.find(name);
    if (info == nullptr) throw ZipError("missing entry");
    std::string sink;
    reader.read_entry(*info, [&](std::string_view chunk) { sink += chunk; });
    return info;
}

}  // namespace

int main() {
    const Json oracle = load_oracle();
#if defined(_WIN32)
    // mkdtemp is POSIX-only; same contract (a fresh unique created
    // directory) via the temp root + pid/suffix probe loop.
    std::filesystem::path work;
    for (unsigned attempt = 0; attempt < 512; ++attempt) {
        const std::filesystem::path candidate =
            std::filesystem::temp_directory_path() /
            ("pwb_interchange_archive_" +
             std::to_string(pwb_test_pid()) + "_" +
             std::to_string(attempt));
        std::error_code ec;
        if (std::filesystem::create_directory(candidate, ec)) {
            work = candidate;
            break;
        }
    }
    if (work.empty()) {
        std::fprintf(stderr, "FAIL mkdtemp-equivalent\\n");
        return 1;
    }
#else
    char template_path[] = "/tmp/pwb_interchange_archive_XXXXXX";
    const char* created = mkdtemp(template_path);
    if (created == nullptr) {
        std::fprintf(stderr, "FAIL mkdtemp\\n");
        return 1;
    }
    const std::filesystem::path work(created);
#endif
    g_frozen_created_at =
        oracle["meta"]["frozen_created_at"].get<std::string>();
    g_application_version =
        oracle["meta"]["package_version"].get<std::string>();

    run_safe_members(oracle, work);
    run_zip_reader(oracle, work);
    run_zip_writer(oracle, work);
    run_extract(oracle, work);
    run_atomic(oracle, work);
    run_verify_zip(oracle, work);
    run_verify_dir(oracle, work);
    run_materialize(oracle, work);
    run_build_package(oracle, work);
    run_model_parse(oracle, work);
    run_model_adapter(oracle, work);
    run_seam_checks(oracle, work);

    std::error_code ec;
    std::filesystem::remove_all(work, ec);

    if (g_failures > 0) {
        std::fprintf(stderr, "%d checks, %d FAILED\n", g_checks, g_failures);
        return 1;
    }
    std::printf("interchange.archive: %d checks passed\n", g_checks);
    return 0;
}
