#include "factor_atlas_panel.hpp"

#include <QLabel>
#include <QListWidget>
#include <QVBoxLayout>

namespace pwb::app {

namespace {

QString jstr(const pwb::domain::Json& obj, const char* key) {
    const auto it = obj.find(key);
    if (it == obj.end() || !it->is_string()) return QString();
    return QString::fromStdString(it->get<std::string>());
}

}  // namespace

FactorAtlasPanel::FactorAtlasPanel(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("FactorAtlasPanel"));
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(6, 6, 6, 6);
    outer->setSpacing(4);

    title_ = new QLabel(this);
    title_->setObjectName(QStringLiteral("FactorAtlasTitle"));
    outer->addWidget(title_);
    set_horizon(QString());

    empty_ = new QLabel(
        QStringLiteral("暂无已完成的单因素图 — 经 Ribbon「计算单因素」"
                       "生成后在此列出"),
        this);
    empty_->setObjectName(QStringLiteral("FactorAtlasEmpty"));
    empty_->setWordWrap(true);
    outer->addWidget(empty_);

    list_ = new QListWidget(this);
    list_->setObjectName(QStringLiteral("FactorAtlasList"));
    connect(list_, &QListWidget::itemChanged, this,
            [this](QListWidgetItem* item) {
                if (syncing_ || item == nullptr ||
                    item->checkState() != Qt::Checked) {
                    return;
                }
                // 单选语义：勾选一张即「当前叠加参考」，其余复位。
                syncing_ = true;
                for (int i = 0; i < list_->count(); ++i) {
                    if (list_->item(i) != item) {
                        list_->item(i)->setCheckState(Qt::Unchecked);
                    }
                }
                syncing_ = false;
                const int index = item->data(Qt::UserRole).toInt();
                if (index >= 0 &&
                    index < static_cast<int>(tasks_.size())) {
                    selected_ = tasks_[static_cast<size_t>(index)];
                    emit overlay_selected(selected_);
                }
            });
    outer->addWidget(list_, 1);
}

void FactorAtlasPanel::set_horizon(const QString& horizon) {
    horizon_ = horizon;
    title_->setText(horizon.isEmpty()
                        ? QStringLiteral("单因素图层")
                        : QStringLiteral("单因素图层（%1）").arg(horizon));
}

void FactorAtlasPanel::update_state(
    const std::vector<pwb::domain::Json>& tasks) {
    tasks_.clear();
    for (const auto& task : tasks) {
        if (jstr(task, "status") == QStringLiteral("complete")) {
            tasks_.push_back(task);
        }
    }
    if (!selected_.empty()) {
        const QString id = jstr(selected_, "id");
        bool alive = false;
        for (const auto& task : tasks_) {
            if (jstr(task, "id") == id) {
                alive = true;
                break;
            }
        }
        if (!alive) selected_ = pwb::domain::Json::object();
    }
    rebuild();
}

void FactorAtlasPanel::rebuild() {
    syncing_ = true;
    list_->clear();
    for (size_t i = 0; i < tasks_.size(); ++i) {
        const auto& task = tasks_[i];
        QString name = jstr(task, "name");
        if (name.isEmpty()) name = QStringLiteral("（未命名）");
        // 稿式「（当前）」标注在已选条目上。
        if (!selected_.empty() &&
            jstr(selected_, "id") == jstr(task, "id")) {
            name += QStringLiteral("（当前）");
        }
        auto* item = new QListWidgetItem(name);
        item->setData(Qt::UserRole, static_cast<int>(i));
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
        item->setCheckState(!selected_.empty() &&
                                    jstr(selected_, "id") ==
                                        jstr(task, "id")
                                ? Qt::Checked
                                : Qt::Unchecked);
        QStringList sub;
        const QString factor = jstr(task, "factor_type");
        const QString method = jstr(task, "method");
        if (!factor.isEmpty()) sub << factor;
        if (!method.isEmpty()) sub << method;
        if (!sub.isEmpty()) item->setToolTip(sub.join(QStringLiteral(" · ")));
        list_->addItem(item);
    }
    syncing_ = false;
    empty_->setVisible(tasks_.empty());
    list_->setVisible(!tasks_.empty());
}

}  // namespace pwb::app
