// Payload path resolution ladder (conv-31b; service.py resolve_path
// 1502-1544 + _fallback_identity_ok 1546-1565 — implementation TU; the
// frozen contract and the rung table live in resolve.hpp / R6 recon).
//
// Parity notes (31b-findings B-25/B-29):
//  - pathlib Path.resolve() ↔ fs::weakly_canonical (sources.cpp precedent;
//    equivalent under POSIX for existing prefixes, B-25).
//  - pathlib "/" and fs::path::operator/ both REPLACE the left side when
//    the right side is absolute — R3 therefore degrades into an R2 retry
//    for absolute recorded paths, exactly like Python.
//  - expanduser() covers only the leading "~" / "~/" form via $HOME
//    (pathlib also understands "~user"; that edge is not reachable with
//    app-supplied project paths).
//  - raw_path.as_posix().split("/") is reproduced by splitting the
//    recorded STRING on "/" — on POSIX a backslash is a filename character
//    and never a separator, so fs::path component iteration is avoided on
//    purpose (R8 member-path parity, B-29).
//
// CONV-31b: implemented in Wave2-A6.
#include "pwb/catalog/resolve.hpp"

#include "pwb/catalog/checksum.hpp"

#include <cstdint>
#include <cstdlib>
#include <system_error>
#include <vector>

namespace pwb::catalog {

namespace {

namespace fs = std::filesystem;

// service.py 1515: project_path.expanduser().resolve().parent — the anchor
// every project-relative join below hangs on.
fs::path project_anchor_dir(const fs::path& project_path) {
    fs::path expanded = project_path;
    const std::string text = project_path.string();
    if (text.size() >= 1 && text[0] == '~' &&
        (text.size() == 1 || text[1] == '/')) {
        const char* home = std::getenv("HOME");
        if (home != nullptr && *home != '\0') {
            expanded = fs::path(home);
            if (text.size() > 2) expanded /= text.substr(2);
        }
    }
    std::error_code ec;
    return fs::weakly_canonical(expanded, ec).parent_path();
}

// pathlib Path.is_file(): follows symlinks, regular files only.
bool is_file(const fs::path& path) {
    std::error_code ec;
    return fs::is_regular_file(path, ec);
}

// [p for p in raw_path.as_posix().split("/") if p] — the ladder's posix
// segmentation over the recorded string.
std::vector<std::string> posix_segments(const std::string& recorded) {
    std::vector<std::string> parts;
    std::size_t start = 0;
    while (start <= recorded.size()) {
        const std::size_t slash = recorded.find('/', start);
        if (slash == std::string::npos) {
            if (start < recorded.size()) parts.push_back(recorded.substr(start));
            break;
        }
        if (slash > start) parts.push_back(recorded.substr(start, slash - start));
        start = slash + 1;
    }
    return parts;
}

}  // namespace

fs::path resolve_payload_path(const fs::path& project_path,
                              const DataVersion& version) {
    const fs::path project_dir = project_anchor_dir(project_path);

    // R1 — managed payloads were placed by this service: unconditional
    // join, no stat, no existence proof (oracle: managed_join_missing).
    if (version.managed) return project_dir / fs::path(version.path);

    const fs::path raw(version.path);

    // R2 — the recorded path (usually absolute) hits as-is.
    if (is_file(raw)) {
        std::error_code ec;
        return fs::weakly_canonical(raw, ec);
    }

    // R3 — project-relative join; an absolute *raw* replaces the base and
    // this degrades into an R2 resolve retry (join-replacement parity).
    std::error_code ec;
    const fs::path rel_candidate = fs::weakly_canonical(project_dir / raw, ec);
    if (is_file(rel_candidate)) return rel_candidate;

    const std::vector<std::string> parts = posix_segments(version.path);
    const std::string proj_name = project_dir.filename().string();

    // R4 — project-name re-anchor, FIRST occurrence only (parts.index
    // semantics; oracle: reanchor_first_occurrence — a miss here falls
    // through, it must NOT try the second occurrence).
    if (!proj_name.empty()) {
        for (std::size_t i = 0; i < parts.size(); ++i) {
            if (parts[i] != proj_name) continue;
            if (i + 1 < parts.size()) {
                std::string subpath = parts[i + 1];
                for (std::size_t j = i + 2; j < parts.size(); ++j) {
                    subpath += '/';
                    subpath += parts[j];
                }
                const fs::path cand =
                    fs::weakly_canonical(project_dir / fs::path(subpath), ec);
                if (is_file(cand) && fallback_identity_ok(cand, version)) {
                    return cand;
                }
            }
            break;  // first occurrence only, gated or not
        }
    }

    // R5 — last two segments joined onto the project dir.
    if (parts.size() >= 2) {
        const std::string two_part =
            parts[parts.size() - 2] + "/" + parts[parts.size() - 1];
        const fs::path cand =
            fs::weakly_canonical(project_dir / fs::path(two_part), ec);
        if (is_file(cand) && fallback_identity_ok(cand, version)) return cand;
    }

    // R6 — basename joined onto the project dir.
    if (!parts.empty()) {
        const fs::path cand =
            fs::weakly_canonical(project_dir / fs::path(parts.back()), ec);
        if (is_file(cand) && fallback_identity_ok(cand, version)) return cand;
    }

    // R7 — total miss: the recorded path verbatim. Never an error, never
    // empty — verify_integrity reports it as missing and relink can rescue.
    return raw;
}

bool fallback_identity_ok(const fs::path& candidate, const DataVersion& version) {
    // service.py 1546-1565, try/OSError→False shape preserved by mapping
    // every IO failure onto "gate refuses". #1140/#1221: sha256 ladder
    // (FULL re-hash, never a scan shortcut) → size ladder → fail CLOSED.
    if (version.sha256.has_value() && !version.sha256->empty()) {
        const std::optional<std::string> digest = sha256_file_or_none(candidate);
        return digest.has_value() && *digest == *version.sha256;
    }
    if (version.size_bytes.has_value()) {
        std::error_code ec;
        const std::uintmax_t size = fs::file_size(candidate, ec);
        if (ec) return false;
        return static_cast<std::int64_t>(size) == *version.size_bytes;
    }
    // No identity evidence at all: refuse the basename guess — an
    // identity-less version surfaces as missing instead of silently
    // binding an unrelated same-named scientific file.
    return false;
}

}  // namespace pwb::catalog
