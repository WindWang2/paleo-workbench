#include <pwb/mapping_document/composer_export.hpp>

#include <pwb/mapping_document/document_io.hpp>

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <system_error>
#include <vector>

namespace pwb::mapping_document {
namespace {

std::string lower(std::string text) {
    std::transform(text.begin(), text.end(), text.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return text;
}

// The re-anchored SVG, written through the document_io atomic store
// (temp → fsync → replace; a failed write leaves no partial file).
bool write_svg_atomic(const std::filesystem::path& path, const std::string& svg,
                      std::string& error) {
    std::error_code ec;
    const std::filesystem::path parent = path.parent_path();
    if (!parent.empty()) {
        std::filesystem::create_directories(parent, ec);
        if (ec) {
            error = "could not create output directory: " + ec.message();
            return false;
        }
    }
    auto store = make_std_file_store();
    if (!store->write_atomic(path.string(), svg, error)) return false;
    // Readback: the exported page must exist and be non-empty.
    std::string bytes;
    std::string read_error;
    if (!store->read(path.string(), bytes, read_error) || bytes.empty()) {
        error = "export readback failed: " + read_error;
        return false;
    }
    if (bytes.find("</svg>") == std::string::npos) {
        error = "export readback failed: not a complete SVG document";
        return false;
    }
    return true;
}

}  // namespace

std::string composition_export_svg(const Composition& doc) {
    return reanchor_composition_svg(render_composition_to_svg(doc), doc.width_mm,
                                    doc.height_mm);
}

std::string composition_export_svg_with_seams(const Composition& doc,
                                              const ComposerRenderSeams& render_seams) {
    return reanchor_composition_svg(render_composition_to_svg(doc, render_seams),
                                    doc.width_mm, doc.height_mm);
}

CompositionExportReport export_composition_page(
    const Composition& doc, const std::filesystem::path& path,
    const std::string& format, std::optional<double> dpi,
    const ComposerRenderSeams& render_seams, const ComposerReplaySeams& replay) {
    CompositionExportReport report;
    report.path = path.string();
    // Python: format_name = (fmt or out.suffix.lstrip(".") or "png").lower()
    std::string format_name = format;
    if (format_name.empty()) {
        format_name = path.has_extension() ? path.extension().string() : "";
        if (!format_name.empty() && format_name.front() == '.') {
            format_name.erase(format_name.begin());
        }
    }
    format_name = lower(format_name);
    if (format_name.empty()) format_name = "png";

    const double effective_dpi = dpi.has_value() ? *dpi : doc.dpi;
    report.dpi = effective_dpi;
    report.format = format_name;

    if (format_name != "svg" && format_name != "png" && format_name != "pdf") {
        // Python: ValueError f"unsupported composition export format {…!r}"
        report.message = "unsupported composition export format '" + format_name + "'";
        return report;
    }

    const std::string svg = composition_export_svg_with_seams(doc, render_seams);
    if (format_name == "svg") {
        std::string error;
        report.ok = write_svg_atomic(path, svg, error);
        report.message = error;
        return report;
    }

    // PNG/PDF: the paint device lives on the host (Qt). No seam ⇒ honest
    // refusal — never a fabricated raster.
    if (!replay.replay) {
        report.message = "no composition replay device available";
        return report;
    }
    std::string message;
    const bool ok = replay.replay(svg, path.string(), format_name, effective_dpi,
                                  doc.width_mm, doc.height_mm, message);
    if (!ok) {
        report.message = message.empty() ? "composition replay failed" : message;
        // Readback/verification of the device output is the host's job; a
        // failed replay must not leave a file behind.
        std::error_code ec;
        if (std::filesystem::exists(path, ec)) std::filesystem::remove(path, ec);
        return report;
    }
    // Readback: the exported page must exist and be non-empty.
    std::error_code ec;
    if (!std::filesystem::exists(path, ec) ||
        std::filesystem::file_size(path, ec) == 0) {
        report.message = "export readback failed: missing or empty output file";
        return report;
    }
    report.ok = true;
    report.message.clear();
    return report;
}

}  // namespace pwb::mapping_document
