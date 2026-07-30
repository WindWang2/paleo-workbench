#include <welllog/io/manifest.hpp>
#include <welllog/session/session.hpp>

#include <cstdlib>
#include <iostream>
#include <memory>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace {

using namespace welllog;

[[noreturn]] void fail(std::string_view message) {
  std::cerr << "FAIL: " << message << '\n';
  std::exit(EXIT_FAILURE);
}

void require(bool condition, std::string_view message) {
  if (!condition) {
    fail(message);
  }
}

EntityId id(std::string_view text) {
  const auto parsed = EntityId::parse(text);
  require(parsed.has_value(), "test UUID must be valid");
  return *parsed;
}

void manifest_round_trip_rebinds_external_buffers() {
  const auto document_id = id("01234567-89ab-4cde-8fab-0123456789ab");
  const auto axis_id = id("12345678-9abc-4def-8abc-123456789abc");
  const auto curve_id = id("23456789-abcd-4efa-8bcd-23456789abcd");

  auto depths = std::make_shared<const std::vector<double>>(
      std::initializer_list<double>{900.25, 900.5, 900.75});
  auto values = std::make_shared<const std::vector<float>>(
      std::initializer_list<float>{12.5F, 25.0F, 37.5F});
  auto nulls = std::make_shared<const std::vector<std::uint8_t>>(
      std::initializer_list<std::uint8_t>{0b00000010});

  const auto depth_view =
      BufferView::from_vector(depths, BufferSourceReference{
                                          .uri = "mmap://well-a.bin#depth",
                                          .checksum = "sha256:depth",
                                          .byte_offset = 64,
                                      });
  const auto value_view =
      BufferView::from_vector(values, BufferSourceReference{
                                          .uri = "mmap://well-a.bin#gr",
                                          .checksum = "sha256:gr",
                                          .byte_offset = 4096,
                                      });
  const auto null_view = NullBitmapView::from_raw(
      nulls->data(), 3, nulls->size(), SharedOwner{nulls},
      BufferSourceReference{
          .uri = "mmap://well-a.bin#gr-null",
          .checksum = "sha256:gr-null",
          .byte_offset = 8192,
      });

  WellLogDocumentBuilder builder(document_id, DocumentRevision{42});
  builder.add_sampling_axis(SamplingAxis{
      .id = axis_id,
      .coordinates = depth_view,
      .domain = DepthDomain::measured_depth,
      .unit = "m",
      .direction = AxisDirection::increasing,
  });
  builder.add_curve(Curve{
      .id = curve_id,
      .mnemonic = "GR",
      .display_name = "伽马",
      .unit = "API",
      .sampling_axis_id = axis_id,
      .values = value_view,
      .nulls = null_view,
  });

  const auto encoded = ManifestCodec::write(builder.build());
  require(encoded.has_value(), "valid document manifest must serialize");
  require(encoded.value().text().find("\"schemaVersion\":1") !=
              std::string::npos,
          "manifest must carry its schema version");
  require(encoded.value().text().find(
              "\"requiredSdkVersion\":\">=0.1.0 <1.0.0\"") != std::string::npos,
          "manifest must carry its required SDK version");
  require(encoded.value().text().find("mmap://well-a.bin#gr") !=
              std::string::npos,
          "manifest must retain external data references");
  require(encoded.value().text().find("900.25") == std::string::npos,
          "manifest must not inline depth samples");
  require(encoded.value().text().find("37.5") == std::string::npos,
          "manifest must not inline curve samples");

  ManifestResolvers resolvers{
      .buffer = [&](const BufferDescriptor &descriptor) -> Result<BufferView> {
        if (descriptor.source.uri == depth_view.source().uri) {
          return depth_view;
        }
        if (descriptor.source.uri == value_view.source().uri) {
          return value_view;
        }
        return Error{
            .code = ErrorCode::unresolved_buffer,
            .entity_id = std::nullopt,
            .message = MessageKey::external_buffer_unresolved,
            .arguments = {},
        };
      },
      .null_bitmap = [&](const NullBitmapDescriptor &descriptor)
          -> Result<NullBitmapView> {
        if (descriptor.source.uri == null_view.source().uri) {
          return null_view;
        }
        return Error{
            .code = ErrorCode::unresolved_buffer,
            .entity_id = std::nullopt,
            .message = MessageKey::external_buffer_unresolved,
            .arguments = {},
        };
      },
      .image_tile = {},
  };
  const auto restored = ManifestCodec::read(encoded.value().text(), resolvers);
  require(restored.has_value(), "manifest must restore through host resolvers");

  WellLogSession session;
  const auto receipt = session.execute(SetDocumentCommand{restored.value()});
  require(receipt.has_value(),
          "restored document must pass session validation");
  require(receipt.value().document_id == document_id,
          "manifest must restore document identity");
  require(receipt.value().document_revision == DocumentRevision{42},
          "manifest must restore document revision");
  require(session.diagnostics().size() == 1,
          "restored null bitmap must retain missing-data semantics");

  auto unsupported_version = std::string{encoded.value().text()};
  unsupported_version.replace(unsupported_version.find("\"schemaVersion\":1"),
                              std::string_view{"\"schemaVersion\":1"}.size(),
                              "\"schemaVersion\":2");
  const auto unsupported = ManifestCodec::read(unsupported_version, resolvers);
  require(!unsupported.has_value(),
          "unsupported manifest schema version must be rejected");
  require(unsupported.error().message ==
              MessageKey::manifest_schema_unsupported,
          "schema rejection must expose a stable localizable message key");

  auto extra_field = std::string{encoded.value().text()};
  extra_field.insert(1, "\"unexpected\":true,");
  const auto schema_mismatch = ManifestCodec::read(extra_field, resolvers);
  require(!schema_mismatch.has_value(),
          "manifest fields outside the published schema must be rejected");
  require(schema_mismatch.error().message == MessageKey::manifest_invalid,
          "schema mismatch must expose the stable manifest error key");

  auto empty_source = std::string{encoded.value().text()};
  empty_source.replace(
      empty_source.find("\"uri\":\"mmap://well-a.bin#depth\""),
      std::string_view{"\"uri\":\"mmap://well-a.bin#depth\""}.size(),
      "\"uri\":\"\"");
  const auto invalid_source = ManifestCodec::read(empty_source, resolvers);
  require(!invalid_source.has_value(),
          "manifest buffer source URI must satisfy the published schema");

  auto zero_length = std::string{encoded.value().text()};
  zero_length.replace(zero_length.find("\"length\":3"),
                      std::string_view{"\"length\":3"}.size(), "\"length\":0");
  const auto invalid_length = ManifestCodec::read(zero_length, resolvers);
  require(!invalid_length.has_value(),
          "manifest buffer dimensions must satisfy the published schema");
}

void manifest_writer_rejects_documents_outside_schema() {
  const auto document_id = id("3456789a-bcde-4fab-8cde-3456789abcde");
  WellLogDocumentBuilder empty_builder(document_id, DocumentRevision{1});
  const auto empty_result = ManifestCodec::write(empty_builder.build());
  require(!empty_result.has_value(),
          "manifest writer must reject documents without axes and curves");

  const auto axis_id = id("456789ab-cdef-4abc-8def-456789abcdef");
  const auto curve_id = id("56789abc-defa-4bcd-8efa-56789abcdefa");
  auto depths = std::make_shared<const std::vector<double>>(
      std::initializer_list<double>{100.0});
  auto values = std::make_shared<const std::vector<float>>(
      std::initializer_list<float>{1.0F});
  WellLogDocumentBuilder missing_source_builder(document_id,
                                                DocumentRevision{1});
  missing_source_builder.add_sampling_axis(SamplingAxis{
      .id = axis_id,
      .coordinates = BufferView::from_vector(depths),
      .domain = DepthDomain::measured_depth,
      .unit = "m",
      .direction = AxisDirection::increasing,
  });
  missing_source_builder.add_curve(Curve{
      .id = curve_id,
      .mnemonic = "GR",
      .display_name = "Gamma ray",
      .unit = "API",
      .sampling_axis_id = axis_id,
      .values = BufferView::from_vector(values),
      .nulls = {},
  });
  const auto missing_source_result =
      ManifestCodec::write(missing_source_builder.build());
  require(!missing_source_result.has_value(),
          "manifest writer must reject buffers without external references");
}

} // namespace

int main() {
  manifest_round_trip_rebinds_external_buffers();
  manifest_writer_rejects_documents_outside_schema();
  std::cout << "PASS: manifest round trip\n";
  return EXIT_SUCCESS;
}
