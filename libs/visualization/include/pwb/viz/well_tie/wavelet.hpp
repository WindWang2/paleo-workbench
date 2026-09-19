#pragma once

// VIZ-B — seismic wavelet generation (Ricker, Ormsby).
// Verbatim port of geoviz_well_tie/wavelet.py (the canonical set exported by
// the package __init__; the legacy wavelet_engine.py time-axis variant is
// intentionally NOT ported — see docs/development/cpp-viz-b/scope.md).

#include <string>
#include <vector>

namespace pwb::viz::well_tie {

// Ricker (Mexican-hat) wavelet, float32-amplitude parity:
//   t = arange(n) * dt - t[n/2]
//   p2 = (pi * f * t)^2 ; w = (1 - 2*p2) * exp(-p2)
// No explicit normalization (the formula peaks at exactly 1 for odd n).
// n_samples should be odd for a zero-centred wavelet. dt is in SECONDS.
[[nodiscard]] std::vector<float> ricker_wavelet(int n_samples, double dt,
                                                double peak_freq);

// Ormsby band-pass wavelet (Ryan 1994): each band group divided by its own
// bandwidth (fixes the 2x band-weight ratio, #540); normalized to unit peak
// amplitude. np.sinc is the normalized sinc (sinc(0) = 1). dt in SECONDS.
[[nodiscard]] std::vector<float> ormsby_wavelet(int n_samples, double dt,
                                                double f1, double f2,
                                                double f3, double f4);

}  // namespace pwb::viz::well_tie
