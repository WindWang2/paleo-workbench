#pragma once

// Well-log host adapter over the real well-log-engine C++ SDK.
//
// This widget is the C-line replacement for the Python WellLogHost bridge:
// it talks to welllog::WellLogSession / welllog::WellLogView directly — no
// Shiboken, no integer widget addresses, no Python. Selection/range changes
// are translated into the Qt-free pwb::viz::SelectionEventV1 contract so the
// application layer can fan them out without any Qt type.
//
// Native host surface (this branch, replacing the Python
// well_log_canvas_panel / welllog_engine_adapter glue):
//   * load_document / load_from_source — Workbench DTO or lazy curve source
//     into one atomic engine document transaction, with cooperative
//     cancellation checkpoints between curves.
//   * apply_track_layout — rebuild the presentation from a user layout
//     (visibility/order/log/scale colors) without touching the document.
//   * depth cursor callbacks — cross-panel linkage (the Python
//     set_link_cursor/jump_to_depth pair).
//   * interpretation events — selection hit-tested against document markers
//     (tops) and facies/lithology intervals.
//   * export_png / export_svg / export_pdf — engine-backed output.
//
// No Q_OBJECT on purpose (no custom signals): callbacks are std::function,
// keeping this translation unit moc-free.

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <QString>
#include <QWidget>

#include <pwb/viz/selection.hpp>
#include <pwb/viz/well_log_document_plan.hpp>
#include <pwb/viz/well_log_events.hpp>
#include <pwb/viz/well_log_track_layout.hpp>

namespace welllog {
class WellLogSession;
class WellLogView;
} // namespace welllog

namespace pwb::viz {

class WellLogHostWidget final : public QWidget {
public:
    using SelectionCallback = std::function<void(const SelectionEventV1&)>;
    using CursorCallback = std::function<void(const WellLogCursorEvent&)>;
    using InterpretationCallback =
        std::function<void(const WellLogInterpretationEvent&)>;

    explicit WellLogHostWidget(QWidget* parent = nullptr);
    ~WellLogHostWidget() override;

    WellLogHostWidget(const WellLogHostWidget&) = delete;
    WellLogHostWidget& operator=(const WellLogHostWidget&) = delete;

    // Parses a real LAS file with the engine's LasSourceAdapter, builds one
    // track per curve (linear scale from the curve's finite value range) and
    // submits document + presentation to the session. Returns false and
    // fills *error on parse or submission failure. Repeated loads are full
    // replacements: each parse produces a new engine document and the view
    // follows it; a failed reload keeps the previously loaded document.
    [[nodiscard]] bool load_las(const QString& path, QString* error = nullptr);

    // Submits a Workbench-side document (curves/intervals/markers) as one
    // atomic engine transaction. Curve sample buffers are adopted zero-copy.
    // Non-finite depths are dropped, NaN values stay (gap-honest), unknown
    // depth units stay visible through plan diagnostics. The track layout is
    // reconciled against the incoming curve schema first (a stale layout
    // falls back to the default), so callers may pass the layout they saved
    // for another well.
    [[nodiscard]] bool
    load_document(const WellLogDocumentInput& input,
                  const WellLogTrackLayout& saved_layout,
                  QString* error = nullptr,
                  const std::atomic_bool* cancel = nullptr);

    // Lazy variant: pulls curve metadata first and loads sample buffers one
    // curve at a time, checking *cancel between curves.
    [[nodiscard]] bool load_from_source(WellLogCurveSource& source,
                                        const WellLogTrackLayout& saved_layout,
                                        QString* error = nullptr,
                                        const std::atomic_bool* cancel = nullptr);

    // Rebuilds the presentation for the currently loaded document from the
    // given layout (visibility / grouping / order / log mode / colors).
    // Viewport and selection survive a successful layout change.
    [[nodiscard]] bool apply_track_layout(const WellLogTrackLayout& layout,
                                          QString* error = nullptr);
    [[nodiscard]] WellLogTrackLayout track_layout() const;

    void set_selection_callback(SelectionCallback callback);
    // Depth cursor fan-out (view crosshair moves) and inbound linkage.
    void set_cursor_callback(CursorCallback callback);
    [[nodiscard]] bool set_depth_cursor(double depth);
    void clear_depth_cursor();
    [[nodiscard]] std::optional<double> cursor_depth() const;

    // Emits WellLogInterpretationEvent when a selection resolves to a
    // document interval (facies evidence) or marker (top).
    void set_interpretation_callback(InterpretationCallback callback);

    // Issues SetSelectionCommand on the loaded document's first sampling
    // axis (reference depth, engine units).
    bool select_depth_range(double top, double bottom);
    void clear_selection();
    void reset_viewport();
    [[nodiscard]] bool zoom_at_depth(double anchor_depth, double span_factor);
    [[nodiscard]] bool pan_depth(double display_depth_delta);
    // Current reference depth viewport (nullopt without a document).
    [[nodiscard]] std::optional<std::pair<double, double>> depth_viewport() const;

    // --- export -----------------------------------------------------------
    [[nodiscard]] bool export_png(const QString& path, QString* error = nullptr);
    [[nodiscard]] bool export_svg(const QString& path, QString* error = nullptr);
    [[nodiscard]] bool export_pdf(const QString& path, QString* error = nullptr);

    // --- introspection for hosts and tests -------------------------------
    [[nodiscard]] welllog::WellLogView* view() const noexcept;
    [[nodiscard]] welllog::WellLogSession* session() const noexcept;
    [[nodiscard]] bool has_document() const noexcept;
    [[nodiscard]] QString document_id_text() const;
    [[nodiscard]] std::uint64_t document_revision() const noexcept;
    // Number of recoverable LAS diagnostics observed by the last load.
    [[nodiscard]] std::size_t last_load_diagnostics() const noexcept;
    // Track count of the presentation built by the last load/layout change.
    [[nodiscard]] std::size_t last_track_count() const noexcept;
    // Adapter plan diagnostics of the last load_document/load_from_source.
    [[nodiscard]] std::vector<std::string> last_plan_diagnostics() const;
    [[nodiscard]] QString axis_unit_text() const;

private:
    struct State;
    std::unique_ptr<State> state_;
};

} // namespace pwb::viz
