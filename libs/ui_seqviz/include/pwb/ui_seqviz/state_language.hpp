#pragma once

// UI-10 — unified state language (paleo_workbench/ui/workstation/
// state_language.py). Every domain state maps to ONE (glyph, label, tone)
// triple; tone is styling-layer input only — glyph + text are the non-color
// signals. Unknown values degrade honestly to 「未知」/muted; an unknown
// category is a programming error and throws (KeyError parity).

#include <map>
#include <stdexcept>
#include <string>

namespace pwb::ui_seqviz {

//: one domain state's presentation vocabulary.
struct StateToken {
    std::string glyph;
    std::string label;
    // ok | info | warn | error | muted | locked (style layer interprets).
    std::string tone;
};

// Thrown for an unknown CATEGORY (Python ``_VOCABULARY[category]`` KeyError —
// fail fast on programming errors).
struct UnknownStateCategory : std::out_of_range {
    using std::out_of_range::out_of_range;
};

// state_token(category, value): vocabulary lookup; null/unknown VALUE
// returns the honest 「未知」 muted token (never throws).
StateToken state_token(const std::string& category,
                       const std::string& value);
StateToken state_token(const std::string& category, const char* value);
// value == None parity (state_token(category, None) -> 未知).
StateToken state_token(const std::string& category, std::nullptr_t);

// tone_to_badge: state_language tone → PwbBadge tone (one-way bridge;
// unknown tone falls back to "neutral").
std::string tone_to_badge(const std::string& tone);

// The frozen 「未知」 token (glyph ·, muted).
const StateToken& unknown_state_token();

}  // namespace pwb::ui_seqviz
