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

Q_DECLARE_METATYPE(pwb::ui_map::Json)
