#include <welllog/session/session.hpp>

#include "scene/prepare.hpp"

#include <welllog/core/utf8.hpp>
#include <welllog/scene/curve_lod.hpp>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <memory>
#include <mutex>
#include <thread>
#include <type_traits>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace welllog {
namespace {

constexpr std::uint32_t default_frame_pixel_height = 2160;

[[nodiscard]] Result<std::uint64_t> required_bytes(const BufferView &buffer) {
  if (!buffer.has_owner()) {
    return Error{
        .code = ErrorCode::missing_owner,
        .entity_id = std::nullopt,
        .message = MessageKey::buffer_owner_required,
        .arguments = {},
    };
  }
  if (buffer.length() == 0 || buffer.data() == nullptr) {
    return Error{
        .code = ErrorCode::invalid_buffer,
        .entity_id = std::nullopt,
        .message = MessageKey::buffer_data_required,
        .arguments = {},
    };
  }
  const auto element_size = scalar_size_bytes(buffer.scalar_type());
  if (buffer.stride_bytes() < element_size) {
    return Error{
        .code = ErrorCode::invalid_buffer,
        .entity_id = std::nullopt,
        .message = MessageKey::buffer_stride_too_small,
        .arguments = {},
    };
  }
  const auto steps = buffer.length() - 1;
  if (steps > (std::numeric_limits<std::uint64_t>::max() - element_size) /
                  buffer.stride_bytes()) {
    return Error{
        .code = ErrorCode::arithmetic_overflow,
        .entity_id = std::nullopt,
        .message = MessageKey::buffer_extent_overflow,
        .arguments = {},
    };
  }
  const auto required = steps * buffer.stride_bytes() + element_size;
  if (required > buffer.byte_capacity()) {
    return Error{
        .code = ErrorCode::invalid_buffer,
        .entity_id = std::nullopt,
        .message = MessageKey::buffer_extent_exceeds_capacity,
        .arguments = {},
    };
  }
  return required;
}

// CurveBuffer overload (#197): sums the required bytes across the single
// block or each composite segment. Each segment is validated independently.
[[nodiscard]] Result<std::uint64_t>
required_bytes(const CurveBuffer &buffer) {
  if (buffer.is_composite()) {
    std::uint64_t total = 0;
    for (const auto &segment : buffer.segments()) {
      const auto r = required_bytes(segment);
      if (!r) {
        return r.error();
      }
      total += r.value();
    }
    return total;
  }
  return required_bytes(buffer.as_single());
}

[[nodiscard]] std::optional<Error>
validate_null_bitmap(const NullBitmapView &nulls,
                     std::uint64_t expected_length) {
  if (nulls.empty()) {
    return std::nullopt;
  }
  if (!nulls.has_owner()) {
    return Error{
        .code = ErrorCode::missing_owner,
        .entity_id = std::nullopt,
        .message = MessageKey::null_bitmap_owner_required,
        .arguments = {},
    };
  }
  if (nulls.data() == nullptr || nulls.bit_length() < expected_length) {
    return Error{
        .code = ErrorCode::invalid_buffer,
        .entity_id = std::nullopt,
        .message = MessageKey::null_bitmap_too_short,
        .arguments = {},
    };
  }
  if (nulls.bit_length() >
      std::numeric_limits<std::uint64_t>::max() - std::uint64_t{7}) {
    return Error{
        .code = ErrorCode::arithmetic_overflow,
        .entity_id = std::nullopt,
        .message = MessageKey::null_bitmap_extent_overflow,
        .arguments = {},
    };
  }
  if ((nulls.bit_length() + 7) / 8 > nulls.byte_capacity()) {
    return Error{
        .code = ErrorCode::invalid_buffer,
        .entity_id = std::nullopt,
        .message = MessageKey::null_bitmap_extent_exceeds_capacity,
        .arguments = {},
    };
  }
  return std::nullopt;
}

// Reads element `index` from a single-block or composite curve buffer. Returns
// NaN for an out-of-range/null cell, matching the non-finite → missing-sample
// semantics used by the missing-sample scan and the selection row mappers.
[[nodiscard]] double load_as_double(const CurveBuffer &buffer,
                                    std::uint64_t index) noexcept {
  const auto v = buffer.value_as_double(index);
  return v.value_or(std::numeric_limits<double>::quiet_NaN());
}

// Type-exact monotone check on a single contiguous coordinate block. Compares
// the raw scalar values (not doubles) so an integer axis whose values differ
// only outside double precision is still checked exactly — e.g. uint64 values
// 2^53+1 and 2^53 are distinct integers but equal as doubles; the double path
// would hide that disorder (regression-tested in session_submission_test).
template <typename T>
[[nodiscard]] bool axis_is_ordered(const BufferView &coordinates,
                                   AxisDirection direction) noexcept {
  T previous{};
  std::memcpy(&previous, coordinates.data(), sizeof(T));
  if constexpr (std::is_floating_point_v<T>) {
    if (!std::isfinite(previous)) {
      return false;
    }
  }

  for (std::uint64_t index = 1; index < coordinates.length(); ++index) {
    T current{};
    std::memcpy(&current,
                coordinates.data() + index * coordinates.stride_bytes(),
                sizeof(T));
    if constexpr (std::is_floating_point_v<T>) {
      if (!std::isfinite(current)) {
        return false;
      }
    }
    const auto ordered = direction == AxisDirection::increasing
                             ? current >= previous
                             : current <= previous;
    if (!ordered) {
      return false;
    }
    previous = current;
  }
  return true;
}

// Checks the axis coordinates are monotone in the declared direction. A
// single-block axis (the common case) is checked type-exactly via the template
// above so integer precision is preserved. A composite (multi-segment) axis —
// the append case (#198) — is checked by walking the concatenation through
// `value_as_double`: coordinates are overwhelmingly floating-point, and the
// append's own validation guarantees tail continuity against the existing
// direction, so double precision across the segment boundary is acceptable.
[[nodiscard]] bool axis_is_ordered(const SamplingAxis &axis) noexcept {
  const auto &coordinates = axis.coordinates;
  if (coordinates.is_composite()) {
    const auto length = coordinates.length();
    if (length == 0) {
      return false;
    }
    auto previous = coordinates.value_as_double(0);
    if (!previous.has_value() || !std::isfinite(*previous)) {
      return false;
    }
    for (std::uint64_t index = 1; index < length; ++index) {
      const auto current = coordinates.value_as_double(index);
      if (!current.has_value() || !std::isfinite(*current)) {
        return false;
      }
      const auto ordered = axis.direction == AxisDirection::increasing
                               ? *current >= *previous
                               : *current <= *previous;
      if (!ordered) {
        return false;
      }
      previous = current;
    }
    return true;
  }
  const auto &block = coordinates.as_single();
  switch (block.scalar_type()) {
  case ScalarType::float32:
    return axis_is_ordered<float>(block, axis.direction);
  case ScalarType::float64:
    return axis_is_ordered<double>(block, axis.direction);
  case ScalarType::int16:
    return axis_is_ordered<std::int16_t>(block, axis.direction);
  case ScalarType::int32:
    return axis_is_ordered<std::int32_t>(block, axis.direction);
  case ScalarType::int64:
    return axis_is_ordered<std::int64_t>(block, axis.direction);
  case ScalarType::uint8:
    return axis_is_ordered<std::uint8_t>(block, axis.direction);
  case ScalarType::uint16:
    return axis_is_ordered<std::uint16_t>(block, axis.direction);
  case ScalarType::uint32:
    return axis_is_ordered<std::uint32_t>(block, axis.direction);
  case ScalarType::uint64:
    return axis_is_ordered<std::uint64_t>(block, axis.direction);
  }
  return false;
}

[[nodiscard]] std::optional<Error>
validate_document(const WellLogDocument &document) {
  if (document.id().is_nil() || document.revision().value == 0 ||
      document.sampling_axes().empty() || document.curves().empty()) {
    return Error{
        .code = ErrorCode::invalid_document,
        .entity_id = document.id(),
        .message = MessageKey::document_structure_invalid,
        .arguments = {},
    };
  }

  std::unordered_set<EntityId, EntityIdHash> ids;
  ids.insert(document.id());
  std::unordered_map<EntityId, const SamplingAxis *, EntityIdHash> axes;
  for (const auto &axis : document.sampling_axes()) {
    if (axis.id.is_nil() || !ids.insert(axis.id).second) {
      return Error{
          .code = ErrorCode::duplicate_entity_id,
          .entity_id = axis.id,
          .message = MessageKey::entity_identity_duplicated,
          .arguments = {},
      };
    }
    if (auto result = required_bytes(axis.coordinates); !result) {
      auto error = result.error();
      error.entity_id = axis.id;
      return error;
    }
    if (!axis_is_ordered(axis)) {
      return Error{
          .code = ErrorCode::invalid_sampling_axis,
          .entity_id = axis.id,
          .message = MessageKey::sampling_axis_direction_invalid,
          .arguments = {},
      };
    }
    axes.emplace(axis.id, &axis);
  }

  for (const auto &curve : document.curves()) {
    if (curve.id.is_nil() || !ids.insert(curve.id).second) {
      return Error{
          .code = ErrorCode::duplicate_entity_id,
          .entity_id = curve.id,
          .message = MessageKey::entity_identity_duplicated,
          .arguments = {},
      };
    }
    if (auto result = required_bytes(curve.values); !result) {
      auto error = result.error();
      error.entity_id = curve.id;
      return error;
    }
    const auto axis = axes.find(curve.sampling_axis_id);
    if (axis == axes.end()) {
      return Error{
          .code = ErrorCode::missing_sampling_axis,
          .entity_id = curve.id,
          .message = MessageKey::sampling_axis_missing,
          .arguments = {},
      };
    }
    if (curve.values.length() != axis->second->coordinates.length()) {
      return Error{
          .code = ErrorCode::length_mismatch,
          .entity_id = curve.id,
          .message = MessageKey::curve_length_mismatch,
          .arguments = {},
      };
    }
    if (auto error = validate_null_bitmap(curve.nulls, curve.values.length())) {
      error->entity_id = curve.id;
      return error;
    }
  }

  const auto encoding_error = [](EntityId entity_id) {
    return Error{
        .code = ErrorCode::invalid_document,
        .entity_id = entity_id,
        .message = MessageKey::text_encoding_invalid,
        .arguments = {},
    };
  };

  for (const auto &interval : document.intervals()) {
    if (interval.id.is_nil() || !ids.insert(interval.id).second) {
      return Error{
          .code = ErrorCode::duplicate_entity_id,
          .entity_id = interval.id,
          .message = MessageKey::entity_identity_duplicated,
          .arguments = {},
      };
    }
    if (!std::isfinite(interval.top_reference_depth) ||
        !std::isfinite(interval.bottom_reference_depth) ||
        interval.top_reference_depth >= interval.bottom_reference_depth) {
      return Error{
          .code = ErrorCode::invalid_document,
          .entity_id = interval.id,
          .message = MessageKey::interval_depth_order_invalid,
          .arguments = {},
      };
    }
    if (!is_valid_utf8(interval.label)) {
      return encoding_error(interval.id);
    }
  }

  for (const auto &marker : document.markers()) {
    if (marker.id.is_nil() || !ids.insert(marker.id).second) {
      return Error{
          .code = ErrorCode::duplicate_entity_id,
          .entity_id = marker.id,
          .message = MessageKey::entity_identity_duplicated,
          .arguments = {},
      };
    }
    if (!std::isfinite(marker.reference_depth)) {
      return Error{
          .code = ErrorCode::invalid_document,
          .entity_id = marker.id,
          .message = MessageKey::document_structure_invalid,
          .arguments = {},
      };
    }
    if (!is_valid_utf8(marker.label)) {
      return encoding_error(marker.id);
    }
  }

  for (const auto &symbol : document.symbols()) {
    if (symbol.id.is_nil() || !ids.insert(symbol.id).second) {
      return Error{
          .code = ErrorCode::duplicate_entity_id,
          .entity_id = symbol.id,
          .message = MessageKey::entity_identity_duplicated,
          .arguments = {},
      };
    }
    if (!std::isfinite(symbol.reference_depth) ||
        !std::isfinite(symbol.track_fraction) ||
        symbol.track_fraction < 0.0 || symbol.track_fraction > 1.0) {
      return Error{
          .code = ErrorCode::invalid_document,
          .entity_id = symbol.id,
          .message = MessageKey::document_structure_invalid,
          .arguments = {},
      };
    }
    if (!is_valid_utf8(symbol.label)) {
      return encoding_error(symbol.id);
    }
  }

  for (const auto &annotation : document.annotations()) {
    if (annotation.id.is_nil() || !ids.insert(annotation.id).second) {
      return Error{
          .code = ErrorCode::duplicate_entity_id,
          .entity_id = annotation.id,
          .message = MessageKey::entity_identity_duplicated,
          .arguments = {},
      };
    }
    const auto valid_fraction = [](double fraction) {
      return std::isfinite(fraction) && fraction >= 0.0 && fraction <= 1.0;
    };
    bool anchor_valid = false;
    switch (annotation.anchor) {
    case AnnotationAnchor::reference_depth:
      anchor_valid = std::isfinite(annotation.reference_depth) &&
                     valid_fraction(annotation.track_fraction);
      break;
    case AnnotationAnchor::track:
      anchor_valid = !annotation.track_id.is_nil() &&
                     valid_fraction(annotation.depth_fraction) &&
                     valid_fraction(annotation.horizontal_fraction);
      break;
    case AnnotationAnchor::scene_point:
      anchor_valid = std::isfinite(annotation.scene_point.left.value) &&
                     std::isfinite(annotation.scene_point.top.value);
      break;
    }
    if (!anchor_valid || !std::isfinite(annotation.rotation_degrees) ||
        !std::isfinite(annotation.font_size.value) ||
        annotation.font_size.value <= 0.0 || annotation.text.empty()) {
      return Error{
          .code = ErrorCode::invalid_document,
          .entity_id = annotation.id,
          .message = MessageKey::annotation_anchor_invalid,
          .arguments = {},
      };
    }
    if (!is_valid_utf8(annotation.text)) {
      return encoding_error(annotation.id);
    }
  }
  return std::nullopt;
}

[[nodiscard]] std::uint64_t missing_sample_count(const Curve &curve) noexcept {
  std::uint64_t count{};
  for (std::uint64_t index = 0; index < curve.values.length(); ++index) {
    if ((!curve.nulls.empty() && curve.nulls.is_null(index)) ||
        !std::isfinite(load_as_double(curve.values, index))) {
      ++count;
    }
  }
  return count;
}

[[nodiscard]] Error viewport_error(EntityId document_id) {
  return Error{
      .code = ErrorCode::invalid_viewport,
      .severity = Severity::error,
      .entity_id = document_id,
      .message = MessageKey::viewport_invalid,
      .arguments = {},
  };
}

[[nodiscard]] bool valid_viewport(DepthViewport viewport) noexcept {
  return std::isfinite(viewport.top) && std::isfinite(viewport.bottom) &&
         viewport.top < viewport.bottom &&
         std::isfinite(viewport.bottom - viewport.top);
}

[[nodiscard]] bool valid_crosshair(CrosshairState crosshair) noexcept {
  return std::isfinite(crosshair.track_fraction) &&
         crosshair.track_fraction >= 0.0 && crosshair.track_fraction <= 1.0 &&
         std::isfinite(crosshair.display_depth);
}

[[nodiscard]] bool valid_selection_range(SelectionDepthRange range) noexcept {
  return std::isfinite(range.top) && std::isfinite(range.bottom) &&
         range.top <= range.bottom;
}

// Lower/upper bound of a Reference Depth Range in axis index space. A selection
// range maps to a half-open `[first_row, last_row)` span of axis rows. For an
// increasing axis, `top` (smaller depth) is the lower index; for a decreasing
// axis it is the higher index. The mapping is index-projection: it reads the
// raw axis coordinates (no LOD, no interpolation) and clamps to the axis length.

// Finds the first index whose coordinate is >= `depth` (increasing axis) or <=
// `depth` (decreasing axis). Returns `length` when `depth` is beyond the last
// coordinate. Used for the selection's `first_row`.
[[nodiscard]] std::uint64_t
first_row_at_depth(const CurveBuffer &coordinates, AxisDirection direction,
                   double depth) noexcept {
  const auto length = coordinates.length();
  if (length == 0) {
    return 0;
  }
  if (direction == AxisDirection::increasing) {
    for (std::uint64_t i = 0; i < length; ++i) {
      if (load_as_double(coordinates, i) >= depth) {
        return i;
      }
    }
    return length;
  }
  for (std::uint64_t i = 0; i < length; ++i) {
    if (load_as_double(coordinates, i) <= depth) {
      return i;
    }
  }
  return length;
}

// Finds the first index whose coordinate is > `depth` (increasing axis) or <
// `depth` (decreasing axis). Returns `length` when `depth` is at/ beyond the
// last coordinate. Used for the selection's exclusive `last_row`.
[[nodiscard]] std::uint64_t
last_row_after_depth(const CurveBuffer &coordinates, AxisDirection direction,
                     double depth) noexcept {
  const auto length = coordinates.length();
  if (length == 0) {
    return 0;
  }
  if (direction == AxisDirection::increasing) {
    for (std::uint64_t i = 0; i < length; ++i) {
      if (load_as_double(coordinates, i) > depth) {
        return i;
      }
    }
    return length;
  }
  for (std::uint64_t i = 0; i < length; ++i) {
    if (load_as_double(coordinates, i) < depth) {
      return i;
    }
  }
  return length;
}

// Resolves a SelectionDepthRange on an axis to a half-open `[first, last)` row
// span. The span is clamped to `[0, length]`; an empty/wholely-out-of-range
// selection yields `first == last` (zero rows). `increasing` axis: top is the
// lower index, bottom the upper; `decreasing`: inverted.
struct RowSpan {
  std::uint64_t first{};
  std::uint64_t last{};
};
[[nodiscard]] RowSpan rows_for_range(const CurveBuffer &coordinates,
                                     AxisDirection direction,
                                     SelectionDepthRange range) noexcept {
  const auto length = coordinates.length();
  if (length == 0) {
    return {0, 0};
  }
  if (direction == AxisDirection::increasing) {
    const auto first = first_row_at_depth(coordinates, direction, range.top);
    const auto last = last_row_after_depth(coordinates, direction, range.bottom);
    return {first, std::max(first, last)};
  }
  const auto first = first_row_at_depth(coordinates, direction, range.bottom);
  const auto last = last_row_after_depth(coordinates, direction, range.top);
  return {first, std::max(first, last)};
}

// Resolves a half-open row span to the Reference Depth Range it covers by
// reading the raw axis coordinate at the boundary rows (no LOD). Direction is
// immaterial here — the range is min/max of the two boundary coordinates, so a
// decreasing axis produces the same `[top, bottom]` as an increasing one. A
// zero-length span (`first == last`) yields the coordinate at `first` for both
// ends.
[[nodiscard]] SelectionDepthRange
range_for_rows(const CurveBuffer &coordinates, std::uint64_t first_row,
               std::uint64_t last_row) noexcept {
  const auto length = coordinates.length();
  const auto clamped_first =
      first_row >= length ? (length == 0 ? 0 : length - 1) : first_row;
  const auto clamped_last_idx =
      last_row == 0 ? 0 : (last_row - 1 >= length ? length - 1 : last_row - 1);
  if (length == 0) {
    return {};
  }
  const auto a = load_as_double(coordinates, clamped_first);
  const auto b = load_as_double(coordinates, clamped_last_idx);
  return {.top = std::min(a, b), .bottom = std::max(a, b)};
}

// Locates a Sampling Axis on a document by id; returns nullptr when absent.
[[nodiscard]] const SamplingAxis *
find_axis(const WellLogDocument &document, EntityId axis_id) noexcept {
  for (const auto &axis : document.sampling_axes()) {
    if (axis.id == axis_id) {
      return &axis;
    }
  }
  return nullptr;
}

// Selection-failure error builders. Each maps to the SAME code/message the
// document/viewport paths already use for that failure mode, so a caller can
// distinguish an unknown document from an unknown axis from a bad range — the
// single invalid_viewport used before was a Mysterious Name that hid the cause
// (architecture.md §2 Result/Error model; quality-security-performance.md §7
// "稳定码").
[[nodiscard]] Error selection_document_missing(EntityId document_id) {
  return Error{
      .code = ErrorCode::document_not_found,
      .severity = Severity::error,
      .entity_id = document_id,
      .message = MessageKey::presentation_document_missing,
      .arguments = {},
  };
}

[[nodiscard]] Error selection_axis_missing(EntityId axis_id) {
  return Error{
      .code = ErrorCode::missing_sampling_axis,
      .severity = Severity::error,
      .entity_id = axis_id,
      .message = MessageKey::sampling_axis_missing,
      .arguments = {},
  };
}

// A bad range/span value or a version overflow — the existing viewport pair is
// the closest "invalid value" code; the session has no selection-specific code.
[[nodiscard]] Error selection_invalid(EntityId document_id) {
  return Error{
      .code = ErrorCode::invalid_viewport,
      .severity = Severity::error,
      .entity_id = document_id,
      .message = MessageKey::viewport_invalid,
      .arguments = {},
  };
}

struct LodBuildOutput {
  bool cancelled{};
  std::optional<Error> error;
  std::uint64_t derived_bytes{};
  std::unordered_map<EntityId, CurveLodPyramid, EntityIdHash> pyramids;
  // Image pyramids built from ImageSource entities (#184). metadata-only
  // (no pixel decode — ADR 0045); a missing/empty map means image layers
  // produce no tiles (non-fatal degradation).
  detail::ScenePreparer::ImagePyramidMap image_pyramids;
  std::uint64_t image_derived_bytes{};
  // ImageSource ids whose pyramid build failed (non-cancelled) and were
  // skipped. poll_async publishes a Diagnostic per id (qsp §7: degradation
  // must be observable), then degrades — the scene emits no layer for them.
  std::vector<EntityId> skipped_images;
};

struct LodTaskState {
  std::mutex mutex;
  bool finished{};
  LodBuildOutput output;
};

struct LodTask {
  EntityId document_id;
  DocumentRevision revision;
  std::uint64_t generation{};
  std::shared_ptr<LodTaskState> state;
  std::jthread worker;
};

struct FrameBuildOutput {
  bool cancelled{};
  std::optional<Error> error;
  std::shared_ptr<const PreparedScene> scene;
};

struct FrameTaskState {
  std::mutex mutex;
  bool finished{};
  FrameBuildOutput output;
};

struct FrameTask {
  EntityId document_id;
  DocumentRevision revision;
  std::uint64_t generation{};
  std::shared_ptr<FrameTaskState> state;
  std::jthread worker;
};

[[nodiscard]] std::unique_ptr<FrameTask> make_frame_task(
    EntityId document_id, DocumentRevision revision, std::uint64_t generation,
    std::shared_ptr<const WellLogDocument> document,
    ScenePresentation presentation,
    std::shared_ptr<const detail::ScenePreparer::CurveLodMap> pyramids,
    CurveLodQuery query,
    std::shared_ptr<const detail::ScenePreparer::ImagePyramidMap> image_pyramids,
    ImagePyramidQuery image_query, std::shared_ptr<TextEngine> text_engine,
    std::mutex *text_engine_mutex) {
  auto state = std::make_shared<FrameTaskState>();
  auto task = std::make_unique<FrameTask>();
  task->document_id = document_id;
  task->revision = revision;
  task->generation = generation;
  task->state = state;
  task->worker = std::jthread(
      [document = std::move(document), presentation = std::move(presentation),
       pyramids = std::move(pyramids), query,
       image_pyramids = std::move(image_pyramids), image_query,
       text_engine = std::move(text_engine), text_engine_mutex,
       state = std::move(state)](std::stop_token stop_token) {
        auto output = FrameBuildOutput{};
        if (stop_token.stop_requested()) {
          output.cancelled = true;
        } else {
          try {
            Result<PreparedScene> prepared = Error{
                .code = ErrorCode::internal_error,
                .severity = Severity::error,
                .entity_id = std::nullopt,
                .message = MessageKey::internal_error,
                .arguments = {},
            };
            {
              // Text engines are single-threaded; serialize shaping across
              // concurrent frame preparations.
              const auto text_guard =
                  text_engine == nullptr
                      ? std::unique_lock<std::mutex>{}
                      : std::unique_lock<std::mutex>{*text_engine_mutex};
              prepared = detail::ScenePreparer::prepare(
                  *document, presentation, *pyramids, query,
                  image_pyramids ? *image_pyramids
                                  : detail::ScenePreparer::ImagePyramidMap{},
                  image_query, stop_token, text_engine.get());
            }
            if (stop_token.stop_requested()) {
              output.cancelled = true;
            } else if (prepared.has_value()) {
              output.scene = std::make_shared<const PreparedScene>(
                  std::move(prepared).value());
            } else {
              output.cancelled =
                  prepared.error().code == ErrorCode::operation_cancelled;
              if (!output.cancelled) {
                output.error = prepared.error();
              }
            }
          } catch (const std::bad_alloc &) {
            output.error = Error{
                .code = ErrorCode::resource_exhausted,
                .severity = Severity::error,
                .entity_id = document->id(),
                .message = MessageKey::resource_exhausted,
                .arguments = {},
            };
          } catch (...) {
            output.error = Error{
                .code = ErrorCode::internal_error,
                .severity = Severity::error,
                .entity_id = document->id(),
                .message = MessageKey::internal_error,
                .arguments = {},
            };
          }
        }
        const auto guard = std::lock_guard{state->mutex};
        state->output = std::move(output);
        state->finished = true;
      });
  return task;
}

struct CurvePreparation {
  DocumentRevision revision;
  std::uint64_t generation{};
  PreparationState state{PreparationState::unavailable};
  std::uint64_t derived_bytes{};
  std::uint64_t maximum_derived_bytes{};
  std::shared_ptr<const detail::ScenePreparer::CurveLodMap> pyramids;
  // Image pyramids built alongside the curve LOD (#184); empty when the
  // document has no ImageSource entities.
  std::shared_ptr<const detail::ScenePreparer::ImagePyramidMap> image_pyramids;
};

// The prepared-scene issue enums (ValueIssueCode / TextIssueCode) map 1:1 onto
// the session-domain DiagnosticCode and the error-domain MessageKey. These
// resolvers keep that mapping in one place per family rather than restating it
// inside each publish loop's switch (ADR 0038 domain separation is preserved:
// the enums themselves stay distinct across scene/session/error layers).

struct ValueIssueMapping {
  DiagnosticCode code{DiagnosticCode::nonpositive_log_values};
  MessageKey message{MessageKey::log_scale_values_not_drawn};
};

[[nodiscard]] ValueIssueMapping resolve(ValueIssueCode code) noexcept {
  switch (code) {
  case ValueIssueCode::nonpositive_log_values:
    return {.code = DiagnosticCode::nonpositive_log_values,
            .message = MessageKey::log_scale_values_not_drawn};
  case ValueIssueCode::scale_readability_hint:
    return {.code = DiagnosticCode::scale_readability_hint,
            .message = MessageKey::scale_readability_hint};
  }
  return {};
}

struct TextIssueMapping {
  DiagnosticCode code{DiagnosticCode::missing_glyphs};
  MessageKey message{MessageKey::glyphs_missing_from_fonts};
};

[[nodiscard]] TextIssueMapping resolve(TextIssueCode code) noexcept {
  switch (code) {
  case TextIssueCode::missing_glyphs:
    return {.code = DiagnosticCode::missing_glyphs,
            .message = MessageKey::glyphs_missing_from_fonts};
  case TextIssueCode::fallback_font_used:
    return {.code = DiagnosticCode::fallback_font_used,
            .message = MessageKey::font_fallback_used};
  case TextIssueCode::text_engine_unavailable:
    return {.code = DiagnosticCode::text_engine_unavailable,
            .message = MessageKey::text_engine_unavailable};
  }
  return {};
}

} // namespace

struct WellLogSession::Impl {
  PerformanceBudgets budgets;
  std::uint64_t state_version{};
  std::uint64_t next_diagnostic_id{1};
  std::uint64_t next_lod_generation{1};
  std::uint64_t next_frame_generation{1};
  std::uint64_t completed_lod_tasks{};
  std::uint64_t cancelled_lod_tasks{};
  std::uint64_t discarded_lod_tasks{};
  std::unordered_map<EntityId, std::shared_ptr<const WellLogDocument>,
                     EntityIdHash>
      documents;
  std::unordered_map<EntityId, std::shared_ptr<const PreparedScene>,
                     EntityIdHash>
      prepared_scenes;
  std::unordered_map<EntityId, ScenePresentation, EntityIdHash> presentations;
  std::unordered_map<EntityId, DepthViewport, EntityIdHash> viewports;
  std::unordered_map<EntityId, std::uint32_t, EntityIdHash>
      viewport_pixel_heights;
  std::unordered_map<EntityId, DepthViewport, EntityIdHash> viewport_defaults;
  std::unordered_map<EntityId, CrosshairState, EntityIdHash> crosshairs;
  std::unordered_map<EntityId, SelectionState, EntityIdHash> selections;
  std::unordered_map<EntityId, CurvePreparation, EntityIdHash> preparations;
  std::unordered_map<EntityId, std::uint64_t, EntityIdHash> frame_generations;
  std::vector<std::unique_ptr<LodTask>> lod_tasks;
  std::vector<std::unique_ptr<FrameTask>> frame_tasks;
  std::vector<ViewEvent> events;
  std::vector<Diagnostic> diagnostics;
  std::unordered_map<std::uint64_t, Error> diagnostic_errors;
  std::shared_ptr<TextEngine> text_engine;
  std::mutex text_engine_mutex;
  ViewEventObserverId next_observer_id{1};
  std::unordered_map<ViewEventObserverId, ViewEventObserver> observers;

  void notify_observers(const ViewEvent &event) const noexcept {
    try {
      std::vector<ViewEventObserver> observer_snapshot;
      observer_snapshot.reserve(observers.size());
      for (const auto &[observer_id, observer] : observers) {
        static_cast<void>(observer_id);
        observer_snapshot.push_back(observer);
      }
      for (const auto &observer : observer_snapshot) {
        try {
          observer(event);
        } catch (...) {
        }
      }
    } catch (...) {
    }
  }

  void publish_async_failure(EntityId document_id, DocumentRevision revision,
                             const Error &error,
                             std::vector<ViewEvent> &notifications) {
    if (state_version == std::numeric_limits<std::uint64_t>::max() ||
        next_diagnostic_id == std::numeric_limits<std::uint64_t>::max()) {
      return;
    }
    const auto diagnostic_id = next_diagnostic_id;
    diagnostics.reserve(diagnostics.size() + 1);
    diagnostic_errors.reserve(diagnostic_errors.size() + 1);
    events.reserve(events.size() + 1);
    notifications.reserve(notifications.size() + 1);
    diagnostic_errors.emplace(diagnostic_id, error);
    ++state_version;
    diagnostics.push_back(Diagnostic{
        .id = diagnostic_id,
        .code = DiagnosticCode::asynchronous_preparation_failed,
        .severity = error.severity,
        .document_id = document_id,
        .entity_id = error.entity_id.value_or(document_id),
        .document_revision = revision,
        .occurrence_count = 1,
    });
    ++next_diagnostic_id;
    const auto event = ViewEvent{
        .kind = ViewEventKind::diagnostic_published,
        .state_version = state_version,
        .document_id = document_id,
        .document_revision = revision,
    };
    events.push_back(event);
    notifications.push_back(event);
  }

  // Publishes one diagnostic derived from a prepared-scene issue: reserves
  // space across the four diagnostic sinks, emplaces the error + Diagnostic,
  // bumps the version/next-id, and fans out the ViewEvent to both event
  // sinks. Shared by publish_value_issues and publish_text_issues so the
  // reserve/emplace/push/event sequence lives in one place. Returns the id
  // assigned to the published diagnostic.
  std::uint64_t publish_one_diagnostic(EntityId document_id,
                                       DocumentRevision revision,
                                       EntityId entity_id,
                                       std::uint32_t occurrence_count,
                                       DiagnosticCode code, MessageKey message,
                                       ErrorCode error_code,
                                       std::vector<ViewEvent> &notifications) noexcept {
    const auto diagnostic_id = next_diagnostic_id;
    diagnostics.reserve(diagnostics.size() + 1);
    diagnostic_errors.reserve(diagnostic_errors.size() + 1);
    events.reserve(events.size() + 1);
    notifications.reserve(notifications.size() + 1);
    diagnostic_errors.emplace(
        diagnostic_id,
        Error{
            .code = error_code,
            .severity = Severity::warning,
            .entity_id = entity_id,
            .message = message,
            .arguments = {},
        });
    ++state_version;
    diagnostics.push_back(Diagnostic{
        .id = diagnostic_id,
        .code = code,
        .severity = Severity::warning,
        .document_id = document_id,
        .entity_id = entity_id,
        .document_revision = revision,
        .occurrence_count = occurrence_count,
    });
    ++next_diagnostic_id;
    const auto event = ViewEvent{
        .kind = ViewEventKind::diagnostic_published,
        .state_version = state_version,
        .document_id = document_id,
        .document_revision = revision,
    };
    events.push_back(event);
    notifications.push_back(event);
    return diagnostic_id;
  }

  // Publishes prepared-scene value issues (non-positive log-scale
  // samples, scale readability hints) into the diagnostic stream.
  void publish_value_issues(EntityId document_id, DocumentRevision revision,
                            const PreparedScene &scene,
                            std::vector<ViewEvent> &notifications) noexcept {
    try {
      for (const auto &issue : scene.value_issues()) {
        if (state_version == std::numeric_limits<std::uint64_t>::max() ||
            next_diagnostic_id == std::numeric_limits<std::uint64_t>::max()) {
          break;
        }
        const auto mapping = resolve(issue.code);
        publish_one_diagnostic(document_id, revision, issue.entity_id,
                               issue.occurrence_count, mapping.code,
                               mapping.message, ErrorCode::diagnostic_warning,
                               notifications);
      }
    } catch (...) {
    }
  }

  // Publishes prepared-scene text issues (missing glyphs, fallback fonts,
  // unavailable engines) into the diagnostic stream. Returns the first
  // published diagnostic identity, if any.
  [[nodiscard]] std::optional<std::uint64_t>
  publish_text_issues(EntityId document_id, DocumentRevision revision,
                      const PreparedScene &scene,
                      std::vector<ViewEvent> &notifications) noexcept {
    std::optional<std::uint64_t> first_diagnostic;
    try {
      for (const auto &issue : scene.text_issues()) {
        if (state_version == std::numeric_limits<std::uint64_t>::max() ||
            next_diagnostic_id == std::numeric_limits<std::uint64_t>::max()) {
          break;
        }
        const auto mapping = resolve(issue.code);
        const auto published = publish_one_diagnostic(
            document_id, revision, issue.entity_id, issue.occurrence_count,
            mapping.code, mapping.message, ErrorCode::invalid_font,
            notifications);
        if (!first_diagnostic.has_value()) {
          first_diagnostic = published;
        }
      }
    } catch (...) {
    }
    return first_diagnostic;
  }
};

WellLogSession::WellLogSession() : WellLogSession(PerformanceBudgets{}) {}
WellLogSession::WellLogSession(PerformanceBudgets budgets)
    : impl_(std::make_unique<Impl>()) {
  impl_->budgets = budgets;
}
WellLogSession::~WellLogSession() = default;
WellLogSession::WellLogSession(WellLogSession &&) noexcept = default;
WellLogSession &WellLogSession::operator=(WellLogSession &&) noexcept = default;

void WellLogSession::set_text_engine(
    std::shared_ptr<TextEngine> text_engine) noexcept {
  try {
    const auto guard = std::lock_guard{impl_->text_engine_mutex};
    impl_->text_engine = std::move(text_engine);
  } catch (...) {
  }
}

Result<CommandReceipt> WellLogSession::execute(SetDocumentCommand command) {
  try {
    if (const auto error = validate_document(command.document)) {
      return *error;
    }
    if (impl_->state_version == std::numeric_limits<std::uint64_t>::max()) {
      return Error{
          .code = ErrorCode::internal_error,
          .severity = Severity::error,
          .entity_id = command.document.id(),
          .message = MessageKey::internal_error,
          .arguments = {},
      };
    }

    auto document =
        std::make_shared<const WellLogDocument>(std::move(command.document));
    const auto document_id = document->id();
    const auto revision = document->revision();
    const auto asynchronous =
        std::any_of(document->curves().begin(), document->curves().end(),
                    [&](const Curve &curve) {
                      return curve.values.length() >=
                             impl_->budgets.asynchronous_sample_threshold;
                    });
    if (asynchronous && impl_->next_lod_generation ==
                            std::numeric_limits<std::uint64_t>::max()) {
      return Error{
          .code = ErrorCode::internal_error,
          .severity = Severity::error,
          .entity_id = document_id,
          .message = MessageKey::internal_error,
          .arguments = {},
      };
    }
    const auto generation =
        asynchronous ? impl_->next_lod_generation : std::uint64_t{};
    auto task = std::unique_ptr<LodTask>{};
    auto maximum_derived_bytes = impl_->budgets.maximum_cpu_derived_bytes;
    if (asynchronous) {
      if (maximum_derived_bytes == 0) {
        const auto add_budget = [&](std::uint64_t increment) {
          maximum_derived_bytes =
              increment > std::numeric_limits<std::uint64_t>::max() -
                              maximum_derived_bytes
                  ? std::numeric_limits<std::uint64_t>::max()
                  : maximum_derived_bytes + increment;
        };
        for (const auto &axis : document->sampling_axes()) {
          add_budget(axis.coordinates.length() *
                     scalar_size_bytes(axis.coordinates.scalar_type()) / 4);
        }
        for (const auto &curve : document->curves()) {
          add_budget(curve.values.length() *
                     scalar_size_bytes(curve.values.scalar_type()) / 4);
        }
      }
      auto state = std::make_shared<LodTaskState>();
      task = std::make_unique<LodTask>();
      task->document_id = document_id;
      task->revision = revision;
      task->generation = generation;
      task->state = state;
      const auto curve_count =
          static_cast<std::uint64_t>(document->curves().size());
      const auto per_curve_budget =
          std::max(std::uint64_t{1}, maximum_derived_bytes / curve_count);
      const auto image_pyramid_options = impl_->budgets.image_pyramid_options;
      task->worker = std::jthread([document, state, per_curve_budget,
                                   image_pyramid_options](
                                      std::stop_token stop_token) {
        auto output = LodBuildOutput{};
        try {
          for (const auto &curve : document->curves()) {
            if (stop_token.stop_requested()) {
              output.cancelled = true;
              break;
            }
            const auto axis =
                std::find_if(document->sampling_axes().begin(),
                             document->sampling_axes().end(),
                             [&](const SamplingAxis &candidate) {
                               return candidate.id == curve.sampling_axis_id;
                             });
            if (axis == document->sampling_axes().end()) {
              output.error = Error{
                  .code = ErrorCode::missing_sampling_axis,
                  .severity = Severity::error,
                  .entity_id = curve.id,
                  .message = MessageKey::sampling_axis_missing,
                  .arguments = {},
              };
              break;
            }
            auto pyramid = CurveLodPyramid::build(
                *axis, curve,
                CurveLodBuildOptions{
                    .algorithm = CurveLodAlgorithm::hierarchical,
                    .base_bucket_samples = 16,
                    .maximum_derived_bytes = per_curve_budget,
                },
                stop_token);
            if (!pyramid.has_value()) {
              output.cancelled =
                  pyramid.error().code == ErrorCode::operation_cancelled;
              if (!output.cancelled) {
                output.error = pyramid.error();
              }
              break;
            }
            output.derived_bytes += pyramid.value().statistics().derived_bytes;
            output.pyramids.emplace(curve.id, std::move(pyramid).value());
          }
          // Image pyramids (#184): build the level/tile grid for each
          // ImageSource. metadata-only (no pixel decode — ADR 0045); a build
          // failure degrades (no tiles for that image) rather than failing the
          // whole LOD task, mirroring how the scene tolerates a missing map.
          for (const auto &image : document->image_sources()) {
            if (stop_token.stop_requested()) {
              output.cancelled = true;
              break;
            }
            auto image_pyramid = ImagePyramid::build(image, image_pyramid_options,
                                                    stop_token);
            if (!image_pyramid.has_value()) {
              output.cancelled = image_pyramid.error().code ==
                                 ErrorCode::operation_cancelled;
              if (!output.cancelled) {
                // Non-fatal: record the skipped image so poll_async publishes a
                // Diagnostic (qsp §7: degradation must be observable), then
                // degrade — the scene emits no layer for this source.
                output.skipped_images.push_back(image.id);
                continue;
              }
              break;
            }
            output.image_derived_bytes +=
                image_pyramid.value().statistics().derived_bytes;
            // Fold into the aggregate so the budget envelope (ADR 0034) and
            // performance_snapshot report the total derived bytes (curve +
            // image), not curve-only.
            output.derived_bytes +=
                image_pyramid.value().statistics().derived_bytes;
            output.image_pyramids.emplace(image.id,
                                          std::move(image_pyramid).value());
          }
        } catch (const std::bad_alloc &) {
          output.error = Error{
              .code = ErrorCode::resource_exhausted,
              .severity = Severity::error,
              .entity_id = document->id(),
              .message = MessageKey::resource_exhausted,
              .arguments = {},
          };
        } catch (...) {
          output.error = Error{
              .code = ErrorCode::internal_error,
              .severity = Severity::error,
              .entity_id = document->id(),
              .message = MessageKey::internal_error,
              .arguments = {},
          };
        }
        const auto guard = std::lock_guard{state->mutex};
        state->output = std::move(output);
        state->finished = true;
      });
    }
    const auto next_state_version = impl_->state_version + 1;
    std::vector<ViewEvent> pending_events;
    std::vector<Diagnostic> pending_diagnostics;
    pending_events.reserve(1 + document->curves().size());
    pending_diagnostics.reserve(document->curves().size());
    pending_events.push_back(ViewEvent{
        .kind = ViewEventKind::documents_changed,
        .state_version = next_state_version,
        .document_id = document_id,
        .document_revision = revision,
    });

    std::optional<std::uint64_t> first_diagnostic_id;
    for (const auto &curve : document->curves()) {
      const auto count = missing_sample_count(curve);
      if (count == 0) {
        continue;
      }
      if (impl_->next_diagnostic_id >
          std::numeric_limits<std::uint64_t>::max() -
              pending_diagnostics.size()) {
        return Error{
            .code = ErrorCode::internal_error,
            .severity = Severity::error,
            .entity_id = document_id,
            .message = MessageKey::internal_error,
            .arguments = {},
        };
      }
      const auto new_diagnostic_id =
          impl_->next_diagnostic_id + pending_diagnostics.size();
      if (!first_diagnostic_id.has_value()) {
        first_diagnostic_id = new_diagnostic_id;
      }
      pending_diagnostics.push_back(Diagnostic{
          .id = new_diagnostic_id,
          .code = DiagnosticCode::missing_samples,
          .severity = Severity::warning,
          .document_id = document_id,
          .entity_id = curve.id,
          .document_revision = revision,
          .occurrence_count = count,
      });
      pending_events.push_back(ViewEvent{
          .kind = ViewEventKind::diagnostic_published,
          .state_version = next_state_version,
          .document_id = document_id,
          .document_revision = revision,
      });
    }

    impl_->events.reserve(impl_->events.size() + pending_events.size());
    impl_->diagnostics.reserve(impl_->diagnostics.size() +
                               pending_diagnostics.size());
    if (asynchronous) {
      impl_->preparations.reserve(impl_->preparations.size() + 1);
      impl_->lod_tasks.reserve(impl_->lod_tasks.size() + 1);
    }
    for (auto &existing_task : impl_->lod_tasks) {
      if (existing_task->document_id == document_id) {
        existing_task->worker.request_stop();
      }
    }
    for (auto &existing_task : impl_->frame_tasks) {
      if (existing_task->document_id == document_id) {
        existing_task->worker.request_stop();
      }
    }
    impl_->documents.insert_or_assign(document_id, document);
    impl_->prepared_scenes.erase(document_id);
    impl_->presentations.erase(document_id);
    impl_->viewports.erase(document_id);
    impl_->viewport_pixel_heights.erase(document_id);
    impl_->viewport_defaults.erase(document_id);
    impl_->crosshairs.erase(document_id);
    impl_->frame_generations.erase(document_id);
    // ADR 0024: a document replacement attempts to safely remap an existing
    // selection onto the new revision's axis coordinates. If the selected axis
    // survived and the depth range still falls within the new axis extent, the
    // row span is recomputed against the new revision and the selection stays
    // valid. Otherwise the selection is explicitly invalidated and a
    // selection_invalidated event is published (the host must stop using it).
    // The outcome event folds into the pending events at next_state_version.
    if (const auto sel = impl_->selections.find(document_id);
        sel != impl_->selections.end()) {
      const auto axis = find_axis(*document, sel->second.sampling_axis_id);
      if (axis != nullptr) {
        const auto span = rows_for_range(axis->coordinates, axis->direction,
                                         sel->second.reference_depth_range);
        const auto axis_extent = range_for_rows(
            axis->coordinates, 0, axis->coordinates.length());
        // Keep the selection if it resolves to a non-empty span within the new
        // axis extent; otherwise invalidate.
        const auto within = span.last > span.first &&
                            sel->second.reference_depth_range.top >=
                                axis_extent.top - 1.0e-9 &&
                            sel->second.reference_depth_range.bottom <=
                                axis_extent.bottom + 1.0e-9;
        if (within) {
          sel->second.first_row = span.first;
          sel->second.last_row = span.last;
          sel->second.document_revision = revision;
          sel->second.valid = true;
        } else {
          sel->second.valid = false;
          sel->second.document_revision = revision;
        }
      } else {
        sel->second.valid = false;
        sel->second.document_revision = revision;
      }
      pending_events.push_back(ViewEvent{
          .kind = sel->second.valid ? ViewEventKind::selection_changed
                                    : ViewEventKind::selection_invalidated,
          .state_version = next_state_version,
          .document_id = document_id,
          .document_revision = revision,
      });
    }
    if (asynchronous) {
      impl_->preparations.insert_or_assign(
          document_id, CurvePreparation{
                           .revision = revision,
                           .generation = generation,
                           .state = PreparationState::pending,
                           .derived_bytes = 0,
                           .maximum_derived_bytes = maximum_derived_bytes,
                           .pyramids = {},
                           .image_pyramids = {},
                       });
      impl_->lod_tasks.push_back(std::move(task));
      ++impl_->next_lod_generation;
    } else {
      impl_->preparations.erase(document_id);
    }
    impl_->state_version = next_state_version;
    impl_->next_diagnostic_id += pending_diagnostics.size();
    impl_->events.insert(impl_->events.end(), pending_events.begin(),
                         pending_events.end());
    impl_->diagnostics.insert(impl_->diagnostics.end(),
                              pending_diagnostics.begin(),
                              pending_diagnostics.end());
    for (const auto &event : pending_events) {
      impl_->notify_observers(event);
    }

    return CommandReceipt{
        .state_version = next_state_version,
        .document_id = document_id,
        .document_revision = revision,
        .asynchronous_preparation_started = asynchronous,
        .diagnostic_id = first_diagnostic_id,
    };
  } catch (const std::bad_alloc &) {
    return Error{
        .code = ErrorCode::resource_exhausted,
        .severity = Severity::error,
        .entity_id = std::nullopt,
        .message = MessageKey::resource_exhausted,
        .arguments = {},
    };
  } catch (...) {
    return Error{
        .code = ErrorCode::internal_error,
        .severity = Severity::error,
        .entity_id = std::nullopt,
        .message = MessageKey::internal_error,
        .arguments = {},
    };
  }
}

Result<CommandReceipt>
WellLogSession::execute(const SetPresentationCommand &command) {
  try {
    const auto document_id = command.presentation.document_id();
    const auto document = impl_->documents.find(document_id);
    if (document == impl_->documents.end()) {
      return Error{
          .code = ErrorCode::document_not_found,
          .severity = Severity::error,
          .entity_id = document_id,
          .message = MessageKey::presentation_document_missing,
          .arguments = {},
      };
    }
    if (impl_->state_version == std::numeric_limits<std::uint64_t>::max()) {
      return Error{
          .code = ErrorCode::internal_error,
          .severity = Severity::error,
          .entity_id = document_id,
          .message = MessageKey::internal_error,
          .arguments = {},
      };
    }
    const auto revision = document->second->revision();
    const auto depth_range = command.presentation.reference_depth_range();
    const auto initial_viewport =
        DepthViewport{.top = depth_range.top, .bottom = depth_range.bottom};
    const auto preparation = impl_->preparations.find(document_id);
    if (preparation != impl_->preparations.end()) {
      if (preparation->second.state == PreparationState::unavailable) {
        return Error{
            .code = ErrorCode::internal_error,
            .severity = Severity::error,
            .entity_id = document_id,
            .message = MessageKey::internal_error,
            .arguments = {},
        };
      }
      auto frame_task = std::unique_ptr<FrameTask>{};
      auto frame_generation = std::uint64_t{};
      if (preparation->second.state == PreparationState::ready) {
        if (impl_->next_frame_generation ==
                std::numeric_limits<std::uint64_t>::max() ||
            preparation->second.pyramids == nullptr) {
          return Error{
              .code = ErrorCode::internal_error,
              .severity = Severity::error,
              .entity_id = document_id,
              .message = MessageKey::internal_error,
              .arguments = {},
          };
        }
        frame_generation = impl_->next_frame_generation;
        frame_task = make_frame_task(
            document_id, revision, frame_generation, document->second,
            command.presentation, preparation->second.pyramids,
            CurveLodQuery{
                .viewport_top = initial_viewport.top,
                .viewport_bottom = initial_viewport.bottom,
                .pixel_height = default_frame_pixel_height,
                .prefetch_viewports = impl_->budgets.prefetch_viewports,
            },
            preparation->second.image_pyramids,
            ImagePyramidQuery{
                .viewport_top = initial_viewport.top,
                .viewport_bottom = initial_viewport.bottom,
                .pixel_height = static_cast<double>(default_frame_pixel_height),
                .prefetch_viewports = impl_->budgets.prefetch_viewports,
            },
            impl_->text_engine, &impl_->text_engine_mutex);
      }
      const auto next_state_version = impl_->state_version + 1;
      std::vector<ViewEvent> pending_events{
          ViewEvent{
              .kind = ViewEventKind::presentation_changed,
              .state_version = next_state_version,
              .document_id = document_id,
              .document_revision = revision,
          },
          ViewEvent{
              .kind = ViewEventKind::viewport_changed,
              .state_version = next_state_version,
              .document_id = document_id,
              .document_revision = revision,
          },
      };
      impl_->events.reserve(impl_->events.size() + pending_events.size());
      impl_->presentations.reserve(impl_->presentations.size() + 1);
      impl_->viewports.reserve(impl_->viewports.size() + 1);
      impl_->viewport_pixel_heights.reserve(
          impl_->viewport_pixel_heights.size() + 1);
      impl_->viewport_defaults.reserve(impl_->viewport_defaults.size() + 1);
      if (frame_task != nullptr) {
        impl_->frame_tasks.reserve(impl_->frame_tasks.size() + 1);
        impl_->frame_generations.reserve(impl_->frame_generations.size() + 1);
      }
      for (auto &existing_task : impl_->frame_tasks) {
        if (existing_task->document_id == document_id) {
          existing_task->worker.request_stop();
        }
      }
      if (frame_task != nullptr) {
        impl_->frame_generations.insert_or_assign(document_id,
                                                  frame_generation);
        impl_->frame_tasks.push_back(std::move(frame_task));
        ++impl_->next_frame_generation;
      } else {
        impl_->frame_generations.erase(document_id);
      }
      impl_->presentations.insert_or_assign(document_id, command.presentation);
      impl_->viewports.insert_or_assign(document_id, initial_viewport);
      impl_->viewport_pixel_heights.insert_or_assign(
          document_id, default_frame_pixel_height);
      impl_->viewport_defaults.insert_or_assign(document_id, initial_viewport);
      impl_->crosshairs.erase(document_id);
      impl_->state_version = next_state_version;
      impl_->events.insert(impl_->events.end(), pending_events.begin(),
                           pending_events.end());
      for (const auto &event : pending_events) {
        impl_->notify_observers(event);
      }
      return CommandReceipt{
          .state_version = next_state_version,
          .document_id = document_id,
          .document_revision = revision,
          .asynchronous_preparation_started =
              preparation->second.state == PreparationState::pending ||
              frame_generation != 0,
          .diagnostic_id = std::nullopt,
      };
    }

    Result<PreparedScene> prepared = Error{
        .code = ErrorCode::internal_error,
        .severity = Severity::error,
        .entity_id = std::nullopt,
        .message = MessageKey::internal_error,
        .arguments = {},
    };
    {
      const auto text_guard =
          impl_->text_engine == nullptr
              ? std::unique_lock<std::mutex>{}
              : std::unique_lock<std::mutex>{impl_->text_engine_mutex};
      prepared = detail::ScenePreparer::prepare(*document->second,
                                                command.presentation,
                                                impl_->text_engine.get());
    }
    if (!prepared) {
      return prepared.error();
    }

    auto scene =
        std::make_shared<const PreparedScene>(std::move(prepared).value());
    std::vector<ViewEvent> text_notifications;
    impl_->publish_value_issues(document_id, revision, *scene,
                                text_notifications);
    const auto text_diagnostic = impl_->publish_text_issues(
        document_id, revision, *scene, text_notifications);
    const auto next_state_version = impl_->state_version + 1;
    std::vector<ViewEvent> pending_events{
        ViewEvent{
            .kind = ViewEventKind::presentation_changed,
            .state_version = next_state_version,
            .document_id = document_id,
            .document_revision = revision,
        },
        ViewEvent{
            .kind = ViewEventKind::viewport_changed,
            .state_version = next_state_version,
            .document_id = document_id,
            .document_revision = revision,
        },
        ViewEvent{
            .kind = ViewEventKind::frame_ready,
            .state_version = next_state_version,
            .document_id = document_id,
            .document_revision = revision,
        },
    };
    impl_->events.reserve(impl_->events.size() + pending_events.size());
    impl_->prepared_scenes.reserve(impl_->prepared_scenes.size() + 1);
    impl_->presentations.reserve(impl_->presentations.size() + 1);
    impl_->viewports.reserve(impl_->viewports.size() + 1);
    impl_->viewport_pixel_heights.reserve(impl_->viewport_pixel_heights.size() +
                                          1);
    impl_->viewport_defaults.reserve(impl_->viewport_defaults.size() + 1);
    for (auto &existing_task : impl_->frame_tasks) {
      if (existing_task->document_id == document_id) {
        existing_task->worker.request_stop();
      }
    }
    impl_->frame_generations.erase(document_id);
    impl_->prepared_scenes.insert_or_assign(document_id, std::move(scene));
    impl_->presentations.insert_or_assign(document_id, command.presentation);
    impl_->viewports.insert_or_assign(document_id, initial_viewport);
    impl_->viewport_pixel_heights.insert_or_assign(document_id,
                                                   default_frame_pixel_height);
    impl_->viewport_defaults.insert_or_assign(document_id, initial_viewport);
    impl_->crosshairs.erase(document_id);
    impl_->state_version = next_state_version;
    impl_->events.insert(impl_->events.end(), pending_events.begin(),
                         pending_events.end());
    for (const auto &event : pending_events) {
      impl_->notify_observers(event);
    }
    for (const auto &event : text_notifications) {
      impl_->notify_observers(event);
    }
    return CommandReceipt{
        .state_version = next_state_version,
        .document_id = document_id,
        .document_revision = revision,
        .asynchronous_preparation_started = false,
        .diagnostic_id = text_diagnostic,
    };
  } catch (const std::bad_alloc &) {
    return Error{
        .code = ErrorCode::resource_exhausted,
        .severity = Severity::error,
        .entity_id = std::nullopt,
        .message = MessageKey::resource_exhausted,
        .arguments = {},
    };
  } catch (...) {
    return Error{
        .code = ErrorCode::internal_error,
        .severity = Severity::error,
        .entity_id = std::nullopt,
        .message = MessageKey::internal_error,
        .arguments = {},
    };
  }
}

Result<CommandReceipt>
WellLogSession::execute(const SetViewportCommand &command) {
  return execute(SetViewportMetricsCommand{
      .document_id = command.document_id,
      .viewport = command.viewport,
      .pixel_height =
          viewport_pixel_height(command.document_id).value_or(std::uint32_t{}),
  });
}

Result<CommandReceipt>
WellLogSession::execute(const SetViewportMetricsCommand &command) {
  try {
    if (!valid_viewport(command.viewport)) {
      return viewport_error(command.document_id);
    }
    const auto document = impl_->documents.find(command.document_id);
    const auto viewport = impl_->viewports.find(command.document_id);
    const auto viewport_pixel_height =
        impl_->viewport_pixel_heights.find(command.document_id);
    if (document == impl_->documents.end() ||
        viewport == impl_->viewports.end() ||
        viewport_pixel_height == impl_->viewport_pixel_heights.end()) {
      return viewport_error(command.document_id);
    }
    if (command.pixel_height == 0) {
      return viewport_error(command.document_id);
    }
    if (impl_->state_version == std::numeric_limits<std::uint64_t>::max()) {
      return viewport_error(command.document_id);
    }
    auto frame_task = std::unique_ptr<FrameTask>{};
    auto frame_generation = std::uint64_t{};
    const auto preparation = impl_->preparations.find(command.document_id);
    const auto presentation = impl_->presentations.find(command.document_id);
    if (preparation != impl_->preparations.end() &&
        preparation->second.state == PreparationState::ready &&
        presentation != impl_->presentations.end()) {
      if (impl_->next_frame_generation ==
          std::numeric_limits<std::uint64_t>::max()) {
        return viewport_error(command.document_id);
      }
      frame_generation = impl_->next_frame_generation;
      frame_task = make_frame_task(
          command.document_id, document->second->revision(), frame_generation,
          document->second, presentation->second, preparation->second.pyramids,
          CurveLodQuery{
              .viewport_top = command.viewport.top,
              .viewport_bottom = command.viewport.bottom,
              .pixel_height = command.pixel_height,
              .prefetch_viewports = impl_->budgets.prefetch_viewports,
          },
          preparation->second.image_pyramids,
          ImagePyramidQuery{
              .viewport_top = command.viewport.top,
              .viewport_bottom = command.viewport.bottom,
              .pixel_height = static_cast<double>(command.pixel_height),
              .prefetch_viewports = impl_->budgets.prefetch_viewports,
          },
          impl_->text_engine, &impl_->text_engine_mutex);
    }
    const auto next_state_version = impl_->state_version + 1;
    const auto revision = document->second->revision();
    impl_->events.reserve(impl_->events.size() + 1);
    if (frame_task != nullptr) {
      impl_->frame_tasks.reserve(impl_->frame_tasks.size() + 1);
      impl_->frame_generations.reserve(impl_->frame_generations.size() + 1);
      for (auto &existing_task : impl_->frame_tasks) {
        if (existing_task->document_id == command.document_id) {
          existing_task->worker.request_stop();
        }
      }
      impl_->frame_generations.insert_or_assign(command.document_id,
                                                frame_generation);
      impl_->frame_tasks.push_back(std::move(frame_task));
      ++impl_->next_frame_generation;
    }
    viewport->second = command.viewport;
    viewport_pixel_height->second = command.pixel_height;
    impl_->state_version = next_state_version;
    const auto event = ViewEvent{
        .kind = ViewEventKind::viewport_changed,
        .state_version = next_state_version,
        .document_id = command.document_id,
        .document_revision = revision,
    };
    impl_->events.push_back(event);
    impl_->notify_observers(event);
    return CommandReceipt{
        .state_version = next_state_version,
        .document_id = command.document_id,
        .document_revision = revision,
        .asynchronous_preparation_started = frame_generation != 0,
        .diagnostic_id = std::nullopt,
    };
  } catch (const std::bad_alloc &) {
    return Error{
        .code = ErrorCode::resource_exhausted,
        .severity = Severity::error,
        .entity_id = command.document_id,
        .message = MessageKey::resource_exhausted,
        .arguments = {},
    };
  } catch (...) {
    return Error{
        .code = ErrorCode::internal_error,
        .severity = Severity::error,
        .entity_id = command.document_id,
        .message = MessageKey::internal_error,
        .arguments = {},
    };
  }
}

Result<CommandReceipt> WellLogSession::execute(const PanDepthCommand &command) {
  const auto current = viewport(command.document_id);
  if (!current.has_value() || !std::isfinite(command.display_depth_delta)) {
    return viewport_error(command.document_id);
  }
  const auto next = DepthViewport{
      .top = current->top + command.display_depth_delta,
      .bottom = current->bottom + command.display_depth_delta,
  };
  if (!valid_viewport(next)) {
    return viewport_error(command.document_id);
  }
  return execute(SetViewportCommand{
      .document_id = command.document_id,
      .viewport = next,
  });
}

Result<CommandReceipt>
WellLogSession::execute(const ZoomDepthAtCommand &command) {
  const auto current = viewport(command.document_id);
  if (!current.has_value() || !std::isfinite(command.anchor_display_depth) ||
      !std::isfinite(command.span_factor) || command.span_factor <= 0.0) {
    return viewport_error(command.document_id);
  }
  const auto next = DepthViewport{
      .top =
          command.anchor_display_depth +
          (current->top - command.anchor_display_depth) * command.span_factor,
      .bottom = command.anchor_display_depth +
                (current->bottom - command.anchor_display_depth) *
                    command.span_factor,
  };
  if (!valid_viewport(next)) {
    return viewport_error(command.document_id);
  }
  return execute(SetViewportCommand{
      .document_id = command.document_id,
      .viewport = next,
  });
}

Result<CommandReceipt>
WellLogSession::execute(const ResetViewportCommand &command) {
  const auto default_viewport =
      impl_->viewport_defaults.find(command.document_id);
  if (default_viewport == impl_->viewport_defaults.end()) {
    return viewport_error(command.document_id);
  }
  return execute(SetViewportCommand{
      .document_id = command.document_id,
      .viewport = default_viewport->second,
  });
}

Result<CommandReceipt>
WellLogSession::execute(const SetCrosshairCommand &command) {
  try {
    if (command.crosshair.has_value() && !valid_crosshair(*command.crosshair)) {
      return viewport_error(command.document_id);
    }
    const auto document = impl_->documents.find(command.document_id);
    if (document == impl_->documents.end() ||
        !impl_->viewports.contains(command.document_id)) {
      return viewport_error(command.document_id);
    }
    if (impl_->state_version == std::numeric_limits<std::uint64_t>::max()) {
      return viewport_error(command.document_id);
    }
    const auto next_state_version = impl_->state_version + 1;
    const auto revision = document->second->revision();
    impl_->events.reserve(impl_->events.size() + 1);
    if (command.crosshair.has_value()) {
      impl_->crosshairs.reserve(impl_->crosshairs.size() + 1);
      impl_->crosshairs.insert_or_assign(command.document_id,
                                         *command.crosshair);
    } else {
      impl_->crosshairs.erase(command.document_id);
    }
    impl_->state_version = next_state_version;
    const auto event = ViewEvent{
        .kind = ViewEventKind::crosshair_changed,
        .state_version = next_state_version,
        .document_id = command.document_id,
        .document_revision = revision,
    };
    impl_->events.push_back(event);
    impl_->notify_observers(event);
    return CommandReceipt{
        .state_version = next_state_version,
        .document_id = command.document_id,
        .document_revision = revision,
        .asynchronous_preparation_started = false,
        .diagnostic_id = std::nullopt,
    };
  } catch (const std::bad_alloc &) {
    return Error{
        .code = ErrorCode::resource_exhausted,
        .severity = Severity::error,
        .entity_id = command.document_id,
        .message = MessageKey::resource_exhausted,
        .arguments = {},
    };
  } catch (...) {
    return Error{
        .code = ErrorCode::internal_error,
        .severity = Severity::error,
        .entity_id = command.document_id,
        .message = MessageKey::internal_error,
        .arguments = {},
    };
  }
}

// Shared apply path for the selection commands. Resolves a SelectionState for
// `document_id` over `axis_id` from either a depth range or a row span, stores
// it, bumps the version, and publishes a selection_changed event. Rejects when
// the document or axis is unknown, or the range/span is invalid.
[[nodiscard]] Result<CommandReceipt>
WellLogSession::apply_selection(EntityId document_id, EntityId axis_id,
                                SelectionDepthRange range,
                                std::uint64_t first_row,
                                std::uint64_t last_row, bool from_rows) {
  try {
    const auto document = impl_->documents.find(document_id);
    if (document == impl_->documents.end()) {
      return selection_document_missing(document_id);
    }
    const auto axis = find_axis(*document->second, axis_id);
    if (axis == nullptr) {
      return selection_axis_missing(axis_id);
    }
    const auto revision = document->second->revision();
    if (from_rows) {
      // Resolve rows → range, then recompute the row span from that range so
      // the stored span is canonical (clamped, monotone).
      range =
          range_for_rows(axis->coordinates, first_row, last_row);
    }
    if (!valid_selection_range(range)) {
      return selection_invalid(document_id);
    }
    const auto span =
        rows_for_range(axis->coordinates, axis->direction, range);
    if (impl_->state_version == std::numeric_limits<std::uint64_t>::max()) {
      return selection_invalid(document_id);
    }
    const auto next_state_version = impl_->state_version + 1;
    impl_->events.reserve(impl_->events.size() + 1);
    impl_->selections.reserve(impl_->selections.size() + 1);
    impl_->selections.insert_or_assign(
        document_id,
        SelectionState{
            .document_id = document_id,
            .sampling_axis_id = axis_id,
            .reference_depth_range = range,
            .first_row = span.first,
            .last_row = span.last,
            .document_revision = revision,
            .valid = true,
        });
    impl_->state_version = next_state_version;
    const auto event = ViewEvent{
        .kind = ViewEventKind::selection_changed,
        .state_version = next_state_version,
        .document_id = document_id,
        .document_revision = revision,
    };
    impl_->events.push_back(event);
    impl_->notify_observers(event);
    return CommandReceipt{
        .state_version = next_state_version,
        .document_id = document_id,
        .document_revision = revision,
        .asynchronous_preparation_started = false,
        .diagnostic_id = std::nullopt,
    };
  } catch (const std::bad_alloc &) {
    return Error{
        .code = ErrorCode::resource_exhausted,
        .severity = Severity::error,
        .entity_id = document_id,
        .message = MessageKey::resource_exhausted,
        .arguments = {},
    };
  } catch (...) {
    return Error{
        .code = ErrorCode::internal_error,
        .severity = Severity::error,
        .entity_id = document_id,
        .message = MessageKey::internal_error,
        .arguments = {},
    };
  }
}

Result<CommandReceipt>
WellLogSession::execute(const SetSelectionCommand &command) {
  return apply_selection(command.document_id, command.sampling_axis_id,
                         command.reference_depth_range, 0, 0,
                         /*from_rows=*/false);
}

Result<CommandReceipt>
WellLogSession::execute(const SetRowSelectionCommand &command) {
  if (command.last_row < command.first_row) {
    return selection_invalid(command.document_id);
  }
  return apply_selection(command.document_id, command.sampling_axis_id,
                         SelectionDepthRange{}, command.first_row,
                         command.last_row, /*from_rows=*/true);
}

Result<CommandReceipt>
WellLogSession::execute(const ClearSelectionCommand &command) {
  try {
    const auto document = impl_->documents.find(command.document_id);
    if (document == impl_->documents.end()) {
      return selection_document_missing(command.document_id);
    }
    if (!impl_->selections.contains(command.document_id)) {
      // Nothing to clear: still succeed, no event.
      return CommandReceipt{
          .state_version = impl_->state_version,
          .document_id = command.document_id,
          .document_revision = document->second->revision(),
          .asynchronous_preparation_started = false,
          .diagnostic_id = std::nullopt,
      };
    }
    if (impl_->state_version == std::numeric_limits<std::uint64_t>::max()) {
      return selection_invalid(command.document_id);
    }
    const auto next_state_version = impl_->state_version + 1;
    const auto revision = document->second->revision();
    impl_->events.reserve(impl_->events.size() + 1);
    impl_->selections.erase(command.document_id);
    impl_->state_version = next_state_version;
    const auto event = ViewEvent{
        .kind = ViewEventKind::selection_changed,
        .state_version = next_state_version,
        .document_id = command.document_id,
        .document_revision = revision,
    };
    impl_->events.push_back(event);
    impl_->notify_observers(event);
    return CommandReceipt{
        .state_version = next_state_version,
        .document_id = command.document_id,
        .document_revision = revision,
        .asynchronous_preparation_started = false,
        .diagnostic_id = std::nullopt,
    };
  } catch (...) {
    return Error{
        .code = ErrorCode::internal_error,
        .severity = Severity::error,
        .entity_id = command.document_id,
        .message = MessageKey::internal_error,
        .arguments = {},
    };
  }
}

// --- AppendBatchCommand (#198, ADR 0031) ------------------------------------
//
// Atomically appends a batch of curve tail-blocks to an existing document,
// producing one new Document Revision from the whole batch (or failing the
// whole batch). Old data blocks stay immutable and are NOT re-copied: each
// appended tail becomes a new segment on the curve's/axis's composite buffer,
// the existing segments retained via their SharedOwners. The session rejects
// an append whose declared revision is not strictly greater than the current
// (monotonic revision gate). Out-of-order and historical backfill are rejected
// — those require an explicit Replace/Patch.

// Gathers the existing physical segments of a CurveBuffer in order: the single
// block, or each composite segment. Used to rebuild a composite spanning the
// existing data plus a new tail, with no contiguous copy of the old data.
[[nodiscard]] std::vector<BufferView>
existing_segments(const CurveBuffer &buffer) {
  if (buffer.is_composite()) {
    const auto segs = buffer.segments();
    return {segs.begin(), segs.end()};
  }
  return {buffer.as_single()};
}

// Tail-continuity + monotonicity check for an append. The tail coordinates must
// (a) be monotone in the axis direction with no non-finite values, and (b)
// continue the existing axis: the tail's first coordinate must stand in the
// declared direction relative to the existing last coordinate (increasing →
// tail.first >= existing.last; decreasing → tail.first <= existing.last). An
// out-of-order tail (the next sample would step backward) or a historical
// backfill (tail starts before the existing end) fails here. Coordinates are
// compared as doubles — append coordinates are depths (floating-point); integer
// precision across the segment boundary is not a concern for an append.
[[nodiscard]] bool tail_continues_axis(const CurveBuffer &existing_coords,
                                       const BufferView &tail_coordinates,
                                       AxisDirection direction) noexcept {
  const auto existing_length = existing_coords.length();
  const auto tail_length = tail_coordinates.length();
  if (tail_length == 0) {
    return false;
  }
  // Tail must itself be monotone + finite in the declared direction.
  auto previous = tail_coordinates.value_as_double(0);
  if (!previous.has_value() || !std::isfinite(*previous)) {
    return false;
  }
  for (std::uint64_t index = 1; index < tail_length; ++index) {
    const auto current = tail_coordinates.value_as_double(index);
    if (!current.has_value() || !std::isfinite(*current)) {
      return false;
    }
    const auto ordered = direction == AxisDirection::increasing
                             ? *current >= *previous
                             : *current <= *previous;
    if (!ordered) {
      return false;
    }
    previous = current;
  }
  // Continuity against the existing axis end (only when the axis is non-empty;
  // an empty axis — impossible for a valid document — would accept any tail).
  if (existing_length == 0) {
    return true;
  }
  const auto existing_last = existing_coords.value_as_double(existing_length - 1);
  const auto tail_first = tail_coordinates.value_as_double(0);
  if (!existing_last.has_value() || !tail_first.has_value()) {
    return false;
  }
  return direction == AxisDirection::increasing
             ? *tail_first >= *existing_last
             : *tail_first <= *existing_last;
}

// Append-failure error builders. Each reuses the closest existing stable
// code/message so a caller distinguishes a missing document, a monotonic
// revision clash, a structural tail mismatch, and a direction/continuity
// violation — never a single opaque code (architecture.md §2 Result/Error).
[[nodiscard]] Error append_document_missing(EntityId document_id) {
  return Error{
      .code = ErrorCode::document_not_found,
      .severity = Severity::error,
      .entity_id = document_id,
      .message = MessageKey::presentation_document_missing,
      .arguments = {},
  };
}

[[nodiscard]] Error append_revision_not_monotonic(EntityId document_id) {
  // A revision clash is a document-structure violation (the host raced or
  // mis-stated the base revision); invalid_document is the closest stable code.
  return Error{
      .code = ErrorCode::invalid_document,
      .severity = Severity::error,
      .entity_id = document_id,
      .message = MessageKey::document_structure_invalid,
      .arguments = {},
  };
}

[[nodiscard]] Error append_curve_missing(EntityId curve_id) {
  return Error{
      .code = ErrorCode::missing_sampling_axis,
      .severity = Severity::error,
      .entity_id = curve_id,
      .message = MessageKey::sampling_axis_missing,
      .arguments = {},
  };
}

[[nodiscard]] Error append_tail_mismatch(EntityId entity_id) {
  return Error{
      .code = ErrorCode::length_mismatch,
      .severity = Severity::error,
      .entity_id = entity_id,
      .message = MessageKey::curve_length_mismatch,
      .arguments = {},
  };
}

[[nodiscard]] Error append_tail_direction(EntityId axis_id) {
  return Error{
      .code = ErrorCode::invalid_sampling_axis,
      .severity = Severity::error,
      .entity_id = axis_id,
      .message = MessageKey::sampling_axis_direction_invalid,
      .arguments = {},
  };
}

Result<CommandReceipt>
WellLogSession::execute(const AppendBatchCommand &command) {
  try {
    if (command.blocks.empty()) {
      // An empty batch is a no-op: succeed at the current revision without
      // producing a new one (no state change, no event).
      const auto document = impl_->documents.find(command.document_id);
      if (document == impl_->documents.end()) {
        return append_document_missing(command.document_id);
      }
      return CommandReceipt{
          .state_version = impl_->state_version,
          .document_id = command.document_id,
          .document_revision = document->second->revision(),
          .asynchronous_preparation_started = false,
          .diagnostic_id = std::nullopt,
      };
    }

    const auto document_entry = impl_->documents.find(command.document_id);
    if (document_entry == impl_->documents.end()) {
      return append_document_missing(command.document_id);
    }
    const auto &current = *document_entry->second;
    const auto current_revision = current.revision();
    // Monotonic revision gate: the declared target must be strictly greater
    // than the document's current revision. SetDocumentCommand blindly
    // replaces; append refuses a stale/equal revision so a racing host cannot
    // silently clobber a newer append.
    if (command.target_revision.value <= current_revision.value) {
      return append_revision_not_monotonic(command.document_id);
    }

    // --- Validate the whole batch before touching any state (atomicity). ---
    // Stage the rebuilt curves/axes keyed by id so the commit rebuild is a
    // lookup. A failure here returns an error and leaves the session unchanged.
    struct RebuiltCurve {
      Curve curve;
    };
    struct RebuiltAxis {
      SamplingAxis axis;
    };
    std::unordered_map<EntityId, RebuiltAxis, EntityIdHash> rebuilt_axes;
    std::unordered_map<EntityId, RebuiltCurve, EntityIdHash> rebuilt_curves;

    for (const auto &block : command.blocks) {
      // Resolve the existing curve + its sampling axis on the current document.
      const Curve *existing_curve = nullptr;
      for (const auto &curve : current.curves()) {
        if (curve.id == block.curve_id) {
          existing_curve = &curve;
          break;
        }
      }
      if (existing_curve == nullptr) {
        return append_curve_missing(block.curve_id);
      }
      if (existing_curve->sampling_axis_id != block.sampling_axis_id) {
        return append_tail_mismatch(block.curve_id);
      }
      const auto *axis = find_axis(current, block.sampling_axis_id);
      if (axis == nullptr) {
        return append_curve_missing(block.sampling_axis_id);
      }

      // Tail buffers must each be valid (owner + non-empty data + stride).
      if (const auto r = required_bytes(block.tail_coordinates); !r) {
        return r.error();
      }
      if (const auto r = required_bytes(block.tail_values); !r) {
        return r.error();
      }
      // Tail coordinate/value lengths must match each other.
      if (block.tail_coordinates.length() != block.tail_values.length()) {
        return append_tail_mismatch(block.curve_id);
      }
      // Tail coordinate scalar type must match the existing axis (a mixed-type
      // composite is rejected at CompositeBufferView build; catch it here with a
      // structural error before composing).
      if (block.tail_coordinates.scalar_type() !=
          axis->coordinates.scalar_type()) {
        return append_tail_mismatch(block.sampling_axis_id);
      }
      // Tail value scalar type must match the existing curve values.
      if (block.tail_values.scalar_type() !=
          existing_curve->values.scalar_type()) {
        return append_tail_mismatch(block.curve_id);
      }

      // Tail continuity + monotonicity in the axis direction (rejects
      // out-of-order and historical backfill).
      const auto axis_coords_so_far =
          rebuilt_axes.count(axis->id)
              ? rebuilt_axes.at(axis->id).axis.coordinates
              : axis->coordinates;
      if (!tail_continues_axis(axis_coords_so_far, block.tail_coordinates,
                               axis->direction)) {
        return append_tail_direction(axis->id);
      }

      // --- Compose the no-copy composite buffers. ---
      // Axis coordinates: existing segments + tail coordinate block.
      auto coord_segments = existing_segments(axis_coords_so_far);
      coord_segments.push_back(block.tail_coordinates);
      auto coord_composite =
          CompositeBufferView::from_segments(std::move(coord_segments));
      if (coord_composite.empty()) {
        return append_tail_mismatch(block.sampling_axis_id);
      }

      // Curve values: existing segments + tail value block.
      const auto curve_values_so_far =
          rebuilt_curves.count(existing_curve->id)
              ? rebuilt_curves.at(existing_curve->id).curve.values
              : existing_curve->values;
      auto value_segments = existing_segments(curve_values_so_far);
      value_segments.push_back(block.tail_values);
      auto value_composite =
          CompositeBufferView::from_segments(std::move(value_segments));
      if (value_composite.empty()) {
        return append_tail_mismatch(block.curve_id);
      }

      // Stage the rebuilt axis + curve (preserving all metadata; only the
      // buffers change). A second block on the same axis/curve composes against
      // the staged composite, so a multi-block batch on one curve appends in
      // order.
      SamplingAxis rebuilt_axis = *axis;
      rebuilt_axis.coordinates = CurveBuffer(coord_composite);
      rebuilt_axes[axis->id] = RebuiltAxis{.axis = std::move(rebuilt_axis)};

      Curve rebuilt_curve = *existing_curve;
      rebuilt_curve.values = CurveBuffer(value_composite);
      rebuilt_curves[existing_curve->id] =
          RebuiltCurve{.curve = std::move(rebuilt_curve)};
    }

    // --- Atomic commit: rebuild the document at the target revision. ---
    // Copy every entity from the current document into a fresh builder at the
    // new revision, substituting the rebuilt (composite-buffer) axes/curves.
    // No old data block is re-copied — the composite buffers reference them
    // in place via their SharedOwners.
    WellLogDocumentBuilder builder(current.id(), command.target_revision);
    for (const auto &axis : current.sampling_axes()) {
      const auto it = rebuilt_axes.find(axis.id);
      builder.add_sampling_axis(it == rebuilt_axes.end() ? axis : it->second.axis);
    }
    for (const auto &curve : current.curves()) {
      const auto it = rebuilt_curves.find(curve.id);
      builder.add_curve(it == rebuilt_curves.end() ? curve : it->second.curve);
    }
    for (const auto &interval : current.intervals()) {
      builder.add_interval(interval);
    }
    for (const auto &marker : current.markers()) {
      builder.add_marker(marker);
    }
    for (const auto &symbol : current.symbols()) {
      builder.add_symbol(symbol);
    }
    for (const auto &image : current.image_sources()) {
      builder.add_image_source(image);
    }
    for (const auto &annotation : current.annotations()) {
      builder.add_annotation(annotation);
    }
    for (const auto &custom : current.custom_sources()) {
      builder.add_custom_source(custom);
    }

    // Delegate to the existing SetDocumentCommand commit path: it re-validates
    // the rebuilt document (catching any inconsistency), rebuilds the LOD,
    // remaps/invalidates the selection, clears stale viewports/scenes, and
    // publishes the documents_changed event at the new revision.
    auto appended = builder.build();
    if (appended.id().is_nil()) {
      // Builder allocation failure (allocation_failed flag is internal to the
      // builder; build() returns a default document on failure).
      return Error{
          .code = ErrorCode::resource_exhausted,
          .severity = Severity::error,
          .entity_id = command.document_id,
          .message = MessageKey::resource_exhausted,
          .arguments = {},
      };
    }
    return execute(SetDocumentCommand{std::move(appended)});
  } catch (const std::bad_alloc &) {
    return Error{
        .code = ErrorCode::resource_exhausted,
        .severity = Severity::error,
        .entity_id = command.document_id,
        .message = MessageKey::resource_exhausted,
        .arguments = {},
    };
  } catch (...) {
    return Error{
        .code = ErrorCode::internal_error,
        .severity = Severity::error,
        .entity_id = command.document_id,
        .message = MessageKey::internal_error,
        .arguments = {},
    };
  }
}

void WellLogSession::poll_async() noexcept {
  try {
    std::vector<ViewEvent> notifications;
    notifications.reserve(impl_->lod_tasks.size() + impl_->frame_tasks.size());
    auto task = impl_->lod_tasks.begin();
    while (task != impl_->lod_tasks.end()) {
      auto output = LodBuildOutput{};
      {
        const auto guard = std::lock_guard{(*task)->state->mutex};
        if (!(*task)->state->finished) {
          ++task;
          continue;
        }
        output = std::move((*task)->state->output);
      }
      auto completed_task = std::move(*task);
      task = impl_->lod_tasks.erase(task);

      try {
        const auto preparation =
            impl_->preparations.find(completed_task->document_id);
        const auto current =
            preparation != impl_->preparations.end() &&
            preparation->second.revision == completed_task->revision &&
            preparation->second.generation == completed_task->generation;
        if (output.cancelled) {
          ++impl_->cancelled_lod_tasks;
        } else if (!current) {
          ++impl_->discarded_lod_tasks;
        } else if (output.error.has_value()) {
          preparation->second.state = PreparationState::unavailable;
          impl_->publish_async_failure(completed_task->document_id,
                                       completed_task->revision, *output.error,
                                       notifications);
        } else {
          preparation->second.state = PreparationState::ready;
          preparation->second.derived_bytes = output.derived_bytes;
          preparation->second.pyramids =
              std::make_shared<const detail::ScenePreparer::CurveLodMap>(
                  std::move(output.pyramids));
          preparation->second.image_pyramids =
              std::make_shared<const detail::ScenePreparer::ImagePyramidMap>(
                  std::move(output.image_pyramids));
          // Publish a Diagnostic for each ImageSource whose pyramid build
          // failed (non-cancelled), so the degradation is observable (qsp §7)
          // before the scene emits no layer for it.
          for (const auto &skipped : output.skipped_images) {
            impl_->publish_one_diagnostic(
                completed_task->document_id, completed_task->revision, skipped,
                1, DiagnosticCode::image_pyramid_unavailable,
                MessageKey::image_metadata_invalid, ErrorCode::invalid_image,
                notifications);
          }
          const auto document =
              impl_->documents.find(completed_task->document_id);
          const auto presentation =
              impl_->presentations.find(completed_task->document_id);
          const auto viewport =
              impl_->viewports.find(completed_task->document_id);
          const auto viewport_pixel_height =
              impl_->viewport_pixel_heights.find(completed_task->document_id);
          if (document != impl_->documents.end() &&
              presentation != impl_->presentations.end() &&
              viewport != impl_->viewports.end() &&
              viewport_pixel_height != impl_->viewport_pixel_heights.end()) {
            if (impl_->next_frame_generation ==
                std::numeric_limits<std::uint64_t>::max()) {
              preparation->second.state = PreparationState::unavailable;
              impl_->publish_async_failure(
                  completed_task->document_id, completed_task->revision,
                  Error{
                      .code = ErrorCode::internal_error,
                      .severity = Severity::error,
                      .entity_id = completed_task->document_id,
                      .message = MessageKey::internal_error,
                      .arguments = {},
                  },
                  notifications);
            } else {
              const auto frame_generation = impl_->next_frame_generation;
              auto pending_frame = make_frame_task(
                  completed_task->document_id, completed_task->revision,
                  frame_generation, document->second, presentation->second,
                  preparation->second.pyramids,
                  CurveLodQuery{
                      .viewport_top = viewport->second.top,
                      .viewport_bottom = viewport->second.bottom,
                      .pixel_height = viewport_pixel_height->second,
                      .prefetch_viewports = impl_->budgets.prefetch_viewports,
                  },
                  preparation->second.image_pyramids,
                  ImagePyramidQuery{
                      .viewport_top = viewport->second.top,
                      .viewport_bottom = viewport->second.bottom,
                      .pixel_height =
                          static_cast<double>(viewport_pixel_height->second),
                      .prefetch_viewports = impl_->budgets.prefetch_viewports,
                  },
                  impl_->text_engine, &impl_->text_engine_mutex);
              impl_->frame_tasks.reserve(impl_->frame_tasks.size() + 1);
              impl_->frame_generations.reserve(impl_->frame_generations.size() +
                                               1);
              for (auto &existing_task : impl_->frame_tasks) {
                if (existing_task->document_id == completed_task->document_id) {
                  existing_task->worker.request_stop();
                }
              }
              impl_->frame_generations.insert_or_assign(
                  completed_task->document_id, frame_generation);
              impl_->frame_tasks.push_back(std::move(pending_frame));
              ++impl_->next_frame_generation;
            }
          }
          ++impl_->completed_lod_tasks;
        }
      } catch (...) {
        const auto preparation =
            impl_->preparations.find(completed_task->document_id);
        if (preparation != impl_->preparations.end() &&
            preparation->second.revision == completed_task->revision &&
            preparation->second.generation == completed_task->generation) {
          preparation->second.state = PreparationState::unavailable;
        }
        ++impl_->discarded_lod_tasks;
        try {
          impl_->publish_async_failure(
              completed_task->document_id, completed_task->revision,
              Error{
                  .code = ErrorCode::internal_error,
                  .severity = Severity::error,
                  .entity_id = completed_task->document_id,
                  .message = MessageKey::internal_error,
                  .arguments = {},
              },
              notifications);
        } catch (...) {
        }
      }
    }

    auto frame_task = impl_->frame_tasks.begin();
    while (frame_task != impl_->frame_tasks.end()) {
      auto output = FrameBuildOutput{};
      {
        const auto guard = std::lock_guard{(*frame_task)->state->mutex};
        if (!(*frame_task)->state->finished) {
          ++frame_task;
          continue;
        }
        output = std::move((*frame_task)->state->output);
      }
      auto completed_task = std::move(*frame_task);
      frame_task = impl_->frame_tasks.erase(frame_task);
      try {
        const auto generation =
            impl_->frame_generations.find(completed_task->document_id);
        const auto document =
            impl_->documents.find(completed_task->document_id);
        const auto current =
            generation != impl_->frame_generations.end() &&
            generation->second == completed_task->generation &&
            document != impl_->documents.end() &&
            document->second->revision() == completed_task->revision;
        if (output.cancelled) {
          ++impl_->cancelled_lod_tasks;
        } else if (!current) {
          ++impl_->discarded_lod_tasks;
        } else if (output.error.has_value() || output.scene == nullptr) {
          impl_->frame_generations.erase(generation);
          const auto error = output.error.value_or(Error{
              .code = ErrorCode::internal_error,
              .severity = Severity::error,
              .entity_id = completed_task->document_id,
              .message = MessageKey::internal_error,
              .arguments = {},
          });
          impl_->publish_async_failure(completed_task->document_id,
                                       completed_task->revision, error,
                                       notifications);
        } else {
          impl_->prepared_scenes.insert_or_assign(completed_task->document_id,
                                                  std::move(output.scene));
          impl_->frame_generations.erase(generation);
          ++impl_->completed_lod_tasks;
          impl_->publish_value_issues(
              completed_task->document_id, completed_task->revision,
              *impl_->prepared_scenes.at(completed_task->document_id),
              notifications);
          static_cast<void>(impl_->publish_text_issues(
              completed_task->document_id, completed_task->revision,
              *impl_->prepared_scenes.at(completed_task->document_id),
              notifications));
          if (impl_->state_version <
              std::numeric_limits<std::uint64_t>::max()) {
            ++impl_->state_version;
            const auto event = ViewEvent{
                .kind = ViewEventKind::frame_ready,
                .state_version = impl_->state_version,
                .document_id = completed_task->document_id,
                .document_revision = completed_task->revision,
            };
            impl_->events.push_back(event);
            notifications.push_back(event);
          }
        }
      } catch (...) {
        const auto generation =
            impl_->frame_generations.find(completed_task->document_id);
        if (generation != impl_->frame_generations.end() &&
            generation->second == completed_task->generation) {
          impl_->frame_generations.erase(generation);
        }
        ++impl_->discarded_lod_tasks;
        try {
          impl_->publish_async_failure(
              completed_task->document_id, completed_task->revision,
              Error{
                  .code = ErrorCode::internal_error,
                  .severity = Severity::error,
                  .entity_id = completed_task->document_id,
                  .message = MessageKey::internal_error,
                  .arguments = {},
              },
              notifications);
        } catch (...) {
        }
      }
    }
    for (const auto &event : notifications) {
      impl_->notify_observers(event);
    }
  } catch (...) {
  }
}

std::optional<PerformanceSnapshot>
WellLogSession::performance_snapshot(EntityId document_id) const noexcept {
  try {
    const auto preparation = impl_->preparations.find(document_id);
    if (preparation == impl_->preparations.end()) {
      return std::nullopt;
    }
    return PerformanceSnapshot{
        .document_revision = preparation->second.revision,
        .preparation_state = preparation->second.state,
        .cpu_derived_bytes = preparation->second.derived_bytes,
        .maximum_cpu_derived_bytes = preparation->second.maximum_derived_bytes,
        .maximum_gpu_cache_bytes = impl_->budgets.maximum_gpu_cache_bytes,
        .maximum_upload_bytes_per_frame =
            impl_->budgets.maximum_upload_bytes_per_frame,
        .completed_tasks = impl_->completed_lod_tasks,
        .cancelled_tasks = impl_->cancelled_lod_tasks,
        .discarded_tasks = impl_->discarded_lod_tasks,
        .frame_preparation_pending =
            impl_->frame_generations.contains(document_id),
    };
  } catch (...) {
    return std::nullopt;
  }
}

PerformanceBudgets WellLogSession::performance_budgets() const noexcept {
  return impl_->budgets;
}

void WellLogSession::set_performance_budgets(
    PerformanceBudgets budgets) noexcept {
  impl_->budgets = std::move(budgets);
}

std::span<const ViewEvent> WellLogSession::events() const noexcept {
  return impl_->events;
}

void WellLogSession::clear_events() noexcept { impl_->events.clear(); }

std::span<const Diagnostic> WellLogSession::diagnostics() const noexcept {
  return impl_->diagnostics;
}

std::optional<Error>
WellLogSession::diagnostic_error(std::uint64_t diagnostic_id) const noexcept {
  try {
    const auto found = impl_->diagnostic_errors.find(diagnostic_id);
    return found == impl_->diagnostic_errors.end()
               ? std::nullopt
               : std::optional<Error>{found->second};
  } catch (...) {
    return std::nullopt;
  }
}

std::shared_ptr<const WellLogDocument>
WellLogSession::document(EntityId id) const noexcept {
  const auto found = impl_->documents.find(id);
  return found == impl_->documents.end() ? nullptr : found->second;
}

std::shared_ptr<const PreparedScene>
WellLogSession::prepared_scene(EntityId document_id) const noexcept {
  const auto found = impl_->prepared_scenes.find(document_id);
  return found == impl_->prepared_scenes.end() ? nullptr : found->second;
}

std::optional<DepthViewport>
WellLogSession::viewport(EntityId document_id) const noexcept {
  const auto found = impl_->viewports.find(document_id);
  return found == impl_->viewports.end()
             ? std::nullopt
             : std::optional<DepthViewport>{found->second};
}

std::optional<std::uint32_t>
WellLogSession::viewport_pixel_height(EntityId document_id) const noexcept {
  const auto found = impl_->viewport_pixel_heights.find(document_id);
  return found == impl_->viewport_pixel_heights.end()
             ? std::nullopt
             : std::optional<std::uint32_t>{found->second};
}

std::optional<CrosshairState>
WellLogSession::crosshair(EntityId document_id) const noexcept {
  const auto found = impl_->crosshairs.find(document_id);
  return found == impl_->crosshairs.end()
             ? std::nullopt
             : std::optional<CrosshairState>{found->second};
}

std::optional<SelectionState>
WellLogSession::selection(EntityId document_id) const noexcept {
  const auto found = impl_->selections.find(document_id);
  return found == impl_->selections.end()
             ? std::nullopt
             : std::optional<SelectionState>{found->second};
}

ViewEventObserverId
WellLogSession::subscribe_view_events(ViewEventObserver observer) noexcept {
  if (!observer) {
    return 0;
  }
  try {
    if (impl_->next_observer_id == 0 ||
        impl_->next_observer_id ==
            std::numeric_limits<ViewEventObserverId>::max()) {
      return 0;
    }
    const auto observer_id = impl_->next_observer_id++;
    impl_->observers.emplace(observer_id, std::move(observer));
    return observer_id;
  } catch (...) {
    return 0;
  }
}

void WellLogSession::unsubscribe_view_events(
    ViewEventObserverId observer_id) noexcept {
  impl_->observers.erase(observer_id);
}

} // namespace welllog
