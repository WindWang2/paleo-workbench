#include <welllog/io/las.hpp>

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include <new>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace welllog {
namespace {

enum class LasSection : std::uint8_t {
  none,
  version,
  well,
  curve,
  ascii,
};

struct CurveDefinition {
  std::string mnemonic;
  std::string unit;
  std::string display_name;
};

struct Token {
  std::string_view text;
  std::uint64_t line{};
};

struct ParsedNumber {
  double value{};
  bool finite{};
};

[[nodiscard]] Error invalid_las() {
  return Error{.code = ErrorCode::invalid_document,
               .severity = Severity::error,
               .entity_id = std::nullopt,
               .message = MessageKey::document_structure_invalid,
               .arguments = {}};
}

[[nodiscard]] Error exhausted() {
  return Error{.code = ErrorCode::resource_exhausted,
               .severity = Severity::error,
               .entity_id = std::nullopt,
               .message = MessageKey::resource_exhausted,
               .arguments = {}};
}

[[nodiscard]] Error internal_failure() {
  return Error{.code = ErrorCode::internal_error,
               .severity = Severity::error,
               .entity_id = std::nullopt,
               .message = MessageKey::internal_error,
               .arguments = {}};
}

[[nodiscard]] std::string_view trim(std::string_view value) noexcept {
  const auto first = value.find_first_not_of(" \t\r");
  if (first == std::string_view::npos) {
    return {};
  }
  const auto last = value.find_last_not_of(" \t\r");
  return value.substr(first, last - first + 1);
}

[[nodiscard]] std::string uppercase(std::string_view value) {
  std::string result;
  result.reserve(value.size());
  for (const auto character : value) {
    if (character >= 'a' && character <= 'z') {
      result.push_back(static_cast<char>(character - 'a' + 'A'));
    } else {
      result.push_back(character);
    }
  }
  return result;
}

[[nodiscard]] std::string_view first_token(std::string_view value) noexcept {
  value = trim(value);
  const auto end = value.find_first_of(" \t");
  return end == std::string_view::npos ? value : value.substr(0, end);
}

[[nodiscard]] std::vector<Token>
tokens_in(std::string_view line, std::uint64_t line_number) {
  std::vector<Token> tokens;
  while (!(line = trim(line)).empty()) {
    const auto end = line.find_first_of(" \t");
    const auto token = end == std::string_view::npos ? line : line.substr(0, end);
    tokens.push_back(Token{.text = token, .line = line_number});
    if (end == std::string_view::npos) {
      break;
    }
    line.remove_prefix(end + 1);
  }
  return tokens;
}

[[nodiscard]] std::optional<ParsedNumber>
parse_number(std::string_view text) {
  const auto normalized = uppercase(text);
  if (normalized == "NAN" || normalized == "+NAN" || normalized == "-NAN") {
    return ParsedNumber{.value = std::numeric_limits<double>::quiet_NaN(),
                        .finite = false};
  }
  if (normalized == "INF" || normalized == "+INF" || normalized == "-INF" ||
      normalized == "INFINITY" || normalized == "+INFINITY" ||
      normalized == "-INFINITY") {
    return ParsedNumber{.value = normalized.front() == '-'
                                      ? -std::numeric_limits<double>::infinity()
                                      : std::numeric_limits<double>::infinity(),
                        .finite = false};
  }

  double value{};
  const auto [end, error] =
      std::from_chars(text.data(), text.data() + text.size(), value);
  if (error != std::errc{} || end != text.data() + text.size()) {
    return std::nullopt;
  }
  return ParsedNumber{.value = value, .finite = std::isfinite(value)};
}

[[nodiscard]] EntityId stable_id(std::string_view identity,
                                  std::string_view kind,
                                  std::uint64_t ordinal) {
  constexpr std::uint64_t offset_a = 1469598103934665603ULL;
  constexpr std::uint64_t offset_b = 1099511628211ULL;
  constexpr std::uint64_t prime = 1099511628211ULL;
  auto first = offset_a;
  auto second = offset_b;
  const auto append = [&](std::string_view value) {
    for (const auto byte : value) {
      first ^= static_cast<std::uint8_t>(byte);
      first *= prime;
      second ^= static_cast<std::uint8_t>(byte);
      second *= prime;
    }
  };
  append(identity);
  append("/");
  append(kind);
  append("/");
  for (std::uint32_t index = 0; index < 8; ++index) {
    const auto byte = static_cast<std::uint8_t>((ordinal >> (index * 8U)) & 0xffU);
    first ^= byte;
    first *= prime;
    second ^= byte;
    second *= prime;
  }

  std::array<std::uint8_t, 16> bytes{};
  for (std::uint32_t index = 0; index < 8; ++index) {
    bytes[index] = static_cast<std::uint8_t>((first >> (index * 8U)) & 0xffU);
    bytes[index + 8] =
        static_cast<std::uint8_t>((second >> (index * 8U)) & 0xffU);
  }
  bytes[6] = static_cast<std::uint8_t>((bytes[6] & 0x0fU) | 0x40U);
  bytes[8] = static_cast<std::uint8_t>((bytes[8] & 0x3fU) | 0x80U);

  constexpr std::array<char, 16> digits{
      '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'b', 'c', 'd', 'e', 'f'};
  std::array<char, 36> text{};
  std::size_t output{};
  for (std::size_t index = 0; index < bytes.size(); ++index) {
    if (index == 4 || index == 6 || index == 8 || index == 10) {
      text[output++] = '-';
    }
    text[output++] = digits[bytes[index] >> 4U];
    text[output++] = digits[bytes[index] & 0x0fU];
  }
  return *EntityId::parse(std::string_view{text.data(), text.size()});
}

[[nodiscard]] std::string source_identity(const BufferSourceReference &source,
                                          std::string_view text) {
  if (!source.uri.empty() || !source.checksum.empty()) {
    return source.uri + "#" + source.checksum;
  }
  return std::string{text};
}

[[nodiscard]] std::optional<CurveDefinition>
parse_curve_definition(std::string_view line) {
  const auto colon = line.find(':');
  const auto declaration = trim(line.substr(0, colon));
  const auto dot = declaration.find('.');
  if (dot == std::string_view::npos) {
    return std::nullopt;
  }
  const auto mnemonic = trim(declaration.substr(0, dot));
  if (mnemonic.empty()) {
    return std::nullopt;
  }
  const auto unit = first_token(declaration.substr(dot + 1));
  const auto description =
      colon == std::string_view::npos ? std::string_view{} : trim(line.substr(colon + 1));
  return CurveDefinition{.mnemonic = std::string{mnemonic},
                         .unit = std::string{unit},
                         .display_name = description.empty() ? std::string{mnemonic}
                                                             : std::string{description}};
}

[[nodiscard]] std::optional<AxisDirection>
axis_direction(const std::vector<double> &depths) noexcept {
  std::optional<AxisDirection> direction;
  for (std::size_t index = 1; index < depths.size(); ++index) {
    if (depths[index] == depths[index - 1]) {
      continue;
    }
    const auto next = depths[index] > depths[index - 1]
                          ? AxisDirection::increasing
                          : AxisDirection::decreasing;
    if (direction.has_value() && *direction != next) {
      return std::nullopt;
    }
    direction = next;
  }
  return direction.value_or(AxisDirection::increasing);
}

[[nodiscard]] BufferView owned_values(const std::shared_ptr<const std::vector<double>> &values,
                                      BufferSourceReference source) {
  return BufferView::from_raw(
      values->data(), static_cast<std::uint64_t>(values->size()), sizeof(double),
      ScalarType::float64,
      static_cast<std::uint64_t>(values->size() * sizeof(double)), SharedOwner{values},
      std::move(source), BufferAccessMode::converted_copy);
}

[[nodiscard]] NullBitmapView
owned_nulls(const std::vector<std::uint8_t> &null_flags,
            BufferSourceReference source) {
  if (std::none_of(null_flags.begin(), null_flags.end(),
                   [](std::uint8_t flag) { return flag != 0; })) {
    return {};
  }
  auto bytes = std::make_shared<std::vector<std::uint8_t>>(
      (null_flags.size() + 7U) / 8U, std::uint8_t{0});
  for (std::size_t index = 0; index < null_flags.size(); ++index) {
    if (null_flags[index] != 0) {
      (*bytes)[index / 8U] |= static_cast<std::uint8_t>(1U << (index % 8U));
    }
  }
  const auto owner = std::shared_ptr<const std::vector<std::uint8_t>>{std::move(bytes)};
  return NullBitmapView::from_raw(
      owner->data(), static_cast<std::uint64_t>(null_flags.size()),
      static_cast<std::uint64_t>(owner->size()), SharedOwner{owner}, std::move(source));
}

} // namespace

Result<LasImport> LasSourceAdapter::parse(std::string_view text,
                                          BufferSourceReference source) {
  try {
    const auto original_text = text;
    LasSection section{LasSection::none};
    std::optional<double> version;
    bool wrapped{};
    std::optional<double> null_sentinel;
    std::vector<CurveDefinition> definitions;
    std::vector<std::vector<Token>> unwrapped_rows;
    std::vector<Token> wrapped_tokens;
    std::uint64_t line_number{};

    while (!text.empty()) {
      ++line_number;
      const auto line_end = text.find('\n');
      auto line = text.substr(0, line_end);
      text = line_end == std::string_view::npos ? std::string_view{}
                                                 : text.substr(line_end + 1);
      if (const auto comment = line.find('#'); comment != std::string_view::npos) {
        line = line.substr(0, comment);
      }
      line = trim(line);
      if (line.empty()) {
        continue;
      }
      if (line.front() == '~') {
        const auto heading = uppercase(trim(line.substr(1)));
        if (heading.empty()) {
          section = LasSection::none;
        } else if (heading.front() == 'V') {
          section = LasSection::version;
        } else if (heading.front() == 'W') {
          section = LasSection::well;
        } else if (heading.front() == 'C') {
          section = LasSection::curve;
        } else if (heading.front() == 'A') {
          section = LasSection::ascii;
        } else {
          section = LasSection::none;
        }
        continue;
      }

      if (section == LasSection::version || section == LasSection::well) {
        const auto dot = line.find('.');
        if (dot == std::string_view::npos) {
          continue;
        }
        const auto key = uppercase(trim(line.substr(0, dot)));
        const auto value = first_token(line.substr(dot + 1));
        if (section == LasSection::version && key == "VERS") {
          const auto parsed = parse_number(value);
          if (!parsed.has_value() || !parsed->finite) {
            return invalid_las();
          }
          version = parsed->value;
        }
        if (key == "WRAP") {
          const auto normalized = uppercase(value);
          if (normalized != "YES" && normalized != "NO") {
            return invalid_las();
          }
          wrapped = normalized == "YES";
        }
        if (section == LasSection::well && key == "NULL") {
          const auto parsed = parse_number(value);
          if (!parsed.has_value() || !parsed->finite) {
            return invalid_las();
          }
          null_sentinel = parsed->value;
        }
        continue;
      }

      if (section == LasSection::curve) {
        const auto definition = parse_curve_definition(line);
        if (!definition.has_value()) {
          return invalid_las();
        }
        definitions.push_back(*definition);
        continue;
      }

      if (section == LasSection::ascii) {
        auto tokens = tokens_in(line, line_number);
        if (wrapped) {
          wrapped_tokens.insert(wrapped_tokens.end(), tokens.begin(), tokens.end());
        } else {
          unwrapped_rows.push_back(std::move(tokens));
        }
      }
    }

    if (!version.has_value() || (*version < 2.0 || *version >= 4.0) ||
        definitions.size() < 2) {
      return invalid_las();
    }

    std::optional<std::size_t> depth_index;
    for (std::size_t index = 0; index < definitions.size(); ++index) {
      const auto mnemonic = uppercase(definitions[index].mnemonic);
      if (mnemonic == "DEPT" || mnemonic == "DEPTH") {
        depth_index = index;
        break;
      }
    }
    if (!depth_index.has_value()) {
      return invalid_las();
    }

    std::vector<double> depths;
    std::vector<std::vector<double>> curve_values(definitions.size() - 1U);
    std::vector<std::vector<std::uint8_t>> curve_nulls(definitions.size() - 1U);
    std::vector<LasDiagnostic> diagnostics;
    const auto accept_row = [&](const std::vector<Token> &row) {
      std::vector<ParsedNumber> parsed;
      parsed.reserve(row.size());
      for (std::size_t index = 0; index < row.size(); ++index) {
        const auto number = parse_number(row[index].text);
        if (!number.has_value()) {
          diagnostics.push_back(LasDiagnostic{
              .code = LasDiagnosticCode::invalid_ascii_value,
              .severity = Severity::warning,
              .line = row[index].line,
              .column = static_cast<std::uint64_t>(index + 1U),
          });
          return;
        }
        parsed.push_back(*number);
      }
      if (!parsed[*depth_index].finite ||
          (null_sentinel.has_value() &&
           parsed[*depth_index].value == *null_sentinel)) {
        diagnostics.push_back(LasDiagnostic{
            .code = LasDiagnosticCode::non_finite_depth_value,
            .severity = Severity::warning,
            .line = row[*depth_index].line,
            .column = static_cast<std::uint64_t>(*depth_index + 1U),
        });
        return;
      }

      depths.push_back(parsed[*depth_index].value);
      std::size_t curve_index{};
      for (std::size_t source_index = 0; source_index < parsed.size(); ++source_index) {
        if (source_index == *depth_index) {
          continue;
        }
        const auto is_null =
            !parsed[source_index].finite ||
            (null_sentinel.has_value() &&
             parsed[source_index].value == *null_sentinel);
        if (!parsed[source_index].finite) {
          diagnostics.push_back(LasDiagnostic{
              .code = LasDiagnosticCode::non_finite_curve_value,
              .severity = Severity::warning,
              .line = row[source_index].line,
              .column = static_cast<std::uint64_t>(source_index + 1U),
          });
        }
        curve_values[curve_index].push_back(
            is_null ? std::numeric_limits<double>::quiet_NaN()
                    : parsed[source_index].value);
        curve_nulls[curve_index].push_back(is_null ? std::uint8_t{1}
                                                    : std::uint8_t{0});
        ++curve_index;
      }
    };

    if (wrapped) {
      std::size_t offset{};
      while (offset + definitions.size() <= wrapped_tokens.size()) {
        std::vector<Token> row(wrapped_tokens.begin() + static_cast<std::ptrdiff_t>(offset),
                               wrapped_tokens.begin() + static_cast<std::ptrdiff_t>(offset + definitions.size()));
        accept_row(row);
        offset += definitions.size();
      }
      if (offset != wrapped_tokens.size()) {
        diagnostics.push_back(LasDiagnostic{
            .code = LasDiagnosticCode::incomplete_wrapped_row,
            .severity = Severity::warning,
            .line = wrapped_tokens[offset].line,
            .column = 0,
        });
      }
    } else {
      for (const auto &row : unwrapped_rows) {
        if (row.size() < definitions.size()) {
          diagnostics.push_back(LasDiagnostic{
              .code = LasDiagnosticCode::short_ascii_row,
              .severity = Severity::warning,
              .line = row.empty() ? 0 : row.front().line,
              .column = 0,
          });
          continue;
        }
        if (row.size() > definitions.size()) {
          diagnostics.push_back(LasDiagnostic{
              .code = LasDiagnosticCode::long_ascii_row,
              .severity = Severity::warning,
              .line = row.front().line,
              .column = 0,
          });
          continue;
        }
        accept_row(row);
      }
    }

    if (depths.empty()) {
      return invalid_las();
    }
    const auto direction = axis_direction(depths);
    if (!direction.has_value()) {
      return invalid_las();
    }

    const auto identity = source_identity(source, original_text);
    const auto document_id = stable_id(identity, "document", 0);
    const auto axis_id = stable_id(identity, "sampling-axis", *depth_index);
    WellLogDocumentBuilder builder(document_id, DocumentRevision{1});
    const auto depth_owner =
        std::make_shared<const std::vector<double>>(std::move(depths));
    builder.add_sampling_axis(SamplingAxis{
        .id = axis_id,
        .coordinates = owned_values(depth_owner, source),
        .domain = DepthDomain::measured_depth,
        .unit = definitions[*depth_index].unit,
        .direction = *direction,
    });

    std::size_t curve_index{};
    for (std::size_t source_index = 0; source_index < definitions.size(); ++source_index) {
      if (source_index == *depth_index) {
        continue;
      }
      const auto values = std::make_shared<const std::vector<double>>(
          std::move(curve_values[curve_index]));
      builder.add_curve(Curve{
          .id = stable_id(identity, "curve", source_index),
          .mnemonic = definitions[source_index].mnemonic,
          .display_name = definitions[source_index].display_name,
          .unit = definitions[source_index].unit,
          .sampling_axis_id = axis_id,
          .values = owned_values(values, source),
          .nulls = owned_nulls(curve_nulls[curve_index], source),
      });
      ++curve_index;
    }

    auto document = builder.build();
    if (document.id().is_nil()) {
      return exhausted();
    }
    return LasImport{.document = std::move(document),
                     .diagnostics = std::move(diagnostics)};
  } catch (const std::bad_alloc &) {
    return exhausted();
  } catch (...) {
    return internal_failure();
  }
}

} // namespace welllog
