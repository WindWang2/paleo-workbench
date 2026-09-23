// algorithm_exec — see algorithm_exec.hpp. The factory table mirrors the
// seismic algorithms the Paleo Processing provider registers
// (libs/qgis_processing/src/algorithms/seismic.cpp): one entry per
// paleo:seismic_<name> id, each constructing the same Qt-free kernel the
// provider wraps.

#include "algorithm_exec.hpp"

#include <string_view>
#include <utility>

#include <pwb/science/algorithms/coherence_c3.hpp>
#include <pwb/seismic_attributes/attributes.hpp>

namespace pwb::app {
namespace {

using Factory = std::unique_ptr<pwb::science::IAlgorithm> (*)();
constexpr auto kBuild = "pwb-platform";

// Sorted by paleo name so lookups and future diffing against
// paleo_algorithm_ids() stay stable.
const std::pair<const char*, Factory> kFactories[] = {
    {"seismic_coherence_c3",
     []() -> std::unique_ptr<pwb::science::IAlgorithm> {
         return pwb::science::algorithms::make_coherence_c3(kBuild);
     }},
    {"seismic_curvature_mean",
     []() -> std::unique_ptr<pwb::science::IAlgorithm> {
         return pwb::seismic_attributes::make_curvature_mean(kBuild);
     }},
    {"seismic_dip_azimuth",
     []() -> std::unique_ptr<pwb::science::IAlgorithm> {
         return pwb::seismic_attributes::make_dip_azimuth(kBuild);
     }},
    {"seismic_dip_il",
     []() -> std::unique_ptr<pwb::science::IAlgorithm> {
         return pwb::seismic_attributes::make_dip_inline(kBuild);
     }},
    {"seismic_dip_xl",
     []() -> std::unique_ptr<pwb::science::IAlgorithm> {
         return pwb::seismic_attributes::make_dip_crossline(kBuild);
     }},
    {"seismic_envelope",
     []() -> std::unique_ptr<pwb::science::IAlgorithm> {
         return pwb::seismic_attributes::make_envelope(kBuild);
     }},
    {"seismic_instantaneous_frequency",
     []() -> std::unique_ptr<pwb::science::IAlgorithm> {
         return pwb::seismic_attributes::make_instantaneous_frequency(kBuild);
     }},
    {"seismic_instantaneous_phase",
     []() -> std::unique_ptr<pwb::science::IAlgorithm> {
         return pwb::seismic_attributes::make_instantaneous_phase(kBuild);
     }},
    {"seismic_relative_impedance",
     []() -> std::unique_ptr<pwb::science::IAlgorithm> {
         return pwb::seismic_attributes::make_relative_impedance(kBuild);
     }},
    {"seismic_rms_amplitude",
     []() -> std::unique_ptr<pwb::science::IAlgorithm> {
         return pwb::seismic_attributes::make_rms_amplitude(kBuild);
     }},
    {"seismic_sweetness",
     []() -> std::unique_ptr<pwb::science::IAlgorithm> {
         return pwb::seismic_attributes::make_sweetness(kBuild);
     }},
};

constexpr std::string_view kPaleoPrefix = "paleo:";

}  // namespace

std::unique_ptr<pwb::science::IAlgorithm> make_science_algorithm(
    const std::string& paleo_name) {
    std::string name = paleo_name;
    if (name.starts_with(kPaleoPrefix)) {
        name = name.substr(kPaleoPrefix.size());
    }
    for (const auto& [registered, factory] : kFactories) {
        if (name == registered) return factory();
    }
    return nullptr;
}

pwb::seismic_viewer::crossplot::AlgorithmResolver paleo_crossplot_resolver() {
    return [](const std::string& id)
               -> std::unique_ptr<pwb::science::IAlgorithm> {
        // Both identity shapes reach the same table entry:
        // "seismic.envelope" and "paleo:seismic_envelope".
        std::string name = id;
        constexpr std::string_view kSciencePrefix = "seismic.";
        if (name.rfind(kSciencePrefix) == 0) {
            name = "seismic_" + name.substr(kSciencePrefix.size());
        }
        return make_science_algorithm(name);
    };
}

}  // namespace pwb::app
