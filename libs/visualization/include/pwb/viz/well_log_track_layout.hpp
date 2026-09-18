#pragma once

// Well-log track layout — C++ port of paleo_workbench/viz/well_log_track_layout.py
// (the Python module stays as the behavioural oracle; do not fork its rules).
//
// The layout is session-local user configuration: which curves are visible and
// how visible curves are grouped into tracks. Curve identities are index-based
// ("curve:{index}:{mnemonic}") so duplicate mnemonics stay distinct. The C++
// model adds what the native host needs beyond the Python legacy canvas:
// per-curve scale mode (linear/logarithmic), color overrides and stable JSON
// template serialization.
//
// Qt-free on purpose: the same model is used by tests without QApplication and
// by the platform settings panel. All mutating operations throw
// std::out_of_range for unknown keys (Python KeyError) and
// curve_group_limit_error when a merge would exceed the per-track curve cap
// (Python CurveGroupLimitError).

#include <cstddef>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace pwb::viz {

inline constexpr std::size_t kMaxCurvesPerTrack = 3;

// Raised when a merge would create a track with more than
// kMaxCurvesPerTrack curves (mirrors CurveGroupLimitError).
class curve_group_limit_error : public std::invalid_argument {
public:
    explicit curve_group_limit_error(const std::string& what_arg)
        : std::invalid_argument(what_arg) {}
};

enum class TrackScaleMode : std::uint8_t { linear, logarithmic };

struct WellLogTrackLayout {
    // Index-based, duplicate-safe curve identities, one per source curve.
    std::vector<std::string> curve_keys;
    // Parallel to curve_keys; visibility is a per-curve flag.
    std::vector<bool> visible;
    // Track grouping: each group is an ordered list of curve_keys rendered as
    // one track. Every key appears exactly once.
    std::vector<std::vector<std::string>> groups;
    // Per-curve scale mode override (parallel to curve_keys). The plan layer
    // decides the default (RT/RXO logarithmic) when the flag is nullopt.
    std::vector<std::optional<TrackScaleMode>> scale_mode;
    // Per-curve color overrides ("#rrggbb"); empty string = plan default.
    std::vector<std::string> color;

    // --- identity ---------------------------------------------------------
    [[nodiscard]] std::size_t curve_count() const noexcept {
        return curve_keys.size();
    }
    [[nodiscard]] std::size_t key_index(std::string_view curve_key) const;
    [[nodiscard]] const std::vector<std::string>&
    group_for(std::string_view curve_key) const;

    // --- Python-parity operations ------------------------------------------
    [[nodiscard]] WellLogTrackLayout with_visible(std::string_view curve_key,
                                                  bool is_visible) const;
    // Move *curve_key* into *onto*'s group, named first (drag GR onto AC
    // reads "GR / AC"), preserving group order.
    [[nodiscard]] WellLogTrackLayout merge(std::string_view curve_key,
                                           std::string_view onto) const;
    // Restore every curve in *curve_key*'s group to its own track.
    [[nodiscard]] WellLogTrackLayout unmerge(std::string_view curve_key) const;

    // --- native-host extensions -------------------------------------------
    // Reorder a curve's group so the track appears at *group_position*.
    [[nodiscard]] WellLogTrackLayout
    move_group(std::string_view curve_key, std::size_t group_position) const;
    [[nodiscard]] WellLogTrackLayout
    with_scale_mode(std::string_view curve_key,
                    std::optional<TrackScaleMode> mode) const;
    [[nodiscard]] WellLogTrackLayout with_color(std::string_view curve_key,
                                                std::string hex_color) const;

    // --- template serialization -------------------------------------------
    // "pwb.well_log_track_template/1" JSON; deterministic key order.
    [[nodiscard]] std::string to_template_json() const;
    // Parses a template previously written by to_template_json (or matching
    // the schema). Returns false and fills *error on malformed input; a
    // structurally valid template whose curve_keys do not match the current
    // well still loads — reconcile_track_layout() decides usability.
    [[nodiscard]] static bool from_template_json(std::string_view json_text,
                                                 WellLogTrackLayout& out,
                                                 std::string* error);
};

// "curve:{index}:{name or 未命名}" — duplicate-safe, index-first (oracle:
// curve_keys_for).
[[nodiscard]] std::string curve_key_for(std::size_t index,
                                        std::string_view mnemonic);

// Six-curve default, guaranteeing GR when available (oracle:
// default_curve_track_layout).
[[nodiscard]] WellLogTrackLayout
default_track_layout(const std::vector<std::string>& mnemonics);

// Keep a layout only while it describes the current well's curve schema
// (oracle: reconcile_curve_track_layout).
[[nodiscard]] WellLogTrackLayout
reconcile_track_layout(const WellLogTrackLayout& layout,
                       const std::vector<std::string>& mnemonics);

} // namespace pwb::viz
