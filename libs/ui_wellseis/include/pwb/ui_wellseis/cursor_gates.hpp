#pragma once

// UI-09 — cursor publication gates (Qt-free).
//
// SeismicCursorGate — port of seismic_view_panel.py::SeismicCursorGate
// (#1029): publish when min_interval_ms elapsed since the previous
// publication OR the inline moved by more than il_jump lines. Injectable
// clock (seconds, monotonic) keeps the behaviour unit-testable.
//
// DepthCursorGate — the Qt-free half of WellLogCanvasPanel's 120 ms depth
// gate with trailing-edge flush (review R3-m2): events inside the gate are
// HELD, and the last held depth publishes once the gate opens. The widget
// owns the QTimer; this core owns the decision so the semantics stay
// testable without Qt.
//
// depth_cursor_unavailable_reason — the fail-closed unit contract
// (R1-M1 / V6 §3): a non-metre or undeclared depth axis must not leak raw
// numbers into the metres contract.

#include <functional>
#include <optional>
#include <string>

#include <pwb/well_science/depth_unit.hpp>

namespace pwb::ui_wellseis {

class SeismicCursorGate {
public:
    // clock returns seconds (monotonic); default = std::chrono::steady_clock.
    explicit SeismicCursorGate(double min_interval_ms = 30.0,
                               double il_jump = 1.0,
                               std::function<double()> clock = {});

    bool should_publish(double il);

    double min_interval_ms() const { return min_interval_ms_; }
    double il_jump() const { return il_jump_; }

private:
    double min_interval_ms_;
    double il_jump_;
    std::function<double()> clock_;
    std::optional<double> last_pub_ms_;
    std::optional<double> last_il_;
};

// The well-log depth gate (DEPTH_GATE_MS = 120.0).
class DepthCursorGate {
public:
    static constexpr double kGateMs = 120.0;

    struct Decision {
        // publish_now: emit immediately (and record the publication).
        bool publish_now = false;
        double depth = 0.0;
        // hold: store the depth as pending; the host schedules the trailing
        // flush after flush_in_ms (Python starts a single-shot QTimer).
        bool hold = false;
        double flush_in_ms = 0.0;
    };

    explicit DepthCursorGate(std::function<double()> clock = {});

    // _publish_gated_depth parity (post unit-check): first event or
    // elapsed >= gate -> publish now; else hold + report the remaining wait.
    Decision offer(double depth);

    // _flush_pending_depth parity: take the held depth (clears it); the
    // caller still applies the unit check before emitting. nullopt when
    // nothing is held. Records the publication timestamp.
    std::optional<double> flush_pending();

    // Drop a held depth without publishing (unit refusal / shutdown).
    void clear_pending() { pending_.reset(); }
    bool has_pending() const { return pending_.has_value(); }

    void reset() {
        last_pub_ms_.reset();
        pending_.reset();
    }

private:
    std::function<double()> clock_;
    std::optional<double> last_pub_ms_;
    std::optional<double> pending_;
};

// depth_cursor_unavailable_reason parity (well_log_canvas_panel.py):
//   unit "m"            -> nullopt (linking on)
//   unit ft/other known -> "depth-unit:<unit>"
//   declared but unrecognized token -> "depth-unit:<raw>" (verbatim)
//   undeclared          -> "depth-unit:unknown"
std::optional<std::string> depth_cursor_unavailable_reason(
    const well_science::DepthUnitInfo& info);

}  // namespace pwb::ui_wellseis
