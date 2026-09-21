#pragma once

// pwb::interchange — resources/exporters.py port: the shared converter
// table (get_available_formats / extension_for_label), ExportError, and the
// Qt-free file→file converters.
//
// Every converter writes through AtomicOutputFile (Python atomic_output
// parity) so a failed export never leaves a corrupt partial file at the
// user-visible destination. Failures raise ExportError with the Python
// message vocabulary ("LAS -> CSV 失败: ..." etc.).
//
// Declared seams (no fake parity):
//   * image_to_png needs a real image decoder — hosts install a provider
//     (QImage on the Qt shell); without one the call raises ExportError
//     instead of writing a bogus file.
//   * XLSX read/write is the bounded in-module OOXML surface (shared
//     strings + first worksheet); pandas/openpyxl exotic features (merged
//     cells, formulas, styles) are out of scope — converters only need the
//     plain table grid pandas produces/consumes.
//   * seismic_to_summary_json maps inspect_segy's VolumeDescriptor onto the
//     geoviz SeismicLoader inspect payload (source/n_inlines/n_crosslines/
//     n_samples/dt_ms/t0_ms/iline/xline start+step).

#include <filesystem>
#include <functional>
#include <string>
#include <string_view>
#include <unordered_set>
#include <utility>
#include <vector>

namespace pwb::interchange {

namespace fs = std::filesystem;

// resources/exporters.ExportError parity — message text carries the
// "LAS -> CSV 失败: <cause>" vocabulary verbatim.
class ExportError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// ---------------------------------------------------------------------------
// Format registry (io_registry.CONVERT_LABEL_EXT + exporters._CONVERTERS)
// ---------------------------------------------------------------------------

// CONVERT_LABEL_EXT.get(label, ".out") parity.
std::string extension_for_label(std::string_view label);

using ConvertFn = std::function<void(const fs::path& input,
                                     const fs::path& output)>;

struct ConverterSpec {
    std::string label;                     // "CSV" | "XLSX" | ...
    std::unordered_set<std::string> inputs;  // lowercase exts, no dot
    ConvertFn fn;
};

// Ordered converter table — the Python _CONVERTERS list verbatim.
const std::vector<ConverterSpec>& converters();

// get_available_formats parity: fmt is the asset format (lowercase ext,
// leading dot tolerated). Unique labels, first converter wins on collision.
std::vector<std::pair<std::string, ConvertFn>> get_available_formats(
    std::string_view format);

// ---------------------------------------------------------------------------
// Image decode seam
// ---------------------------------------------------------------------------

// (input_path, output_path) → true on success. The host (Qt shell) installs
// a QImage-backed provider at startup; without one image_to_png raises
// ExportError — honest unavailability instead of a wrong-byte copy.
using ImagePngProvider =
    std::function<bool(const fs::path& input, const fs::path& output)>;
void set_image_png_provider(ImagePngProvider provider);
bool image_png_provider_installed();

// ---------------------------------------------------------------------------
// Converters (resources/exporters.py function parity)
// ---------------------------------------------------------------------------

void las_to_csv(const fs::path& input, const fs::path& output);
void las_to_xlsx(const fs::path& input, const fs::path& output);
void las_to_json_summary(const fs::path& input, const fs::path& output);
void table_to_json(const fs::path& input, const fs::path& output);
void table_to_xlsx(const fs::path& input, const fs::path& output);
void image_to_png(const fs::path& input, const fs::path& output);
void text_to_txt(const fs::path& input, const fs::path& output);
void geojson_normalize(const fs::path& input, const fs::path& output);
void seismic_to_summary_json(const fs::path& input, const fs::path& output);

}  // namespace pwb::interchange
