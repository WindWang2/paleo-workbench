#include <pwb/seismic_viewer/attribute_fusion_core.hpp>

#include <pwb/seismic_viewer/display_core.hpp>

#include <algorithm>
#include <cmath>

namespace pwb::seismic_viewer::fusion {
namespace {

// Python: _normalize(a) * 255 astype(uint8) — the numpy chain is float32
// end to end (weak scalars), astype truncates toward zero.
std::uint8_t quantize(float value, float lo32, float span32) {
    if (!std::isfinite(value)) {
        return 0; // NaN cast parity (see header): the reference platform
                  // casts NaN to 0; clip of NaN stays NaN.
    }
    float norm = (value - lo32) / span32;
    norm = std::clamp(norm, 0.0f, 1.0f);
    const float scaled = norm * 255.0f;
    return static_cast<std::uint8_t>(std::trunc(scaled));
}

} // namespace

ChannelPlan channel_plan(std::span<const float> data, double clip_pct) {
    // percentile_clip_range already implements the full _normalize range
    // ladder: nanpercentile pair, nanmin/nanmax fallback (hi <= lo), and the
    // degenerate flag for a constant finite plane. All-NaN returns
    // {NaN, NaN, degenerate=false} — Python's `hi <= lo` is False for NaN,
    // so the channel falls through to clip-of-NaN; we flag it as a zero
    // channel instead (cast parity, declared deviation).
    const display::ClipRange range = display::percentile_clip_range(data, clip_pct);
    if (range.degenerate) {
        return {range.lo, range.hi, true};
    }
    if (!std::isfinite(range.lo) || !std::isfinite(range.hi)) {
        return {0.0, 1.0, true}; // all-NaN channel -> zeros
    }
    if (!(range.hi > range.lo)) {
        return {range.lo, range.hi, true}; // collapsed after fallback
    }
    return {range.lo, range.hi, false};
}

std::vector<std::uint8_t> fuse_rgb(std::span<const float> attr_r,
                                   std::span<const float> attr_g,
                                   std::span<const float> attr_b,
                                   std::int64_t rows, std::int64_t cols,
                                   double clip_pct) {
    const std::size_t cells = static_cast<std::size_t>(rows) * static_cast<std::size_t>(cols);
    std::vector<std::uint8_t> out(cells * 3, 0);
    if (attr_r.size() != cells || attr_g.size() != cells || attr_b.size() != cells ||
        rows <= 0 || cols <= 0) {
        return out; // shape mismatch: honest empty (black) image, no throw
    }
    const ChannelPlan plans[3] = {channel_plan(attr_r, clip_pct),
                                  channel_plan(attr_g, clip_pct),
                                  channel_plan(attr_b, clip_pct)};
    const std::span<const float> channels[3] = {attr_r, attr_g, attr_b};
    for (int c = 0; c < 3; ++c) {
        if (plans[c].zero_channel) {
            continue; // bytes stay 0
        }
        const float lo32 = static_cast<float>(plans[c].lo);
        const float span32 = static_cast<float>(plans[c].hi) - lo32;
        const std::span<const float> data = channels[c];
        for (std::size_t i = 0; i < cells; ++i) {
            out[i * 3 + static_cast<std::size_t>(c)] = quantize(data[i], lo32, span32);
        }
    }
    return out;
}

} // namespace pwb::seismic_viewer::fusion
