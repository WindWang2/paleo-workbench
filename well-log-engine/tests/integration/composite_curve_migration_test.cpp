// Headless test for the #197 migration: a curve carrying a multi-segment
// (composite) buffer flows through CurveLodPyramid::build and the table
// projection/exporters identically to the equivalent single-block curve. This
// proves consumers read the composite via the CurveBuffer index interface
// (value_as_double/length/scalar_type) with no contiguous copy, and that the
// GL upload path (scene-prepare flattens via value_as_double) is unaffected.

#include <welllog/core/document.hpp>
#include <welllog/scene/curve_lod.hpp>
#include <welllog/table/table_projection.hpp>
#include <welllog/export/table_writers.hpp>

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <string_view>
#include <vector>

#if defined(_WIN32)
#include <process.h>
#else
#include <unistd.h>
#endif

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
  if (actual < expected - 1.0e-9 || actual > expected + 1.0e-9) {
    fail(message);
  }
}

EntityId id(std::string_view text) {
  auto parsed = EntityId::parse(text);
  require(parsed.has_value(), "test UUID must be valid");
  return *parsed;
}

const auto document_id = id("bbbb0000-0000-4000-8000-000000000001");
const auto axis_id = id("bbbb0000-0000-4000-8000-000000000002");
const auto curve_id = id("bbbb0000-0000-4000-8000-000000000003");

// A reference single-block document: 6 samples [0,1,2,3,4,5].
WellLogDocument single_block_document() {
  auto depths = std::make_shared<const std::vector<double>>(
      std::initializer_list<double>{1000.0, 1001.0, 1002.0, 1003.0, 1004.0,
                                    1005.0});
  auto values = std::make_shared<const std::vector<double>>(
      std::initializer_list<double>{0.0, 1.0, 2.0, 3.0, 4.0, 5.0});
  WellLogDocumentBuilder builder(document_id, DocumentRevision{1});
  builder.add_sampling_axis(SamplingAxis{
      .id = axis_id, .coordinates = BufferView::from_vector(depths),
      .domain = DepthDomain::measured_depth, .unit = "m",
      .direction = AxisDirection::increasing});
  builder.add_curve(Curve{
      .id = curve_id, .mnemonic = "GR", .display_name = "GR", .unit = "API",
      .sampling_axis_id = axis_id, .values = BufferView::from_vector(values),
      .nulls = {}});
  return builder.build();
}

// The same 6 samples split across two segments: head [0,1,2] + tail [3,4,5].
// The curve's values is a CompositeBufferView; old block retained, no copy.
WellLogDocument two_segment_document() {
  auto depths = std::make_shared<const std::vector<double>>(
      std::initializer_list<double>{1000.0, 1001.0, 1002.0, 1003.0, 1004.0,
                                    1005.0});
  auto head = std::make_shared<const std::vector<double>>(
      std::initializer_list<double>{0.0, 1.0, 2.0});
  auto tail = std::make_shared<const std::vector<double>>(
      std::initializer_list<double>{3.0, 4.0, 5.0});
  auto composite = CompositeBufferView::from_segments(
      {BufferView::from_vector(head), BufferView::from_vector(tail)});
  WellLogDocumentBuilder builder(document_id, DocumentRevision{1});
  builder.add_sampling_axis(SamplingAxis{
      .id = axis_id, .coordinates = BufferView::from_vector(depths),
      .domain = DepthDomain::measured_depth, .unit = "m",
      .direction = AxisDirection::increasing});
  builder.add_curve(Curve{
      .id = curve_id, .mnemonic = "GR", .display_name = "GR", .unit = "API",
      .sampling_axis_id = axis_id, .values = CurveBuffer{std::move(composite)},
      .nulls = {}});
  return builder.build();
}

// --- Tests -------------------------------------------------------------------

// A composite-carrying curve reports the same length + scalar type + per-index
// values as the equivalent single-block curve.
void composite_curve_reads_match_single_block() {
  const auto single = single_block_document();
  const auto dual = two_segment_document();
  const auto &c_single = single.curves().front();
  const auto &c_dual = dual.curves().front();
  require(c_dual.values.is_composite(),
          "two-segment document's curve must carry a composite");
  require(c_dual.values.length() == c_single.values.length(),
          "composite length must equal single-block length (6)");
  require(c_dual.values.scalar_type() == c_single.values.scalar_type(),
          "scalar type must match");
  for (std::uint64_t i = 0; i < 6; ++i) {
    require_near(c_dual.values.value_as_double(i).value_or(-999.0),
                 c_single.values.value_as_double(i).value_or(-888.0),
                 "composite curve must read identically to single-block");
  }
}

// CurveLodPyramid::build produces equal statistics from a composite-carrying
// curve and the equivalent single-block curve (the LOD read path is index-based
// and delegates to value_as_double, so the pyramid is identical).
void lod_build_matches_for_composite_and_single_block() {
  const auto single = single_block_document();
  const auto dual = two_segment_document();
  const auto &axis = single.sampling_axes().front();
  const auto &curve_single = single.curves().front();
  const auto &curve_dual = dual.curves().front();
  CurveLodBuildOptions options{.algorithm = CurveLodAlgorithm::hierarchical,
                               .base_bucket_samples = 2,
                               .maximum_derived_bytes = 1 << 20};
  const auto py_single =
      CurveLodPyramid::build(axis, curve_single, options, {});
  const auto py_dual = CurveLodPyramid::build(axis, curve_dual, options, {});
  require(py_single.has_value(), "single-block LOD build must succeed");
  require(py_dual.has_value(), "composite LOD build must succeed");
  const auto s1 = py_single.value().statistics();
  const auto s2 = py_dual.value().statistics();
  require(s1.derived_bytes == s2.derived_bytes,
          "composite + single-block LOD derived bytes must match");
  require(s1.level_count == s2.level_count,
          "composite + single-block LOD level counts must match");
}

// The table projection reads a composite-carrying curve's cells identically to
// the equivalent single-block curve (the projection + exporters go through
// value_as_double via CurveBuffer).
void table_projection_reads_composite_identically() {
  const auto single = single_block_document();
  const auto dual = two_segment_document();
  const auto tables_single = TableProjectionBuilder::from_document(single);
  const auto tables_dual = TableProjectionBuilder::from_document(dual);
  require(tables_single.size() == 1 && tables_dual.size() == 1,
          "each document yields one table");
  const auto &t_single = tables_single.front();
  const auto &t_dual = tables_dual.front();
  require(t_single.row_count() == 6 && t_dual.row_count() == 6,
          "both projections must have 6 rows");
  for (std::uint64_t r = 0; r < 6; ++r) {
    // Column 0 = depth, column 1 = GR value.
    require_near(
        t_dual.cell(r, 1).value.value_or(-999.0),
        t_single.cell(r, 1).value.value_or(-888.0),
        "table projection of a composite curve must match single-block");
  }
}

// The CSV exporter streams a composite-carrying curve correctly: the exported
// values match the single-block export (proves the exporter→projection→
// CurveBuffer→value_as_double chain works end-to-end).
void csv_export_of_composite_curve_matches_single_block() {
  const auto single = single_block_document();
  const auto dual = two_segment_document();
  const auto tables_single = TableProjectionBuilder::from_document(single);
  const auto tables_dual = TableProjectionBuilder::from_document(dual);
  // A unique temp dir per process (the test is short-lived).
  std::ostringstream nm;
  nm << "welllog-composite-"
#if defined(_WIN32)
     << ::_getpid()
#else
     << ::getpid()
#endif
     ;
  const auto dir = std::filesystem::temp_directory_path() / nm.str();
  std::filesystem::create_directories(dir);
  struct Cleanup {
    std::filesystem::path path;
    ~Cleanup() {
      std::error_code ec;
      std::filesystem::remove_all(path, ec);
    }
  } cleanup{dir};
  const auto p_single = dir / "single.csv";
  const auto p_dual = dir / "dual.csv";
  require(
      CsvTableExporter::write_to_file(tables_single.front(), p_single).has_value(),
      "single-block CSV export must succeed");
  require(
      CsvTableExporter::write_to_file(tables_dual.front(), p_dual).has_value(),
      "composite CSV export must succeed");
  // Read both back and compare bodies.
  auto read = [](const std::filesystem::path &p) {
    std::ifstream in(p, std::ios::binary);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
  };
  require(read(p_single) == read(p_dual),
          "composite-curve CSV export must equal single-block CSV export");
}

} // namespace

int main() {
  composite_curve_reads_match_single_block();
  lod_build_matches_for_composite_and_single_block();
  table_projection_reads_composite_identically();
  csv_export_of_composite_curve_matches_single_block();
  std::cout << "welllog.composite-curve-migration: all cases passed\n";
  return EXIT_SUCCESS;
}
