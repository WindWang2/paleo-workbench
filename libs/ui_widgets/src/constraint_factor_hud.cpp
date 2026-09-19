#include "pwb/ui_widgets/constraint_factor_hud.hpp"

#include <QEvent>
#include <QGridLayout>
#include <QSizePolicy>

namespace pwb::ui_widgets {

namespace {

const QHash<QString, QString>& hud_tooltips() {
    static const QHash<QString, QString> tips = {
        {"sand_ratio",
         "光标处单因素（砂地比）网格双线性采样；无活动网格时为 —"},
        {"slope", "单因素网格局部梯度坡度（中心差分）；无网格时为 —"},
        {"nearest_well", "容差内最近控制井；相别分歧需井-层位解释数据在场"},
        {"confidence", "克里金方差置信度 1/(1+σ/σz)；IDW 等无方差结果为 —"},
    };
    return tips;
}

constexpr const char* kMissing = "—";

}  // namespace

ConstraintFactorHud::ConstraintFactorHud(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("ConstraintFactorHud"));
    setAttribute(Qt::WA_TransparentForMouseEvents);
    setSizePolicy(QSizePolicy::Fixed, QSizePolicy::Fixed);
    auto* layout = new QGridLayout(this);
    layout->setContentsMargins(10, 6, 10, 6);
    layout->setHorizontalSpacing(8);
    layout->setVerticalSpacing(2);
    int row = 0;
    for (const auto& [key, label] : kHudRows) {
        auto* name_label = new QLabel(label, this);
        name_label->setObjectName(QStringLiteral("ConstraintHudRow_") + key);
        name_label->setToolTip(hud_tooltips().value(key));
        auto* value_label = new QLabel(QLatin1String(kMissing), this);
        value_label->setObjectName(QStringLiteral("ConstraintHudValue_") + key);
        layout->addWidget(name_label, row, 0);
        layout->addWidget(value_label, row, 1);
        value_labels_.insert(key, value_label);
        ++row;
    }
    if (parent != nullptr) parent->installEventFilter(this);
}

bool ConstraintFactorHud::eventFilter(QObject* obj, QEvent* event) {
    if (obj == parent() && event->type() == QEvent::Resize) reposition();
    return QWidget::eventFilter(obj, event);
}

void ConstraintFactorHud::reposition() {
    QWidget* host = parentWidget();
    if (host == nullptr) return;
    adjustSize();
    move(qMax(8, host->width() - width() - 12), 12);
}

void ConstraintFactorHud::apply_values(const QHash<QString, QString>& values) {
    for (auto it = value_labels_.begin(); it != value_labels_.end(); ++it) {
        const QString value = values.value(it.key());
        const QString text =
            value.isEmpty() ? QLatin1String(kMissing) : value;
        if (it.value()->text() != text) it.value()->setText(text);
    }
}

QString ConstraintFactorHud::value_of(const QString& key) const {
    return value_labels_.value(key) ? value_labels_.value(key)->text()
                                    : QString();
}

HudController::HudController(QObject* parent) : QObject(parent) {
    timer_ = new QTimer(this);
    timer_->setSingleShot(true);
    timer_->setInterval(kHudRefreshIntervalMs);
    connect(timer_, &QTimer::timeout, this, &HudController::refresh);
    clear_timer_ = new QTimer(this);
    clear_timer_->setSingleShot(true);
    clear_timer_->setInterval(kHudClearDelayMs);
    connect(clear_timer_, &QTimer::timeout, this,
            &HudController::publish_clear);
}

void HudController::bind(ConstraintFactorHud* hud,
                         GridProvider factor_grid_provider,
                         WellsProvider wells_provider,
                         SectionCursorPublisher publish_section_cursor,
                         double section_well_radius) {
    hud_ = hud;
    grid_provider_ = std::move(factor_grid_provider);
    wells_provider_ = std::move(wells_provider);
    publish_section_cursor_ = std::move(publish_section_cursor);
    section_well_radius_ = section_well_radius;
}

void HudController::set_view_coordination(
    SectionCursorPublisher publish) {
    publish_section_cursor_ = std::move(publish);
}

void HudController::handle_position(double x, double y) {
    pending_ = std::make_pair(x, y);
    if (!timer_->isActive()) timer_->start();
}

void HudController::refresh() {
    if (!pending_ || hud_.isNull()) return;
    const double x = pending_->first, y = pending_->second;
    QHash<QString, QString> values;
    const core::GridView* grid =
        grid_provider_ ? grid_provider_() : nullptr;
    if (grid != nullptr) {
        const auto sand = core::bilinear_sample(*grid, x, y);
        if (sand) {
            values.insert(QStringLiteral("sand_ratio"),
                          grid->unit == "%"
                              ? QString::number(*sand, 'f', 1) + "%"
                              : QString::number(*sand, 'f', 2));
        }
        const auto slope = core::local_slope_degrees(*grid, x, y);
        if (slope) {
            values.insert(QStringLiteral("slope"),
                          QString::number(*slope, 'f', 2) + "°");
        }
        // P1-1: nanstd O(grid) cached once per grid identity (D7).
        if (!sigma_cache_ || sigma_cache_->first != grid) {
            sigma_cache_ = std::make_pair(
                static_cast<const void*>(grid),
                core::grid_sigma_reference(*grid));
        }
        const auto confidence = core::confidence_from_variance(
            *grid, x, y, sigma_cache_->second);
        if (confidence) {
            values.insert(QStringLiteral("confidence"),
                          QString::number(*confidence, 'f', 2));
        }
    }
    const auto wells = wells_provider_ ? wells_provider_()
                                       : std::vector<core::WellLocation>{};
    const auto nearest =
        core::nearest_well(wells, x, y, section_well_radius_);
    if (nearest) {
        // 相别分歧需井-层位解释数据在场；缺省诚实显示 —（D7/04 #10）。
        values.insert(
            QStringLiteral("nearest_well"),
            QString::fromStdString(nearest->first) + QStringLiteral("（相别 —）"));
    }
    hud_->apply_values(values);
    route_section_link(
        nearest ? QString::fromStdString(nearest->first) : QString());
}

void HudController::route_section_link(const QString& well_name) {
    if (!well_name.isEmpty()) {
        if (clear_scheduled_) {
            clear_timer_->stop();  // 回到容差内：撤销挂起的清除
            clear_scheduled_ = false;
        }
        if (well_name != last_well_) {
            publish(well_name);
            last_well_ = well_name;
        }
        return;
    }
    if (!last_well_.isEmpty() && !clear_scheduled_) {
        clear_timer_->start();
        clear_scheduled_ = true;
    }
}

void HudController::publish_clear() {
    clear_scheduled_ = false;
    if (!last_well_.isEmpty()) {
        publish(QString());
        last_well_.clear();
    }
}

void HudController::publish(const QString& well_name) {
    if (publish_section_cursor_) {
        publish_section_cursor_(well_name,
                                QString::fromLatin1(kSourceTag));
    }
}

}  // namespace pwb::ui_widgets
