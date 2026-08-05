// CGM Version 3 Binary subset writer (B1.CGM.1–2 / ADR 0054).
// Encoding follows ISO/IEC 8632-3 command headers (big-endian).

#include <welllog/export/cgm.hpp>

#include <welllog/core/result.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>
#include <utility>
#include <vector>

namespace welllog {
namespace {

[[nodiscard]] Error cgm_error(ErrorCode code, MessageKey message) {
  return Error{
      .code = code,
      .severity = Severity::error,
      .entity_id = std::nullopt,
      .message = message,
      .arguments = {},
  };
}

// 1 VDC unit = 0.01 mm.
constexpr double k_vdc_per_mm = 100.0;

[[nodiscard]] std::int16_t clamp_i16(double v) noexcept {
  if (!std::isfinite(v)) {
    return 0;
  }
  if (v > static_cast<double>(std::numeric_limits<std::int16_t>::max())) {
    return std::numeric_limits<std::int16_t>::max();
  }
  if (v < static_cast<double>(std::numeric_limits<std::int16_t>::min())) {
    return std::numeric_limits<std::int16_t>::min();
  }
  return static_cast<std::int16_t>(std::lround(v));
}

void append_u16_be(std::string &out, std::uint16_t value) {
  out.push_back(static_cast<char>((value >> 8) & 0xFF));
  out.push_back(static_cast<char>(value & 0xFF));
}

void append_i16_be(std::string &out, std::int16_t value) {
  append_u16_be(out, static_cast<std::uint16_t>(value));
}

// CGM binary string: 1-byte length (0–254) then data, pad to even.
void append_cgm_string(std::string &out, std::string_view s) {
  const auto n = std::min<std::size_t>(s.size(), 254);
  out.push_back(static_cast<char>(n));
  out.append(s.data(), n);
  if (((n + 1) & 1U) != 0U) {
    out.push_back('\0');
  }
}

// Element class (4 bits) + id (7 bits) + param length (5 bits) or long form.
void append_command(std::string &out, std::uint8_t element_class,
                    std::uint8_t element_id, std::string_view params) {
  const auto len = params.size();
  const auto cls = static_cast<std::uint16_t>(element_class & 0x0FU);
  const auto eid = static_cast<std::uint16_t>(element_id & 0x7FU);
  if (len < 31) {
    const auto header = static_cast<std::uint16_t>(
        (cls << 12) | (eid << 5) | static_cast<std::uint16_t>(len));
    append_u16_be(out, header);
    out.append(params.data(), params.size());
  } else {
    const auto header =
        static_cast<std::uint16_t>((cls << 12) | (eid << 5) | 31U);
    append_u16_be(out, header);
    // Partition flag 0 + 15-bit length (we stay under 32767 for B1.CGM.1).
    const auto long_len = static_cast<std::uint16_t>(
        std::min<std::size_t>(len, 0x7FFFU));
    append_u16_be(out, long_len);
    out.append(params.data(), long_len);
  }
  // Pad parameter list to even total after header(s) — CGM requires word
  // alignment of the parameter data following the command header.
  if ((out.size() & 1U) != 0U) {
    out.push_back('\0');
  }
}

void append_command_i16(std::string &out, std::uint8_t element_class,
                        std::uint8_t element_id, std::int16_t value) {
  std::string params;
  append_i16_be(params, value);
  append_command(out, element_class, element_id, params);
}

void append_rgb(std::string &params, std::uint8_t r, std::uint8_t g,
                std::uint8_t b) {
  params.push_back(static_cast<char>(r));
  params.push_back(static_cast<char>(g));
  params.push_back(static_cast<char>(b));
}

std::string filter_latin(std::string_view text) {
  std::string out;
  out.reserve(text.size());
  for (char ch : text) {
    const auto c = static_cast<unsigned char>(ch);
    if (c >= 32 && c < 127) {
      out.push_back(static_cast<char>(c));
    }
  }
  return out;
}

// Parse a single command header at offset; return param start + length, or null.
struct CmdView {
  std::uint8_t cls{};
  std::uint8_t id{};
  std::size_t param_start{};
  std::size_t param_len{};
  std::size_t next_offset{};
};

[[nodiscard]] bool read_command(std::string_view bytes, std::size_t offset,
                                CmdView &out) noexcept {
  if (offset + 2 > bytes.size()) {
    return false;
  }
  const auto b0 = static_cast<std::uint8_t>(bytes[offset]);
  const auto b1 = static_cast<std::uint8_t>(bytes[offset + 1]);
  const auto header = static_cast<std::uint16_t>((b0 << 8) | b1);
  out.cls = static_cast<std::uint8_t>((header >> 12) & 0x0F);
  out.id = static_cast<std::uint8_t>((header >> 5) & 0x7F);
  auto plen = static_cast<std::size_t>(header & 0x1FU);
  std::size_t pstart = offset + 2;
  if (plen == 31) {
    if (offset + 4 > bytes.size()) {
      return false;
    }
    const auto l0 = static_cast<std::uint8_t>(bytes[offset + 2]);
    const auto l1 = static_cast<std::uint8_t>(bytes[offset + 3]);
    plen = static_cast<std::size_t>(((l0 & 0x7FU) << 8) | l1);
    pstart = offset + 4;
  }
  if (pstart + plen > bytes.size()) {
    return false;
  }
  out.param_start = pstart;
  out.param_len = plen;
  auto end = pstart + plen;
  if ((end & 1U) != 0U) {
    ++end; // padding
  }
  out.next_offset = end;
  return true;
}

} // namespace

struct CgmDocument::Impl {
  std::string bytes;
};

CgmDocument::CgmDocument() = default;
CgmDocument::~CgmDocument() = default;
CgmDocument::CgmDocument(const CgmDocument &) = default;
CgmDocument &CgmDocument::operator=(const CgmDocument &) = default;
CgmDocument::CgmDocument(CgmDocument &&) noexcept = default;
CgmDocument &CgmDocument::operator=(CgmDocument &&) noexcept = default;
CgmDocument::CgmDocument(std::shared_ptr<const Impl> impl)
    : impl_(std::move(impl)) {}

std::string_view CgmDocument::bytes() const noexcept {
  return impl_ == nullptr ? std::string_view{} : std::string_view{impl_->bytes};
}

std::string CgmExportDiagnostics::summary() const {
  std::string s;
  if (patterns_flattened_to_solid > 0) {
    s += "patterns_flattened_to_solid=";
    s += std::to_string(patterns_flattened_to_solid);
    s += "; ";
  }
  if (alpha_flattened_to_opaque > 0) {
    s += "alpha_flattened_to_opaque=";
    s += std::to_string(alpha_flattened_to_opaque);
    s += "; ";
  }
  if (non_latin_text_dropped > 0) {
    s += "non_latin_text_dropped=";
    s += std::to_string(non_latin_text_dropped);
    s += "; ";
  }
  s += "intervals=";
  s += std::to_string(intervals_emitted);
  s += " fills=";
  s += std::to_string(fill_regions_emitted);
  for (const auto &n : notes) {
    s += " | ";
    s += n;
  }
  return s;
}

struct CgmBinaryWriter::Impl {
  std::string bytes;
  bool finished{false};
  bool in_metafile{false};
  bool in_picture{false};
};

CgmBinaryWriter::CgmBinaryWriter() : impl_(std::make_unique<Impl>()) {}
CgmBinaryWriter::~CgmBinaryWriter() = default;

void CgmBinaryWriter::begin_metafile(std::string_view name) noexcept {
  std::string params;
  append_cgm_string(params, name);
  append_command(impl_->bytes, 0, 1, params);
  impl_->in_metafile = true;
}

void CgmBinaryWriter::metafile_version(std::int16_t version) noexcept {
  append_command_i16(impl_->bytes, 1, 1, version);
}

void CgmBinaryWriter::metafile_description(std::string_view text) noexcept {
  std::string params;
  append_cgm_string(params, text);
  append_command(impl_->bytes, 1, 2, params);
}

void CgmBinaryWriter::vdc_type_integer() noexcept {
  // enum: 0 = integer
  append_command_i16(impl_->bytes, 1, 3, 0);
}

void CgmBinaryWriter::integer_precision(std::int16_t bits) noexcept {
  append_command_i16(impl_->bytes, 1, 4, bits);
}

void CgmBinaryWriter::colour_precision(std::int16_t bits) noexcept {
  append_command_i16(impl_->bytes, 1, 7, bits);
}

void CgmBinaryWriter::colour_value_extent() noexcept {
  // min RGB (0,0,0) max RGB (255,255,255) — 6 bytes colour components
  std::string params;
  params.append("\0\0\0", 3);
  params.append("\xFF\xFF\xFF", 3);
  append_command(impl_->bytes, 1, 10, params);
}

void CgmBinaryWriter::metafile_element_list_drawing_plus() noexcept {
  // Drawing set: n = 1, then (class,id) pairs is underspecified across tools.
  // Emit "drawing plus" indicator used by many writers: integer -1 == drawing
  // plus control (ISO allows a single index). Keep minimal: one I16 = -1.
  append_command_i16(impl_->bytes, 1, 11, -1);
}

void CgmBinaryWriter::begin_picture(std::string_view name) noexcept {
  std::string params;
  append_cgm_string(params, name);
  append_command(impl_->bytes, 0, 3, params);
  impl_->in_picture = true;
}

void CgmBinaryWriter::colour_selection_mode_direct() noexcept {
  // enum 1 = direct
  append_command_i16(impl_->bytes, 2, 2, 1);
}

void CgmBinaryWriter::vdc_extent(std::int16_t x0, std::int16_t y0,
                                 std::int16_t x1, std::int16_t y1) noexcept {
  std::string params;
  append_i16_be(params, x0);
  append_i16_be(params, y0);
  append_i16_be(params, x1);
  append_i16_be(params, y1);
  append_command(impl_->bytes, 2, 6, params);
}

void CgmBinaryWriter::begin_picture_body() noexcept {
  append_command(impl_->bytes, 0, 4, {});
}

void CgmBinaryWriter::background_colour(std::uint8_t r, std::uint8_t g,
                                        std::uint8_t b) noexcept {
  std::string params;
  append_rgb(params, r, g, b);
  append_command(impl_->bytes, 2, 7, params);
}

void CgmBinaryWriter::line_width(std::int16_t width_vdc) noexcept {
  append_command_i16(impl_->bytes, 5, 3, width_vdc);
}

void CgmBinaryWriter::line_colour(std::uint8_t r, std::uint8_t g,
                                  std::uint8_t b) noexcept {
  std::string params;
  append_rgb(params, r, g, b);
  append_command(impl_->bytes, 5, 4, params);
}

void CgmBinaryWriter::fill_colour(std::uint8_t r, std::uint8_t g,
                                  std::uint8_t b) noexcept {
  std::string params;
  append_rgb(params, r, g, b);
  append_command(impl_->bytes, 5, 23, params);
}

void CgmBinaryWriter::interior_style_solid() noexcept {
  // enum 1 = solid
  append_command_i16(impl_->bytes, 5, 22, 1);
}

void CgmBinaryWriter::edge_visibility_off() noexcept {
  // EDGE VISIBILITY (class 5, id 30): enum 0 = off
  append_command_i16(impl_->bytes, 5, 30, 0);
}

void CgmBinaryWriter::character_height(std::int16_t height_vdc) noexcept {
  append_command_i16(impl_->bytes, 5, 15, height_vdc);
}

void CgmBinaryWriter::text_colour(std::uint8_t r, std::uint8_t g,
                                  std::uint8_t b) noexcept {
  std::string params;
  append_rgb(params, r, g, b);
  append_command(impl_->bytes, 5, 14, params);
}

void CgmBinaryWriter::polyline(
    std::span<const std::pair<std::int16_t, std::int16_t>> points) noexcept {
  if (points.size() < 2) {
    return;
  }
  std::string params;
  params.reserve(points.size() * 4);
  for (const auto &p : points) {
    append_i16_be(params, p.first);
    append_i16_be(params, p.second);
  }
  append_command(impl_->bytes, 4, 1, params);
}

void CgmBinaryWriter::polygon(
    std::span<const std::pair<std::int16_t, std::int16_t>> points) noexcept {
  if (points.size() < 3) {
    return;
  }
  std::string params;
  params.reserve(points.size() * 4);
  for (const auto &p : points) {
    append_i16_be(params, p.first);
    append_i16_be(params, p.second);
  }
  append_command(impl_->bytes, 4, 7, params);
}

void CgmBinaryWriter::rectangle_polyline(std::int16_t x, std::int16_t y,
                                         std::int16_t w,
                                         std::int16_t h) noexcept {
  if (w <= 0 || h <= 0) {
    return;
  }
  const std::array<std::pair<std::int16_t, std::int16_t>, 5> pts{{
      {x, y},
      {static_cast<std::int16_t>(x + w), y},
      {static_cast<std::int16_t>(x + w), static_cast<std::int16_t>(y + h)},
      {x, static_cast<std::int16_t>(y + h)},
      {x, y},
  }};
  polyline(pts);
}

void CgmBinaryWriter::rectangle_fill(std::int16_t x, std::int16_t y,
                                     std::int16_t w, std::int16_t h) noexcept {
  if (w <= 0 || h <= 0) {
    return;
  }
  const std::array<std::pair<std::int16_t, std::int16_t>, 4> pts{{
      {x, y},
      {static_cast<std::int16_t>(x + w), y},
      {static_cast<std::int16_t>(x + w), static_cast<std::int16_t>(y + h)},
      {x, static_cast<std::int16_t>(y + h)},
  }};
  interior_style_solid();
  edge_visibility_off();
  polygon(pts);
}

bool CgmBinaryWriter::text(std::int16_t x, std::int16_t y,
                           std::string_view s) noexcept {
  const auto filtered = filter_latin(s);
  if (filtered.empty()) {
    return false;
  }
  // TEXT: point, final/not-final flag (enum 1 = final), string
  std::string params;
  append_i16_be(params, x);
  append_i16_be(params, y);
  append_i16_be(params, 1); // final
  append_cgm_string(params, filtered);
  append_command(impl_->bytes, 4, 4, params);
  return true;
}

void CgmBinaryWriter::end_picture() noexcept {
  append_command(impl_->bytes, 0, 5, {});
  impl_->in_picture = false;
}

void CgmBinaryWriter::end_metafile() noexcept {
  append_command(impl_->bytes, 0, 2, {});
  impl_->in_metafile = false;
}

Result<CgmDocument> CgmBinaryWriter::finish() noexcept {
  try {
    if (impl_->finished) {
      return cgm_error(ErrorCode::invalid_presentation,
                       MessageKey::presentation_invalid);
    }
    if (impl_->bytes.empty()) {
      return cgm_error(ErrorCode::invalid_buffer, MessageKey::buffer_data_required);
    }
    impl_->finished = true;
    auto doc_impl = std::make_shared<CgmDocument::Impl>();
    doc_impl->bytes = std::move(impl_->bytes);
    return CgmDocument{std::move(doc_impl)};
  } catch (const std::bad_alloc &) {
    return cgm_error(ErrorCode::resource_exhausted,
                     MessageKey::resource_exhausted);
  } catch (...) {
    return cgm_error(ErrorCode::internal_error, MessageKey::internal_error);
  }
}

Result<CgmDocument>
CgmSceneExporter::write(const PreparedScene &scene,
                        CgmExportDiagnostics *diagnostics) noexcept {
  try {
    CgmExportDiagnostics local_diag;
    auto &diag = diagnostics != nullptr ? *diagnostics : local_diag;
    if (diagnostics != nullptr) {
      *diagnostics = CgmExportDiagnostics{};
    }

    const auto width_mm = scene.physical_width().value;
    const auto height_mm = scene.physical_height().value;
    if (!(width_mm > 0.0) || !(height_mm > 0.0)) {
      return cgm_error(ErrorCode::invalid_presentation,
                       MessageKey::presentation_invalid);
    }

    const auto vdc_w = clamp_i16(width_mm * k_vdc_per_mm);
    const auto vdc_h = clamp_i16(height_mm * k_vdc_per_mm);
    if (vdc_w <= 0 || vdc_h <= 0) {
      return cgm_error(ErrorCode::invalid_presentation,
                       MessageKey::presentation_invalid);
    }

    // Scene mm is y-down; CGM VDC y-up.
    const auto to_vdc = [&](double sx, double sy) {
      return std::pair<std::int16_t, std::int16_t>{
          clamp_i16(sx * k_vdc_per_mm),
          clamp_i16((height_mm - sy) * k_vdc_per_mm),
      };
    };

    const auto solid_rgb = [&](RgbaColor c) {
      if (c.alpha < 255) {
        diag.alpha_flattened_to_opaque += 1;
      }
      return c;
    };

    CgmBinaryWriter w;
    w.begin_metafile("WellLogEngine");
    w.metafile_version(3);
    w.metafile_description("WellLog CGM B1.CGM.2 subset (ADR 0054)");
    w.vdc_type_integer();
    w.integer_precision(16);
    w.colour_precision(8);
    w.colour_value_extent();
    w.metafile_element_list_drawing_plus();

    w.begin_picture("page1");
    w.colour_selection_mode_direct();
    w.vdc_extent(0, 0, vdc_w, vdc_h);
    w.background_colour(255, 255, 255);
    w.begin_picture_body();

    // Intervals as solid filled rects (pattern → solid fill_color + note).
    for (const auto &layer : scene.interval_layers()) {
      for (std::uint64_t oi = 0; oi < layer.interval_count; ++oi) {
        const auto &iv =
            scene.intervals()[static_cast<std::size_t>(layer.first_interval +
                                                       oi)];
        if (!iv.pattern_id.is_nil()) {
          diag.patterns_flattened_to_solid += 1;
        }
        const auto col = solid_rgb(iv.fill_color);
        w.fill_colour(col.red, col.green, col.blue);
        const auto tl = to_vdc(iv.rect.left.value, iv.rect.top.value);
        const auto br = to_vdc(iv.rect.left.value + iv.rect.width.value,
                               iv.rect.top.value + iv.rect.height.value);
        const auto x = std::min(tl.first, br.first);
        const auto y = std::min(tl.second, br.second);
        const auto rw =
            static_cast<std::int16_t>(std::abs(br.first - tl.first));
        const auto rh =
            static_cast<std::int16_t>(std::abs(br.second - tl.second));
        w.rectangle_fill(x, y, rw, rh);
        diag.intervals_emitted += 1;
      }
    }

    // Crossover fill regions as solid polygons (pattern flattened).
    const auto fill_vertices = scene.fill_vertices();
    for (const auto &fill_layer : scene.fill_layers()) {
      for (std::uint64_t ri = 0; ri < fill_layer.region_count; ++ri) {
        const auto &region = scene.fill_regions()[static_cast<std::size_t>(
            fill_layer.first_region + ri)];
        if (region.vertex_count < 3) {
          continue;
        }
        if (!region.pattern_id.is_nil()) {
          diag.patterns_flattened_to_solid += 1;
        }
        const auto col = solid_rgb(region.fill_color);
        w.fill_colour(col.red, col.green, col.blue);
        std::vector<std::pair<std::int16_t, std::int16_t>> pts;
        pts.reserve(static_cast<std::size_t>(region.vertex_count));
        for (std::uint64_t vi = 0; vi < region.vertex_count; ++vi) {
          const auto &v = fill_vertices[static_cast<std::size_t>(
              region.first_vertex + vi)];
          pts.push_back(to_vdc(v.position.left.value, v.position.top.value));
        }
        w.interior_style_solid();
        w.edge_visibility_off();
        w.polygon(pts);
        diag.fill_regions_emitted += 1;
      }
    }

    // Track frames.
    for (const auto &track : scene.tracks()) {
      const auto &c = track.clip;
      const auto tl = to_vdc(c.left.value, c.top.value);
      const auto br =
          to_vdc(c.left.value + c.width.value, c.top.value + c.height.value);
      const auto x = std::min(tl.first, br.first);
      const auto y = std::min(tl.second, br.second);
      const auto rw =
          static_cast<std::int16_t>(std::abs(br.first - tl.first));
      const auto rh =
          static_cast<std::int16_t>(std::abs(br.second - tl.second));
      w.line_colour(180, 180, 180);
      w.line_width(10); // 0.1 mm
      w.rectangle_polyline(x, y, rw, rh);
    }

    // Legend / track header mnemonics as restricted TEXT (Latin only).
    w.text_colour(40, 40, 40);
    w.character_height(300); // 3 mm
    for (const auto &entry : scene.track_header_entries()) {
      double sx = 2.0;
      double sy = 5.0;
      for (const auto &track : scene.tracks()) {
        if (track.id == entry.track_id) {
          sx = track.clip.left.value + 1.0;
          sy = track.clip.top.value + 4.0;
          break;
        }
      }
      const auto label_pt = to_vdc(sx, sy);
      if (!w.text(label_pt.first, label_pt.second, entry.curve_name)) {
        if (!entry.curve_name.empty()) {
          diag.non_latin_text_dropped += 1;
        }
      } else if (filter_latin(entry.curve_name).size() <
                 entry.curve_name.size()) {
        // Mixed Latin + non-Latin: partial emit still drops non-Latin bytes.
        diag.non_latin_text_dropped += 1;
      }
    }

    // Curve polylines.
    const auto segments = scene.curve_segments();
    const auto points = scene.curve_points();
    for (const auto &layer : scene.curve_layers()) {
      if (!layer.visible || layer.segment_count == 0) {
        continue;
      }
      w.line_colour(layer.color.red, layer.color.green, layer.color.blue);
      w.line_width(std::max<std::int16_t>(
          5, clamp_i16(layer.line_width.value * k_vdc_per_mm)));
      for (std::uint64_t seg_i = 0; seg_i < layer.segment_count; ++seg_i) {
        const auto &segment =
            segments[static_cast<std::size_t>(layer.first_segment + seg_i)];
        if (segment.point_count < 2) {
          continue;
        }
        std::vector<std::pair<std::int16_t, std::int16_t>> pts;
        pts.reserve(static_cast<std::size_t>(segment.point_count));
        for (std::uint64_t pi = 0; pi < segment.point_count; ++pi) {
          const auto &pt =
              points[static_cast<std::size_t>(segment.first_point + pi)];
          pts.push_back(
              to_vdc(pt.position.left.value, pt.position.top.value));
        }
        w.polyline(pts);
      }
    }

    if (diag.patterns_flattened_to_solid > 0) {
      diag.notes.push_back(
          "pattern fills flattened to solid colour (B1.CGM.2)");
    }
    if (diag.alpha_flattened_to_opaque > 0) {
      diag.notes.push_back(
          "semi-transparent fills forced opaque (CGM limit)");
    }

    w.end_picture();
    w.end_metafile();
    return w.finish();
  } catch (const std::bad_alloc &) {
    return cgm_error(ErrorCode::resource_exhausted,
                     MessageKey::resource_exhausted);
  } catch (...) {
    return cgm_error(ErrorCode::internal_error, MessageKey::internal_error);
  }
}

std::size_t cgm_count_polylines(std::string_view cgm_bytes) noexcept {
  std::size_t count = 0;
  std::size_t offset = 0;
  CmdView cmd{};
  while (read_command(cgm_bytes, offset, cmd)) {
    if (cmd.cls == 4 && cmd.id == 1) {
      ++count;
    }
    if (cmd.next_offset <= offset) {
      break;
    }
    offset = cmd.next_offset;
  }
  return count;
}

std::size_t cgm_count_polygons(std::string_view cgm_bytes) noexcept {
  std::size_t count = 0;
  std::size_t offset = 0;
  CmdView cmd{};
  while (read_command(cgm_bytes, offset, cmd)) {
    if (cmd.cls == 4 && cmd.id == 7) {
      ++count;
    }
    if (cmd.next_offset <= offset) {
      break;
    }
    offset = cmd.next_offset;
  }
  return count;
}

bool cgm_has_metafile_delimiters(std::string_view cgm_bytes) noexcept {
  bool begin = false;
  bool end = false;
  std::size_t offset = 0;
  CmdView cmd{};
  while (read_command(cgm_bytes, offset, cmd)) {
    if (cmd.cls == 0 && cmd.id == 1) {
      begin = true;
    }
    if (cmd.cls == 0 && cmd.id == 2) {
      end = true;
    }
    if (cmd.next_offset <= offset) {
      break;
    }
    offset = cmd.next_offset;
  }
  return begin && end;
}

} // namespace welllog
