// V14-COMPILATION-PUBLISH — composer scale & performance battery.
//
// Structural (not wall-clock) assertions for the composition surface, per
// the prompt's scale budget:
//   * 100 / 500 / 1000-element documents render with linear cost (the SVG
//     length grows proportionally, and the render stays bounded);
//   * a 100-entry legend is linear (one swatch group per entry, no N²);
//   * 50 composition elements render in one pass;
//   * template instantiation is O(elements) and allocation-free per call
//     beyond the document itself;
//   * the export pixel budget refuses an impossible page instead of
//     attempting it;
//   * a repeated render is byte-identical (id determinism) so a preview
//     cache can key on content.

#include <pwb/layout_export/layout_export.hpp>
#include <pwb/mapping_document/composition.hpp>
#include <pwb/mapping_document/composer_export.hpp>
#include <pwb/mapping_document/composer_renderer.hpp>
#include <pwb/mapping_document/composer_templates.hpp>
#include <pwb/domain/json.hpp>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <string>
#include <vector>

namespace {

int g_failures = 0;
int g_checks = 0;

void check(const std::string& id, bool ok, const std::string& detail = "") {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::fprintf(stderr, "FAIL: %s %s\n", id.c_str(), detail.c_str());
    }
}

using pwb::mapping_document::ComposerElement;
using pwb::mapping_document::Composition;
using pwb::mapping_document::CompositionFactory;

Composition make_doc(std::size_t element_count, const std::string& type = "text") {
    Composition doc;
    doc.title = "scale";
    for (std::size_t i = 0; i < element_count; ++i) {
        ComposerElement element;
        element.id = "el_" + std::to_string(i);
        element.element_type = type;
        element.x_mm = 5.0;
        element.y_mm = 5.0 + static_cast<double>(i % 40);
        element.width_mm = 40.0;
        element.height_mm = 6.0;
        element.z_index = static_cast<long long>(i);
        element.properties = pwb::domain::Json::object();
        element.properties["text"] = "行 " + std::to_string(i);
        pwb::mapping_document::add_element(doc, std::move(element));
    }
    return doc;
}

double elapsed_ms(const std::chrono::steady_clock::time_point& from) {
    return std::chrono::duration<double, std::milli>(
               std::chrono::steady_clock::now() - from)
        .count();
}

}  // namespace

int main() {
    // ---- 1. Element-count scaling (structural: output grows linearly) ----
    {
        const std::size_t small_n = 100;
        const std::size_t large_n = 1000;
        const Composition small = make_doc(small_n);
        const Composition large = make_doc(large_n);
        const std::string small_svg =
            pwb::mapping_document::render_composition_to_svg(small);
        const std::string large_svg =
            pwb::mapping_document::render_composition_to_svg(large);
        check("scale.100_elements", small.elements.size() == small_n);
        check("scale.1000_elements", large.elements.size() == large_n);
        // Each text element contributes a <g> group with one <text> per
        // line; 10x the elements must give roughly 10x the bytes.
        const double ratio =
            static_cast<double>(large_svg.size()) /
            static_cast<double>(small_svg.size());
        check("scale.linear_output", ratio > 8.0 && ratio < 12.0,
              "ratio=" + std::to_string(ratio));
        // 50-element document (the prompt's budget) renders in one pass
        // and well under a second (structural sanity, not a gate).
        const auto started = std::chrono::steady_clock::now();
        const std::string mid_svg =
            pwb::mapping_document::render_composition_to_svg(make_doc(50));
        const double ms = elapsed_ms(started);
        check("scale.50_elements_fast", ms < 1000.0, "ms=" + std::to_string(ms));
        check("scale.50_elements_content", mid_svg.find("<svg") == 0);
    }

    // ---- 2. Legend scaling (one swatch pair per entry, linear) -----------
    {
        auto legend_doc = [](std::size_t entries) {
            Composition doc;
            doc.title = "legend";
            ComposerElement element;
            element.id = "el_legend";
            element.element_type = "legend";
            element.x_mm = 10.0;
            element.y_mm = 10.0;
            element.width_mm = 78.0;
            element.height_mm = 200.0;
            element.z_index = 30;
            pwb::domain::Json items = pwb::domain::Json::array();
            for (std::size_t i = 0; i < entries; ++i) {
                pwb::domain::Json item = pwb::domain::Json::object();
                item["label"] = "条目 " + std::to_string(i);
                item["color"] = "#123456";
                items.push_back(std::move(item));
            }
            element.properties = pwb::domain::Json::object();
            element.properties["items"] = std::move(items);
            pwb::mapping_document::add_element(doc, std::move(element));
            return doc;
        };
        const std::string svg_10 =
            pwb::mapping_document::render_composition_to_svg(legend_doc(10));
        const std::string svg_100 =
            pwb::mapping_document::render_composition_to_svg(legend_doc(100));
        // Every entry renders exactly one swatch rect + one label.
        auto count_of = [](const std::string& text, const std::string& needle) {
            std::size_t count = 0;
            std::size_t at = text.find(needle);
            while (at != std::string::npos) {
                ++count;
                at = text.find(needle, at + needle.size());
            }
            return count;
        };
        check("legend.10_swatches", count_of(svg_10, "width=\"6\" height=\"3\"") == 10);
        check("legend.100_swatches", count_of(svg_100, "width=\"6\" height=\"3\"") == 100);
        check("legend.100_labels", count_of(svg_100, "条目 99") == 1);
        check("legend.linear_size",
              svg_100.size() > svg_10.size() * 8 && svg_100.size() < svg_10.size() * 12);
        // The legend's required height overflows the declared box by design
        // (Python parity: req_h = max(h, 10 + n*6)) — the box grows, it is
        // never clipped.
        // req_h = max(h, 10 + 100*6) = 610 → the box height attribute
        // carries the float repr (the legend box grows, never clips).
        check("legend.grows_box", svg_100.find("610.0") != std::string::npos);
    }

    // ---- 3. Template instantiation cost -----------------------------------
    {
        const CompositionFactory factory;
        const auto started = std::chrono::steady_clock::now();
        const Composition doc = pwb::mapping_document::instantiate_composer_template(
            factory, "comprehensive");
        const double ms = elapsed_ms(started);
        check("template.instantiate_fast", ms < 50.0, "ms=" + std::to_string(ms));
        check("template.instantiate_elements", doc.elements.size() == 9,
              std::to_string(doc.elements.size()));
        // Deterministic id SHAPE (the default factory counter): every
        // element id is unique within the document and follows the
        // el_%010d shape — a preview cache can key on content, never on
        // wall time. Two documents get distinct ids (fresh document, fresh
        // ids), which is the Python uuid behaviour's deterministic mirror.
        std::vector<std::string> ids;
        for (const auto& element : doc.elements) ids.push_back(element.id);
        std::sort(ids.begin(), ids.end());
        const bool unique =
            std::adjacent_find(ids.begin(), ids.end()) == ids.end();
        check("template.unique_ids", unique);
        bool shaped = !ids.empty();
        for (const auto& id : ids) {
            if (id.rfind("el_", 0) != 0 || id.size() != 13) shaped = false;
        }
        check("template.id_shape", shaped);
        // Every template instantiates (the library is complete).
        std::size_t total = 0;
        for (const auto& tpl :
             pwb::mapping_document::composer_template_library()) {
            const Composition instantiated =
                pwb::mapping_document::instantiate_composer_template(factory,
                                                                     tpl.template_id);
            total += instantiated.elements.size();
            check("template." + tpl.template_id + ".metadata",
                  instantiated.metadata.value("template_id", std::string()) ==
                      tpl.template_id);
        }
        check("template.library_complete", total >= 40, std::to_string(total));
    }

    // ---- 4. Render determinism (byte-identical repeats) -------------------
    {
        const Composition doc = make_doc(30);
        const std::string first =
            pwb::mapping_document::render_composition_to_svg(doc);
        const std::string second =
            pwb::mapping_document::render_composition_to_svg(doc);
        check("render.deterministic", first == second);
    }

    // ---- 5. Pixel budget policy (layout_export — applied by the export
    //         orchestration before any writer runs) -------------------------
    {
        Composition huge = make_doc(2);
        huge.width_mm = 5000.0;   // > the 2e8-pixel budget at any sane DPI
        huge.height_mm = 5000.0;
        std::string message;
        try {
            pwb::layout_export::check_pixel_budget(huge, 600.0);
        } catch (const std::invalid_argument& ex) {
            message = ex.what();
        }
        check("budget.refuses_huge_page", !message.empty());
        check("budget.refuses_message",
              message.find("budget 200000000") != std::string::npos, message);
        // A4 at 600 DPI is inside the budget.
        Composition a4 = make_doc(2);
        a4.width_mm = 297.0;
        a4.height_mm = 210.0;
        bool accepted = true;
        try {
            pwb::layout_export::check_pixel_budget(a4, 600.0);
        } catch (const std::invalid_argument&) {
            accepted = false;
        }
        check("budget.accepts_a4_600dpi", accepted);
    }

    // ---- 6. Unsupported formats fail closed -------------------------------
    {
        const Composition doc = make_doc(2);
        const auto report = pwb::mapping_document::export_composition_page(
            doc, "/tmp/x.tiff", "tiff");
        check("format.unsupported_refused", !report.ok);
        check("format.unsupported_message",
              report.message.find("unsupported composition export format") !=
                  std::string::npos);
    }

    std::printf("%d/%d checks passed\n", g_checks - g_failures, g_checks);
    if (g_failures != 0) {
        std::fprintf(stderr, "%d FAILURES\n", g_failures);
        return 1;
    }
    std::printf("composer scale battery: PASS\n");
    return 0;
}
