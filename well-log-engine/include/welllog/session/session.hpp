#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <span>
#include <vector>

#include <welllog/core/document.hpp>
#include <welllog/core/result.hpp>
#include <welllog/scene/image_pyramid.hpp>
#include <welllog/scene/scene.hpp>
#include <welllog/scene/text_engine.hpp>
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
};

struct SetViewportMetricsCommand {
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

// A closed Reference Depth Range on one Sampling Axis (ADR 0024). Selection is
// expressed in Reference Depth (the axis coordinate), never in Display Depth,
// screen pixels or LOD envelope points. `top <= bottom` and both finite.
struct SelectionDepthRange {
  double top{};
  double bottom{};
  friend constexpr bool operator==(SelectionDepthRange,
                                   SelectionDepthRange) = default;
};

// The shared semantic Selection Set state held by the session (ADR 0024). One
// selection per document, expressed over a single Sampling Axis: a Reference
// Depth Range plus the half-open `[first_row, last_row)` row span it maps to on
// that axis. `document_revision` is the revision the selection was made against
// (the invalidation key); `valid` becomes false when a document replacement
// could not safely remap the selection (the axis vanished or the range no
// longer fits), and a `selection_invalidated` event is published.
struct SelectionState {
  EntityId document_id;
  EntityId sampling_axis_id;
  SelectionDepthRange reference_depth_range;
  std::uint64_t first_row{};
  std::uint64_t last_row{}; // exclusive
  DocumentRevision document_revision;
  bool valid{true};
  friend constexpr bool operator==(const SelectionState &,
                                   const SelectionState &) = default;
};

// Selects a Reference Depth Range on a Sampling Axis of a document. The session
// maps the range to the half-open row span on that axis's coordinates.
struct SetSelectionCommand {
  EntityId document_id;
  EntityId sampling_axis_id;
  SelectionDepthRange reference_depth_range;
};

// Selects a half-open `[first_row, last_row)` row span on a Sampling Axis. The
// session maps the span back to a Reference Depth Range by reading the axis
// coordinate at the boundary rows. Drives graphic selection from a table.
struct SetRowSelectionCommand {
  EntityId document_id;
  EntityId sampling_axis_id;
  std::uint64_t first_row{};
  std::uint64_t last_row{}; // exclusive
};

// Clears any selection on a document.
struct ClearSelectionCommand {
  EntityId document_id;
};

// One curve tail-block in an AppendBatch (#162/#198, ADR 0031). The session
// appends `tail_values` to the existing curve identified by `curve_id` and
// `tail_coordinates` to that curve's sampling axis (`sampling_axis_id`), both as
// new immutable segments on the curve's/axis's composite buffer — the existing
// blocks are retained untouched with no contiguous copy. The two tail buffers
// must have equal length and a matching scalar type to the existing axis
// coordinates; the tail must continue the axis in its declared direction (no
// out-of-order or historical backfill — those require an explicit
// Replace/Patch).
struct CurveTailBlock {
  EntityId curve_id;
  EntityId sampling_axis_id;
  BufferView tail_coordinates;
  BufferView tail_values;
};

// Atomically appends a batch of curve tail-blocks to an existing document,
// producing one new Document Revision from the whole batch, or failing the
// whole batch (never a half-batch visible state). `target_revision` must be
// strictly greater than the document's current revision (monotonic revision
// gate — does not exist for SetDocumentCommand, which blindly replaces). Old
// data blocks are immutable and not re-copied. Out-of-order and historical
// backfill are rejected as Append.
struct AppendBatchCommand {
  EntityId document_id;
  DocumentRevision target_revision;
  std::vector<CurveTailBlock> blocks;
};

// How the session treats an existing viewport when an AppendBatchCommand
// produces a new revision (#200, ADR 0031 "Session 可固定视口或跟随最新深度").
// `fixed` (default) preserves the current depth window across the append;
// `follow_latest` advances the viewport's `bottom` to the appended tail's last
// reference depth, preserving the span (top = new_bottom - span). Applies only
// to AppendBatchCommand — a plain SetDocumentCommand always resets the viewport
// (it is a full document replacement).
enum class AppendViewportMode : std::uint8_t {
  fixed,
  follow_latest,
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
  selection_changed,
  selection_invalidated,
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
  missing_glyphs,
  fallback_font_used,
  text_engine_unavailable,
  nonpositive_log_values,
  scale_readability_hint,
  // An ImageSource's pyramid build failed (non-cancelled); the image layer is
  // degraded (no tiles). Stable code for the observable degradation (#184).
  image_pyramid_unavailable,
};

struct PerformanceBudgets {
  std::uint64_t maximum_cpu_derived_bytes{};
  std::uint64_t maximum_gpu_cache_bytes{256ULL * 1024ULL * 1024ULL};
  std::uint64_t maximum_upload_bytes_per_frame{4ULL * 1024ULL * 1024ULL};
  // Carve-out of the GPU cache reserved for decoded image-tile textures,
  // LRU-evicted (ADR 0034). Defaults to a quarter of the GPU cache.
  std::uint64_t maximum_image_texture_bytes{64ULL * 1024ULL * 1024ULL};
  double prefetch_viewports{2.0};
  std::uint64_t asynchronous_sample_threshold{16'384};
  // Image-pyramid build options (#184): tile size + derived-metadata byte
  // budget for the ImagePyramidMap the session builds from ImageSource
  // entities. metadata-only (no pixel decode — ADR 0045); the host configures
  // LOD here, mirroring how curve-LOD budgets flow through this struct.
  ImagePyramidOptions image_pyramid_options{};
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
  [[nodiscard]] Result<CommandReceipt>
  execute(const SetViewportMetricsCommand &command);
  [[nodiscard]] Result<CommandReceipt> execute(const PanDepthCommand &command);
  [[nodiscard]] Result<CommandReceipt>
  execute(const ZoomDepthAtCommand &command);
  [[nodiscard]] Result<CommandReceipt>
  execute(const ResetViewportCommand &command);
  [[nodiscard]] Result<CommandReceipt>
  execute(const SetCrosshairCommand &command);
  [[nodiscard]] Result<CommandReceipt>
  execute(const SetSelectionCommand &command);
  [[nodiscard]] Result<CommandReceipt>
  execute(const SetRowSelectionCommand &command);
  [[nodiscard]] Result<CommandReceipt>
  execute(const ClearSelectionCommand &command);
  [[nodiscard]] Result<CommandReceipt>
  execute(const AppendBatchCommand &command);
  // Installs the text pipeline used to shape annotations and labels during
  // scene preparation (ADR 0029). Without an engine, text layers prepare
  // empty and a text_engine_unavailable diagnostic is published.
  void set_text_engine(std::shared_ptr<TextEngine> text_engine) noexcept;
  [[nodiscard]] std::span<const ViewEvent> events() const noexcept;
  void clear_events() noexcept;
  [[nodiscard]] std::span<const Diagnostic> diagnostics() const noexcept;
  [[nodiscard]] std::optional<Error>
  diagnostic_error(std::uint64_t diagnostic_id) const noexcept;
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
  // The shared semantic Selection Set entry for a document (ADR 0024). Empty
  // when the document has no selection.
  [[nodiscard]] std::optional<SelectionState>
  selection(EntityId document_id) const noexcept;
  // The append viewport mode for a document (#200): whether an
  // AppendBatchCommand preserves the current viewport (`fixed`, the default) or
  // advances its bottom to the new tail depth (`follow_latest`). Returns `fixed`
  // when no mode has been set.
  [[nodiscard]] AppendViewportMode
  append_viewport_mode(EntityId document_id) const noexcept;
  // Sets the append viewport mode for a document (#200). The host/view uses
  // this to choose Fixed vs Follow-Latest behaviour; takes effect on the next
  // AppendBatchCommand for that document. Mirrors how other interaction state
  // (selection, crosshair) is exposed on the session.
  void set_append_viewport_mode(EntityId document_id,
                                AppendViewportMode mode) noexcept;
  [[nodiscard]] ViewEventObserverId
  subscribe_view_events(ViewEventObserver observer) noexcept;
  void unsubscribe_view_events(ViewEventObserverId observer_id) noexcept;
  void poll_async() noexcept;
  [[nodiscard]] PerformanceBudgets performance_budgets() const noexcept;
  // Replaces the performance budgets (#184: the host updates image-pyramid
  // build options via the view). Takes effect on the next document LOD build.
  void set_performance_budgets(PerformanceBudgets budgets) noexcept;
  [[nodiscard]] std::optional<PerformanceSnapshot>
  performance_snapshot(EntityId document_id) const noexcept;

private:
  // Shared apply path for the selection commands (depth-range or row-span
  // source). Resolves, stores, versions, and publishes. Returns the receipt or
  // an error. Defined in the .cpp; `from_rows` selects the row→range path.
  [[nodiscard]] Result<CommandReceipt>
  apply_selection(EntityId document_id, EntityId axis_id,
                  SelectionDepthRange range, std::uint64_t first_row,
                  std::uint64_t last_row, bool from_rows);

  struct Impl;
  std::unique_ptr<Impl> impl_;
};

} // namespace welllog
