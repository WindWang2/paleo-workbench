#include "factor_reference_strip.hpp"

#include <QHBoxLayout>
#include <QLabel>
#include <QListWidget>
#include <QPushButton>
#include <QVBoxLayout>

namespace pwb::app {

namespace {

QString jstr(const pwb::domain::Json& obj, const char* key) {
    const auto it = obj.find(key);
    if (it == obj.end() || !it->is_string()) return QString();
    return QString::fromStdString(it->get<std::string>());
}

}  // namespace

FactorReferenceStrip::FactorReferenceStrip(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("FactorReferenceStrip"));
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(4, 2, 4, 2);
    outer->setSpacing(2);

    auto* row = new QHBoxLayout;
    row->setSpacing(6);
    auto* caption = new QLabel(QStringLiteral("单因素参考带"), this);
    caption->setObjectName(QStringLiteral("FactorStripCaption"));
    row->addWidget(caption);
    detail_ = new QLabel(QStringLiteral("选择一张参考图查看详情"), this);
    detail_->setObjectName(QStringLiteral("FactorStripDetail"));
    row->addWidget(detail_, 1);
    auto* overlay = new QPushButton(QStringLiteral("叠加到主图"), this);
    overlay->setObjectName(QStringLiteral("FactorStripOverlay"));
    overlay->setToolTip(QStringLiteral(
        "把已完成的单因素结果叠加到主图（不替换主成果）"));
    connect(overlay, &QPushButton::clicked, this, [this] {
        if (!selected_.empty()) emit overlay_requested(selected_);
    });
    row->addWidget(overlay);
    outer->addLayout(row);

    cards_ = new QListWidget(this);
    cards_->setObjectName(QStringLiteral("FactorStripCards"));
    cards_->setViewMode(QListView::IconMode);
    cards_->setFlow(QListView::LeftToRight);
    cards_->setWrapping(false);
    cards_->setResizeMode(QListView::Adjust);
    cards_->setMovement(QListView::Static);
    cards_->setIconSize(QSize(96, 96));
    cards_->setGridSize(QSize(128, 124));
    cards_->setSpacing(4);
    cards_->setHorizontalScrollBarPolicy(Qt::ScrollBarAsNeeded);
    cards_->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    cards_->setFixedHeight(132);
    connect(cards_, &QListWidget::itemClicked, this,
            [this](QListWidgetItem* item) {
                if (syncing_ || item == nullptr) return;
                const int index = item->data(Qt::UserRole).toInt();
                if (index < 0 ||
                    index >= static_cast<int>(tasks_.size())) {
                    return;
                }
                // Single-selection model: exactly one checked card (F:68
                // reference switching, never a multi-select mutation of the
                // main product).
                syncing_ = true;
                for (int i = 0; i < cards_->count(); ++i) {
                    auto* other = cards_->item(i);
                    other->setCheckState(i == index ? Qt::Checked
                                                    : Qt::Unchecked);
                }
                syncing_ = false;
                selected_ = tasks_[static_cast<size_t>(index)];
                show_detail(selected_);
                emit reference_selected(selected_);
            });
    outer->addWidget(cards_);
}

void FactorReferenceStrip::set_thumbnail_renderer(
    std::function<QPixmap(const pwb::domain::Json&, const QSize&)> renderer) {
    renderer_ = std::move(renderer);
    rebuild();
}

void FactorReferenceStrip::update_state(
    const std::vector<pwb::domain::Json>& tasks) {
    tasks_.clear();
    for (const auto& task : tasks) {
        const auto status = jstr(task, "status");
        if (status == QStringLiteral("complete")) tasks_.push_back(task);
    }
    // A disappeared task must not stay selected.
    bool selection_alive = false;
    if (!selected_.empty()) {
        const QString id = jstr(selected_, "id");
        for (const auto& task : tasks_) {
            if (jstr(task, "id") == id) {
                selection_alive = true;
                break;
            }
        }
    }
    if (!selection_alive) selected_ = pwb::domain::Json::object();
    rebuild();
}

void FactorReferenceStrip::rebuild() {
    syncing_ = true;
    cards_->clear();
    for (size_t i = 0; i < tasks_.size(); ++i) {
        const auto& task = tasks_[i];
        auto* item = new QListWidgetItem(card_text(task));
        item->setData(Qt::UserRole, static_cast<int>(i));
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
        item->setCheckState(Qt::Unchecked);
        if (renderer_ != nullptr) {
            const QPixmap thumb = renderer_(task, QSize(96, 96));
            if (!thumb.isNull()) item->setIcon(thumb);
        }
        cards_->addItem(item);
    }
    syncing_ = false;
    if (!selected_.empty()) {
        const QString id = jstr(selected_, "id");
        for (int i = 0; i < cards_->count(); ++i) {
            auto* item = cards_->item(i);
            const int index = item->data(Qt::UserRole).toInt();
            if (index >= 0 && index < static_cast<int>(tasks_.size()) &&
                jstr(tasks_[static_cast<size_t>(index)], "id") == id) {
                item->setCheckState(Qt::Checked);
            }
        }
    }
}

void FactorReferenceStrip::show_detail(const pwb::domain::Json& task) {
    const QString name = jstr(task, "name");
    const QString factor = jstr(task, "factor_type");
    const QString method = jstr(task, "method");
    const QString horizon = jstr(task, "target_horizon");
    QStringList parts;
    if (!name.isEmpty()) parts << name;
    if (!factor.isEmpty()) parts << factor;
    if (!method.isEmpty()) parts << method;
    if (!horizon.isEmpty()) parts << (QStringLiteral("层位 ") + horizon);
    detail_->setText(parts.isEmpty()
                         ? QStringLiteral("（无详情）")
                         : parts.join(QStringLiteral(" · ")));
}

QString FactorReferenceStrip::card_text(const pwb::domain::Json& task) {
    const QString name = jstr(task, "name");
    return name.isEmpty() ? QStringLiteral("（未命名）") : name;
}

}  // namespace pwb::app
