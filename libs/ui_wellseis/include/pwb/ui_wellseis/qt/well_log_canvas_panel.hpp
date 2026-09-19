#pragma once

// UI-09 — WellLogCanvasPanel Qt shell (well_log_canvas_panel.py).
// Header chrome (backend combo Legacy/WellLogEngine + status) over a stack
// holding the injected legacy canvas / engine view. The panel owns:
//   - backend selection + honest engine placeholder
//   - the 120 ms DepthCursorGate between the engine crosshair and the
//     coordination bus (cursor_gates.hpp owns the rule)
//   - depth-unit fail-closed reasons (depth_cursor_unavailable_reason)
// It never reimplements the canvases — those are engine seams.

#include <functional>
#include <optional>
#include <string>
#include <vector>

#include <QWidget>

#include <pwb/ui_wellseis/cursor_gates.hpp>
#include <pwb/ui_wellseis/qt/engine_seams.hpp>
#include <pwb/ui_wellseis/slices.hpp>
#include <pwb/well_science/depth_unit.hpp>

class QComboBox;
class QLabel;
class QStackedLayout;

namespace pwb::ui_wellseis::qt {

// Engine-side ops the page delegates through the panel (Python
// WellLogCanvasPanel forwards each to the active canvas/engine). Empty
// hooks are no-ops; the backend stack stays local either way.
struct WellLogCanvasHooks {
    std::function<void(const PredictionTaskSlice*, const ProjectSlice*)>
        update_state;
    std::function<bool(const ResourceSlice&, const ProjectSlice*)>
        show_resource;
    std::function<bool()> has_bound_las;
    // well_log_data.well_name or "" (export stem).
    std::function<std::string()> well_name;
    std::function<void()> shutdown;
    // Legacy-branch export (export_well_canvas); returns the error text
    // or nullopt on success. task ids feed provenance.
    std::function<std::optional<std::string>(
        const std::string& path, const std::string& format_label,
        const ProjectSlice* project,
        const std::vector<std::string>& source_task_ids)>
        export_legacy;
    // Engine-view grab() surface for PNG export (nullptr = unavailable).
    std::function<QWidget*()> engine_view;
};

class WellLogCanvasPanel : public QWidget {
    Q_OBJECT
public:
    explicit WellLogCanvasPanel(QWidget* parent = nullptr);

    // Inject one backend's surface; a null widget keeps that backend's
    // placeholder honest (engine_unavailable_text).
    void set_canvas_seam(const std::string& backend,
                         WellLogCanvasSeam seam);
    void set_hooks(WellLogCanvasHooks hooks);

    // Page-delegated engine ops (each a hook forward or no-op).
    void update_state(const PredictionTaskSlice* task,
                      const ProjectSlice* project);
    bool show_resource(const ResourceSlice& resource,
                       const ProjectSlice* project);
    [[nodiscard]] bool has_bound_las() const;
    [[nodiscard]] std::string well_name() const;
    void shutdown();
    // Legacy-branch export hook — only called when backend()=="legacy"
    // (the page enforces the engine PNG-only gate itself).
    [[nodiscard]] std::optional<std::string> export_legacy(
        const std::string& path, const std::string& format_label,
        const ProjectSlice* project,
        const std::vector<std::string>& source_task_ids) const;
    [[nodiscard]] QWidget* engine_view_widget() const;
    // Programmatic backend switch (Python _set_backend parity).
    void set_backend(const std::string& backend);
    [[nodiscard]] std::string backend() const;
    // Selection-only probe — "engine" stays selected after a failed load
    // while the stack falls back to legacy (Python parity).
    [[nodiscard]] bool is_native_backend() const;
    [[nodiscard]] bool is_canvas_ready() const;
    [[nodiscard]] QWidget* active_canvas() const;

    // Depth-unit info the cursor gate needs (host reads depth_unit_of and
    // reports it here — V6 §3 fail-closed). Reuses the well_science
    // envelope directly — one authority for unit vocabulary.
    using DepthUnitInfo = well_science::DepthUnitInfo;
    void set_depth_unit(DepthUnitInfo info);
    // depth_cursor_unavailable_reason parity: nullopt = linking on;
    // "depth-unit:<unit|raw|unknown>" otherwise.
    [[nodiscard]] std::optional<std::string>
    depth_cursor_unavailable_reason() const;
    // depth_cursor_supported parity: legacy always; engine needs the
    // crosshair channel flag from its seam.
    [[nodiscard]] bool depth_cursor_supported() const;
    [[nodiscard]] std::string depth_cursor_unit() const;

    // Engine crosshair → gate → depth_cursor_published (120 ms).
    void offer_depth_cursor(double depth_m);
    // Trailing-edge publication on mouse-release / teardown.
    void flush_depth_cursor();

    void set_status(const QString& text);

signals:
    void backend_changed(const QString& backend);
    void depth_cursor_published(double depth_m);
    // Engine pick events (L2 parity — parameterless native pick signals
    // the host wires into interpretation sessions).
    void engine_pick_event();
    // Python canvas_ready parity — a bound LAS finished loading on the
    // worker thread (#842); the page refreshes the evidence summary.
    void canvas_ready(bool ready);

private:
    void refresh_stack();

    QComboBox* backend_combo_ = nullptr;
    QLabel* status_label_ = nullptr;
    QStackedLayout* stack_ = nullptr;
    QWidget* empty_page_ = nullptr;
    QLabel* empty_label_ = nullptr;
    WellLogCanvasSeam legacy_seam_;
    WellLogCanvasSeam engine_seam_;
    WellLogCanvasHooks hooks_;
    std::string backend_ = "legacy";
    DepthUnitInfo depth_unit_;
    DepthCursorGate depth_gate_;
    bool suppress_ = false;
};

}  // namespace pwb::ui_wellseis::qt
