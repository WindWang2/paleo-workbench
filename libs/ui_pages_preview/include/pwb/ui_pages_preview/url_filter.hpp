#pragma once

// Scheme whitelist semantics from web_document_preview_widget.py and
// rich_text_preview_widget.py (UI-07) — Qt-free part.

#include <string>

namespace pwb::ui_pages_preview {

// _LocalOnlyRequestInterceptor/_LocalOnlyPage: {"file","data","about","blob"}.
// Used for both resource requests and user-initiated navigation.
bool local_scheme_allowed(const std::string& scheme);

// RichTextPreviewWidget.loadResource: blocks non-file URLs; "" (relative)
// and "file" are allowed so local embedded figures render.
bool resource_scheme_allowed(const std::string& scheme);

}  // namespace pwb::ui_pages_preview
