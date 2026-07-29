#include "scene/prepare.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace welllog {
namespace {

[[nodiscard]] Error presentation_error(EntityId entity_id = {}) {
  return Error{
      .code = ErrorCode::invalid_presentation,
      .severity = Severity::error,
      .entity_id = entity_id.is_nil() ? std::nullopt
                                      : std::optional<EntityId>{entity_id},
      .message = MessageKey::presentation_invalid,
      .arguments = {},
  };
}

[[nodiscard]] Error cancellation_error() {
  return Error{
      .code = ErrorCode::operation_cancelled,
      .severity = Severity::error,
      .entity_id = std::nullopt,
      .message = MessageKey::operation_cancelled,
      .arguments = {},
  };
}

} // namespace

struct ScenePresentation::Impl {
  EntityId document_id;
  DepthDomain reference_depth_domain;
  std::string reference_depth_unit;
  double reference_depth_top{};
  double reference_depth_bottom{};
  Millimetres physical_height;
  std::string font_asset_fingerprint;
  std::vector<TrackSpec> tracks;
  std::vector<TrackScaleSpec> scales;
  std::vector<CurveLayerSpec> curve_layers;
  std::vector<PatternDefinition> patterns;
  std::vector<IntervalLayerSpec> interval_layers;
  std::vector<MarkerLayerSpec> marker_layers;
  std::vector<SymbolLayerSpec> symbol_layers;
  std::vector<TextLayerSpec> text_layers;
};

ScenePresentation::ScenePresentation() = default;
ScenePresentation::~ScenePresentation() = default;
ScenePresentation::ScenePresentation(const ScenePresentation &) = default;
ScenePresentation &
ScenePresentation::operator=(const ScenePresentation &) = default;
ScenePresentation::ScenePresentation(ScenePresentation &&) noexcept = default;
ScenePresentation &
ScenePresentation::operator=(ScenePresentation &&) noexcept = default;

ScenePresentation::ScenePresentation(std::shared_ptr<const Impl> impl)
    : impl_(std::move(impl)) {}

EntityId ScenePresentation::document_id() const noexcept {
  return impl_ == nullptr ? EntityId{} : impl_->document_id;
}

ReferenceDepthRange ScenePresentation::reference_depth_range() const noexcept {
  return impl_ == nullptr ? ReferenceDepthRange{}
                          : ReferenceDepthRange{
                                .domain = impl_->reference_depth_domain,
                                .unit = impl_->reference_depth_unit,
                                .top = impl_->reference_depth_top,
                                .bottom = impl_->reference_depth_bottom,
                            };
}

Millimetres ScenePresentation::physical_height() const noexcept {
  return impl_ == nullptr ? Millimetres{} : impl_->physical_height;
}

std::string_view ScenePresentation::font_asset_fingerprint() const noexcept {
  return impl_ == nullptr ? std::string_view{}
                          : std::string_view{impl_->font_asset_fingerprint};
}

std::span<const TrackSpec> ScenePresentation::tracks() const noexcept {
  return impl_ == nullptr ? std::span<const TrackSpec>{}
                          : std::span<const TrackSpec>{impl_->tracks};
}

std::span<const TrackScaleSpec> ScenePresentation::scales() const noexcept {
  return impl_ == nullptr ? std::span<const TrackScaleSpec>{}
                          : std::span<const TrackScaleSpec>{impl_->scales};
}

std::span<const CurveLayerSpec>
ScenePresentation::curve_layers() const noexcept {
  return impl_ == nullptr
             ? std::span<const CurveLayerSpec>{}
             : std::span<const CurveLayerSpec>{impl_->curve_layers};
}

std::span<const PatternDefinition>
ScenePresentation::patterns() const noexcept {
  return impl_ == nullptr
             ? std::span<const PatternDefinition>{}
             : std::span<const PatternDefinition>{impl_->patterns};
}

std::span<const IntervalLayerSpec>
ScenePresentation::interval_layers() const noexcept {
  return impl_ == nullptr
             ? std::span<const IntervalLayerSpec>{}
             : std::span<const IntervalLayerSpec>{impl_->interval_layers};
}

std::span<const MarkerLayerSpec>
ScenePresentation::marker_layers() const noexcept {
  return impl_ == nullptr
             ? std::span<const MarkerLayerSpec>{}
             : std::span<const MarkerLayerSpec>{impl_->marker_layers};
}

std::span<const SymbolLayerSpec>
ScenePresentation::symbol_layers() const noexcept {
  return impl_ == nullptr
             ? std::span<const SymbolLayerSpec>{}
             : std::span<const SymbolLayerSpec>{impl_->symbol_layers};
}

std::span<const TextLayerSpec>
ScenePresentation::text_layers() const noexcept {
  return impl_ == nullptr
             ? std::span<const TextLayerSpec>{}
             : std::span<const TextLayerSpec>{impl_->text_layers};
}

struct ScenePresentationBuilder::Impl {
  ScenePresentation::Impl presentation;
  bool allocation_failed{};
};

ScenePresentationBuilder::ScenePresentationBuilder(
    EntityId document_id, ReferenceDepthRange reference_depth_range,
    Millimetres physical_height,
    std::string_view font_asset_fingerprint) noexcept {
  try {
    impl_ = std::make_unique<Impl>(Impl{
        .presentation =
            ScenePresentation::Impl{
                .document_id = document_id,
                .reference_depth_domain = reference_depth_range.domain,
                .reference_depth_unit = std::string{reference_depth_range.unit},
                .reference_depth_top = reference_depth_range.top,
                .reference_depth_bottom = reference_depth_range.bottom,
                .physical_height = physical_height,
                .font_asset_fingerprint = std::string{font_asset_fingerprint},
                .tracks = {},
                .scales = {},
                .curve_layers = {},
                .patterns = {},
                .interval_layers = {},
                .marker_layers = {},
                .symbol_layers = {},
                .text_layers = {},
            },
        .allocation_failed = false,
    });
  } catch (...) {
    impl_.reset();
  }
}

ScenePresentationBuilder::~ScenePresentationBuilder() = default;
ScenePresentationBuilder::ScenePresentationBuilder(
    ScenePresentationBuilder &&) noexcept = default;
ScenePresentationBuilder &ScenePresentationBuilder::operator=(
    ScenePresentationBuilder &&) noexcept = default;

ScenePresentationBuilder &
ScenePresentationBuilder::add_track(const TrackSpec &track) noexcept {
  if (impl_ == nullptr || impl_->allocation_failed) {
    return *this;
  }
  try {
    impl_->presentation.tracks.push_back(track);
  } catch (...) {
    impl_->allocation_failed = true;
  }
  return *this;
}

ScenePresentationBuilder &
ScenePresentationBuilder::add_scale(const TrackScaleSpec &scale) noexcept {
  if (impl_ == nullptr || impl_->allocation_failed) {
    return *this;
  }
  try {
    impl_->presentation.scales.push_back(scale);
  } catch (...) {
    impl_->allocation_failed = true;
  }
  return *this;
}

ScenePresentationBuilder &ScenePresentationBuilder::add_curve_layer(
    const CurveLayerSpec &layer) noexcept {
  if (impl_ == nullptr || impl_->allocation_failed) {
    return *this;
  }
  try {
    impl_->presentation.curve_layers.push_back(layer);
  } catch (...) {
    impl_->allocation_failed = true;
  }
  return *this;
}

ScenePresentationBuilder &
ScenePresentationBuilder::add_pattern(const PatternDefinition &pattern) noexcept {
  if (impl_ == nullptr || impl_->allocation_failed) {
    return *this;
  }
  try {
    impl_->presentation.patterns.push_back(pattern);
  } catch (...) {
    impl_->allocation_failed = true;
  }
  return *this;
}

ScenePresentationBuilder &ScenePresentationBuilder::add_interval_layer(
    const IntervalLayerSpec &layer) noexcept {
  if (impl_ == nullptr || impl_->allocation_failed) {
    return *this;
  }
  try {
    impl_->presentation.interval_layers.push_back(layer);
  } catch (...) {
    impl_->allocation_failed = true;
  }
  return *this;
}

ScenePresentationBuilder &ScenePresentationBuilder::add_marker_layer(
    const MarkerLayerSpec &layer) noexcept {
  if (impl_ == nullptr || impl_->allocation_failed) {
    return *this;
  }
  try {
    impl_->presentation.marker_layers.push_back(layer);
  } catch (...) {
    impl_->allocation_failed = true;
  }
  return *this;
}

ScenePresentationBuilder &ScenePresentationBuilder::add_symbol_layer(
    const SymbolLayerSpec &layer) noexcept {
  if (impl_ == nullptr || impl_->allocation_failed) {
    return *this;
  }
  try {
    impl_->presentation.symbol_layers.push_back(layer);
  } catch (...) {
    impl_->allocation_failed = true;
  }
  return *this;
}

ScenePresentationBuilder &ScenePresentationBuilder::add_text_layer(
    const TextLayerSpec &layer) noexcept {
  if (impl_ == nullptr || impl_->allocation_failed) {
    return *this;
  }
  try {
    impl_->presentation.text_layers.push_back(layer);
  } catch (...) {
    impl_->allocation_failed = true;
  }
  return *this;
}

ScenePresentation ScenePresentationBuilder::build() const noexcept {
  if (impl_ == nullptr || impl_->allocation_failed) {
    return {};
  }
  try {
    return ScenePresentation{
        std::make_shared<ScenePresentation::Impl>(impl_->presentation)};
  } catch (...) {
    return {};
  }
}

struct PreparedScene::Impl {
  struct PickPrimitive {
    std::uint64_t first_point{};
    std::uint64_t second_point{};
  };

  struct CurvePickIndex {
    std::uint64_t layer_index{};
    double bin_height{};
    std::vector<PickPrimitive> primitives;
    std::vector<std::vector<std::uint64_t>> bins;
  };

  EntityId document_id;
  DocumentRevision document_revision;
  Millimetres physical_width;
  Millimetres physical_height;
  DepthDomain reference_depth_domain;
  std::string reference_depth_unit;
  double reference_depth_top{};
  double reference_depth_bottom{};
  std::string font_asset_fingerprint;
  std::vector<PreparedTrack> tracks;
  std::vector<PreparedCurveLayer> curve_layers;
  std::vector<PreparedCurveSegment> curve_segments;
  std::vector<PreparedCurvePoint> curve_points;
  std::vector<CurvePickIndex> curve_pick_indices;
  std::vector<PatternDefinition> patterns;
  std::vector<PreparedIntervalLayer> interval_layers;
  std::vector<PreparedInterval> intervals;
  std::vector<PreparedMarkerLayer> marker_layers;
  std::vector<PreparedMarker> markers;
  std::vector<PreparedSymbolLayer> symbol_layers;
  std::vector<PreparedSymbol> symbols;
};

PreparedScene::PreparedScene() = default;
PreparedScene::~PreparedScene() = default;
PreparedScene::PreparedScene(const PreparedScene &) = default;
PreparedScene &PreparedScene::operator=(const PreparedScene &) = default;
PreparedScene::PreparedScene(PreparedScene &&) noexcept = default;
PreparedScene &PreparedScene::operator=(PreparedScene &&) noexcept = default;

PreparedScene::PreparedScene(std::shared_ptr<const Impl> impl)
    : impl_(std::move(impl)) {}

EntityId PreparedScene::document_id() const noexcept {
  return impl_ == nullptr ? EntityId{} : impl_->document_id;
}

DocumentRevision PreparedScene::document_revision() const noexcept {
  return impl_ == nullptr ? DocumentRevision{} : impl_->document_revision;
}

Millimetres PreparedScene::physical_width() const noexcept {
  return impl_ == nullptr ? Millimetres{} : impl_->physical_width;
}

Millimetres PreparedScene::physical_height() const noexcept {
  return impl_ == nullptr ? Millimetres{} : impl_->physical_height;
}

ReferenceDepthRange PreparedScene::reference_depth_range() const noexcept {
  return impl_ == nullptr ? ReferenceDepthRange{}
                          : ReferenceDepthRange{
                                .domain = impl_->reference_depth_domain,
                                .unit = impl_->reference_depth_unit,
                                .top = impl_->reference_depth_top,
                                .bottom = impl_->reference_depth_bottom,
                            };
}

std::string_view PreparedScene::font_asset_fingerprint() const noexcept {
  return impl_ == nullptr ? std::string_view{}
                          : std::string_view{impl_->font_asset_fingerprint};
}

std::span<const PreparedTrack> PreparedScene::tracks() const noexcept {
  return impl_ == nullptr ? std::span<const PreparedTrack>{}
                          : std::span<const PreparedTrack>{impl_->tracks};
}

std::span<const PreparedCurveLayer>
PreparedScene::curve_layers() const noexcept {
  return impl_ == nullptr
             ? std::span<const PreparedCurveLayer>{}
             : std::span<const PreparedCurveLayer>{impl_->curve_layers};
}

std::span<const PreparedCurveSegment>
PreparedScene::curve_segments() const noexcept {
  return impl_ == nullptr
             ? std::span<const PreparedCurveSegment>{}
             : std::span<const PreparedCurveSegment>{impl_->curve_segments};
}

std::span<const PreparedCurvePoint>
PreparedScene::curve_points() const noexcept {
  return impl_ == nullptr
             ? std::span<const PreparedCurvePoint>{}
             : std::span<const PreparedCurvePoint>{impl_->curve_points};
}

std::span<const PatternDefinition>
PreparedScene::patterns() const noexcept {
  return impl_ == nullptr
             ? std::span<const PatternDefinition>{}
             : std::span<const PatternDefinition>{impl_->patterns};
}

std::span<const PreparedIntervalLayer>
PreparedScene::interval_layers() const noexcept {
  return impl_ == nullptr
             ? std::span<const PreparedIntervalLayer>{}
             : std::span<const PreparedIntervalLayer>{impl_->interval_layers};
}

std::span<const PreparedInterval> PreparedScene::intervals() const noexcept {
  return impl_ == nullptr
             ? std::span<const PreparedInterval>{}
             : std::span<const PreparedInterval>{impl_->intervals};
}

std::span<const PreparedMarkerLayer>
PreparedScene::marker_layers() const noexcept {
  return impl_ == nullptr
             ? std::span<const PreparedMarkerLayer>{}
             : std::span<const PreparedMarkerLayer>{impl_->marker_layers};
}

std::span<const PreparedMarker> PreparedScene::markers() const noexcept {
  return impl_ == nullptr
             ? std::span<const PreparedMarker>{}
             : std::span<const PreparedMarker>{impl_->markers};
}

std::span<const PreparedSymbolLayer>
PreparedScene::symbol_layers() const noexcept {
  return impl_ == nullptr
             ? std::span<const PreparedSymbolLayer>{}
             : std::span<const PreparedSymbolLayer>{impl_->symbol_layers};
}

std::span<const PreparedSymbol> PreparedScene::symbols() const noexcept {
  return impl_ == nullptr
             ? std::span<const PreparedSymbol>{}
             : std::span<const PreparedSymbol>{impl_->symbols};
}

std::optional<CurvePick>
PreparedScene::pick_curve(const CurvePickQuery &query) const noexcept {
  const auto &position = query.scene_position;
  if (impl_ == nullptr || !std::isfinite(position.left.value) ||
      !std::isfinite(position.top.value) ||
      !std::isfinite(query.tolerance.value) || query.tolerance.value < 0.0 ||
      !std::isfinite(
          query.horizontal_device_independent_pixels_per_millimetre) ||
      query.horizontal_device_independent_pixels_per_millimetre <= 0.0 ||
      !std::isfinite(query.vertical_device_independent_pixels_per_millimetre) ||
      query.vertical_device_independent_pixels_per_millimetre <= 0.0) {
    return std::nullopt;
  }
  const auto vertical_tolerance_millimetres =
      query.tolerance.value /
      query.vertical_device_independent_pixels_per_millimetre;
  if (!std::isfinite(vertical_tolerance_millimetres)) {
    return std::nullopt;
  }

  const auto point_distance = [&](const PreparedCurvePoint &point) {
    return std::hypot(
        (point.position.left.value - position.left.value) *
            query.horizontal_device_independent_pixels_per_millimetre,
        (point.position.top.value - position.top.value) *
            query.vertical_device_independent_pixels_per_millimetre);
  };
  const auto segment_distance =
      [&](const PreparedCurvePoint &first,
          const PreparedCurvePoint &second) -> std::pair<double, double> {
    const auto delta_x =
        (second.position.left.value - first.position.left.value) *
        query.horizontal_device_independent_pixels_per_millimetre;
    const auto delta_y =
        (second.position.top.value - first.position.top.value) *
        query.vertical_device_independent_pixels_per_millimetre;
    const auto length_squared = delta_x * delta_x + delta_y * delta_y;
    if (length_squared == 0.0) {
      return {point_distance(first), 0.0};
    }
    const auto projected =
        ((position.left.value - first.position.left.value) *
             query.horizontal_device_independent_pixels_per_millimetre *
             delta_x +
         (position.top.value - first.position.top.value) *
             query.vertical_device_independent_pixels_per_millimetre *
             delta_y) /
        length_squared;
    const auto parameter = std::clamp(projected, 0.0, 1.0);
    const auto closest_x =
        first.position.left.value *
            query.horizontal_device_independent_pixels_per_millimetre +
        parameter * delta_x;
    const auto closest_y =
        first.position.top.value *
            query.vertical_device_independent_pixels_per_millimetre +
        parameter * delta_y;
    return {
        std::hypot(
            closest_x -
                position.left.value *
                    query.horizontal_device_independent_pixels_per_millimetre,
            closest_y -
                position.top.value *
                    query.vertical_device_independent_pixels_per_millimetre),
        parameter};
  };

  for (auto index_iterator = impl_->curve_pick_indices.rbegin();
       index_iterator != impl_->curve_pick_indices.rend(); ++index_iterator) {
    const auto &pick_index = *index_iterator;
    const auto &layer =
        impl_->curve_layers[static_cast<std::size_t>(pick_index.layer_index)];
    const auto track = std::find_if(impl_->tracks.begin(), impl_->tracks.end(),
                                    [&](const PreparedTrack &candidate) {
                                      return candidate.id == layer.track_id;
                                    });
    if (track == impl_->tracks.end() ||
        position.left.value < track->clip.left.value ||
        position.top.value < track->clip.top.value ||
        position.left.value >
            track->clip.left.value + track->clip.width.value ||
        position.top.value > track->clip.top.value + track->clip.height.value) {
      continue;
    }

    const PreparedCurvePoint *best_point = nullptr;
    auto best_distance = std::numeric_limits<double>::infinity();
    const auto bin_for = [&](double top) {
      if (top <= 0.0) {
        return std::size_t{0};
      }
      if (top >= impl_->physical_height.value) {
        return pick_index.bins.size() - std::size_t{1};
      }
      return std::min(static_cast<std::size_t>(top / pick_index.bin_height),
                      pick_index.bins.size() - std::size_t{1});
    };
    const auto first_bin =
        bin_for(position.top.value - vertical_tolerance_millimetres);
    const auto last_bin =
        bin_for(position.top.value + vertical_tolerance_millimetres);
    for (auto bin = first_bin; bin <= last_bin; ++bin) {
      for (const auto primitive_index : pick_index.bins[bin]) {
        const auto &primitive =
            pick_index.primitives[static_cast<std::size_t>(primitive_index)];
        const auto &first =
            impl_
                ->curve_points[static_cast<std::size_t>(primitive.first_point)];
        const auto &second = impl_->curve_points[static_cast<std::size_t>(
            primitive.second_point)];
        if (primitive.first_point == primitive.second_point) {
          const auto distance = point_distance(first);
          if (distance < best_distance) {
            best_distance = distance;
            best_point = &first;
          }
          continue;
        }
        const auto [distance, parameter] = segment_distance(first, second);
        if (distance < best_distance) {
          best_distance = distance;
          best_point = parameter <= 0.5 ? &first : &second;
        }
      }
    }
    if (best_point != nullptr && best_distance <= query.tolerance.value) {
      return CurvePick{
          .layer_id = layer.id,
          .curve_id = layer.curve_id,
          .sample_index = best_point->sample_index,
          .reference_depth = best_point->reference_depth,
          .display_depth = best_point->reference_depth,
          .value = best_point->value,
          .distance = DeviceIndependentPixels{best_distance},
      };
    }
  }
  return std::nullopt;
}

Result<PreparedScene>
detail::ScenePreparer::prepare(const WellLogDocument &document,
                               const ScenePresentation &presentation) noexcept {
  return prepare_impl(document, presentation, nullptr, nullptr, {});
}

Result<PreparedScene> detail::ScenePreparer::prepare(
    const WellLogDocument &document, const ScenePresentation &presentation,
    const CurveLodMap &curve_lods, const CurveLodQuery &query,
    std::stop_token stop_token) noexcept {
  return prepare_impl(document, presentation, &curve_lods, &query, stop_token);
}

Result<PreparedScene> detail::ScenePreparer::prepare_impl(
    const WellLogDocument &document, const ScenePresentation &presentation,
    const CurveLodMap *curve_lods, const CurveLodQuery *query,
    std::stop_token stop_token) noexcept {
  try {
    if (stop_token.stop_requested()) {
      return cancellation_error();
    }
    const auto depth_range = presentation.reference_depth_range();
    const auto layer_count =
        presentation.curve_layers().size() +
        presentation.interval_layers().size() +
        presentation.marker_layers().size() +
        presentation.symbol_layers().size() + presentation.text_layers().size();
    if (presentation.document_id() != document.id() ||
        depth_range.domain == DepthDomain::source_index ||
        depth_range.unit.empty() || !std::isfinite(depth_range.top) ||
        !std::isfinite(depth_range.bottom) ||
        depth_range.top >= depth_range.bottom ||
        !std::isfinite(depth_range.bottom - depth_range.top) ||
        !std::isfinite(presentation.physical_height().value) ||
        presentation.physical_height().value <= 0.0 ||
        presentation.tracks().empty() || layer_count == 0) {
      return presentation_error(presentation.document_id());
    }

    std::unordered_set<EntityId, EntityIdHash> ids;
    ids.insert(document.id());
    for (const auto &axis : document.sampling_axes()) {
      ids.insert(axis.id);
    }
    for (const auto &curve : document.curves()) {
      ids.insert(curve.id);
    }
    std::unordered_map<EntityId, PhysicalRect, EntityIdHash> track_bounds;
    auto scene = std::make_shared<PreparedScene::Impl>();
    scene->document_id = document.id();
    scene->document_revision = document.revision();
    scene->physical_height = presentation.physical_height();
    scene->reference_depth_domain = depth_range.domain;
    scene->reference_depth_unit = std::string{depth_range.unit};
    scene->reference_depth_top = depth_range.top;
    scene->reference_depth_bottom = depth_range.bottom;
    scene->font_asset_fingerprint =
        std::string{presentation.font_asset_fingerprint()};
    scene->tracks.reserve(presentation.tracks().size());
    scene->curve_layers.reserve(presentation.curve_layers().size());

    double left{};
    for (const auto &track : presentation.tracks()) {
      if (stop_token.stop_requested()) {
        return cancellation_error();
      }
      if (track.id.is_nil() || !ids.insert(track.id).second ||
          !std::isfinite(track.width.value) || track.width.value <= 0.0) {
        return presentation_error(track.id);
      }
      const auto right = left + track.width.value;
      if (!std::isfinite(right)) {
        return presentation_error(track.id);
      }
      const auto bounds = PhysicalRect{
          .left = Millimetres{left},
          .top = Millimetres{0.0},
          .width = track.width,
          .height = presentation.physical_height(),
      };
      scene->tracks.push_back(PreparedTrack{
          .id = track.id,
          .bounds = bounds,
          .clip = bounds,
          .z_order = track.z_order,
      });
      track_bounds.emplace(track.id, bounds);
      left = right;
    }
    scene->physical_width = Millimetres{left};

    std::unordered_map<EntityId, const TrackScaleSpec *, EntityIdHash> scales;
    for (const auto &scale : presentation.scales()) {
      if (stop_token.stop_requested()) {
        return cancellation_error();
      }
      if (scale.id.is_nil() || !ids.insert(scale.id).second ||
          !track_bounds.contains(scale.track_id) ||
          scale.mode != ScaleMode::linear || !std::isfinite(scale.minimum) ||
          !std::isfinite(scale.maximum) || scale.minimum >= scale.maximum ||
          !std::isfinite(scale.maximum - scale.minimum) || scale.unit.empty()) {
        return presentation_error(scale.id);
      }
      scales.emplace(scale.id, &scale);
    }

    std::vector<const CurveLayerSpec *> ordered_layers;
    ordered_layers.reserve(presentation.curve_layers().size());
    for (const auto &layer : presentation.curve_layers()) {
      ordered_layers.push_back(&layer);
    }
    std::stable_sort(ordered_layers.begin(), ordered_layers.end(),
                     [](const CurveLayerSpec *left_layer,
                        const CurveLayerSpec *right_layer) {
                       if (left_layer->z_order != right_layer->z_order) {
                         return left_layer->z_order < right_layer->z_order;
                       }
                       return left_layer->id < right_layer->id;
                     });

    for (const auto *layer_pointer : ordered_layers) {
      if (stop_token.stop_requested()) {
        return cancellation_error();
      }
      const auto &layer = *layer_pointer;
      const auto scale = scales.find(layer.scale_id);
      const auto curve =
          std::find_if(document.curves().begin(), document.curves().end(),
                       [&](const Curve &candidate) {
                         return candidate.id == layer.curve_id;
                       });
      if (layer.id.is_nil() || !ids.insert(layer.id).second ||
          !track_bounds.contains(layer.track_id) || scale == scales.end() ||
          scale->second->track_id != layer.track_id ||
          curve == document.curves().end() ||
          !std::isfinite(layer.line_width.value) ||
          layer.line_width.value <= 0.0) {
        return presentation_error(layer.id);
      }

      const auto axis = std::find_if(
          document.sampling_axes().begin(), document.sampling_axes().end(),
          [&](const SamplingAxis &candidate) {
            return candidate.id == curve->sampling_axis_id;
          });
      if (axis == document.sampling_axes().end()) {
        return presentation_error(layer.id);
      }
      if (axis->domain != depth_range.domain ||
          axis->domain == DepthDomain::source_index ||
          axis->unit != depth_range.unit ||
          curve->unit != scale->second->unit) {
        return presentation_error(layer.id);
      }

      const auto bounds = track_bounds.at(layer.track_id);
      const auto first_segment =
          static_cast<std::uint64_t>(scene->curve_segments.size());
      std::optional<std::uint64_t> segment_start;
      const auto close_segment = [&]() {
        if (!segment_start.has_value()) {
          return;
        }
        scene->curve_segments.push_back(PreparedCurveSegment{
            .layer_id = layer.id,
            .first_point = *segment_start,
            .point_count =
                static_cast<std::uint64_t>(scene->curve_points.size()) -
                *segment_start,
        });
        segment_start.reset();
      };

      const auto append_sample = [&](std::uint64_t sample_index) {
        const auto depth = axis->coordinates.value_as_double(sample_index);
        const auto value = curve->values.value_as_double(sample_index);
        const auto missing =
            (!curve->nulls.empty() && curve->nulls.is_null(sample_index)) ||
            !depth.has_value() || !value.has_value() ||
            !std::isfinite(*depth) || !std::isfinite(*value);
        if (missing) {
          close_segment();
          return true;
        }

        if (!segment_start.has_value()) {
          segment_start =
              static_cast<std::uint64_t>(scene->curve_points.size());
        }
        auto normalized_value =
            (*value - scale->second->minimum) /
            (scale->second->maximum - scale->second->minimum);
        if (scale->second->direction == ScaleDirection::right_to_left) {
          normalized_value = 1.0 - normalized_value;
        }
        const auto normalized_depth =
            (*depth - depth_range.top) / (depth_range.bottom - depth_range.top);
        const auto horizontal_offset = normalized_value * bounds.width.value;
        const auto left_position = bounds.left.value + horizontal_offset;
        const auto top_position =
            normalized_depth * presentation.physical_height().value;
        if (!std::isfinite(normalized_value) ||
            !std::isfinite(normalized_depth) ||
            !std::isfinite(horizontal_offset) ||
            !std::isfinite(left_position) || !std::isfinite(top_position)) {
          return false;
        }
        scene->curve_points.push_back(PreparedCurvePoint{
            .position =
                PhysicalPoint{
                    .left = Millimetres{left_position},
                    .top = Millimetres{top_position},
                },
            .sample_index = sample_index,
            .reference_depth = *depth,
            .value = *value,
        });
        return true;
      };

      const auto lod = curve_lods == nullptr ? CurveLodMap::const_iterator{}
                                             : curve_lods->find(curve->id);
      if (curve_lods != nullptr && query != nullptr &&
          lod != curve_lods->end()) {
        const auto selection = lod->second.query(*query, stop_token);
        if (!selection.has_value()) {
          return selection.error();
        }
        for (const auto &segment : selection.value().segments()) {
          close_segment();
          for (std::uint64_t offset = 0; offset < segment.point_count;
               ++offset) {
            if ((offset & std::uint64_t{4095}) == 0 &&
                stop_token.stop_requested()) {
              return cancellation_error();
            }
            const auto &point =
                selection.value().points()[static_cast<std::size_t>(
                    segment.first_point + offset)];
            if (!append_sample(point.sample_index)) {
              return presentation_error(layer.id);
            }
          }
          close_segment();
        }
      } else {
        const auto sample_count = curve->values.length();
        for (std::uint64_t sample_index = 0; sample_index < sample_count;
             ++sample_index) {
          if ((sample_index & std::uint64_t{4095}) == 0 &&
              stop_token.stop_requested()) {
            return cancellation_error();
          }
          if (!append_sample(sample_index)) {
            return presentation_error(layer.id);
          }
        }
      }
      close_segment();

      const auto layer_index =
          static_cast<std::uint64_t>(scene->curve_layers.size());
      scene->curve_layers.push_back(PreparedCurveLayer{
          .id = layer.id,
          .track_id = layer.track_id,
          .curve_id = layer.curve_id,
          .scale_id = layer.scale_id,
          .color = layer.color,
          .line_width = layer.line_width,
          .z_order = layer.z_order,
          .first_segment = first_segment,
          .segment_count =
              static_cast<std::uint64_t>(scene->curve_segments.size()) -
              first_segment,
      });

      PreparedScene::Impl::CurvePickIndex pick_index{
          .layer_index = layer_index,
          .bin_height = 0.0,
          .primitives = {},
          .bins = {},
      };
      constexpr std::size_t maximum_pick_bins = 2048;
      constexpr double target_pick_bin_height = 2.0;
      const auto requested_bin_count =
          std::ceil(scene->physical_height.value / target_pick_bin_height);
      const auto bin_count =
          requested_bin_count >= static_cast<double>(maximum_pick_bins)
              ? maximum_pick_bins
              : std::max(std::size_t{1},
                         static_cast<std::size_t>(requested_bin_count));
      pick_index.bin_height =
          scene->physical_height.value / static_cast<double>(bin_count);
      pick_index.bins.resize(bin_count);
      for (std::uint64_t segment_offset = 0;
           segment_offset < scene->curve_layers.back().segment_count;
           ++segment_offset) {
        if (stop_token.stop_requested()) {
          return cancellation_error();
        }
        const auto &segment = scene->curve_segments[static_cast<std::size_t>(
            first_segment + segment_offset)];
        if (segment.point_count == 0) {
          continue;
        }
        const auto primitive_count =
            segment.point_count == 1 ? std::uint64_t{1}
                                     : segment.point_count - std::uint64_t{1};
        for (std::uint64_t primitive_offset = 0;
             primitive_offset < primitive_count; ++primitive_offset) {
          if (stop_token.stop_requested()) {
            return cancellation_error();
          }
          const auto first_point =
              segment.first_point +
              (segment.point_count == 1 ? std::uint64_t{0} : primitive_offset);
          const auto second_point =
              segment.point_count == 1 ? first_point : first_point + 1;
          const auto &first =
              scene->curve_points[static_cast<std::size_t>(first_point)];
          const auto &second =
              scene->curve_points[static_cast<std::size_t>(second_point)];
          const auto minimum_top =
              std::min(first.position.top.value, second.position.top.value);
          const auto maximum_top =
              std::max(first.position.top.value, second.position.top.value);
          if (maximum_top < 0.0 || minimum_top > scene->physical_height.value) {
            continue;
          }
          const auto primitive_index =
              static_cast<std::uint64_t>(pick_index.primitives.size());
          pick_index.primitives.push_back(PreparedScene::Impl::PickPrimitive{
              .first_point = first_point,
              .second_point = second_point,
          });
          const auto bin_for = [&](double top) {
            if (top <= 0.0) {
              return std::size_t{0};
            }
            if (top >= scene->physical_height.value) {
              return bin_count - std::size_t{1};
            }
            return std::min(
                static_cast<std::size_t>(top / pick_index.bin_height),
                bin_count - std::size_t{1});
          };
          const auto first_bin = bin_for(minimum_top);
          const auto last_bin = bin_for(maximum_top);
          for (auto bin = first_bin; bin <= last_bin; ++bin) {
            if (stop_token.stop_requested()) {
              return cancellation_error();
            }
            pick_index.bins[bin].push_back(primitive_index);
          }
        }
      }
      scene->curve_pick_indices.push_back(std::move(pick_index));
    }

    // Pattern definitions are the single vector source of truth shared by
    // the screen and vector backends (ADR 0020). They are validated against
    // the untrusted-asset limits of ADR 0042 before entering the scene.
    constexpr std::size_t maximum_pattern_primitives = 256;
    constexpr std::size_t maximum_polyline_points = 1024;
    constexpr double maximum_tile_extent_millimetres = 500.0;
    std::unordered_set<EntityId, EntityIdHash> pattern_ids;
    scene->patterns.reserve(presentation.patterns().size());
    for (const auto &pattern : presentation.patterns()) {
      if (stop_token.stop_requested()) {
        return cancellation_error();
      }
      if (pattern.id.is_nil() || !ids.insert(pattern.id).second ||
          !std::isfinite(pattern.tile_width.value) ||
          pattern.tile_width.value <= 0.0 ||
          pattern.tile_width.value > maximum_tile_extent_millimetres ||
          !std::isfinite(pattern.tile_height.value) ||
          pattern.tile_height.value <= 0.0 ||
          pattern.tile_height.value > maximum_tile_extent_millimetres ||
          !std::isfinite(pattern.rotation_degrees) ||
          !std::isfinite(pattern.stroke_width.value) ||
          pattern.stroke_width.value <= 0.0 ||
          pattern.stroke_width.value > maximum_tile_extent_millimetres ||
          !std::isfinite(pattern.scene_anchor.left.value) ||
          !std::isfinite(pattern.scene_anchor.top.value) ||
          pattern.primitives.size() > maximum_pattern_primitives) {
        return presentation_error(pattern.id);
      }
      bool primitives_valid = true;
      const auto point_valid = [](const PhysicalPoint &point) {
        return std::isfinite(point.left.value) &&
               std::isfinite(point.top.value);
      };
      for (const auto &primitive : pattern.primitives) {
        if (const auto *line = std::get_if<PatternLine>(&primitive)) {
          primitives_valid = point_valid(line->from) && point_valid(line->to);
        } else if (const auto *polyline =
                       std::get_if<PatternPolyline>(&primitive)) {
          primitives_valid =
              polyline->points.size() >= 2 &&
              polyline->points.size() <= maximum_polyline_points &&
              std::all_of(polyline->points.begin(), polyline->points.end(),
                          point_valid);
        } else {
          const auto &circle = std::get<PatternCircle>(primitive);
          primitives_valid = point_valid(circle.center) &&
                             std::isfinite(circle.radius.value) &&
                             circle.radius.value > 0.0 &&
                             circle.radius.value <=
                                 maximum_tile_extent_millimetres;
        }
        if (!primitives_valid) {
          break;
        }
      }
      if (!primitives_valid) {
        return presentation_error(pattern.id);
      }
      pattern_ids.insert(pattern.id);
      scene->patterns.push_back(pattern);
    }

    const auto depth_to_top = [&](double reference_depth) {
      return (reference_depth - depth_range.top) /
             (depth_range.bottom - depth_range.top) *
             presentation.physical_height().value;
    };

    std::vector<const IntervalLayerSpec *> ordered_interval_layers;
    ordered_interval_layers.reserve(presentation.interval_layers().size());
    for (const auto &layer : presentation.interval_layers()) {
      ordered_interval_layers.push_back(&layer);
    }
    std::stable_sort(
        ordered_interval_layers.begin(), ordered_interval_layers.end(),
        [](const IntervalLayerSpec *left_layer,
           const IntervalLayerSpec *right_layer) {
          if (left_layer->z_order != right_layer->z_order) {
            return left_layer->z_order < right_layer->z_order;
          }
          return left_layer->id < right_layer->id;
        });

    for (const auto *layer_pointer : ordered_interval_layers) {
      if (stop_token.stop_requested()) {
        return cancellation_error();
      }
      const auto &layer = *layer_pointer;
      const auto bounds = track_bounds.find(layer.track_id);
      if (layer.id.is_nil() || !ids.insert(layer.id).second ||
          bounds == track_bounds.end() ||
          (layer.draw_labels &&
           (!std::isfinite(layer.label_font_size.value) ||
            layer.label_font_size.value <= 0.0))) {
        return presentation_error(layer.id);
      }
      const auto first_interval =
          static_cast<std::uint64_t>(scene->intervals.size());
      for (const auto &interval : document.intervals()) {
        if (stop_token.stop_requested()) {
          return cancellation_error();
        }
        if (!interval.pattern_id.is_nil() &&
            !pattern_ids.contains(interval.pattern_id)) {
          return presentation_error(interval.id);
        }
        if (interval.bottom_reference_depth <= depth_range.top ||
            interval.top_reference_depth >= depth_range.bottom) {
          continue;
        }
        const auto unclipped_top = depth_to_top(interval.top_reference_depth);
        const auto unclipped_bottom =
            depth_to_top(interval.bottom_reference_depth);
        const auto top = std::clamp(unclipped_top, 0.0,
                                    presentation.physical_height().value);
        const auto bottom = std::clamp(unclipped_bottom, 0.0,
                                       presentation.physical_height().value);
        const auto height = bottom - top;
        if (!std::isfinite(top) || !std::isfinite(bottom) ||
            !std::isfinite(height) || height <= 0.0) {
          continue;
        }
        scene->intervals.push_back(PreparedInterval{
            .layer_id = layer.id,
            .interval_id = interval.id,
            .rect =
                PhysicalRect{
                    .left = bounds->second.left,
                    .top = Millimetres{top},
                    .width = bounds->second.width,
                    .height = Millimetres{height},
                },
            .fill_color = interval.fill_color,
            .pattern_id = interval.pattern_id,
            .top_reference_depth = interval.top_reference_depth,
            .bottom_reference_depth = interval.bottom_reference_depth,
            .label_run_index = no_text_run,
        });
      }
      scene->interval_layers.push_back(PreparedIntervalLayer{
          .id = layer.id,
          .track_id = layer.track_id,
          .z_order = layer.z_order,
          .first_interval = first_interval,
          .interval_count =
              static_cast<std::uint64_t>(scene->intervals.size()) -
              first_interval,
      });
    }

    std::vector<const MarkerLayerSpec *> ordered_marker_layers;
    ordered_marker_layers.reserve(presentation.marker_layers().size());
    for (const auto &layer : presentation.marker_layers()) {
      ordered_marker_layers.push_back(&layer);
    }
    std::stable_sort(
        ordered_marker_layers.begin(), ordered_marker_layers.end(),
        [](const MarkerLayerSpec *left_layer,
           const MarkerLayerSpec *right_layer) {
          if (left_layer->z_order != right_layer->z_order) {
            return left_layer->z_order < right_layer->z_order;
          }
          return left_layer->id < right_layer->id;
        });

    for (const auto *layer_pointer : ordered_marker_layers) {
      if (stop_token.stop_requested()) {
        return cancellation_error();
      }
      const auto &layer = *layer_pointer;
      if (layer.id.is_nil() || !ids.insert(layer.id).second ||
          !track_bounds.contains(layer.track_id) ||
          !std::isfinite(layer.line_width.value) ||
          layer.line_width.value <= 0.0 ||
          (layer.draw_labels &&
           (!std::isfinite(layer.label_font_size.value) ||
            layer.label_font_size.value <= 0.0))) {
        return presentation_error(layer.id);
      }
      const auto first_marker =
          static_cast<std::uint64_t>(scene->markers.size());
      for (const auto &marker : document.markers()) {
        if (stop_token.stop_requested()) {
          return cancellation_error();
        }
        if (marker.reference_depth < depth_range.top ||
            marker.reference_depth > depth_range.bottom) {
          continue;
        }
        const auto top = depth_to_top(marker.reference_depth);
        if (!std::isfinite(top)) {
          continue;
        }
        scene->markers.push_back(PreparedMarker{
            .layer_id = layer.id,
            .marker_id = marker.id,
            .display_top = Millimetres{top},
            .reference_depth = marker.reference_depth,
            .label_run_index = no_text_run,
        });
      }
      scene->marker_layers.push_back(PreparedMarkerLayer{
          .id = layer.id,
          .track_id = layer.track_id,
          .z_order = layer.z_order,
          .line_color = layer.line_color,
          .line_width = layer.line_width,
          .first_marker = first_marker,
          .marker_count =
              static_cast<std::uint64_t>(scene->markers.size()) - first_marker,
      });
    }

    std::vector<const SymbolLayerSpec *> ordered_symbol_layers;
    ordered_symbol_layers.reserve(presentation.symbol_layers().size());
    for (const auto &layer : presentation.symbol_layers()) {
      ordered_symbol_layers.push_back(&layer);
    }
    std::stable_sort(
        ordered_symbol_layers.begin(), ordered_symbol_layers.end(),
        [](const SymbolLayerSpec *left_layer,
           const SymbolLayerSpec *right_layer) {
          if (left_layer->z_order != right_layer->z_order) {
            return left_layer->z_order < right_layer->z_order;
          }
          return left_layer->id < right_layer->id;
        });

    for (const auto *layer_pointer : ordered_symbol_layers) {
      if (stop_token.stop_requested()) {
        return cancellation_error();
      }
      const auto &layer = *layer_pointer;
      const auto bounds = track_bounds.find(layer.track_id);
      if (layer.id.is_nil() || !ids.insert(layer.id).second ||
          bounds == track_bounds.end() ||
          !std::isfinite(layer.symbol_size.value) ||
          layer.symbol_size.value <= 0.0) {
        return presentation_error(layer.id);
      }
      const auto first_symbol =
          static_cast<std::uint64_t>(scene->symbols.size());
      for (const auto &symbol : document.symbols()) {
        if (stop_token.stop_requested()) {
          return cancellation_error();
        }
        if (symbol.reference_depth < depth_range.top ||
            symbol.reference_depth > depth_range.bottom) {
          continue;
        }
        const auto top = depth_to_top(symbol.reference_depth);
        const auto left = bounds->second.left.value +
                          symbol.track_fraction * bounds->second.width.value;
        if (!std::isfinite(top) || !std::isfinite(left)) {
          continue;
        }
        scene->symbols.push_back(PreparedSymbol{
            .layer_id = layer.id,
            .symbol_id = symbol.id,
            .center =
                PhysicalPoint{
                    .left = Millimetres{left},
                    .top = Millimetres{top},
                },
            .kind = symbol.kind,
            .reference_depth = symbol.reference_depth,
        });
      }
      scene->symbol_layers.push_back(PreparedSymbolLayer{
          .id = layer.id,
          .track_id = layer.track_id,
          .z_order = layer.z_order,
          .color = layer.color,
          .symbol_size = layer.symbol_size,
          .first_symbol = first_symbol,
          .symbol_count =
              static_cast<std::uint64_t>(scene->symbols.size()) - first_symbol,
      });
    }

    for (const auto &layer : presentation.text_layers()) {
      if (layer.id.is_nil() || !ids.insert(layer.id).second ||
          !track_bounds.contains(layer.track_id)) {
        return presentation_error(layer.id);
      }
    }
    return PreparedScene{std::move(scene)};
  } catch (const std::bad_alloc &) {
    return Error{
        .code = ErrorCode::resource_exhausted,
        .severity = Severity::error,
        .entity_id = presentation.document_id(),
        .message = MessageKey::resource_exhausted,
        .arguments = {},
    };
  } catch (...) {
    return Error{
        .code = ErrorCode::internal_error,
        .severity = Severity::error,
        .entity_id = presentation.document_id(),
        .message = MessageKey::internal_error,
        .arguments = {},
    };
  }
}

} // namespace welllog
