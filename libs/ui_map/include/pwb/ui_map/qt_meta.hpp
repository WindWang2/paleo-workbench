#pragma once

// UI-05 — QMetaType registration for the Json signal payload type.
//
// Json travels in queued signal payloads (document_selected,
// chrome_changed, draft_saved). Q_DECLARE_METATYPE must appear exactly
// once per type per TU — every Q_OBJECT header that exposes a Json signal
// includes THIS header (pragma-once dedupes), so the AUTOMOC
// mocs_compilation TU never sees a duplicate QMetaTypeId specialization.
//
// Kept out of map_chrome_core.hpp: the core stays Qt-free for the
// headless oracle replay.

#include <QMetaType>

#include <pwb/ui_map/map_chrome_core.hpp>

// BEGIN CLOSURE-MAPPING (08-line compile-fix lease — registered in
// codex-coordination/cpp-close-wave/08-line.json): shared include-order
// guard so TUs combining ui_map Json signals with other slices' Json
// Q_DECLARE_METATYPE (ui_pages_mapedit factor_preview_grid) compile.
// Alias == same type; the specialization must exist exactly once.
#ifndef PWB_JSON_METATYPE_DECLARED
#define PWB_JSON_METATYPE_DECLARED
Q_DECLARE_METATYPE(pwb::ui_map::Json)
#endif
// END CLOSURE-MAPPING
