// UI-06 — HubPage shell (see qt/hub_page.hpp).
#include <pwb/ui_pages_data/qt/hub_page.hpp>

#include <QHBoxLayout>
#include <QPushButton>
#include <QStackedWidget>
#include <QStyle>
#include <QVBoxLayout>

namespace pwb::ui_pages_data::qt {

HubPage::HubPage(int hub_index, QWidget* parent)
    : QWidget(parent), hub_index_(hub_index) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);

    switcher_host_ = new QWidget(this);
    switcher_host_->setObjectName(QStringLiteral("SubmoduleSwitcher"));
    switcher_layout_ = new QHBoxLayout(switcher_host_);
    switcher_layout_->setContentsMargins(16, 4, 16, 4);  // PAGE_MARGIN/SPACE_1
    switcher_layout_->setSpacing(4);                     // SPACE_1

    stack_ = new QStackedWidget(this);
    layout->addWidget(switcher_host_);
    layout->addWidget(stack_, 1);
    switcher_host_->setVisible(false);
}

void HubPage::add_submodule(const std::string& key, const QString& title,
                            QWidget* page) {
    keys_.push_back(key);
    pages_[key] = page;
    stack_->addWidget(page);
    auto* btn = new QPushButton(title, switcher_host_);
    btn->setObjectName(QStringLiteral("SubmodulePill"));
    btn->setProperty("active", false);
    btn->setCursor(Qt::CursorShape::PointingHandCursor);
    const std::string k = key;
    connect(btn, &QPushButton::clicked, this,
            [this, k] { switch_to(k, /*emit=*/true); });
    buttons_.push_back(btn);
    switcher_layout_->addWidget(btn);
    // A single-sub-module hub has no visible switcher (可视化)；宿主
    // 也可经 set_switcher_visible 钉死隐藏（ws0 原型无 pill 行）。
    switcher_host_->setVisible(!switcher_hidden_ && keys_.size() > 1);
}

QWidget* HubPage::replace_submodule(const std::string& key, QWidget* page) {
    const auto it = pages_.find(key);
    if (it == pages_.end() || page == nullptr) return nullptr;
    QWidget* old = it->second;
    it->second = page;
    stack_->addWidget(page);
    if (current_ == key) stack_->setCurrentWidget(page);
    // Detach the old widget only when this stack still hosts it — the
    // adopt flow (task 04) reparents it into the composite BEFORE the
    // swap, and stealing it back there would gut the page.
    if (old->parent() == stack_) {
        stack_->removeWidget(old);
        old->setParent(nullptr);
    }
    return old;
}

void HubPage::finish() { switcher_layout_->addStretch(1); }

void HubPage::set_switcher_visible(bool on) {
    switcher_hidden_ = !on;
    switcher_host_->setVisible(on);
}

void HubPage::switch_to(const std::string& key, bool emit_signal) {
    QWidget* page_widget = nullptr;
    if (const auto it = pages_.find(key); it != pages_.end()) {
        page_widget = it->second;
    }
    if (page_widget == nullptr) return;
    current_ = key;
    if (page_widget->parent() == stack_) {
        stack_->setCurrentWidget(page_widget);
    }
    for (std::size_t i = 0; i < buttons_.size(); ++i) {
        buttons_[i]->setProperty("active", keys_[i] == key);
        buttons_[i]->style()->unpolish(buttons_[i]);
        buttons_[i]->style()->polish(buttons_[i]);
    }
    if (const auto it = activate_fns_.find(key); it != activate_fns_.end()) {
        it->second();
    }
    Q_EMIT page_activated(hub_index_, QString::fromStdString(key));
    if (emit_signal) {
        Q_EMIT submodule_changed(hub_index_, QString::fromStdString(key));
    }
}

std::string HubPage::current_key() const {
    if (!current_.empty()) return current_;
    const int index = stack_->currentIndex();
    if (0 <= index && index < static_cast<int>(keys_.size())) {
        return keys_[index];
    }
    return {};
}

QWidget* HubPage::current_page() const { return stack_->currentWidget(); }

QWidget* HubPage::page(const std::string& key) const {
    const auto it = pages_.find(key);
    return it != pages_.end() ? it->second : nullptr;
}

void HubPage::activate_page() {
    QWidget* current = stack_->currentWidget();
    for (const auto& [key, page_widget] : pages_) {
        if (page_widget == current) {
            if (const auto it = activate_fns_.find(key);
                it != activate_fns_.end()) {
                it->second();
            }
            return;
        }
    }
}

void HubPage::set_activate_fn(const std::string& key,
                              std::function<void()> fn) {
    activate_fns_[key] = std::move(fn);
}


// BEGIN CLOSURE-MAPPING (08-line adopt)
void HubPage::adopt_submodule(const std::string& key, QWidget* page) {
    const auto it = pages_.find(key);
    if (page == nullptr || it == pages_.end() || it->second == page) {
        return;
    }
    QWidget* old_page = it->second;
    // QStackedWidget has no replaceWidget — swap via index.
    const int index = stack_->indexOf(old_page);
    if (index < 0) return;
    stack_->removeWidget(old_page);
    stack_->insertWidget(index, page);
    old_page->deleteLater();
    it->second = page;
}
// END CLOSURE-MAPPING

}  // namespace pwb::ui_pages_data::qt
