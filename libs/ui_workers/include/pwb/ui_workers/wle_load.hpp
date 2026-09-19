#pragma once

// VIZ-A — production engine load for the well_log worker seam (UI-04
// WellLogLoadFn). Bridges WLE LasSourceAdapter: on success LoadedWellLog::data
// holds std::shared_ptr<const welllog::WellLogDocument> (copyable across the
// JobOutcome GUI hop; consumers any_cast that type and include
// welllog/core/document.hpp themselves). LAS only — WLE has no XML source
// adapter, so XML paths resolve to the honest message payload
// (viz_resolve semantics). Built only when the WLE SDK participates in the
// build; without it the seam keeps reporting the engine as unavailable.

#include <pwb/ui_workers/viz_resolve.hpp>

namespace pwb::ui_workers {

// Production load_fn. Reads the file, checks the cooperative cancel token
// before and after parsing, parses through WLE (byte-identical to the
// well-log dock path), and reports the ~W well name (path stem fallback).
// Unreadable/unparseable files return nullopt; cancellation propagates as
// WellLogLoadCancelled.
WellLogLoadFn make_wle_load_fn();

}  // namespace pwb::ui_workers
