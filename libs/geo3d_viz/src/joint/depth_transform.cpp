// depth_transform.cpp — priority chain (#63 / grill E), fail-closed.
#include "pwb/geo3d_viz/joint/depth_transform.hpp"

#include <cmath>
#include <cstdio>

namespace pwb::geo3d_viz::joint {

namespace {
std::vector<double> map_all(const std::vector<double>& in, double (ConstantVelocityDepth::*fn)(double) const,
                            const ConstantVelocityDepth& self) {
    std::vector<double> out;
    out.reserve(in.size());
    for (double v : in) out.push_back((self.*fn)(v));
    return out;
}
}  // namespace

ConstantVelocityDepth::ConstantVelocityDepth(double v0_m_s) : v0_m_s_(v0_m_s) {
    // #147: v0<=0 divides by zero (depth→time) and flattens TWT to a zero
    // depth surface (time→depth). Fail-closed by contract — a degenerate
    // velocity is rejected, never silently applied.
    if (!(v0_m_s_ > 0.0) || !std::isfinite(v0_m_s_)) {
        throw std::invalid_argument(
            "v0_m_s must be a positive finite velocity, got " +
            std::to_string(v0_m_s_));
    }
}

std::vector<double> ConstantVelocityDepth::time_ms_to_depth_m(
    const std::vector<double>& time_ms) const {
    return map_all(time_ms, &ConstantVelocityDepth::time_ms_to_depth_m, *this);
}

std::vector<double> ConstantVelocityDepth::depth_m_to_time_ms(
    const std::vector<double>& depth_m) const {
    return map_all(depth_m, &ConstantVelocityDepth::depth_m_to_time_ms, *this);
}

DepthTransformState::DepthTransformState()
    : kind_(DepthTransformKind::None), constant_(3000.0) {}

DepthTransformState::DepthTransformState(
    DepthTransformKind kind, std::optional<ConstantVelocityDepth> constant,
    std::optional<std::string> warning)
    : kind_(kind),
      constant_(constant.has_value() ? *constant : ConstantVelocityDepth()),
      approximate_warning_(std::move(warning)) {
    if (kind_ == DepthTransformKind::ConstantV0) {
        char buf[64];
        std::snprintf(buf, sizeof(buf), "%.0f", constant_.v0_m_s());
        approximate_warning_ =
            std::string("Depth uses constant V0=") + buf +
            " m/s (approximate)";
    } else if (kind_ == DepthTransformKind::WellTzField) {
        // Reserved slot: not implemented; degrade explicitly to V0 with a
        // warning so callers can surface the approximation.
        kind_ = DepthTransformKind::ConstantV0;
        approximate_warning_ = "Well T–Z field not implemented; using V0";
    } else if (kind_ == DepthTransformKind::None) {
        approximate_warning_.reset();
    }
}

DepthTransformState DepthTransformState::none() { return DepthTransformState(); }

DepthTransformState DepthTransformState::external_volume(double v0_m_s) {
    return DepthTransformState(DepthTransformKind::ExternalVolume,
                               ConstantVelocityDepth(v0_m_s), std::nullopt);
}

DepthTransformState DepthTransformState::constant_v0(double v0_m_s) {
    return DepthTransformState(DepthTransformKind::ConstantV0,
                               ConstantVelocityDepth(v0_m_s), std::nullopt);
}

DepthTransformState DepthTransformState::well_tz_field(double v0_m_s) {
    return DepthTransformState(DepthTransformKind::WellTzField,
                               ConstantVelocityDepth(v0_m_s), std::nullopt);
}

double DepthTransformState::time_ms_to_depth_m(double time_ms) const {
    if (!available()) {
        throw std::runtime_error("no depth transform available");
    }
    return constant_.time_ms_to_depth_m(time_ms);
}

double DepthTransformState::depth_m_to_time_ms(double depth_m) const {
    if (!available()) {
        throw std::runtime_error("no depth transform available");
    }
    return constant_.depth_m_to_time_ms(depth_m);
}

std::vector<double> DepthTransformState::time_ms_to_depth_m(
    const std::vector<double>& time_ms) const {
    return map_all(time_ms, &ConstantVelocityDepth::time_ms_to_depth_m,
                   constant_);
}

std::vector<double> DepthTransformState::depth_m_to_time_ms(
    const std::vector<double>& depth_m) const {
    return map_all(depth_m, &ConstantVelocityDepth::depth_m_to_time_ms,
                   constant_);
}

DepthTransformState select_depth_transform(bool has_external_volume,
                                           double v0_m_s, bool constant_v0) {
    if (has_external_volume) {
        return DepthTransformState::external_volume(v0_m_s);
    }
    if (constant_v0) {
        return DepthTransformState::constant_v0(v0_m_s);
    }
    return DepthTransformState::none();
}

}  // namespace pwb::geo3d_viz::joint
