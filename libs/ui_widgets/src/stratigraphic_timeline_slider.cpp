#include "pwb/ui_widgets/stratigraphic_timeline_slider.hpp"

#include <QFontMetrics>
#include <QHBoxLayout>
#include <QKeyEvent>
#include <QMouseEvent>
#include <QPainter>
#include <QPen>
#include <QSizePolicy>
#include <QVBoxLayout>

namespace pwb::ui_widgets {

// ---------------------------------------------------------------------------
// TimelineTrack
// ---------------------------------------------------------------------------

TimelineTrack::TimelineTrack(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("TimelineTrack"));
    setMinimumHeight(30);
    setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
    setCursor(Qt::PointingHandCursor);
}

void TimelineTrack::set_epochs(const QStringList& labels) {
    labels_ = labels;
    current_ = labels_.isEmpty() ? -1 : 0;
    preview_ = -1;
    update();
}

void TimelineTrack::set_current_index(int index) {
    if (labels_.isEmpty()) return;
    current_ = qBound(0, index, int(labels_.size()) - 1);
    preview_ = -1;
    update();
}

void TimelineTrack::set_preview_index(int index) {
    preview_ = index;
    update();
}

int TimelineTrack::index_at(int x) const {
    if (labels_.isEmpty() || width() <= 0) return -1;
    return qBound(0, int(x * labels_.size() / width()),
                  int(labels_.size()) - 1);
}

void TimelineTrack::mousePressEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton) {
        const int index = index_at(event->position().toPoint().x());
        if (index >= 0) {
            dragging_ = true;
            preview_ = index;
            emit scrub_started();
            emit scrub_moved(index);
            update();
            event->accept();
            return;
        }
    }
    QWidget::mousePressEvent(event);
}

void TimelineTrack::mouseMoveEvent(QMouseEvent* event) {
    if (dragging_) {
        const int index = index_at(event->position().toPoint().x());
        if (index != preview_) {
            preview_ = index;
            emit scrub_moved(index);
            update();
        }
        event->accept();
        return;
    }
    QWidget::mouseMoveEvent(event);
}

void TimelineTrack::mouseReleaseEvent(QMouseEvent* event) {
    if (dragging_ && event->button() == Qt::LeftButton) {
        dragging_ = false;
        const int released_index = preview_;
        preview_ = -1;
        update();
        emit released(released_index);
        event->accept();
        return;
    }
    QWidget::mouseReleaseEvent(event);
}

void TimelineTrack::paintEvent(QPaintEvent* event) {
    Q_UNUSED(event);
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing, false);
    const int margin = 6, gap = 3;
    const int usable = width() - 2 * margin;
    const int count = int(labels_.size());
    if (count == 0 || usable <= 0) return;
    const double seg = double(usable - gap * (count - 1)) / count;
    const QFontMetrics metrics(font());
    const QPalette palette = this->palette();
    const QColor base = palette.button().color();
    const QColor highlight = palette.highlight().color();
    const QColor preview = palette.mid().color();
    const QColor text = palette.windowText().color();
    for (int i = 0; i < count; ++i) {
        const QRect rect(int(margin + i * (seg + gap)), 4, int(seg),
                         height() - 10);
        QColor fill = base;
        if (i == current_) fill = highlight;
        if (preview_ >= 0 && i == preview_) fill = preview;
        painter.fillRect(rect, fill);
        painter.setPen(QPen(palette.window().color(), 1));
        painter.drawRect(rect.adjusted(0, 0, -1, -1));
        const QString elided = metrics.elidedText(
            labels_.at(i), Qt::ElideRight, rect.width() - 8);
        QColor pen_color = text;
        if (i == current_ && highlight.lightness() > 150) {
            pen_color = palette.window().color();
        }
        painter.setPen(pen_color);
        painter.drawText(rect, Qt::AlignCenter, elided);
    }
}

// ---------------------------------------------------------------------------
// StratigraphicTimelineWidget
// ---------------------------------------------------------------------------

StratigraphicTimelineWidget::StratigraphicTimelineWidget(QWidget* parent)
    : QWidget(parent) {
    setObjectName(QStringLiteral("StratigraphicTimeline"));
    setFocusPolicy(Qt::StrongFocus);

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    auto* row = new QHBoxLayout();
    row->setContentsMargins(8, 2, 8, 2);
    row->setSpacing(4);

    prev_button_ = new QToolButton(this);
    prev_button_->setText(QStringLiteral("◀"));
    prev_button_->setToolTip(QStringLiteral("上一期次（←）"));
    connect(prev_button_, &QToolButton::clicked, this,
            [this]() { step(-1); });
    track_ = new TimelineTrack(this);
    connect(track_, &TimelineTrack::scrub_started, this,
            &StratigraphicTimelineWidget::scrub_started);
    connect(track_, &TimelineTrack::scrub_moved, this,
            &StratigraphicTimelineWidget::on_scrub_index);
    connect(track_, &TimelineTrack::released, this,
            &StratigraphicTimelineWidget::schedule_commit_index);
    next_button_ = new QToolButton(this);
    next_button_->setText(QStringLiteral("▶"));
    next_button_->setToolTip(QStringLiteral("下一期次（→）"));
    connect(next_button_, &QToolButton::clicked, this,
            [this]() { step(1); });
    onion_button = new QToolButton(this);
    onion_button->setObjectName(QStringLiteral("TimelineOnionButton"));
    onion_button->setText(QStringLiteral("洋葱皮"));
    onion_button->setToolTip(
        QStringLiteral("洋葱皮：30% 半透明叠加相邻前一期次相带边界"));
    onion_button->setCheckable(true);
    connect(onion_button, &QToolButton::toggled, this,
            &StratigraphicTimelineWidget::onion_toggled);

    placeholder_ = new QLabel(
        QStringLiteral("无期次数据 — 先在层序页建立层序界面目录"), this);
    placeholder_->setObjectName(QStringLiteral("TimelinePlaceholder"));
    placeholder_->setAlignment(Qt::AlignCenter);
    placeholder_->hide();

    row->addWidget(prev_button_);
    row->addWidget(track_, 1);
    row->addWidget(next_button_);
    row->addWidget(onion_button);
    layout->addLayout(row);
    layout->addWidget(placeholder_);

    commit_timer_ = new QTimer(this);
    commit_timer_->setSingleShot(true);
    commit_timer_->setInterval(kCommitDebounceMs);
    connect(commit_timer_, &QTimer::timeout, this,
            &StratigraphicTimelineWidget::flush_commit);
}

void StratigraphicTimelineWidget::set_epochs(
    const std::vector<core::EpochInfo>& epochs) {
    epochs_ = epochs;
    QStringList labels;
    for (const core::EpochInfo& e : epochs_) {
        labels.append(e.label.empty() ? QString::fromStdString(e.key)
                                      : QString::fromStdString(e.label));
    }
    track_->set_epochs(labels);
    const bool empty = epochs_.empty();
    placeholder_->setVisible(empty);
    track_->setVisible(!empty);
    prev_button_->setVisible(!empty);
    next_button_->setVisible(!empty);
    onion_button->setVisible(!empty);
    current_index_ = empty ? -1 : 0;
    preview_index_ = -1;
    track_->set_current_index(current_index_);
    pending_key_.clear();
    has_pending_ = false;
}

QString StratigraphicTimelineWidget::current_epoch() const {
    if (current_index_ >= 0 &&
        current_index_ < int(epochs_.size())) {
        return QString::fromStdString(epochs_[current_index_].key);
    }
    return QString();
}

void StratigraphicTimelineWidget::set_current_epoch(const QString& key,
                                                    bool suppress) {
    for (int i = 0; i < int(epochs_.size()); ++i) {
        if (QString::fromStdString(epochs_[i].key) == key) {
            current_index_ = i;
            preview_index_ = -1;
            track_->set_current_index(i);
            if (suppress) {
                pending_key_.clear();
                has_pending_ = false;
            }
            return;
        }
    }
}

QString StratigraphicTimelineWidget::key_at(int index) const {
    if (index >= 0 && index < int(epochs_.size())) {
        return QString::fromStdString(epochs_[index].key);
    }
    return QString();
}

void StratigraphicTimelineWidget::on_scrub_index(int index) {
    const QString key = key_at(index);
    if (!key.isEmpty()) {
        track_->set_preview_index(index);
        emit epoch_scrubbed(key);
    }
}

void StratigraphicTimelineWidget::schedule_commit_index(int index) {
    const QString key = key_at(index);
    if (!key.isEmpty()) {
        pending_key_ = key;
        has_pending_ = true;
        commit_timer_->start();
    }
}

void StratigraphicTimelineWidget::step(int delta) {
    if (epochs_.empty()) return;
    // 步进基准是预览位（连击从上次预览继续），提交前不移动 current。
    const int base =
        preview_index_ >= 0 ? preview_index_ : current_index_;
    const int target = qBound(0, base + delta, int(epochs_.size()) - 1);
    preview_index_ = target;
    on_scrub_index(target);
    schedule_commit_index(target);
}

void StratigraphicTimelineWidget::keyPressEvent(QKeyEvent* event) {
    if (event->key() == Qt::Key_Right || event->key() == Qt::Key_Left) {
        step(event->key() == Qt::Key_Right ? 1 : -1);
        event->accept();
        return;
    }
    QWidget::keyPressEvent(event);
}

void StratigraphicTimelineWidget::flush_commit() {
    const QString key = pending_key_;
    pending_key_.clear();
    has_pending_ = false;
    preview_index_ = -1;
    if (key.isEmpty()) return;
    set_current_epoch(key, /*suppress=*/false);
    emit epoch_committed(key);
}

// ---------------------------------------------------------------------------
// EpochTimelineController
// ---------------------------------------------------------------------------

EpochTimelineController::EpochTimelineController(QObject* parent)
    : QObject(parent) {}

void EpochTimelineController::bind(
    LayerManagerSeam layer_manager, HorizonIo horizon_io,
    std::function<void(const QString&)> status_sink,
    core::EpochClassifier classifier) {
    manager_ = std::move(layer_manager);
    horizon_io_ = std::move(horizon_io);
    status_sink_ = std::move(status_sink);
    classifier_ = std::move(classifier);
    custom_classifier_ = static_cast<bool>(classifier_);
}

void EpochTimelineController::set_horizon_io(HorizonIo io) {
    horizon_io_ = std::move(io);
    if (horizon_io_.read_active) {
        const QString horizon = horizon_io_.read_active();
        if (!horizon.isEmpty()) {
            current_key_ = horizon;
            has_current_ = true;
        }
    }
}

void EpochTimelineController::set_epochs(
    const std::vector<core::EpochInfo>& epochs) {
    epochs_ = epochs;
    // 目录变化即重建默认分类器（注入的自定义分类器不覆盖）。
    if (!custom_classifier_) {
        classifier_ = core::default_epoch_classifier(epochs_);
    }
    if (!has_current_ && !epochs_.empty()) {
        current_key_ = QString::fromStdString(epochs_.front().key);
        has_current_ = true;
    }
}

std::vector<core::LayerSnapshot> EpochTimelineController::layers() const {
    if (!manager_.layers) return {};
    return manager_.layers();
}

void EpochTimelineController::status(const QString& message) {
    if (status_sink_) status_sink_(message);
}

const core::LayerSnapshot* EpochTimelineController::find_layer(
    const std::string& layer_id,
    const std::vector<core::LayerSnapshot>& layers) const {
    for (const core::LayerSnapshot& layer : layers) {
        if (layer.id == layer_id) return &layer;
    }
    return nullptr;
}

QString EpochTimelineController::label_of(const QString& key) const {
    for (const core::EpochInfo& epoch : epochs_) {
        if (QString::fromStdString(epoch.key) == key) {
            return epoch.label.empty()
                       ? key
                       : QString::fromStdString(epoch.label);
        }
    }
    return key;
}

void EpochTimelineController::request_commit(const QString& key) {
    if (!manager_.set_visible) return;
    const std::string target = key.toStdString();
    const auto current_layers = layers();
    const std::string current_std =
        has_current_ ? current_key_.toStdString() : std::string();
    const core::EpochSwitchPlan plan = core::build_epoch_switch_plan(
        current_layers, has_current_ ? &current_std : nullptr, target,
        classifier_);
    // touched 记录（回滚用）。
    std::vector<std::pair<std::string, bool>> touched;
    for (const std::string& layer_id : plan.show) {
        const core::LayerSnapshot* layer = find_layer(layer_id, current_layers);
        touched.emplace_back(layer_id, layer ? layer->visible : true);
    }
    for (const std::string& layer_id : plan.hide) {
        const core::LayerSnapshot* layer = find_layer(layer_id, current_layers);
        touched.emplace_back(layer_id, layer ? layer->visible : true);
    }
    try {
        if (onion_) restore_onion();
        for (const std::string& layer_id : plan.hide) {
            manager_.set_visible(layer_id, false);
        }
        for (const std::string& layer_id : plan.show) {
            manager_.set_visible(layer_id, true);
        }
    } catch (...) {
        for (const auto& [layer_id, visible] : touched) {
            try {
                manager_.set_visible(layer_id, visible);
            } catch (...) {
            }  // 回滚尽力而为；原始异常继续上抛
        }
        throw;
    }
    current_key_ = key;
    has_current_ = true;
    write_horizon(key);
    emit epoch_changed(key);
    const auto after_layers = layers();
    const bool affiliated =
        classifier_ && std::any_of(after_layers.begin(), after_layers.end(),
                                   [&](const core::LayerSnapshot& l) {
                                       const auto k = classifier_(l);
                                       return k && *k == target;
                                   });
    const QString label = label_of(key);
    if (!affiliated) {
        status(QStringLiteral("期次「%1」暂无图层——仅切换目标层位").arg(label));
    } else if (!plan.has_changes()) {
        status(QStringLiteral("期次「%1」图层已就绪，无需切换可见性").arg(label));
    } else {
        status(QStringLiteral("已切换到期次「%1」（隐藏 %2 层，显示 %3 层）")
                   .arg(label)
                   .arg(plan.hide.size())
                   .arg(plan.show.size()));
    }
    if (onion_) apply_onion();
}

void EpochTimelineController::write_horizon(const QString& key) {
    if (!horizon_io_.write_target) return;
    try {
        horizon_io_.write_target(key);
    } catch (...) {
    }  // 元数据写穿失败不阻断可见性切换
}

void EpochTimelineController::set_onion(bool enabled) {
    if (enabled) {
        if (onion_) restore_onion();
        apply_onion();
    } else {
        restore_onion();
        status(QStringLiteral("洋葱皮已关闭"));
    }
}

int EpochTimelineController::layer_position(
    const std::string& layer_id,
    const std::vector<core::LayerSnapshot>& layers) const {
    for (int i = 0; i < int(layers.size()); ++i) {
        if (layers[i].id == layer_id) return i;
    }
    return -1;
}

QString EpochTimelineController::prev_label() const {
    QStringList keys;
    for (const core::EpochInfo& e : epochs_) {
        keys.append(QString::fromStdString(e.key));
    }
    const QString current = has_current_ ? current_key_ : QString();
    const int index = keys.indexOf(current);
    if (index > 0) return label_of(keys.at(index - 1));
    return QString();
}

bool EpochTimelineController::raise_layer_to_top(
    const std::string& layer_id) {
    // 返回是否**真的应用**（分组模式下 move 可能不落地的如实信号）。
    if (!manager_.move_layer) return false;
    const auto current_layers = layers();
    const int position = layer_position(layer_id, current_layers);
    const int moved = std::max(int(current_layers.size()) - 1 - position, 0);
    if (moved == 0) return true;  // 已在栈顶
    bool applied = false;
    for (int i = 0; i < moved; ++i) {
        applied = manager_.move_layer(layer_id, -1);
    }
    return applied;
}

void EpochTimelineController::lower_layer_to(const std::string& layer_id,
                                             int position) {
    if (!manager_.move_layer) return;
    const auto current_layers = layers();
    const int current = layer_position(layer_id, current_layers);
    for (int i = 0; i < std::max(current - position, 0); ++i) {
        manager_.move_layer(layer_id, 1);
    }
}

void EpochTimelineController::apply_onion() {
    const auto current_layers = layers();
    const std::vector<std::string> onion_ids = core::build_onion_layers(
        current_layers, epochs_,
        has_current_ ? current_key_.toStdString() : "", classifier_);
    if (onion_ids.empty()) {
        onion_ = false;
        const QString label =
            label_of(has_current_ ? current_key_ : QString());
        status(QStringLiteral("期次「%1」无相邻前一期次相带层可叠加")
                   .arg(label));
        emit onion_applied(false);  // F3：按钮态回同步
        return;
    }
    onion_ = true;
    onion_restore_.clear();
    bool raised = true;
    for (const std::string& layer_id : onion_ids) {
        const core::LayerSnapshot* layer = find_layer(layer_id, current_layers);
        const bool visible = layer ? layer->visible : true;
        const double opacity = layer ? layer->opacity : 1.0;
        const int position = layer_position(layer_id, current_layers);
        onion_restore_.emplace_back(layer_id, visible, opacity, position);
        if (manager_.set_visible) manager_.set_visible(layer_id, true);
        if (manager_.set_opacity) {
            manager_.set_opacity(layer_id, core::kOnionOpacity);
        }
        raised = raise_layer_to_top(layer_id) && raised;
    }
    emit onion_applied(true);
    QString hint = QStringLiteral(
                       "洋葱皮开启：前一期次「%1」相带以 30% 半透明叠加")
                       .arg(prev_label());
    if (!raised) {
        // 分层模式下 root 平铺序不是权威——置顶推不动，如实说明。
        hint += QStringLiteral(
            "（当前分组模式不支持跨组置顶：叠加层仍在其所属组内）");
    }
    status(hint);
}

void EpochTimelineController::restore_onion() {
    if (onion_restore_.empty()) {
        onion_ = false;
        return;
    }
    for (const auto& [layer_id, visible, opacity, position] :
         onion_restore_) {
        try {
            lower_layer_to(layer_id, position);  // B2：复原层序
            if (manager_.set_opacity) manager_.set_opacity(layer_id, opacity);
            if (manager_.set_visible) manager_.set_visible(layer_id, visible);
        } catch (...) {
        }
    }
    onion_restore_.clear();
    onion_ = false;
}

}  // namespace pwb::ui_widgets
