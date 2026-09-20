// UI-06 — DataAssetTable shell (see qt/data_asset_table.hpp).
#include <pwb/ui_pages_data/qt/data_asset_table.hpp>

#include <pwb/ui_pages_data/qt/vector_asset_row_source.hpp>

#include <QAction>
#include <QHeaderView>
#include <QMenu>
#include <QPushButton>
#include <QVBoxLayout>

#include <algorithm>

#include <pwb/ui_pages_data/chips.hpp>
#include <pwb/ui_pages_data/qt/filter_chips_bar.hpp>
#include <pwb/ui_pages_data/vocab.hpp>
#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_pages_data::qt {

DataAssetTable::DataAssetTable(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("DataAssetTable"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(8);                       // SPACE_2

    chips_bar_ = new FilterChipsBar(this);
    connect(chips_bar_, &FilterChipsBar::chip_removed, this,
            [this](const QString& key) {
                // data_asset_table._remove_filter_dimension — the "text"
                // chip additionally clears + re-emits the search text.
                const auto updated = remove_filter_dimension(
                    filter_query_, key.toStdString());
                if (!updated.has_value()) return;
                if (key == QLatin1String("text")) {
                    search_text_.clear();
                    Q_EMIT search_text_changed(QString());
                }
                set_filter_query(*updated);
            });
    connect(chips_bar_, &FilterChipsBar::clear_all, this, [this] {
        search_text_.clear();
        Q_EMIT search_text_changed(QString());
        set_filter_query(FilterQuery{});
    });
    connect(chips_bar_, &FilterChipsBar::filter_applied, this,
            &DataAssetTable::apply_saved_filter);
    layout->addWidget(chips_bar_);

    auto* toolbar = new QHBoxLayout();
    toolbar->setContentsMargins(0, 0, 0, 0);
    toolbar->addStretch();
    column_settings_btn_ =
        new QPushButton(QStringLiteral("列设置"), this);
    column_settings_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    column_settings_menu_ = new QMenu(column_settings_btn_);
    build_column_settings_menu();
    column_settings_btn_->setMenu(column_settings_menu_);
    toolbar->addWidget(column_settings_btn_);
    layout->addLayout(toolbar);

    table_ = new QTableView(this);
    table_->setObjectName(QStringLiteral("DataAssetGrid"));
    // CLOSURE-PREVIEW (task 04): a table without a model has no selection
    // model and crashes on the first update_assets — ship the vector row
    // source by default; set_model() replaces the pointer for UI-03 hosts.
    owned_model_ = new VectorAssetRowSource(this);
    install_model(owned_model_);
    connect(owned_model_, &QAbstractItemModel::modelReset, this,
            &DataAssetTable::on_model_reset);
    table_->setSelectionBehavior(
        QTableView::SelectionBehavior::SelectRows);
    table_->setSelectionMode(
        QTableView::SelectionMode::ExtendedSelection);
    table_->setEditTriggers(QTableView::EditTrigger::NoEditTriggers);
    // Header clicks route through on_header_clicked instead of the view's
    // built-in sorting so the user's sort intent is tracked explicitly.
    table_->setSortingEnabled(false);
    connect(table_->horizontalHeader(), &QHeaderView::sectionClicked, this,
            &DataAssetTable::on_header_clicked);
    connect(table_->horizontalHeader(), &QHeaderView::sectionResized, this,
            &DataAssetTable::on_section_resized);
    table_->verticalHeader()->setVisible(false);
    table_->horizontalHeader()->setSectionResizeMode(
        QHeaderView::ResizeMode::Interactive);
    table_->horizontalHeader()->setStretchLastSection(true);
    table_->setAlternatingRowColors(true);
    ui_shell::style_bind(table_, [] {
        const auto p = ui_shell::style_palette();
        auto at = [&](const char* k) {
            const auto it = p.find(k);
            return it != p.end() ? QString::fromStdString(it->second)
                                 : QString();
        };
        return QStringLiteral(
                   "QTableView#DataAssetGrid { background: %1;"
                   " border: 1px solid %2; border-radius: 4px;"
                   " gridline-color: %2; }")
            .arg(at("BG_SIDEBAR"), at("BORDER"));
    });
    table_->setContextMenuPolicy(
        Qt::ContextMenuPolicy::CustomContextMenu);
    connect(table_, &QTableView::customContextMenuRequested, this,
            &DataAssetTable::on_context_menu);
    layout->addWidget(table_);
}

void DataAssetTable::set_filter_fn(FilterIndexFn fn) {
    filter_fn_ = std::move(fn);
}

void DataAssetTable::set_model(AssetRowSource* model) {
    model_ = model;
    if (model_ != nullptr) {
        install_model(model_);
        connect(model_, &QAbstractItemModel::modelReset, this,
                &DataAssetTable::on_model_reset);
        // #1390: a source that re-sorts via layoutChanged + persistent-index
        // remap (the ObjectTableModel convention) never emits modelReset —
        // without this connection visible_assets_ keeps the pre-sort order
        // and sync_selection() selects the wrong rows.
        connect(model_, &QAbstractItemModel::layoutChanged, this,
                &DataAssetTable::on_model_reset);
    }
}

void DataAssetTable::set_paged_model(AssetRowSource* model) {
    paged_model_ = model;
    if (paged_model_ != nullptr) {
        connect(paged_model_, &QAbstractItemModel::modelReset, this,
                &DataAssetTable::on_model_reset);
        connect(paged_model_, &QAbstractItemModel::layoutChanged, this,
                &DataAssetTable::on_model_reset);
    }
}

AssetRowSource* DataAssetTable::active_model() const {
    auto* current = qobject_cast<AssetRowSource*>(table_->model());
    return current != nullptr ? current : model_;
}

void DataAssetTable::install_model(AssetRowSource* model) {
    if (table_->model() == model) return;
    table_->setModel(model);
    connect(table_->selectionModel(),
            &QItemSelectionModel::selectionChanged, this,
            &DataAssetTable::emit_selection);
}

void DataAssetTable::set_legacy_category_parse_fn(
    std::function<FilterQuery(const QString&, const std::string&)> fn) {
    legacy_parse_fn_ = std::move(fn);
}

void DataAssetTable::set_category(const QString& category) {
    if (legacy_parse_fn_) {
        set_filter_query(legacy_parse_fn_(category, search_text_));
    }
}

void DataAssetTable::update_assets(const std::vector<AssetRow>& assets) {
    if (in_paged_mode_) exit_paged_mode();
    assets_ = assets;
    if (model_ == owned_model_ && owned_model_ != nullptr) {
        owned_model_->set_rows(assets);  // the shipped source mirrors rows
    }
    const auto prev_primary = selected_asset_;
    const auto prev_multi = selected_assets_;
    const auto pre_build_sort =
        model_ != nullptr ? model_->last_sort() : std::nullopt;
    filter_query_.search_text = search_text_;
    chips_bar_->set_query(filter_query_);
    apply_filter();
    reapply_sort(pre_build_sort);
    sync_selection();
    emit_selection_changes(prev_primary, prev_multi);
}

void DataAssetTable::apply_filter() {
    // The model rebuild is the source model's business (set_filtered_rows /
    // set_assets_filtered in Python); the widget recomputes the visible
    // row list through the filter seam.
    const auto prev_primary = selected_asset_;
    const auto prev_multi = selected_assets_;
    const auto pre_build_sort =
        active_model() != nullptr ? active_model()->last_sort()
                                  : std::nullopt;
    // Without a host filter seam the identity filter applies (Python
    // shows the full set when no filter is armed) — an empty default left
    // every row invisible and wiped the selection on each update.
    const std::vector<int> filtered =
        filter_fn_
            ? filter_fn_(filter_query_)
            : [&] {
                  std::vector<int> all(assets_.size());
                  for (std::size_t i = 0; i < assets_.size(); ++i) {
                      all[static_cast<std::size_t>(i)] =
                          static_cast<int>(i);
                  }
                  return all;
              }();
    visible_assets_.clear();
    for (const int i : filtered) {
        if (0 <= i && i < static_cast<int>(assets_.size())) {
            visible_assets_.push_back(assets_[static_cast<std::size_t>(i)]);
        }
    }
    reapply_sort(pre_build_sort);
    sync_selection();
    emit_selection_changes(prev_primary, prev_multi);
}

void DataAssetTable::set_filter_query(const FilterQuery& query) {
    filter_query_ = query;
    filter_query_.search_text = search_text_;
    chips_bar_->set_query(filter_query_);
    // Paged-mode apply_query is the model's contract; the widget only
    // knows success/failure through the model's own signal path — kept as
    // a host responsibility (see ledger).
    apply_filter();
}

void DataAssetTable::set_search_text(const QString& text) {
    search_text_ = normalize_search_text(text.toStdString());
    set_filter_query(filter_query_);
}

void DataAssetTable::apply_saved_filter(const FilterQuery& query) {
    // A saved filter carries its OWN search text — adopt it before the
    // set_filter_query normalization pass.
    search_text_ =
        normalize_search_text(query.search_text);
    set_filter_query(query);
}

int DataAssetTable::visible_asset_count() const {
    if (in_paged_mode_ && paged_model_ != nullptr) {
        return paged_model_->rowCount();
    }
    return static_cast<int>(visible_assets_.size());
}

const AssetRow* DataAssetTable::asset_at(int view_row) const {
    AssetRowSource* active = active_model();
    return active != nullptr ? active->asset_at(view_row) : nullptr;
}

const AssetView* DataAssetTable::view_at(int view_row) const {
    AssetRowSource* active = active_model();
    return active != nullptr ? active->view_at(view_row) : nullptr;
}

void DataAssetTable::set_selected_asset(const AssetRow* asset) {
    if (asset != nullptr) {
        selected_asset_ = *asset;
        selected_assets_ = {*asset};
    } else {
        selected_asset_.reset();
        selected_assets_.clear();
    }
    sync_selection();
}

// --- columns -----------------------------------------------------------------

void DataAssetTable::build_column_settings_menu() {
    for (const ColumnDef& column : column_definitions()) {
        auto* action = new QAction(
            QString::fromStdString(std::string(column.label)),
            column_settings_menu_);
        action->setCheckable(true);
        action->setChecked(
            std::find(visible_column_keys_.begin(),
                      visible_column_keys_.end(),
                      std::string(column.key)) != visible_column_keys_.end());
        action->setEnabled(!column.required);
        const std::string key = std::string(column.key);
        connect(action, &QAction::toggled, this,
                [this, key](bool checked) {
                    set_column_visible_from_action(key, checked);
                });
        column_settings_menu_->addAction(action);
        column_actions_[key] = action;
    }
    column_settings_menu_->addSeparator();
    reset_columns_action_ =
        column_settings_menu_->addAction(QStringLiteral("恢复默认列"));
    connect(reset_columns_action_, &QAction::triggered, this,
            &DataAssetTable::reset_columns);
    if (visible_column_keys_.empty()) {
        visible_column_keys_ = default_column_keys();
    }
}

void DataAssetTable::set_column_visible_from_action(const std::string& key,
                                                    bool checked) {
    if (syncing_column_actions_) return;
    auto keys = visible_column_keys_;
    if (checked &&
        std::find(keys.begin(), keys.end(), key) == keys.end()) {
        keys.push_back(key);
    } else if (!checked) {
        keys.erase(std::remove(keys.begin(), keys.end(), key), keys.end());
    }
    set_visible_columns(keys);
}

void DataAssetTable::sync_column_actions() {
    syncing_column_actions_ = true;
    const std::set<std::string> visible(visible_column_keys_.begin(),
                                        visible_column_keys_.end());
    for (const auto& [key, action] : column_actions_) {
        action->setChecked(visible.count(key) != 0);
    }
    syncing_column_actions_ = false;
}

void DataAssetTable::set_visible_columns(
    const std::vector<std::string>& keys) {
    visible_column_keys_ = ordered_column_keys(keys);
    // Model column keys are the model's business (set_column_keys); the
    // widget exposes them for the host to forward.
    sync_selection();
    sync_column_actions();
}

void DataAssetTable::reset_columns() {
    visible_column_keys_ = default_column_keys();
    sync_selection();
    sync_column_actions();
}

// --- paged mode ----------------------------------------------------------------

bool DataAssetTable::enter_paged_mode() {
    if (paged_model_ == nullptr) return false;
    in_paged_mode_ = true;
    install_model(paged_model_);
    visible_assets_.clear();
    sync_selection();
    return true;
}

void DataAssetTable::exit_paged_mode() {
    if (!in_paged_mode_) return;
    in_paged_mode_ = false;
    install_model(model_);
    visible_assets_.clear();
    selected_assets_.clear();
    selected_asset_.reset();
}

// --- selection --------------------------------------------------------------

std::optional<std::pair<std::string, std::string>>
DataAssetTable::asset_key(const AssetRow* asset) const {
    if (asset == nullptr) return std::nullopt;
    return ui_pages_data::asset_key(
        asset->kind == AssetKind::Artifact ? RowKind::Artifact
                                           : RowKind::Resource,
        asset->view.id.empty() ? std::string() : asset->view.id);
}

void DataAssetTable::emit_selection() {
    const auto rows = table_->selectionModel()->selectedRows();
    if (rows.isEmpty()) {
        selected_asset_.reset();
        selected_assets_.clear();
        Q_EMIT selected_asset_changed(std::nullopt);
        Q_EMIT selected_assets_changed({});
        return;
    }
    AssetRowSource* active = active_model();
    std::vector<AssetRow> items;
    for (const auto& row : rows) {
        if (const AssetRow* asset =
                active != nullptr ? active->asset_at(row.row()) : nullptr) {
            items.push_back(*asset);
        }
    }
    selected_assets_ = items;
    if (!items.empty()) {
        selected_asset_ = items.front();
    } else {
        selected_asset_.reset();
    }
    Q_EMIT selected_asset_changed(selected_asset_);
    Q_EMIT selected_assets_changed(selected_assets_);
}

void DataAssetTable::on_context_menu(const QPoint& pos) {
    const int view_row = table_->rowAt(pos.y());
    if (view_row < 0) return;
    std::vector<int> selected_rows;
    bool row_selected = false;
    for (const auto& r : table_->selectionModel()->selectedRows()) {
        selected_rows.push_back(r.row());
        if (r.row() == view_row) row_selected = true;
    }
    if (!row_selected) {
        table_->selectRow(view_row);
        selected_rows = {view_row};
    }
    AssetRowSource* active = active_model();
    std::vector<AssetRow> items;
    for (const int r : selected_rows) {
        if (const AssetRow* asset =
                active != nullptr ? active->asset_at(r) : nullptr) {
            items.push_back(*asset);
        }
    }
    if (items.empty()) return;
    Q_EMIT context_menu_requested(table_->viewport()->mapToGlobal(pos),
                                  items);
}

void DataAssetTable::on_model_reset() {
    // Rebuild _visible_assets from the model so a sort (or any reset) can
    // never leave highlight and selection on different rows (#412).
    AssetRowSource* active = active_model();
    if (in_paged_mode_ && active == paged_model_) {
        visible_assets_.clear();
        sync_selection();
        return;
    }
    visible_assets_.clear();
    if (active != nullptr) {
        for (int row = 0; row < active->rowCount(); ++row) {
            if (const AssetRow* asset = active->asset_at(row)) {
                visible_assets_.push_back(*asset);
            }
        }
    }
    sync_selection();
}

void DataAssetTable::on_section_resized(int logical, int /*old_size*/,
                                        int new_size) {
    if (fitting_columns_) return;
    if (logical < 0 ||
        logical >= static_cast<int>(visible_column_keys_.size())) {
        return;
    }
    if (new_size <= 0) return;
    user_resized_columns_.insert(
        visible_column_keys_[static_cast<std::size_t>(logical)]);
}

void DataAssetTable::on_header_clicked(int column) {
    QHeaderView* header = table_->horizontalHeader();
    Qt::SortOrder order;
    if (column == header->sortIndicatorSection() &&
        header->sortIndicatorOrder() == Qt::SortOrder::AscendingOrder) {
        order = Qt::SortOrder::DescendingOrder;
    } else {
        order = Qt::SortOrder::AscendingOrder;
    }
    header->setSortIndicator(column, order);
    header->setSortIndicatorShown(true);
    if (AssetRowSource* active = active_model()) {
        active->sort(column, order);
    }
}

void DataAssetTable::reapply_sort(
    std::optional<std::pair<int, Qt::SortOrder>> pre_build_sort) {
    AssetRowSource* active = active_model();
    const auto last = pre_build_sort.has_value()
                          ? pre_build_sort
                          : (active != nullptr ? active->last_sort()
                                               : std::nullopt);
    if (!last.has_value() || active == nullptr) return;
    const auto [column, order] = *last;
    if (column < 0 || column >= active->columnCount()) return;
    table_->sortByColumn(column, order);
}

void DataAssetTable::emit_selection_changes(
    const std::optional<AssetRow>& prev_primary,
    const std::vector<AssetRow>& prev_multi) {
    const bool primary_changed =
        (prev_primary.has_value() != selected_asset_.has_value()) ||
        (prev_primary.has_value() && selected_asset_.has_value() &&
         asset_key(&*prev_primary) != asset_key(&*selected_asset_));
    const auto keys_of = [this](const std::vector<AssetRow>& v) {
        std::vector<std::optional<std::pair<std::string, std::string>>> out;
        for (const auto& a : v) out.push_back(asset_key(&a));
        return out;
    };
    const bool multi_changed =
        keys_of(prev_multi) != keys_of(selected_assets_);
    if (primary_changed) Q_EMIT selected_asset_changed(selected_asset_);
    if (multi_changed) Q_EMIT selected_assets_changed(selected_assets_);
}

bool DataAssetTable::sync_selection() {
    std::map<std::pair<std::string, std::string>, AssetRow> wanted;
    if (const auto key = asset_key(
            selected_asset_.has_value() ? &*selected_asset_ : nullptr)) {
        wanted[*key] = *selected_asset_;
    }
    for (const auto& a : selected_assets_) {
        if (const auto key = asset_key(&a)) wanted[*key] = a;
    }

    auto* selection_model = table_->selectionModel();
    selection_model->blockSignals(true);
    table_->clearSelection();
    std::vector<AssetRow> restored;
    if (in_paged_mode_ && paged_model_ != nullptr) {
        for (const auto& [key, asset] : wanted) {
            const int row = paged_model_->row_for_key(key);
            if (row >= 0 && row < paged_model_->rowCount()) {
                table_->selectRow(row);
                restored.push_back(asset);
            }
        }
    } else {
        for (std::size_t row = 0; row < visible_assets_.size(); ++row) {
            if (const auto key = asset_key(&visible_assets_[row]);
                key && wanted.count(*key)) {
                table_->selectRow(static_cast<int>(row));
                restored.push_back(visible_assets_[row]);
            }
        }
    }
    selection_model->blockSignals(false);
    selected_assets_ = restored;
    if (!restored.empty()) {
        selected_asset_ = restored.front();
    } else {
        selected_asset_.reset();
    }
    return !restored.empty();
}

}  // namespace pwb::ui_pages_data::qt
