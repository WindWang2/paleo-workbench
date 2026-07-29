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

std::optional<CurvePick>
PreparedScene::pick_curve(const CurvePickQuery &query) const noexcept {
  const auto &position = query.scene_position;
  if (impl_ == nullptr || !std::isfinite(position.left.value) ||
      !std::isfinite(position.top.value) ||
      !std::isfinite(query.tolerance.value) || query.tolerance.value < 0.0 ||
      !std::isfinite(query.device_independent_pixels_per_millimetre) ||
      query.device_independent_pixels_per_millimetre <= 0.0) {
    return std::nullopt;
  }
  const auto tolerance_millimetres =
      query.tolerance.value / query.device_independent_pixels_per_millimetre;
  if (!std::isfinite(tolerance_millimetres)) {
    return std::nullopt;
  }

  const auto point_distance = [&](const PreparedCurvePoint &point) {
    return std::hypot(point.position.left.value - position.left.value,
                      point.position.top.value - position.top.value);
  };
  const auto segment_distance =
      [&](const PreparedCurvePoint &first,
          const PreparedCurvePoint &second) -> std::pair<double, double> {
    const auto delta_x = second.position.left.value - first.position.left.value;
    const auto delta_y = second.position.top.value - first.position.top.value;
    const auto length_squared = delta_x * delta_x + delta_y * delta_y;
    if (length_squared == 0.0) {
      return {point_distance(first), 0.0};
    }
    const auto projected =
        ((position.left.value - first.position.left.value) * delta_x +
         (position.top.value - first.position.top.value) * delta_y) /
        length_squared;
    const auto parameter = std::clamp(projected, 0.0, 1.0);
    const auto closest_x = first.position.left.value + parameter * delta_x;
    const auto closest_y = first.position.top.value + parameter * delta_y;
    return {std::hypot(closest_x - position.left.value,
                       closest_y - position.top.value),
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
    const auto first_bin = bin_for(position.top.value - tolerance_millimetres);
    const auto last_bin = bin_for(position.top.value + tolerance_millimetres);
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
    if (best_point != nullptr && best_distance <= tolerance_millimetres) {
      return CurvePick{
          .layer_id = layer.id,
          .curve_id = layer.curve_id,
          .sample_index = best_point->sample_index,
          .reference_depth = best_point->reference_depth,
          .display_depth = best_point->reference_depth,
          .value = best_point->value,
          .distance =
              DeviceIndependentPixels{
                  best_distance *
                  query.device_independent_pixels_per_millimetre},
      };
    }
  }
  return std::nullopt;
}

Result<PreparedScene>
detail::ScenePreparer::prepare(const WellLogDocument &document,
                               const ScenePresentation &presentation) noexcept {
  try {
    const auto depth_range = presentation.reference_depth_range();
    if (presentation.document_id() != document.id() ||
        depth_range.domain == DepthDomain::source_index ||
        depth_range.unit.empty() || !std::isfinite(depth_range.top) ||
        !std::isfinite(depth_range.bottom) ||
        depth_range.top >= depth_range.bottom ||
        !std::isfinite(depth_range.bottom - depth_range.top) ||
        !std::isfinite(presentation.physical_height().value) ||
        presentation.physical_height().value <= 0.0 ||
        presentation.tracks().empty() || presentation.scales().empty() ||
        presentation.curve_layers().empty()) {
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

      const auto sample_count = curve->values.length();
      for (std::uint64_t offset = 0; offset < sample_count; ++offset) {
        const auto sample_index = offset;
        const auto depth = axis->coordinates.value_as_double(sample_index);
        const auto value = curve->values.value_as_double(sample_index);
        const auto missing =
            (!curve->nulls.empty() && curve->nulls.is_null(sample_index)) ||
            !depth.has_value() || !value.has_value() ||
            !std::isfinite(*depth) || !std::isfinite(*value);
        if (missing) {
          close_segment();
          continue;
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
          return presentation_error(layer.id);
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
            pick_index.bins[bin].push_back(primitive_index);
          }
        }
      }
      scene->curve_pick_indices.push_back(std::move(pick_index));
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
