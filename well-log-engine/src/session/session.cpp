#include <welllog/session/session.hpp>

#include "scene/prepare.hpp"

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

template <typename T>
[[nodiscard]] double load_as_double(const BufferView &buffer,
                                    std::uint64_t index) noexcept {
  T value{};
  std::memcpy(&value, buffer.data() + index * buffer.stride_bytes(), sizeof(T));
  return static_cast<double>(value);
}

[[nodiscard]] double load_as_double(const BufferView &buffer,
                                    std::uint64_t index) noexcept {
  switch (buffer.scalar_type()) {
  case ScalarType::float32:
    return load_as_double<float>(buffer, index);
  case ScalarType::float64:
    return load_as_double<double>(buffer, index);
  case ScalarType::int16:
    return load_as_double<std::int16_t>(buffer, index);
  case ScalarType::int32:
    return load_as_double<std::int32_t>(buffer, index);
  case ScalarType::int64:
    return load_as_double<std::int64_t>(buffer, index);
  case ScalarType::uint8:
    return load_as_double<std::uint8_t>(buffer, index);
  case ScalarType::uint16:
    return load_as_double<std::uint16_t>(buffer, index);
  case ScalarType::uint32:
    return load_as_double<std::uint32_t>(buffer, index);
  case ScalarType::uint64:
    return load_as_double<std::uint64_t>(buffer, index);
  }
  return std::numeric_limits<double>::quiet_NaN();
}

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

[[nodiscard]] bool axis_is_ordered(const SamplingAxis &axis) noexcept {
  switch (axis.coordinates.scalar_type()) {
  case ScalarType::float32:
    return axis_is_ordered<float>(axis.coordinates, axis.direction);
  case ScalarType::float64:
    return axis_is_ordered<double>(axis.coordinates, axis.direction);
  case ScalarType::int16:
    return axis_is_ordered<std::int16_t>(axis.coordinates, axis.direction);
  case ScalarType::int32:
    return axis_is_ordered<std::int32_t>(axis.coordinates, axis.direction);
  case ScalarType::int64:
    return axis_is_ordered<std::int64_t>(axis.coordinates, axis.direction);
  case ScalarType::uint8:
    return axis_is_ordered<std::uint8_t>(axis.coordinates, axis.direction);
  case ScalarType::uint16:
    return axis_is_ordered<std::uint16_t>(axis.coordinates, axis.direction);
  case ScalarType::uint32:
    return axis_is_ordered<std::uint32_t>(axis.coordinates, axis.direction);
  case ScalarType::uint64:
    return axis_is_ordered<std::uint64_t>(axis.coordinates, axis.direction);
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

struct LodBuildOutput {
  bool cancelled{};
  bool failed{};
  std::uint64_t derived_bytes{};
  std::unordered_map<EntityId, CurveLodPyramid, EntityIdHash> pyramids;
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
  bool failed{};
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

struct CurvePreparation {
  DocumentRevision revision;
  std::uint64_t generation{};
  PreparationState state{PreparationState::unavailable};
  std::uint64_t derived_bytes{};
  std::uint64_t maximum_derived_bytes{};
  std::unordered_map<EntityId, CurveLodPyramid, EntityIdHash> pyramids;
};

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
  std::unordered_map<EntityId, DepthViewport, EntityIdHash> viewport_defaults;
  std::unordered_map<EntityId, CrosshairState, EntityIdHash> crosshairs;
  std::unordered_map<EntityId, CurvePreparation, EntityIdHash> preparations;
  std::unordered_map<EntityId, std::uint64_t, EntityIdHash> frame_generations;
  std::vector<std::unique_ptr<LodTask>> lod_tasks;
  std::vector<std::unique_ptr<FrameTask>> frame_tasks;
  std::vector<ViewEvent> events;
  std::vector<Diagnostic> diagnostics;
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
};

WellLogSession::WellLogSession() : WellLogSession(PerformanceBudgets{}) {}
WellLogSession::WellLogSession(PerformanceBudgets budgets)
    : impl_(std::make_unique<Impl>()) {
  impl_->budgets = budgets;
}
WellLogSession::~WellLogSession() = default;
WellLogSession::WellLogSession(WellLogSession &&) noexcept = default;
WellLogSession &WellLogSession::operator=(WellLogSession &&) noexcept = default;

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
        for (const auto &curve : document->curves()) {
          const auto axis =
              std::find_if(document->sampling_axes().begin(),
                           document->sampling_axes().end(),
                           [&](const SamplingAxis &candidate) {
                             return candidate.id == curve.sampling_axis_id;
                           });
          if (axis != document->sampling_axes().end()) {
            maximum_derived_bytes +=
                (axis->coordinates.length() *
                     scalar_size_bytes(axis->coordinates.scalar_type()) +
                 curve.values.length() *
                     scalar_size_bytes(curve.values.scalar_type())) /
                4;
          }
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
      task->worker = std::jthread([document, state, per_curve_budget](
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
              output.failed = true;
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
              output.failed = !output.cancelled;
              break;
            }
            output.derived_bytes += pyramid.value().statistics().derived_bytes;
            output.pyramids.emplace(curve.id, std::move(pyramid).value());
          }
        } catch (...) {
          output.failed = true;
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
    impl_->viewport_defaults.erase(document_id);
    impl_->crosshairs.erase(document_id);
    impl_->frame_generations.erase(document_id);
    if (asynchronous) {
      impl_->preparations.insert_or_assign(
          document_id, CurvePreparation{
                           .revision = revision,
                           .generation = generation,
                           .state = PreparationState::pending,
                           .derived_bytes = 0,
                           .maximum_derived_bytes = maximum_derived_bytes,
                           .pyramids = {},
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
    if (preparation != impl_->preparations.end() &&
        preparation->second.state == PreparationState::pending) {
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
      impl_->viewport_defaults.reserve(impl_->viewport_defaults.size() + 1);
      for (auto &existing_task : impl_->frame_tasks) {
        if (existing_task->document_id == document_id) {
          existing_task->worker.request_stop();
        }
      }
      impl_->frame_generations.erase(document_id);
      impl_->presentations.insert_or_assign(document_id, command.presentation);
      impl_->viewports.insert_or_assign(document_id, initial_viewport);
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
          .asynchronous_preparation_started = true,
          .diagnostic_id = std::nullopt,
      };
    }

    auto prepared = preparation != impl_->preparations.end() &&
                            preparation->second.state == PreparationState::ready
                        ? detail::ScenePreparer::prepare(
                              *document->second, command.presentation,
                              preparation->second.pyramids,
                              CurveLodQuery{
                                  .viewport_top = initial_viewport.top,
                                  .viewport_bottom = initial_viewport.bottom,
                                  .pixel_height = default_frame_pixel_height,
                                  .prefetch_viewports = 0.0,
                              })
                        : detail::ScenePreparer::prepare(*document->second,
                                                         command.presentation);
    if (!prepared) {
      return prepared.error();
    }

    auto scene =
        std::make_shared<const PreparedScene>(std::move(prepared).value());
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
        .asynchronous_preparation_started = false,
        .diagnostic_id = std::nullopt,
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
  try {
    if (!valid_viewport(command.viewport)) {
      return viewport_error(command.document_id);
    }
    const auto document = impl_->documents.find(command.document_id);
    const auto viewport = impl_->viewports.find(command.document_id);
    if (document == impl_->documents.end() ||
        viewport == impl_->viewports.end()) {
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
      auto state = std::make_shared<FrameTaskState>();
      frame_task = std::make_unique<FrameTask>();
      frame_task->document_id = command.document_id;
      frame_task->revision = document->second->revision();
      frame_task->generation = frame_generation;
      frame_task->state = state;
      const auto task_document = document->second;
      const auto task_presentation = presentation->second;
      const auto task_pyramids = preparation->second.pyramids;
      const auto query = CurveLodQuery{
          .viewport_top = command.viewport.top,
          .viewport_bottom = command.viewport.bottom,
          .pixel_height = default_frame_pixel_height,
          .prefetch_viewports = impl_->budgets.prefetch_viewports,
      };
      frame_task->worker =
          std::jthread([task_document, task_presentation, task_pyramids, query,
                        state](std::stop_token stop_token) {
            auto output = FrameBuildOutput{};
            if (stop_token.stop_requested()) {
              output.cancelled = true;
            } else {
              try {
                auto prepared = detail::ScenePreparer::prepare(
                    *task_document, task_presentation, task_pyramids, query);
                if (stop_token.stop_requested()) {
                  output.cancelled = true;
                } else if (prepared.has_value()) {
                  output.scene = std::make_shared<const PreparedScene>(
                      std::move(prepared).value());
                } else {
                  output.failed = true;
                }
              } catch (...) {
                output.failed = true;
              }
            }
            const auto guard = std::lock_guard{state->mutex};
            state->output = std::move(output);
            state->finished = true;
          });
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

void WellLogSession::poll_async() noexcept {
  try {
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
      } else if (output.failed) {
        preparation->second.state = PreparationState::unavailable;
      } else {
        preparation->second.state = PreparationState::ready;
        preparation->second.derived_bytes = output.derived_bytes;
        preparation->second.pyramids = std::move(output.pyramids);
        auto frame_ready = false;
        const auto document =
            impl_->documents.find(completed_task->document_id);
        const auto presentation =
            impl_->presentations.find(completed_task->document_id);
        const auto viewport =
            impl_->viewports.find(completed_task->document_id);
        if (document != impl_->documents.end() &&
            presentation != impl_->presentations.end() &&
            viewport != impl_->viewports.end()) {
          auto prepared = detail::ScenePreparer::prepare(
              *document->second, presentation->second,
              preparation->second.pyramids,
              CurveLodQuery{
                  .viewport_top = viewport->second.top,
                  .viewport_bottom = viewport->second.bottom,
                  .pixel_height = default_frame_pixel_height,
                  .prefetch_viewports = impl_->budgets.prefetch_viewports,
              });
          if (prepared.has_value()) {
            impl_->prepared_scenes.insert_or_assign(
                completed_task->document_id,
                std::make_shared<const PreparedScene>(
                    std::move(prepared).value()));
            frame_ready = true;
          } else {
            preparation->second.state = PreparationState::unavailable;
          }
        }
        ++impl_->completed_lod_tasks;
        if (frame_ready &&
            impl_->state_version < std::numeric_limits<std::uint64_t>::max()) {
          ++impl_->state_version;
          const auto event = ViewEvent{
              .kind = ViewEventKind::frame_ready,
              .state_version = impl_->state_version,
              .document_id = completed_task->document_id,
              .document_revision = completed_task->revision,
          };
          impl_->events.push_back(event);
          impl_->notify_observers(event);
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
      const auto generation =
          impl_->frame_generations.find(completed_task->document_id);
      const auto document = impl_->documents.find(completed_task->document_id);
      const auto current =
          generation != impl_->frame_generations.end() &&
          generation->second == completed_task->generation &&
          document != impl_->documents.end() &&
          document->second->revision() == completed_task->revision;
      if (output.cancelled) {
        ++impl_->cancelled_lod_tasks;
      } else if (!current) {
        ++impl_->discarded_lod_tasks;
      } else if (output.failed || output.scene == nullptr) {
        impl_->frame_generations.erase(generation);
      } else {
        impl_->prepared_scenes.insert_or_assign(completed_task->document_id,
                                                std::move(output.scene));
        impl_->frame_generations.erase(generation);
        ++impl_->completed_lod_tasks;
        if (impl_->state_version < std::numeric_limits<std::uint64_t>::max()) {
          ++impl_->state_version;
          const auto event = ViewEvent{
              .kind = ViewEventKind::frame_ready,
              .state_version = impl_->state_version,
              .document_id = completed_task->document_id,
              .document_revision = completed_task->revision,
          };
          impl_->events.push_back(event);
          impl_->notify_observers(event);
        }
      }
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

std::span<const ViewEvent> WellLogSession::events() const noexcept {
  return impl_->events;
}

void WellLogSession::clear_events() noexcept { impl_->events.clear(); }

std::span<const Diagnostic> WellLogSession::diagnostics() const noexcept {
  return impl_->diagnostics;
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

std::optional<CrosshairState>
WellLogSession::crosshair(EntityId document_id) const noexcept {
  const auto found = impl_->crosshairs.find(document_id);
  return found == impl_->crosshairs.end()
             ? std::nullopt
             : std::optional<CrosshairState>{found->second};
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
