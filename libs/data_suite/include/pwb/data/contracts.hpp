// Frozen cross-module contracts, v1 (contracts.md).
//
// B owns ProjectSnapshotV1 / LayerBindingV1 / CommitRequestV1 /
// CommitReceiptV1; A/C consume them through these headers. This umbrella
// header pins the contract version every tool links against: bumping it
// requires a contracts.md revision, not a silent struct change.
//
// Public interfaces never carry QGIS/Qt/Python types.
#pragma once

#include "pwb/data/commit_coordinator.hpp"
#include "pwb/data/facade.hpp"

namespace pwb::data::contracts {

// Increments whenever a struct above changes shape or semantics.
inline constexpr int kVersion = 1;

// Must stay in lockstep with the persistence floors they describe.
static_assert(kVersion == 1, "contracts v1: snapshot/commit/journal shape");
static_assert(pwb::project::kKnownProjectSchemaVersion == 2,
              "contracts v1: .paleo.json schema floor is v2");

}  // namespace pwb::data::contracts
