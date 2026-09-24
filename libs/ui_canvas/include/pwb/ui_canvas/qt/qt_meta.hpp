// UI-15 — metatype registrations for the canvas signal payloads.
#pragma once

#include <array>
#include <optional>
#include <string>
#include <utility>

#include <QMetaType>

#include <pwb/ui_canvas/layer_scene.hpp>
#include <pwb/ui_canvas/map_render_backend.hpp>

// RenderFrame crosses no queued boundary today (frames are polled, not
// signalled) but declaring it keeps host-side queued connections safe.
Q_DECLARE_METATYPE(pwb::ui_canvas::RenderFrame)
// Extent is std::array<double,4> — the same metatype id.
Q_DECLARE_METATYPE(pwb::ui_canvas::Extent)
Q_DECLARE_METATYPE(pwb::ui_canvas::RasterKey)
Q_DECLARE_METATYPE(pwb::ui_canvas::RasterImage)
Q_DECLARE_METATYPE(pwb::ui_canvas::Json)
Q_DECLARE_METATYPE(std::optional<std::string>)
// std::pair contains a comma — Q_DECLARE_METATYPE takes a single
// argument, so the alias doubles as the declaration spelling.
using MapPointPair = std::pair<double, double>;
Q_DECLARE_METATYPE(MapPointPair)
