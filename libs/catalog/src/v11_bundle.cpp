// V11 bundle registration orchestration (conv-31b Wave2-A8;
// paleo_workbench/catalog/service_v11.py 216-586 — R8 recon contract,
// frozen in 31b-findings §A-8).
//
// This TU is IO orchestration only. Every decision that already lives in
// v11_policy.cpp (the unified member-name pool with ~N disambiguation,
// ports⊆flat, the operation→output-role table) is CONSUMED here, never
// re-implemented. Phase ordering is the contract:
//   A  plan_bundle_registration   pure validation + read-only inventory
//                                 (A1-A7, all failures BEFORE any byte
//                                 lands; A7 stays interleaved — the spec-
//                                 name duplicate check and the auto-name
//                                 allocation walk sorted rels TOGETHER)
//   B  commit_bundle_registration pre-checks (unknown asset / run refuse
//                                 before placement — Phase B parity)
//   C  staging lease              best-effort via BundleSeams (acquire
//                                 failure → no lease, proceed; #1222)
//   D  place + assemble           place_managed_tree (always copy; the
//                                 delete half of move runs only after the
//                                 commit succeeds — P1-2), version path
//                                 derived from the LAYOUT, never from the
//                                 sorted file list (P1-1)
//   E  commit + rollback ladder   E1 asset / E2 immutable version /
//                                 E3 run / E4 save (full in-memory undo +
//                                 tree rmtree) / E5 move consumption
//
// Bounded divergences (declared, 31b-findings §E unless noted here):
//   B-30 member order = Python Path component-tuple sort (implemented in
//        dedup.cpp collect_tree_members; the ordinal backfill below rides
//        that order). B-32 the internal "names are not unique" backstop
//        raises WITHOUT a rollback, byte-verbatim.
//   Local: an OS copy/hash failure inside the working-copy member loop or
//        verify surfaces as DataError(IoError)/degraded member status —
//        Python lets the raw OSError propagate and the call crashes; the
//        catalog-authored message texts stay byte-identical.
#include "pwb/catalog/v11_bundle.hpp"

#include "pwb/catalog/checksum.hpp"
#include "pwb/catalog/dedup.hpp"
#include "pwb/catalog/trash.hpp"
#include "pwb/domain/ids.hpp"
#include "pwb/project/paths.hpp"

#include <algorithm>
#include <fstream>
#include <set>
#include <utility>

namespace pwb::catalog {

namespace {

using pwb::domain::DataError;
using pwb::domain::ErrorCode;
using pwb::domain::Result;

fs::path project_dir_of(const fs::path& project_path) {
    return pwb::project::project_dir_for(project_path);
}

std::string path_text(const fs::path& path) {
    return pwb::project::path_to_u8(path);
}

// Python repr(str) for error texts (same contract as dedup.cpp python_repr:
// prefers single quotes, switches to double when the value has one and no
// double quote, escapes backslashes and the chosen quote).
std::string py_repr(const std::string& value) {
    const bool has_single = value.find('\'') != std::string::npos;
    const bool has_double = value.find('"') != std::string::npos;
    const char quote = (has_single && !has_double) ? '"' : '\'';
    std::string out;
    out.reserve(value.size() + 2);
    out.push_back(quote);
    for (const char c : value) {
        if (c == '\\' || c == quote) out.push_back('\\');
        out.push_back(c);
    }
    out.push_back(quote);
    return out;
}

std::string posix_base_name(const std::string& rel) {
    const auto slash = rel.find_last_of('/');
    return slash == std::string::npos ? rel : rel.substr(slash + 1);
}

// Path(rel).as_posix() parity for spec rel normalization: collapse "//",
// drop "." segments, drop a trailing slash, keep ".." and a leading "/",
// "" → ".". On POSIX a backslash is NOT a separator (byte-faithful).
std::string posix_normalize(const std::string& raw) {
    if (raw.empty()) return ".";
    const bool absolute = raw.front() == '/';
    std::string joined;
    std::size_t i = 0;
    while (i < raw.size()) {
        std::size_t slash = raw.find('/', i);
        const std::string token =
            raw.substr(i, slash == std::string::npos ? std::string::npos
                                                     : slash - i);
        if (!token.empty() && token != ".") {
            if (!joined.empty()) joined.push_back('/');
            joined += token;
        }
        if (slash == std::string::npos) break;
        i = slash + 1;
    }
    if (absolute) return "/" + joined;
    return joined.empty() ? "." : joined;
}

// One shutil.copyfile parity: stream copy so the destination keeps default
// writable permissions (committed members are read-only; a working copy
// must never inherit that bit — Python copyfile never copies the mode).
DataError copy_file_stream(const fs::path& src, const fs::path& dst) {
    std::ifstream in(src, std::ios::binary);
    if (!in.good()) {
        return DataError(ErrorCode::IoError,
                         "bundle working-copy member unreadable: "
                         + path_text(src));
    }
    std::ofstream out(dst, std::ios::binary | std::ios::trunc);
    if (!out.good()) {
        return DataError(ErrorCode::IoError,
                         "bundle working-copy member unwritable: "
                         + path_text(dst));
    }
    std::string buffer(1024 * 1024, '\0');
    while (in) {
        in.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        if (in.gcount() > 0) out.write(buffer.data(), in.gcount());
    }
    const bool read_failed = in.bad();
    out.flush();
    if (read_failed || !out.good()) {
        return DataError(ErrorCode::IoError,
                         "bundle working-copy member copy failed: "
                         + path_text(src));
    }
    return DataError(ErrorCode::Ok, "");
}

// service_v11.py _rollback_bundle (404-406): rmtree of the placed version
// directory, ignore_errors.
void rollback_bundle(const fs::path& project_path,
                     const std::string& version_dir_rel) {
    std::error_code ec;
    fs::remove_all(project_dir_of(project_path) / fs::path(version_dir_rel),
                   ec);
}

// Best-effort lease scope over the BundleSeams pair (Python
// _payload_staging_lease: acquire failure → no lease, release swallows).
class SeamLeaseScope {
public:
    SeamLeaseScope(const BundleSeams& seams, const std::string& target)
        : seams_(&seams) {
        if (seams.acquire_lease) {
            lease_id_ = seams.acquire_lease(target).value_or(std::string());
        }
    }
    ~SeamLeaseScope() {
        if (seams_ != nullptr && !lease_id_.empty() && seams_->release_lease) {
            seams_->release_lease(lease_id_);
        }
    }
    SeamLeaseScope(const SeamLeaseScope&) = delete;
    SeamLeaseScope& operator=(const SeamLeaseScope&) = delete;

private:
    const BundleSeams* seams_;
    std::string lease_id_;
};

// collect the regular-file inventory of a source dir (rglob is_file
// parity: file symlinks count, directory symlinks are not descended),
// deduplicated + string-sorted (a Python SET feeds sorted(), so the sort
// is the plain string order — distinct from the placement order's
// component-tuple sort, which lives in dedup.cpp).
std::vector<std::string> source_file_inventory(const fs::path& source_dir,
                                               bool* walk_error) {
    std::set<std::string> files;
    std::error_code walk_ec;
    for (fs::recursive_directory_iterator it(source_dir,
                                             fs::directory_options::none,
                                             walk_ec),
             end;
         !walk_ec && it != end; it.increment(walk_ec)) {
        if (walk_ec) break;
        std::error_code file_ec;
        if (!fs::is_regular_file(it->path(), file_ec) || file_ec) continue;
        std::error_code rel_ec;
        const fs::path rel =
            fs::relative(it->path(), source_dir, rel_ec);
        if (rel_ec) continue;
        files.insert(path_text(rel));
    }
    if (walk_ec && walk_error != nullptr) *walk_error = true;
    return std::vector<std::string>(files.begin(), files.end());
}

// Python list-repr formatting of the missing-file list (v11_policy.cpp's
// plan_bundle_members formats its own copy the same way).
std::string python_list_repr(const std::vector<std::string>& items) {
    std::string listed = "[";
    for (std::size_t i = 0; i < items.size(); ++i) {
        if (i != 0) listed += ", ";
        listed += "'" + items[i] + "'";
    }
    listed += "]";
    return listed;
}

}  // namespace

// ---- rel-path guard (service_v11.py 408-415) --------------------------------

DataError validate_member_rel_path(const std::string& rel_path) {
    // Reject exactly: absolute, any ".." component, empty string. The
    // component scan mirrors the Python parser (""/"." segments never
    // appear, ".." survives); a backslash is not a separator on POSIX.
    const fs::path candidate(rel_path);
    bool dot_dot = false;
    std::size_t i = 0;
    while (i < rel_path.size()) {
        std::size_t slash = rel_path.find('/', i);
        const std::string token =
            rel_path.substr(i, slash == std::string::npos
                                   ? std::string::npos
                                   : slash - i);
        if (token == "..") dot_dot = true;
        if (slash == std::string::npos) break;
        i = slash + 1;
    }
    if (candidate.is_absolute() || dot_dot || rel_path.empty()) {
        return DataError(
            ErrorCode::PathEscape,
            "Unsafe member rel_path " + py_repr(rel_path)
                + ": must stay inside the version payload directory");
    }
    return DataError(ErrorCode::Ok, "");
}

Result<fs::path> bundle_member_path(const fs::path& payload_base,
                                    const std::string& rel_path) {
    if (auto error = validate_member_rel_path(rel_path);
        error.code != ErrorCode::Ok) {
        return error;
    }
    return payload_base / fs::path(rel_path);
}

// ---- Phase A (service_v11.py 216-293) ----------------------------------------

Result<BundleRegistrationPlan> plan_bundle_registration(
    const fs::path& source_dir,
    const std::vector<VersionMember>& member_specs) {
    // A1 — source must be a directory (str(Path) as given, not resolved).
    std::error_code ec;
    if (!fs::is_directory(source_dir, ec)) {
        return DataError(ErrorCode::InvalidArgument,
                         "Bundle source directory not found: "
                         + path_text(source_dir));
    }
    // A2/A3 — per spec, IN INPUT ORDER: normalize → validate → duplicate.
    // (The empty rel normalizes to "." and passes validation, surfacing
    // later as the A5 missing-file ['.'] — oracle bundle_relpath_guard.)
    BundleRegistrationPlan plan;
    for (const VersionMember& spec : member_specs) {
        const std::string rel = posix_normalize(spec.rel_path);
        if (auto error = validate_member_rel_path(rel);
            error.code != ErrorCode::Ok) {
            return error;
        }
        if (plan.spec_by_rel.count(rel) != 0) {
            return DataError(ErrorCode::InvalidArgument,
                             "Duplicate member rel_path: " + rel);
        }
        VersionMember normalized = spec;
        normalized.rel_path = rel;
        plan.spec_by_rel.emplace(rel, std::move(normalized));
    }
    // A4 — empty inventory (set semantics; a walk error degrades to what
    // was readable, Python's rglob swallows PermissionError too).
    bool walk_error = false;
    plan.source_files = source_file_inventory(source_dir, &walk_error);
    (void)walk_error;
    if (plan.source_files.empty()) {
        return DataError(ErrorCode::InvalidArgument,
                         "Bundle source directory is empty: "
                         + path_text(source_dir));
    }
    // A5 — every spec must name a real file (specs refine reality).
    std::vector<std::string> unexpected;
    for (const auto& [rel, spec] : plan.spec_by_rel) {
        (void)spec;
        if (std::find(plan.source_files.begin(), plan.source_files.end(),
                      rel) == plan.source_files.end()) {
            unexpected.push_back(rel);  // map order = sorted
        }
    }
    if (!unexpected.empty()) {
        return DataError(ErrorCode::InvalidArgument,
                         "Member specs reference missing files: "
                         + python_list_repr(unexpected));
    }
    // A6 — member budget (before any IO; move=True sources stay intact).
    if (static_cast<int>(plan.source_files.size()) > kMaxBundleMembers) {
        return DataError(
            ErrorCode::InvalidArgument,
            "Bundle exceeds member budget ("
                + std::to_string(plan.source_files.size()) + " > "
                + std::to_string(kMaxBundleMembers)
                + "); split the directory or import as separate assets");
    }
    // A7 — the unified name pool, delegated to the v11_policy core. With
    // A3-A6 already satisfied the only reachable failure there is the
    // spec-name duplicate inside the interleaved walk.
    std::vector<VersionMember> normalized_specs;
    normalized_specs.reserve(plan.spec_by_rel.size());
    for (const auto& [rel, spec] : plan.spec_by_rel) {
        (void)rel;
        normalized_specs.push_back(spec);
    }
    auto names = plan_bundle_members(plan.source_files, normalized_specs);
    if (!names.is_ok()) return names.error();
    plan.names = std::move(names.value());
    return plan;
}

// ---- Phase B+C+D+E (service_v11.py 294-402) -----------------------------------

Result<DataVersion> commit_bundle_registration(
    CatalogDocument* document, const DocumentIndex& index,
    const fs::path& project_path, const domain::AssetId& asset_id,
    domain::DataStage stage, const BundleRegistrationPlan& plan,
    const fs::path& source_dir, DataVersion version,
    std::optional<domain::RunId> run_id, bool move,
    const BundleSeams& seams) {
    // Phase B — refuse unknown asset/run BEFORE any byte lands (the lock
    // is the caller's; the release/acquire dance of the Python two-lock
    // structure collapses into the caller's discipline).
    const DataAsset* asset = index.asset(asset_id.str());
    if (asset == nullptr) {
        return DataError(ErrorCode::NotFound,
                         "Unknown asset: " + asset_id.str());
    }
    if (run_id.has_value() && index.run(run_id->str()) == nullptr) {
        return DataError(ErrorCode::NotFound, "Unknown run: " + run_id->str());
    }

    // Phase C — staging lease over the ON-DISK stage dir name (OUTPUT →
    // "outputs"), best-effort.
    SeamLeaseScope lease(seams,
                         staging_target(project_path, stage, asset_id.str()));

    // Phase D — half-built row completion (service_v11.py 305-315).
    version.asset_id = asset_id;
    version.version_number = 0;  // assigned at commit
    version.stage = stage;
    version.managed = true;
    {
        std::error_code resolve_ec;
        const fs::path resolved = fs::weakly_canonical(source_dir, resolve_ec);
        version.source_uri = path_text(resolve_ec
                                           ? fs::absolute(source_dir, resolve_ec)
                                           : resolved);
    }
    version.format.clear();
    if (asset->metadata.is_object() && asset->metadata.contains("format")
        && asset->metadata["format"].is_string()) {
        version.format = asset->metadata["format"].get<std::string>();
    }
    version.run_id = run_id;

    // Payload placement — always a copy (P1-2: move's delete half runs
    // only after the commit succeeds, Phase E5 below).
    auto placed = place_managed_tree(source_dir, project_path, stage,
                                     asset_id.str(), version.id.str(),
                                     /*keep_source=*/true);
    if (!placed.is_ok()) return placed.error();

    // The version payload path is the member DIRECTORY derived from the
    // authoritative layout — never from the sorted file list (P1-1: the
    // alphabetically-first member can live in a subdirectory).
    std::error_code ec;
    const int stage_index = static_cast<int>(stage);
    const fs::path version_dir =
        pwb::project::artifact_dir_for(project_path)
        / kStageDirs[static_cast<std::size_t>(stage_index)]
        / fs::path(asset_id.str()) / fs::path(version.id.str());
    const std::string version_dir_rel =
        path_text(fs::relative(version_dir, project_dir_of(project_path), ec));

    // Member assembly (337-350): member_rel by STRING slicing off the
    // version-dir prefix; spec rows refine, the rest ride the placement
    // order (component-tuple sorted) with enum ordinals. Spec ordinals
    // are kept verbatim — duplicates allowed, never re-normalized.
    const std::string prefix = version_dir_rel + "/";
    std::map<std::string, std::string> name_by_rel(plan.names.names.begin(),
                                                   plan.names.names.end());
    const std::vector<PlacedTreeMember>& landed_members = placed.value();
    std::vector<VersionMember> members;
    for (std::size_t ordinal = 0; ordinal < landed_members.size(); ++ordinal) {
        const PlacedTreeMember& landed = landed_members[ordinal];
        std::string member_rel = landed.rel_path;
        if (member_rel.size() > prefix.size()
            && member_rel.compare(0, prefix.size(), prefix) == 0) {
            member_rel = member_rel.substr(prefix.size());
        }
        VersionMember member;
        const auto spec = plan.spec_by_rel.find(member_rel);
        if (spec != plan.spec_by_rel.end()) {
            member.name = spec->second.name;
            member.member_role = spec->second.member_role;
            member.ordinal = spec->second.ordinal;
            member.required = spec->second.required;
        } else {
            const auto name = name_by_rel.find(member_rel);
            member.name = name != name_by_rel.end() ? name->second
                                                    : posix_base_name(member_rel);
            member.member_role = "";
            member.ordinal = static_cast<int>(ordinal);
            member.required = true;
        }
        member.rel_path = member_rel;
        member.sha256 = landed.sha256;
        member.size_bytes = landed.size_bytes;
        members.push_back(std::move(member));
    }
    // Backstop (351-355) — theoretical only (the pool guarantees unique
    // names); Python raises WITHOUT a rollback, so the tree stays (B-32,
    // byte-verbatim, no added rmtree).
    {
        std::set<std::string> names;
        for (const VersionMember& member : members) names.insert(member.name);
        if (names.size() != members.size()) {
            return DataError(ErrorCode::InvalidArgument,
                             "Bundle member names are not unique"
                             " (internal error)");
        }
    }
    version.members = std::move(members);
    version.path = version_dir_rel;
    version.size_bytes = 0;
    for (const VersionMember& member : version.members) {
        version.size_bytes =
            *version.size_bytes + (member.size_bytes.value_or(0));
    }
    version.sha256 = aggregate_member_sha256(version.members);

    // Phase E — commit window with the rollback ladder.
    DataAsset* live_asset = document->find_asset_mut(asset_id);
    if (live_asset == nullptr) {  // E1 — asset deleted concurrently
        rollback_bundle(project_path, version_dir_rel);
        return DataError(ErrorCode::NotFound,
                         "Unknown asset: " + asset_id.str());
    }
    for (const DataVersion& existing : document->versions) {
        if (existing.id == version.id) {  // E2 — immutable duplicate
            rollback_bundle(project_path, version_dir_rel);
            return DataError(
                ErrorCode::ImmutableVersion,
                "Version " + version.id.str()
                    + " is already committed and immutable");
        }
    }
    DataRun* run = nullptr;
    if (run_id.has_value()) {
        for (DataRun& candidate : document->runs) {
            if (candidate.id == *run_id) {
                run = &candidate;
                break;
            }
        }
        if (run == nullptr) {  // E3 — run deleted concurrently
            rollback_bundle(project_path, version_dir_rel);
            return DataError(ErrorCode::NotFound,
                             "Unknown run: " + run_id->str());
        }
    }
    version.version_number = document->next_version_number(asset_id);
    const auto previous_current = live_asset->current_version_id;
    document->versions.push_back(version);
    live_asset->current_version_id = version.id;
    bool run_output_added = false;
    if (run != nullptr
        && std::find(run->output_version_ids.begin(),
                     run->output_version_ids.end(), version.id)
               == run->output_version_ids.end()) {
        run->output_version_ids.push_back(version.id);
        run_output_added = true;
    }
    // E4 — single-transaction persistence; dirty = asset + version (+ run).
    DirtySet dirty;
    dirty.mark_asset(asset_id.str());
    dirty.mark_version(version.id.str());
    if (run != nullptr) dirty.mark_run(run->id.str());
    if (seams.save) {
        const DataError save_error = seams.save(dirty);
        if (save_error.code != ErrorCode::Ok) {
            if (run != nullptr && run_output_added) {
                run->output_version_ids.erase(
                    std::find(run->output_version_ids.begin(),
                              run->output_version_ids.end(), version.id));
            }
            for (auto it = document->versions.begin();
                 it != document->versions.end(); ++it) {
                if (it->id == version.id) {
                    document->versions.erase(it);
                    break;
                }
            }
            live_asset->current_version_id = previous_current;
            rollback_bundle(project_path, version_dir_rel);
            return save_error;
        }
    }
    // E5 — only now (metadata committed) may move consume the source.
    if (move) {
        fs::remove_all(source_dir, ec);
    }
    return version;
}

Result<DataVersion> register_bundle_version(
    CatalogDocument* document, const DocumentIndex& index,
    const fs::path& project_path, const domain::AssetId& asset_id,
    const fs::path& source_dir, domain::DataStage stage,
    const std::vector<VersionMember>& member_specs,
    const std::vector<domain::VersionId>& parent_version_ids,
    std::optional<domain::RunId> run_id, domain::Json metadata, bool move,
    const BundleSeams& seams) {
    auto planned = plan_bundle_registration(source_dir, member_specs);
    if (!planned.is_ok()) return planned.error();
    DataVersion version;
    version.id = domain::VersionId(domain::make_id("ver_"));
    version.parent_version_ids = parent_version_ids;
    version.run_id = run_id;
    version.metadata =
        metadata.is_null() ? domain::Json::object() : std::move(metadata);
    return commit_bundle_registration(
        document, index, project_path, asset_id, stage, planned.value(), source_dir,
        std::move(version), run_id, move, seams);
}

// ---- verify (service_v11.py 425-461) -----------------------------------------

BundleIntegrityReport verify_bundle_integrity(const DataVersion& version,
                                              const fs::path& payload_base) {
    BundleIntegrityReport report;
    if (version.members.empty()) {
        report.bundle = false;
        report.status = "unknown";
        return report;
    }
    report.bundle = true;
    report.status = "verified";
    const auto rank = [](const std::string& status) -> int {
        if (status == "verified") return 0;
        if (status == "unknown") return 1;
        if (status == "modified") return 2;
        return 3;  // missing
    };
    std::string worst = "verified";
    for (const VersionMember& member : version.members) {
        BundleMemberReport entry;
        entry.name = member.name;
        entry.rel_path = member.rel_path;
        entry.status = "unknown";
        const auto path = bundle_member_path(payload_base, member.rel_path);
        std::error_code ec;
        // A rel-path violation (corrupt stored row; Python would raise out
        // of member_path) degrades to "missing" — verify never hashes
        // outside the payload directory.
        if (!path.is_ok() || !fs::is_regular_file(path.value(), ec)) {
            entry.status = "missing";
        } else {
            // Python sha256_file raises on IO errors and the whole report
            // dies; here an unreadable file degrades to "modified" without
            // an actual digest (declared bounded divergence).
            const auto digest = sha256_file_or_none(path.value());
            if (!member.sha256.has_value()) {
                entry.status = "unknown";
            } else if (!digest.has_value()
                       || *digest != *member.sha256) {
                entry.status = "modified";
                if (digest.has_value()) entry.actual_sha256 = *digest;
            } else {
                entry.status = "verified";
            }
        }
        if (rank(entry.status) > rank(worst)) worst = entry.status;
        report.members.push_back(std::move(entry));
    }
    if (worst == "verified") {
        // Tail aggregate check (service_v11.py:458): `sha256 not in
        // (None, recomputed)` — an ABSENT version.sha256 is IN the tuple,
        // so it never flags "modified" (CONV-31b Wave4 fix V1-P1-1: the
        // previous "neither absent nor equal" reading inverted this and
        // reported a tampered-row "modified" for null sha256 rows where
        // Python reports "verified"). Only a PRESENT-but-different value
        // means the row itself was tampered with.
        const auto recomputed = aggregate_member_sha256(version.members);
        if (recomputed.has_value() && version.sha256.has_value() &&
            *version.sha256 != *recomputed) {
            worst = "modified";
        }
    }
    report.status = worst;
    return report;
}

// ---- bundle working copies (service_v11.py 463-586, over R5's machine) --------

Result<fs::path> create_bundle_working_copy(
    const DataVersion& version, const fs::path& payload_base,
    const fs::path& project_path, bool allow_replace,
    WorkingCopyContext& registry) {
    // C1 — the version row lookup is the caller's (payload_base already
    // resolved through the same seam).
    // C2 — not a bundle.
    if (version.members.empty()) {
        return DataError(ErrorCode::InvalidArgument,
                         "Version " + version.id.str()
                             + " is not a bundle");
    }
    // C3 — live registry row (sqlite truth, read failures swallow to
    // "no row").
    std::optional<WorkingCopy> live;
    if (registry.repo != nullptr) {
        live = registry.repo->get_live_working_copy_for_source(version.id);
    }
    // C4 — payload directory must exist.
    std::error_code ec;
    if (!fs::is_directory(payload_base, ec)) {
        return DataError(ErrorCode::InvalidArgument,
                         "Bundle payload not available: "
                         + path_text(payload_base));
    }
    const fs::path pdir = project_dir_of(project_path);
    // C5 — reuse ladder over the live row.
    if (live.has_value()) {
        const fs::path existing = pdir / fs::path(live->path);
        if (fs::is_directory(existing, ec)) {
            if (!allow_replace) return existing;  // reuse, never destroy
            fs::remove_all(existing, ec);
            if (registry.repo != nullptr) {
                (void)registry.repo->remove_working_copy(live->working_id);
            }
        } else {
            // dead row (file gone / replaced by a file): drop the row only
            if (registry.repo != nullptr) {
                (void)registry.repo->remove_working_copy(live->working_id);
            }
        }
    }
    // C6 — target ladder: a non-empty target is REUSED even when
    // unregistered; allow_replace clears it.
    const fs::path target_dir =
        working_dir_for(project_path) / version.id.str();
    if (fs::exists(target_dir, ec) && !fs::is_empty(target_dir, ec)) {
        if (!allow_replace) return target_dir;
    }
    if (fs::exists(target_dir, ec)) {
        fs::remove_all(target_dir, ec);
    }
    fs::create_directories(target_dir, ec);
    if (ec) {
        return DataError(ErrorCode::IoError, ec.message());
    }
    // C7 — copy member-by-member (writable), preserving relative layout;
    // non-member files are never copied.
    for (const VersionMember& member : version.members) {
        const auto src = bundle_member_path(payload_base, member.rel_path);
        if (!src.is_ok()) return src.error();
        const fs::path dst = target_dir / fs::path(member.rel_path);
        fs::create_directories(dst.parent_path(), ec);
        if (auto error = copy_file_stream(src.value(), dst);
            error.code != ErrorCode::Ok) {
            return error;
        }
    }
    // C8 — registration is bookkeeping, never a checkout gate (swallow);
    // null mtime/size: a directory's stat size is noise and would cry
    // wolf on the dirty hint.
    if (registry.repo != nullptr) {
        const std::string rel =
            path_text(fs::relative(target_dir, pdir, ec));
        (void)registry.repo->register_working_copy(
            version.id, rel, target_dir.filename().generic_string(),
            std::nullopt, std::nullopt);
    }
    return target_dir;
}

Result<DataVersion> commit_bundle_working_copy(
    CatalogDocument* document, const DocumentIndex& index,
    const fs::path& project_path, const fs::path& working_dir,
    std::optional<domain::AssetId> asset_id, std::optional<std::string> name,
    domain::DataStage stage,
    const std::vector<domain::VersionId>* parent_version_ids,
    std::optional<domain::RunId> run_id, domain::Json metadata,
    WorkingCopyContext& registry, const BundleSeams& seams,
    const std::function<domain::AssetId(const std::string&, domain::Json)>&
        new_asset) {
    // M1 — the working directory must exist.
    std::error_code ec;
    if (!fs::is_directory(working_dir, ec)) {
        return DataError(ErrorCode::InvalidArgument,
                         "Working directory not found: "
                         + path_text(working_dir));
    }
    // M2 — registry row for this path (project-external / unregistered →
    // none; read failures swallow).
    std::optional<WorkingCopyStatus> wc_row;
    if (registry.repo != nullptr) {
        wc_row = working_copy_state(registry, working_dir);
    }
    // M3 — parents default to the row's source version ([parent] only when
    // the id is truthy, [] otherwise).
    std::vector<domain::VersionId> parents;
    if (parent_version_ids != nullptr) {
        parents = *parent_version_ids;
    } else if (wc_row.has_value() && !wc_row->source_version_id.empty()) {
        parents.emplace_back(wc_row->source_version_id);
    }
    const std::string working_id =
        wc_row.has_value() ? wc_row->working_id : std::string();
    // M4 — committing transition (swallow).
    if (!working_id.empty()) {
        (void)mark_committing(registry, working_dir);
    }
    auto flip_back_to_dirty = [&]() {
        if (!working_id.empty()) {
            (void)revert_to_dirty(registry, working_id);
        }
    };
    Result<DataVersion> committed = DataError(ErrorCode::Unknown, "");
    bool register_failed = false;
    if (!asset_id.has_value()) {
        // M5 — NEW asset (#1218): the seam creates and adds it (the caller
        // seeds pending_commit_assets around this whole call per the
        // frozen header contract); failure removes it again when it is
        // still in the document.
        const std::string asset_name =
            (name.has_value() && !name->empty())
                ? *name
                : working_dir.filename().generic_string();
        if (!new_asset) {
            flip_back_to_dirty();
            return DataError(ErrorCode::InvalidArgument,
                             "new asset seam missing for bundle commit");
        }
        const domain::AssetId fresh = new_asset(asset_name, metadata);
        committed = register_bundle_version(
            document, index, project_path, fresh, working_dir, stage, {},
            parents, run_id, metadata, /*move=*/true, seams);
        if (!committed.is_ok()) {
            register_failed = true;
            for (auto it = document->assets.begin();
                 it != document->assets.end(); ++it) {
                if (it->id == fresh) {
                    document->assets.erase(it);
                    break;
                }
            }
        }
    } else {
        // M6 — existing asset: straight registration with move semantics.
        committed = register_bundle_version(
            document, index, project_path, *asset_id, working_dir, stage,
            {}, parents, run_id, metadata, /*move=*/true, seams);
        if (!committed.is_ok()) register_failed = true;
    }
    // M7 — any failure flips the row back to dirty (swallow) and re-raises.
    if (register_failed) {
        flip_back_to_dirty();
        return committed.error();
    }
    // M8 — success removes the row (swallow).
    if (!working_id.empty()) {
        (void)drop_row(registry, working_id);
    }
    return committed;
}

// ---- migrate_run_ports persistence half (service_v11.py 745-782) --------------

PortMigrationOutcome migrate_run_ports_persist(CatalogDocument* document,
                                               const DocumentIndex& index,
                                               const SaveHook& save) {
    PortMigrationOutcome out;
    // The decision core only mutates run fields (no insert/erase), so the
    // snapshot index stays pointer-valid across the call.
    std::set<std::string> had_ports;
    for (const DataRun& run : document->runs) {
        if (!run.output_ports.empty()) had_ports.insert(run.id.str());
    }
    out.counts = migrate_run_ports(document, index);
    // touched = exactly the runs whose output ports went empty → non-empty
    // (an observable diff, not a re-implementation of the heuristic).
    for (const DataRun& run : document->runs) {
        if (!run.output_ports.empty()
            && had_ports.count(run.id.str()) == 0) {
            out.touched_run_ids.push_back(run.id.str());
        }
    }
    if (!out.touched_run_ids.empty() && save) {
        DirtySet dirty;
        for (const std::string& run_id : out.touched_run_ids) {
            dirty.mark_run(run_id);
        }
        out.error = save(dirty);
        // Python parity: a failed _save propagates with the in-memory port
        // mutations left in place (no undo there either).
        return out;
    }
    out.error = DataError(ErrorCode::Ok, "");
    return out;
}

}  // namespace pwb::catalog
