#pragma once

// seismic.coherence_c3 — C3 eigenstructure coherence (Marfurt et al., 1998).
//
// Ported from the frozen production path
//   paleo_workbench/providers/builtin/seismic_attribute.py (kernel "c3")
//     -> paleo_workbench/seismic_attributes.py KERNELS["c3"]
//       -> geoviz_seismic.attributes.compute_coherence_c3 @ 08851951
// whose numpy implementation is the numeric oracle (frozen fixtures in
// tests/cpp/science/fixtures/coherence_c3). Semantics replicated exactly:
// half-windows win_* (>=1), window size min(2w+1, n) forced odd, reflect
// padding, 30 power iterations on the implicit covariance, coherence =
// lambda_max / total_energy, 1.0 where total energy is not strictly positive
// (NaN windows included).

#include <memory>
#include <string>

#include <pwb/science/algorithm.hpp>

namespace pwb::science::algorithms {

[[nodiscard]] std::unique_ptr<IAlgorithm> make_coherence_c3(std::string build_identity);

} // namespace pwb::science::algorithms
