// Payload path resolution ladder (conv-31b; service.py resolve_path
// 1502-1544 + _fallback_identity_ok 1546-1565 — R6 recon contract, frozen
// in 31b-findings).
//
// Seven rungs, first hit wins, the function NEVER fails and never returns
// nothing — a total miss returns the recorded path verbatim (rung R7:
// integrity reports it as missing, relink can rescue). The docstring's
// "deliberately NO basename guess" is stale: rungs R4-R6 exist as
// fail-closed IDENTITY-VERIFIED fallbacks (#1221) and the CODE is the
// frozen truth.
//
// R4-R6 run a FULL-FILE sha256 (or a size-only weak fingerprint) per
// candidate. This ladder must never be wired into an O(versions) scan —
// sources.hpp missing_probe_path keeps its first-rung-only contract, and
// the existing resolve seams (queries/audit/refs DisplayContext) opt in
// explicitly.
//
// CONV-31b: implemented in Wave2-A6 (src/resolve.cpp).
#pragma once

#include "pwb/catalog/models.hpp"

#include <filesystem>

namespace pwb::catalog {

// The full ladder over (project_path = the .paleo.json FILE, project_dir
// = its parent):
//   R1 managed     → project_dir / version.path, unconditionally (no stat)
//   R2 recorded    → raw path is a file → its resolved form
//   R3 project-join→ (project_dir / raw) resolved and is a file
//   R4 re-anchor   → project_dir.name found in the posix segments (FIRST
//                    occurrence) → suffix join, gated by identity proof
//   R5 last-two    → final two segments joined, gated
//   R6 basename    → final segment joined, gated
//   R7 miss        → recorded path verbatim
std::filesystem::path resolve_payload_path(
    const std::filesystem::path& project_path, const DataVersion& version);

// #1140/#1221 fail-closed identity gate: sha256 ladder (full re-hash)
// when the version carries a digest, else size-only when it carries a
// size, else REJECT (no identity evidence → surface as missing rather
// than silently bind a same-named stranger). Any OSError → false. Note
// the deliberate difference from sources.hpp relink_identity_proof
// (sha256 → stat fingerprint incl. mtime): this gate reads version
// fields only.
bool fallback_identity_ok(const std::filesystem::path& candidate,
                          const DataVersion& version);

}  // namespace pwb::catalog
