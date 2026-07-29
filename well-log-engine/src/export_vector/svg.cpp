#include <welllog/export/svg.hpp>

#include <array>
#include <charconv>
#include <cmath>
#include <limits>
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
    output += "</defs>";

    for (const auto &track : scene.tracks()) {
      output += "<g id=\"track-";
      output += track.id.to_string();
      output += "\" clip-path=\"url(#clip-";
      output += track.id.to_string();
      output += ")\" data-z-order=\"";
      append_integer(output, track.z_order);
      output += "\">";
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
