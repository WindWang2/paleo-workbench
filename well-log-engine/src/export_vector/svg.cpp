#include <welllog/export/svg.hpp>

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <limits>
#include <optional>
#include <string>
#include <type_traits>
#include <utility>

namespace welllog {
namespace {

void append_number(std::string &output, double value) {
  if (value == 0.0) {
    output.push_back('0');
    return;
  }
  std::array<char, 64> buffer{};
  const auto result = std::to_chars(
      buffer.data(), buffer.data() + buffer.size(), value,
      std::chars_format::general, std::numeric_limits<double>::max_digits10);
  if (result.ec != std::errc{}) {
    throw std::bad_alloc{};
  }
  output.append(buffer.data(), result.ptr);
}

template <typename Integer>
  requires std::is_integral_v<Integer>
void append_integer(std::string &output, Integer value) {
  std::array<char, 32> buffer{};
  const auto result =
      std::to_chars(buffer.data(), buffer.data() + buffer.size(), value);
  if (result.ec != std::errc{}) {
    throw std::bad_alloc{};
  }
  output.append(buffer.data(), result.ptr);
}

void append_xml_attribute(std::string &output, std::string_view value) {
  for (const auto character : value) {
    switch (character) {
    case '&':
      output += "&amp;";
      break;
    case '<':
      output += "&lt;";
      break;
    case '>':
      output += "&gt;";
      break;
    case '"':
      output += "&quot;";
      break;
    case '\'':
      output += "&apos;";
      break;
    default:
      output.push_back(character);
      break;
    }
  }
}

void append_color(std::string &output, RgbaColor color) {
  constexpr std::string_view digits = "0123456789abcdef";
  const auto append_byte = [&](std::uint8_t value) {
    output.push_back(digits[value >> 4U]);
    output.push_back(digits[value & 0x0fU]);
  };
  output.push_back('#');
  append_byte(color.red);
  append_byte(color.green);
  append_byte(color.blue);
}

void append_rect(std::string &output, const PhysicalRect &rect) {
  output += "<rect x=\"";
  append_number(output, rect.left.value);
  output += "\" y=\"";
  append_number(output, rect.top.value);
  output += "\" width=\"";
  append_number(output, rect.width.value);
  output += "\" height=\"";
  append_number(output, rect.height.value);
  output += "\"/>";
}

// Clips a tile-local segment to the pattern tile rect (Liang-Barsky).
[[nodiscard]] std::optional<std::pair<PhysicalPoint, PhysicalPoint>>
clip_line_to_tile(PhysicalPoint from, PhysicalPoint to, double width,
                  double height) {
  const auto delta_x = to.left.value - from.left.value;
  const auto delta_y = to.top.value - from.top.value;
  double enter = 0.0;
  double leave = 1.0;
  const auto clip_side = [&](double p, double q) {
    if (p == 0.0) {
      return q >= 0.0;
    }
    const auto ratio = q / p;
    if (p < 0.0) {
      if (ratio > leave) {
        return false;
      }
      enter = std::max(enter, ratio);
    } else {
      if (ratio < enter) {
        return false;
      }
      leave = std::min(leave, ratio);
    }
    return true;
  };
  if (!clip_side(-delta_x, from.left.value) ||
      !clip_side(delta_x, width - from.left.value) ||
      !clip_side(-delta_y, from.top.value) ||
      !clip_side(delta_y, height - from.top.value)) {
    return std::nullopt;
  }
  return std::pair{
      PhysicalPoint{
          .left = Millimetres{from.left.value + enter * delta_x},
          .top = Millimetres{from.top.value + enter * delta_y},
      },
      PhysicalPoint{
          .left = Millimetres{from.left.value + leave * delta_x},
          .top = Millimetres{from.top.value + leave * delta_y},
      },
  };
}

void append_tile_line(std::string &output, PhysicalPoint from, PhysicalPoint to,
                      const PatternDefinition &pattern) {
  const auto clipped =
      clip_line_to_tile(from, to, pattern.tile_width.value,
                        pattern.tile_height.value);
  if (!clipped.has_value()) {
    return;
  }
  output += "<line x1=\"";
  append_number(output, clipped->first.left.value);
  output += "\" y1=\"";
  append_number(output, clipped->first.top.value);
  output += "\" x2=\"";
  append_number(output, clipped->second.left.value);
  output += "\" y2=\"";
  append_number(output, clipped->second.top.value);
  output += "\" stroke=\"";
  append_color(output, pattern.foreground);
  output += "\" stroke-opacity=\"";
  append_number(output,
                static_cast<double>(pattern.foreground.alpha) / 255.0);
  output += "\" stroke-width=\"";
  append_number(output, pattern.stroke_width.value);
  output += "\"/>";
}

// Emits the constrained vector tile exactly once, anchored to scene
// coordinates via patternUnits="userSpaceOnUse" so adjacent intervals and
// scrolling share phase (ADR 0020).
void append_pattern_definition(std::string &output,
                               const PatternDefinition &pattern) {
  output += "<pattern id=\"pat-";
  output += pattern.id.to_string();
  output += "\" patternUnits=\"userSpaceOnUse\" x=\"";
  append_number(output, pattern.scene_anchor.left.value);
  output += "\" y=\"";
  append_number(output, pattern.scene_anchor.top.value);
  output += "\" width=\"";
  append_number(output, pattern.tile_width.value);
  output += "\" height=\"";
  append_number(output, pattern.tile_height.value);
  output += "\" patternTransform=\"rotate(";
  append_number(output, pattern.rotation_degrees);
  output += ")\">";
  if (pattern.background.alpha > 0) {
    output += "<rect x=\"0\" y=\"0\" width=\"";
    append_number(output, pattern.tile_width.value);
    output += "\" height=\"";
    append_number(output, pattern.tile_height.value);
    output += "\" fill=\"";
    append_color(output, pattern.background);
    output += "\" fill-opacity=\"";
    append_number(output,
                  static_cast<double>(pattern.background.alpha) / 255.0);
    output += "\"/>";
  }
  for (const auto &primitive : pattern.primitives) {
    if (const auto *line = std::get_if<PatternLine>(&primitive)) {
      append_tile_line(output, line->from, line->to, pattern);
    } else if (const auto *polyline =
                   std::get_if<PatternPolyline>(&primitive)) {
      for (std::size_t index = 0; index + 1 < polyline->points.size();
           ++index) {
        append_tile_line(output, polyline->points[index],
                         polyline->points[index + 1], pattern);
      }
      if (polyline->closed && polyline->points.size() > 2) {
        append_tile_line(output, polyline->points.back(),
                         polyline->points.front(), pattern);
      }
    } else {
      const auto &circle = std::get<PatternCircle>(primitive);
      output += "<circle cx=\"";
      append_number(output, circle.center.left.value);
      output += "\" cy=\"";
      append_number(output, circle.center.top.value);
      output += "\" r=\"";
      append_number(output, circle.radius.value);
      if (circle.filled) {
        output += "\" fill=\"";
        append_color(output, pattern.foreground);
        output += "\" fill-opacity=\"";
        append_number(output,
                      static_cast<double>(pattern.foreground.alpha) / 255.0);
      } else {
        output += "\" fill=\"none\" stroke=\"";
        append_color(output, pattern.foreground);
        output += "\" stroke-opacity=\"";
        append_number(output,
                      static_cast<double>(pattern.foreground.alpha) / 255.0);
        output += "\" stroke-width=\"";
        append_number(output, pattern.stroke_width.value);
      }
      output += "\"/>";
    }
  }
  output += "</pattern>";
}

// Serializes a glyph outline in em fractions as an SVG path. Scaling,
// y-flipping, rotation and placement happen at the <use> site so every
// run shares one definition.
void append_outline_path_data(std::string &output,
                              std::span<const OutlineCommand> commands) {
  bool first = true;
  for (const auto &command : commands) {
    if (!first) {
      output.push_back(' ');
    }
    first = false;
    switch (command.verb) {
    case OutlineVerb::move_to:
      output += "M ";
      append_number(output, command.coordinates[0]);
      output.push_back(' ');
      append_number(output, command.coordinates[1]);
      break;
    case OutlineVerb::line_to:
      output += "L ";
      append_number(output, command.coordinates[0]);
      output.push_back(' ');
      append_number(output, command.coordinates[1]);
      break;
    case OutlineVerb::quadratic_to:
      output += "Q ";
      append_number(output, command.coordinates[0]);
      output.push_back(' ');
      append_number(output, command.coordinates[1]);
      output.push_back(' ');
      append_number(output, command.coordinates[2]);
      output.push_back(' ');
      append_number(output, command.coordinates[3]);
      break;
    case OutlineVerb::cubic_to:
      output += "C ";
      for (const auto coordinate : command.coordinates) {
        append_number(output, coordinate);
        output.push_back(' ');
      }
      output.pop_back();
      break;
    case OutlineVerb::close:
      output.push_back('Z');
      break;
    }
  }
}

void append_symbol(std::string &output, const PreparedSymbol &symbol,
                   const PreparedSymbolLayer &layer) {
  const auto half = layer.symbol_size.value / 2.0;
  const auto center_x = symbol.center.left.value;
  const auto center_y = symbol.center.top.value;
  output += "<path id=\"symbol-";
  output += symbol.symbol_id.to_string();
  output += "\" data-layer-id=\"";
  output += layer.id.to_string();
  switch (symbol.kind) {
  case SymbolKind::circle:
    output += "\" fill=\"";
    append_color(output, layer.color);
    output += "\" d=\"M ";
    append_number(output, center_x + half);
    output.push_back(' ');
    append_number(output, center_y);
    output += " A ";
    append_number(output, half);
    output.push_back(' ');
    append_number(output, half);
    output += " 0 1 0 ";
    append_number(output, center_x - half);
    output.push_back(' ');
    append_number(output, center_y);
    output += " A ";
    append_number(output, half);
    output.push_back(' ');
    append_number(output, half);
    output += " 0 1 0 ";
    append_number(output, center_x + half);
    output.push_back(' ');
    append_number(output, center_y);
    output += " Z\"/>";
    return;
  case SymbolKind::cross:
    output += "\" fill=\"none\" stroke=\"";
    append_color(output, layer.color);
    output += "\" stroke-width=\"";
    append_number(output, layer.symbol_size.value / 6.0);
    output += "\" d=\"M ";
    append_number(output, center_x - half);
    output.push_back(' ');
    append_number(output, center_y - half);
    output += " L ";
    append_number(output, center_x + half);
    output.push_back(' ');
    append_number(output, center_y + half);
    output += " M ";
    append_number(output, center_x + half);
    output.push_back(' ');
    append_number(output, center_y - half);
    output += " L ";
    append_number(output, center_x - half);
    output.push_back(' ');
    append_number(output, center_y + half);
    output += "\"/>";
    return;
  case SymbolKind::square:
  case SymbolKind::triangle_up:
  case SymbolKind::diamond:
    break;
  }
  output += "\" fill=\"";
  append_color(output, layer.color);
  output += "\" d=\"";
  if (symbol.kind == SymbolKind::square) {
    output += "M ";
    append_number(output, center_x - half);
    output.push_back(' ');
    append_number(output, center_y - half);
    output += " L ";
    append_number(output, center_x + half);
    output.push_back(' ');
    append_number(output, center_y - half);
    output += " L ";
    append_number(output, center_x + half);
    output.push_back(' ');
    append_number(output, center_y + half);
    output += " L ";
    append_number(output, center_x - half);
    output.push_back(' ');
    append_number(output, center_y + half);
    output += " Z\"/>";
  } else if (symbol.kind == SymbolKind::triangle_up) {
    output += "M ";
    append_number(output, center_x);
    output.push_back(' ');
    append_number(output, center_y - half);
    output += " L ";
    append_number(output, center_x + half);
    output.push_back(' ');
    append_number(output, center_y + half);
    output += " L ";
    append_number(output, center_x - half);
    output.push_back(' ');
    append_number(output, center_y + half);
    output += " Z\"/>";
  } else {
    output += "M ";
    append_number(output, center_x);
    output.push_back(' ');
    append_number(output, center_y - half);
    output += " L ";
    append_number(output, center_x + half);
    output.push_back(' ');
    append_number(output, center_y);
    output += " L ";
    append_number(output, center_x);
    output.push_back(' ');
    append_number(output, center_y + half);
    output += " L ";
    append_number(output, center_x - half);
    output.push_back(' ');
    append_number(output, center_y);
    output += " Z\"/>";
  }
}

void append_path_data(std::string &output, const PreparedScene &scene,
                      const PreparedCurveLayer &layer) {
  const auto segments = scene.curve_segments();
  const auto points = scene.curve_points();
  bool first_segment = true;
  for (std::uint64_t segment_offset = 0; segment_offset < layer.segment_count;
       ++segment_offset) {
    const auto &segment = segments[static_cast<std::size_t>(
        layer.first_segment + segment_offset)];
    if (!first_segment && segment.point_count > 0) {
      output.push_back(' ');
    }
    for (std::uint64_t point_offset = 0; point_offset < segment.point_count;
         ++point_offset) {
      const auto &point =
          points[static_cast<std::size_t>(segment.first_point + point_offset)];
      output += point_offset == 0 ? "M " : " L ";
      append_number(output, point.position.left.value);
      output.push_back(' ');
      append_number(output, point.position.top.value);
    }
    first_segment = false;
  }
}

[[nodiscard]] Error svg_error(ErrorCode code, MessageKey message) {
  return Error{
      .code = code,
      .severity = Severity::error,
      .entity_id = std::nullopt,
      .message = message,
      .arguments = {},
  };
}

} // namespace

struct SvgDocument::Impl {
  std::string text;
};

SvgDocument::SvgDocument() = default;
SvgDocument::~SvgDocument() = default;
SvgDocument::SvgDocument(const SvgDocument &) = default;
SvgDocument &SvgDocument::operator=(const SvgDocument &) = default;
SvgDocument::SvgDocument(SvgDocument &&) noexcept = default;
SvgDocument &SvgDocument::operator=(SvgDocument &&) noexcept = default;

SvgDocument::SvgDocument(std::string text)
    : impl_(std::make_shared<Impl>(Impl{.text = std::move(text)})) {}

std::string_view SvgDocument::text() const noexcept {
  return impl_ == nullptr ? std::string_view{} : std::string_view{impl_->text};
}

Result<SvgDocument> SvgExporter::write(const PreparedScene &scene) noexcept {
  try {
    if (scene.document_id().is_nil() || scene.document_revision().value == 0 ||
        !std::isfinite(scene.physical_width().value) ||
        scene.physical_width().value <= 0.0 ||
        !std::isfinite(scene.physical_height().value) ||
        scene.physical_height().value <= 0.0 || scene.tracks().empty()) {
      return svg_error(ErrorCode::invalid_presentation,
                       MessageKey::presentation_invalid);
    }

    std::string output;
    output.reserve(1024 + scene.curve_points().size() * 32);
    output += "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"";
    append_number(output, scene.physical_width().value);
    output += "mm\" height=\"";
    append_number(output, scene.physical_height().value);
    output += "mm\" viewBox=\"0 0 ";
    append_number(output, scene.physical_width().value);
    output.push_back(' ');
    append_number(output, scene.physical_height().value);
    output += "\" data-document-id=\"";
    output += scene.document_id().to_string();
    output += "\" data-document-revision=\"";
    append_integer(output, scene.document_revision().value);
    output += "\" data-font-asset=\"";
    append_xml_attribute(output, scene.font_asset_fingerprint());
    output += "\"><defs>";

    for (const auto &track : scene.tracks()) {
      output += "<clipPath id=\"clip-";
      output += track.id.to_string();
      output += "\">";
      append_rect(output, track.clip);
      output += "</clipPath>";
    }
    for (const auto &pattern : scene.patterns()) {
      append_pattern_definition(output, pattern);
    }
    const auto outline_commands = scene.outline_commands();
    for (const auto &outline : scene.glyph_outlines()) {
      output += "<path id=\"g";
      append_integer(output, outline.font_index);
      output.push_back('-');
      append_integer(output, outline.glyph_id);
      output += "\" d=\"";
      append_outline_path_data(
          output,
          outline_commands.subspan(
              static_cast<std::size_t>(outline.first_command),
              static_cast<std::size_t>(outline.command_count)));
      output += "\"/>";
    }
    output += "</defs>";

    for (const auto &track : scene.tracks()) {
      output += "<g id=\"track-";
      output += track.id.to_string();
      output += "\" clip-path=\"url(#clip-";
      output += track.id.to_string();
      output += ")\" data-z-order=\"";
      append_integer(output, track.z_order);
      output += "\">";
      for (const auto &layer : scene.interval_layers()) {
        if (layer.track_id != track.id) {
          continue;
        }
        for (std::uint64_t offset = 0; offset < layer.interval_count;
             ++offset) {
          const auto &interval = scene.intervals()[static_cast<std::size_t>(
              layer.first_interval + offset)];
          output += "<rect id=\"interval-";
          output += interval.interval_id.to_string();
          output += "\" data-layer-id=\"";
          output += layer.id.to_string();
          output += "\" data-top-depth=\"";
          append_number(output, interval.top_reference_depth);
          output += "\" data-bottom-depth=\"";
          append_number(output, interval.bottom_reference_depth);
          output += "\" x=\"";
          append_number(output, interval.rect.left.value);
          output += "\" y=\"";
          append_number(output, interval.rect.top.value);
          output += "\" width=\"";
          append_number(output, interval.rect.width.value);
          output += "\" height=\"";
          append_number(output, interval.rect.height.value);
          if (interval.pattern_id.is_nil()) {
            output += "\" fill=\"";
            append_color(output, interval.fill_color);
            output += "\" fill-opacity=\"";
            append_number(
                output,
                static_cast<double>(interval.fill_color.alpha) / 255.0);
          } else {
            output += "\" fill=\"url(#pat-";
            output += interval.pattern_id.to_string();
            output += ")";
          }
          output += "\"/>";
        }
      }
      for (const auto &layer : scene.marker_layers()) {
        if (layer.track_id != track.id) {
          continue;
        }
        const auto right = track.clip.left.value + track.clip.width.value;
        for (std::uint64_t offset = 0; offset < layer.marker_count;
             ++offset) {
          const auto &marker = scene.markers()[static_cast<std::size_t>(
              layer.first_marker + offset)];
          output += "<line id=\"marker-";
          output += marker.marker_id.to_string();
          output += "\" data-layer-id=\"";
          output += layer.id.to_string();
          output += "\" data-reference-depth=\"";
          append_number(output, marker.reference_depth);
          output += "\" x1=\"";
          append_number(output, track.clip.left.value);
          output += "\" y1=\"";
          append_number(output, marker.display_top.value);
          output += "\" x2=\"";
          append_number(output, right);
          output += "\" y2=\"";
          append_number(output, marker.display_top.value);
          output += "\" stroke=\"";
          append_color(output, layer.line_color);
          output += "\" stroke-opacity=\"";
          append_number(output,
                        static_cast<double>(layer.line_color.alpha) / 255.0);
          output += "\" stroke-width=\"";
          append_number(output, layer.line_width.value);
          output += "\"/>";
        }
      }
      for (const auto &layer : scene.symbol_layers()) {
        if (layer.track_id != track.id) {
          continue;
        }
        for (std::uint64_t offset = 0; offset < layer.symbol_count;
             ++offset) {
          const auto &symbol = scene.symbols()[static_cast<std::size_t>(
              layer.first_symbol + offset)];
          append_symbol(output, symbol, layer);
        }
      }
      for (const auto &layer : scene.curve_layers()) {
        if (layer.track_id != track.id) {
          continue;
        }
        output += "<path id=\"layer-";
        output += layer.id.to_string();
        output += "\" data-curve-id=\"";
        output += layer.curve_id.to_string();
        output += "\" data-scale-id=\"";
        output += layer.scale_id.to_string();
        output += "\" data-z-order=\"";
        append_integer(output, layer.z_order);
        output += "\" fill=\"none\" stroke=\"";
        append_color(output, layer.color);
        output += "\" stroke-opacity=\"";
        append_number(output, static_cast<double>(layer.color.alpha) / 255.0);
        output += "\" stroke-width=\"";
        append_number(output, layer.line_width.value);
        output += "\" d=\"";
        append_path_data(output, scene, layer);
        output += "\"/>";
      }
      const auto glyphs = scene.glyphs();
      for (const auto &run : scene.text_runs()) {
        const auto run_track = scene.track_id_for_layer(run.layer_id);
        if (!run_track.has_value() || *run_track != track.id) {
          continue;
        }
        output += "<g id=\"run-";
        output += run.source_entity_id.to_string();
        output += "\" data-layer-id=\"";
        output += run.layer_id.to_string();
        output += "\" data-orientation=\"";
        append_integer(output,
                       static_cast<std::uint8_t>(run.orientation));
        output += "\" fill=\"";
        append_color(output, run.color);
        output += "\" fill-opacity=\"";
        append_number(output,
                      static_cast<double>(run.color.alpha) / 255.0);
        output += "\">";
        for (std::uint64_t offset = 0; offset < run.glyph_count; ++offset) {
          const auto &glyph = glyphs[static_cast<std::size_t>(
              run.first_glyph + offset)];
          output += "<use href=\"#g";
          append_integer(output, glyph.font_index);
          output.push_back('-');
          append_integer(output, glyph.glyph_id);
          output += "\" transform=\"translate(";
          append_number(output, glyph.origin.left.value);
          output.push_back(' ');
          append_number(output, glyph.origin.top.value);
          output += ") rotate(";
          append_number(output, glyph.rotation_degrees);
          output += ") scale(";
          append_number(output, run.font_size.value);
          output += " -";
          append_number(output, run.font_size.value);
          output += ")\"/>";
        }
        output += "</g>";
      }
      output += "</g>";
    }
    output += "</svg>";
    return SvgDocument{std::move(output)};
  } catch (const std::bad_alloc &) {
    return svg_error(ErrorCode::resource_exhausted,
                     MessageKey::resource_exhausted);
  } catch (...) {
    return svg_error(ErrorCode::internal_error, MessageKey::internal_error);
  }
}

} // namespace welllog
