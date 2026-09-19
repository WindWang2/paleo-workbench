#include "pwb/ui_pages_mapedit/map_attribute_table.hpp"

#include "pwb/ui_data_core/json_util.hpp"
#include "pwb/ui_shell/style_registry.hpp"
#include "pwb/ui_widgets/reconcile.hpp"

#include <QAbstractItemView>
#include <QHeaderView>
#include <QLabel>
#include <QLineEdit>
#include <QListWidgetItem>
#include <QTableWidget>
#include <QTableWidgetItem>
#include <QTimer>
#include <QVBoxLayout>

#include <algorithm>
#include <set>

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

// Python ``str(value or "")``: falsy → "" (None/0/[] all collapse).
QString truthy_str(const domain::Json& value) {
    return ui_data_core::json_truthy(value)
               ? QString::fromStdString(ui_data_core::python_str(value))
               : QString();
}

bool record_has(const domain::Json& record, const QString& key) {
    return record.is_object() &&
           record.find(key.toStdString()) != record.end();
}

}  // namespace

// --- FeatureSelectorList ------------------------------------------------------

FeatureSelectorList::FeatureSelectorList(QWidget* parent)
    : QListWidget(parent) {
    setSelectionMode(QListWidget::SingleSelection);
}

QVariant FeatureSelectorList::currentData(int role) const {
    QListWidgetItem* item = currentItem();
    return item == nullptr ? QVariant() : item->data(role);
}

int FeatureSelectorList::findData(const QVariant& data, int role) const {
    for (int row = 0; row < count(); ++row) {
        if (item(row)->data(role) == data) {
            return row;
        }
    }
    return -1;
}

QString FeatureSelectorList::itemText(int row) const {
    QListWidgetItem* item = this->item(row);
    return item == nullptr ? QString() : item->text();
}

// --- MapAttributeTable --------------------------------------------------------

MapAttributeTable::MapAttributeTable(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("MapAttributeTable"));

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(tok_int("PANEL_PADDING", 12),
                               tok_int("SPACE_2", 8),
                               tok_int("PANEL_PADDING", 12),
                               tok_int("SPACE_2", 8));
    layout->setSpacing(tok_int("SPACE_2", 8));

    auto* title = new QLabel(QStringLiteral("属性"), this);
    title->setObjectName(QStringLiteral("MapDockTitle"));
    layout->addWidget(title);

    // 要素选择器（V11 D2 ②）：搜索框 + 有界列表 + 计数脚注。
    feature_search = new QLineEdit(this);
    feature_search->setObjectName(
        QStringLiteral("MapAttributeFeatureSearch"));
    feature_search->setPlaceholderText(QStringLiteral("搜索要素…"));
    feature_search->setClearButtonEnabled(true);
    layout->addWidget(feature_search);

    feature_combo = new FeatureSelectorList(this);
    feature_combo->setObjectName(
        QStringLiteral("MapAttributeFeatureSelector"));
    feature_combo->setToolTip(QStringLiteral(
        "活动图层要素选择（输入过滤；列表有界显示前 500 项）"));
    feature_combo->setMaximumHeight(kSelectorListMaxHeight);
    layout->addWidget(feature_combo);

    feature_count_label_ = new QLabel(QString(), this);
    feature_count_label_->setObjectName(
        QStringLiteral("MapAttributeFootnote"));
    ui_shell::style_bind(feature_count_label_, [] {
        const auto& p = ui_shell::style_palette();
        const auto get = [&p](const char* k) {
            const auto it = p.find(k);
            return it != p.end() ? QString::fromStdString(it->second)
                                 : QString();
        };
        return QStringLiteral("color: %1; font-size: %2;")
            .arg(get("TEXT_SECONDARY"), get("FONT_SIZE_STATUS"));
    });
    feature_count_label_->hide();
    layout->addWidget(feature_count_label_);

    table = new QTableWidget(0, 2, this);
    table->setObjectName(QStringLiteral("MapAttributeTableWidget"));
    table->setHorizontalHeaderLabels(
        {QStringLiteral("属性"), QStringLiteral("值")});
    table->horizontalHeader()->setSectionResizeMode(
        0, QHeaderView::ResizeToContents);
    table->horizontalHeader()->setSectionResizeMode(
        1, QHeaderView::Stretch);
    table->verticalHeader()->setVisible(false);
    table->setSelectionBehavior(QAbstractItemView::SelectRows);
    table->setEditTriggers(QAbstractItemView::DoubleClicked |
                           QAbstractItemView::SelectedClicked |
                           QAbstractItemView::EditKeyPressed);
    layout->addWidget(table, 1);

    // V11：搜索防抖（评审 P1-1：全量过滤扫描不逐键执行）。
    search_debounce_ = new QTimer(this);
    search_debounce_->setSingleShot(true);
    search_debounce_->setInterval(200);
    connect(search_debounce_, &QTimer::timeout, this,
            [this]() { apply_search_now(); });
    connect(table, &QTableWidget::itemChanged, this,
            [this](QTableWidgetItem* item) { on_item_changed(item); });
    connect(feature_combo, &QListWidget::currentItemChanged, this,
            [this](QListWidgetItem* cur, QListWidgetItem* prev) {
                on_feature_selected(cur, prev);
            });
    connect(feature_search, &QLineEdit::textChanged, this,
            [this](const QString& text) { on_search_changed(text); });
    // 初始占位行（构造期不发出选择信号——旧空 QComboBox 同语义）。
    suppress_feature_selection_ = true;
    refresh_selector(nullptr);
    suppress_feature_selection_ = false;
}

// -- 可见窗口 ---------------------------------------------------------------

QStringList MapAttributeTable::visible_feature_ids() const {
    // Feature ids surviving the current filter, in current sort order.
    QStringList ids;
    for (const QString& fid : layer_order_) {
        ids.append(fid);
    }
    const QString field = filter_field_;
    const QString needle = filter_needle_.trimmed().toLower();
    if (!field.isEmpty() && !needle.isEmpty()) {
        QStringList kept;
        for (const QString& fid : ids) {
            const domain::Json& feature = layer_features_.at(fid);
            // value = props.get(field, feature.get(field)); str(value or "")
            QString value;
            const auto pit = feature.find("properties");
            const domain::Json* props =
                pit != feature.end() && pit->is_object() ? &*pit : nullptr;
            const QString fkey = field;
            bool found = false;
            if (props != nullptr) {
                const auto vit = props->find(fkey.toStdString());
                if (vit != props->end()) {
                    value = truthy_str(*vit);
                    found = true;
                }
            }
            if (!found) {
                const auto vit = feature.find(fkey.toStdString());
                if (vit != feature.end()) {
                    value = truthy_str(*vit);
                }
            }
            if (value.toLower().contains(needle)) {
                kept.append(fid);
            }
        }
        ids = kept;
    }
    const QString search = search_needle_.trimmed().toLower();
    if (!search.isEmpty()) {
        // 搜索框按“下拉展示文本 + 要素 id”过滤。
        QStringList kept;
        for (const QString& fid : ids) {
            const QString label =
                combo_label(layer_features_.at(fid), fid).toLower();
            if (label.contains(search) || fid.toLower().contains(search)) {
                kept.append(fid);
            }
        }
        ids = kept;
    }
    if (!sort_field_.isEmpty()) {
        std::stable_sort(ids.begin(), ids.end(), [this](const QString& a,
                                                       const QString& b) {
            const auto sort_key = [this](const QString& fid) {
                const domain::Json& feature = layer_features_.at(fid);
                const auto pit = feature.find("properties");
                const domain::Json* props =
                    pit != feature.end() && pit->is_object() ? &*pit
                                                             : nullptr;
                const std::string fkey = sort_field_.toStdString();
                if (props != nullptr) {
                    const auto vit = props->find(fkey);
                    if (vit != props->end()) {
                        return truthy_str(*vit);
                    }
                }
                const auto vit = feature.find(fkey);
                if (vit != feature.end()) {
                    return truthy_str(*vit);
                }
                return QString();
            };
            return sort_key(a) < sort_key(b);
        });
    }
    return ids;
}

QStringList MapAttributeTable::selector_keys(const QStringList& visible,
                                           const QString& pin_id) const {
    // 占位行 + 置顶选中 + 过滤/排序窗口（截断到 _MAX_VISIBLE）。
    const QString pin = pin_id.isNull() ? feature_id_ : pin_id;
    QStringList window = visible;
    if (window.contains(pin)) {
        window.removeAll(pin);
        window.prepend(pin);
    }
    QStringList keys{QString()};
    for (int i = 0; i < window.size() && i < kMaxVisible; ++i) {
        keys.append(window[i]);
    }
    return keys;
}

QListWidgetItem* MapAttributeTable::make_feature_item(const QString& key) {
    if (key.isEmpty()) {
        return new QListWidgetItem(QStringLiteral("— 未选择 —"));
    }
    const auto it = layer_features_.find(key);
    const QString label =
        it != layer_features_.end() ? combo_label(it->second, key) : key;
    return new QListWidgetItem(label);
}

void MapAttributeTable::update_feature_item(QListWidgetItem* item,
                                            const QString& key) {
    if (key.isEmpty()) {
        if (item->text() != QLatin1String("— 未选择 —")) {
            item->setText(QStringLiteral("— 未选择 —"));
        }
        item->setData(Qt::UserRole, QString());
        return;
    }
    item->setData(Qt::UserRole, key);
    const auto it = layer_features_.find(key);
    if (it == layer_features_.end()) {
        return;  // 已被过滤/解绑的键——reconcile 随后会移除
    }
    const QString label = combo_label(it->second, key);
    if (item->text() != label) {
        item->setText(label);
    }
}

void MapAttributeTable::refresh_selector(const QString* pin_id) {
    // 把可见窗口同步进选择器列表（调用方负责选择抑制）。键差分——同键序
    // 零结构操作。
    const QStringList visible = visible_feature_ids();
    const QString pin = pin_id != nullptr ? *pin_id : feature_id_;
    const QStringList keys = selector_keys(visible, pin);
    std::vector<QString> key_vec(keys.begin(), keys.end());
    ui_widgets::reconcile_widget_items(
        feature_combo, key_vec,
        [this](const QString& k) { return make_feature_item(k); },
        [this](QListWidgetItem* item, const QString& k) {
            update_feature_item(item, k);
        });
    // 当前选中行：仍可见则落在置顶行；否则回落占位行（不清属性格）。
    const int row =
        !pin.isEmpty() ? feature_combo->findData(pin) : -1;
    feature_combo->setCurrentRow(std::max(0, row));
    if (visible.size() > kMaxVisible) {
        feature_count_label_->setText(QStringLiteral(
            "共 %1 个要素，显示前 %2，输入过滤…")
            .arg(visible.size())
            .arg(kMaxVisible));
        feature_count_label_->show();
    } else {
        feature_count_label_->hide();
    }
}

void MapAttributeTable::on_search_changed(const QString& text) {
    search_needle_ = text;
    // 200ms 防抖（与 TagManagerDialog 同口径）。程序化 setText（无焦点）
    // 立即应用：属性同步测试与宿主脚本依赖同步收窄窗口的契约。
    if (feature_search->hasFocus()) {
        search_debounce_->start();
    } else {
        search_debounce_->stop();
        apply_search_now();
    }
}

void MapAttributeTable::apply_search_now() {
    suppress_feature_selection_ = true;
    refresh_selector(nullptr);
    suppress_feature_selection_ = false;
}

QStringList MapAttributeTable::apply_filter(const QString& field,
                                            const QString& needle) {
    filter_field_ = field;
    filter_needle_ = needle;
    const QStringList visible = visible_feature_ids();
    const QString selected =
        feature_combo->currentData().toString();
    suppress_feature_selection_ = true;
    refresh_selector(&selected);
    suppress_feature_selection_ = false;
    if (!visible.contains(selected)) {
        set_feature(nullptr);
        // the previously selected feature is now hidden — the map must
        // drop its highlight too (review R3-P3).
        emit feature_selection_requested(QString());
        return visible;
    }
    return visible;
}

QStringList MapAttributeTable::sort_features(const QString& field) {
    sort_field_ = field;
    return apply_filter(filter_field_, filter_needle_);
}

void MapAttributeTable::set_feature(const domain::Json* feature) {
    has_feature_ = feature != nullptr && feature->is_object();
    feature_ = has_feature_ ? *feature : domain::Json();
    feature_id_ =
        has_feature_
            ? truthy_str(feature_.contains("id") ? feature_["id"]
                                                 : domain::Json())
            : QString();
    rebuild();
}

QString MapAttributeTable::combo_label(const domain::Json& feature,
                                       const QString& feature_id) {
    // str(feature.get("name") or feature.get("text") or feature_id)
    const auto get = [&feature](const char* key) {
        const auto it = feature.find(key);
        return it != feature.end() ? truthy_str(*it) : QString();
    };
    const QString name = get("name");
    if (!name.isEmpty()) {
        return name;
    }
    const QString text = get("text");
    return text.isEmpty() ? feature_id : text;
}

void MapAttributeTable::set_layer_features(
    const std::vector<domain::Json>& features,
    const QStringList& selected_ids) {
    // Bind the property grid to one active vector layer without edit
    // shadow state.
    std::map<QString, domain::Json> new_features;
    std::vector<QString> order;
    for (const auto& feature : features) {
        if (!feature.is_object()) {
            continue;
        }
        const QString fid = truthy_str(
            feature.contains("id") ? feature["id"] : domain::Json());
        if (fid.isEmpty()) {
            continue;
        }
        if (!new_features.count(fid)) {
            order.push_back(fid);
        }
        new_features[fid] = feature;
    }
    QStringList sorted_selected = selected_ids;
    sorted_selected.sort();
    QString selected = sorted_selected.isEmpty() ? QString()
                                               : sorted_selected.first();
    if (!new_features.count(selected)) {
        selected.clear();
    }
    layer_features_ = std::move(new_features);
    layer_order_ = std::move(order);
    suppress_feature_selection_ = true;
    // 置顶键用本次目标选中（而非旧的 _feature_id）。
    refresh_selector(&selected);
    suppress_feature_selection_ = false;
    const auto it = layer_features_.find(selected);
    set_feature(it != layer_features_.end() ? &it->second : nullptr);
}

void MapAttributeTable::update_layer_features(
    const std::vector<domain::Json>& features,
    const QStringList& selected_ids) {
    // 差量更新已绑定要素的记录（要素 id 集不变；C-P0-3）。
    for (const auto& feature : features) {
        if (!feature.is_object()) {
            continue;
        }
        const QString fid = truthy_str(
            feature.contains("id") ? feature["id"] : domain::Json());
        if (fid.isEmpty() || !layer_features_.count(fid)) {
            continue;
        }
        layer_features_[fid] = feature;
    }
    suppress_feature_selection_ = true;
    refresh_selector(nullptr);
    suppress_feature_selection_ = false;
    set_selected_ids(selected_ids);
}

void MapAttributeTable::set_selected_ids(const QStringList& selected_ids) {
    // Move the selector/feature selection without rebuilding feature
    // entries (selection-only updates stay O(1)).
    if (layer_features_.empty()) {
        return;
    }
    QStringList sorted = selected_ids;
    sorted.sort();
    QString selected = sorted.isEmpty() ? QString() : sorted.first();
    if (!layer_features_.count(selected)) {
        selected.clear();
    }
    suppress_feature_selection_ = true;
    if (feature_combo->findData(selected) < 0) {
        // 选中要素不在当前可见窗口（被过滤/截断）——重排窗口置顶。
        refresh_selector(&selected);
    }
    const int row = feature_combo->findData(selected);
    feature_combo->setCurrentRow(std::max(0, row));
    suppress_feature_selection_ = false;
    const auto it = layer_features_.find(selected);
    set_feature(it != layer_features_.end() ? &it->second : nullptr);
}

void MapAttributeTable::on_feature_selected(QListWidgetItem* current,
                                            QListWidgetItem* /*previous*/) {
    if (suppress_feature_selection_ || current == nullptr) {
        return;
    }
    emit feature_selection_requested(
        feature_combo->currentData().toString());
}

void MapAttributeTable::rebuild() {
    suppress_item_changed_ = true;
    table->setRowCount(0);
    if (!has_feature_) {
        suppress_item_changed_ = false;
        return;
    }

    struct Row {
        QString key;
        QString value;
        bool editable;
    };
    std::vector<Row> rows;
    for (const QString& key : display_keys()) {
        const bool present = record_has(feature_, key);
        if (!present && key != QLatin1String("text") &&
            key != QLatin1String("topology_status")) {
            continue;
        }
        if (!present) {
            continue;  // text/topology_status 仅存在时显示
        }
        const auto vit = feature_.find(key.toStdString());
        if (key == QLatin1String("topology_status")) {
            // Friendlier display for topology warnings:
            // "警告" if value == "warning" else str(value or "ok").
            const QString value = truthy_str(*vit);
            rows.push_back({key, value == QLatin1String("warning")
                                       ? QStringLiteral("警告")
                                       : (value.isEmpty()
                                              ? QStringLiteral("ok")
                                              : value),
                            false});
            continue;
        }
        const bool editable = key == QLatin1String("name") ||
                              key == QLatin1String("text");
        rows.push_back({key,
                        vit->is_null() ? QString()
                                       : QString::fromStdString(
                                             ui_data_core::python_str(*vit)),
                        editable});
    }

    const auto cit = feature_.find("coordinates");
    if (cit != feature_.end() && !cit->is_null()) {
        rows.push_back({QStringLiteral("geometry"), geometry_summary(*cit),
                        false});
    }

    table->setRowCount(static_cast<int>(rows.size()));
    for (int row = 0; row < static_cast<int>(rows.size()); ++row) {
        const auto& [key, value, editable] = rows[row];
        auto* key_item = new QTableWidgetItem(key);
        key_item->setFlags(key_item->flags() & ~Qt::ItemIsEditable);
        auto* value_item = new QTableWidgetItem(value);
        if (!editable) {
            value_item->setFlags(value_item->flags() & ~Qt::ItemIsEditable);
        }
        value_item->setData(Qt::UserRole, key);
        table->setItem(row, 0, key_item);
        table->setItem(row, 1, value_item);
    }

    suppress_item_changed_ = false;
}

QString MapAttributeTable::geometry_summary(const domain::Json& coords) {
    if (!coords.is_array()) {
        return QString::fromStdString(ui_data_core::python_str(coords));
    }
    if (coords.empty()) {
        return QStringLiteral("empty");
    }
    const auto& first = coords[0];
    if (first.is_array()) {
        return QStringLiteral("%1 pts").arg(coords.size());
    }
    if (coords.size() >= 2) {
        return QStringLiteral("(%1, %2)")
            .arg(QString::fromStdString(ui_data_core::python_str(coords[0])),
                 QString::fromStdString(ui_data_core::python_str(coords[1])));
    }
    return QString::fromStdString(ui_data_core::python_str(coords));
}

void MapAttributeTable::on_item_changed(QTableWidgetItem* item) {
    if (suppress_item_changed_) {
        return;
    }
    if (item->column() != 1) {
        return;
    }
    const QString key = item->data(Qt::UserRole).toString();
    if (key.isEmpty() || feature_id_.isEmpty()) {
        return;
    }
    const QString value = item->text();
    if (has_feature_ && feature_.is_object()) {
        feature_[key.toStdString()] = value.toStdString();
    }
    emit property_changed(feature_id_, key, value);
}

}  // namespace pwb::ui_pages_mapedit
