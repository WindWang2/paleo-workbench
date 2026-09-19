#pragma once

// Port of paleo_workbench/ui/pages/media_preview_widget.py time formatting
// (UI-07) — Qt-free part.

#include <string>

namespace pwb::ui_pages_preview {

// _ms: milliseconds → "MM:SS" (floor seconds, zero-padded).
std::string media_ms_to_mmss(long long ms);

// time label: "pos / dur" both mm:ss.
std::string media_time_label(long long position_ms, long long duration_ms);

}  // namespace pwb::ui_pages_preview
