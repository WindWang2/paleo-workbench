#pragma once

// M3 (ribbon five-workspaces, plan 00-plan.md §4-M3) — 综合编图 (ws3,
// stage=integrated_compilation) bottom factor-reference strip:
// horizontally arranged checkable thumbnail cards (single selection, F:68
// contract) fed by the REAL completed factor tasks (the same
// project.factor_map_tasks payload the MapFactorShelf consumes) with
// thumbnails rendered from the live factor grids through an injected
// renderer + cache (the host owns the cache — one downsample per
// task+fingerprint, never a re-parse of the same big grid).
//
// Clicking a card only switches the reference object/detail and emits
// reference_selected — it NEVER replaces the main product map (F:68 hard
// constraint). 叠加 is a separate explicit button routed by the host
// through the existing governed dispatch.

#include <functional>
#include <vector>

#include <QPixmap>
#include <QSize>
#include <QWidget>

#include <pwb/domain/json.hpp>

class QHBoxLayout;
class QLabel;
class QListWidget;
class QListWidgetItem;

namespace pwb::app {

class FactorReferenceStrip : public QWidget {
    Q_OBJECT
public:
    explicit FactorReferenceStrip(QWidget* parent = nullptr);

    // update_state(tasks): keep the status=="complete" cards (MapFactorShelf
    // payload parity: id/factor_type/name/method/target_horizon/
    // quality_metrics). Unknown fields never fabricate.
    void update_state(const std::vector<pwb::domain::Json>& tasks);

    // Thumbnail seam: (task, size) -> pixmap (null = honest "no preview").
    // The host implementation renders the live grid downsampled and caches
    // per task id + result fingerprint.
    void set_thumbnail_renderer(
        std::function<QPixmap(const pwb::domain::Json&, const QSize&)> renderer);

    // The currently selected task (empty object when none).
    pwb::domain::Json selected_task() const { return selected_; }

signals:
    // 选中参考对象（只切详情/定位，不替换主成果 — F:68）。
    void reference_selected(const pwb::domain::Json& task);
    // 显式"叠加到主图"按钮（宿主接到既有 governed 派发）。
    void overlay_requested(const pwb::domain::Json& task);

private:
    void rebuild();
    void show_detail(const pwb::domain::Json& task);
    static QString card_text(const pwb::domain::Json& task);

    std::vector<pwb::domain::Json> tasks_;
    pwb::domain::Json selected_ = pwb::domain::Json::object();
    std::function<QPixmap(const pwb::domain::Json&, const QSize&)> renderer_;
    QListWidget* cards_ = nullptr;
    QLabel* detail_ = nullptr;
    bool syncing_ = false;
};

}  // namespace pwb::app

// Json rides a queued-capable signal — one metatype declaration per TU
// (shared guard with factor_preview_grid.hpp / ui_map qt_meta.hpp).
#ifndef PWB_JSON_METATYPE_DECLARED
#define PWB_JSON_METATYPE_DECLARED
Q_DECLARE_METATYPE(pwb::domain::Json)
#endif
