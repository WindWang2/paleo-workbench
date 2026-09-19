#include <pwb/ui_seqviz/qt/correlation_page.hpp>

#include <QButtonGroup>
#include <QCheckBox>
#include <QCloseEvent>
#include <QComboBox>
#include <QDialogButtonBox>
#include <QFileDialog>
#include <QFormLayout>
#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QListWidget>
#include <QListWidgetItem>
#include <QMessageBox>
#include <QPushButton>
#include <QScrollArea>
#include <QSizePolicy>
#include <QSlider>
#include <QSpinBox>
#include <QSplitter>
#include <QStackedLayout>
#include <QTimer>
#include <QVBoxLayout>

#include <filesystem>
#include <mutex>
#include <typeinfo>

#include <pwb/job_runtime/job_scheduler.hpp>
#include <pwb/ui_seqviz/page_tokens.hpp>
#include <pwb/ui_seqviz/qt/panel_float_button.hpp>
#include <pwb/ui_shell/dock_manager.hpp>
#include <pwb/ui_shell/float_controller.hpp>
#include <pwb/ui_shell/layout_persistence.hpp>

namespace pwb::ui_seqviz::qt {

namespace {

constexpr int kDockedSizesDelayMs = 400;

// make_correlation_load_job_spec max_wells (Python load_section parity).
constexpr int kMaxWells = 8;

}  // namespace

StratigraphyCorrelationPage::StratigraphyCorrelationPage(
    QWidget* parent, ui_shell::LayoutPersistence* persistence)
    : QWidget(parent), persistence_(persistence) {
    setObjectName("StratigraphyCorrelationPage");

    load_job_ = new job::qtbridge::JobOwner(this);
    connect(load_job_, &job::qtbridge::JobOwner::released, this, [this] {
        load_btn_->setEnabled(true);
    });
    dtw_job_ = new job::qtbridge::JobOwner(this);
    connect(dtw_job_, &job::qtbridge::JobOwner::released, this,
            [this] { sync_backend_stack(); });

    auto* outer = new QVBoxLayout(this);
    const int margin = tokens::PAGE_MARGIN;
    outer->setContentsMargins(margin, margin, margin, margin);
    outer->setSpacing(tokens::SPACE_4);

    splitter_ = new QSplitter(Qt::Horizontal, this);
    splitter_->setObjectName("StratigraphyCorrelationSplitter");
    splitter_->setChildrenCollapsible(false);

    // -- Left: well picker -------------------------------------------------
    well_panel_ = new QFrame(this);
    well_panel_->setObjectName("StratWellPanel");
    well_panel_->setMinimumWidth(200);
    auto* left = new QVBoxLayout(well_panel_);
    const int pad = tokens::PANEL_PADDING;
    left->setContentsMargins(pad, pad, pad, pad);
    left->setSpacing(tokens::SPACE_2);
    auto* title = new QLabel("对比井选择", well_panel_);
    title->setObjectName("MapDockTitle");
    left->addWidget(title);
    horizon_value_ = new QLabel("目标层位: —", well_panel_);
    horizon_value_->setObjectName("WorkFieldValue");
    left->addWidget(horizon_value_);
    well_list_ = new QListWidget(well_panel_);
    well_list_->setObjectName("WorkListWidget");
    left->addWidget(well_list_, 1);
    load_btn_ = new QPushButton("加载连井剖面", well_panel_);
    load_btn_->setObjectName("PrimaryButton");
    connect(load_btn_, &QPushButton::clicked, this,
            &StratigraphyCorrelationPage::load_section);
    left->addWidget(load_btn_);
    auto* select_bound_btn =
        new QPushButton("选用预测绑定井", well_panel_);
    select_bound_btn->setObjectName("SecondaryButton");
    connect(select_bound_btn, &QPushButton::clicked, this,
            &StratigraphyCorrelationPage::select_bound_wells);
    left->addWidget(select_bound_btn);
    splitter_->addWidget(well_panel_);

    // -- Center: CrossWell host -------------------------------------------
    auto* center = new QFrame(this);
    center->setObjectName("StratCrossHost");
    auto* center_layout = new QVBoxLayout(center);
    center_layout->setContentsMargins(pad, pad, pad, pad);
    section_title_ = new QLabel("连井地层对比", center);
    section_title_->setObjectName("MapDockTitle");
    center_layout->addWidget(section_title_);

    auto* backend_row = new QHBoxLayout();
    backend_row->setSpacing(tokens::SPACE_2);
    status_label_ = new QLabel(
        "从左侧选择井后加载剖面（复用 CrossWell / DTW 引擎）", center);
    status_label_->setObjectName("WorkFieldLabel");
    status_label_->setWordWrap(true);
    backend_row->addWidget(status_label_, 1);
    backend_combo_ = new QComboBox(center);
    backend_combo_->setObjectName("StratBackendCombo");
    backend_combo_->addItem("Legacy (CrossWell)", "legacy");
    backend_combo_->addItem("WellLogEngine", "engine");
    backend_combo_->setCurrentIndex(backend_combo_index(backend_));
    connect(backend_combo_, &QComboBox::currentIndexChanged, this,
            &StratigraphyCorrelationPage::on_backend_combo);
    backend_row->addWidget(backend_combo_, 0);
    center_layout->addLayout(backend_row);

    auto* toolbar = new QHBoxLayout();
    toolbar->setSpacing(tokens::SPACE_2);
    mode_group_ = new QButtonGroup(this);
    mode_group_->setExclusive(true);
    browse_btn_ = new QPushButton("浏览", center);
    pick_btn_ = new QPushButton("拾取", center);
    link_btn_ = new QPushButton("连线", center);
    for (auto* btn : {browse_btn_, pick_btn_, link_btn_}) {
        btn->setObjectName("SecondaryButton");
        btn->setCheckable(true);
        mode_group_->addButton(btn);
        connect(btn, &QPushButton::toggled, this,
                [this](bool) { on_mode_changed(); });
        toolbar->addWidget(btn);
    }
    browse_btn_->setChecked(true);

    formation_combo_ = new QComboBox(center);
    formation_combo_->setEditable(true);
    formation_combo_->setPlaceholderText("拾取层位");
    formation_combo_->setMinimumWidth(110);
    connect(formation_combo_, &QComboBox::currentTextChanged, this,
            &StratigraphyCorrelationPage::on_formation_changed);
    toolbar->addWidget(formation_combo_);

    snap_combo_ = new QComboBox(center);
    snap_combo_->addItem("不吸附", "none");
    snap_combo_->addItem("波峰", "max");
    snap_combo_->addItem("波谷", "min");
    connect(snap_combo_, &QComboBox::currentIndexChanged, this,
            [this](int) { on_snap_changed(); });
    toolbar->addWidget(snap_combo_);

    dtw_btn_ = new QPushButton("DTW 传播", center);
    dtw_btn_->setObjectName("SecondaryButton");
    connect(dtw_btn_, &QPushButton::clicked, this,
            &StratigraphyCorrelationPage::run_dtw);
    toolbar->addWidget(dtw_btn_);
    undo_btn_ = new QPushButton("撤销", center);
    undo_btn_->setObjectName("SecondaryButton");
    connect(undo_btn_, &QPushButton::clicked, this,
            &StratigraphyCorrelationPage::undo_pick);
    toolbar->addWidget(undo_btn_);
    redo_btn_ = new QPushButton("重做", center);
    redo_btn_->setObjectName("SecondaryButton");
    connect(redo_btn_, &QPushButton::clicked, this,
            &StratigraphyCorrelationPage::redo_pick);
    toolbar->addWidget(redo_btn_);
    auto_link_btn_ = new QPushButton("自动连线", center);
    auto_link_btn_->setObjectName("SecondaryButton");
    connect(auto_link_btn_, &QPushButton::clicked, this,
            &StratigraphyCorrelationPage::run_auto_link);
    toolbar->addWidget(auto_link_btn_);

    tops_visible_box_ = new QCheckBox("分层顶线", center);
    tops_visible_box_->setChecked(true);
    connect(tops_visible_box_, &QCheckBox::toggled, this,
            &StratigraphyCorrelationPage::on_tops_visible);
    toolbar->addWidget(tops_visible_box_);

    toolbar->addWidget(new QLabel("间距", center));
    spacing_slider_ = new QSlider(Qt::Horizontal, center);
    spacing_slider_->setRange(50, 300);
    spacing_slider_->setValue(150);
    spacing_slider_->setFixedWidth(90);
    connect(spacing_slider_, &QSlider::valueChanged, this,
            &StratigraphyCorrelationPage::on_spacing_changed);
    toolbar->addWidget(spacing_slider_);
    toolbar->addStretch();
    center_layout->addLayout(toolbar);

    auto* view_stack_host = new QFrame(center);
    view_stack_host->setObjectName("StratViewStack");
    view_stack_ = new QStackedLayout(view_stack_host);
    view_stack_->setContentsMargins(0, 0, 0, 0);

    auto* scroll_area = new QScrollArea(view_stack_host);
    scroll_area->setObjectName("StratCrossScrollArea");
    scroll_area->setWidgetResizable(true);
    scroll_area->setFrameShape(QFrame::NoFrame);
    scroll_area->setSizePolicy(QSizePolicy::Expanding,
                               QSizePolicy::Expanding);
    scroll_area->setHorizontalScrollBarPolicy(Qt::ScrollBarAsNeeded);
    scroll_area->setVerticalScrollBarPolicy(Qt::ScrollBarAsNeeded);
    // The injected canvas widget lands here via set_canvas().
    scroll_area->setObjectName("StratCrossScrollAreaHost");
    view_stack_->addWidget(scroll_area);  // 0 legacy

    auto* engine_host = new QFrame(view_stack_host);
    engine_host->setObjectName("StratEngineHost");
    auto* engine_layout = new QVBoxLayout(engine_host);
    engine_layout->setContentsMargins(0, 0, 0, 0);
    engine_placeholder_ = new QLabel(
        "WellLogEngine 多井路径未启用或不可用。\n"
        "WellLogEngine 默认启用；安装带 multi-well 的 welllog 绑定，"
        "或设 PALEO_USE_WELLLOG_ENGINE=0 使用 Legacy。",
        engine_host);
    engine_placeholder_->setObjectName("EmptyStateLabel");
    engine_placeholder_->setAlignment(Qt::AlignCenter);
    engine_placeholder_->setWordWrap(true);
    engine_layout->addWidget(engine_placeholder_);
    view_stack_->addWidget(engine_host);  // 1 engine
    engine_view_parent_ = engine_host;

    center_layout->addWidget(view_stack_host, 1);
    splitter_->addWidget(center);
    // Keep the scroll area reachable for set_canvas.
    legacy_scroll_ = scroll_area;

    // -- Right: actions ----------------------------------------------------
    action_panel_ = new QFrame(this);
    action_panel_->setObjectName("StratActionPanel");
    action_panel_->setMinimumWidth(200);
    auto* right = new QVBoxLayout(action_panel_);
    right->setContentsMargins(pad, pad, pad, pad);
    right->setSpacing(tokens::SPACE_2);
    auto* a_title = new QLabel("对比操作", action_panel_);
    a_title->setObjectName("MapDockTitle");
    right->addWidget(a_title);
    loaded_value_ = new QLabel("已加载: 0 口井", action_panel_);
    loaded_value_->setObjectName("WorkFieldValue");
    right->addWidget(loaded_value_);
    tops_value_ = new QLabel("相/顶: —", action_panel_);
    tops_value_->setObjectName("WorkFieldValue");
    tops_value_->setWordWrap(true);
    right->addWidget(tops_value_);
    auto* track_title = new QLabel("轨道显隐", action_panel_);
    track_title->setObjectName("MapDockTitle");
    right->addWidget(track_title);
    track_list_ = new QListWidget(action_panel_);
    track_list_->setObjectName("WorkListWidget");
    connect(track_list_, &QListWidget::itemChanged, this,
            &StratigraphyCorrelationPage::on_track_item_changed);
    right->addWidget(track_list_);
    right->addStretch();
    auto* export_btn = new QPushButton("导出连井剖面", action_panel_);
    export_btn->setObjectName("PrimaryButton");
    connect(export_btn, &QPushButton::clicked, this,
            &StratigraphyCorrelationPage::export_section);
    right->addWidget(export_btn);
    auto* export_tops_btn =
        new QPushButton("导出分层顶 CSV", action_panel_);
    export_tops_btn->setObjectName("SecondaryButton");
    connect(export_tops_btn, &QPushButton::clicked, this,
            &StratigraphyCorrelationPage::export_tops);
    right->addWidget(export_tops_btn);
    auto* save_interp_btn =
        new QPushButton("保存解释版本", action_panel_);
    save_interp_btn->setObjectName("PrimaryButton");
    save_interp_btn->setToolTip(
        "将当前分层顶保存为不可变连井对比解释版本");
    connect(save_interp_btn, &QPushButton::clicked, this,
            &StratigraphyCorrelationPage::save_interpretation_version);
    right->addWidget(save_interp_btn);
    auto* open_interp_btn =
        new QPushButton("打开已保存解释", action_panel_);
    open_interp_btn->setObjectName("SecondaryButton");
    connect(open_interp_btn, &QPushButton::clicked, this,
            &StratigraphyCorrelationPage::open_saved_interpretation);
    right->addWidget(open_interp_btn);
    auto* restore_interp_btn =
        new QPushButton("恢复已保存版本", action_panel_);
    restore_interp_btn->setObjectName("SecondaryButton");
    restore_interp_btn->setToolTip(
        "丢弃未保存编辑，重新加载当前已保存版本");
    connect(restore_interp_btn, &QPushButton::clicked, this,
            &StratigraphyCorrelationPage::restore_saved_interpretation);
    right->addWidget(restore_interp_btn);
    auto* link_edit_btn = new QPushButton("链接编辑…", action_panel_);
    link_edit_btn->setObjectName("SecondaryButton");
    link_edit_btn->setToolTip(
        "增删改井间相关链接与顶点属性（写入解释草稿）");
    connect(link_edit_btn, &QPushButton::clicked, this,
            &StratigraphyCorrelationPage::open_link_editor);
    right->addWidget(link_edit_btn);
    interp_status_ = new QLabel("解释: 未保存", action_panel_);
    interp_status_->setObjectName("WorkFieldValue");
    interp_status_->setWordWrap(true);
    right->addWidget(interp_status_);
    auto* clear_btn = new QPushButton("清空剖面", action_panel_);
    clear_btn->setObjectName("SecondaryButton");
    connect(clear_btn, &QPushButton::clicked, this,
            &StratigraphyCorrelationPage::clear_section);
    right->addWidget(clear_btn);
    splitter_->addWidget(action_panel_);

    splitter_->setStretchFactor(0, 0);
    splitter_->setStretchFactor(1, 1);
    splitter_->setStretchFactor(2, 0);
    splitter_->setSizes({260, 940, 260});
    outer->addWidget(splitter_, 1);

    // M6: picker/action panels float; the CrossWell center never does.
    float_controller_ = std::make_unique<ui_shell::FloatController>(
        [this](const std::string& key) -> QWidget* {
            for (const auto& [k, w] : floatable_) {
                if (k == key) {
                    return w;
                }
            }
            return nullptr;
        },
        persistence_, nullptr, this);
    make_floatable("stratigraphy:wells", well_panel_, "对比井选择");
    make_floatable("stratigraphy:actions", action_panel_, "对比操作");

    auto* sizes_timer = new QTimer(this);
    sizes_timer->setSingleShot(true);
    sizes_timer->setInterval(kDockedSizesDelayMs);
    connect(sizes_timer, &QTimer::timeout, this,
            &StratigraphyCorrelationPage::persist_docked_sizes);
    connect(splitter_, &QSplitter::splitterMoved, this,
            [sizes_timer](int, int) { sizes_timer->start(); });
    for (const auto& [key, panel] : floatable_) {
        float_controller_->restore_saved(key, panel);
    }

    probe_engine();
    sync_backend_stack();
}

StratigraphyCorrelationPage::~StratigraphyCorrelationPage() {
    shutdown_workers();
}

// ---------------------------------------------------------------------------
// seam binding
// ---------------------------------------------------------------------------

void StratigraphyCorrelationPage::set_canvas(CorrelationCanvasApi canvas) {
    canvas_ = std::move(canvas);
    if (canvas_.widget != nullptr && legacy_scroll_ != nullptr) {
        legacy_scroll_->setWidget(canvas_.widget);
    }
}

void StratigraphyCorrelationPage::set_engine(CorrelationEngineApi engine) {
    engine_ = std::move(engine);
    probe_engine();
    sync_backend_stack();
}

void StratigraphyCorrelationPage::set_workflow(
    CorrelationWorkflowSeams workflow) {
    workflow_ = std::move(workflow);
}

void StratigraphyCorrelationPage::set_project(
    const std::any& project,
    const ui_workers::CorrelationProjectSlice& project_slice,
    const void* token) {
    // Python `project is not self._project` — a different live handle
    // while a load runs gets the bump+cancel treatment.
    const bool switching = token != nullptr && token != project_token_;
    if (switching && load_job_->is_running()) {
        load_seq_.bump();
        load_job_->cancel();
    }
    project_ = project;
    project_slice_ = project_slice;
    if (token != nullptr) {
        project_token_ = token;
    }
    refresh_interp_status();
}

void StratigraphyCorrelationPage::set_project_path(
    const std::string& path) {
    project_path_ = path;
}

// ---------------------------------------------------------------------------
// backend
// ---------------------------------------------------------------------------

void StratigraphyCorrelationPage::set_backend(const std::string& name) {
    const CorrelationBackend target = normalize_backend(name);
    if (target == backend_) {
        return;
    }
    backend_ = target;
    const int idx = backend_combo_index(target);
    if (backend_combo_->currentIndex() != idx) {
        backend_combo_->blockSignals(true);
        backend_combo_->setCurrentIndex(idx);
        backend_combo_->blockSignals(false);
    }
    sync_backend_stack();
    if (!loaded_logs_.empty()) {
        if (dtw_job_->is_running()) {
            dtw_job_->cancel();
        }
        reload_current_section();
    }
}

void StratigraphyCorrelationPage::on_backend_combo(int index) {
    const QString data = backend_combo_->itemData(index).toString();
    set_backend(data == "engine" ? "engine" : "legacy");
}

void StratigraphyCorrelationPage::probe_engine() {
    engine_error_.clear();
    engine_binding_installed_ = engine_.view_factory != nullptr;
    const EngineProbeResult probe = probe_engine(
        engine_.has_submit_multi_well_section,
        engine_binding_installed_);
    engine_error_ = probe.error;
}

void StratigraphyCorrelationPage::sync_backend_stack() {
    view_stack_->setCurrentIndex(backend_ == CorrelationBackend::Legacy
                                     ? 0
                                     : 1);
    const bool interactive = backend_ == CorrelationBackend::Legacy;
    for (QWidget* w :
         {static_cast<QWidget*>(browse_btn_),
          static_cast<QWidget*>(pick_btn_),
          static_cast<QWidget*>(link_btn_),
          static_cast<QWidget*>(dtw_btn_),
          static_cast<QWidget*>(undo_btn_),
          static_cast<QWidget*>(redo_btn_),
          static_cast<QWidget*>(auto_link_btn_),
          static_cast<QWidget*>(tops_visible_box_),
          static_cast<QWidget*>(spacing_slider_),
          static_cast<QWidget*>(formation_combo_),
          static_cast<QWidget*>(snap_combo_),
          static_cast<QWidget*>(track_list_)}) {
        w->setEnabled(interactive);
    }
}

void StratigraphyCorrelationPage::ensure_engine_view() {
    if (engine_view_ != nullptr || !engine_.view_factory) {
        return;
    }
    QWidget* view = nullptr;
    try {
        view = engine_.view_factory(engine_view_parent_);
    } catch (const std::exception& exc) {
        engine_error_ =
            ui_workers::py_error_class_name(exc) + ": " + exc.what();
        return;
    }
    if (view == nullptr) {
        return;
    }
    engine_view_ = view;
    auto* layout = engine_view_parent_->layout();
    if (layout != nullptr) {
        engine_placeholder_->hide();
        layout->addWidget(view);
    }
}

void StratigraphyCorrelationPage::release_engine_view() {
    if (engine_view_ != nullptr) {
        engine_view_->hide();
        if (engine_.clear_view_section) {
            try {
                engine_.clear_view_section(engine_view_);
            } catch (...) {
            }
        }
        if (engine_.release_view) {
            engine_.release_view(engine_view_);
        }
        if (auto* layout = engine_view_parent_->layout();
            layout != nullptr) {
            layout->removeWidget(engine_view_);
        }
        engine_view_->setParent(nullptr);
        engine_view_->deleteLater();
        engine_view_ = nullptr;
    }
    engine_placeholder_->show();
}

bool StratigraphyCorrelationPage::shutdown_workers(int wait_ms) {
    const bool dtw_joined = dtw_job_->shutdown(wait_ms);
    load_seq_.bump();
    const bool load_joined = load_job_->shutdown(wait_ms);
    if (dtw_joined && load_joined) {
        release_engine_view();
    }
    return dtw_joined && load_joined;
}

// ---------------------------------------------------------------------------
// update_state / well list
// ---------------------------------------------------------------------------

void StratigraphyCorrelationPage::update_state() {
    if (!project_.has_value()) {
        well_list_->clear();
        well_entries_.clear();
        well_list_signature_.clear();
        horizon_value_->setText("目标层位: —");
        return;
    }
    std::optional<std::string> horizon;
    if (workflow_.active_target_horizon) {
        horizon = workflow_.active_target_horizon();
    }
    const CorrelationHeaderView header = correlation_header(horizon);
    horizon_value_->setText(QString::fromStdString(header.horizon_text));
    section_title_->setText(
        QString::fromStdString(header.section_title));
    sync_well_list(project_slice_.resources);
}

void StratigraphyCorrelationPage::sync_well_list(
    const std::vector<ui_workers::ResourceSlice>& resources) {
    const auto sorted = ui_workers::list_well_log_resources(resources);
    const std::vector<WellListEntry> entries =
        well_list_entries(sorted);
    const WellListSignature signature = well_list_signature(entries);
    if (signature == well_list_signature_) {
        return;  // unchanged signature — no item work at all (V6).
    }
    // Keyed diff: items are keyed by resource id and reused — drop
    // removed ids, insert new ids, retitle renamed ids, move to order.
    std::map<std::string, QListWidgetItem*> items;
    for (int i = 0; i < well_list_->count(); ++i) {
        auto* item = well_list_->item(i);
        items[item->data(Qt::UserRole).toString().toStdString()] = item;
    }
    std::set<std::string> wanted;
    for (const auto& entry : entries) {
        wanted.insert(entry.id);
    }
    for (auto it = items.begin(); it != items.end();) {
        if (wanted.count(it->first) == 0U) {
            const int row = well_list_->row(it->second);
            if (row >= 0) {
                delete well_list_->takeItem(row);
            }
            it = items.erase(it);
        } else {
            ++it;
        }
    }
    for (int index = 0;
         index < static_cast<int>(entries.size()); ++index) {
        const auto& entry = entries[static_cast<std::size_t>(index)];
        QListWidgetItem* item = nullptr;
        const auto found = items.find(entry.id);
        if (found == items.end()) {
            item = new QListWidgetItem(
                QString::fromStdString(entry.name));
            item->setData(Qt::UserRole,
                          QString::fromStdString(entry.id));
            item->setFlags(item->flags() |
                           Qt::ItemIsUserCheckable);
            item->setCheckState(Qt::Unchecked);
            items[entry.id] = item;
            well_list_->insertItem(index, item);
            continue;
        }
        item = found->second;
        if (item->text() != QString::fromStdString(entry.name)) {
            item->setText(QString::fromStdString(entry.name));
        }
        const int row = well_list_->row(item);
        if (row != index) {
            well_list_->takeItem(row);
            well_list_->insertItem(index, item);
        }
    }
    well_entries_ = entries;
    well_list_signature_ = signature;
}

std::vector<std::string>
StratigraphyCorrelationPage::selected_resource_ids() const {
    std::vector<std::string> ids;
    for (int i = 0; i < well_list_->count(); ++i) {
        const auto* item = well_list_->item(i);
        if (item->checkState() == Qt::Checked) {
            const QString rid = item->data(Qt::UserRole).toString();
            if (!rid.isEmpty()) {
                ids.push_back(rid.toStdString());
            }
        }
    }
    return ids;
}

void StratigraphyCorrelationPage::select_bound_wells() {
    if (!project_.has_value()) {
        return;
    }
    const std::set<std::string> bound =
        workflow_.bound_well_ids ? workflow_.bound_well_ids()
                                 : std::set<std::string>{};
    std::vector<bool> checks(well_entries_.size(), false);
    if (bound.empty()) {
        for (std::size_t i = 0;
             i < std::min<std::size_t>(4, well_entries_.size()); ++i) {
            checks[i] = true;
        }
    } else {
        checks = bound_well_check_states(well_entries_, bound);
    }
    for (int i = 0; i < well_list_->count(); ++i) {
        const QString rid =
            well_list_->item(i)->data(Qt::UserRole).toString();
        for (std::size_t e = 0; e < well_entries_.size(); ++e) {
            if (well_entries_[e].id == rid.toStdString()) {
                well_list_->item(i)->setCheckState(
                    checks[e] ? Qt::Checked : Qt::Unchecked);
                break;
            }
        }
    }
}

// ---------------------------------------------------------------------------
// canvas interaction wiring (all thin forwards into the injected surface)
// ---------------------------------------------------------------------------

void StratigraphyCorrelationPage::on_mode_changed() {
    if (canvas_.set_pick_mode) {
        canvas_.set_pick_mode(pick_btn_->isChecked());
    }
    if (canvas_.set_manual_link) {
        canvas_.set_manual_link(link_btn_->isChecked());
    }
}

void StratigraphyCorrelationPage::on_formation_changed(
    const QString& text) {
    if (!canvas_.set_active_formation) {
        return;
    }
    const QString trimmed = text.trimmed();
    canvas_.set_active_formation(
        trimmed.isEmpty()
            ? std::nullopt
            : std::optional<std::string>(trimmed.toStdString()));
}

void StratigraphyCorrelationPage::on_snap_changed() {
    if (canvas_.set_snap_type) {
        canvas_.set_snap_type(
            snap_combo_->currentData().toString().toStdString());
    }
}

void StratigraphyCorrelationPage::on_tops_visible(bool checked) {
    if (canvas_.set_tops_visible) {
        canvas_.set_tops_visible(checked);
    }
}

void StratigraphyCorrelationPage::on_spacing_changed(int value) {
    if (canvas_.set_well_spacing) {
        canvas_.set_well_spacing(value);
    }
}

void StratigraphyCorrelationPage::undo_pick() {
    if (canvas_.picks_undo) {
        canvas_.picks_undo();
    }
}

void StratigraphyCorrelationPage::redo_pick() {
    if (canvas_.picks_redo) {
        canvas_.picks_redo();
    }
}

void StratigraphyCorrelationPage::run_auto_link() {
    if (canvas_.auto_link) {
        canvas_.auto_link();
    }
    status_label_->setText("已按同名分层自动连线");
}

// ---------------------------------------------------------------------------
// DTW
// ---------------------------------------------------------------------------

void StratigraphyCorrelationPage::run_dtw() {
    const std::vector<CorrelationPick> picks =
        canvas_.all_picks ? canvas_.all_picks()
                          : std::vector<CorrelationPick>{};
    if (picks.empty()) {
        status_label_->setText(
            "请先在拾取模式下添加一个参考拾取点");
        return;
    }
    const CorrelationPick& ref = picks.back();
    if (ref.connected_wells.empty()) {
        status_label_->setText("参考拾取点没有关联井");
        return;
    }
    if (dtw_job_->is_running()) {
        // Second click while running acts as cooperative cancel.
        dtw_job_->cancel();
        status_label_->setText("正在取消 DTW 传播…");
        return;
    }
    const std::string ref_well = ref.connected_wells.front();
    const auto depth_it = ref.depth_by_well.find(ref_well);
    const double ref_depth =
        depth_it != ref.depth_by_well.end() ? depth_it->second : 0.0;
    const std::string target_well = ref.connected_wells.size() > 1
                                        ? ref.connected_wells[1]
                                        : ref_well;

    dtw_conf_text_ = "置信度: 不可用";
    dtw_confidence_ = 0.0;
    const long long n_samples = max_loaded_curve_samples(
        loaded_logs_, workflow_.curve_length_fn);
    const int band = ui_workers::bounded_dtw_band(
        static_cast<int>(n_samples));

    ui_workers::DtwPropagationInput input;
    if (canvas_.dtw_scene) {
        input.scene = canvas_.dtw_scene();
    }
    input.ref_well = ref_well;
    input.ref_depth = ref_depth;
    input.formation = ref.formation_name;
    input.n_samples = static_cast<int>(n_samples);
    input.band_radius = band;
    dtw_formation_ = ref.formation_name;

    // recommend_fn — the engine recommendation runs at the head of the
    // worker thread; a mailbox carries it to the GUI on delivery.
    auto rec_box = std::make_shared<
        std::pair<std::mutex, std::optional<std::any>>>();
    if (workflow_.recommend_top) {
        auto recommend = workflow_.recommend_top;
        input.recommend_fn = [recommend, ref_well, ref_depth,
                              target_well]() -> std::any {
            return recommend(ref_well, ref_depth, target_well);
        };
        input.on_recommendation = [rec_box](const std::any& rec) {
            const std::lock_guard lock(rec_box->first);
            rec_box->second = rec;
        };
    }

    job::JobSpec spec = ui_workers::make_dtw_propagation_job_spec(
        std::move(input));
    dtw_btn_->setEnabled(false);
    status_label_->setText("DTW 传播中…（再次点击可取消）");
    dtw_job_->start(
        job::global_scheduler(), std::move(spec),
        [this, rec_box](const job::qtbridge::JobOutcome& outcome) {
            // Apply the recommendation before the pairs (the Python
            // recommendation_ready signal lands first on the GUI too).
            {
                const std::lock_guard lock(rec_box->first);
                if (rec_box->second.has_value()) {
                    const auto values =
                        workflow_.recommend_values
                            ? workflow_.recommend_values(
                                  *rec_box->second)
                            : std::pair<double, double>{999.0, 0.0};
                    const DtwConfidence conf = dtw_confidence_from_cost(
                        values.first, values.second);
                    dtw_conf_text_ = conf.text;
                    dtw_confidence_ = conf.value;
                }
            }
            switch (outcome.state) {
            case job::JobState::done:
            case job::JobState::degraded: {
                const auto* result =
                    std::any_cast<ui_workers::DtwPropagationResult>(
                        &outcome.result);
                if (result != nullptr) {
                    on_dtw_finished(*result);
                }
                return;
            }
            case job::JobState::failed:
                on_dtw_failed(outcome.error);
                return;
            case job::JobState::cancelled:
                on_dtw_cancelled();
                return;
            }
        },
        [this](double done, double total) {
            on_dtw_progress(done, total);
        });
}

void StratigraphyCorrelationPage::on_dtw_progress(double done,
                                                  double total) {
    const std::string text = dtw_progress_status(
        static_cast<int>(done), static_cast<int>(total));
    if (!text.empty()) {
        status_label_->setText(QString::fromStdString(text));
    }
}

void StratigraphyCorrelationPage::on_dtw_finished(
    const ui_workers::DtwPropagationResult& result) {
    // Model/undo mutations run on the GUI thread only (#826).
    std::size_t created = 0;
    for (const auto& [well, depth] : result.pairs) {
        if (canvas_.add_pick) {
            canvas_.add_pick(dtw_formation_, well, depth, "dtw");
            ++created;
        }
    }
    status_label_->setText(QString::fromStdString(dtw_finished_status(
        dtw_formation_, created, dtw_conf_text_)));
}

void StratigraphyCorrelationPage::on_dtw_failed(
    const std::string& message) {
    status_label_->setText(
        QString::fromStdString(dtw_failed_status(message)));
}

void StratigraphyCorrelationPage::on_dtw_cancelled() {
    status_label_->setText("DTW 传播已取消");
}

void StratigraphyCorrelationPage::on_track_item_changed(
    QListWidgetItem* item) {
    if (canvas_.set_track_visible && item != nullptr) {
        canvas_.set_track_visible(item->text().toStdString(),
                                  item->checkState() == Qt::Checked);
    }
}

// ---------------------------------------------------------------------------
// tops injection / track list
// ---------------------------------------------------------------------------

std::vector<std::string> StratigraphyCorrelationPage::inject_well_tops(
    const std::vector<std::string>& names,
    const std::optional<TopsByWell>& tops_by_well_opt) {
    if (canvas_.tops_clear) {
        canvas_.tops_clear();
    }
    if (canvas_.picks_clear) {
        canvas_.picks_clear();
    }
    std::vector<std::string> notices;
    if (!project_.has_value()) {
        return notices;
    }
    TopsByWell tops;
    if (tops_by_well_opt.has_value()) {
        tops = *tops_by_well_opt;
    } else if (workflow_.load_well_tops) {
        auto [loaded, warnings] = workflow_.load_well_tops();
        tops = std::move(loaded);
        notices.insert(notices.end(), warnings.begin(), warnings.end());
    }
    TopsMatchResult match;
    if (workflow_.match_tops) {
        match = workflow_.match_tops(tops, names);
    }
    for (const auto& [well, rows] : match.matched) {
        for (const auto& [top_name, depth] : rows) {
            if (canvas_.add_top) {
                canvas_.add_top(well, top_name, depth);
            }
        }
        if (canvas_.set_formation_data && workflow_.tops_to_intervals) {
            canvas_.set_formation_data(
                well, workflow_.tops_to_intervals(rows));
        }
    }
    const auto extra = tops_injection_notices(match);
    notices.insert(notices.end(), extra.begin(), extra.end());

    formation_combo_->clear();
    if (canvas_.formation_names) {
        for (const auto& name : canvas_.formation_names()) {
            formation_combo_->addItem(QString::fromStdString(name));
        }
    }
    return notices;
}

void StratigraphyCorrelationPage::refresh_track_list() {
    track_list_->blockSignals(true);
    track_list_->clear();
    if (canvas_.track_labels) {
        for (const auto& label : canvas_.track_labels()) {
            auto* item = new QListWidgetItem(
                QString::fromStdString(label));
            item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
            item->setCheckState(Qt::Checked);
            track_list_->addItem(item);
        }
    }
    track_list_->blockSignals(false);
}

// ---------------------------------------------------------------------------
// load_section
// ---------------------------------------------------------------------------

void StratigraphyCorrelationPage::load_section() {
    const bool project_bound = project_.has_value();
    const std::vector<std::string> checked = selected_resource_ids();
    LoadSectionDecision decision = plan_load_section(
        project_bound, load_job_->is_running(), checked,
        well_list_->count());
    switch (decision.plan) {
    case LoadSectionPlan::NoProject:
        emit warning_requested("地层对比", "未绑定工程");
        return;
    case LoadSectionPlan::AlreadyRunning:
        return;
    case LoadSectionPlan::NoResources:
        emit info_requested("地层对比", "工程中没有测井 LAS 资源");
        return;
    case LoadSectionPlan::Load:
        break;
    }
    std::vector<std::string> ids = decision.ids;
    if (ids.empty()) {
        // Auto-select up to 4 wells if none checked, then re-read.
        for (int i = 0;
             i < std::min(4, well_list_->count()); ++i) {
            well_list_->item(i)->setCheckState(Qt::Checked);
        }
        ids = selected_resource_ids();
        if (ids.empty()) {
            emit info_requested("地层对比",
                                "工程中没有测井 LAS 资源");
            return;
        }
    }
    if (dtw_job_->is_running()) {
        dtw_job_->cancel();
    }

    const long long seq = load_seq_.bump();
    load_seq_.arm(seq);

    ui_workers::CorrelationLoadInput input;
    input.project = project_slice_;
    input.resource_ids = ids;
    input.max_wells = kMaxWells;
    input.seams = workflow_.correlation;
    if (workflow_.loader_fn) {
        input.loader_fn = workflow_.loader_fn;
    }

    job::JobSpec spec = ui_workers::make_correlation_load_job_spec(
        std::move(input));
    load_btn_->setEnabled(false);
    status_label_->setText("正在加载连井剖面…");
    load_job_->start(
        job::global_scheduler(), std::move(spec),
        [this](const job::qtbridge::JobOutcome& outcome) {
            switch (outcome.state) {
            case job::JobState::done:
            case job::JobState::degraded: {
                const auto* result =
                    std::any_cast<ui_workers::CorrelationLoadResult>(
                        &outcome.result);
                if (result != nullptr) {
                    on_load_finished(*result);
                }
                return;
            }
            case job::JobState::failed:
                on_load_failed(outcome.error);
                return;
            case job::JobState::cancelled:
                on_load_cancelled();
                return;
            }
        });
}

void StratigraphyCorrelationPage::on_load_finished(
    const ui_workers::CorrelationLoadResult& result) {
    if (load_seq_.stale()) {
        return;
    }
    const CorrelationLoadView view = correlation_load_view(
        result, workflow_.curve_count_fn, /*path_msg=*/"",
        /*top_notices=*/{}, engine_error_,
        backend_ == CorrelationBackend::Engine);
    if (result.logs.empty()) {
        status_label_->setText(
            QString::fromStdString(view.empty_status));
        load_btn_->setEnabled(true);
        return;
    }
    loaded_logs_ = view.logs;
    loaded_names_ = view.names;
    loaded_ids_ = view.loaded_ids;
    bind_engine_wells();
    const auto [ok, top_notices, path_msg] = apply_loaded_section();
    const CorrelationLoadView final_view = correlation_load_view(
        result, workflow_.curve_count_fn, path_msg, top_notices,
        engine_error_, backend_ == CorrelationBackend::Engine);
    loaded_value_->setText(
        QString::fromStdString(final_view.loaded_value));
    tops_value_->setText(QString::fromStdString(final_view.tops_value));
    status_label_->setText(QString::fromStdString(
        ok ? final_view.status : std::string("加载失败")));
    emit section_updated();
}

void StratigraphyCorrelationPage::on_load_failed(
    const std::string& message) {
    if (load_seq_.stale()) {
        return;
    }
    status_label_->setText(
        QString::fromStdString("加载失败: " + message));
}

void StratigraphyCorrelationPage::on_load_cancelled() {
    if (status_label_->text().contains("正在加载")) {
        status_label_->setText("加载已取消");
    }
}

// ---------------------------------------------------------------------------
// section application (backend dispatch)
// ---------------------------------------------------------------------------

void StratigraphyCorrelationPage::bind_engine_wells() {
    if (workflow_.bind_wells) {
        workflow_.bind_wells(loaded_logs_, loaded_names_);
    }
}

void StratigraphyCorrelationPage::reload_current_section() {
    if (loaded_logs_.empty()) {
        sync_backend_stack();
        return;
    }
    const auto [ok, notices, path_msg] = apply_loaded_section();
    status_label_->setText(QString::fromStdString(
        ok ? "已切换到 " + path_msg
           : "切换失败: " +
                 (engine_error_.empty() ? path_msg : engine_error_)));
}

std::tuple<bool, std::vector<std::string>, std::string>
StratigraphyCorrelationPage::apply_loaded_section() {
    std::vector<std::string> top_notices;
    if (backend_ == CorrelationBackend::Engine) {
        const bool ok = apply_engine_section(
            loaded_logs_, loaded_names_, loaded_ids_);
        return {ok, top_notices, "WellLogEngine"};
    }
    UiVizPayload payload;
    payload.kind = "cross_well";
    payload.label = "地层对比";
    payload.well_logs = loaded_logs_;
    payload.well_names = loaded_names_;
    const bool ok = canvas_.apply && canvas_.apply(payload);
    std::optional<TopsByWell> shared_tops;
    if (ok) {
        if (project_.has_value() && workflow_.load_well_tops) {
            auto [tops, warnings] = workflow_.load_well_tops();
            shared_tops = std::move(tops);
            top_notices.insert(top_notices.end(), warnings.begin(),
                               warnings.end());
        }
        const auto injected =
            inject_well_tops(loaded_names_, shared_tops);
        top_notices.insert(top_notices.end(), injected.begin(),
                           injected.end());
        refresh_track_list();
        if (canvas_.set_well_spacing) {
            canvas_.set_well_spacing(spacing_slider_->value());
        }
    }
    // Always build the engine plan for parity even on Legacy.
    build_engine_plan_only(loaded_logs_, loaded_names_, loaded_ids_,
                           shared_tops);
    return {ok, top_notices, "Legacy"};
}

void StratigraphyCorrelationPage::build_engine_plan_only(
    const std::vector<std::any>& logs,
    const std::vector<std::string>& names,
    const std::vector<std::string>& resource_ids,
    const std::optional<TopsByWell>& raw_tops_opt) {
    TopsByWell matched;
    if (project_.has_value() && workflow_.match_tops) {
        TopsByWell raw;
        if (raw_tops_opt.has_value()) {
            raw = *raw_tops_opt;
        } else if (workflow_.load_well_tops) {
            raw = workflow_.load_well_tops().first;
        }
        matched = workflow_.match_tops(raw, names).matched;
    }
    std::string horizon;
    if (project_.has_value() && workflow_.active_target_horizon) {
        horizon = workflow_.active_target_horizon().value_or("");
    }
    if (!engine_.adapt_plan) {
        engine_plan_.reset();
        return;
    }
    CorrelationEngineApi::PlanInput input;
    input.logs = logs;
    input.names = names;
    input.resource_ids = resource_ids;
    input.tops_by_well = std::move(matched);
    input.spacing_px = spacing_slider_->value();
    input.datum_mode = horizon.empty() ? "md" : "horizon";
    input.target_horizon = horizon;
    engine_plan_ = engine_.adapt_plan(input);
}

bool StratigraphyCorrelationPage::apply_engine_section(
    const std::vector<std::any>& logs,
    const std::vector<std::string>& names,
    const std::vector<std::string>& ids) {
    engine_error_.clear();
    engine_report_.reset();
    build_engine_plan_only(logs, names, ids, std::nullopt);
    const bool has_wells =
        engine_plan_.has_value() && engine_.plan_has_wells &&
        engine_.plan_has_wells(engine_plan_);
    if (!engine_plan_.has_value() || !has_wells) {
        engine_error_ = "多井计划为空";
        engine_placeholder_->setText(QString::fromStdString(
            "WellLogEngine 无法构建多井计划。\n" + engine_error_));
        engine_placeholder_->show();
        return false;
    }
    ensure_engine_view();
    if (engine_view_ == nullptr) {
        if (engine_error_.empty()) {
            engine_error_ = "WellLogView 不可用";
        }
        engine_placeholder_->setText(QString::fromStdString(
            "WellLogEngine 不可用。\n" + engine_error_ +
            "\n可切换回 Legacy。"));
        engine_placeholder_->show();
        return false;
    }
    try {
        engine_report_ = engine_.submit_plan
                             ? engine_.submit_plan(engine_view_,
                                                   engine_plan_)
                             : std::any{};
    } catch (const std::exception& exc) {
        engine_error_ =
            ui_workers::py_error_class_name(exc) + ": " + exc.what();
        engine_placeholder_->setText(QString::fromStdString(
            "WellLogEngine 加载失败。\n" + engine_error_));
        engine_placeholder_->show();
        return false;
    }
    engine_placeholder_->hide();
    engine_view_->show();
    return true;
}

void StratigraphyCorrelationPage::clear_section() {
    if (dtw_job_->is_running()) {
        dtw_job_->cancel();
    }
    if (load_job_->is_running()) {
        load_seq_.bump();
        load_job_->cancel();
    }
    if (canvas_.clear) {
        canvas_.clear();
    }
    if (canvas_.tops_clear) {
        canvas_.tops_clear();
    }
    if (canvas_.picks_clear) {
        canvas_.picks_clear();
    }
    formation_combo_->clear();
    track_list_->clear();
    release_engine_view();
    loaded_names_.clear();
    loaded_logs_.clear();
    loaded_ids_.clear();
    if (workflow_.bind_wells) {
        workflow_.bind_wells({}, {});
    }
    engine_plan_.reset();
    engine_report_.reset();
    engine_error_.clear();
    loaded_value_->setText("已加载: 0 口井");
    tops_value_->setText("相/顶: —");
    status_label_->setText("剖面已清空");
}

// ---------------------------------------------------------------------------
// exports
// ---------------------------------------------------------------------------

void StratigraphyCorrelationPage::export_tops() {
    const bool has_tops = canvas_.tops_any && canvas_.tops_any();
    if (!has_tops) {
        emit warning_requested("导出", "没有分层顶数据");
        return;
    }
    const std::string start_dir =
        workflow_.export_dir ? workflow_.export_dir() : std::string{};
    const QString suggested = QString::fromStdString(
        start_dir.empty() ? "well_tops.csv"
                          : start_dir + "/well_tops.csv");
    const QString path = QFileDialog::getSaveFileName(
        this, "导出分层顶 CSV", suggested, "CSV (*.csv)");
    if (path.isEmpty()) {
        return;
    }
    try {
        if (canvas_.save_tops_csv) {
            canvas_.save_tops_csv(path.toStdString());
        } else {
            emit warning_requested("导出失败",
                                   "tops 模型未绑定");
            return;
        }
    } catch (const std::exception& exc) {
        emit warning_requested(
            "导出失败",
            QString::fromStdString(ui_workers::py_error_class_name(exc) +
                                   ": " + exc.what()));
        return;
    }
    register_export(path.toStdString(), "csv", "分层顶 CSV");
    emit info_requested(
        "导出完成",
        QString::fromStdString(
            "已导出: " +
            std::filesystem::path(path.toStdString())
                .filename()
                .string()));
}

void StratigraphyCorrelationPage::export_section() {
    if (backend_ == CorrelationBackend::Engine) {
        if (engine_view_ == nullptr || !engine_report_.has_value()) {
            emit warning_requested(
                "导出", "请先加载 WellLogEngine 连井剖面");
            return;
        }
        const std::string start_dir =
            workflow_.export_dir ? workflow_.export_dir()
                                 : std::string{};
        const QString suggested = QString::fromStdString(
            start_dir.empty() ? "cross_well_engine.png"
                              : start_dir + "/cross_well_engine.png");
        const QString path = QFileDialog::getSaveFileName(
            this, "导出连井剖面 (Engine PNG)", suggested,
            "PNG (*.png)");
        if (path.isEmpty()) {
            return;
        }
        bool saved = false;
        try {
            saved = engine_.grab_png
                        ? engine_.grab_png(engine_view_,
                                           path.toStdString())
                        : engine_view_->grab().save(
                              path, "PNG");
        } catch (const std::exception& exc) {
            emit warning_requested(
                "导出失败",
                QString::fromStdString(
                    ui_workers::py_error_class_name(exc) + ": " +
                    exc.what()));
            return;
        }
        if (!saved) {
            emit warning_requested("导出失败",
                                   "WellLogEngine 抓屏失败");
            return;
        }
        register_export(path.toStdString(), "png",
                        "连井剖面 (Engine PNG)");
        emit info_requested(
            "导出完成",
            QString::fromStdString(
                "已导出: " +
                std::filesystem::path(path.toStdString())
                    .filename()
                    .string()));
        return;
    }

    const bool has = canvas_.has_canvases && canvas_.has_canvases();
    if (!has) {
        emit warning_requested("导出", "请先加载连井剖面");
        return;
    }
    CrossWellExportDialog dialog(this);
    if (dialog.exec() != QDialog::Accepted) {
        return;
    }
    const CrossWellExportOptions opts = dialog.options();
    const std::string start_dir =
        workflow_.export_dir ? workflow_.export_dir() : std::string{};
    const QString suggested = QString::fromStdString(
        (start_dir.empty() ? "." : start_dir) +
        "/cross_well_correlation." + opts.fmt);
    const QString path = QFileDialog::getSaveFileName(
        this, "导出连井剖面", suggested,
        QString::fromStdString(opts.fmt + " (*." + opts.fmt + ")")
            .toUpper());
    if (path.isEmpty()) {
        return;
    }
    try {
        if (canvas_.export_composite) {
            canvas_.export_composite(path.toStdString(), opts);
        } else {
            emit warning_requested("导出失败",
                                   "剖面导出表面未绑定");
            return;
        }
    } catch (const std::exception& exc) {
        emit warning_requested(
            "导出失败",
            QString::fromStdString(ui_workers::py_error_class_name(exc) +
                                   ": " + exc.what()));
        return;
    }
    register_export(path.toStdString(), opts.fmt, "连井剖面");
    emit info_requested(
        "导出完成",
        QString::fromStdString(
            "已导出: " +
            std::filesystem::path(path.toStdString())
                .filename()
                .string()));
}

void StratigraphyCorrelationPage::register_export(
    const std::string& path, const std::string& fmt,
    const std::string& label) {
    if (!project_.has_value() || !workflow_.register_export) {
        return;
    }
    try {
        workflow_.register_export(label + " export", path, fmt,
                                  loaded_ids_);
    } catch (...) {
        // Provenance is best-effort; never break the export flow.
    }
}

// ---------------------------------------------------------------------------
// interpretation lifecycle
// ---------------------------------------------------------------------------

void StratigraphyCorrelationPage::open_link_editor() {
    if (loaded_names_.empty()) {
        status_label_->setText(
            "请先加载连井剖面，再编辑相关链接");
        return;
    }
    if (!workflow_.run_link_editor || !workflow_.tops_from_canvas ||
        !workflow_.new_draft) {
        status_label_->setText("解释编辑工作流未绑定");
        return;
    }
    if (!correlation_draft_.has_value()) {
        // _ensure_correlation_draft — lazy create from canvas tops.
        const auto tops = workflow_.tops_from_canvas(
            loaded_names_, loaded_ids_, std::any{});
        const auto version_ids = workflow_.resolve_version_ids
                                     ? workflow_.resolve_version_ids(
                                           loaded_ids_)
                                     : std::vector<std::string>{};
        const std::string horizon =
            workflow_.active_target_horizon
                ? workflow_.active_target_horizon().value_or("")
                : "";
        correlation_draft_ =
            workflow_.new_draft(tops, loaded_ids_, version_ids, horizon);
        if (workflow_.apply_links) {
            workflow_.apply_links(correlation_draft_, tops);
        }
    }
    workflow_.run_link_editor(this, correlation_draft_, [this] {
        interp_status_->setText(
            "解释: 链接已修改（保存后生成新版本）");
    });
}

void StratigraphyCorrelationPage::save_interpretation_version() {
    const bool project_bound = project_.has_value();
    const bool file_present = !project_path_.empty();

    std::vector<std::any> tops;
    bool tops_built = false;
    std::string tops_error;
    if (project_bound && file_present &&
        loaded_names_.size() == loaded_ids_.size()) {
        if (workflow_.tops_from_canvas) {
            try {
                tops = workflow_.tops_from_canvas(
                    loaded_names_, loaded_ids_, correlation_draft_);
                tops_built = true;
            } catch (const std::exception& exc) {
                tops_error = exc.what();
            }
        } else {
            tops_error = "解释工作流未绑定（correlation_session 无 C++ "
                         "端口）";
        }
    }
    const InterpSaveDecision gate = gate_save_interpretation(
        project_bound, loaded_names_.size(), loaded_ids_.size(),
        file_present, tops_built,
        tops_built && tops.empty(), tops_error);
    if (gate.gate != InterpSaveGate::Ok) {
        emit warning_requested("保存解释",
                               QString::fromStdString(gate.message));
        return;
    }
    if (!workflow_.save_draft || !workflow_.new_draft) {
        emit warning_requested(
            "保存解释",
            "解释生命周期工作流未绑定（correlation_lifecycle 无 C++ "
            "端口）");
        return;
    }

    const auto version_ids =
        workflow_.resolve_version_ids
            ? workflow_.resolve_version_ids(loaded_ids_)
            : std::vector<std::string>{};
    const std::string horizon =
        workflow_.active_target_horizon
            ? workflow_.active_target_horizon().value_or("")
            : "";
    if (!correlation_draft_.has_value()) {
        correlation_draft_ =
            workflow_.new_draft(tops, loaded_ids_, version_ids, horizon);
        if (workflow_.apply_links) {
            workflow_.apply_links(correlation_draft_, tops);
        }
    } else if (workflow_.update_draft) {
        workflow_.update_draft(correlation_draft_, tops, loaded_ids_,
                               version_ids);
        if (workflow_.apply_links) {
            workflow_.apply_links(correlation_draft_, tops);
        }
    }
    auto [ref, msg] = workflow_.save_draft(correlation_draft_);
    const InterpSaveOutcome outcome = interp_save_outcome(ref, msg);
    if (!outcome.interp_status.empty()) {
        interp_status_->setText(
            QString::fromStdString(outcome.interp_status));
    }
    if (!outcome.dialog_text.empty()) {
        emit info_requested("保存解释",
                            QString::fromStdString(outcome.dialog_text));
    }
    if (!outcome.failure_text.empty()) {
        emit warning_requested(
            "保存解释", QString::fromStdString(outcome.failure_text));
        return;
    }
    if (outcome.saved) {
        emit section_updated();
    }
}

bool StratigraphyCorrelationPage::apply_draft_tops_to_canvas(
    const std::any& draft) {
    try {
        if (canvas_.tops_clear) {
            canvas_.tops_clear();
        }
        if (workflow_.draft_info && canvas_.add_top) {
            const auto info = workflow_.draft_info(draft);
            for (const auto& [well, marker, depth] : info.tops) {
                canvas_.add_top(well, marker, depth);
            }
        }
        formation_combo_->clear();
        if (canvas_.formation_names) {
            for (const auto& name : canvas_.formation_names()) {
                formation_combo_->addItem(
                    QString::fromStdString(name));
            }
        }
    } catch (const std::exception& exc) {
        emit warning_requested(
            "打开解释",
            QString::fromStdString("无法把层位恢复到画布:\n" +
                                   std::string(exc.what())));
        return false;
    }
    return true;
}

void StratigraphyCorrelationPage::open_saved_interpretation() {
    const bool project_bound = project_.has_value();
    const bool file_present = !project_path_.empty();
    if (!project_bound) {
        emit warning_requested("打开解释", "未绑定工程");
        return;
    }
    if (!file_present || !workflow_.restore_draft) {
        const InterpOpenDecision decision = gate_open_interpretation(
            project_bound, file_present, std::nullopt, "", false, true);
        emit info_requested("打开解释",
                            QString::fromStdString(
                                decision.dialog_text.empty()
                                    ? "工程中尚无已保存的连井对比解释"
                                    : decision.dialog_text));
        return;
    }
    std::any draft;
    std::string restore_error;
    try {
        draft = workflow_.restore_draft();
    } catch (const std::exception& exc) {
        restore_error = exc.what();
    }
    const bool returned = draft.has_value();
    if (!returned || !restore_error.empty()) {
        const InterpOpenDecision decision = gate_open_interpretation(
            project_bound, file_present, std::nullopt, restore_error,
            returned, true);
        if (decision.gate == InterpOpenGate::RestoreFailed) {
            emit warning_requested(
                "打开解释",
                QString::fromStdString(decision.dialog_text));
        } else {
            emit info_requested(
                "打开解释",
                QString::fromStdString(decision.dialog_text));
        }
        return;
    }
    correlation_draft_ = draft;
    if (!apply_draft_tops_to_canvas(draft)) {
        const InterpOpenDecision decision = gate_open_interpretation(
            project_bound, file_present, std::nullopt, "", true, false);
        interp_status_->setText(
            QString::fromStdString(decision.interp_status));
        return;
    }
    std::string parent;
    if (workflow_.draft_info) {
        parent = workflow_.draft_info(draft).parent_version_id;
    }
    const InterpOpenDecision decision = gate_open_interpretation(
        project_bound, file_present,
        parent.empty() ? std::nullopt
                       : std::optional<std::string>(parent),
        "", true, true);
    interp_status_->setText(
        QString::fromStdString(decision.interp_status));
    emit section_updated();
}

void StratigraphyCorrelationPage::restore_saved_interpretation() {
    if (!project_.has_value()) {
        return;
    }
    bool dirty = false;
    if (correlation_draft_.has_value() && workflow_.draft_info) {
        dirty = workflow_.draft_info(correlation_draft_).dirty;
    }
    if (const auto prompt = restore_confirm_text(dirty);
        prompt.has_value()) {
        const bool yes =
            confirm_fn_ ? confirm_fn_(
                              "恢复已保存版本",
                              QString::fromStdString(*prompt))
                        : QMessageBox::question(
                              this, "恢复已保存版本",
                              QString::fromStdString(*prompt)) ==
                              QMessageBox::Yes;
        if (!yes) {
            return;
        }
    }
    open_saved_interpretation();
}

void StratigraphyCorrelationPage::refresh_interp_status() {
    const std::vector<CorrelationInterpRef> refs =
        workflow_.interp_refs && project_.has_value()
            ? workflow_.interp_refs()
            : std::vector<CorrelationInterpRef>{};
    interp_status_->setText(QString::fromStdString(
        interp_status_text(project_.has_value(), refs)));
}

// ---------------------------------------------------------------------------
// misc
// ---------------------------------------------------------------------------

bool StratigraphyCorrelationPage::confirm_question(
    const QString& title, const QString& message) {
    if (confirm_fn_) {
        return confirm_fn_(title, message);
    }
    return QMessageBox::question(this, title, message) ==
           QMessageBox::Yes;
}

void StratigraphyCorrelationPage::closeEvent(QCloseEvent* event) {
    shutdown_workers();
    QWidget::closeEvent(event);
}

void StratigraphyCorrelationPage::persist_docked_sizes() {
    if (persistence_ == nullptr) {
        return;
    }
    const auto sizes = splitter_->sizes();
    const std::vector<int> size_vec(sizes.begin(), sizes.end());
    for (const auto& [key, panel] : floatable_) {
        if (panel->parentWidget() == splitter_) {
            persistence_->save_docked_sizes(key, size_vec);
        }
    }
}

void StratigraphyCorrelationPage::make_floatable(
    const std::string& key, QWidget* panel, const QString& title) {
    ui_shell::dock_manager().register_panel(key, title.toStdString());
    floatable_.emplace_back(key, panel);
    new PanelFloatButton(key, panel, float_controller_.get());
}

// ---------------------------------------------------------------------------
// CrossWellExportDialog — cross_well_export_dialog.py parity.
// ---------------------------------------------------------------------------

CrossWellExportDialog::CrossWellExportDialog(QWidget* parent)
    : QDialog(parent) {
    setWindowTitle("导出连井剖面");
    auto* layout = new QVBoxLayout(this);
    auto* form = new QFormLayout();

    format_combo_ = new QComboBox(this);
    format_combo_->addItem("SVG 矢量图", "svg");
    format_combo_->addItem("PNG 位图", "png");
    format_combo_->addItem("PDF 文档", "pdf");
    connect(format_combo_, &QComboBox::currentIndexChanged, this,
            [this](int) { update_enabled(); });
    form->addRow("格式", format_combo_);

    dpi_combo_ = new QComboBox(this);
    for (int dpi : {96, 150, 300}) {
        dpi_combo_->addItem(QString::number(dpi), dpi);
    }
    dpi_combo_->setCurrentIndex(1);  // 150
    form->addRow("DPI", dpi_combo_);

    width_spin_ = new QSpinBox(this);
    width_spin_->setRange(0, 20000);
    width_spin_->setSingleStep(100);
    width_spin_->setSpecialValueText("自然宽度");
    width_spin_->setSuffix(" px");
    width_spin_->setValue(0);
    form->addRow("宽度", width_spin_);

    page_size_combo_ = new QComboBox(this);
    page_size_combo_->addItem("内容尺寸", QVariant{});
    page_size_combo_->addItem("A4", "A4");
    page_size_combo_->addItem("Letter", "LETTER");
    connect(page_size_combo_, &QComboBox::currentIndexChanged, this,
            [this](int) { update_enabled(); });
    form->addRow("纸张", page_size_combo_);

    layout->addLayout(form);
    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons, &QDialogButtonBox::accepted, this,
            &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this,
            &QDialog::reject);
    layout->addWidget(buttons);

    update_enabled();
}

void CrossWellExportDialog::update_enabled() {
    const QString fmt = format_combo_->currentData().toString();
    dpi_combo_->setEnabled(fmt == "png" || fmt == "pdf");
    page_size_combo_->setEnabled(fmt == "pdf");
    const bool page_size_set =
        fmt == "pdf" && page_size_combo_->currentData().isValid() &&
        !page_size_combo_->currentData().toString().isEmpty();
    width_spin_->setEnabled(!page_size_set);
}

CrossWellExportOptions CrossWellExportDialog::options() const {
    CrossWellExportOptions opts;
    opts.fmt = format_combo_->currentData().toString().toStdString();
    opts.dpi = dpi_combo_->currentData().toInt();
    const int width = width_spin_->value();
    opts.width_px = width > 0 ? std::optional<int>(width)
                              : std::nullopt;
    if (opts.fmt == "pdf") {
        const QString page =
            page_size_combo_->currentData().toString();
        if (!page.isEmpty()) {
            opts.page_size = page.toStdString();
            opts.width_px.reset();
        }
    }
    return opts;
}

}  // namespace pwb::ui_seqviz::qt
