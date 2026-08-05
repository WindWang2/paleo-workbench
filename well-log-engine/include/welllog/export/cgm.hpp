#pragma once

// CGM Version 3 **Binary** subset exporter (B1.CGM.1–2 / ADR 0054).
//
// Self-written — no third-party CGM SDK. Consumes PreparedScene (same model as
// SVG/PDF). Emits one PICTURE with:
//   - metafile / picture delimiter skeleton
//   - integer VDC (0.01 mm units)
//   - curve polylines + track frames
//   - interval / fill regions as solid POLYGON (pattern → solid + diagnostic)
//   - restricted TEXT for Latin/ASCII labels
//
// B1.CGM.2 adds degradation diagnostics and host/Python export entry points.
// Pagination multi-PICTURE and pattern hatch fidelity remain B1.CGM.3.

#include <cstdint>
#include <memory>
#include <span>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <welllog/core/result.hpp>
#include <welllog/export/cgm_export.hpp>
#include <welllog/scene/scene.hpp>

namespace welllog {

class WELLLOG_EXPORT_CGM_API CgmDocument {
public:
  CgmDocument();
  ~CgmDocument();
  CgmDocument(const CgmDocument &);
  CgmDocument &operator=(const CgmDocument &);
  CgmDocument(CgmDocument &&) noexcept;
  CgmDocument &operator=(CgmDocument &&) noexcept;

  [[nodiscard]] std::string_view bytes() const noexcept;

private:
  struct Impl;
  explicit CgmDocument(std::shared_ptr<const Impl> impl);
  std::shared_ptr<const Impl> impl_;
  friend class CgmBinaryWriter;
  friend class CgmSceneExporter;
};

// Out-of-band degradation notes (ADR 0054: pattern/alpha must not silently look
// complete). Filled by CgmSceneExporter when a non-null pointer is passed.
struct WELLLOG_EXPORT_CGM_API CgmExportDiagnostics {
  std::uint32_t patterns_flattened_to_solid{0};
  std::uint32_t alpha_flattened_to_opaque{0};
  std::uint32_t non_latin_text_dropped{0};
  std::uint32_t intervals_emitted{0};
  std::uint32_t fill_regions_emitted{0};
  std::vector<std::string> notes;

  [[nodiscard]] bool empty() const noexcept {
    return patterns_flattened_to_solid == 0 && alpha_flattened_to_opaque == 0 &&
           non_latin_text_dropped == 0 && notes.empty();
  }

  // Single human-readable summary for host UI / tests.
  [[nodiscard]] std::string summary() const;
};

// Low-level binary command stream (ISO/IEC 8632-3 subset). Coordinates are
// integer VDC; one unit = 0.01 mm (centi-millimetre). Origin bottom-left,
// y-up (scene y-down is flipped by the scene exporter).
class WELLLOG_EXPORT_CGM_API CgmBinaryWriter {
public:
  CgmBinaryWriter();
  ~CgmBinaryWriter();
  CgmBinaryWriter(const CgmBinaryWriter &) = delete;
  CgmBinaryWriter &operator=(const CgmBinaryWriter &) = delete;

  void begin_metafile(std::string_view name) noexcept;
  void metafile_version(std::int16_t version = 3) noexcept;
  void metafile_description(std::string_view text) noexcept;
  void vdc_type_integer() noexcept;
  void integer_precision(std::int16_t bits = 16) noexcept;
  void colour_precision(std::int16_t bits = 8) noexcept;
  void colour_value_extent() noexcept;
  void metafile_element_list_drawing_plus() noexcept;
  void begin_picture(std::string_view name) noexcept;
  void colour_selection_mode_direct() noexcept;
  void vdc_extent(std::int16_t x0, std::int16_t y0, std::int16_t x1,
                  std::int16_t y1) noexcept;
  void begin_picture_body() noexcept;
  void background_colour(std::uint8_t r, std::uint8_t g,
                         std::uint8_t b) noexcept;
  void line_width(std::int16_t width_vdc) noexcept;
  void line_colour(std::uint8_t r, std::uint8_t g, std::uint8_t b) noexcept;
  void fill_colour(std::uint8_t r, std::uint8_t g, std::uint8_t b) noexcept;
  void interior_style_solid() noexcept;
  void edge_visibility_off() noexcept;
  void character_height(std::int16_t height_vdc) noexcept;
  void text_colour(std::uint8_t r, std::uint8_t g, std::uint8_t b) noexcept;

  // Open polyline (not automatically closed).
  void polyline(std::span<const std::pair<std::int16_t, std::int16_t>>
                    points) noexcept;
  // Filled polygon (closed automatically by CGM POLYGON semantics).
  void polygon(std::span<const std::pair<std::int16_t, std::int16_t>>
                   points) noexcept;
  // Axis-aligned rectangle as closed polyline (stroke).
  void rectangle_polyline(std::int16_t x, std::int16_t y, std::int16_t w,
                          std::int16_t h) noexcept;
  // Axis-aligned filled rectangle (solid POLYGON).
  void rectangle_fill(std::int16_t x, std::int16_t y, std::int16_t w,
                      std::int16_t h) noexcept;
  // Restricted TEXT at (x,y); Latin/ASCII only (non-ASCII dropped).
  // Returns false if the string had no emitable Latin characters.
  bool text(std::int16_t x, std::int16_t y, std::string_view s) noexcept;

  void end_picture() noexcept;
  void end_metafile() noexcept;

  [[nodiscard]] Result<CgmDocument> finish() noexcept;

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

// Maps a PreparedScene into one continuous CGM PICTURE (B1.CGM.1–2).
class WELLLOG_EXPORT_CGM_API CgmSceneExporter {
public:
  [[nodiscard]] static Result<CgmDocument>
  write(const PreparedScene &scene,
        CgmExportDiagnostics *diagnostics = nullptr) noexcept;
};

// Test/diagnostic: count POLYLINE elements in a binary CGM produced by this
// writer (best-effort scan of command headers). Returns 0 on malformed input.
[[nodiscard]] WELLLOG_EXPORT_CGM_API std::size_t
cgm_count_polylines(std::string_view cgm_bytes) noexcept;

// Count POLYGON elements (class 4, id 7).
[[nodiscard]] WELLLOG_EXPORT_CGM_API std::size_t
cgm_count_polygons(std::string_view cgm_bytes) noexcept;

// Test/diagnostic: true if BEGIN METAFILE and END METAFILE headers are found.
[[nodiscard]] WELLLOG_EXPORT_CGM_API bool
cgm_has_metafile_delimiters(std::string_view cgm_bytes) noexcept;

} // namespace welllog
