#pragma once

// UI-09 — SeismicViewPanel Qt shell (seismic_view_panel.py).
// Center stack: "未选择预测任务" empty page ⇄ the injected SeismicView
// engine widget; interpretation-lifecycle button bar (draft/sync/undo/redo/
// save/reopen are engine/session actions surfaced as signals); the
// SeismicCursorGate republishes engine cursor moves at ≤30 ms or on
// >1-line jumps (cursor_gates.hpp owns the rule).

#include <array>
#include <cstdint>
#include <functional>
#include <optional>
#include <string>

#include <QFrame>
#include <QString>

#include <pwb/ui_wellseis/cursor_gates.hpp>
#include <pwb/ui_wellseis/qt/engine_seams.hpp>
#include <pwb/ui_wellseis/slices.hpp>

class QLabel;
class QPushButton;
class QStackedLayout;

namespace pwb::ui_wellseis::qt {

// Engine-side ops the page delegates through the panel (Python
// SeismicViewPanel forwards each to its view/session). Empty hooks are
// no-ops; the panel's own state (volume shape, cursor gate, stack) stays
// local either way.
struct SeismicViewHooks {
    std::function<void(const PredictionTaskSlice*, const ProjectSlice*)>
        update_state;
    std::function<bool(const ResourceSlice&, const ProjectSlice*)>
        show_resource;
    std::function<void(const QString&)> set_display_mode;
    std::function<QString()> display_mode;
    std::function<void(const QString&)> set_attribute_label;
    std::function<QString()> attribute_label;
    std::function<void(bool)> set_well_tie_enabled;
    std::function<void(const QString&)> set_project_path;
    std::function<void()> shutdown;
};

class SeismicViewPanel : public QFrame {
    Q_OBJECT
public:
    explicit SeismicViewPanel(QWidget* parent = nullptr,
                              SeismicViewFactory view_factory = {});

    // Engine seam — nullptr widget swaps the honest empty/unavailable page
    // in. view_ready mirrors the Python signal.
    void set_view(SeismicViewSeam seam);
    void set_hooks(SeismicViewHooks hooks);
    [[nodiscard]] bool is_view_ready() const;
    [[nodiscard]] QWidget* view() const;

    // Page-delegated engine ops (each a hook forward or no-op).
    void update_state(const PredictionTaskSlice* task,
                      const ProjectSlice* project);
    bool show_resource(const ResourceSlice& resource,
                       const ProjectSlice* project);
    void set_display_mode(const QString& mode);
    [[nodiscard]] QString display_mode() const;
    void set_attribute_label(const QString& label);
    [[nodiscard]] QString attribute_label() const;
    void set_well_tie_enabled(bool enabled);
    void set_project_path(const QString& path);
    void shutdown();

    void set_volume_shape(
        std::optional<std::array<std::int64_t, 3>> shape);
    [[nodiscard]] std::optional<std::array<std::int64_t, 3>>
    volume_shape() const;

    // Interpretation bar enablement (host computes draft/session state —
    // the versioned-interpretation service is a deferred seam).
    void set_interpretation_state(bool draft_open, bool session_available,
                                  bool can_undo, bool can_redo,
                                  bool version_saved);
    void set_interpretation_status(const QString& text);

    // Engine cursor input → gated republication. The host wires the
    // engine's per-profile cursor signals into offer_cursor; the gate
    // decides whether cursor_published fires (30 ms / >1 inline line).
    void offer_cursor(double il, double xl, double twt_ms);
    void reset_cursor_gate();

    // Honest unavailable text for overlay/depth-slice requests (engine
    // capability probes stay host-side; the panel renders the reason).
    void set_unavailable_reason(const std::string& reason);

signals:
    void view_ready(bool ready);
    void cursor_published(double il, double xl, double twt_ms);
    void interpretation_draft_requested();
    void interpretation_sync_requested();
    void interpretation_undo_requested();
    void interpretation_redo_requested();
    void interpretation_save_requested();
    void interpretation_reopen_requested();

private:
    QStackedLayout* stack_ = nullptr;
    QLabel* empty_label_ = nullptr;
    QWidget* view_ = nullptr;
    QPushButton* interp_draft_btn_ = nullptr;
    QPushButton* interp_sync_btn_ = nullptr;
    QPushButton* interp_undo_btn_ = nullptr;
    QPushButton* interp_redo_btn_ = nullptr;
    QPushButton* interp_save_btn_ = nullptr;
    QPushButton* interp_reload_btn_ = nullptr;
    QLabel* interp_status_label_ = nullptr;
    SeismicCursorGate cursor_gate_;
    std::optional<std::array<std::int64_t, 3>> volume_shape_;
    SeismicViewHooks hooks_;
    // Panel-local mirrors of the last-requested engine state — Python
    // defaults are "vd" / "振幅" when the view lacks the capability.
    QString display_mode_ = QStringLiteral("vd");
    QString attribute_label_ = QStringLiteral("振幅");
};

}  // namespace pwb::ui_wellseis::qt
