// Minimal hand-rolled PDF writer (ADR: PDF via hand-rolled writer, #185 spike).
//
// Produces a byte-deterministic, Flate-compressed multi-page PDF with no
// third-party PDF library (only zlib for stream compression). The structure is
// the standard one: a header, an object for each indirect object (Catalog,
// Pages, one Page + one content stream per page), an xref table, and a trailer.
// Determinism is by construction: no CreationDate/ModDate and no /ID are
// emitted, so identical inputs always produce identical output.
//
// The path-operator vocabulary mirrors the SVG emitter; quadratic curves lift
// to cubics because PDF has no quadratic Bezier operator.

#include <welllog/export/pdf.hpp>

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <limits>
#include <memory>
#include <string>
#include <string_view>
#include <vector>
#include <zlib.h>

namespace welllog {
namespace {

// Appends a double as a compact PDF number (general format, no trailing zeros).
// Mirrors the SVG emitter's append_number for consistency.
void append_number(std::string &out, double value) {
  if (value == 0.0) {
    out.push_back('0');
    return;
  }
  std::array<char, 48> buffer{};
  const auto res = std::to_chars(buffer.data(), buffer.data() + buffer.size(),
                                 value, std::chars_format::general,
                                 std::numeric_limits<double>::max_digits10);
  if (res.ec != std::errc{}) {
    out.push_back('0');
    return;
  }
  out.append(buffer.data(), res.ptr);
}

// Appends an integer.
void append_integer(std::string &out, std::int64_t value) {
  std::array<char, 24> buffer{};
  const auto res =
      std::to_chars(buffer.data(), buffer.data() + buffer.size(), value);
  if (res.ec == std::errc{}) {
    out.append(buffer.data(), res.ptr);
  }
}

// Lifts a quadratic Bezier (p0, c, p1) to a cubic using the standard identity:
//   c1 = p0 + 2/3 (c - p0)
//   c2 = c + 1/3 (p1 - c)
// p0 is the current point carried by the caller; we only need c and p1 here
// because the cubic's first control point is derived from p0.
struct CubicFromQuadratic {
  double c1x, c1y, c2x, c2y, x, y;
};
[[nodiscard]] CubicFromQuadratic lift_quadratic(double p0x, double p0y,
                                                double cx, double cy,
                                                double x, double y) noexcept {
  return {.c1x = p0x + (2.0 / 3.0) * (cx - p0x),
          .c1y = p0y + (2.0 / 3.0) * (cy - p0y),
          .c2x = cx + (1.0 / 3.0) * (x - cx),
          .c2y = cy + (1.0 / 3.0) * (y - cy),
          .x = x,
          .y = y};
}

// Compresses a byte range with zlib (FlateDecode). Returns false on zlib error.
[[nodiscard]] bool flate_compress(const std::string &input,
                                  std::string &output) noexcept {
  z_stream stream{};
  // deflateInit2 with windowBits=15 (zlib format — PDF FlateDecode expects the
  // zlib 2-byte header, not raw deflate).
  if (deflateInit2(&stream, Z_DEFAULT_COMPRESSION, Z_DEFLATED, 15, 8,
                   Z_DEFAULT_STRATEGY) != Z_OK) {
    return false;
  }
  output.resize(deflateBound(&stream, input.size()));
  stream.next_in =
      reinterpret_cast<Bytef *>(const_cast<char *>(input.data()));
  stream.avail_in = static_cast<uInt>(input.size());
  stream.next_out = reinterpret_cast<Bytef *>(output.data());
  stream.avail_out = static_cast<uInt>(output.size());
  const auto rc = deflate(&stream, Z_FINISH);
  deflateEnd(&stream);
  if (rc != Z_STREAM_END) {
    return false;
  }
  output.resize(stream.total_out);
  return true;
}

[[nodiscard]] Error pdf_error(ErrorCode code, MessageKey message) {
  return Error{
      .code = code,
      .severity = Severity::error,
      .entity_id = std::nullopt,
      .message = message,
      .arguments = {},
  };
}

} // namespace

struct PdfPathStream::Impl {
  std::string operators;
  // Last move-to point, carried so a following quadratic_to can lift to cubic.
  double current_x{};
  double current_y{};
};

PdfPathStream::PdfPathStream() : impl_(std::make_unique<Impl>()) {}
PdfPathStream::~PdfPathStream() = default;
PdfPathStream::PdfPathStream(const PdfPathStream &other)
    : impl_(std::make_unique<Impl>(*other.impl_)) {}
PdfPathStream &PdfPathStream::operator=(const PdfPathStream &other) {
  if (this != &other) {
    impl_ = std::make_unique<Impl>(*other.impl_);
  }
  return *this;
}
PdfPathStream::PdfPathStream(PdfPathStream &&) noexcept = default;
PdfPathStream &PdfPathStream::operator=(PdfPathStream &&) noexcept = default;

PdfPathStream &PdfPathStream::move_to(double x, double y) noexcept {
  append_number(impl_->operators, x);
  impl_->operators.push_back(' ');
  append_number(impl_->operators, y);
  impl_->operators += " m\n";
  impl_->current_x = x;
  impl_->current_y = y;
  return *this;
}

PdfPathStream &PdfPathStream::line_to(double x, double y) noexcept {
  append_number(impl_->operators, x);
  impl_->operators.push_back(' ');
  append_number(impl_->operators, y);
  impl_->operators += " l\n";
  impl_->current_x = x;
  impl_->current_y = y;
  return *this;
}

PdfPathStream &PdfPathStream::append_outline(std::span<const OutlineCommand> commands,
                                             double scale, double dx,
                                             double dy) noexcept {
  // PDF user space is y-up; OutlineCommand is also y-up (em fractions, glyph
  // local), so no y-flip is needed — only scale + translate. We track the
  // current point so a quadratic_to can be lifted to a cubic.
  for (const auto &command : commands) {
    switch (command.verb) {
    case OutlineVerb::move_to: {
      const auto x = dx + scale * command.coordinates[0];
      const auto y = dy + scale * command.coordinates[1];
      move_to(x, y);
      break;
    }
    case OutlineVerb::line_to: {
      const auto x = dx + scale * command.coordinates[0];
      const auto y = dy + scale * command.coordinates[1];
      line_to(x, y);
      break;
    }
    case OutlineVerb::quadratic_to: {
      const auto cx = dx + scale * command.coordinates[0];
      const auto cy = dy + scale * command.coordinates[1];
      const auto x = dx + scale * command.coordinates[2];
      const auto y = dy + scale * command.coordinates[3];
      const auto lifted = lift_quadratic(impl_->current_x, impl_->current_y,
                                         cx, cy, x, y);
      append_number(impl_->operators, lifted.c1x);
      impl_->operators.push_back(' ');
      append_number(impl_->operators, lifted.c1y);
      impl_->operators.push_back(' ');
      append_number(impl_->operators, lifted.c2x);
      impl_->operators.push_back(' ');
      append_number(impl_->operators, lifted.c2y);
      impl_->operators.push_back(' ');
      append_number(impl_->operators, lifted.x);
      impl_->operators.push_back(' ');
      append_number(impl_->operators, lifted.y);
      impl_->operators += " c\n";
      impl_->current_x = x;
      impl_->current_y = y;
      break;
    }
    case OutlineVerb::cubic_to: {
      for (std::size_t i = 0; i < 6; ++i) {
        append_number(impl_->operators,
                      dx + scale * command.coordinates[i]);
        impl_->operators.push_back(' ');
      }
      impl_->operators += "c\n";
      impl_->current_x = dx + scale * command.coordinates[4];
      impl_->current_y = dy + scale * command.coordinates[5];
      break;
    }
    case OutlineVerb::close:
      close();
      break;
    }
  }
  return *this;
}

PdfPathStream &PdfPathStream::close() noexcept {
  impl_->operators += "h\n";
  return *this;
}

PdfPathStream &PdfPathStream::fill() noexcept {
  impl_->operators += "f\n";
  return *this;
}

PdfPathStream &PdfPathStream::stroke() noexcept {
  impl_->operators += "S\n";
  return *this;
}

PdfPathStream &PdfPathStream::set_fill_color(std::uint8_t r, std::uint8_t g,
                                             std::uint8_t b) noexcept {
  append_number(impl_->operators, r / 255.0);
  impl_->operators.push_back(' ');
  append_number(impl_->operators, g / 255.0);
  impl_->operators.push_back(' ');
  append_number(impl_->operators, b / 255.0);
  impl_->operators += " rg\n";
  return *this;
}

PdfPathStream &PdfPathStream::set_stroke_color(std::uint8_t r, std::uint8_t g,
                                               std::uint8_t b) noexcept {
  append_number(impl_->operators, r / 255.0);
  impl_->operators.push_back(' ');
  append_number(impl_->operators, g / 255.0);
  impl_->operators.push_back(' ');
  append_number(impl_->operators, b / 255.0);
  impl_->operators += " RG\n";
  return *this;
}

PdfPathStream &PdfPathStream::set_line_width(double width) noexcept {
  append_number(impl_->operators, width);
  impl_->operators += " w\n";
  return *this;
}

std::string_view PdfPathStream::operators() const noexcept {
  return impl_->operators;
}

struct PdfDocument::Impl {
  std::string bytes;
};

PdfDocument::PdfDocument() = default;
PdfDocument::~PdfDocument() = default;
PdfDocument::PdfDocument(const PdfDocument &) = default;
PdfDocument &PdfDocument::operator=(const PdfDocument &) = default;
PdfDocument::PdfDocument(PdfDocument &&) noexcept = default;
PdfDocument &PdfDocument::operator=(PdfDocument &&) noexcept = default;
PdfDocument::PdfDocument(std::shared_ptr<const Impl> impl)
    : impl_(std::move(impl)) {}

std::string_view PdfDocument::bytes() const noexcept {
  return impl_ == nullptr ? std::string_view{} : std::string_view{impl_->bytes};
}

// Builds the PDF byte stream. Object layout (1-based object numbers):
//   1: Catalog         2: Pages
//   per page p (0-based):  content stream = 3 + 2*p ;  Page = 3 + 2*p + 1
// The xref table follows, then trailer. All offsets are deterministic given the
// (deterministic) content streams.
Result<PdfDocument> PdfWriter::write(std::span<const PdfPageContent> pages,
                                     std::span<const PdfPageSpec> page_specs) noexcept {
  try {
    if (pages.empty()) {
      return pdf_error(ErrorCode::invalid_buffer,
                       MessageKey::buffer_data_required);
    }
    std::vector<PdfPageSpec> specs(pages.size());
    for (std::size_t i = 0; i < pages.size(); ++i) {
      specs[i] = i < page_specs.size() ? page_specs[i] : PdfPageSpec{};
    }

    std::string out;
    out.reserve(4096);
    out += "%PDF-1.7\n";
    // Binary comment marking the file as binary (4 high-bit bytes) — standard
    // practice; helps tools detect binary content.
    out += "%\xE2\xE3\xCF\xD3\n";

    // Record the byte offset of each indirect object for the xref table.
    std::vector<std::size_t> offsets;

    auto emit_object_header = [&](int object_number) -> int {
      offsets.resize(static_cast<std::size_t>(object_number) + 1);
      offsets[static_cast<std::size_t>(object_number)] = out.size();
      append_integer(out, object_number);
      out += " 0 obj\n";
      return object_number;
    };

    // Object 1: Catalog
    emit_object_header(1);
    out += "<< /Type /Catalog /Pages 2 0 R >>\nendobj\n";

    // Object 2: Pages (kids filled after page objects exist)
    emit_object_header(2);
    out += "<< /Type /Pages /Count ";
    append_integer(out, static_cast<std::int64_t>(pages.size()));
    out += "\n   /Kids [";
    for (std::size_t p = 0; p < pages.size(); ++p) {
      if (p > 0) {
        out.push_back(' ');
      }
      // Page object number = 3 + 2*p + 1
      append_integer(out, static_cast<std::int64_t>(3 + 2 * p + 1));
      out += " 0 R";
    }
    out += "]\n>>\nendobj\n";

    // Per-page: content stream object + page object.
    for (std::size_t p = 0; p < pages.size(); ++p) {
      // Compress the page's content stream.
      std::string compressed;
      const auto &ops = pages[p].stream.operators();
      if (!flate_compress(std::string(ops), compressed)) {
        return pdf_error(ErrorCode::internal_error,
                         MessageKey::internal_error);
      }

      // Content stream object = 3 + 2*p
      emit_object_header(3 + static_cast<int>(2 * p));
      out += "<< /Length ";
      append_integer(out, static_cast<std::int64_t>(compressed.size()));
      out += " /Filter /FlateDecode >>\nstream\n";
      out.append(compressed.data(), compressed.size());
      out += "\nendstream\nendobj\n";

      // Page object = 3 + 2*p + 1
      emit_object_header(3 + static_cast<int>(2 * p) + 1);
      out += "<< /Type /Page /Parent 2 0 R ";
      out += "/MediaBox [0 0 ";
      append_number(out, specs[p].width_points);
      out.push_back(' ');
      append_number(out, specs[p].height_points);
      out += "] ";
      out += "/Contents ";
      append_integer(out, 3 + static_cast<int>(2 * p));
      out += " 0 R ";
      out += "/Resources << >> >>\nendobj\n";
    }

    // xref table.
    const auto xref_offset = out.size();
    const auto object_count = static_cast<std::size_t>(2 + 2 * pages.size() + 1);
    out += "xref\n0 ";
    append_integer(out, static_cast<std::int64_t>(object_count));
    out += "\n0000000000 65535 f \n";
    for (std::size_t obj = 1; obj < object_count; ++obj) {
      std::array<char, 10> offset_buf{};
      auto off = offsets[obj];
      for (int i = 9; i >= 0; --i) {
        offset_buf[static_cast<std::size_t>(i)] =
            static_cast<char>('0' + (off % 10));
        off /= 10;
      }
      out.append(offset_buf.data(), 10);
      out += " 00000 n \n";
    }

    // trailer — no CreationDate/ModDate by construction (determinism).
    out += "trailer\n<< /Size ";
    append_integer(out, static_cast<std::int64_t>(object_count));
    out += " /Root 1 0 R >>\nstartxref\n";
    append_integer(out, static_cast<std::int64_t>(xref_offset));
    out += "\n%%EOF";

    auto doc_impl = std::make_shared<PdfDocument::Impl>();
    doc_impl->bytes = std::move(out);
    return PdfDocument{std::move(doc_impl)};
  } catch (const std::bad_alloc &) {
    return pdf_error(ErrorCode::resource_exhausted,
                     MessageKey::resource_exhausted);
  } catch (...) {
    return pdf_error(ErrorCode::internal_error, MessageKey::internal_error);
  }
}

} // namespace welllog
