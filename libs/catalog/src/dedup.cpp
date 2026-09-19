#include "pwb/catalog/dedup.hpp"

#include "pwb/domain/ids.hpp"
#include "pwb/domain/sha256.hpp"
#include "pwb/project/paths.hpp"

#include <algorithm>
#include <cstdlib>
#include <fstream>
#include <optional>
#include <set>

#if !defined(_WIN32)
#include <fcntl.h>
#include <unistd.h>
#endif

namespace pwb::catalog {

using pwb::domain::DataError;
using pwb::domain::ErrorCode;
using pwb::domain::Result;

namespace {

constexpr std::size_t kChunkSize = 1024 * 1024;  // checksum.py CHUNK_SIZE

std::string unique_suffix() {
    static int counter = 0;
    return "-" + std::to_string(::rand()) + "-" + std::to_string(++counter);
}

fs::path project_dir(const fs::path& project_path) {
    return pwb::project::project_dir_for(project_path);
}

// Best-effort durability parity with Python fsync_dir / os.fsync; a failure
// never fails the placement (best-effort accident guard, not a gate).
void fsync_path_best_effort(const fs::path& file_or_dir) {
#if !defined(_WIN32)
    const int fd = ::open(file_or_dir.c_str(), O_RDONLY);
    if (fd < 0) return;
    ::fsync(fd);
    ::close(fd);
#else
    (void)file_or_dir;
#endif
}

void make_read_only(const fs::path& target) {
    std::error_code ec;
    // storage.py `_make_read_only` parity: clear ONLY the write bits (exec /
    // setuid survive), never force the whole mode.
    fs::permissions(target,
                    fs::perms::owner_write | fs::perms::group_write
                        | fs::perms::others_write,
                    fs::perm_options::remove, ec);
}

// Reserve a uniquely-named temp path. POSIX creates it O_EXCL so concurrent
// placements can never truncate each other's temp; Windows relies on the
// single-writer protocol (15-decisions.md D4).
fs::path reserve_temp(const fs::path& directory, const char* prefix) {
    for (int attempt = 0; attempt < 64; ++attempt) {
        const fs::path candidate =
            directory / (prefix + unique_suffix());
#if !defined(_WIN32)
        const int fd = ::open(candidate.c_str(),
                              O_WRONLY | O_CREAT | O_EXCL, 0644);
        if (fd >= 0) {
            ::close(fd);
            return candidate;
        }
#else
        std::error_code ec;
        if (!fs::exists(candidate, ec)) return candidate;
#endif
    }
    return directory / (prefix + unique_suffix());
}

std::string digest_of(const fs::path& source) {
    const auto digest = pwb::domain::Sha256::of_file(source, kChunkSize);
    return digest.has_value() ? *digest : std::string();
}

DataError io_error(const std::string& message) {
    return DataError(ErrorCode::IoError, message);
}

// storage.py `is_safe_entity_id` (#1175): non-empty, no leading dot, every
// character `c.isalnum() or c in "._-"`, no path separators. Python's
// isalnum is Unicode-aware, so valid non-ASCII UTF-8 sequences are accepted
// here as a declared superset (decisions D14) — no full Unicode category
// tables are carried; ASCII punctuation inside non-ASCII ids diverges
// (accepted by C++, rejected by Python) and traversal stays impossible
// because '/' and a leading '.' are ASCII.
bool is_safe_entity_id_python_parity(const std::string& id) {
    if (id.empty() || id[0] == '.') return false;
    std::size_t i = 0;
    while (i < id.size()) {
        const unsigned char c = static_cast<unsigned char>(id[i]);
        const bool ascii_ok = (c >= 'a' && c <= 'z')
            || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')
            || c == '.' || c == '_' || c == '-';
        if (ascii_ok) {
            ++i;
            continue;
        }
        if (c < 0x80) return false;  // other ASCII: separator or punctuation
        // Non-ASCII: consume one well-formed UTF-8 sequence.
        std::size_t length = 0;
        if ((c & 0xE0) == 0xC0) length = 2;
        else if ((c & 0xF0) == 0xE0) length = 3;
        else if ((c & 0xF8) == 0xF0) length = 4;
        if (length == 0 || i + length > id.size()) return false;
        for (std::size_t k = 1; k < length; ++k) {
            if ((static_cast<unsigned char>(id[i + k]) & 0xC0) != 0x80) {
                return false;
            }
        }
        i += length;
    }
    return true;
}

// Python `repr(str)` parity for the unsafe-id error text: prefers single
// quotes, switches to double quotes when the value contains one and no
// double quote; escapes backslashes and the chosen quote (non-printables
// are out of the declared envelope — ids are [A-Za-z0-9._-]+ / CJK names).
std::string python_repr(const std::string& value) {
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

}  // namespace

fs::path blob_dir_for(const fs::path& project_path) {
    return pwb::project::artifact_dir_for(project_path) / "blobs";
}

fs::path blob_path_for(const fs::path& project_path,
                       const std::string& digest) {
    return blob_dir_for(project_path) / digest.substr(0, 2) / digest;
}

bool has_blob(const fs::path& project_path, const std::string& digest) {
    return !digest.empty()
        && fs::is_regular_file(blob_path_for(project_path, digest));
}

std::int64_t blob_size(const fs::path& project_path, const std::string& digest) {
    std::error_code ec;
    const auto size = fs::file_size(blob_path_for(project_path, digest), ec);
    return ec ? 0 : static_cast<std::int64_t>(size);
}

Result<BlobPlacement> place_blob(const fs::path& project_path,
                                 const fs::path& source,
                                 const std::optional<std::string>& digest) {
    BlobPlacement result;
    result.digest = digest.has_value() ? *digest : digest_of(source);
    if (result.digest.empty()) {
        return io_error("source unreadable while hashing: "
                        + source.generic_string());
    }
    if (has_blob(project_path, result.digest)) {
        result.newly_placed = false;
        return result;
    }
    const fs::path shard = blob_dir_for(project_path) / result.digest.substr(0, 2);
    std::error_code ec;
    fs::create_directories(shard, ec);
    const fs::path target = shard / result.digest;
    if (fs::is_regular_file(target, ec)) {
        result.newly_placed = false;
        return result;
    }
    std::ifstream in(source, std::ios::binary);
    if (!in.good()) {
        return io_error("blob source unreadable: " + source.generic_string());
    }
    const fs::path temp = reserve_temp(shard, ".blob-");
    {
        std::ofstream out(temp, std::ios::binary | std::ios::trunc);
        if (!out.good()) {
            return io_error("blob temp unwritable: " + temp.generic_string());
        }
        std::string buffer(kChunkSize, '\0');
        while (in) {
            in.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
            if (in.gcount() > 0) {
                out.write(buffer.data(), in.gcount());
            }
        }
        // A mid-read I/O error must fail the placement (Python's read loop
        // raises OSError): a truncated temp must never be renamed to a
        // content-addressed name that is trusted forever.
        const bool read_failed = in.bad();
        out.flush();
        const bool write_failed = !out.good();
        in.close();  // flush the read side before removing the temp
        if (read_failed || write_failed) {
            fs::remove(temp, ec);
            return io_error(read_failed
                                ? "blob source read failed: "
                                    + source.generic_string()
                                : "blob temp write failed: "
                                    + temp.generic_string());
        }
    }
    in.close();
    fsync_path_best_effort(temp);
    fs::rename(temp, target, ec);
    if (ec) {
        fs::remove(temp, ec);
        return io_error("blob rename failed: " + ec.message());
    }
    fsync_path_best_effort(shard);
    make_read_only(target);
    result.newly_placed = true;
    return result;
}

std::map<std::string, std::int64_t> scan_blobs(const fs::path& project_path) {
    std::map<std::string, std::int64_t> blobs;
    const fs::path root = blob_dir_for(project_path);
    std::error_code ec;
    if (!fs::is_directory(root, ec)) return blobs;
    for (const fs::directory_entry& shard : fs::directory_iterator(root, ec)) {
        if (ec || !shard.is_directory()) continue;
        for (const fs::directory_entry& entry :
             fs::directory_iterator(shard.path(), ec)) {
            if (ec) break;
            // Every regular file inside a shard counts, temp names included
            // (Python records whatever sits there; temps only live at the
            // root or inside stage dirs, never in shards in steady state).
            if (entry.is_regular_file()) {
                blobs[entry.path().filename().generic_string()]
                    = static_cast<std::int64_t>(entry.file_size(ec));
            }
        }
    }
    return blobs;
}

std::vector<std::string> referenced_digests(const CatalogDocument& document) {
    std::set<std::string> digests;
    for (const DataVersion& version : document.versions) {
        if (version.managed && version.sha256.has_value()
            && !version.sha256->empty()) {
            digests.insert(*version.sha256);
        }
    }
    return std::vector<std::string>(digests.begin(), digests.end());
}

std::vector<std::string> plan_blob_gc(const fs::path& project_path,
                                      const CatalogDocument& document) {
    const std::vector<std::string> refs = referenced_digests(document);
    const std::set<std::string> keep(refs.begin(), refs.end());
    std::vector<std::string> orphans;
    for (const auto& [digest, size] : scan_blobs(project_path)) {
        (void)size;
        if (keep.count(digest) == 0) orphans.push_back(digest);
    }
    return orphans;  // map order = sorted
}

DataError sweep_unreferenced_blobs(const fs::path& project_path,
                                   const CatalogDocument& document,
                                   std::vector<std::string>* removed) {
    for (const std::string& digest : plan_blob_gc(project_path, document)) {
        std::error_code ec;
        const fs::path path = blob_path_for(project_path, digest);
        if (!fs::remove(path, ec) || ec) {
            // Missing → already gone; anything else stays conservative.
            continue;
        }
        fsync_path_best_effort(path.parent_path());
        if (removed != nullptr) removed->push_back(digest);
    }
    return DataError(ErrorCode::Ok, "");
}

BlobMetrics blob_metrics(const fs::path& project_path,
                         const CatalogDocument& document) {
    const auto blobs = scan_blobs(project_path);
    const std::vector<std::string> refs = referenced_digests(document);
    const std::set<std::string> keep(refs.begin(), refs.end());
    std::map<std::string, std::int64_t> ref_counts;
    for (const DataVersion& version : document.versions) {
        if (version.managed && version.sha256.has_value()) {
            const auto it = blobs.find(*version.sha256);
            if (it != blobs.end()) {
                ref_counts[*version.sha256] += 1;
            }
        }
    }
    BlobMetrics metrics;
    metrics.blobs_on_disk = static_cast<std::int64_t>(blobs.size());
    for (const auto& [digest, size] : blobs) {
        metrics.bytes_on_disk += size;
        const auto refs = ref_counts.find(digest);
        if (refs != ref_counts.end() && refs->second > 1) {
            metrics.bytes_deduped += size * (refs->second - 1);
        }
    }
    // ref_counts keys are exactly the managed digests that sit on disk, and
    // every counted digest is in keep by construction.
    metrics.referenced_digests =
        static_cast<std::int64_t>(ref_counts.size());
    // unreferenced counts blobs absent from keep: blobs_on_disk minus the
    // keep∩blobs split above.
    metrics.unreferenced_blobs = metrics.blobs_on_disk
        - metrics.referenced_digests;
    return metrics;
}

Result<PlacedFile> place_managed_file(const fs::path& source,
                                      const fs::path& project_path,
                                      domain::DataStage stage,
                                      const std::string& asset_id,
                                      const std::string& version_id,
                                      const PlaceManagedOptions& options) {
    // storage.py `_require_safe_entity_id` (#1175): both ids become path
    // segments under `{stage}/{asset_id}/{version_id}/`. Python's gate
    // (storage.py:57) is Unicode-aware (`str.isalnum`), so the C++ check
    // accepts valid non-ASCII UTF-8 sequences in addition to the ASCII
    // vocabulary — a declared superset (decisions D14): traversal is still
    // impossible because '/' and a leading '.' are both ASCII and rejected
    // before any directory is created.
    auto safe_or_fail = [&](const char* role,
                            const std::string& id) -> std::optional<DataError> {
        if (!is_safe_entity_id_python_parity(id)) {
            return DataError(
                ErrorCode::UnsafeId,
                "Unsafe " + std::string(role) + " id " + python_repr(id)
                    + ": only [A-Za-z0-9._-] allowed");
        }
        return std::nullopt;
    };
    if (auto error = safe_or_fail("asset", asset_id)) return *error;
    if (auto error = safe_or_fail("version", version_id)) return *error;

    const fs::path dir = project_dir(project_path);
    // Dedup fast path: the caller's digest names an existing blob AND the
    // source size matches AND the content is re-proven — adopt the shared
    // read-only blob without copying.
    if (options.known_sha256.has_value()
        && has_blob(project_path, *options.known_sha256)) {
        std::error_code ec;
        const auto source_size = fs::file_size(source, ec);
        if (!ec
            && static_cast<std::int64_t>(source_size)
                == blob_size(project_path, *options.known_sha256)
            && digest_of(source) == *options.known_sha256) {
            const fs::path blob = blob_path_for(project_path, *options.known_sha256);
            if (!options.keep_source) fs::remove(source, ec);
            PlacedFile placed;
            placed.rel_path = pwb::project::path_to_u8(
                fs::relative(blob, dir, ec));
            placed.size_bytes = blob_size(project_path, *options.known_sha256);
            placed.sha256 = *options.known_sha256;
            return placed;
        }
    }

    const int stage_index = static_cast<int>(stage);
    if (stage_index < 0 || stage_index > 3) {
        return DataError(ErrorCode::InvalidArgument, "unknown data stage");
    }
    const fs::path artifacts = pwb::project::artifact_dir_for(project_path);
    const fs::path target_dir = artifacts
        / kStageDirs[static_cast<std::size_t>(stage_index)]
        / fs::path(asset_id) / fs::path(version_id);
    std::error_code ec;
    fs::create_directories(target_dir, ec);
    const fs::path target = target_dir / source.filename();
    if (fs::exists(target, ec)) {
        return DataError(ErrorCode::ImmutableVersion,
                         "Managed payload already exists: "
                         + pwb::project::path_to_u8(target));
    }

    const fs::path blobs_root = artifacts / "blobs";
    fs::path blob_temp;
    if (options.register_blob) {
        fs::create_directories(blobs_root, ec);
        blob_temp = reserve_temp(blobs_root, ".blob-");
    }
    const fs::path temp = reserve_temp(target_dir, ".place-");

    pwb::domain::Sha256 digest;
    std::int64_t size = 0;
    {
        std::ifstream in(source, std::ios::binary);
        std::ofstream out(temp, std::ios::binary | std::ios::trunc);
        if (!in.good() || !out.good()) {
            return io_error("payload source unreadable: "
                            + source.generic_string());
        }
        std::ofstream blob_out;
        if (!blob_temp.empty()) {
            blob_out.open(blob_temp, std::ios::binary | std::ios::trunc);
            if (!blob_out.good()) {
                return io_error("blob temp unwritable: "
                                + blob_temp.generic_string());
            }
        }
        std::string buffer(kChunkSize, '\0');
        while (in) {
            in.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
            const auto got = in.gcount();
            if (got > 0) {
                digest.update(buffer.data(), static_cast<std::size_t>(got));
                size += static_cast<std::int64_t>(got);
                out.write(buffer.data(), got);
                if (blob_out.is_open()) blob_out.write(buffer.data(), got);
            }
        }
        // A mid-read I/O error fails the placement (Python's read loop
        // raises OSError): never commit a truncated payload or blob.
        const bool read_failed = in.bad();
        out.flush();
        const bool write_failed = !out.good();
        bool blob_write_failed = false;
        if (blob_out.is_open()) {
            blob_out.flush();
            blob_write_failed = !blob_out.good();
        }
        if (read_failed || write_failed || blob_write_failed) {
            // A failed blob fsync must fail the placement: content-store
            // blobs are trusted forever by has_blob/dedup.
            fs::remove(temp, ec);
            if (blob_out.is_open()) fs::remove(blob_temp, ec);
            return io_error(read_failed
                                ? "payload source read failed: "
                                    + source.generic_string()
                                : (blob_write_failed
                                      ? "blob temp write failed: "
                                            + blob_temp.generic_string()
                                      : "payload temp write failed: "
                                            + temp.generic_string()));
        }
    }
    fsync_path_best_effort(temp);
    fs::rename(temp, target, ec);
    if (ec) {
        fs::remove(temp, ec);
        if (!blob_temp.empty()) fs::remove(blob_temp, ec);
        return io_error("payload rename failed: " + ec.message());
    }
    fsync_path_best_effort(target_dir);
    const std::string hex = digest.hex_digest();
    if (options.known_sha256.has_value()
        && *options.known_sha256 != hex) {
        // Honest checksum: never adopt a caller digest that does not match
        // the bytes actually placed.
        fs::remove(target, ec);
        if (!blob_temp.empty()) fs::remove(blob_temp, ec);
        return DataError(
            ErrorCode::InvalidArgument,
            "Checksum mismatch for " + pwb::project::path_to_u8(source)
                + ": caller reported " + *options.known_sha256
                + ", actual " + hex);
    }
    make_read_only(target);
    if (!blob_temp.empty()) {
        // Same idempotency contract as place_blob: an already-present blob
        // wins and the temp is discarded. A failed commit raises in Python
        // (storage.py `_commit_blob_temp`), so it fails the placement here
        // too — a trusted content store may never be silently skipped.
        const fs::path blob_target = blobs_root / hex.substr(0, 2) / hex;
        if (fs::is_regular_file(blob_target, ec)) {
            fs::remove(blob_temp, ec);
        } else {
            fs::create_directories(blob_target.parent_path(), ec);
            fs::rename(blob_temp, blob_target, ec);
            if (ec) {
                fs::remove(blob_temp, ec);
                return io_error("blob commit failed: " + ec.message());
            }
            fsync_path_best_effort(blob_target.parent_path());
            make_read_only(blob_target);
        }
    }
    if (!options.keep_source) {
        fs::remove(source, ec);
    }
    PlacedFile placed;
    placed.rel_path = pwb::project::path_to_u8(
        fs::relative(target, dir, ec));
    placed.size_bytes = size;
    placed.sha256 = hex;
    return placed;
}

// ---- place_managed_tree (storage.py 542-615; conv-31b Wave2-A8) --------------
// V11 bundle placement. Branch ladder order IS the contract (R8 ① T1-T8):
// safe-id gate before any directory exists → ensure layout (all seven
// dirs, Python ensure_catalog_layout parity — trash.cpp's artifacts_root
// only creates the root, tree placement keeps the full layout here) → a
// NON-EMPTY existing target is refused while an empty one is tolerated →
// source-not-a-directory AFTER the target mkdir (bare-call shape; the
// register_bundle_version orchestrator pre-checks it) → per-member atomic
// placement → empty result ("only subdirectories") refuses → keep_source
// =false consumes the source only after every member landed (copy-then-
// delete, P1-2). Any mid-loop failure rmtree's the target tree — never a
// partial bundle. Bundle members NEVER enter the CAS blob store and there
// is no caller-digest fast path (the place_managed_file divergences).

namespace {

// storage.py ensure_catalog_layout (70-82). Stage→directory mapping single
// source of truth: models.hpp kStageDirs — the same table place_managed_file
// indexes above (findings §C-8; no third literal list is introduced).
fs::path ensure_catalog_layout(const fs::path& project_path) {
    const fs::path root = pwb::project::artifact_dir_for(project_path);
    std::error_code ec;
    for (const char* stage_dir : kStageDirs) {
        fs::create_directories(root / stage_dir, ec);
    }
    for (const char* extra : {"working", "metadata", "trash"}) {
        fs::create_directories(root / extra, ec);
    }
    return root;
}

struct TreeMemberSource {
    fs::path source_path;             // file under source_dir
    fs::path relative;                // lexical source_dir-relative path
    std::vector<std::string> parts;   // Python sorted(Path) key (B-30)
};

// storage.py `sorted(p for p in source_dir.rglob("*") if p.is_file())`:
// every regular file (file symlinks count — is_file follows; directory
// symlinks are neither descended nor selected). Sort key is the component
// VECTOR (findings B-30: ("a", "b") < ("a.txt",) because "a" < "a.txt"),
// never the native string order. An unreadable subdirectory stops the walk
// (Python's rglob skips it and continues — declared bounded divergence,
// unreachable in the managed-tree envelope).
std::vector<TreeMemberSource> collect_tree_members(const fs::path& source_dir) {
    std::vector<TreeMemberSource> files;
    std::error_code walk_ec;
    for (fs::recursive_directory_iterator it(source_dir,
                                             fs::directory_options::none,
                                             walk_ec),
             end;
         !walk_ec && it != end; it.increment(walk_ec)) {
        if (walk_ec) break;
        std::error_code file_ec;
        if (!fs::is_regular_file(it->path(), file_ec) || file_ec) continue;
        TreeMemberSource member;
        member.source_path = it->path();
        member.relative = fs::relative(member.source_path, source_dir, file_ec);
        if (file_ec) continue;
        for (const auto& part : member.relative) {
            member.parts.push_back(part.generic_string());
        }
        files.push_back(std::move(member));
    }
    std::sort(files.begin(), files.end(),
              [](const TreeMemberSource& a, const TreeMemberSource& b) {
                  return a.parts < b.parts;  // lexicographic component tuple
              });
    return files;
}

}  // namespace

Result<std::vector<PlacedTreeMember>> place_managed_tree(
    const fs::path& source_dir, const fs::path& project_path,
    domain::DataStage stage, const std::string& asset_id,
    const std::string& version_id, bool keep_source) {
    // T1 — #1175 safe-id gate, before ANY directory is created (same
    // message/precedent as place_managed_file above).
    auto safe_or_fail = [&](const char* role,
                            const std::string& id) -> std::optional<DataError> {
        if (!is_safe_entity_id_python_parity(id)) {
            return DataError(
                ErrorCode::UnsafeId,
                "Unsafe " + std::string(role) + " id " + python_repr(id)
                    + ": only [A-Za-z0-9._-] allowed");
        }
        return std::nullopt;
    };
    if (auto error = safe_or_fail("asset", asset_id)) return *error;
    if (auto error = safe_or_fail("version", version_id)) return *error;

    const int stage_index = static_cast<int>(stage);
    if (stage_index < 0 || stage_index > 3) {
        return DataError(ErrorCode::InvalidArgument, "unknown data stage");
    }
    // T2 — the full seven-directory layout (mkdir -p, errors swallowed into
    // the per-member failure below exactly like a Python mkdir OSError).
    const fs::path root = ensure_catalog_layout(project_path);
    const fs::path target_dir =
        root / kStageDirs[static_cast<std::size_t>(stage_index)]
        / fs::path(asset_id) / fs::path(version_id);
    std::error_code ec;
    // T3 / T3b — an existing NON-EMPTY target refuses (FileExistsError →
    // place_managed_file's ImmutableVersion precedent, message byte-equal);
    // an existing EMPTY directory is tolerated below.
    if (fs::exists(target_dir, ec) && !fs::is_empty(target_dir, ec)) {
        return DataError(ErrorCode::ImmutableVersion,
                         "Managed payload already exists: "
                         + pwb::project::path_to_u8(target_dir));
    }
    fs::create_directories(target_dir, ec);
    // T4 — source check comes AFTER the target mkdir (storage.py 571-573);
    // on this refusal the freshly created empty target dir is NOT cleaned
    // (bare-call fidelity; through the service orchestrator the source was
    // already verified in Phase A so this is unreachable there).
    if (!fs::is_directory(source_dir, ec)) {
        return DataError(ErrorCode::NotFound,
                         "Bundle source directory not found: "
                         + pwb::project::path_to_u8(source_dir));
    }

    const fs::path dir = project_dir(project_path);
    std::vector<PlacedTreeMember> placed;
    // T5 — per-member atomic placement: mkstemp ".place-" in the member's
    // parent → streaming copy+hash → fsync → rename → dir fsync →
    // read-only (chmod AFTER the rename, like Python). Returns the error
    // (temp already removed) instead of raising so T6 can roll the whole
    // tree back first.
    auto place_one = [&](const TreeMemberSource& member,
                         PlacedTreeMember* landed) -> std::optional<DataError> {
        const fs::path member_target = target_dir / member.relative;
        fs::create_directories(member_target.parent_path(), ec);
        const fs::path temp = reserve_temp(member_target.parent_path(), ".place-");
        pwb::domain::Sha256 digest;
        std::int64_t size = 0;
        {
            std::ifstream in(member.source_path, std::ios::binary);
            std::ofstream out(temp, std::ios::binary | std::ios::trunc);
            if (!in.good() || !out.good()) {
                fs::remove(temp, ec);
                return io_error("payload source unreadable: "
                                + member.source_path.generic_string());
            }
            std::string buffer(kChunkSize, '\0');
            while (in) {
                in.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
                const auto got = in.gcount();
                if (got > 0) {
                    digest.update(buffer.data(), static_cast<std::size_t>(got));
                    size += static_cast<std::int64_t>(got);
                    out.write(buffer.data(), got);
                }
            }
            const bool read_failed = in.bad();
            out.flush();
            const bool write_failed = !out.good();
            if (read_failed || write_failed) {
                fs::remove(temp, ec);
                return io_error(read_failed
                                    ? "payload source read failed: "
                                          + member.source_path.generic_string()
                                    : "payload temp write failed: "
                                          + temp.generic_string());
            }
        }
        fsync_path_best_effort(temp);
        fs::rename(temp, member_target, ec);
        if (ec) {
            fs::remove(temp, ec);
            return io_error("payload rename failed: " + ec.message());
        }
        fsync_path_best_effort(member_target.parent_path());
        make_read_only(member_target);
        landed->rel_path = pwb::project::path_to_u8(
            fs::relative(member_target, dir, ec));
        landed->size_bytes = size;
        landed->sha256 = digest.hex_digest();
        return std::nullopt;
    };
    for (const TreeMemberSource& member : collect_tree_members(source_dir)) {
        PlacedTreeMember landed;
        if (auto error = place_one(member, &landed)) {
            // T6 — all members or nothing: any mid-loop failure rmtree's
            // the target tree (ignore_errors) and re-raises.
            fs::remove_all(target_dir, ec);
            return *error;
        }
        placed.push_back(std::move(landed));
    }
    // T7 — only subdirectories / no regular files: refuse and clean up.
    if (placed.empty()) {
        fs::remove_all(target_dir, ec);
        return DataError(ErrorCode::InvalidArgument,
                         "Bundle source directory is empty: "
                         + pwb::project::path_to_u8(source_dir));
    }
    // T8 — keep_source=false removes the source directory only after every
    // file landed (move semantics, ignore_errors).
    if (!keep_source) {
        fs::remove_all(source_dir, ec);
    }
    return placed;
}

}  // namespace pwb::catalog
