// execute_ingest_plan (conv-26) — phase-2 port of
// paleo_workbench/resources/ingest_plan.py: registered imports in chunks,
// entity binding, primary selection; cancellable and idempotent on re-run
// (an interrupted execution can simply be executed again — already
// registered (source, sha) pairs resolve to the existing asset and are
// skipped-with-reference).
//
// Transaction boundary: the C++ repository has no dirty-set batching, so
// each import commits as its own transaction (Python batches 64 per
// batch_save). Finer granularity, strictly safer partial-progress
// semantics; chunk_size is retained as the cancel/progress granularity.
// The project document is mutated in memory only — the caller saves it.
#pragma once

#include "pwb/data/ingest_plan.hpp"
#include "pwb/data/session.hpp"

#include <map>
#include <string>
#include <vector>

namespace pwb::data {

struct IngestExecuteOptions {
    bool bind = true;
    int chunk_size = 64;
    CancelFn cancel;                 // polled per chunk
    ProgressFn progress;             // (done, total) per item
    bool execute_unconfirmed = false;  // pending items execute only then
};

struct IngestExecuteReport {
    std::vector<std::string> imported_version_ids;
    std::map<std::string, std::string> asset_id_by_path;  // path → asset id
    int bound_links = 0;
    int created_entities = 0;
    std::vector<std::string> skipped;
    std::vector<std::string> issues;
    bool cancelled = false;

    domain::Json to_json() const;
};

// Execute the (user-confirmed) plan against one writable project session:
// import → bind → primary. Payloads are placed through the CONV-15 managed
// placement (content-addressed dedup); every catalog landing is a single
// all-or-nothing import_raw_transaction; on transaction failure the just
// staged version directory is removed (shared blobs stay — only GC removes
// those). `pending` items execute only with execute_unconfirmed.
IngestExecuteReport execute_ingest_plan(const IngestPlan& plan,
                                        WritableSession& session,
                                        const IngestExecuteOptions& options = {});

}  // namespace pwb::data
