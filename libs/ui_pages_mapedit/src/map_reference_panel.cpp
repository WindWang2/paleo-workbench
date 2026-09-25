#include "pwb/ui_pages_mapedit/map_reference_panel.hpp"

#include "pwb/ui_shell/style_registry.hpp"
#include "pwb/ui_widgets/reconcile.hpp"

#include <QCheckBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QListWidget>
#include <QListWidgetItem>
#include <QSlider>
#include <QVBoxLayout>

#include <cmath>

namespace pwb::ui_pages_mapedit {
namespace {

int tok_int(const char* key, int fallback) {
    const auto& p = ui_shell::style_palette();
    const auto it = p.find(key);
    if (it == p.end()) {
        return fallback;
    }
    bool ok = false;
    const int v = QString::fromStdString(it->second).toInt(&ok);
    return ok ? v : fallback;
}

}  // namespace

MapReferencePanel::MapReferencePanel(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("MapReferencePanel"));
    setMinimumWidth(200);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(tok_int("PANEL_PADDING", 12),
                               tok_int("PANEL_PADDING", 12),
                               tok_int("PANEL_PADDING", 12),
                               tok_int("PANEL_PADDING", 12));
    layout->setSpacing(tok_int("SPACE_2", 8));

    auto* title = new QLabel(QStringLiteral("参考地图"), this);
    title->setObjectName(QStringLiteral("MapDockTitle"));
    layout->addWidget(title);

    // 参考图视图槽：宿主注入真实地图视图（未注入时占位说明——面板
    // 仍是可用控件，不假装有图）。
    view_host_ = new QWidget(this);
    view_host_->setObjectName(QStringLiteral("MapReferenceViewHost"));
    auto* view_layout = new QVBoxLayout(view_host_);
    view_layout->setContentsMargins(0, 0, 0, 0);
    view_layout->setSpacing(0);
    view_placeholder_ = new QLabel(
        QStringLiteral("参考图视图未装配"), view_host_);
    view_placeholder_->setAlignment(Qt::AlignCenter);
    view_layout->addWidget(view_placeholder_);
    layout->addWidget(view_host_, 2);

    // 联动开关（状态消费在宿主：单一 master = 主图 extent）。
    link_check_ = new QCheckBox(QStringLiteral("与主图联动"), this);
    link_check_->setObjectName(QStringLiteral("MapRefLinkToggle"));
    link_check_->setChecked(false);
    link_check_->setToolTip(QStringLiteral(
        "开启：参考图视图范围跟随主图（主图为单一权威）；"
        "关闭：两个视图独立漫游"));
    connect(link_check_, &QCheckBox::toggled, this,
            [this](bool on) { emit link_toggled(on); });
    layout->addWidget(link_check_);

    status_label_ = new QLabel(QStringLiteral("暂无参考图"), this);
    // tokens.TEXT_SECONDARY/BG_SEARCH/BORDER_LIGHT — resolved through the
    // CURRENT palette at render time (theme switches re-render).
    ui_shell::style_bind(status_label_, [] {
        const auto& p = ui_shell::style_palette();
        const auto get = [&p](const char* k) {
            const auto it = p.find(k);
            return it != p.end() ? QString::fromStdString(it->second)
                                 : QString();
        };
        return QStringLiteral(
                   "color: %1; background: %2;"
                   " border: 1px solid %3; border-radius: 4px;"
                   " padding: 3px 8px;")
            .arg(get("TEXT_SECONDARY"), get("BG_SEARCH"),
                 get("BORDER_LIGHT"));
    });
    status_label_->setAlignment(Qt::AlignCenter);
    layout->addWidget(status_label_);

    layer_list_ = new QListWidget(this);
    connect(layer_list_, &QListWidget::itemChanged, this,
            [this](QListWidgetItem* item) { on_item_changed(item); });
    layout->addWidget(layer_list_, 1);

    auto* controls = new QHBoxLayout();
    controls->addWidget(new QLabel(QStringLiteral("透明度"), this));
    opacity_slider_ = new QSlider(Qt::Horizontal, this);
    opacity_slider_->setRange(0, 100);
    connect(opacity_slider_, &QSlider::valueChanged, this,
            [this](int v) { on_opacity_changed(v); });
    controls->addWidget(opacity_slider_, 1);
    layout->addLayout(controls);
}

void MapReferencePanel::set_view(QWidget* view) {
    if (view == nullptr || view_host_ == nullptr) return;
    auto* view_layout = qobject_cast<QVBoxLayout*>(view_host_->layout());
    if (view_layout == nullptr) return;
    if (view_ != nullptr) {
        view_layout->removeWidget(view_);
        view_->deleteLater();
        view_ = nullptr;
    }
    view_placeholder_->hide();
    view_ = view;
    view->setParent(view_host_);
    view_layout->addWidget(view);
}

void MapReferencePanel::set_linked(bool linked) {
    if (link_check_ == nullptr) return;
    const QSignalBlocker block(link_check_);
    link_check_->setChecked(linked);
}

bool MapReferencePanel::linked() const {
    return link_check_ != nullptr && link_check_->isChecked();
}

void MapReferencePanel::set_layers(
    const std::vector<MapReferenceLayer>& layers) {
    // V11 D2 ⑮：clear+rebuild → 键差分（键 = 参考层 id）。
    suppress_ = true;
    layers_.clear();
    std::vector<QString> keys;
    keys.reserve(layers.size());
    for (const auto& layer : layers) {
        layers_[layer.id] = layer;
        keys.push_back(layer.id);
    }
    ui_widgets::reconcile_widget_items(
        layer_list_, keys,
        [](const QString&) { return new QListWidgetItem(QString()); },
        [this](QListWidgetItem* item, const QString& key) {
            update_layer_item(item, key);
        });
    status_label_->setText(status_summary(layers));
    if (!layers.empty()) {
        layer_list_->setCurrentRow(0);
        opacity_slider_->setValue(
            static_cast<int>(std::lround(layers[0].opacity * 100.0)));
    }
    suppress_ = false;
}

void MapReferencePanel::update_layer_item(QListWidgetItem* item,
                                          const QString& key) {
    const auto it = layers_.find(key);
    if (it == layers_.end()) {
        return;
    }
    const MapReferenceLayer& layer = it->second;
    const QString label = layer_label(layer);
    if (item->text() != label) {
        item->setText(label);
    }
    item->setData(Qt::UserRole, layer.id);
    item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
    item->setCheckState(layer.visible ? Qt::Checked : Qt::Unchecked);
    // 就绪状态清掉旧错误 tooltip，非就绪展示错误/状态。
    item->setToolTip(layer.status != QLatin1String("ready")
                         ? (!layer.error_message.isEmpty()
                                ? layer.error_message
                                : layer.status)
                         : QString());
}

QString MapReferencePanel::layer_label(const MapReferenceLayer& layer) {
    QString label = layer.name;
    if (layer.status == QLatin1String("offline")) {
        label += QStringLiteral(" (离线)");
    } else if (layer.status == QLatin1String("failed")) {
        label += QStringLiteral(" (失败)");
    }
    if (layer.external) {
        label += QStringLiteral(" [外部]");
    }
    return label;
}

QString MapReferencePanel::status_summary(
    const std::vector<MapReferenceLayer>& layers) {
    if (layers.empty()) {
        return QStringLiteral("暂无参考图");
    }
    int offline = 0, failed = 0, external = 0;
    for (const auto& layer : layers) {
        if (layer.status == QLatin1String("offline")) ++offline;
        if (layer.status == QLatin1String("failed")) ++failed;
        if (layer.external) ++external;
    }
    QStringList parts{QStringLiteral("坐标已对齐")};
    if (offline) {
        parts.append(QStringLiteral("%1 层离线").arg(offline));
    }
    if (failed) {
        parts.append(QStringLiteral("%1 层失败").arg(failed));
    }
    if (external) {
        parts.append(QStringLiteral("%1 外部").arg(external));
    }
    return parts.join(QStringLiteral(" · "));
}

void MapReferencePanel::on_item_changed(QListWidgetItem* item) {
    if (!suppress_) {
        emit reference_visibility_changed(
            item->data(Qt::UserRole).toString(),
            item->checkState() == Qt::Checked);
    }
}

void MapReferencePanel::on_opacity_changed(int value) {
    QListWidgetItem* item = layer_list_->currentItem();
    if (item != nullptr && !suppress_) {
        emit reference_opacity_changed(
            item->data(Qt::UserRole).toString(),
            static_cast<double>(value) / 100.0);
    }
}

}  // namespace pwb::ui_pages_mapedit
