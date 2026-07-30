// Scene-emission test for the hand-rolled PDF writer (#187, ADR: PDF via
// hand-rolled writer). Proves PdfSceneExporter serializes a PreparedScene to a
// structurally-valid, byte-deterministic, single-page PDF whose content stream
// is PURE vector geometry (interval rects, markers, symbols, curves, text-as-
// outlines) with no rasterisation, and that track clipping is honoured.
//
// External structural validity is checked with qpdf --check / pdfinfo when
// available. The Flate round-trip inflates the ACTUAL embedded content stream
// (extracted from the PDF bytes) so the operator assertions run on the real
// artifact, not a stand-in string.

#include <welllog/export/pdf_scene.hpp>
#include <welllog/session/session.hpp>
#include <welllog/text/harfbuzz_text_engine.hpp>

#include <array>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <string>
#include <string_view>
#include <vector>
#include <zlib.h>

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

#ifndef WELLLOG_TEST_FONT_DIR
#define WELLLOG_TEST_FONT_DIR "tests/assets/fonts"
#endif

const auto document_id = id("70000000-0000-4000-8000-000000000001");
const auto axis_id = id("70000000-0000-4000-8000-000000000002");
const auto curve_id = id("70000000-0000-4000-8000-000000000003");
const auto track_id = id("70000000-0000-4000-8000-000000000004");
const auto scale_id = id("70000000-0000-4000-8000-000000000005");
const auto interval_layer_id = id("70000000-0000-4000-8000-000000000006");
const auto marker_layer_id = id("70000000-0000-4000-8000-000000000007");
const auto symbol_layer_id = id("70000000-0000-4000-8000-000000000008");
const auto text_layer_id = id("70000000-0000-4000-8000-000000000009");
const auto curve_layer_id = id("70000000-0000-4000-8000-00000000000a");
const auto interval_id = id("70000000-0000-4000-8000-00000000000b");
const auto marker_id = id("70000000-0000-4000-8000-00000000000c");
const auto symbol_id = id("70000000-0000-4000-8000-00000000000d");
const auto annotation_id = id("70000000-0000-4000-8000-00000000000e");

// Vertical-CJK scene uses its own document/track/text ids (separate scene).
const auto v_document_id = id("70000000-0000-4000-8000-000000000020");
const auto v_axis_id = id("70000000-0000-4000-8000-000000000021");
const auto v_curve_id = id("70000000-0000-4000-8000-000000000022");
const auto v_track_id = id("70000000-0000-4000-8000-000000000023");
const auto v_text_layer_id = id("70000000-0000-4000-8000-000000000024");
const auto v_annotation_id = id("70000000-0000-4000-8000-000000000025");

std::shared_ptr<HarfBuzzTextEngine> make_engine() {
  auto engine = std::make_shared<HarfBuzzTextEngine>();
  require(engine
              ->add_project_font(std::string{WELLLOG_TEST_FONT_DIR} +
                                 "/NotoSans-Regular.ttf")
              .has_value(),
          "bundled test font must load");
  return engine;
}

// Builds a scene with one curve layer (linear scale), an interval, a marker, a
// diamond symbol, and a text annotation — so the PDF exercises every pure-
// vector primitive kind this ticket covers. Mirrors the scene builders in
// layer_svg_test.cpp / paginated_svg_test.cpp.
std::shared_ptr<const PreparedScene> make_scene(WellLogSession &session) {
  auto depths = std::make_shared<const std::vector<double>>(
      std::initializer_list<double>{1000.0, 1005.0, 1010.0});
  auto values = std::make_shared<const std::vector<double>>(
      std::initializer_list<double>{25.0, 50.0, 75.0});
  WellLogDocumentBuilder document(document_id, DocumentRevision{9});
  document.add_sampling_axis(SamplingAxis{
      .id = axis_id,
      .coordinates = BufferView::from_vector(depths),
      .domain = DepthDomain::measured_depth,
      .unit = "m",
      .direction = AxisDirection::increasing,
  });
  document.add_curve(Curve{
      .id = curve_id,
      .mnemonic = "GR",
      .display_name = "Gamma Ray",
      .unit = "API",
      .sampling_axis_id = axis_id,
      .values = BufferView::from_vector(values),
      .nulls = {},
  });
  // Semi-transparent fill (alpha 180) so the PDF exercises the alpha/ExtGState
  // path: the writer must emit a `gs` operator + a /ca ExtGState object.
  document.add_interval(Interval{
      .id = interval_id,
      .top_reference_depth = 1000.0,
      .bottom_reference_depth = 1005.0,
      .semantic = IntervalSemantic::lithology,
      .pattern_id = {},
      .fill_color = RgbaColor{220, 200, 120, 180},
      .label = "Sand",
  });
  document.add_marker(Marker{
      .id = marker_id,
      .reference_depth = 1005.0,
      .semantic = MarkerSemantic::formation_top,
      .label = "Top B",
  });
  document.add_symbol(SymbolOccurrence{
      .id = symbol_id,
      .reference_depth = 1002.0,
      .track_fraction = 0.5,
      .kind = SymbolKind::diamond,
      .label = "fossil",
  });
  document.add_annotation(TextAnnotation{
      .id = annotation_id,
      .anchor = AnnotationAnchor::reference_depth,
      .reference_depth = 1006.0,
      .track_fraction = 0.5,
      .track_id = {},
      .depth_fraction = 0.0,
      .horizontal_fraction = 0.0,
      .scene_point = {},
      .text = "Gas",
      .language = "en",
      .orientation = TextOrientation::horizontal,
      .rotation_degrees = 0.0,
      .font_size = Millimetres{4.0},
  });
  require(session.execute(SetDocumentCommand{document.build()}).has_value(),
          "document must be accepted");

  ScenePresentationBuilder presentation(
      document_id,
      ReferenceDepthRange{
          .domain = DepthDomain::measured_depth,
          .unit = "m",
          .top = 1000.0,
          .bottom = 1010.0,
      },
      Millimetres{100.0}, "font-fixture-v1");
  presentation.add_track(TrackSpec{
      .id = track_id,
      .width = Millimetres{40.0},
      .z_order = 0,
  });
  presentation.add_scale(TrackScaleSpec{
      .id = scale_id,
      .track_id = track_id,
      .mode = ScaleMode::linear,
      .minimum = 0.0,
      .maximum = 100.0,
      .direction = ScaleDirection::left_to_right,
      .unit = "API",
  });
  presentation.add_curve_layer(CurveLayerSpec{
      .id = curve_layer_id,
      .track_id = track_id,
      .curve_id = curve_id,
      .scale_id = scale_id,
      .color = RgbaColor{20, 120, 20, 255},
      .line_width = Millimetres{0.5},
      .z_order = 0,
      .visible = true,
  });
  presentation.add_interval_layer(IntervalLayerSpec{
      .id = interval_layer_id,
      .track_id = track_id,
      .z_order = 1,
      .draw_labels = false,
      .label_font_size = Millimetres{3.0},
      .label_color = RgbaColor{0, 0, 0, 255},
  });
  presentation.add_marker_layer(MarkerLayerSpec{
      .id = marker_layer_id,
      .track_id = track_id,
      .z_order = 2,
      .line_color = RgbaColor{200, 0, 0, 255},
      .line_width = Millimetres{0.5},
      .draw_labels = false,
  });
  presentation.add_symbol_layer(SymbolLayerSpec{
      .id = symbol_layer_id,
      .track_id = track_id,
      .z_order = 3,
      .color = RgbaColor{0, 0, 200, 255},
      .symbol_size = Millimetres{4.0},
  });
  presentation.add_text_layer(TextLayerSpec{
      .id = text_layer_id,
      .track_id = track_id,
      .z_order = 4,
      .color = RgbaColor{10, 10, 10, 255},
  });
  require(session.execute(SetPresentationCommand{presentation.build()})
              .has_value(),
          "presentation must be accepted");
  auto scene = session.prepared_scene(document_id);
  require(scene != nullptr, "scene must be prepared");
  return scene;
}

ExportSnapshot make_snapshot() {
  return ExportSnapshot{
      .document_id = document_id,
      .document_revision = DocumentRevision{9},
      .presentation_version = PresentationVersion{1},
      .depth_transform =
          DepthTransformDescriptor{
              .domain = DepthDomain::measured_depth,
              .unit = "m",
              .reference_top = 1000.0,
              .reference_bottom = 1010.0,
              .version = 1,
          },
      .font_asset_fingerprint = "font-fixture-v1",
      .pattern_versions = {},
      .page = ExportPageSpec{
          .mode = PaginationMode::continuous,
          .page_width = Millimetres{120.0},
          .page_height = Millimetres{297.0},
          .margins = ExportPageMargins{.top = Millimetres{10.0},
                                       .right = Millimetres{10.0},
                                       .bottom = Millimetres{10.0},
                                       .left = Millimetres{10.0}},
          .dpi = 300,
          .page_overlap = 0.0,
          .well_name = {},
          .repeat_headers = true,
          .repeat_legend = true,
          .show_page_numbers = true,
          .show_depth_range = true,
      },
  };
}

// Writes the PDF bytes to a temp file for external verification.
std::filesystem::path write_temp(std::string_view bytes) {
  const auto path =
      std::filesystem::temp_directory_path() / "welllog_pdf_scene.pdf";
  std::ofstream out(path, std::ios::binary);
  require(out.good(), "temp PDF file must open");
  out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
  out.close();
  return path;
}

int run(std::string_view command, std::string &captured) {
  std::array<char, 128> buffer{};
  captured.clear();
  const auto pipe =
      popen(std::string{command}.c_str(), "r"); // NOLINT(cert-env33-c)
  if (pipe == nullptr) {
    return -1;
  }
  while (std::fgets(buffer.data(), buffer.size(), pipe) != nullptr) {
    captured += buffer.data();
  }
  return pclose(pipe); // NOLINT(cert-env33-c)
}

// Extracts + inflates the first FlateDecode content stream from the PDF bytes,
// returning the decompressed operator text. Mirrors pdf_spike_test.cpp's
// flate_stream_round_trips but operates on the scene PDF.
std::string inflate_content_stream(std::string_view bytes) {
  const auto filter_pos = bytes.find("/Filter /FlateDecode");
  require(filter_pos != std::string_view::npos,
          "PDF must contain a FlateDecode stream");
  const auto stream_kw = bytes.find("stream\n", filter_pos);
  require(stream_kw != std::string_view::npos,
          "stream keyword must follow the dict");
  const auto payload_start = stream_kw + std::strlen("stream\n");
  const auto endstream = bytes.find("\nendstream", payload_start);
  require(endstream != std::string_view::npos,
          "endstream must terminate the stream");
  const std::string compressed =
      std::string{bytes.substr(payload_start, endstream - payload_start)};
  require(!compressed.empty(), "the embedded content stream must be non-empty");
  z_stream stream{};
  require(inflateInit(&stream) == Z_OK, "inflateInit must succeed");
  std::string sink(compressed.size() * 8 + 4096, '\0');
  stream.next_in =
      reinterpret_cast<Bytef *>(const_cast<char *>(compressed.data()));
  stream.avail_in = static_cast<uInt>(compressed.size());
  stream.next_out = reinterpret_cast<Bytef *>(sink.data());
  stream.avail_out = static_cast<uInt>(sink.size());
  const auto rc = inflate(&stream, Z_FINISH);
  inflateEnd(&stream);
  require(rc == Z_STREAM_END, "the embedded stream must inflate cleanly");
  return std::string(sink.data(), stream.total_out);
}

// Builds the scene-PDF; reused by every assertion so the input is identical
// across the determinism check.
PdfDocument build_scene_document() {
  WellLogSession session;
  session.set_text_engine(make_engine());
  const auto scene = make_scene(session);
  const auto snapshot = make_snapshot();
  const auto result = PdfSceneExporter::write(*scene, snapshot);
  require(result.has_value(), "scene PDF must build");
  return result.value();
}

// --- Tests ------------------------------------------------------------------

// The PDF is structurally complete: header, Catalog/Pages/Page, Flate stream,
// MediaBox, %%EOF, no timestamps.
void pdf_is_structurally_complete() {
  const auto doc = build_scene_document();
  const auto bytes = std::string{doc.bytes()};
  require(bytes.starts_with("%PDF-1.7"), "PDF header must be present");
  require(bytes.find("/Type /Catalog") != std::string::npos,
          "Catalog object must exist");
  require(bytes.find("/Type /Pages") != std::string::npos,
          "Pages object must exist");
  require(bytes.find("/Count 1") != std::string::npos,
          "exactly one page must be declared");
  require(bytes.find("/Type /Page ") != std::string::npos,
          "a Page object must exist");
  require(bytes.find("/MediaBox [0 0 ") != std::string::npos,
          "MediaBox must be present");
  require(bytes.find("/Filter /FlateDecode") != std::string::npos,
          "content stream must be Flate-compressed");
  require(bytes.find("%%EOF") != std::string::npos, "PDF must end with %%EOF");
  require(bytes.find("startxref") != std::string::npos,
          "xref offset must be recorded");
}

// External structural validity: qpdf --check (and pdfinfo) accept the file.
void external_tools_accept_the_pdf() {
  const auto doc = build_scene_document();
  const auto path = write_temp(doc.bytes());

  bool qpdf_available = std::filesystem::exists("/usr/sbin/qpdf") ||
                        std::filesystem::exists("/usr/bin/qpdf");
  if (qpdf_available) {
    std::string captured;
    const auto rc = run("qpdf --check " + path.string() + " 2>&1", captured);
    require(rc == 0,
            "qpdf --check must accept the PDF (rc != 0): " + captured);
  }
  bool pdfinfo_available =
      std::filesystem::exists("/usr/sbin/pdfinfo") ||
      std::filesystem::exists("/usr/bin/pdfinfo");
  if (pdfinfo_available) {
    std::string captured;
    const auto rc = run("pdfinfo " + path.string() + " 2>&1", captured);
    require(rc == 0, "pdfinfo must accept the PDF (rc != 0): " + captured);
  }
  if (!qpdf_available && !pdfinfo_available) {
    std::cout << "welllog.pdf-scene: qpdf/pdfinfo absent; skipping external "
                 "structural check\n";
  }
  std::error_code ec;
  std::filesystem::remove(path, ec);
}

// The inflated content stream contains every vector primitive kind (criterion 5)
// and the graphics-state operators for clipping + the page transform.
void content_stream_contains_vector_primitives() {
  const auto doc = build_scene_document();
  const auto inflated = inflate_content_stream(doc.bytes());
  // Path operators for curves/symbols/intervals/markers.
  require(inflated.find(" m\n") != std::string::npos,
          "stream must contain a move-to");
  require(inflated.find(" l\n") != std::string::npos,
          "stream must contain a line-to (curves/markers)");
  require(inflated.find(" re\n") != std::string::npos,
          "stream must contain a rectangle (interval/clip)");
  require(inflated.find("f\n") != std::string::npos,
          "stream must contain a fill (interval/symbol/text)");
  require(inflated.find("S\n") != std::string::npos,
          "stream must contain a stroke (marker/curve)");
  require(inflated.find(" c\n") != std::string::npos,
          "stream must contain a cubic (symbol circle / text outlines)");
  // Graphics state for the page transform + per-track clipping.
  require(inflated.find("cm\n") != std::string::npos,
          "stream must contain a concat-matrix (page transform)");
  require(inflated.find("q\n") != std::string::npos,
          "stream must save graphics state (per-track clip scope)");
  require(inflated.find("Q\n") != std::string::npos,
          "stream must restore graphics state");
  require(inflated.find("W\n") != std::string::npos,
          "stream must establish a clip (track clipPath)");
}

// Builds a VERTICAL text scene with a MIXED Latin+CJK string "A砂". In vertical
// orientation ICU classifies Latin 'A' as rotated (glyph.rotation=90) and CJK
// '砂' as upright (glyph.rotation=0), while the run rotation is 0. A correct
// emitter must therefore read the PER-GLYPH rotation — emitting one glyph with a
// 90° matrix and one with 0° — rather than the (uniform) run rotation.
std::shared_ptr<const PreparedScene>
make_vertical_cjk_scene(WellLogSession &session) {
  auto depths = std::make_shared<const std::vector<double>>(
      std::initializer_list<double>{1000.0, 1010.0});
  auto values = std::make_shared<const std::vector<double>>(
      std::initializer_list<double>{1.0, 2.0});
  WellLogDocumentBuilder document(v_document_id, DocumentRevision{3});
  document.add_sampling_axis(SamplingAxis{
      .id = v_axis_id,
      .coordinates = BufferView::from_vector(depths),
      .domain = DepthDomain::measured_depth,
      .unit = "m",
      .direction = AxisDirection::increasing,
  });
  document.add_curve(Curve{
      .id = v_curve_id,
      .mnemonic = "GR",
      .display_name = "Gamma Ray",
      .unit = "API",
      .sampling_axis_id = v_axis_id,
      .values = BufferView::from_vector(values),
      .nulls = {},
  });
  // "A砂": Latin A (vertical-rotated) + CJK 砂 (vertical-upright).
  document.add_annotation(TextAnnotation{
      .id = v_annotation_id,
      .anchor = AnnotationAnchor::reference_depth,
      .reference_depth = 1005.0,
      .track_fraction = 0.5,
      .track_id = {},
      .depth_fraction = 0.0,
      .horizontal_fraction = 0.0,
      .scene_point = {},
      .text = "A\xE7\xA0\x82", // A砂
      .language = "zh-Hans",
      .orientation = TextOrientation::vertical,
      .rotation_degrees = 0.0,
      .font_size = Millimetres{4.0},
  });
  require(session.execute(SetDocumentCommand{document.build()}).has_value(),
          "vertical document must be accepted");
  ScenePresentationBuilder presentation(
      v_document_id,
      ReferenceDepthRange{
          .domain = DepthDomain::measured_depth,
          .unit = "m",
          .top = 1000.0,
          .bottom = 1010.0,
      },
      Millimetres{100.0}, "font-fixture-v1");
  presentation.add_track(TrackSpec{
      .id = v_track_id,
      .width = Millimetres{40.0},
      .z_order = 0,
  });
  presentation.add_text_layer(TextLayerSpec{
      .id = v_text_layer_id,
      .track_id = v_track_id,
      .z_order = 0,
      .color = RgbaColor{10, 10, 10, 255},
  });
  require(session.execute(SetPresentationCommand{presentation.build()})
              .has_value(),
          "vertical presentation must be accepted");
  auto scene = session.prepared_scene(v_document_id);
  require(scene != nullptr, "vertical scene must be prepared");
  return scene;
}

ExportSnapshot make_vertical_snapshot() {
  return ExportSnapshot{
      .document_id = v_document_id,
      .document_revision = DocumentRevision{3},
      .presentation_version = PresentationVersion{1},
      .depth_transform =
          DepthTransformDescriptor{
              .domain = DepthDomain::measured_depth,
              .unit = "m",
              .reference_top = 1000.0,
              .reference_bottom = 1010.0,
              .version = 1,
          },
      .font_asset_fingerprint = "font-fixture-v1",
      .pattern_versions = {},
      .page = ExportPageSpec{
          .mode = PaginationMode::continuous,
          .page_width = Millimetres{120.0},
          .page_height = Millimetres{297.0},
          .margins = ExportPageMargins{.top = Millimetres{10.0},
                                       .right = Millimetres{10.0},
                                       .bottom = Millimetres{10.0},
                                       .left = Millimetres{10.0}},
          .dpi = 300,
          .page_overlap = 0.0,
          .well_name = {},
          .repeat_headers = true,
          .repeat_legend = true,
          .show_page_numbers = true,
          .show_depth_range = true,
      },
  };
}

// Vertical mixed text (Latin 'A' + CJK '砂') must emit a distinct per-glyph
// rotation: 'A' is rotated 90° in vertical orientation (glyph.rotation=90) while
// '砂' is upright (glyph.rotation=0), yet the run rotation is 0. So the PDF must
// contain BOTH a 90° glyph matrix (the rotated glyph) and a 0° matrix (the
// upright glyph) — proving the emitter reads glyph.rotation_degrees, not the run
// rotation. This directly guards the regression found in code review (a run-
// rotation emitter would produce identical 0° matrices for both glyphs).
void vertical_text_uses_per_glyph_rotation() {
  WellLogSession session;
  auto engine = make_engine();
  require(engine
              ->add_project_font(std::string{WELLLOG_TEST_FONT_DIR} +
                                 "/SourceHanSansCN-subset.otf")
              .has_value(),
          "bundled CJK subset font must load");
  session.set_text_engine(std::move(engine));
  const auto scene = make_vertical_cjk_scene(session);
  // Confirm the prepared scene actually has one rotated + one upright glyph, so
  // the assertion is meaningful (guards against a font/classification change
  // silently making both glyphs identical).
  int rotated_count = 0;
  int upright_count = 0;
  for (const auto &run : scene->text_runs()) {
    for (std::uint64_t o = 0; o < run.glyph_count; ++o) {
      const auto &g = scene->glyphs()[run.first_glyph + o];
      if (g.rotation_degrees == 0.0) {
        ++upright_count;
      } else {
        ++rotated_count;
      }
    }
  }
  require(upright_count == 1 && rotated_count == 1,
          "the mixed run must prepare one upright + one rotated glyph");

  const auto snapshot = make_vertical_snapshot();
  const auto result = PdfSceneExporter::write(*scene, snapshot);
  require(result.has_value(), "vertical PDF must build");
  const auto inflated = inflate_content_stream(result.value().bytes());
  // Upright glyph (rot 0°, fs 4) → cm matrix [4 0 0 -4 ox oy]: the b,c operands
  // are both 0 ("0 0").
  // Rotated glyph (rot 90°, fs 4) → cm matrix [~0 4 4 ~0 ox oy]: cos(π/2) is a
  // tiny non-zero float, so the a,d operands are ~2e-16, but b,c are exactly
  // 4 ("4 4"). Match the b,c signature rather than the near-zero values.
  require(inflated.find("\n4 0 0 -4 ") != std::string::npos,
          "the upright glyph must emit a 0° per-glyph cm (b=c=0)");
  require(inflated.find(" 4 4 ") != std::string::npos,
          "the rotated glyph must emit a 90° per-glyph cm (b=c=4)");
}

// Pure-vector export never rasterises (criterion 7): no XObject image drawing
// (Do) and no inline image (BI/EI) operators appear in the content stream.
void content_stream_has_no_rasterisation() {
  const auto doc = build_scene_document();
  const auto inflated = inflate_content_stream(doc.bytes());
  // XObject `Do` and inline image `BI`/`EI` are the only image-drawing ops.
  // Match on the operator-with-newline form the writer uses.
  require(inflated.find(" Do\n") == std::string::npos,
          "stream must not draw an XObject image");
  require(inflated.find("BI\n") == std::string::npos,
          "stream must not contain an inline image begin");
}

// Semi-transparent fills resolve to a named /ExtGState: the content stream
// emits `gs /GSn` and the PDF carries a /ca ExtGState object referenced from the
// page Resources. (PDF has no inline opacity; ADR: PDF via hand-rolled writer.)
void semi_transparent_fill_uses_extgstate() {
  const auto doc = build_scene_document();
  const auto bytes = std::string{doc.bytes()};
  const auto inflated = inflate_content_stream(bytes);
  require(inflated.find("/GS0 gs\n") != std::string::npos,
          "the semi-transparent interval must select its ExtGState via gs");
  require(bytes.find("/ExtGState <<") != std::string::npos,
          "the page Resources must name its ExtGState objects");
  require(bytes.find("/Type /ExtGState /ca ") != std::string::npos,
          "a /ca ExtGState object must be embedded");
  // The alpha (180/255 ≈ 0.706) must round-trip in the ExtGState object.
  require(bytes.find("0.705882352941176") != std::string::npos,
          "the alpha value (180/255) must be recorded in the ExtGState object");
}

// Identical scene + snapshot must produce byte-identical output (no timestamps).
void output_is_byte_deterministic() {
  const auto first = std::string{build_scene_document().bytes()};
  const auto second = std::string{build_scene_document().bytes()};
  require(first == second,
          "two builds of the same scene must be byte-identical");
  require(first.find("CreationDate") == std::string::npos,
          "no CreationDate may appear");
  require(first.find("ModDate") == std::string::npos,
          "no ModDate may appear");
}

// Text is emitted as vector outlines, not as a font-backed text operator: the
// content stream contains NO PDF text-show operators (Tf/TJ/Tj) and no font
// resource is embedded (no /Font in Resources) — text is graphical (criterion 5).
void text_is_vector_outlines_not_font_backed() {
  const auto doc = build_scene_document();
  const auto bytes = std::string{doc.bytes()};
  // No text-show operators in the content stream.
  const auto inflated = inflate_content_stream(bytes);
  require(inflated.find("Tf\n") == std::string::npos,
          "stream must not select a font (text is outlines)");
  require(inflated.find("Tj\n") == std::string::npos,
          "stream must not show text (text is outlines)");
  // No font program embedded in the document resources.
  require(bytes.find("/Font") == std::string::npos,
          "no /Font resource may be embedded");
  require(bytes.find("/Type /Font") == std::string::npos,
          "no font object may be embedded");
}

} // namespace

int main() {
  pdf_is_structurally_complete();
  external_tools_accept_the_pdf();
  content_stream_contains_vector_primitives();
  content_stream_has_no_rasterisation();
  vertical_text_uses_per_glyph_rotation();
  semi_transparent_fill_uses_extgstate();
  output_is_byte_deterministic();
  text_is_vector_outlines_not_font_backed();
  std::cout << "welllog.pdf-scene: all cases passed\n";
  return EXIT_SUCCESS;
}
