#pragma once

// SelectionEventV1 — cross-view selection contract (interface handshake v1).
// Qt-free on purpose: the same event crosses WLE-viewer -> host -> A's
// application layer without dragging QWidget/Python/QGIS types along.

#include <cstdint>
#include <string>

namespace pwb::viz {

enum class DepthDomainKind : std::uint8_t { measured_depth, time };

struct DepthRange {
    double top{0.0};
    double bottom{0.0};
    std::string unit; // required: "m", "ms", ...
};

struct SelectionEventV1 {
    std::string document_id; // stable domain id (well/document), never a widget
                             // address or pointer-derived value
    std::string origin;      // emitting view identity; rebroadcasts skip the
                             // same origin to break feedback loops
    std::uint64_t revision{0}; // source document revision at emission time
    DepthDomainKind domain{DepthDomainKind::measured_depth};
    DepthRange range;
    std::string crs; // required when horizontal coordinates ride along;
                     // empty for pure depth selections
};

} // namespace pwb::viz
