// UI-06 — FilterChipsBar shell (see qt/filter_chips_bar.hpp).
#include <pwb/ui_pages_data/qt/filter_chips_bar.hpp>

#include <QComboBox>
#include <QHBoxLayout>
#include <QInputDialog>
#include <QMessageBox>
#include <QMouseEvent>
#include <QPushButton>

#include <pwb/ui_pages_data/vocab.hpp>
#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_pages_data::qt {
namespace {

QString chip_qss() {
    const auto p = ui_shell::style_palette();
    auto at = [&](const char* k) {
        const auto it = p.find(k);
        return it != p.end() ? QString::fromStdString(it->second) : QString();
    };
    return QStringLiteral(
               "QLabel#FilterChip { background: %1;"
               " border: 1px solid %2; border-radius: 9px;"
               " padding: 1px 8px; color: %3; font-size: 12px; }")
        .arg(at("BG_SIDEBAR"), at("BORDER"), at("TEXT_PRIMARY"));
    // FONT_SIZE_MINOR
}

}  // namespace

// ---------------------------------------------------------------------------
// FilterChip

FilterChip::FilterChip(const QString& key, const QString& text,
                       QWidget* parent)
    : QLabel(text, parent), key_(key) {
    setObjectName(QStringLiteral("FilterChip"));
    setToolTip(QStringLiteral("点击移除该过滤条件"));
    ui_shell::style_bind(this, chip_qss);
    setCursor(Qt::CursorShape::PointingHandCursor);
}

void FilterChip::mousePressEvent(QMouseEvent* event) {
    if (event->type() == QEvent::Type::MouseButtonPress) {
        Q_EMIT clicked(key_);
        return;
    }
    QLabel::mousePressEvent(event);
}

// ---------------------------------------------------------------------------
// FilterChipsBar

FilterChipsBar::FilterChipsBar(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("FilterChipsBar"));
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(4);                       // SPACE_1
    chips_layout_ = new QHBoxLayout();
    chips_layout_->setContentsMargins(0, 0, 0, 0);
    chips_layout_->setSpacing(4);                // SPACE_1
    layout->addLayout(chips_layout_, 1);

    clear_btn_ = new QPushButton(QStringLiteral("清除全部"), this);
    clear_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    clear_btn_->setToolTip(QStringLiteral("移除全部过滤条件"));
    connect(clear_btn_, &QPushButton::clicked, this,
            &FilterChipsBar::clear_all);
    layout->addWidget(clear_btn_);

    saved_combo_ = new QComboBox(this);
    saved_combo_->setToolTip(
        QStringLiteral("应用已保存的过滤器（用户设置）"));
    saved_combo_->addItem(QString::fromStdString(
        std::string(kSavedFiltersPlaceholder)));
    connect(saved_combo_,
            QOverload<int>::of(&QComboBox::activated), this,
            &FilterChipsBar::apply_saved);
    layout->addWidget(saved_combo_);
    save_btn_ = new QPushButton(QStringLiteral("保存过滤器…"), this);
    save_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(save_btn_, &QPushButton::clicked, this,
            &FilterChipsBar::save_current);
    layout->addWidget(save_btn_);
    delete_saved_btn_ = new QPushButton(QStringLiteral("删除"), this);
    delete_saved_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    delete_saved_btn_->setToolTip(
        QStringLiteral("删除当前选择的已保存过滤器"));
    connect(delete_saved_btn_, &QPushButton::clicked, this,
            &FilterChipsBar::delete_saved);
    layout->addWidget(delete_saved_btn_);

    reload_saved();
    set_query(query_);
}

void FilterChipsBar::set_saved_filter_store(SavedFilterStore store) {
    store_ = std::move(store);
    reload_saved();
}

std::vector<std::pair<std::string, domain::Json>>
FilterChipsBar::stored_filters() const {
    const std::string raw =
        store_.get ? store_.get() : memory_store_;
    return saved_filters_load(raw);
}

void FilterChipsBar::dump_filters(
    const std::vector<std::pair<std::string, domain::Json>>& filters) {
    const std::string payload = saved_filters_dump(filters);
    if (store_.set) {
        store_.set(payload);
    } else {
        memory_store_ = payload;
    }
}

void FilterChipsBar::set_query(const FilterQuery& query) {
    query_ = query;
    while (chips_layout_->count()) {
        QLayoutItem* item = chips_layout_->takeAt(0);
        if (QWidget* widget = item->widget()) widget->deleteLater();
        delete item;
    }
    const auto dims = filter_dimensions(query);
    for (const auto& [key, label] : dims) {
        add_chip(QString::fromStdString(key),
                 QString::fromStdString(label));
    }
    clear_btn_->setVisible(!dims.empty());
}

void FilterChipsBar::add_chip(const QString& key, const QString& label) {
    auto* chip = new FilterChip(key, label + QStringLiteral("  ✕"), this);
    connect(chip, &FilterChip::clicked, this,
            &FilterChipsBar::chip_removed);
    chips_layout_->addWidget(chip);
}

void FilterChipsBar::reload_saved() {
    const QString current = saved_combo_->currentText();
    saved_combo_->blockSignals(true);
    saved_combo_->clear();
    saved_combo_->addItem(
        QString::fromStdString(std::string(kSavedFiltersPlaceholder)));
    for (const auto& name : saved_filter_names_sorted(stored_filters())) {
        saved_combo_->addItem(QString::fromStdString(name));
    }
    if (!current.isEmpty()) {
        const int index = saved_combo_->findText(current);
        if (index >= 0) saved_combo_->setCurrentIndex(index);
    }
    saved_combo_->blockSignals(false);
}

void FilterChipsBar::apply_saved(int index) {
    const QString name = saved_combo_->itemText(index);
    saved_combo_->setCurrentIndex(0);
    if (name.isEmpty()) return;
    const auto stored = stored_filters();
    const auto it = std::find_if(
        stored.begin(), stored.end(), [&](const auto& pair) {
            return pair.first == name.toStdString();
        });
    if (it == stored.end()) return;
    try {
        Q_EMIT filter_applied(filter_query_from_dict(it->second));
    } catch (...) {
        QMessageBox::warning(this, QStringLiteral("应用过滤器"),
                             QStringLiteral("该保存的过滤器无法解析"));
    }
}

void FilterChipsBar::save_current() {
    bool ok = false;
    const QString name =
        QInputDialog::getText(this, QStringLiteral("保存过滤器"),
                              QStringLiteral("名称:"), QLineEdit::Normal,
                              QString(), &ok)
            .trimmed();
    if (!ok || name.isEmpty()) return;
    auto filters = stored_filters();
    const domain::Json dict = filter_query_to_dict(query_);
    const auto it = std::find_if(
        filters.begin(), filters.end(), [&](const auto& pair) {
            return pair.first == name.toStdString();
        });
    if (it != filters.end()) {
        it->second = dict;   // existing name keeps its dict position
    } else {
        filters.emplace_back(name.toStdString(), dict);
    }
    dump_filters(filters);
    reload_saved();
    saved_combo_->setCurrentIndex(saved_combo_->findText(name));
}

void FilterChipsBar::delete_saved() {
    const QString name = saved_combo_->currentText();
    if (name.isEmpty() ||
        name == QString::fromStdString(
                    std::string(kSavedFiltersPlaceholder))) {
        return;
    }
    auto filters = stored_filters();
    filters.erase(std::remove_if(filters.begin(), filters.end(),
                                 [&](const auto& pair) {
                                     return pair.first == name.toStdString();
                                 }),
                  filters.end());
    dump_filters(filters);
    reload_saved();
}

}  // namespace pwb::ui_pages_data::qt
