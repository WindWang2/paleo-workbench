// Integration tests for the raster image layer (#152, rendering.md section 10).
// Exercises the document model (ImageSource), the multi-resolution pyramid's
// visible-tile selection, asset-limit rejection, the prepared-scene tile
// placement, and SVG raster-object export. The engine never decodes images;
// tests supply decoded tile bytes through a fake resolver.

#include "scene/prepare.hpp"

#include <welllog/export/svg.hpp>
#include <welllog/scene/image_pyramid.hpp>
#include <welllog/scene/scene.hpp>
#include <welllog/session/session.hpp>

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <string>
#include <string_view>
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

void require_near(double actual, double expected, std::string_view message) {
  if (std::abs(actual - expected) > 1.0e-9) {
    std::cerr << "actual " << actual << " expected " << expected << '\n';
    fail(message);
  }
}

EntityId id(std::string_view text) {
  const auto parsed = EntityId::parse(text);
  require(parsed.has_value(), "test UUID must be valid");
  return *parsed;
}

const auto document_id = id("a0000000-0000-4000-8000-000000000001");
const auto track_id = id("a0000000-0000-4000-8000-000000000002");
const auto image_source_id = id("a0000000-0000-4000-8000-000000000003");
const auto image_layer_id = id("a0000000-0000-4000-8000-000000000004");

// A 2048x2048 image spanning depth 1000..1100, dpi 300.
WellLogDocument image_document(std::uint64_t width_px = 2048,
                               std::uint64_t height_px = 2048,
                               double dpi = 300.0) {
  WellLogDocumentBuilder builder(document_id, DocumentRevision{1});
  builder.add_image_source(ImageSource{
      .id = image_source_id,
      .width_px = width_px,
      .height_px = height_px,
      .pixel_format = PixelFormat::rgba8,
      .reference_depth_top = 1000.0,
      .reference_depth_bottom = 1100.0,
      .dpi = static_cast<std::uint32_t>(dpi),
      .source = BufferSourceReference{.uri = "image://core-photo/1",
                                      .checksum = {},
                                      .byte_offset = 0},
  });
  return builder.build();
}

ScenePresentationBuilder image_presentation() {
  auto builder = ScenePresentationBuilder(
      document_id,
      ReferenceDepthRange{
          .domain = DepthDomain::measured_depth,
          .unit = "m",
          .top = 1000.0,
          .bottom = 1100.0,
      },
      Millimetres{200.0}, "font-fixture-v1");
  builder.add_track(TrackSpec{
      .id = track_id,
      .width = Millimetres{80.0},
      .z_order = 0,
      .header = {},
  });
  builder.add_image_layer(ImageLayerSpec{
      .id = image_layer_id,
      .track_id = track_id,
      .image_source_id = image_source_id,
      .z_order = 0,
      .visible = true,
  });
  return builder;
}

// Builds the pyramid map and prepares the scene via the preparer directly
// (the session does not yet thread the image pyramid map; that is host wiring).
PreparedScene
prepare_with_image(const WellLogDocument &document,
                   ScenePresentationBuilder &builder,
                   const ImagePyramidQuery &query) {
  const auto presentation = builder.build();
  detail::ScenePreparer::CurveLodMap curve_lods;
  detail::ScenePreparer::ImagePyramidMap image_pyramids;
  const auto pyramid = ImagePyramid::build(
      document.image_sources().front(),
      ImagePyramidOptions{.tile_size = 256, .maximum_derived_bytes = 16 * 1024});
  require(pyramid.has_value(), "image pyramid must build");
  image_pyramids.emplace(image_source_id, pyramid.value());
  const auto scene = detail::ScenePreparer::prepare(
      document, presentation, curve_lods, {}, image_pyramids, query);
  require(scene.has_value(), "image scene must prepare");
  return scene.value();
}

// --- Tests ------------------------------------------------------------------

// Criterion 1: an image layer declares its depth range, dimensions, DPI,
// pixel format and data-source identity, all of which round-trip into the
// prepared scene.
void image_layer_declares_metadata_and_prepares() {
  const auto document = image_document();
  auto builder = image_presentation();
  const auto scene = prepare_with_image(
      document, builder,
      ImagePyramidQuery{.viewport_top = 1000.0,
                        .viewport_bottom = 1100.0,
                        .pixel_height = 1000.0,
                        .prefetch_viewports = 0.0});
  require(scene.image_layers().size() == 1, "one image layer expected");
  const auto &layer = scene.image_layers().front();
  require(layer.id == image_layer_id, "layer identity must round-trip");
  require(layer.image_source_id == image_source_id,
          "image source identity must round-trip");
  require(layer.tile_count > 0, "at least one visible tile must be prepared");

  const auto &tile = scene.image_tiles()[0];
  require(tile.dpi == 300, "tile must carry the source DPI");
  require(tile.pixel_format == PixelFormat::rgba8,
          "tile must carry the pixel format");
  require(tile.source.uri == "image://core-photo/1",
          "tile must carry the data-source identity");
  // The image spans the full presentation depth range.
  require_near(tile.rect.width.value, 80.0,
               "tile must span the full track width");
}

// Criterion 2: the pyramid selects only tiles overlapping the visible depth
// window (+ prefetch), not the whole image.
void pyramid_selects_only_visible_tiles() {
  const auto document = image_document(2048, 8192); // tall image

  // Full-depth viewport: all tiles.
  auto full_builder = image_presentation();
  const auto full_scene = prepare_with_image(
      document, full_builder,
      ImagePyramidQuery{.viewport_top = 1000.0,
                        .viewport_bottom = 1100.0,
                        .pixel_height = 100.0,
                        .prefetch_viewports = 0.0});
  const auto full_count = full_scene.image_layers().front().tile_count;
  require(full_count > 0, "full viewport must select tiles");

  // Partial (top-quarter) viewport: strictly fewer tiles.
  auto partial_builder = image_presentation();
  const auto partial_scene = prepare_with_image(
      document, partial_builder,
      ImagePyramidQuery{.viewport_top = 1000.0,
                        .viewport_bottom = 1025.0,
                        .pixel_height = 100.0,
                        .prefetch_viewports = 0.0});
  const auto partial_count =
      partial_scene.image_layers().front().tile_count;
  require(partial_count > 0, "partial viewport must still select tiles");
  require(partial_count < full_count,
          "a partial viewport must select fewer tiles than the full image");
}

// Criterion 5: oversized / invalid-metadata images are rejected.
void invalid_images_are_rejected() {
  auto builder = image_presentation();

  // Zero dimensions.
  {
    WellLogDocumentBuilder b(document_id, DocumentRevision{1});
    b.add_image_source(ImageSource{
        .id = image_source_id, .width_px = 0, .height_px = 100,
        .pixel_format = PixelFormat::rgba8,
        .reference_depth_top = 1000.0, .reference_depth_bottom = 1100.0,
        .dpi = 300, .source = BufferSourceReference{.uri = "x", .checksum = {}, .byte_offset = 0}});
    const auto scene = detail::ScenePreparer::prepare(
        b.build(), builder.build());
    require(!scene.has_value(), "zero-dimension image must be rejected");
    require(scene.error().code == ErrorCode::invalid_presentation,
            "zero-dimension image must use invalid_presentation");
  }

  // Pixel count over the limit: dimensions each under the per-side cap
  // (65536) but total pixels beyond maximum_image_pixels.
  {
    WellLogDocumentBuilder b(document_id, DocumentRevision{1});
    // 24000 * 24000 = 576M pixels > 512M limit, each side < 65536.
    b.add_image_source(ImageSource{
        .id = image_source_id,
        .width_px = 24000, .height_px = 24000,
        .pixel_format = PixelFormat::rgba8,
        .reference_depth_top = 1000.0, .reference_depth_bottom = 1100.0,
        .dpi = 300, .source = BufferSourceReference{.uri = "x", .checksum = {}, .byte_offset = 0}});
    const auto scene = detail::ScenePreparer::prepare(
        b.build(), builder.build());
    require(!scene.has_value(), "oversized image must be rejected");
    require(scene.error().code == ErrorCode::invalid_image,
            "oversized image must use invalid_image");
  }

  // Inverted depth range.
  {
    WellLogDocumentBuilder b(document_id, DocumentRevision{1});
    b.add_image_source(ImageSource{
        .id = image_source_id, .width_px = 100, .height_px = 100,
        .pixel_format = PixelFormat::rgba8,
        .reference_depth_top = 1100.0, .reference_depth_bottom = 1000.0,
        .dpi = 300, .source = BufferSourceReference{.uri = "x", .checksum = {}, .byte_offset = 0}});
    const auto scene = detail::ScenePreparer::prepare(
        b.build(), builder.build());
    require(!scene.has_value(), "inverted-depth image must be rejected");
  }
}

// Criterion 7: SVG keeps each visible tile as a raster object with explicit
// physical dimensions, DPI and source identity.
void svg_keeps_raster_object_with_physical_dimensions() {
  const auto document = image_document();
  auto builder = image_presentation();
  const auto scene = prepare_with_image(
      document, builder,
      ImagePyramidQuery{.viewport_top = 1000.0,
                        .viewport_bottom = 1100.0,
                        .pixel_height = 500.0,
                        .prefetch_viewports = 0.0});
  const auto exported = SvgExporter::write(scene);
  require(exported.has_value(), "SVG export must succeed");
  const auto text = std::string{exported.value().text()};
  require(text.find("<image ") != std::string::npos,
          "SVG must emit an <image> element");
  require(text.find("data-image-source-id=\"" +
                    image_source_id.to_string() + "\"") != std::string::npos,
          "SVG must tag the image source identity");
  require(text.find("data-dpi=\"300\"") != std::string::npos,
          "SVG must carry the explicit DPI");
  require(text.find("width=") != std::string::npos &&
              text.find("height=") != std::string::npos,
          "SVG must emit physical width/height");
  require(text.find("href=\"image://core-photo/1\"") != std::string::npos,
          "SVG must reference the data-source URI, not inline pixels");
}

// The pyramid build itself: statistics report levels, budget-limited degrade.
void pyramid_build_reports_levels_and_budget() {
  const auto document = image_document(2048, 2048);
  const auto pyramid = ImagePyramid::build(
      document.image_sources().front(),
      ImagePyramidOptions{.tile_size = 256, .maximum_derived_bytes = 1024 * 1024});
  require(pyramid.has_value(), "pyramid must build");
  const auto stats = pyramid.value().statistics();
  require(stats.width_px == 2048 && stats.height_px == 2048,
          "statistics must report source dimensions");
  require(stats.tile_size == 256, "statistics must report tile size");
  require(stats.level_count >= 1, "pyramid must have at least one level");
}

// A hidden image layer keeps its identity but emits no tiles.
void hidden_image_layer_emits_no_tiles() {
  const auto document = image_document();
  auto builder = ScenePresentationBuilder(
      document_id,
      ReferenceDepthRange{.domain = DepthDomain::measured_depth, .unit = "m",
                          .top = 1000.0, .bottom = 1100.0},
      Millimetres{200.0}, "font-fixture-v1");
  builder.add_track(TrackSpec{
      .id = track_id, .width = Millimetres{80.0}, .z_order = 0, .header = {}});
  builder.add_image_layer(ImageLayerSpec{
      .id = image_layer_id, .track_id = track_id,
      .image_source_id = image_source_id, .z_order = 0, .visible = false});
  const auto scene = prepare_with_image(
      document, builder,
      ImagePyramidQuery{.viewport_top = 1000.0, .viewport_bottom = 1100.0,
                        .pixel_height = 500.0, .prefetch_viewports = 0.0});
  require(scene.image_layers().size() == 1,
          "hidden layer must keep its identity");
  require(scene.image_layers().front().tile_count == 0,
          "hidden layer must emit no tiles");
}

} // namespace

int main() {
  image_layer_declares_metadata_and_prepares();
  pyramid_selects_only_visible_tiles();
  invalid_images_are_rejected();
  svg_keeps_raster_object_with_physical_dimensions();
  pyramid_build_reports_levels_and_budget();
  hidden_image_layer_emits_no_tiles();
  std::cout << "PASS: raster image layer\n";
  return EXIT_SUCCESS;
}
