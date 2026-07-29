#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <string_view>

#include <welllog/core/document.hpp>
#include <welllog/core/result.hpp>
#include <welllog/scene/export.hpp>

namespace welllog {

struct Millimetres {
  double value{};
  friend constexpr bool operator==(Millimetres, Millimetres) = default;
};

struct PhysicalRect {
  Millimetres left;
  Millimetres top;
  Millimetres width;
  Millimetres height;
};

struct PhysicalPoint {
  Millimetres left;
  Millimetres top;
};

struct ReferenceDepthRange {
  DepthDomain domain{DepthDomain::measured_depth};
  std::string_view unit;
  double top{};
  double bottom{};
};

struct DeviceIndependentPixels {
  double value{};
  friend constexpr bool operator==(DeviceIndependentPixels,
                                   DeviceIndependentPixels) = default;
};

enum class ScaleDirection : std::uint8_t {
  left_to_right,
  right_to_left,
};

enum class ScaleMode : std::uint8_t {
  linear,
};

struct RgbaColor {
  std::uint8_t red{};
  std::uint8_t green{};
  std::uint8_t blue{};
  std::uint8_t alpha{255};
  friend constexpr bool operator==(RgbaColor, RgbaColor) = default;
};

struct TrackSpec {
  EntityId id;
  Millimetres width;
  std::int32_t z_order{};
};

struct TrackScaleSpec {
  EntityId id;
  EntityId track_id;
  ScaleMode mode{ScaleMode::linear};
  double minimum{};
  double maximum{};
  ScaleDirection direction{ScaleDirection::left_to_right};
  std::string unit;
};

struct CurveLayerSpec {
  EntityId id;
  EntityId track_id;
  EntityId curve_id;
  EntityId scale_id;
  RgbaColor color;
  Millimetres line_width;
  std::int32_t z_order{};
};

class WELLLOG_SCENE_API ScenePresentation {
public:
  ScenePresentation();
  ~ScenePresentation();
  ScenePresentation(const ScenePresentation &);
  ScenePresentation &operator=(const ScenePresentation &);
  ScenePresentation(ScenePresentation &&) noexcept;
  ScenePresentation &operator=(ScenePresentation &&) noexcept;

  [[nodiscard]] EntityId document_id() const noexcept;
  [[nodiscard]] ReferenceDepthRange reference_depth_range() const noexcept;
  [[nodiscard]] Millimetres physical_height() const noexcept;
  [[nodiscard]] std::string_view font_asset_fingerprint() const noexcept;
  [[nodiscard]] std::span<const TrackSpec> tracks() const noexcept;
  [[nodiscard]] std::span<const TrackScaleSpec> scales() const noexcept;
  [[nodiscard]] std::span<const CurveLayerSpec> curve_layers() const noexcept;

private:
  struct Impl;
  explicit ScenePresentation(std::shared_ptr<const Impl> impl);
  std::shared_ptr<const Impl> impl_;
  friend class ScenePresentationBuilder;
};

class WELLLOG_SCENE_API ScenePresentationBuilder {
public:
  ScenePresentationBuilder(EntityId document_id,
                           ReferenceDepthRange reference_depth_range,
                           Millimetres physical_height,
                           std::string_view font_asset_fingerprint) noexcept;
  ~ScenePresentationBuilder();
  ScenePresentationBuilder(ScenePresentationBuilder &&) noexcept;
  ScenePresentationBuilder &operator=(ScenePresentationBuilder &&) noexcept;
  ScenePresentationBuilder(const ScenePresentationBuilder &) = delete;
  ScenePresentationBuilder &
  operator=(const ScenePresentationBuilder &) = delete;

  ScenePresentationBuilder &add_track(const TrackSpec &track) noexcept;
  ScenePresentationBuilder &add_scale(const TrackScaleSpec &scale) noexcept;
  ScenePresentationBuilder &
  add_curve_layer(const CurveLayerSpec &layer) noexcept;
  [[nodiscard]] ScenePresentation build() const noexcept;

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

struct PreparedTrack {
  EntityId id;
  PhysicalRect bounds;
  PhysicalRect clip;
  std::int32_t z_order{};
};

struct PreparedCurveLayer {
  EntityId id;
  EntityId track_id;
  EntityId curve_id;
  EntityId scale_id;
  RgbaColor color;
  Millimetres line_width;
  std::int32_t z_order{};
  std::uint64_t first_segment{};
  std::uint64_t segment_count{};
};

struct PreparedCurveSegment {
  EntityId layer_id;
  std::uint64_t first_point{};
  std::uint64_t point_count{};
};

struct PreparedCurvePoint {
  PhysicalPoint position;
  std::uint64_t sample_index{};
  double reference_depth{};
  double value{};
};

struct CurvePick {
  EntityId layer_id;
  EntityId curve_id;
  std::uint64_t sample_index{};
  double reference_depth{};
  double display_depth{};
  double value{};
  DeviceIndependentPixels distance;
};

struct CurvePickQuery {
  PhysicalPoint scene_position;
  DeviceIndependentPixels tolerance;
  double horizontal_device_independent_pixels_per_millimetre{};
  double vertical_device_independent_pixels_per_millimetre{};
};

namespace detail {
class ScenePreparer;
}

class WELLLOG_SCENE_API PreparedScene {
public:
  PreparedScene();
  ~PreparedScene();
  PreparedScene(const PreparedScene &);
  PreparedScene &operator=(const PreparedScene &);
  PreparedScene(PreparedScene &&) noexcept;
  PreparedScene &operator=(PreparedScene &&) noexcept;

  [[nodiscard]] EntityId document_id() const noexcept;
  [[nodiscard]] DocumentRevision document_revision() const noexcept;
  [[nodiscard]] Millimetres physical_width() const noexcept;
  [[nodiscard]] Millimetres physical_height() const noexcept;
  [[nodiscard]] ReferenceDepthRange reference_depth_range() const noexcept;
  [[nodiscard]] std::string_view font_asset_fingerprint() const noexcept;
  [[nodiscard]] std::span<const PreparedTrack> tracks() const noexcept;
  [[nodiscard]] std::span<const PreparedCurveLayer>
  curve_layers() const noexcept;
  [[nodiscard]] std::span<const PreparedCurveSegment>
  curve_segments() const noexcept;
  [[nodiscard]] std::span<const PreparedCurvePoint>
  curve_points() const noexcept;
  [[nodiscard]] std::optional<CurvePick>
  pick_curve(const CurvePickQuery &query) const noexcept;

private:
  struct Impl;
  explicit PreparedScene(std::shared_ptr<const Impl> impl);
  std::shared_ptr<const Impl> impl_;
  friend class detail::ScenePreparer;
};

} // namespace welllog
