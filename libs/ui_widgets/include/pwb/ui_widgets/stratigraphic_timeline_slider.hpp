#pragma once

// UI-02 — StratigraphicTimelineWidget + EpochTimelineController, ported
// from paleo_workbench/ui/components/stratigraphic_timeline_slider.py (M1).
//
// The widget owns gestures + debounce only (D4): drag/keyboard step ->
// epoch_scrubbed preview; a 150 ms pause or release -> one epoch_committed.
// The controller consumes commit/onion and applies the core
// epoch_switching plan through the injected layer-manager seam (existing
// set_layer_visible / set_layer_opacity incremental path — zero canvas
// rebuilds), writing the epoch through to stratigraphy.target_horizon via
// the injected horizon IO seam.

#include <QLabel>
#include <QObject>
#include <QTimer>
#include <QToolButton>
#include <QWidget>

#include <functional>
#include <optional>
#include <vector>

#include "pwb/ui_widgets/core/epoch_switching.hpp"

namespace pwb::ui_widgets {

//: 提交去抖（ms）：拖拽释放 / 键盘步进停顿后触发一次 commit（D4）。
inline constexpr int kCommitDebounceMs = 150;
//: 洋葱皮不透明度（D2：alpha 0.30）——re-exported from core.
inline constexpr double kTimelineOnionOpacity = core::kOnionOpacity;

// Epoch tick track: paint + drag gestures (deterministic x->index map).
class TimelineTrack : public QWidget {
    Q_OBJECT
public:
    explicit TimelineTrack(QWidget* parent = nullptr);

    void set_epochs(const QStringList& labels);
    void set_current_index(int index);
    void set_preview_index(int index);
    int index_at(int x) const;

    int current_index() const { return current_; }
    int preview_index() const { return preview_; }

signals:
    void scrub_started();
    void scrub_moved(int index);
    void released(int index);

protected:
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void paintEvent(QPaintEvent* event) override;

private:
    QStringList labels_;
    int current_ = -1;
    int preview_ = -1;
    bool dragging_ = false;
};

// Timeline strip: tick track + step buttons + onion toggle.
class StratigraphicTimelineWidget : public QWidget {
    Q_OBJECT
public:
    explicit StratigraphicTimelineWidget(QWidget* parent = nullptr);

    void set_epochs(const std::vector<core::EpochInfo>& epochs);
    std::vector<core::EpochInfo> epochs() const { return epochs_; }

    QString current_epoch() const;          // "" when none (Python None)
    // Programmatic current-epoch sync (no commit; echo breaker).
    void set_current_epoch(const QString& key, bool suppress = true);

    TimelineTrack* track() const { return track_; }
    QToolButton* onion_button = nullptr;    // public per Python surface

signals:
    void epoch_scrubbed(const QString& key);
    void scrub_started();
    void epoch_committed(const QString& key);
    void onion_toggled(bool checked);

protected:
    void keyPressEvent(QKeyEvent* event) override;

private:
    QString key_at(int index) const;
    void on_scrub_index(int index);
    void schedule_commit_index(int index);
    void step(int delta);
    void flush_commit();

    std::vector<core::EpochInfo> epochs_;
    int current_index_ = -1;
    int preview_index_ = -1;
    QString pending_key_;
    bool has_pending_ = false;

    QToolButton* prev_button_ = nullptr;
    QToolButton* next_button_ = nullptr;
    TimelineTrack* track_ = nullptr;
    QLabel* placeholder_ = nullptr;
    QTimer* commit_timer_ = nullptr;
};

// Layer-manager duck-face seam (Python _layers / set_layer_visible /
// set_layer_opacity / move_layer — optional).
struct LayerManagerSeam {
    std::function<std::vector<core::LayerSnapshot>()> layers;
    std::function<void(const std::string& layer_id, bool visible)> set_visible;
    std::function<void(const std::string& layer_id, double opacity)> set_opacity;
    // move_layer(id, direction): +1 -> index shrinks (toward bottom),
    // -1 -> toward list end (top). Optional — missing means "cannot
    // raise" (honest degraded status, Python `not callable(move)` parity).
    std::function<bool(const std::string& layer_id, int direction)> move_layer;
};

// stratigraphy horizon IO seam: active_target_horizon(project) /
// set_target_from_boundary(project, key).
struct HorizonIo {
    std::function<QString()> read_active;                 // "" when none
    std::function<void(const QString& key)> write_target;
};

// Epoch diff-switch executor (pure QObject; programs against seams).
class EpochTimelineController : public QObject {
    Q_OBJECT
public:
    explicit EpochTimelineController(QObject* parent = nullptr);

    void bind(LayerManagerSeam layer_manager, HorizonIo horizon_io = {},
              std::function<void(const QString&)> status_sink = {},
              core::EpochClassifier classifier = {});

    // Python set_project(): reads the active horizon into current key.
    void set_horizon_io(HorizonIo io);
    void set_epochs(const std::vector<core::EpochInfo>& epochs);
    QString current_epoch() const { return current_key_; }  // "" = None

    void request_commit(const QString& key);
    void set_onion(bool enabled);
    bool onion() const { return onion_; }

signals:
    // Commit completed (incl. direct request_commit automation) -> host
    // re-syncs the widget highlight. Read-only broadcast (echo breaker).
    void epoch_changed(const QString& key);
    // Effective onion state (False = no previous-epoch layer etc. — the
    // button must re-sync, F3).
    void onion_applied(bool applied);

private:
    std::vector<core::LayerSnapshot> layers() const;
    const core::LayerSnapshot* find_layer(const std::string& layer_id,
                                          const std::vector<core::LayerSnapshot>& layers) const;
    void status(const QString& message);
    QString label_of(const QString& key) const;
    void write_horizon(const QString& key);
    QString prev_label() const;
    int layer_position(const std::string& layer_id,
                       const std::vector<core::LayerSnapshot>& layers) const;
    bool raise_layer_to_top(const std::string& layer_id);
    void lower_layer_to(const std::string& layer_id, int position);
    void apply_onion();
    void restore_onion();

    LayerManagerSeam manager_;
    HorizonIo horizon_io_;
    std::function<void(const QString&)> status_sink_;
    core::EpochClassifier classifier_;
    bool custom_classifier_ = false;
    std::vector<core::EpochInfo> epochs_;
    QString current_key_;  // empty = None
    bool has_current_ = false;
    bool onion_ = false;
    // (layer_id, visible, opacity, position) restore records.
    std::vector<std::tuple<std::string, bool, double, int>> onion_restore_;
};

}  // namespace pwb::ui_widgets
