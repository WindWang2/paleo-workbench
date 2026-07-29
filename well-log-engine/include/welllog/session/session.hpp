#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <span>
#include <vector>

#include <welllog/core/document.hpp>
#include <welllog/core/result.hpp>
#include <welllog/scene/scene.hpp>
#include <welllog/session/export.hpp>

namespace welllog {

struct SetDocumentCommand {
  WellLogDocument document;
};

struct SetPresentationCommand {
  ScenePresentation presentation;
};

struct DepthViewport {
  double top{};
  double bottom{};
  friend constexpr bool operator==(DepthViewport, DepthViewport) = default;
};

struct CrosshairState {
  double track_fraction{};
  double display_depth{};
  friend constexpr bool operator==(CrosshairState, CrosshairState) = default;
};

struct SetViewportCommand {
  EntityId document_id;
  DepthViewport viewport;
  std::uint32_t pixel_height{};
};

struct PanDepthCommand {
  EntityId document_id;
  double display_depth_delta{};
};

struct ZoomDepthAtCommand {
  EntityId document_id;
  double anchor_display_depth{};
  double span_factor{};
};

struct ResetViewportCommand {
  EntityId document_id;
};

struct SetCrosshairCommand {
  EntityId document_id;
  std::optional<CrosshairState> crosshair;
};

struct CommandReceipt {
  std::uint64_t state_version{};
  EntityId document_id;
  DocumentRevision document_revision;
  bool asynchronous_preparation_started{};
  std::optional<std::uint64_t> diagnostic_id;
};

enum class ViewEventKind : std::uint8_t {
  documents_changed,
  diagnostic_published,
  presentation_changed,
  viewport_changed,
  crosshair_changed,
  frame_ready,
};

struct ViewEvent {
  ViewEventKind kind{ViewEventKind::documents_changed};
  std::uint64_t state_version{};
  EntityId document_id;
  DocumentRevision document_revision;
};

using ViewEventObserverId = std::uint64_t;
using ViewEventObserver = std::function<void(const ViewEvent &)>;

enum class DiagnosticCode : std::uint16_t {
  missing_samples,
  asynchronous_preparation_failed,
};

struct PerformanceBudgets {
  std::uint64_t maximum_cpu_derived_bytes{};
  std::uint64_t maximum_gpu_cache_bytes{256ULL * 1024ULL * 1024ULL};
  std::uint64_t maximum_upload_bytes_per_frame{4ULL * 1024ULL * 1024ULL};
  double prefetch_viewports{2.0};
  std::uint64_t asynchronous_sample_threshold{16'384};
};

enum class PreparationState : std::uint8_t {
  unavailable,
  pending,
  ready,
};

struct PerformanceSnapshot {
  DocumentRevision document_revision;
  PreparationState preparation_state{PreparationState::unavailable};
  std::uint64_t cpu_derived_bytes{};
  std::uint64_t maximum_cpu_derived_bytes{};
  std::uint64_t maximum_gpu_cache_bytes{};
  std::uint64_t maximum_upload_bytes_per_frame{};
  std::uint64_t completed_tasks{};
  std::uint64_t cancelled_tasks{};
  std::uint64_t discarded_tasks{};
  bool frame_preparation_pending{};
};

struct Diagnostic {
  std::uint64_t id{};
  DiagnosticCode code{DiagnosticCode::missing_samples};
  Severity severity{Severity::warning};
  EntityId document_id;
  EntityId entity_id;
  DocumentRevision document_revision;
  std::uint64_t occurrence_count{};
  std::optional<ErrorCode> error_code;
  std::optional<MessageKey> message;
};

class WELLLOG_SESSION_API WellLogSession {
public:
  WellLogSession();
  explicit WellLogSession(PerformanceBudgets budgets);
  ~WellLogSession();
  WellLogSession(WellLogSession &&) noexcept;
  WellLogSession &operator=(WellLogSession &&) noexcept;
  WellLogSession(const WellLogSession &) = delete;
  WellLogSession &operator=(const WellLogSession &) = delete;

  [[nodiscard]] Result<CommandReceipt> execute(SetDocumentCommand command);
  [[nodiscard]] Result<CommandReceipt>
  execute(const SetPresentationCommand &command);
  [[nodiscard]] Result<CommandReceipt>
  execute(const SetViewportCommand &command);
  [[nodiscard]] Result<CommandReceipt> execute(const PanDepthCommand &command);
  [[nodiscard]] Result<CommandReceipt>
  execute(const ZoomDepthAtCommand &command);
  [[nodiscard]] Result<CommandReceipt>
  execute(const ResetViewportCommand &command);
  [[nodiscard]] Result<CommandReceipt>
  execute(const SetCrosshairCommand &command);
  [[nodiscard]] std::span<const ViewEvent> events() const noexcept;
  void clear_events() noexcept;
  [[nodiscard]] std::span<const Diagnostic> diagnostics() const noexcept;
  [[nodiscard]] std::shared_ptr<const WellLogDocument>
  document(EntityId id) const noexcept;
  [[nodiscard]] std::shared_ptr<const PreparedScene>
  prepared_scene(EntityId document_id) const noexcept;
  [[nodiscard]] std::optional<DepthViewport>
  viewport(EntityId document_id) const noexcept;
  [[nodiscard]] std::optional<std::uint32_t>
  viewport_pixel_height(EntityId document_id) const noexcept;
  [[nodiscard]] std::optional<CrosshairState>
  crosshair(EntityId document_id) const noexcept;
  [[nodiscard]] ViewEventObserverId
  subscribe_view_events(ViewEventObserver observer) noexcept;
  void unsubscribe_view_events(ViewEventObserverId observer_id) noexcept;
  void poll_async() noexcept;
  [[nodiscard]] PerformanceBudgets performance_budgets() const noexcept;
  [[nodiscard]] std::optional<PerformanceSnapshot>
  performance_snapshot(EntityId document_id) const noexcept;

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

} // namespace welllog
