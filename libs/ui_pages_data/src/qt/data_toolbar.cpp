// UI-06 — DataToolbar shell (see qt/data_toolbar.hpp).
#include <pwb/ui_pages_data/qt/data_toolbar.hpp>

#include <QAction>
#include <QActionGroup>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QMenu>
#include <QPushButton>
#include <QTimer>

#include <algorithm>

#include <pwb/ui_pages_data/timings.hpp>
#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_pages_data::qt {

ToolbarIconFn DataToolbar::icon_provider_;

void DataToolbar::set_icon_provider(ToolbarIconFn fn) {
    icon_provider_ = std::move(fn);
}

namespace {

QIcon icon(const std::string& name) {
    return DataToolbar::icon_provider() ? DataToolbar::icon_provider()(name)
                                        : QIcon();
}

// sorted({t for t in tags if t and str(t).strip()})
std::vector<std::string> clean_tags(const std::vector<std::string>& tags) {
    std::vector<std::string> out;
    for (const auto& tag : tags) {
        const auto first = tag.find_first_not_of(" \t\r\n");
        if (tag.empty() || first == std::string::npos) continue;
        if (std::find(out.begin(), out.end(), tag) == out.end()) {
            out.push_back(tag);
        }
    }
    std::sort(out.begin(), out.end());
    return out;
}

QPushButton* make_button(QWidget* parent, const char* icon_name,
                         const QString& text, const QString& object,
                         const QString& tooltip) {
    auto* btn = new QPushButton(icon(icon_name), text, parent);
    btn->setObjectName(object);
    ui_shell::style_track_control_height(btn);
    btn->setToolTip(tooltip);
    return btn;
}

}  // namespace

DataToolbar::DataToolbar(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("DataToolbar"));
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(4);                       // SPACE_1

    import_btn_ = new QPushButton(icon("btn-import"),
                                  QStringLiteral("导入文件"), this);
    import_btn_->setObjectName(QStringLiteral("PrimaryButton"));
    import_btn_->setMinimumHeight(34);           // CONTROL_HEIGHT_LG
    import_btn_->setToolTip(
        QStringLiteral("导入文件并创建项目受管的不可变 RAW 副本"));
    connect(import_btn_, &QPushButton::clicked, this,
            &DataToolbar::import_files_requested);
    layout->addWidget(import_btn_);

    import_folder_btn_ = make_button(
        this, "btn-import-folder", QStringLiteral("导入目录"),
        "SecondaryButton", QStringLiteral("导入整个目录"));
    connect(import_folder_btn_, &QPushButton::clicked, this,
            &DataToolbar::import_folder_requested);
    layout->addWidget(import_folder_btn_);

    plan_import_btn_ = make_button(
        this, "btn-import", QStringLiteral("规划导入…"), "SecondaryButton",
        QStringLiteral(
            "规划导入：扫描/分类/身份匹配/查重 → 逐项确认 → 分块执行"
            "（与 Agent 导入共用同一计划服务）"));
    connect(plan_import_btn_, &QPushButton::clicked, this,
            &DataToolbar::plan_import_requested);
    layout->addWidget(plan_import_btn_);

    // D4: visible only while an import runs; cooperative cancel.
    cancel_import_btn_ = new QPushButton(QStringLiteral("取消导入"), this);
    cancel_import_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    cancel_import_btn_->setMinimumHeight(30);    // CONTROL_HEIGHT
    cancel_import_btn_->setToolTip(QStringLiteral(
        "协作式取消：当前分块完成后停止，已完成分块保持一致"));
    cancel_import_btn_->setVisible(false);
    connect(cancel_import_btn_, &QPushButton::clicked, this,
            &DataToolbar::cancel_import_requested);
    layout->addWidget(cancel_import_btn_);

    verify_btn_ = make_button(this, "btn-verify", QStringLiteral("完整性校验"),
                              "SecondaryButton",
                              QStringLiteral("后台校验数据资产完整性与 SHA-256"));
    connect(verify_btn_, &QPushButton::clicked, this,
            &DataToolbar::verify_requested);
    layout->addWidget(verify_btn_);

    health_btn_ = make_button(
        this, "btn-health", QStringLiteral("健康检查"), "SecondaryButton",
        QStringLiteral(
            "数据目录健康体检：资产/版本统计、缺失、血缘断链、标签悬挂、孤儿文件"));
    connect(health_btn_, &QPushButton::clicked, this,
            &DataToolbar::health_check_requested);
    layout->addWidget(health_btn_);

    rescan_btn_ = make_button(this, "btn-rescan", QStringLiteral("重新扫描"),
                              "SecondaryButton", QStringLiteral("重新扫描选中项"));
    connect(rescan_btn_, &QPushButton::clicked, this,
            &DataToolbar::rescan_requested);
    layout->addWidget(rescan_btn_);

    remove_btn_ = make_button(this, "btn-remove", QStringLiteral("移出项目"),
                              "SecondaryButton",
                              QStringLiteral("移出项目（不删源文件）"));
    connect(remove_btn_, &QPushButton::clicked, this,
            &DataToolbar::remove_requested);
    layout->addWidget(remove_btn_);

    open_folder_btn_ = make_button(this, "btn-open-folder",
                                   QStringLiteral("打开目录"), "SecondaryButton",
                                   QStringLiteral("在文件管理器中打开"));
    connect(open_folder_btn_, &QPushButton::clicked, this,
            &DataToolbar::open_folder_requested);
    layout->addWidget(open_folder_btn_);

    visualize_btn_ = make_button(this, "btn-visualize", QStringLiteral("可视化"),
                                 "SecondaryButton",
                                 QStringLiteral("在可视化页面打开"));
    connect(visualize_btn_, &QPushButton::clicked, this,
            &DataToolbar::visualize_requested);
    layout->addWidget(visualize_btn_);

    clear_preview_cache_btn_ = make_button(
        this, "btn-clear-cache", QStringLiteral("清除预览缓存"),
        "SecondaryButton", QStringLiteral("清除项目预览磁盘缓存"));
    connect(clear_preview_cache_btn_, &QPushButton::clicked, this,
            &DataToolbar::clear_preview_cache_requested);
    layout->addWidget(clear_preview_cache_btn_);

    // --- Tag tools ---------------------------------------------------------
    tag_filter_btn_ = make_button(this, "btn-tag-filter",
                                  QStringLiteral("标签筛选"), "SecondaryButton",
                                  QStringLiteral("按标签筛选资产表（支持多选与 AND/OR 组合）"));
    tag_filter_menu_ = new QMenu(tag_filter_btn_);
    connect(tag_filter_menu_, &QMenu::aboutToShow, this,
            &DataToolbar::rebuild_tag_filter_menu);
    tag_filter_btn_->setMenu(tag_filter_menu_);
    layout->addWidget(tag_filter_btn_);

    tag_manager_btn_ = make_button(this, "btn-tag-manager",
                                   QStringLiteral("标签管理"), "SecondaryButton",
                                   QStringLiteral("管理标签：新建 / 重命名 / 合并 / 清理"));
    connect(tag_manager_btn_, &QPushButton::clicked, this,
            &DataToolbar::tag_manager_requested);
    layout->addWidget(tag_manager_btn_);

    operation_status_label_ = new QLabel(QString(), this);
    {
        const auto p = ui_shell::style_palette();
        const auto it = p.find("TEXT_SECONDARY");
        if (it != p.end()) {
            operation_status_label_->setStyleSheet(
                QStringLiteral("color: %1;")
                    .arg(QString::fromStdString(it->second)));
        }
    }
    layout->addWidget(operation_status_label_);

    search_timer_ = new QTimer(this);
    search_timer_->setSingleShot(true);
    search_timer_->setInterval(kSearchDebounceMs);  // 180
    connect(search_timer_, &QTimer::timeout, this,
            &DataToolbar::emit_debounced_search);

    search_box_ = new QLineEdit(this);
    search_box_->setObjectName(QStringLiteral("SearchBox"));
    search_box_->setPlaceholderText(
        QStringLiteral("搜索文件名 / 类型 / 阶段 / 标签 / 路径..."));
    search_box_->setToolTip(
        QStringLiteral("搜索文件名/类型/阶段/标签/路径"));
    search_box_->setClearButtonEnabled(true);
    ui_shell::style_track_control_height(search_box_);
    connect(search_box_, &QLineEdit::textChanged, this,
            [this](const QString& text) {
                if (search_sync_) return;
                pending_search_ = text;
                search_timer_->start();
            });
    layout->addWidget(search_box_, 1);

    column_settings_slot_ = new QWidget(this);
    column_settings_slot_->setObjectName(QStringLiteral("ColumnSettingsSlot"));
    auto* slot_layout = new QHBoxLayout(column_settings_slot_);
    slot_layout->setContentsMargins(0, 0, 0, 0);
    slot_layout->setSpacing(0);
    layout->addWidget(column_settings_slot_);

    // Hides the whole right column (reader + inspector), not only the reader.
    reader_btn_ = make_button(this, "btn-reader", QStringLiteral("预览栏"),
                              "SecondaryButton",
                              QStringLiteral("显示或隐藏右侧预览与属性面板"));
    reader_btn_->setCheckable(true);
    connect(reader_btn_, &QPushButton::clicked, this,
            &DataToolbar::reader_toggled);
    layout->addWidget(reader_btn_);
}

void DataToolbar::set_verify_running(bool running) {
    verify_running_ = running;
    const VerifyButtonState state = verify_button_state(running);
    verify_btn_->setText(QString::fromStdString(state.text));
    verify_btn_->setToolTip(QString::fromStdString(state.tooltip));
}

void DataToolbar::set_column_settings_button(QPushButton* button) {
    column_settings_slot_->layout()->addWidget(button);
}

// --- tag filter --------------------------------------------------------------

void DataToolbar::set_tag_candidates(const std::vector<std::string>& tags) {
    tag_candidates_ = clean_tags(tags);
}

void DataToolbar::set_tag_operator(const std::string& op) {
    if (op == "and" || op == "or") tag_operator_ = op;
}

void DataToolbar::apply_tag_selection(const std::vector<std::string>& tags,
                                      const std::string& op) {
    selected_tags_.clear();
    for (const auto& tag : tags) {
        const auto first = tag.find_first_not_of(" \t\r\n");
        if (!tag.empty() && first != std::string::npos) {
            selected_tags_.push_back(tag);
        }
    }
    if (op == "and" || op == "or") tag_operator_ = op;
    emit_tag_filter();
}

void DataToolbar::rebuild_tag_filter_menu() {
    tag_filter_menu_->clear();
    tag_check_actions_.clear();
    if (tag_candidates_.empty()) {
        auto* empty = new QAction(QStringLiteral("暂无可用标签"),
                                  tag_filter_menu_);
        empty->setEnabled(false);
        tag_filter_menu_->addAction(empty);
        return;
    }
    for (const auto& tag : tag_candidates_) {
        auto* action =
            new QAction(QString::fromStdString(tag), tag_filter_menu_);
        action->setCheckable(true);
        action->setChecked(std::find(selected_tags_.begin(),
                                     selected_tags_.end(),
                                     tag) != selected_tags_.end());
        connect(action, &QAction::toggled, this,
                [this, tag](bool checked) { on_tag_toggled(tag, checked); });
        tag_filter_menu_->addAction(action);
        tag_check_actions_.push_back(action);
    }
    tag_filter_menu_->addSeparator();

    auto* operator_group = new QActionGroup(tag_filter_menu_);
    operator_group->setExclusive(true);
    const std::pair<const char*, const char*> ops[] = {
        {"匹配全部 (AND)", "and"}, {"匹配任一 (OR)", "or"}};
    for (const auto& [label, value] : ops) {
        auto* op_action = new QAction(QString::fromUtf8(label),
                                      tag_filter_menu_);
        op_action->setCheckable(true);
        op_action->setChecked(tag_operator_ == value);
        op_action->setActionGroup(operator_group);
        const std::string op = value;
        connect(op_action, &QAction::toggled, this,
                [this, op](bool checked) { on_operator_changed(op, checked); });
        tag_filter_menu_->addAction(op_action);
    }
    tag_filter_menu_->addSeparator();

    auto* clear_action = new QAction(QStringLiteral("清除标签筛选"),
                                     tag_filter_menu_);
    connect(clear_action, &QAction::triggered, this,
            &DataToolbar::clear_tag_filter);
    tag_filter_menu_->addAction(clear_action);
}

void DataToolbar::on_tag_toggled(const std::string& tag, bool checked) {
    const auto it =
        std::find(selected_tags_.begin(), selected_tags_.end(), tag);
    if (checked && it == selected_tags_.end()) {
        selected_tags_.push_back(tag);
    } else if (!checked && it != selected_tags_.end()) {
        selected_tags_.erase(it);
    }
    emit_tag_filter();
}

void DataToolbar::on_operator_changed(const std::string& op, bool checked) {
    if (!checked) return;
    tag_operator_ = op;
    emit_tag_filter();
}

void DataToolbar::clear_tag_filter() {
    selected_tags_.clear();
    emit_tag_filter();
}

void DataToolbar::emit_tag_filter() {
    QStringList tags;
    for (const auto& tag : selected_tags_) {
        tags << QString::fromStdString(tag);
    }
    Q_EMIT tag_filter_changed(tags, QString::fromStdString(tag_operator_));
}

void DataToolbar::set_search_text_silent(const QString& text) {
    search_sync_ = true;
    search_box_->setText(text);
    search_sync_ = false;
}

void DataToolbar::emit_debounced_search() {
    Q_EMIT search_changed(pending_search_);
}

}  // namespace pwb::ui_pages_data::qt
