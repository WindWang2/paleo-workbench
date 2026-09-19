// Frozen promote-run / promote-metadata shapes (conv-31b; service.py
// promote_version / promote_asset 3665-3759 — R7 recon contract, frozen
// in 31b-findings).
//
// This header freezes the PURE assembly shapes only: the promote run row,
// the new version's metadata, and the staging-lease key rule. The full
// orchestration (resolve_path → place copy → lock-window version-number
// RE-assignment (#849-1: the number is re-computed under the lock at
// commit time; the build-time estimate is discarded) → single save with
// dirty assets+versions+runs → _rollback on failure) is composed by the
// service layer over these shapes, repository.hpp's
// commit_promote_transaction, working_copy.hpp's staging_target (the
// single lease-key source — findings §C-7; this header deliberately does
// NOT re-declare a target builder) and dedup.hpp place_managed_file
// (keep_source=true: a promote COPIES, the source version is immutable
// provenance).
//
// CONV-31b: implemented in Wave2-A7 (src/version_promote.cpp).
#pragma once

#include "pwb/catalog/models.hpp"

#include <optional>
#include <string>

namespace pwb::catalog {

struct PromoteOptions {
    domain::DataStage to_stage = domain::DataStage::Output;
    std::optional<std::string> reviewed_by;   // null in JSON when absent
    std::optional<std::string> note;
};

// The frozen promote run row (service.py 3665 H-6):
//   operation = "promote", inputs = [source], outputs backfilled with the
//   new version id by the orchestrator, status = "completed" (default),
//   parameters = {"to_stage": <stage.value>, "reviewed_by": …, "note": …}.
// The run id comes from the caller's id factory (make_id("run") shape).
DataRun make_promote_run(const domain::VersionId& source_id,
                         const PromoteOptions& options);

// The frozen new-version metadata:
//   {"promoted_from": <source id>, "reviewed_by": …, "note": …}.
domain::Json make_promote_version_metadata(const domain::VersionId& source_id,
                                           const PromoteOptions& options);

}  // namespace pwb::catalog
