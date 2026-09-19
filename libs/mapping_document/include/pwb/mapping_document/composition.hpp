// Qt-free MapCompositionDocument / ComposerElement JSON kernel (CONV-02).
//
// Port of the to_dict/from_dict contract of
// paleo_workbench/mapping/composer/models.py, including:
//   * the declared-field key order (id, element_type, x_mm, y_mm, width_mm,
//     height_mm, z_index, visible, locked, properties / + schema_version,
//     elements, metadata at the top level);
//   * the forward-compat TEXT carrier for unknown element types
//     (properties["_raw_element_type"], setdefault semantics on read,
//     pop-on-write — including the quirk that a marker stored on a genuine
//     "text" element is popped and used as the element type);
//   * the Python falsy coercions (`x or default` for numerics and strings
//     versus `payload.get(key, default)` for visible/locked);
//   * stable z_index sorting on parse and on add_element;
//   * set_paper with the exact Python error message;
//   * composition_page_pixels, the single mm→device-pixel fold
//     (Python round = banker's rounding → std::nearbyint).
//
// Deviation from Python (deliberate, prompt §7.4): unknown element fields and
// unknown top-level keys are preserved in `extras` and re-emitted, where
// Python's from_dict silently drops them. See decision D-08.
#pragma once

#include <pwb/domain/json.hpp>

#include <string>
#include <utility>
#include <vector>

namespace pwb::mapping_document {

using Json = pwb::domain::Json;

struct ComposerElement {
    std::string id;
    std::string element_type = "text";
    // True when the input element_type is not in the known vocabulary and is
    // carried through a TEXT element (the raw value travels in properties
    // under "_raw_element_type", exactly like ComposerElement.from_dict).
    bool carried_raw_type = false;
    double x_mm = 0.0;
    double y_mm = 0.0;
    double width_mm = 1.0;
    double height_mm = 1.0;
    long long z_index = 0;
    bool visible = true;
    bool locked = false;
    Json properties;  // object payload, verbatim (minus the raw-type marker)
    Json extras;      // unknown element fields, order preserved
};

struct Composition {
    std::string id;
    std::string title;
    std::string paper_size = "A4";
    std::string orientation = "landscape";
    double width_mm = 297.0;
    double height_mm = 210.0;
    double dpi = 300.0;
    // Written on dump; a payload's own schema_version is never read back
    // (models.py contract: re-serialization always declares the current one).
    long long schema_version = 2;
    std::vector<ComposerElement> elements;  // kept sorted by z_index
    Json metadata;  // object payload, verbatim
    Json extras;    // unknown top-level keys, order preserved
};

// Throws std::invalid_argument when a known scalar cannot be coerced (the
// Python from_dict would raise an uncaught ValueError).
ComposerElement parse_composer_element(const Json& payload);
Json dump_composer_element(const ComposerElement& element);

Composition parse_composition(const Json& payload);
Json dump_composition(const Composition& doc);

// Appends and re-sorts by z_index (std::stable_sort — Python list.sort is
// stable, ties keep insertion order).
void add_element(Composition& doc, ComposerElement element);
ComposerElement* find_element(Composition& doc,
                                   const std::string& element_id);

// models.py set_paper: unknown size → std::invalid_argument with the exact
// Python message ("unknown paper size 'b5'"); any orientation other than
// "portrait" is landscape.
void set_paper(Composition& doc, const std::string& paper_size,
               const std::string& orientation);

// The PAPER_SIZES_MM lookup behind set_paper, exposed for edit sessions that
// must validate before building an undoable command. On a hit returns true,
// stores the canonical upper-case name handling and the (short, long)
// portrait edges in mm; unknown sizes return false.
bool known_paper_size(const std::string& paper_size, std::string& canonical,
                      std::pair<double, double>& short_long_mm);

// Physical page size in device pixels (the single DPI fold): max(1, round(w
// / 25.4 * dpi)) with Python's banker's rounding, evaluated in the same
// IEEE754 order as the Python expression.
std::pair<long long, long long> composition_page_pixels(
    const Composition& doc, double dpi);

}  // namespace pwb::mapping_document
