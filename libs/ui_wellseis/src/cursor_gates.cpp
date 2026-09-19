#include <pwb/ui_wellseis/cursor_gates.hpp>

#include <chrono>
#include <cmath>
#include <utility>

namespace pwb::ui_wellseis {

namespace {
std::function<double()> default_clock() {
    return [] {
        return std::chrono::duration<double>(
                   std::chrono::steady_clock::now().time_since_epoch())
            .count();
    };
}
}  // namespace

SeismicCursorGate::SeismicCursorGate(double min_interval_ms, double il_jump,
                                     std::function<double()> clock)
    : min_interval_ms_(min_interval_ms),
      il_jump_(il_jump),
      clock_(clock ? std::move(clock) : default_clock()) {}

bool SeismicCursorGate::should_publish(double il) {
    const double now_ms = clock_() * 1000.0;
    const double il_val = il;
    bool publish;
    if (!last_pub_ms_.has_value()) {
        publish = true;
    } else {
        const double elapsed = now_ms - *last_pub_ms_;
        const bool jumped =
            !last_il_.has_value() || std::abs(il_val - *last_il_) > il_jump_;
        publish = elapsed >= min_interval_ms_ || jumped;
    }
    if (publish) {
        last_pub_ms_ = now_ms;
        last_il_ = il_val;
    }
    return publish;
}

DepthCursorGate::DepthCursorGate(std::function<double()> clock)
    : clock_(clock ? std::move(clock) : default_clock()) {}

DepthCursorGate::Decision DepthCursorGate::offer(double depth) {
    const double now_ms = clock_() * 1000.0;
    Decision decision;
    if (!last_pub_ms_.has_value() ||
        now_ms - *last_pub_ms_ >= kGateMs) {
        last_pub_ms_ = now_ms;
        pending_.reset();
        decision.publish_now = true;
        decision.depth = depth;
        return decision;
    }
    pending_ = depth;
    decision.hold = true;
    decision.depth = depth;
    decision.flush_in_ms =
        std::max(1.0, kGateMs - (now_ms - *last_pub_ms_));
    return decision;
}

std::optional<double> DepthCursorGate::flush_pending() {
    const std::optional<double> depth = pending_;
    pending_.reset();
    if (!depth.has_value()) {
        return std::nullopt;
    }
    last_pub_ms_ = clock_() * 1000.0;
    return depth;
}

std::optional<std::string> depth_cursor_unavailable_reason(
    const well_science::DepthUnitInfo& info) {
    const std::string unit = info.unit.value_or("");
    if (unit.empty()) {
        if (info.declared && !info.raw.empty()) {
            return "depth-unit:" + info.raw;
        }
        return std::string("depth-unit:unknown");
    }
    if (unit != "m") {
        return "depth-unit:" + unit;
    }
    return std::nullopt;
}

}  // namespace pwb::ui_wellseis
