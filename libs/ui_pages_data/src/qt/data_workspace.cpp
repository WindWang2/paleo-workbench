// UI-06 — DataWorkspace shell (see qt/data_workspace.hpp).
#include <pwb/ui_pages_data/qt/data_workspace.hpp>

#include <QEvent>
#include <QHBoxLayout>
#include <QSizePolicy>
#include <QTimer>
#include <QVBoxLayout>

#include <pwb/ui_pages_data/qt/asset_selection_bus.hpp>
#include <pwb/ui_pages_data/qt/data_asset_table.hpp>
#include <pwb/ui_pages_data/qt/data_reader_panel.hpp>
#include <pwb/ui_pages_data/qt/navigation_tree_widget.hpp>
#include <pwb/ui_pages_data/qt/project_overview_panel.hpp>

namespace pwb::ui_pages_data::qt {

// --- PanelFloatButton ---------------------------------------------------------

PanelFloatButton::PanelFloatButton(const QString& key, QWidget* panel,
                                   FloatControllerApi* controller,
                                   bool pin, QWidget* parent)
    : QToolButton(pin ? panel : parent),
      key_(key),
      panel_(panel),
      controller_(controller),
      pinned_(pin) {
    setObjectName(QStringLiteral("PanelFloatButton"));
    setText(QStringLiteral("⇱"));
    setToolTip(QStringLiteral("浮动面板 (Float panel)"));
    setFixedSize(18, 18);
    connect(this, &QToolButton::clicked, this, [this] {
        if (controller_ != nullptr) controller_->toggle(key_);
    });
    if (pinned_) panel_->installEventFilter(this);
    if (controller_ != nullptr) {
        connect(controller_, &FloatControllerApi::float_changed, this,
                [this](const QString& key, bool floating) {
                    if (key == key_) setVisible(!floating);
                });
    }
    if (pinned_) reposition();
}

void PanelFloatButton::reposition() {
    move(panel_->width() - width() - 4, 2);
}

bool PanelFloatButton::eventFilter(QObject* obj, QEvent* event) {
    if (obj == panel_ && event->type() == QEvent::Type::Resize) {
        reposition();
    }
    return false;
}

// --- DataWorkspace ------------------------------------------------------------

DataWorkspace::DataWorkspace(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("DataWorkspace"));
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);

    main_splitter_ = new QSplitter(Qt::Orientation::Horizontal, this);
    main_splitter_->setObjectName(QStringLiteral("DataMainSplitter"));
    main_splitter_->setChildrenCollapsible(false);

    navigation_tree_ = new NavigationTree(this);
    asset_table_ = new DataAssetTable(this);

    center_stack_ = new QStackedWidget(this);
    center_stack_->setObjectName(QStringLiteral("DataCenterStack"));
    overview_panel_ = new ProjectOverviewPanel(this);
    well_detail_panel_ = new QWidget(this);  // seam placeholder
    center_stack_->addWidget(asset_table_);      // index 0 = table
    center_stack_->addWidget(overview_panel_);   // index 1 = overview
    center_stack_->addWidget(well_detail_panel_);// index 2 = well view

    // 原型 ws0 右列 = 数据属性（上）+ 数据血缘/处理流程（下）；两个都是
    // seam 槽位 —— V14 装配注入 DataDetailPanel / DataLineagePanel。
    right_splitter_ = new QSplitter(Qt::Orientation::Vertical, this);
    right_splitter_->setChildrenCollapsible(false);
    inspector_panel_ = new QWidget(this);  // 数据属性 seam placeholder
    lineage_panel_ = new QWidget(this);    // 数据血缘 seam placeholder
    right_splitter_->addWidget(inspector_panel_);
    right_splitter_->addWidget(lineage_panel_);
    right_splitter_->setStretchFactor(0, 3);
    right_splitter_->setStretchFactor(1, 2);
    right_splitter_->setSizes({260, 140});

    main_splitter_->addWidget(navigation_tree_);
    auto* center_container = new QWidget(this);
    map_center_host_ = center_container;
    center_layout_ = new QVBoxLayout(center_container);
    center_layout_->setContentsMargins(0, 0, 0, 0);
    // 原型 ws0 中央 = 数据列表 + 表格下页签（数据预览|版本历史|关联关系）。
    // 预览是真实 DataReaderPanel；版本/血缘页由 V14 装配提入。
    center_vsplit_ = new QSplitter(Qt::Orientation::Vertical,
                                   center_container);
    center_vsplit_->setObjectName(QStringLiteral("DataCenterSplit"));
    center_vsplit_->setChildrenCollapsible(false);
    center_vsplit_->addWidget(center_stack_);
    bottom_tabs_ = new QTabWidget(center_vsplit_);
    bottom_tabs_->setObjectName(QStringLiteral("DataBottomTabs"));
    reader_panel_ = new DataReaderPanel(bottom_tabs_);
    bottom_tabs_->addTab(reader_panel_, QStringLiteral("数据预览"));
    center_vsplit_->addWidget(bottom_tabs_);
    center_vsplit_->setStretchFactor(0, 11);
    center_vsplit_->setStretchFactor(1, 9);
    center_layout_->addWidget(center_vsplit_, 1);
    well_map_panel_ = nullptr;  // injected via set_well_map_panel
    main_splitter_->addWidget(center_container);
    main_splitter_->addWidget(right_splitter_);
    for (QWidget* side :
         {static_cast<QWidget*>(navigation_tree_), center_container,
          static_cast<QWidget*>(right_splitter_)}) {
        side->setSizePolicy(QSizePolicy::Policy::Expanding,
                            QSizePolicy::Policy::Expanding);
    }
    main_splitter_->setStretchFactor(0, 0);
    main_splitter_->setStretchFactor(1, 3);
    main_splitter_->setStretchFactor(2, 1);

    layout->addWidget(main_splitter_);

    float_sizes_timer_ = new QTimer(this);
    float_sizes_timer_->setSingleShot(true);
    float_sizes_timer_->setInterval(kDockedSizesDelayMs);
    connect(float_sizes_timer_, &QTimer::timeout, this,
            &DataWorkspace::persist_docked_sizes);
    connect(main_splitter_, &QSplitter::splitterMoved, this,
            [this](int, int) { float_sizes_timer_->start(); });
    connect(right_splitter_, &QSplitter::splitterMoved, this,
            [this](int, int) { float_sizes_timer_->start(); });
}

void DataWorkspace::showEvent(QShowEvent* event) {
    QWidget::showEvent(event);
    // 原型 ws0：数据列表约占中央高度 55%，表格下页签（数据预览|
    // 版本历史|关联关系）占余下 —— 首次可见时按真实高度播种一次；
    // 用户拖动后 persist_docked_sizes 接管，种子不再干预。
    if (vsplit_seeded_ || center_vsplit_ == nullptr) return;
    const int total = center_vsplit_->height();
    if (total <= 200) return;
    vsplit_seeded_ = true;
    const int top = total * 55 / 100;
    center_vsplit_->setSizes({top, total - top});
}

void DataWorkspace::set_float_controller(FloatControllerApi* controller) {
    float_controller_ = controller;
    if (float_controller_ == nullptr) return;
    make_floatable(QStringLiteral("data:navigation"), navigation_tree_,
                   QStringLiteral("数据导航树"));
    make_floatable(QStringLiteral("data:reader"), reader_panel_,
                   QStringLiteral("数据预览"));
    make_floatable(QStringLiteral("data:inspector"), inspector_panel_,
                   QStringLiteral("数据资产检查器"));
    if (well_map_panel_ != nullptr) {
        make_floatable(QStringLiteral("data:well_map"), well_map_panel_,
                       QStringLiteral("井位地图"));
        well_map_panel_->add_header_button(new PanelFloatButton(
            QStringLiteral("data:well_map"), well_map_panel_,
            float_controller_, /*pin=*/false));
    }
    connect(float_controller_, &FloatControllerApi::float_changed, this,
            &DataWorkspace::on_map_float_changed);
    for (const auto& [key, panel] : floatable_) {
        float_controller_->restore_saved(key);
    }
}

void DataWorkspace::set_save_docked_sizes_fn(
    std::function<void(const QString&, const QList<int>&)> fn) {
    save_docked_sizes_fn_ = std::move(fn);
}

void DataWorkspace::set_well_map_panel(WellMapPanelApi* panel) {
    if (well_map_panel_ != nullptr) {
        center_layout_->removeWidget(well_map_panel_);
    }
    well_map_panel_ = panel;
    if (well_map_panel_ != nullptr) {
        center_layout_->addWidget(well_map_panel_, 0);
    }
}

void DataWorkspace::set_inspector_panel(QWidget* panel) {
    if (panel == nullptr || panel == inspector_panel_) return;
    const int index = right_splitter_->indexOf(inspector_panel_);
    auto* old = inspector_panel_;
    inspector_panel_ = panel;
    // #1389: keep the floatable registry pointed at the LIVE panel — the
    // old one is deleteLater'd and a stale entry would dangle when the
    // docked-sizes debounce timer fires.
    auto fit = floatable_.find(QStringLiteral("data:inspector"));
    if (fit != floatable_.end()) {
        fit->second = panel;
    }
    if (index >= 0) {
        right_splitter_->insertWidget(index, panel);
        old->hide();
        old->deleteLater();
    }
}

void DataWorkspace::set_lineage_panel(QWidget* panel) {
    if (panel == nullptr || panel == lineage_panel_) return;
    const int index = right_splitter_->indexOf(lineage_panel_);
    auto* old = lineage_panel_;
    lineage_panel_ = panel;
    if (index >= 0) {
        right_splitter_->insertWidget(index, panel);
        old->hide();
        old->deleteLater();
    }
}

void DataWorkspace::set_well_detail_panel(QWidget* panel) {
    if (panel == nullptr || panel == well_detail_panel_) return;
    const int index = center_stack_->indexOf(well_detail_panel_);
    auto* old = well_detail_panel_;
    well_detail_panel_ = panel;
    if (index >= 0) {
        center_stack_->insertWidget(index, panel);
        center_stack_->removeWidget(old);
        old->deleteLater();
    }
}

void DataWorkspace::bind_selection_bus(AssetSelectionBus* bus) {
    if (selection_bus_ != nullptr) {
        disconnect(selection_bus_, nullptr, this, nullptr);
        // The table->bus lambda's receiver context is the bus itself —
        // drop it explicitly or an unbound table keeps feeding an orphan.
        disconnect(asset_table_, nullptr, selection_bus_, nullptr);
    }
    selection_bus_ = bus;
    if (selection_bus_ == nullptr) return;
    // Table → bus (the user's real selection is the state). The loop
    // bus→table→bus terminates on the bus's unchanged-selection check.
    connect(asset_table_, &DataAssetTable::selected_asset_changed,
            selection_bus_, [this](const std::optional<AssetRow>& asset) {
                if (syncing_selection_bus_) return;
                selection_bus_->set_current_asset(asset);
            });
    // Bus → table (external selection, row deletion, project switch).
    connect(selection_bus_,
            &AssetSelectionBus::current_asset_changed, this,
            [this](const std::optional<AssetRow>& asset) {
                syncing_selection_bus_ = true;
                asset_table_->set_selected_asset(asset.has_value()
                                                     ? &*asset
                                                     : nullptr);
                syncing_selection_bus_ = false;
            });
    connect(selection_bus_, &AssetSelectionBus::assets_changed, this,
            [this](const std::vector<AssetRow>& rows, const QString&) {
                syncing_selection_bus_ = true;
                asset_table_->update_assets(rows);
                syncing_selection_bus_ = false;
            });
}

void DataWorkspace::make_floatable(const QString& key, QWidget* panel,
                                   const QString& /*title*/) {
    floatable_[key] = panel;
    new PanelFloatButton(key, panel, float_controller_);
}

void DataWorkspace::on_map_float_changed(const QString& key,
                                         bool floating) {
    if (key != QLatin1String("data:well_map") ||
        well_map_panel_ == nullptr) {
        return;
    }
    if (floating) {
        map_collapsed_before_float_ = well_map_panel_->is_collapsed();
        well_map_panel_->set_collapsed(false);
        return;
    }
    const bool lost_from_fold =
        well_map_panel_->parentWidget() != map_center_host_ ||
        center_layout_->indexOf(well_map_panel_) == -1;
    if (lost_from_fold) {
        center_layout_->addWidget(well_map_panel_, 0);
    }
    well_map_panel_->set_collapsed(map_collapsed_before_float_);
}

void DataWorkspace::persist_docked_sizes() {
    if (!save_docked_sizes_fn_) return;
    for (const auto& [key, panel] : floatable_) {
        if (panel == nullptr) continue;  // destroyed between events (#1389)
        if (auto* splitter =
                qobject_cast<QSplitter*>(panel->parentWidget())) {
            save_docked_sizes_fn_(key, splitter->sizes());
        }
    }
}

void DataWorkspace::show_overview(bool visible) {
    const bool map_afloat =
        float_controller_ != nullptr &&
        float_controller_->is_floating(QStringLiteral("data:well_map"));
    center_stack_->setCurrentIndex(visible ? 1 : 0);
    if (well_map_panel_ == nullptr) return;
    if (visible) {
        map_collapsed_before_overview_ = well_map_panel_->is_collapsed();
        if (map_afloat) return;
        overview_panel_->set_map_widget(well_map_panel_);
        well_map_panel_->set_header_visible(false);
        well_map_panel_->set_collapsed(false);
    } else {
        if (map_afloat) return;
        center_layout_->addWidget(well_map_panel_, 0);
        well_map_panel_->set_header_visible(true);
        well_map_panel_->set_collapsed(map_collapsed_before_overview_);
    }
}

bool DataWorkspace::overview_visible() const {
    return center_stack_->currentIndex() == 1;
}

void DataWorkspace::show_well_detail(bool visible) {
    if (visible) {
        center_stack_->setCurrentIndex(2);
    } else if (center_stack_->currentIndex() == 2) {
        center_stack_->setCurrentIndex(0);
    }
}

bool DataWorkspace::well_detail_visible() const {
    return center_stack_->currentIndex() == 2;
}

void DataWorkspace::set_right_visible(bool visible) {
    right_splitter_->setVisible(visible);
}

}  // namespace pwb::ui_pages_data::qt
