#include <welllog/io/manifest.hpp>

#include <cctype>
#include <charconv>
#include <initializer_list>
#include <map>
#include <stdexcept>
#include <utility>
#include <variant>
#include <vector>

namespace welllog {
namespace {

struct JsonNumber {
  std::string text;
};

struct JsonValue;
using JsonObject = std::map<std::string, JsonValue, std::less<>>;
using JsonArray = std::vector<JsonValue>;

struct JsonValue {
  std::variant<std::nullptr_t, bool, JsonNumber, std::string, JsonArray,
               JsonObject>
      value;
};

class ParseFailure final : public std::runtime_error {
public:
  using std::runtime_error::runtime_error;
};

class JsonParser {
public:
  explicit JsonParser(std::string_view input) : input_(input) {}

  [[nodiscard]] JsonValue parse() {
    auto value = parse_value(0);
    skip_space();
    if (position_ != input_.size()) {
      fail("unexpected trailing JSON data");
    }
    return value;
  }

private:
  [[noreturn]] void fail(const char *message) const {
    throw ParseFailure{std::string{message} + " at byte " +
                       std::to_string(position_)};
  }

  void skip_space() {
    while (position_ < input_.size() &&
           std::isspace(static_cast<unsigned char>(input_[position_])) != 0) {
      ++position_;
    }
  }

  [[nodiscard]] bool consume(char expected) {
    skip_space();
    if (position_ < input_.size() && input_[position_] == expected) {
      ++position_;
      return true;
    }
    return false;
  }

  void expect(std::string_view expected) {
    skip_space();
    if (input_.substr(position_, expected.size()) != expected) {
      fail("unexpected JSON token");
    }
    position_ += expected.size();
  }

  [[nodiscard]] JsonValue parse_value(std::size_t depth) {
    if (depth > 64) {
      fail("JSON nesting limit exceeded");
    }
    skip_space();
    if (position_ >= input_.size()) {
      fail("unexpected end of JSON");
    }
    switch (input_[position_]) {
    case '{':
      return JsonValue{parse_object(depth + 1)};
    case '[':
      return JsonValue{parse_array(depth + 1)};
    case '"':
      return JsonValue{parse_string()};
    case 't':
      expect("true");
      return JsonValue{true};
    case 'f':
      expect("false");
      return JsonValue{false};
    case 'n':
      expect("null");
      return JsonValue{nullptr};
    default:
      if (input_[position_] == '-' ||
          std::isdigit(static_cast<unsigned char>(input_[position_])) != 0) {
        return JsonValue{parse_number()};
      }
      fail("invalid JSON value");
    }
  }

  [[nodiscard]] JsonObject parse_object(std::size_t depth) {
    if (!consume('{')) {
      fail("expected object");
    }
    JsonObject result;
    if (consume('}')) {
      return result;
    }
    while (true) {
      skip_space();
      if (position_ >= input_.size() || input_[position_] != '"') {
        fail("expected object key");
      }
      auto key = parse_string();
      if (!consume(':')) {
        fail("expected colon");
      }
      auto [_, inserted] = result.emplace(std::move(key), parse_value(depth));
      if (!inserted) {
        fail("duplicate object key");
      }
      if (consume('}')) {
        return result;
      }
      if (!consume(',')) {
        fail("expected comma");
      }
    }
  }

  [[nodiscard]] JsonArray parse_array(std::size_t depth) {
    if (!consume('[')) {
      fail("expected array");
    }
    JsonArray result;
    if (consume(']')) {
      return result;
    }
    while (true) {
      result.push_back(parse_value(depth));
      if (consume(']')) {
        return result;
      }
      if (!consume(',')) {
        fail("expected comma");
      }
    }
  }

  static void append_utf8(std::string &output, std::uint32_t codepoint) {
    if (codepoint <= 0x7f) {
      output.push_back(static_cast<char>(codepoint));
    } else if (codepoint <= 0x7ff) {
      output.push_back(static_cast<char>(0xc0 | (codepoint >> 6)));
      output.push_back(static_cast<char>(0x80 | (codepoint & 0x3f)));
    } else {
      output.push_back(static_cast<char>(0xe0 | (codepoint >> 12)));
      output.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3f)));
      output.push_back(static_cast<char>(0x80 | (codepoint & 0x3f)));
    }
  }

  [[nodiscard]] std::string parse_string() {
    if (!consume('"')) {
      fail("expected string");
    }
    std::string result;
    while (position_ < input_.size()) {
      const auto character = static_cast<unsigned char>(input_[position_++]);
      if (character == '"') {
        return result;
      }
      if (character < 0x20) {
        fail("unescaped control character");
      }
      if (character != '\\') {
        result.push_back(static_cast<char>(character));
        continue;
      }
      if (position_ >= input_.size()) {
        fail("unterminated escape");
      }
      switch (input_[position_++]) {
      case '"':
        result.push_back('"');
        break;
      case '\\':
        result.push_back('\\');
        break;
      case '/':
        result.push_back('/');
        break;
      case 'b':
        result.push_back('\b');
        break;
      case 'f':
        result.push_back('\f');
        break;
      case 'n':
        result.push_back('\n');
        break;
      case 'r':
        result.push_back('\r');
        break;
      case 't':
        result.push_back('\t');
        break;
      case 'u': {
        if (position_ + 4 > input_.size()) {
          fail("short unicode escape");
        }
        std::uint32_t codepoint{};
        const auto [end, error] =
            std::from_chars(input_.data() + position_,
                            input_.data() + position_ + 4, codepoint, 16);
        if (error != std::errc{} || end != input_.data() + position_ + 4 ||
            (codepoint >= 0xd800 && codepoint <= 0xdfff)) {
          fail("invalid unicode escape");
        }
        position_ += 4;
        append_utf8(result, codepoint);
        break;
      }
      default:
        fail("invalid string escape");
      }
    }
    fail("unterminated string");
  }

  [[nodiscard]] JsonNumber parse_number() {
    skip_space();
    const auto start = position_;
    if (input_[position_] == '-') {
      ++position_;
    }
    if (position_ >= input_.size()) {
      fail("short number");
    }
    if (input_[position_] == '0') {
      ++position_;
    } else {
      if (std::isdigit(static_cast<unsigned char>(input_[position_])) == 0) {
        fail("invalid number");
      }
      while (position_ < input_.size() &&
             std::isdigit(static_cast<unsigned char>(input_[position_])) != 0) {
        ++position_;
      }
    }
    if (position_ < input_.size() && input_[position_] == '.') {
      ++position_;
      const auto fractional_start = position_;
      while (position_ < input_.size() &&
             std::isdigit(static_cast<unsigned char>(input_[position_])) != 0) {
        ++position_;
      }
      if (fractional_start == position_) {
        fail("invalid fraction");
      }
    }
    if (position_ < input_.size() &&
        (input_[position_] == 'e' || input_[position_] == 'E')) {
      ++position_;
      if (position_ < input_.size() &&
          (input_[position_] == '+' || input_[position_] == '-')) {
        ++position_;
      }
      const auto exponent_start = position_;
      while (position_ < input_.size() &&
             std::isdigit(static_cast<unsigned char>(input_[position_])) != 0) {
        ++position_;
      }
      if (exponent_start == position_) {
        fail("invalid exponent");
      }
    }
    return JsonNumber{std::string{input_.substr(start, position_ - start)}};
  }

  std::string_view input_;
  std::size_t position_{};
};

[[nodiscard]] const JsonObject &object(const JsonValue &value) {
  if (const auto *result = std::get_if<JsonObject>(&value.value)) {
    return *result;
  }
  throw ParseFailure{"expected JSON object"};
}

[[nodiscard]] const JsonArray &array(const JsonValue &value) {
  if (const auto *result = std::get_if<JsonArray>(&value.value)) {
    return *result;
  }
  throw ParseFailure{"expected JSON array"};
}

[[nodiscard]] const JsonValue &field(const JsonObject &value,
                                     std::string_view name) {
  const auto found = value.find(name);
  if (found == value.end()) {
    throw ParseFailure{"missing field: " + std::string{name}};
  }
  return found->second;
}

void require_exact_fields(const JsonObject &value,
                          std::initializer_list<std::string_view> names) {
  if (value.size() != names.size()) {
    throw ParseFailure{"JSON object does not match manifest schema"};
  }
  for (const auto name : names) {
    static_cast<void>(field(value, name));
  }
}

[[nodiscard]] const std::string &string(const JsonValue &value) {
  if (const auto *result = std::get_if<std::string>(&value.value)) {
    return *result;
  }
  throw ParseFailure{"expected JSON string"};
}

[[nodiscard]] std::uint64_t unsigned_integer(const JsonValue &value) {
  const auto *number = std::get_if<JsonNumber>(&value.value);
  if (number == nullptr || number->text.empty() ||
      number->text.front() == '-') {
    throw ParseFailure{"expected unsigned integer"};
  }
  std::uint64_t result{};
  const auto [end, error] = std::from_chars(
      number->text.data(), number->text.data() + number->text.size(), result);
  if (error != std::errc{} ||
      end != number->text.data() + number->text.size()) {
    throw ParseFailure{"unsigned integer is out of range"};
  }
  return result;
}

[[nodiscard]] EntityId entity_id(const JsonValue &value) {
  const auto parsed = EntityId::parse(string(value));
  if (!parsed || parsed->is_nil()) {
    throw ParseFailure{"invalid entity identity"};
  }
  return *parsed;
}

void append_escaped(std::string &output, std::string_view text) {
  output.push_back('"');
  constexpr char hex[] = "0123456789abcdef";
  for (const auto raw : text) {
    const auto character = static_cast<unsigned char>(raw);
    switch (character) {
    case '"':
      output += "\\\"";
      break;
    case '\\':
      output += "\\\\";
      break;
    case '\b':
      output += "\\b";
      break;
    case '\f':
      output += "\\f";
      break;
    case '\n':
      output += "\\n";
      break;
    case '\r':
      output += "\\r";
      break;
    case '\t':
      output += "\\t";
      break;
    default:
      if (character < 0x20) {
        output += "\\u00";
        output.push_back(hex[character >> 4]);
        output.push_back(hex[character & 0x0f]);
      } else {
        output.push_back(static_cast<char>(character));
      }
    }
  }
  output.push_back('"');
}

[[nodiscard]] ScalarType parse_scalar(std::string_view name) {
  if (const auto type = parse_scalar_type(name)) {
    return *type;
  }
  throw ParseFailure{"unknown scalar type"};
}

[[nodiscard]] std::string_view domain_name(DepthDomain domain) {
  return depth_domain_name(domain);
}

[[nodiscard]] DepthDomain parse_domain(std::string_view name) {
  const auto parsed = parse_depth_domain(name);
  if (!parsed.has_value()) {
    throw ParseFailure{"unknown depth domain"};
  }
  return *parsed;
}

[[nodiscard]] std::string_view direction_name(AxisDirection direction) {
  return direction == AxisDirection::increasing ? "increasing" : "decreasing";
}

[[nodiscard]] AxisDirection parse_direction(std::string_view name) {
  if (name == "increasing")
    return AxisDirection::increasing;
  if (name == "decreasing")
    return AxisDirection::decreasing;
  throw ParseFailure{"unknown sampling-axis direction"};
}

void write_source(std::string &output, const BufferSourceReference &source) {
  output += "{\"uri\":";
  append_escaped(output, source.uri);
  output += ",\"checksum\":";
  append_escaped(output, source.checksum);
  output += ",\"byteOffset\":" + std::to_string(source.byte_offset) + '}';
}

void write_buffer(std::string &output, const BufferView &buffer) {
  output += "{\"source\":";
  write_source(output, buffer.source());
  output += ",\"length\":" + std::to_string(buffer.length());
  output += ",\"strideBytes\":" + std::to_string(buffer.stride_bytes());
  output += ",\"scalarType\":";
  append_escaped(output, scalar_type_name(buffer.scalar_type()));
  output += ",\"byteCapacity\":" + std::to_string(buffer.byte_capacity()) + '}';
}

void write_nulls(std::string &output, const NullBitmapView &nulls) {
  output += "{\"source\":";
  write_source(output, nulls.source());
  output += ",\"bitLength\":" + std::to_string(nulls.bit_length());
  output += ",\"byteCapacity\":" + std::to_string(nulls.byte_capacity()) + '}';
}

[[nodiscard]] BufferSourceReference parse_source(const JsonValue &value) {
  const auto &source = object(value);
  auto result = BufferSourceReference{
      .uri = string(field(source, "uri")),
      .checksum = string(field(source, "checksum")),
      .byte_offset = unsigned_integer(field(source, "byteOffset")),
  };
  if (result.uri.empty()) {
    throw ParseFailure{"buffer source URI must not be empty"};
  }
  return result;
}

[[nodiscard]] BufferDescriptor parse_buffer(const JsonValue &value) {
  const auto &buffer = object(value);
  auto result = BufferDescriptor{
      .source = parse_source(field(buffer, "source")),
      .length = unsigned_integer(field(buffer, "length")),
      .stride_bytes = unsigned_integer(field(buffer, "strideBytes")),
      .scalar_type = parse_scalar(string(field(buffer, "scalarType"))),
      .byte_capacity = unsigned_integer(field(buffer, "byteCapacity")),
  };
  if (result.length == 0 || result.stride_bytes == 0 ||
      result.byte_capacity == 0) {
    throw ParseFailure{"buffer dimensions must be positive"};
  }
  return result;
}

[[nodiscard]] NullBitmapDescriptor parse_nulls(const JsonValue &value) {
  const auto &nulls = object(value);
  auto result = NullBitmapDescriptor{
      .source = parse_source(field(nulls, "source")),
      .bit_length = unsigned_integer(field(nulls, "bitLength")),
      .byte_capacity = unsigned_integer(field(nulls, "byteCapacity")),
  };
  if (result.bit_length == 0 || result.byte_capacity == 0) {
    throw ParseFailure{"null bitmap dimensions must be positive"};
  }
  return result;
}

void validate_source_schema(const JsonValue &value) {
  require_exact_fields(object(value), {"uri", "checksum", "byteOffset"});
}

void validate_buffer_schema(const JsonValue &value) {
  const auto &buffer = object(value);
  require_exact_fields(buffer, {"source", "length", "strideBytes", "scalarType",
                                "byteCapacity"});
  validate_source_schema(field(buffer, "source"));
}

void validate_manifest_schema(const JsonObject &root) {
  require_exact_fields(root,
                       {"schemaVersion", "requiredSdkVersion", "document"});
  const auto &document = object(field(root, "document"));
  require_exact_fields(document, {"id", "revision", "samplingAxes", "curves"});

  const auto &axes = array(field(document, "samplingAxes"));
  const auto &curves = array(field(document, "curves"));
  if (axes.empty() || curves.empty()) {
    throw ParseFailure{"manifest requires axes and curves"};
  }
  for (const auto &axis_value : axes) {
    const auto &axis = object(axis_value);
    require_exact_fields(axis,
                         {"id", "domain", "unit", "direction", "coordinates"});
    validate_buffer_schema(field(axis, "coordinates"));
  }
  for (const auto &curve_value : curves) {
    const auto &curve = object(curve_value);
    require_exact_fields(curve, {"id", "mnemonic", "displayName", "unit",
                                 "samplingAxisId", "values", "nulls"});
    validate_buffer_schema(field(curve, "values"));
    const auto &nulls = field(curve, "nulls");
    if (!std::holds_alternative<std::nullptr_t>(nulls.value)) {
      const auto &null_object = object(nulls);
      require_exact_fields(null_object,
                           {"source", "bitLength", "byteCapacity"});
      validate_source_schema(field(null_object, "source"));
    }
  }
}

[[nodiscard]] bool source_matches(const BufferSourceReference &actual,
                                  const BufferSourceReference &expected) {
  return actual.uri == expected.uri && actual.checksum == expected.checksum &&
         actual.byte_offset == expected.byte_offset;
}

[[nodiscard]] bool
can_write_manifest_buffer(const BufferView &buffer) noexcept {
  return !buffer.source().uri.empty() && buffer.length() > 0 &&
         buffer.stride_bytes() > 0 && buffer.byte_capacity() > 0;
}

[[nodiscard]] bool
can_write_manifest_nulls(const NullBitmapView &nulls) noexcept {
  return nulls.empty() || (!nulls.source().uri.empty() &&
                           nulls.bit_length() > 0 && nulls.byte_capacity() > 0);
}

[[nodiscard]] bool
can_write_manifest_document(const WellLogDocument &document) noexcept {
  if (document.id().is_nil() || document.revision().value == 0 ||
      document.sampling_axes().empty() || document.curves().empty()) {
    return false;
  }
  for (const auto &axis : document.sampling_axes()) {
    if (!can_write_manifest_buffer(axis.coordinates)) {
      return false;
    }
  }
  for (const auto &curve : document.curves()) {
    if (!can_write_manifest_buffer(curve.values) ||
        !can_write_manifest_nulls(curve.nulls)) {
      return false;
    }
  }
  return true;
}

[[nodiscard]] Error
manifest_error(MessageKey message = MessageKey::manifest_invalid) {
  return Error{
      .code = ErrorCode::invalid_manifest,
      .severity = Severity::error,
      .entity_id = std::nullopt,
      .message = message,
      .arguments = {},
  };
}

[[nodiscard]] Error boundary_error(ErrorCode code, MessageKey message) {
  return Error{
      .code = code,
      .severity = Severity::error,
      .entity_id = std::nullopt,
      .message = message,
      .arguments = {},
  };
}

} // namespace

struct ManifestText::Impl {
  std::string value;
};

ManifestText::ManifestText() = default;
ManifestText::~ManifestText() = default;
ManifestText::ManifestText(const ManifestText &) = default;
ManifestText &ManifestText::operator=(const ManifestText &) = default;
ManifestText::ManifestText(ManifestText &&) noexcept = default;
ManifestText &ManifestText::operator=(ManifestText &&) noexcept = default;

ManifestText::ManifestText(std::string text)
    : impl_(std::make_shared<Impl>(Impl{.value = std::move(text)})) {}

std::string_view ManifestText::text() const noexcept {
  return impl_ == nullptr ? std::string_view{} : std::string_view{impl_->value};
}

Result<ManifestText> ManifestCodec::write(const WellLogDocument &document) {
  try {
    if (!can_write_manifest_document(document)) {
      return manifest_error();
    }

    std::string output;
    output.reserve(1024);
    output += "{\"schemaVersion\":";
    output += std::to_string(manifest_schema_version);
    output += ",\"requiredSdkVersion\":";
    append_escaped(output, manifest_sdk_requirement);
    output += ",\"document\":{\"id\":";
    append_escaped(output, document.id().to_string());
    output += ",\"revision\":" + std::to_string(document.revision().value);
    output += ",\"samplingAxes\":[";
    bool first = true;
    for (const auto &axis : document.sampling_axes()) {
      if (axis.coordinates.source().uri.empty()) {
        return manifest_error();
      }
      if (!first)
        output.push_back(',');
      first = false;
      output += "{\"id\":";
      append_escaped(output, axis.id.to_string());
      output += ",\"domain\":";
      append_escaped(output, domain_name(axis.domain));
      output += ",\"unit\":";
      append_escaped(output, axis.unit);
      output += ",\"direction\":";
      append_escaped(output, direction_name(axis.direction));
      output += ",\"coordinates\":";
      write_buffer(output, axis.coordinates);
      output.push_back('}');
    }
    output += "],\"curves\":[";
    first = true;
    for (const auto &curve : document.curves()) {
      if (curve.values.source().uri.empty() ||
          (!curve.nulls.empty() && curve.nulls.source().uri.empty())) {
        return manifest_error();
      }
      if (!first)
        output.push_back(',');
      first = false;
      output += "{\"id\":";
      append_escaped(output, curve.id.to_string());
      output += ",\"mnemonic\":";
      append_escaped(output, curve.mnemonic);
      output += ",\"displayName\":";
      append_escaped(output, curve.display_name);
      output += ",\"unit\":";
      append_escaped(output, curve.unit);
      output += ",\"samplingAxisId\":";
      append_escaped(output, curve.sampling_axis_id.to_string());
      output += ",\"values\":";
      write_buffer(output, curve.values);
      output += ",\"nulls\":";
      if (curve.nulls.empty()) {
        output += "null";
      } else {
        write_nulls(output, curve.nulls);
      }
      output.push_back('}');
    }
    output += "]}}";
    return ManifestText{std::move(output)};
  } catch (const std::bad_alloc &) {
    return boundary_error(ErrorCode::resource_exhausted,
                          MessageKey::resource_exhausted);
  } catch (...) {
    return boundary_error(ErrorCode::internal_error,
                          MessageKey::internal_error);
  }
}

Result<WellLogDocument>
ManifestCodec::read(std::string_view manifest,
                    const ManifestResolvers &resolvers) {
  try {
    const auto root = JsonParser{manifest}.parse();
    const auto &root_object = object(root);
    validate_manifest_schema(root_object);
    if (unsigned_integer(field(root_object, "schemaVersion")) !=
        manifest_schema_version) {
      return manifest_error(MessageKey::manifest_schema_unsupported);
    }
    if (string(field(root_object, "requiredSdkVersion")) !=
        manifest_sdk_requirement) {
      return manifest_error(MessageKey::manifest_schema_unsupported);
    }
    if (!resolvers.buffer) {
      return manifest_error(MessageKey::manifest_resolver_required);
    }

    const auto &document = object(field(root_object, "document"));
    const auto revision = unsigned_integer(field(document, "revision"));
    if (revision == 0) {
      return manifest_error();
    }
    WellLogDocumentBuilder builder(entity_id(field(document, "id")),
                                   DocumentRevision{revision});

    for (const auto &axis_value : array(field(document, "samplingAxes"))) {
      const auto &axis = object(axis_value);
      const auto descriptor = parse_buffer(field(axis, "coordinates"));
      auto resolved = resolvers.buffer(descriptor);
      if (!resolved) {
        return resolved.error();
      }
      const auto &view = resolved.value();
      if (!source_matches(view.source(), descriptor.source) ||
          view.length() != descriptor.length ||
          view.stride_bytes() != descriptor.stride_bytes ||
          view.scalar_type() != descriptor.scalar_type ||
          view.byte_capacity() < descriptor.byte_capacity) {
        return manifest_error(MessageKey::manifest_buffer_mismatch);
      }
      builder.add_sampling_axis(SamplingAxis{
          .id = entity_id(field(axis, "id")),
          .coordinates = view,
          .domain = parse_domain(string(field(axis, "domain"))),
          .unit = string(field(axis, "unit")),
          .direction = parse_direction(string(field(axis, "direction"))),
      });
    }

    for (const auto &curve_value : array(field(document, "curves"))) {
      const auto &curve = object(curve_value);
      const auto descriptor = parse_buffer(field(curve, "values"));
      auto resolved = resolvers.buffer(descriptor);
      if (!resolved) {
        return resolved.error();
      }
      const auto &view = resolved.value();
      if (!source_matches(view.source(), descriptor.source) ||
          view.length() != descriptor.length ||
          view.stride_bytes() != descriptor.stride_bytes ||
          view.scalar_type() != descriptor.scalar_type ||
          view.byte_capacity() < descriptor.byte_capacity) {
        return manifest_error(MessageKey::manifest_buffer_mismatch);
      }

      NullBitmapView nulls;
      const auto &null_value = field(curve, "nulls");
      if (!std::holds_alternative<std::nullptr_t>(null_value.value)) {
        if (!resolvers.null_bitmap) {
          return manifest_error(MessageKey::manifest_resolver_required);
        }
        const auto null_descriptor = parse_nulls(null_value);
        auto resolved_nulls = resolvers.null_bitmap(null_descriptor);
        if (!resolved_nulls) {
          return resolved_nulls.error();
        }
        nulls = resolved_nulls.value();
        if (!source_matches(nulls.source(), null_descriptor.source) ||
            nulls.bit_length() != null_descriptor.bit_length ||
            nulls.byte_capacity() < null_descriptor.byte_capacity) {
          return manifest_error(MessageKey::manifest_buffer_mismatch);
        }
      }

      builder.add_curve(Curve{
          .id = entity_id(field(curve, "id")),
          .mnemonic = string(field(curve, "mnemonic")),
          .display_name = string(field(curve, "displayName")),
          .unit = string(field(curve, "unit")),
          .sampling_axis_id = entity_id(field(curve, "samplingAxisId")),
          .values = view,
          .nulls = std::move(nulls),
      });
    }
    auto result = builder.build();
    if (result.id().is_nil()) {
      return boundary_error(ErrorCode::resource_exhausted,
                            MessageKey::resource_exhausted);
    }
    return result;
  } catch (const std::bad_alloc &) {
    return boundary_error(ErrorCode::resource_exhausted,
                          MessageKey::resource_exhausted);
  } catch (const std::exception &) {
    return manifest_error();
  } catch (...) {
    return manifest_error();
  }
}

} // namespace welllog
