// Frozen cross-module contracts (contracts.md v1 + v3-contracts.md).
//
// B owns ProjectSnapshotV1 / LayerBindingV1 / CommitRequestV1 /
// CommitReceiptV1 and, since v3, the run lifecycle surface
// (RunRegistrationV1 / RunStateV1 / PublishRequestV1 / PublishReceiptV1 /
// WritableSession); A/C consume them through these headers. This umbrella
// header pins the contract version every tool links against: bumping it
// requires a contracts revision, not a silent struct change.
//
// Public interfaces never carry QGIS/Qt/Python types.
#pragma once

#include "pwb/data/commit_coordinator.hpp"
#include "pwb/data/facade.hpp"
#include "pwb/data/run_contracts.hpp"
#include "pwb/data/session.hpp"

namespace pwb::data::contracts {

// Increments whenever a struct above changes shape or semantics.
// v1: snapshot/commit/journal shape. v3: run registration, single-result
// publish, explicit terminal states, pending-recovery gate, writable
// session (v1 structs unchanged — existing API stays source-compatible).
inline constexpr int kVersion = 3;

// Must stay in lockstep with the persistence floors they describe.
static_assert(kVersion == 3, "contracts v3: run lifecycle + publish");
static_assert(pwb::project::kKnownProjectSchemaVersion == 2,
              "contracts v3: .paleo.json schema floor is v2");

}  // namespace pwb::data::contracts
