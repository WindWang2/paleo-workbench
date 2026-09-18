#pragma once

// Well-log interpretation/cursor event contracts (Qt-free, interface
// handshake v1). These cross the host widget -> application boundary without
// dragging QWidget types along, exactly like SelectionEventV1.
//
// Interpretation events are derived host-side from the session selection by
// hit-testing the loaded document's intervals (facies evidence) and markers
// (tops), so the platform layer can fan them out to interpretation stores
// without knowing the engine document model.

#include <cstdint>
#include <string>

namespace pwb::viz {

// Depth cursor broadcast for cross-panel linkage (the Python host's
// set_link_cursor/jump_to_depth pair). Emitted when the view crosshair moves;
// accepted inbound via WellLogHostWidget::set_depth_cursor.
struct WellLogCursorEvent {
    std::string document_id;
    double depth{0.0};
    std::string unit; // canonical lowercase axis unit ("m", "ft", ...)
    bool valid{false};
};

struct WellLogInterpretationEvent {
    enum class Kind : std::uint8_t {
        interval_selected, // selection resolved to a facies/lithology interval
        marker_hit,        // selection top landed on a document marker (top)
    };

    Kind kind{Kind::interval_selected};
    std::string document_id;
    // Engine semantic vocabulary: "facies"/"lithology"/"formation_top"/...
    std::string semantic;
    // Human label of the interval/marker (UTF-8), e.g. the facies name.
    std::string label;
    double top{0.0};
    double bottom{0.0};
    std::string unit; // axis unit at emission ("m"/"ft")
};

} // namespace pwb::viz
