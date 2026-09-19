#pragma once

// UI-02 — InteractiveQCHub + SmoothPanController, ported from
// paleo_workbench/ui/components/interactive_qc_hub.py (M4).
//
// The widget only presents and emits request signals; pan animation lives
// in SmoothPanController (D9: 180 ms ease-in-out, history written once on
// the last frame, user input interrupts); fix execution stays in the host
// (the injected availability/apply gate wraps the document-domain actions).

#include <QComboBox>
#include <QHash>
#include <QLabel>
#include <QListWidget>
#include <QObject>
#include <QPushButton>
#include <QTimer>
#include <QVariantMap>
#include <QWidget>

#include <array>
#include <functional>
#include <map>
#include <optional>
#include <vector>

#include "pwb/ui_widgets/core/qc_hub_core.hpp"

namespace pwb::ui_widgets {

// Canvas duck-face seam (QgisCanvasShim / UnifiedMapCanvas / test fake):
// view_extent() -> [xmin,ymin,xmax,ymax]; set_extent(extent,
// record_history, coalesce_history).
struct PanCanvas {
    std::function<std::array<double, 4>()> view_extent;
    std::function<void(const std::array<double, 4>& extent,
                       bool record_history, bool coalesce_history)>
        set_extent;
};

class SmoothPanController : public QObject {
    Q_OBJECT
public:
    explicit SmoothPanController(QObject* parent = nullptr);

    // Smooth pan centered on the target extent (pad applied first).
    void pan_to_extent(PanCanvas canvas, const std::vector<double>& extent,
                       double pad = 0.0);

    // User-input interrupt (immediate stop; no further frames).
    void cancel();

    bool active() const { return canvas_.set_extent != nullptr; }

private:
    void tick();

    PanCanvas canvas_;
    std::array<double, 4> start_{};
    std::array<double, 4> target_{};
    bool has_target_ = false;
    int elapsed_ = 0;
    QTimer* timer_ = nullptr;
};

// QC fix wizard: issue list + detail/fix pane (two-column; dock or embed).
class InteractiveQCHub : public QWidget {
    Q_OBJECT
public:
    // Fix-action registry seam (default: the frozen core registry).
    using FixActionsFn =
        std::function<std::vector<core::QuickFixActionMeta>(const QString& rule)>;
    // Fix context+availability gate: issue+action -> nullopt (no fix
    // context — button disabled) or {available, reason}.
    using FixAvailabilityFn = std::function<
        std::optional<std::pair<bool, std::string>>(
            const QVariantMap& issue, const QString& action_id)>;

    explicit InteractiveQCHub(QWidget* parent = nullptr);

    // Per-source incremental update (cartographic / topology / ...).
    void set_issues(const QString& source, const QList<QVariantMap>& issues);
    int issue_count() const { return int(items_.size()); }

    // Remove one fixed issue from display (all sources synced).
    void mark_resolved(const QVariantMap& issue);

    // Inject the fix context/availability gate (issue -> ctx in Python;
    // here one fused gate — see ledger D-SEAM).
    void set_fix_gate(FixAvailabilityFn gate);
    // Optional registry override (default = frozen quick_fix_registry).
    void set_fix_actions(FixActionsFn actions);

    QPushButton* fix_button(const QString& action_id) const;

    QLabel* counts_label = nullptr;   // public per Python surface
    QListWidget* issue_list = nullptr;

signals:
    void issue_focused(const QVariantMap& issue);
    void fix_requested(const QVariantMap& issue, const QString& action_id);
    void refresh_requested();

protected:
    bool eventFilter(QObject* obj, QEvent* event) override;

private:
    void reload();
    void on_selection();
    void show_detail(QListWidgetItem* item);
    void refresh_detail();
    QVariantMap current_issue_dict() const;
    void request_fix(const QString& action_id);
    void locate_selected();

    std::map<QString, QList<QVariantMap>> sources_;
    QList<QVariantMap> items_;
    QVariantMap current_issue_;
    QHash<QString, QPair<bool, QString>> current_availability_;
    FixActionsFn fix_actions_;
    FixAvailabilityFn fix_gate_;
    QComboBox* filter_combo_ = nullptr;
    QPushButton* locate_button_ = nullptr;
    QLabel* detail_title_ = nullptr;
    QLabel* detail_meta_ = nullptr;
    QLabel* fix_area_label_ = nullptr;
    QWidget* detail_pane_ = nullptr;
    QHash<QString, QPushButton*> fix_buttons_;
};

}  // namespace pwb::ui_widgets
