// interchange.dependency_audit — line-10 port of dependency_audit.py: the
// status classification rules (valid / missing / changed / unknown /
// relink_candidate), the hash budget degradation, the refusing-to-guess
// relink ladder and the apply_relink human-confirmation rule, verified
// against real files on disk including a tamper (negative self-check).

#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <pwb/interchange/dependency_audit.hpp>

namespace pi = pwb::interchange;
using pwb::domain::Json;

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

template <typename Fn>
std::string expect_throw(Fn&& fn) {
    try {
        fn();
    } catch (const std::exception& exc) {
        return exc.what();
    }
    return "<no throw>";
}

// --- fixture -----------------------------------------------------------------

std::string g_dir;

void write_file(const std::string& name, const std::string& content) {
    std::ofstream stream(g_dir + "/" + name, std::ios::binary | std::ios::trunc);
    stream << content;
}

std::string sha_of(const std::string& name) {
    return *pi::sha256_file(g_dir + "/" + name);
}

long long size_of(const std::string& name) {
    return static_cast<long long>(std::filesystem::file_size(g_dir + "/" + name));
}

// In-memory ILinkableCatalog over the fixture files.
class FakeCatalog final : public pi::ILinkableCatalog {
public:
    std::vector<pi::CatalogAssetRef> list_assets() override {
        return {{"a1", "asset-1", "raw"}};
    }
    std::vector<pi::CatalogVersionRef> list_versions(const std::string&) override {
        return versions;
    }
    std::filesystem::path resolve_path(const pi::CatalogVersionRef& version) override {
        return std::filesystem::path(version.path);
    }
    pi::ILinkableCatalog::LinkResult link_external(const std::filesystem::path& path,
                                                   const std::string& name,
                                                   Json metadata) override {
        ++link_calls;
        last_link_name = name;
        last_link_metadata = metadata;
        return {"a-new", "v-relinked"};
    }

    std::vector<pi::CatalogVersionRef> versions;
    int link_calls = 0;
    std::string last_link_name;
    Json last_link_metadata = Json::object();
};

int main() {
    // Isolated temp workspace.
    g_dir = (std::filesystem::temp_directory_path() / "pwb_interchange_audit_test")
                .string();
    std::filesystem::remove_all(g_dir);
    std::filesystem::create_directories(g_dir);
    write_file("a.bin", "AAAA-BBBB-CCCC-DDDD");           // known payload
    write_file("b.bin", "0123456789");                     // 10 bytes, will "change"
    write_file("copy_of_a.bin", "AAAA-BBBB-CCCC-DDDD");    // relink candidate
    write_file("same_size.bin", "012345678X");             // same size, different hash

    FakeCatalog catalog;
    auto make_version = [&](const std::string& id, const std::string& file,
                            bool managed, const std::string& sha,
                            long long size) {
        pi::CatalogVersionRef version;
        version.id = id;
        version.asset_id = "a1";
        version.stage = "input";
        version.managed = managed;
        version.format = "bin";
        version.path = file;
        version.sha256 = sha;
        version.size_bytes = size;
        return version;
    };
    catalog.versions.push_back(
        make_version("v-valid", g_dir + "/a.bin", true, sha_of("a.bin"),
                     size_of("a.bin")));
    catalog.versions.push_back(
        make_version("v-missing", g_dir + "/gone.bin", true, "aa", 10));
    catalog.versions.push_back(
        make_version("v-changed", g_dir + "/b.bin", true,
                     "0000000000000000000000000000000000000000000000000000000000000000",
                     size_of("b.bin")));
    catalog.versions.push_back(
        make_version("v-size-changed", g_dir + "/b.bin", true,
                     sha_of("b.bin"), 999));
    catalog.versions.push_back(
        make_version("v-unknown-external", g_dir + "/a.bin", false, "", -1));
    catalog.versions.push_back(
        make_version("v-tamper", g_dir + "/same_size.bin", true,
                     sha_of("b.bin"), size_of("same_size.bin")));

    pi::ExternalDependencyAuditor auditor(&catalog);
    const pi::DependencyAuditReport report = auditor.audit();

    check(report.records.size() == 6, "one record per version");
    auto status_of = [&](const std::string& id) {
        for (const auto& record : report.records) {
            if (record.version_id == id) return record.status;
        }
        return pi::DependencyStatus::MISSING;
    };
    check(status_of("v-valid") == pi::DependencyStatus::VALID, "valid classified");
    check(status_of("v-missing") == pi::DependencyStatus::MISSING, "missing classified");
    check(status_of("v-changed") == pi::DependencyStatus::CHANGED,
          "same-size different-hash is changed (identity = content)");
    check(status_of("v-size-changed") == pi::DependencyStatus::CHANGED,
          "size mismatch is changed");
    check(status_of("v-unknown-external") == pi::DependencyStatus::UNKNOWN,
          "external without hash is unknown");
    check(status_of("v-tamper") == pi::DependencyStatus::CHANGED,
          "tampered payload detected by hash");
    check(!report.ok(), "report with changed records is not ok");
    const Json summary = report.summary();
    check(summary["total"] == 6, "summary total");
    check(summary["counts"]["valid"] == 1, "summary counts valid");
    check(summary["counts"]["changed"] == 3, "summary counts changed");

    // Hash budget exhaustion degrades to unknown, never to a fake verdict.
    catalog.versions.clear();
    catalog.versions.push_back(
        make_version("v-budget", g_dir + "/a.bin", true, sha_of("a.bin"),
                     size_of("a.bin")));
    const pi::DependencyAuditReport budget_report =
        pi::ExternalDependencyAuditor(&catalog, 1).audit();
    check(budget_report.records.front().status == pi::DependencyStatus::UNKNOWN,
          "over-budget hash degrades to unknown");
    check(budget_report.records.front().detail == "超过哈希预算：未验证内容",
          "budget detail message parity");

    // --- relink ladder -------------------------------------------------------
    catalog.versions.push_back(
        make_version("v-missing", g_dir + "/gone.bin", true, sha_of("a.bin"),
                     size_of("a.bin")));
    pi::DependencyAuditReport report2 = auditor.audit();
    auditor.attach_candidates(report2, {g_dir});
    for (auto& record : report2.records) {
        if (record.version_id != "v-missing") continue;
        check(record.status == pi::DependencyStatus::RELINK_CANDIDATE,
              "missing with verified candidate becomes relink_candidate");
        check(!record.relink_candidates.empty(), "candidates attached");
        bool verified_first = !record.relink_candidates.empty() &&
                              record.relink_candidates.front().basis == "size+hash";
        check(verified_first, "hash-verified candidate ranked first");
    }

    // Refusing to guess: a record with no recorded identity at all.
    pi::DependencyRecord identity_free;
    identity_free.version_id = "v-none";
    identity_free.status = pi::DependencyStatus::MISSING;
    check(auditor.find_relink_candidates(identity_free, {g_dir}).empty(),
          "no identity recorded → no candidates (never guess)");

    // apply_relink: hash mismatch refuses; size-only needs confirmation;
    // verified candidate registers a NEW version with lineage metadata.
    pi::DependencyRecord record;
    record.version_id = "v-missing";
    record.asset_name = "asset-1";
    record.status = pi::DependencyStatus::MISSING;
    record.expected_size = size_of("a.bin");
    record.expected_sha256 = sha_of("a.bin");

    pi::RelinkCandidate mismatched;
    mismatched.path = g_dir + "/same_size.bin";
    mismatched.size_bytes = size_of("same_size.bin");
    mismatched.sha256 = sha_of("same_size.bin");
    mismatched.basis = "size+hash";
    check(expect_throw([&] { auditor.apply_relink(record, mismatched); })
              .find("拒绝重连") != std::string::npos,
          "hash mismatch refuses relink");

    pi::RelinkCandidate size_only;
    size_only.path = g_dir + "/same_size.bin";
    size_only.size_bytes = size_of("a.bin");
    size_only.basis = "size";
    check(expect_throw([&] { auditor.apply_relink(record, size_only); })
              .find("confirm_unverified") != std::string::npos,
          "size-only candidate requires explicit confirmation");
    catalog.link_calls = 0;
    auditor.apply_relink(record, size_only, /*confirm_unverified=*/true);
    check(catalog.link_calls == 1, "confirmed relink registers new version");
    check(catalog.last_link_name == "asset-1", "link keeps asset name");
    check(catalog.last_link_metadata.value("relinked_from", "") == "v-missing",
          "link records lineage");

    pi::RelinkCandidate verified;
    verified.path = g_dir + "/copy_of_a.bin";
    verified.size_bytes = size_of("a.bin");
    verified.sha256 = sha_of("a.bin");
    verified.basis = "size+hash";
    auditor.apply_relink(record, verified);
    check(catalog.link_calls == 2, "verified candidate auto-approves");

    std::filesystem::remove_all(g_dir);
    if (g_failures == 0) {
        std::printf("interchange.dependency_audit: %d checks passed\n", g_checks);
        return 0;
    }
    std::fprintf(stderr, "interchange.dependency_audit: %d/%d checks FAILED\n",
                 g_failures, g_checks);
    return 1;
}
