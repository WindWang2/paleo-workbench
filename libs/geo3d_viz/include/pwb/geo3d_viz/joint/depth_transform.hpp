// Depth transform priority chain (#63 / grill E) — port of
// geoviz_well_seismic_3d/depth_transform.py @ 08851951.
//
// Fail-closed policy: without an authoritative time-depth transform
// (velocity model, checkshot fit, or depth-converted cube) the Depth
// domain is UNAVAILABLE. A constant-V0 conversion is only ever installed
// through an explicit select_depth_transform(constant_v0=true) opt-in so
// callers cannot mistake approximate scaling for depth.
#pragma once

#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace pwb::geo3d_viz::joint {

enum class DepthTransformKind {
    None,            // no authoritative transform → Depth unavailable
    ExternalVolume,  // depth-converted cube
    ConstantV0,      // explicit approximate opt-in
    WellTzField,     // reserved; degrades to ConstantV0 with a warning
};

// Z_depth_m = V0_m_s * TWT_s / 2.
class ConstantVelocityDepth {
public:
    explicit ConstantVelocityDepth(double v0_m_s = 3000.0);

    double v0_m_s() const { return v0_m_s_; }

    double time_ms_to_depth_m(double time_ms) const {
        return time_ms * 1e-3 * v0_m_s_ / 2.0;
    }
    double depth_m_to_time_ms(double depth_m) const {
        return (depth_m * 2.0 / v0_m_s_) * 1e3;
    }
    std::vector<double> time_ms_to_depth_m(
        const std::vector<double>& time_ms) const;
    std::vector<double> depth_m_to_time_ms(
        const std::vector<double>& depth_m) const;

private:
    double v0_m_s_;  // positive finite (validated; #147 fail-closed)
};

// Active depth transform selection. kind == None means no transform is
// available; Depth-domain features must refuse to run rather than fake
// depth with uniform scaling.
class DepthTransformState {
public:
    DepthTransformState();

    static DepthTransformState none();
    static DepthTransformState external_volume(double v0_m_s = 3000.0);
    static DepthTransformState constant_v0(double v0_m_s = 3000.0);
    // Reserved slot in Python; degrades explicitly to V0 with a warning.
    static DepthTransformState well_tz_field(double v0_m_s = 3000.0);

    DepthTransformKind kind() const { return kind_; }
    const ConstantVelocityDepth& constant() const { return constant_; }
    const std::optional<std::string>& approximate_warning() const {
        return approximate_warning_;
    }

    // True when a real (or explicitly opted-in approximate) transform
    // exists.
    bool available() const { return kind_ != DepthTransformKind::None; }

    double time_ms_to_depth_m(double time_ms) const;
    double depth_m_to_time_ms(double depth_m) const;
    std::vector<double> time_ms_to_depth_m(
        const std::vector<double>& time_ms) const;
    std::vector<double> depth_m_to_time_ms(
        const std::vector<double>& depth_m) const;

private:
    DepthTransformState(DepthTransformKind kind,
                        std::optional<ConstantVelocityDepth> constant,
                        std::optional<std::string> warning);

    DepthTransformKind kind_;
    ConstantVelocityDepth constant_;
    std::optional<std::string> approximate_warning_;
};

// Priority: external volume → explicit constant V0 → none. The default
// return is an UNAVAILABLE transform (fail-closed).
DepthTransformState select_depth_transform(bool has_external_volume = false,
                                            double v0_m_s = 3000.0,
                                            bool constant_v0 = false);

}  // namespace pwb::geo3d_viz::joint
