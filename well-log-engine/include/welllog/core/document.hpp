#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

#include <welllog/core/entity_id.hpp>
#include <welllog/core/export.hpp>
#include <welllog/core/units.hpp>

namespace welllog {

struct DocumentRevision {
  std::uint64_t value{};
  friend constexpr bool operator==(DocumentRevision,
                                   DocumentRevision) = default;
};

enum class ScalarType : std::uint8_t {
  float32,
  float64,
  int16,
  int32,
  int64,
  uint8,
  uint16,
  uint32,
  uint64,
};

[[nodiscard]] WELLLOG_CORE_API std::uint64_t
scalar_size_bytes(ScalarType type) noexcept;
[[nodiscard]] WELLLOG_CORE_API std::string_view
scalar_type_name(ScalarType type) noexcept;
[[nodiscard]] WELLLOG_CORE_API std::optional<ScalarType>
parse_scalar_type(std::string_view name) noexcept;

enum class DepthDomain : std::uint8_t {
  measured_depth,
  true_vertical_depth,
  true_vertical_depth_subsea,
  source_index,
};

enum class AxisDirection : std::uint8_t {
  increasing,
  decreasing,
};

enum class BufferAccessMode : std::uint8_t {
  zero_copy,
  shared_copy,
  converted_copy,
};

struct BufferSourceReference {
  std::string uri;
  std::string checksum;
  std::uint64_t byte_offset{};
};

class WELLLOG_CORE_API SharedOwner {
public:
  SharedOwner();
  ~SharedOwner();
  SharedOwner(const SharedOwner &);
  SharedOwner &operator=(const SharedOwner &);
  SharedOwner(SharedOwner &&) noexcept;
  SharedOwner &operator=(SharedOwner &&) noexcept;

  template <typename T>
  explicit SharedOwner(std::shared_ptr<T> owner)
      : SharedOwner(std::shared_ptr<const void>{std::move(owner)}) {}

  [[nodiscard]] bool has_value() const noexcept;

private:
  struct Impl;
  explicit SharedOwner(std::shared_ptr<const void> owner) noexcept;
  std::shared_ptr<const Impl> impl_;
  friend class BufferView;
  friend class NullBitmapView;
};

template <typename T> inline constexpr bool dependent_false_v = false;

template <typename T> [[nodiscard]] consteval ScalarType scalar_type_for() {
  using Value = std::remove_cv_t<T>;
  if constexpr (std::is_same_v<Value, float>) {
    return ScalarType::float32;
  } else if constexpr (std::is_same_v<Value, double>) {
    return ScalarType::float64;
  } else if constexpr (std::is_same_v<Value, std::int16_t>) {
    return ScalarType::int16;
  } else if constexpr (std::is_same_v<Value, std::int32_t>) {
    return ScalarType::int32;
  } else if constexpr (std::is_same_v<Value, std::int64_t>) {
    return ScalarType::int64;
  } else if constexpr (std::is_same_v<Value, std::uint8_t>) {
    return ScalarType::uint8;
  } else if constexpr (std::is_same_v<Value, std::uint16_t>) {
    return ScalarType::uint16;
  } else if constexpr (std::is_same_v<Value, std::uint32_t>) {
    return ScalarType::uint32;
  } else if constexpr (std::is_same_v<Value, std::uint64_t>) {
    return ScalarType::uint64;
  } else {
    static_assert(dependent_false_v<T>, "unsupported WellLog scalar type");
  }
}

class WELLLOG_CORE_API BufferView {
public:
  BufferView();
  ~BufferView();
  BufferView(const BufferView &);
  BufferView &operator=(const BufferView &);
  BufferView(BufferView &&) noexcept;
  BufferView &operator=(BufferView &&) noexcept;

  [[nodiscard]] static BufferView
  from_raw(const void *data, std::uint64_t length, std::uint64_t stride_bytes,
           ScalarType scalar_type, std::uint64_t byte_capacity,
           SharedOwner owner, BufferSourceReference source = {},
           BufferAccessMode access_mode = BufferAccessMode::zero_copy) noexcept;

  template <typename T>
  [[nodiscard]] static BufferView
  from_vector(const std::shared_ptr<const std::vector<T>> &values,
              BufferSourceReference source = {}) {
    return from_raw(
        values ? values->data() : nullptr,
        values ? static_cast<std::uint64_t>(values->size()) : 0, sizeof(T),
        scalar_type_for<T>(),
        values ? static_cast<std::uint64_t>(values->size() * sizeof(T)) : 0,
        SharedOwner{values}, std::move(source));
  }

  [[nodiscard]] const std::byte *data() const noexcept;
  [[nodiscard]] std::uint64_t length() const noexcept;
  [[nodiscard]] std::uint64_t stride_bytes() const noexcept;
  [[nodiscard]] ScalarType scalar_type() const noexcept;
  [[nodiscard]] std::uint64_t byte_capacity() const noexcept;
  [[nodiscard]] bool has_owner() const noexcept;
  [[nodiscard]] const BufferSourceReference &source() const noexcept;
  [[nodiscard]] BufferAccessMode access_mode() const noexcept;
  [[nodiscard]] std::optional<double>
  value_as_double(std::uint64_t index) const noexcept;

private:
  struct Impl;
  explicit BufferView(std::shared_ptr<const Impl> impl);
  std::shared_ptr<const Impl> impl_;
};

class WELLLOG_CORE_API NullBitmapView {
public:
  NullBitmapView();
  ~NullBitmapView();
  NullBitmapView(const NullBitmapView &);
  NullBitmapView &operator=(const NullBitmapView &);
  NullBitmapView(NullBitmapView &&) noexcept;
  NullBitmapView &operator=(NullBitmapView &&) noexcept;

  [[nodiscard]] static NullBitmapView
  from_raw(const std::uint8_t *data, std::uint64_t bit_length,
           std::uint64_t byte_capacity, SharedOwner owner,
           BufferSourceReference source = {}) noexcept;

  [[nodiscard]] bool empty() const noexcept;
  [[nodiscard]] bool is_null(std::uint64_t index) const noexcept;
  [[nodiscard]] const std::uint8_t *data() const noexcept;
  [[nodiscard]] std::uint64_t bit_length() const noexcept;
  [[nodiscard]] std::uint64_t byte_capacity() const noexcept;
  [[nodiscard]] bool has_owner() const noexcept;
  [[nodiscard]] const BufferSourceReference &source() const noexcept;

private:
  struct Impl;
  explicit NullBitmapView(std::shared_ptr<const Impl> impl);
  std::shared_ptr<const Impl> impl_;
};

struct SamplingAxis {
  EntityId id;
  BufferView coordinates;
  DepthDomain domain{DepthDomain::measured_depth};
  std::string unit;
  AxisDirection direction{AxisDirection::increasing};
};

struct Curve {
  EntityId id;
  std::string mnemonic;
  std::string display_name;
  std::string unit;
  EntityId sampling_axis_id;
  BufferView values;
  NullBitmapView nulls;
};

enum class IntervalSemantic : std::uint8_t {
  lithology,
  stratigraphy,
  sequence,
  systems_tract,
  facies,
  custom,
};

// A closed depth interval. `top_reference_depth` must be less than
// `bottom_reference_depth`; a zero-thickness feature is a Marker, not an
// Interval. `pattern_id` references a PatternDefinition registered on the
// ScenePresentation; when nil the interval is solid-filled with
// `fill_color`. `label` is UTF-8.
struct Interval {
  EntityId id;
  double top_reference_depth{};
  double bottom_reference_depth{};
  IntervalSemantic semantic{IntervalSemantic::custom};
  EntityId pattern_id;
  RgbaColor fill_color{};
  std::string label;
};

enum class MarkerSemantic : std::uint8_t {
  formation_top,
  fault,
  fluid_contact,
  casing_shoe,
  custom,
};

// A zero-thickness depth feature drawn as a horizontal line with an
// optional UTF-8 `label`.
struct Marker {
  EntityId id;
  double reference_depth{};
  MarkerSemantic semantic{MarkerSemantic::custom};
  std::string label;
};

enum class SymbolKind : std::uint8_t {
  circle,
  square,
  triangle_up,
  diamond,
  cross,
};

// A discrete symbol anchored at a depth; `track_fraction` is the horizontal
// anchor within the owning track in [0, 1].
struct SymbolOccurrence {
  EntityId id;
  double reference_depth{};
  double track_fraction{0.5};
  SymbolKind kind{SymbolKind::circle};
  std::string label;
};

enum class TextOrientation : std::uint8_t {
  horizontal,
  rotated,
  vertical,
};

enum class AnnotationAnchor : std::uint8_t {
  reference_depth,
  track,
  scene_point,
};

// A UTF-8 text annotation. The anchor type is explicit:
//  - reference_depth: `reference_depth` + `track_fraction` inside the layer's
//    track;
//  - track: `track_id` + `depth_fraction`/`horizontal_fraction` in [0, 1];
//  - scene_point: absolute `scene_point` in scene millimetres.
// `rotation_degrees` applies when `orientation` is `rotated`; `vertical`
// requests true vertical typesetting. `language` is a BCP 47 tag used for
// shaping and font fallback.
struct TextAnnotation {
  EntityId id;
  AnnotationAnchor anchor{AnnotationAnchor::reference_depth};
  double reference_depth{};
  double track_fraction{0.5};
  EntityId track_id;
  double depth_fraction{};
  double horizontal_fraction{};
  PhysicalPoint scene_point{};
  std::string text;
  std::string language;
  TextOrientation orientation{TextOrientation::horizontal};
  double rotation_degrees{};
  Millimetres font_size{3.0};
};

class WELLLOG_CORE_API WellLogDocument {
public:
  WellLogDocument();

  [[nodiscard]] EntityId id() const noexcept;
  [[nodiscard]] DocumentRevision revision() const noexcept;
  [[nodiscard]] std::span<const SamplingAxis> sampling_axes() const noexcept;
  [[nodiscard]] std::span<const Curve> curves() const noexcept;
  [[nodiscard]] std::span<const Interval> intervals() const noexcept;
  [[nodiscard]] std::span<const Marker> markers() const noexcept;
  [[nodiscard]] std::span<const SymbolOccurrence> symbols() const noexcept;
  [[nodiscard]] std::span<const TextAnnotation> annotations() const noexcept;

private:
  struct Impl;
  explicit WellLogDocument(std::shared_ptr<const Impl> impl);
  std::shared_ptr<const Impl> impl_;
  friend class WellLogDocumentBuilder;
};

class WELLLOG_CORE_API WellLogDocumentBuilder {
public:
  WellLogDocumentBuilder(EntityId id, DocumentRevision revision) noexcept;
  ~WellLogDocumentBuilder();
  WellLogDocumentBuilder(WellLogDocumentBuilder &&) noexcept;
  WellLogDocumentBuilder &operator=(WellLogDocumentBuilder &&) noexcept;
  WellLogDocumentBuilder(const WellLogDocumentBuilder &) = delete;
  WellLogDocumentBuilder &operator=(const WellLogDocumentBuilder &) = delete;

  WellLogDocumentBuilder &add_sampling_axis(const SamplingAxis &axis) noexcept;
  WellLogDocumentBuilder &add_curve(const Curve &curve) noexcept;
  WellLogDocumentBuilder &add_interval(const Interval &interval) noexcept;
  WellLogDocumentBuilder &add_marker(const Marker &marker) noexcept;
  WellLogDocumentBuilder &add_symbol(const SymbolOccurrence &symbol) noexcept;
  WellLogDocumentBuilder &
  add_annotation(const TextAnnotation &annotation) noexcept;
  [[nodiscard]] WellLogDocument build() const noexcept;

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

} // namespace welllog
