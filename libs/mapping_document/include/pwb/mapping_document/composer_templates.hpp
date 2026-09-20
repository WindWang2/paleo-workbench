#pragma once

// Native composer template library (V14-COMPILATION-PUBLISH).
//
// Faithful port of paleo_workbench/mapping/composer/templates.py — the
// declarative TEMPLATE_LIBRARY (9 built-in composition templates) plus
// instantiate_template. A template is NOT a bitmap: it declares the
// components it instantiates (type, mm geometry, z-order), style bindings
// and data bindings; live data is attached later through
// composition_session's bind_template with real content.
//
// Parity contract (frozen by tools/oracle/generate_composer_fixtures.py):
//   * instantiate_template(template_id, title?, paper_size?, orientation?,
//     dpi?) → Composition built via CompositionFactory (create_document
//     with `or`-falsy semantics: empty/0 arguments fall back to the
//     template's own values), metadata["template_id"] /
//     ["template_category"] set, element definitions materialised in
//     z_index-sorted order with fresh ids and deep-copied properties, and
//     an explicit title overwriting the first TITLE element's text;
//   * unknown template ids raise std::invalid_argument (Python KeyError);
//   * every template declares paper A4 landscape unless overridden, and
//     the shared geometry helpers (_base_map_frames /
//     _factor_map_components) reproduce the Python float arithmetic.
//
// Qt-free, Python-free.

#include <pwb/mapping_document/composition.hpp>
#include <pwb/mapping_document/composition_session.hpp>

#include <optional>
#include <string>
#include <vector>

namespace pwb::mapping_document {

// One component slot inside a template layout (ElementDefinition).
struct TemplateElementDefinition {
    std::string element_type;
    double x_mm = 0.0;
    double y_mm = 0.0;
    double width_mm = 1.0;
    double height_mm = 1.0;
    long long z_index = 0;
    Json properties;  // object payload (may be null for {})
};

// CompositionTemplate (frozen dataclass mirror).
struct CompositionTemplate {
    std::string template_id;
    std::string category;
    std::string label;
    std::string description;
    std::string paper_size = "A4";
    std::string orientation = "landscape";
    std::vector<TemplateElementDefinition> element_definitions;
    Json style_bindings;   // object payload
    Json data_bindings;    // object payload
};

// TEMPLATE_LIBRARY values in Python registration order (dict insertion
// order — the template menu order).
const std::vector<CompositionTemplate>& composer_template_library();

// TEMPLATE_LIBRARY lookup; nullptr when the id is unknown.
const CompositionTemplate* find_composer_template(const std::string& template_id);

// Shared geometry helper (templates.py _base_map_frames):
// (margin, top, paper_w - 2*margin - 88, paper_h - top - bottom) with
// margin = min(12.0, paper_w * 0.05), top = 24.0, bottom = 34.0.
std::array<double, 4> template_base_map_frames(double paper_w_mm,
                                               double paper_h_mm);

// Materialize a template into a fresh composition document
// (templates.py instantiate_template). Throws std::invalid_argument for an
// unknown template id (Python KeyError parity). Elements are appended in
// z_index-sorted order; ids come from the factory's generator (Python uses
// uuid4 — the C++ factory default is the deterministic counter, hosts
// inject a uuid-style generator for production id shape).
[[nodiscard]] Composition instantiate_composer_template(
    const CompositionFactory& factory, const std::string& template_id,
    const std::optional<std::string>& title = std::nullopt,
    const std::optional<std::string>& paper_size = std::nullopt,
    const std::optional<std::string>& orientation = std::nullopt,
    const std::optional<double>& dpi = std::nullopt);

}  // namespace pwb::mapping_document
