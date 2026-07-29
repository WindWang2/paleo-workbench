#include <welllog/scene/curve_lod.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <optional>
#include <utility>
#include <vector>

namespace welllog {
namespace {

[[nodiscard]] Error lod_error(ErrorCode code, MessageKey message) {
  return Error{
      .code = code,
      .severity = Severity::error,
      .entity_id = std::nullopt,
      .message = message,
      .arguments = {},
  };
}

[[nodiscard]] bool valid_sample(const SamplingAxis &axis, const Curve &curve,
                                std::uint64_t index) noexcept {
  const auto depth = axis.coordinates.value_as_double(index);
  const auto value = curve.values.value_as_double(index);
  return (curve.nulls.empty() || !curve.nulls.is_null(index)) &&
         depth.has_value() && value.has_value() && std::isfinite(*depth) &&
         std::isfinite(*value);
}

struct Summary {
  std::uint32_t source_begin{};
  std::uint32_t source_end{};
  std::array<std::uint32_t, 4> indices{};
  std::uint8_t count{};
};

struct Level {
  std::uint64_t bucket_samples{};
  std::vector<Summary> summaries;
};

struct SourceRun {
  std::uint64_t begin{};
  std::uint64_t end{};
  std::vector<Level> levels;
};

struct SourceRange {
  std::uint64_t begin{};
  std::uint64_t end{};
};

[[nodiscard]] Summary summarize(const Curve &curve, std::uint64_t begin,
                                std::uint64_t end) {
  auto minimum_index = begin;
  auto maximum_index = begin;
  auto minimum = curve.values.value_as_double(begin).value();
  auto maximum = minimum;
  for (auto index = begin + 1; index < end; ++index) {
    const auto value = curve.values.value_as_double(index).value();
    if (value < minimum) {
      minimum = value;
      minimum_index = index;
    }
    if (value > maximum) {
      maximum = value;
      maximum_index = index;
    }
  }
  std::array<std::uint64_t, 4> candidates{
      begin,
      minimum_index,
      maximum_index,
      end - 1,
  };
  std::sort(candidates.begin(), candidates.end());

  Summary result{
      .source_begin = static_cast<std::uint32_t>(begin),
      .source_end = static_cast<std::uint32_t>(end),
      .indices = {},
      .count = 0,
  };
  for (const auto candidate : candidates) {
    if (result.count == 0 ||
        result.indices[static_cast<std::size_t>(result.count - 1)] !=
            candidate) {
      result.indices[static_cast<std::size_t>(result.count)] =
          static_cast<std::uint32_t>(candidate);
      ++result.count;
    }
  }
  return result;
}

[[nodiscard]] Summary summarize_children(const Curve &curve,
                                         std::span<const Summary> children) {
  std::array<std::uint32_t, 16> candidates{};
  std::size_t candidate_count{};
  for (const auto &child :
       children.first(std::min(children.size(), std::size_t{4}))) {
    const auto retained =
        std::min<std::size_t>(child.count, child.indices.size());
    for (std::size_t offset = 0; offset < retained; ++offset) {
      if (candidate_count == candidates.size()) {
        break;
      }
      candidates[candidate_count] = child.indices[offset];
      ++candidate_count;
    }
  }
  for (std::size_t index = 1; index < candidate_count; ++index) {
    const auto value = candidates[index];
    auto insertion = index;
    while (insertion > 0 && candidates[insertion - 1] > value) {
      candidates[insertion] = candidates[insertion - 1];
      --insertion;
    }
    candidates[insertion] = value;
  }
  auto unique_count = std::size_t{};
  for (std::size_t index = 0; index < candidate_count; ++index) {
    if (unique_count == 0 ||
        candidates[unique_count - 1] != candidates[index]) {
      candidates[unique_count] = candidates[index];
      ++unique_count;
    }
  }
  candidate_count = unique_count;

  auto minimum_index = candidates[0];
  auto maximum_index = candidates[0];
  auto minimum = curve.values.value_as_double(minimum_index).value();
  auto maximum = minimum;
  for (std::size_t offset = 1; offset < candidate_count; ++offset) {
    const auto index = candidates[offset];
    const auto value = curve.values.value_as_double(index).value();
    if (value < minimum) {
      minimum = value;
      minimum_index = index;
    }
    if (value > maximum) {
      maximum = value;
      maximum_index = index;
    }
  }
  std::array<std::uint32_t, 4> selected{
      candidates[0],
      minimum_index,
      maximum_index,
      candidates[candidate_count - 1],
  };
  std::sort(selected.begin(), selected.end());
  Summary result{
      .source_begin = children.front().source_begin,
      .source_end = children.back().source_end,
      .indices = {},
      .count = 0,
  };
  for (const auto index : selected) {
    if (result.count == 0 ||
        result.indices[static_cast<std::size_t>(result.count - 1)] != index) {
      result.indices[static_cast<std::size_t>(result.count)] = index;
      ++result.count;
    }
  }
  return result;
}

[[nodiscard]] SourceRange source_range(const SamplingAxis &axis, double top,
                                       double bottom) {
  const auto length = axis.coordinates.length();
  const auto first_matching = [&](auto before_range) {
    std::uint64_t low{};
    auto high = length;
    while (low < high) {
      const auto middle = low + (high - low) / 2;
      const auto depth = axis.coordinates.value_as_double(middle).value();
      if (before_range(depth)) {
        low = middle + 1;
      } else {
        high = middle;
      }
    }
    return low;
  };
  if (axis.direction == AxisDirection::increasing) {
    return SourceRange{
        .begin = first_matching([&](double depth) { return depth < top; }),
        .end = first_matching([&](double depth) { return depth <= bottom; }),
    };
  }
  return SourceRange{
      .begin = first_matching([&](double depth) { return depth > bottom; }),
      .end = first_matching([&](double depth) { return depth >= top; }),
  };
}

[[nodiscard]] std::uint64_t default_budget(const SamplingAxis &axis,
                                           const Curve &curve) noexcept {
  const auto axis_bytes = axis.coordinates.length() *
                          scalar_size_bytes(axis.coordinates.scalar_type());
  const auto curve_bytes =
      curve.values.length() * scalar_size_bytes(curve.values.scalar_type());
  return (axis_bytes + curve_bytes) / 4;
}

} // namespace

struct CurveLodSelection::Impl {
  bool uses_raw_samples{};
  std::uint64_t bucket_samples{};
  std::vector<CurveLodPoint> points;
  std::vector<CurveLodSegment> segments;
};

CurveLodSelection::CurveLodSelection() = default;
CurveLodSelection::~CurveLodSelection() = default;
CurveLodSelection::CurveLodSelection(const CurveLodSelection &) = default;
CurveLodSelection &
CurveLodSelection::operator=(const CurveLodSelection &) = default;
CurveLodSelection::CurveLodSelection(CurveLodSelection &&) noexcept = default;
CurveLodSelection &
CurveLodSelection::operator=(CurveLodSelection &&) noexcept = default;

CurveLodSelection::CurveLodSelection(std::shared_ptr<const Impl> impl)
    : impl_(std::move(impl)) {}

bool CurveLodSelection::uses_raw_samples() const noexcept {
  return impl_ == nullptr || impl_->uses_raw_samples;
}

std::uint64_t CurveLodSelection::bucket_samples() const noexcept {
  return impl_ == nullptr ? 1 : impl_->bucket_samples;
}

std::span<const CurveLodPoint> CurveLodSelection::points() const noexcept {
  return impl_ == nullptr ? std::span<const CurveLodPoint>{}
                          : std::span<const CurveLodPoint>{impl_->points};
}

std::span<const CurveLodSegment> CurveLodSelection::segments() const noexcept {
  return impl_ == nullptr ? std::span<const CurveLodSegment>{}
                          : std::span<const CurveLodSegment>{impl_->segments};
}

struct CurveLodPyramid::Impl {
  SamplingAxis axis;
  Curve curve;
  CurveLodBuildOptions options;
  std::vector<SourceRun> runs;
  CurveLodStatistics statistics;
};

CurveLodPyramid::CurveLodPyramid() = default;
CurveLodPyramid::~CurveLodPyramid() = default;
CurveLodPyramid::CurveLodPyramid(const CurveLodPyramid &) = default;
CurveLodPyramid &CurveLodPyramid::operator=(const CurveLodPyramid &) = default;
CurveLodPyramid::CurveLodPyramid(CurveLodPyramid &&) noexcept = default;
CurveLodPyramid &
CurveLodPyramid::operator=(CurveLodPyramid &&) noexcept = default;

CurveLodPyramid::CurveLodPyramid(std::shared_ptr<const Impl> impl)
    : impl_(std::move(impl)) {}

Result<CurveLodPyramid>
CurveLodPyramid::build(const SamplingAxis &axis, const Curve &curve,
                       CurveLodBuildOptions options,
                       std::stop_token stop_token) noexcept {
  try {
    if (stop_token.stop_requested()) {
      return lod_error(ErrorCode::operation_cancelled,
                       MessageKey::operation_cancelled);
    }
    if (curve.sampling_axis_id != axis.id ||
        axis.coordinates.length() != curve.values.length() ||
        axis.coordinates.length() == 0 ||
        axis.coordinates.length() > std::numeric_limits<std::uint32_t>::max() ||
        options.base_bucket_samples < 2) {
      return lod_error(ErrorCode::invalid_document,
                       MessageKey::document_structure_invalid);
    }
    if (options.maximum_derived_bytes == 0) {
      options.maximum_derived_bytes = default_budget(axis, curve);
    }
    auto impl = std::make_shared<Impl>(Impl{
        .axis = axis,
        .curve = curve,
        .options = options,
        .runs = {},
        .statistics =
            CurveLodStatistics{
                .source_samples = curve.values.length(),
                .source_bytes =
                    axis.coordinates.length() *
                        scalar_size_bytes(axis.coordinates.scalar_type()) +
                    curve.values.length() *
                        scalar_size_bytes(curve.values.scalar_type()) +
                    curve.nulls.byte_capacity(),
                .derived_bytes = 0,
                .maximum_derived_bytes = options.maximum_derived_bytes,
                .level_count = 0,
                .budget_limited = false,
            },
    });

    const auto sample_count = curve.values.length();
    std::uint64_t index{};
    std::uint64_t derived_bytes{};
    while (index < sample_count) {
      if (stop_token.stop_requested()) {
        return lod_error(ErrorCode::operation_cancelled,
                         MessageKey::operation_cancelled);
      }
      while (index < sample_count && !valid_sample(axis, curve, index)) {
        if ((index & std::uint64_t{4095}) == 0 && stop_token.stop_requested()) {
          return lod_error(ErrorCode::operation_cancelled,
                           MessageKey::operation_cancelled);
        }
        ++index;
      }
      if (index == sample_count) {
        break;
      }
      const auto run_begin = index;
      while (index < sample_count && valid_sample(axis, curve, index)) {
        if ((index & std::uint64_t{4095}) == 0 && stop_token.stop_requested()) {
          return lod_error(ErrorCode::operation_cancelled,
                           MessageKey::operation_cancelled);
        }
        ++index;
      }
      auto run = SourceRun{
          .begin = run_begin,
          .end = index,
          .levels = {},
      };
      auto bucket_samples = options.base_bucket_samples;
      while (options.algorithm == CurveLodAlgorithm::hierarchical &&
             bucket_samples <= run.end - run.begin) {
        if (stop_token.stop_requested()) {
          return lod_error(ErrorCode::operation_cancelled,
                           MessageKey::operation_cancelled);
        }
        Level level{
            .bucket_samples = bucket_samples,
            .summaries = {},
        };
        const auto bucket_count =
            (run.end - run.begin + bucket_samples - 1) / bucket_samples;
        const auto level_bytes = bucket_count * sizeof(Summary);
        if (level_bytes > options.maximum_derived_bytes - derived_bytes) {
          impl->statistics.budget_limited = true;
          break;
        }
        level.summaries.reserve(static_cast<std::size_t>(bucket_count));
        if (run.levels.empty()) {
          for (auto bucket_begin = run.begin; bucket_begin < run.end;
               bucket_begin += bucket_samples) {
            if (stop_token.stop_requested()) {
              return lod_error(ErrorCode::operation_cancelled,
                               MessageKey::operation_cancelled);
            }
            const auto bucket_end =
                std::min(run.end, bucket_begin + bucket_samples);
            level.summaries.push_back(
                summarize(curve, bucket_begin, bucket_end));
          }
        } else {
          const auto &children = run.levels.back().summaries;
          for (std::size_t child_begin = 0; child_begin < children.size();
               child_begin += 4) {
            if (stop_token.stop_requested()) {
              return lod_error(ErrorCode::operation_cancelled,
                               MessageKey::operation_cancelled);
            }
            const auto child_end =
                std::min(children.size(), child_begin + std::size_t{4});
            level.summaries.push_back(summarize_children(
                curve, std::span<const Summary>{children}.subspan(
                           child_begin, child_end - child_begin)));
          }
        }
        derived_bytes += level_bytes;
        ++impl->statistics.level_count;
        run.levels.push_back(std::move(level));
        if (bucket_samples > std::numeric_limits<std::uint64_t>::max() / 4) {
          break;
        }
        bucket_samples *= 4;
      }
      impl->runs.push_back(std::move(run));
    }
    impl->statistics.derived_bytes = derived_bytes;
    return CurveLodPyramid{std::move(impl)};
  } catch (const std::bad_alloc &) {
    return lod_error(ErrorCode::resource_exhausted,
                     MessageKey::resource_exhausted);
  } catch (...) {
    return lod_error(ErrorCode::internal_error, MessageKey::internal_error);
  }
}

Result<CurveLodSelection>
CurveLodPyramid::query(const CurveLodQuery &query) const noexcept {
  try {
    if (impl_ == nullptr || !std::isfinite(query.viewport_top) ||
        !std::isfinite(query.viewport_bottom) ||
        query.viewport_top >= query.viewport_bottom ||
        query.pixel_height == 0 || !std::isfinite(query.prefetch_viewports) ||
        query.prefetch_viewports < 0.0) {
      return lod_error(ErrorCode::invalid_viewport,
                       MessageKey::viewport_invalid);
    }

    const auto span = query.viewport_bottom - query.viewport_top;
    const auto query_top = query.viewport_top - span * query.prefetch_viewports;
    const auto query_bottom =
        query.viewport_bottom + span * query.prefetch_viewports;
    if (!std::isfinite(query_top) || !std::isfinite(query_bottom)) {
      return lod_error(ErrorCode::invalid_viewport,
                       MessageKey::viewport_invalid);
    }
    const auto visible =
        source_range(impl_->axis, query.viewport_top, query.viewport_bottom);
    const auto prefetched = source_range(impl_->axis, query_top, query_bottom);

    auto selection = std::make_shared<CurveLodSelection::Impl>();
    if (visible.begin >= visible.end || prefetched.begin >= prefetched.end) {
      return CurveLodSelection{std::move(selection)};
    }
    const auto visible_samples = visible.end - visible.begin;
    const auto samples_per_pixel = static_cast<double>(visible_samples) /
                                   static_cast<double>(query.pixel_height);
    const auto use_raw = samples_per_pixel <= 1.0;
    selection->uses_raw_samples = use_raw;
    selection->bucket_samples = 1;

    for (const auto &run : impl_->runs) {
      const auto begin = std::max(run.begin, prefetched.begin);
      const auto end = std::min(run.end, prefetched.end);
      if (begin >= end) {
        continue;
      }
      const auto first_point =
          static_cast<std::uint64_t>(selection->points.size());
      if (use_raw ||
          (run.levels.empty() &&
           impl_->options.algorithm == CurveLodAlgorithm::hierarchical)) {
        for (auto index = begin; index < end; ++index) {
          selection->points.push_back(CurveLodPoint{
              .sample_index = index,
              .reference_depth =
                  impl_->axis.coordinates.value_as_double(index).value(),
              .value = impl_->curve.values.value_as_double(index).value(),
          });
        }
      } else if (impl_->options.algorithm ==
                 CurveLodAlgorithm::scalar_reference) {
        auto bucket_samples = impl_->options.base_bucket_samples;
        while (static_cast<double>(bucket_samples) < samples_per_pixel &&
               bucket_samples <=
                   std::numeric_limits<std::uint64_t>::max() / 4) {
          bucket_samples *= 4;
        }
        selection->bucket_samples =
            std::max(selection->bucket_samples, bucket_samples);
        const auto first_bucket =
            run.begin + ((begin - run.begin) / bucket_samples) * bucket_samples;
        for (auto bucket_begin = first_bucket; bucket_begin < end;
             bucket_begin += bucket_samples) {
          const auto bucket_end =
              std::min(run.end, bucket_begin + bucket_samples);
          const auto summary =
              summarize(impl_->curve, bucket_begin, bucket_end);
          for (std::uint8_t offset = 0; offset < summary.count; ++offset) {
            const auto index =
                summary.indices[static_cast<std::size_t>(offset)];
            selection->points.push_back(CurveLodPoint{
                .sample_index = index,
                .reference_depth =
                    impl_->axis.coordinates.value_as_double(index).value(),
                .value = impl_->curve.values.value_as_double(index).value(),
            });
          }
        }
      } else {
        auto level = run.levels.end() - 1;
        for (auto candidate = run.levels.begin(); candidate != run.levels.end();
             ++candidate) {
          if (static_cast<double>(candidate->bucket_samples) >=
              samples_per_pixel) {
            level = candidate;
            break;
          }
        }
        selection->bucket_samples =
            std::max(selection->bucket_samples, level->bucket_samples);
        for (const auto &summary : level->summaries) {
          if (summary.source_end <= begin || summary.source_begin >= end) {
            continue;
          }
          for (std::uint8_t offset = 0; offset < summary.count; ++offset) {
            const auto index =
                summary.indices[static_cast<std::size_t>(offset)];
            selection->points.push_back(CurveLodPoint{
                .sample_index = index,
                .reference_depth =
                    impl_->axis.coordinates.value_as_double(index).value(),
                .value = impl_->curve.values.value_as_double(index).value(),
            });
          }
        }
      }
      selection->segments.push_back(CurveLodSegment{
          .first_point = first_point,
          .point_count = static_cast<std::uint64_t>(selection->points.size()) -
                         first_point,
      });
    }
    return CurveLodSelection{std::move(selection)};
  } catch (const std::bad_alloc &) {
    return lod_error(ErrorCode::resource_exhausted,
                     MessageKey::resource_exhausted);
  } catch (...) {
    return lod_error(ErrorCode::internal_error, MessageKey::internal_error);
  }
}

CurveLodStatistics CurveLodPyramid::statistics() const noexcept {
  return impl_ == nullptr ? CurveLodStatistics{} : impl_->statistics;
}

} // namespace welllog
