#pragma once

// UI-02 — ConstraintFactorHud + HudController, ported from
// paleo_workbench/ui/components/constraint_factor_hud.py (M3).
//
// Budget contract (00-decisions D7):
//  - value computation O(1): bilinear sample + local slope + linear
//    nearest well (wells <= thousands);
//  - 60 ms coalescing refresh (single-shot QTimer keeps only the latest
//    cursor point — high-frequency jitter is not amplified);
//  - the HUD is a CHILD widget of the canvas (never top-level),
//    mouse-transparent, row widgets created once;
//  - missing data fields show "—" (honest degradation, never guessed).
//
// Providers are injected std::function seams — the widget owns no data.

#include <QHash>
#include <QLabel>
#include <QObject>
#include <QPointer>
#include <QTimer>
#include <QWidget>

#include <functional>
#include <memory>
#include <optional>
#include <vector>

#include "pwb/ui_widgets/core/hud_sampling.hpp"

namespace pwb::ui_widgets {

// 光标→HUD 刷新合并窗口（ms）。
inline constexpr int kHudRefreshIntervalMs = 60;
// 离开井位容差后的延迟清除（ms，防闪烁）。
inline constexpr int kHudClearDelayMs = 300;
// HUD 行定义（key, 显示名）——冻结顺序。
inline const std::vector<std::pair<QString, QString>> kHudRows = {
    {"sand_ratio", "砂地比"},
    {"slope", "坡度"},
    {"nearest_well", "最近井"},
    {"confidence", "预测置信度"},
};

class ConstraintFactorHud : public QWidget {
    Q_OBJECT
public:
    explicit ConstraintFactorHud(QWidget* parent = nullptr);

    // Batch value update; missing/empty values render "—".
    void apply_values(const QHash<QString, QString>& values);
    QString value_of(const QString& key) const;

protected:
    bool eventFilter(QObject* obj, QEvent* event) override;

private:
    void reposition();

    QHash<QString, QLabel*> value_labels_;
};

// Cursor -> HUD value computation + section-link publishing (pure
// coordinator; data arrives through injected providers).
class HudController : public QObject {
    Q_OBJECT
public:
    static constexpr const char* kSourceTag = "mapping_cursor";

    // Injected seams:
    using GridProvider =
        std::function<const core::GridView*()>;  // nullptr = no grid
    using WellsProvider =
        std::function<std::vector<core::WellLocation>()>;
    // (well_name, source) — view_coordination.publish_section_cursor.
    using SectionCursorPublisher =
        std::function<void(const QString& well_name, const QString& source)>;

    explicit HudController(QObject* parent = nullptr);

    void bind(ConstraintFactorHud* hud, GridProvider factor_grid_provider,
              WellsProvider wells_provider,
              SectionCursorPublisher publish_section_cursor = {},
              double section_well_radius = 50.0);
    void set_view_coordination(SectionCursorPublisher publish);

    // High-frequency cursor entry: keep only the latest point; the timer
    // is not restarted while active (coalescing throttle).
    void handle_position(double x, double y);

    // Test/introspection.
    QString last_well() const { return last_well_; }
    bool refresh_pending() const { return pending_.has_value(); }

private:
    void refresh();
    void route_section_link(const QString& well_name);
    void publish_clear();
    void publish(const QString& well_name);

    QPointer<ConstraintFactorHud> hud_;
    GridProvider grid_provider_;
    WellsProvider wells_provider_;
    SectionCursorPublisher publish_section_cursor_;
    double section_well_radius_ = 50.0;
    std::optional<std::pair<double, double>> pending_;
    QString last_well_;
    // (grid identity, sigma) — nanstd O(grid) is cached per grid, never
    // inside the 60 ms refresh loop (P1-1 review, D7).
    std::optional<std::pair<const void*, double>> sigma_cache_;
    bool clear_scheduled_ = false;
    QTimer* timer_ = nullptr;
    QTimer* clear_timer_ = nullptr;
};

}  // namespace pwb::ui_widgets
