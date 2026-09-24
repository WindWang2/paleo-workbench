#pragma once

// algorithm_exec — product-side science-kernel executor over the paleo
// algorithm vocabulary (CONV-QGIS-PROCESSING phase 4).
//
// GUI paths that hold plain in-memory planes (2-D section attributes, the
// attribute crossplot) cannot go through QgsProcessingRegistry's file-based
// INPUT/OUTPUT contract without staging I/O they do not need. This seam
// keeps them on the SAME identity vocabulary — the paleo algorithm name
// ("paleo:seismic_envelope" or "seismic_envelope") — while constructing
// the registered kernel directly. The registry (provider "paleo") stays
// the single authority for which algorithms exist; this table is the
// execution mirror of the seismic family it exposes.

#include <memory>
#include <string>

#include <pwb/science/algorithm.hpp>
#include <pwb/seismic_viewer/crossplot_core.hpp>

namespace pwb::app {

// paleo:seismic_envelope / seismic_envelope -> make_envelope("pwb-platform")
// style factory lookup over the seismic attribute family (the 10
// pwb::seismic_attributes kernels + seismic.coherence_c3). Returns null
// for names outside the family (callers fail closed).
[[nodiscard]] std::unique_ptr<pwb::science::IAlgorithm> make_science_algorithm(
    const std::string& paleo_name);

// Product-side binding of seismic_viewer's AlgorithmResolver seam (the
// attribute crossplot): accepts the science id ("seismic.envelope") and
// the paleo id ("paleo:seismic_envelope") — both resolve to a fresh owned
// kernel from the same table. Pass to prepare_attribute_crossplot where
// the product drives the attribute crossplot.
[[nodiscard]] pwb::seismic_viewer::crossplot::AlgorithmResolver
paleo_crossplot_resolver();

}  // namespace pwb::app
