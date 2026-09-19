#include <pwb/ui_wellseis/qt/seismic_context_toolbar.hpp>

#include <QAction>
#include <QActionGroup>
#include <QComboBox>
#include <QGridLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QMenu>
#include <QPushButton>
#include <QToolButton>
#include <QWidgetAction>

#include <pwb/ui_wellseis/output_labels.hpp>
#include <pwb/ui_wellseis/seismic_attributes.hpp>

namespace pwb::ui_wellseis::qt {

namespace {

QString qs(const std::string& text) {
    return QString::fromUtf8(text.data(), static_cast<int>(text.size()));
}

QLabel* field_label(const QString& text, QWidget* parent) {
    auto* label = new QLabel(text, parent);
    label->setObjectName(QStringLiteral("WorkFieldLabel"));
    return label;
}

QLabel* field_value_label(const QString& text, QWidget* parent) {
    auto* label = new QLabel(text, parent);
    label->setObjectName(QStringLiteral("WorkFieldValue"));
    return label;
}

}  // namespace

SeismicContextToolbar::SeismicContextToolbar(QWidget* parent)
    : QFrame(parent) {
    setObjectName(QStringLiteral("SeismicContextToolbar"));
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(12, 4, 12, 4);
    layout->setSpacing(8);

    // 1. 工区地震体 (source volume selector)
    layout->addWidget(field_label(QStringLiteral("工区地震体"), this));
    source_combo_ = new QComboBox(this);
    source_combo_->setObjectName(QStringLiteral("SeismicPredictionSourceCombo"));
    source_combo_->setPlaceholderText(
        QStringLiteral("选择数据管理中的 SEG-Y 地震体"));
    source_combo_->setToolTip(QStringLiteral(
        "选择工区数据中已归档的 .sgy / .segy 地震体，加载后可直接运行预测"));
    source_combo_->setMinimumWidth(180);
    connect(source_combo_, &QComboBox::currentIndexChanged, this, [this](int) {
        emit source_changed(
            source_combo_->currentData().toString());
    });
    layout->addWidget(source_combo_, 1);

    // 2. 地震属性下拉
    layout->addWidget(field_label(QStringLiteral("属性"), this));
    attribute_combo_ = new QComboBox(this);
    attribute_combo_->setObjectName(
        QStringLiteral("SeismicAttributeDropdownCombo"));
    attribute_combo_->setToolTip(QStringLiteral("快速切换当前显示的地震属性"));
    for (const std::string& attribute : all_seismic_attributes()) {
        attribute_combo_->addItem(qs(attribute));
    }
    connect(attribute_combo_, &QComboBox::currentTextChanged, this,
            [this](const QString& text) {
                if (!suppress_signals_ && !text.isEmpty()) {
                    attribute_value_->setText(text);
                    emit attribute_changed(text);
                }
            });
    layout->addWidget(attribute_combo_);

    // 3. 设置与详情 popover
    settings_btn_ = new QToolButton(this);
    settings_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    settings_btn_->setText(QStringLiteral("设置与详情 ▾"));
    settings_btn_->setToolTip(
        QStringLiteral("查看预测任务详情、目标层位、显示模式与状态"));
    settings_btn_->setPopupMode(QToolButton::InstantPopup);
    build_settings_menu();
    layout->addWidget(settings_btn_);

    // 4. 状态
    layout->addWidget(field_label(QStringLiteral("状态:"), this));
    status_value_ = field_value_label(QStringLiteral("—"), this);
    layout->addWidget(status_value_);

    layout->addStretch(1);

    // 6. 操作按钮
    demo_btn_ = new QPushButton(QStringLiteral("运行演示预测"), this);
    demo_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    demo_btn_->setToolTip(QStringLiteral(
        "显式演示模式：运行 DemoModelProvider（合成数据，非科学预测）"));
    connect(demo_btn_, &QPushButton::clicked, this,
            &SeismicContextToolbar::demo_requested);
    layout->addWidget(demo_btn_);

    run_btn_ = new QPushButton(QStringLiteral("运行预测"), this);
    run_btn_->setObjectName(QStringLiteral("PrimaryButton"));
    run_btn_->setToolTip(
        QStringLiteral("通过 ModelRegistry 解析生产模型后运行科学预测；"
                       "未配置生产模型时不会自动运行 mock"));
    connect(run_btn_, &QPushButton::clicked, this,
            &SeismicContextToolbar::run_requested);
    layout->addWidget(run_btn_);
}

void SeismicContextToolbar::build_settings_menu() {
    settings_menu_ = new QMenu(this);
    settings_menu_->setObjectName(QStringLiteral("SeismicSettingsMenu"));

    auto* details = new QFrame(settings_menu_);
    details->setObjectName(QStringLiteral("SeismicSettingsDetailsCard"));
    auto* grid = new QGridLayout(details);
    grid->setContentsMargins(8, 4, 8, 4);
    grid->setSpacing(4);

    grid->addWidget(field_label(QStringLiteral("任务:"), details), 0, 0);
    task_value_ =
        field_value_label(QStringLiteral("未选择预测任务"), details);
    grid->addWidget(task_value_, 0, 1);

    grid->addWidget(field_label(QStringLiteral("层位:"), details), 1, 0);
    horizon_value_ = field_value_label(QStringLiteral("—"), details);
    grid->addWidget(horizon_value_, 1, 1);

    grid->addWidget(field_label(QStringLiteral("当前属性:"), details), 2, 0);
    attribute_value_ = field_value_label(QStringLiteral("振幅"), details);
    grid->addWidget(attribute_value_, 2, 1);

    grid->addWidget(field_label(QStringLiteral("显示模式:"), details), 3, 0);
    mode_value_ = field_value_label(QStringLiteral("vd"), details);
    grid->addWidget(mode_value_, 3, 1);

    grid->addWidget(field_label(QStringLiteral("体数据维度:"), details), 4, 0);
    shape_value_ = field_value_label(QStringLiteral("—"), details);
    grid->addWidget(shape_value_, 4, 1);

    grid->addWidget(field_label(QStringLiteral("输出性质:"), details), 5, 0);
    mock_value_ = field_value_label(QStringLiteral("—"), details);
    grid->addWidget(mock_value_, 5, 1);

    auto* card_action = new QWidgetAction(settings_menu_);
    card_action->setDefaultWidget(details);
    settings_menu_->addAction(card_action);
    settings_menu_->addSeparator();

    // Display-mode submenu (checkable group).
    QMenu* mode_menu =
        settings_menu_->addMenu(QStringLiteral("切换显示模式"));
    mode_group_ = new QActionGroup(this);
    for (const std::string& mode : seismic_display_modes()) {
        QAction* action = new QAction(qs(mode), this);
        action->setCheckable(true);
        if (mode == kDisplayModeVd) {
            action->setChecked(true);
        }
        const QString mode_name = qs(mode);
        connect(action, &QAction::triggered, this, [this, mode_name] {
            mode_value_->setText(mode_name);
            emit display_mode_changed(mode_name);
        });
        mode_group_->addAction(action);
        mode_menu->addAction(action);
    }

    // Attribute submenu grouped by catalog.
    QMenu* attr_menu =
        settings_menu_->addMenu(QStringLiteral("切换地震属性"));
    for (const SeismicAttributeGroup& group : seismic_attribute_groups()) {
        QMenu* group_menu = attr_menu->addMenu(qs(group.group_label));
        for (const std::string& label : group.attributes) {
            QAction* action = new QAction(qs(label), this);
            const QString name = qs(label);
            connect(action, &QAction::triggered, this, [this, name] {
                set_selected_attribute(name);
                emit attribute_changed(name);
            });
            group_menu->addAction(action);
        }
    }

    settings_btn_->setMenu(settings_menu_);
}

void SeismicContextToolbar::set_context(
    const PredictionTaskSlice* task,
    const std::string& horizon,
    const std::string& attribute_label,
    const std::string& mode_label,
    std::optional<std::array<std::int64_t, 3>> volume_shape,
    const std::optional<std::string>& mock_nature) {
    task_value_->setText(
        task != nullptr && !task->name.empty()
            ? qs(task->name)
            : QStringLiteral("未选择预测任务"));
    horizon_value_->setText(horizon.empty() ? QStringLiteral("—")
                                            : qs(horizon));
    set_selected_attribute(qs(attribute_label_or_default(attribute_label)));
    const QString mode =
        mode_label.empty() ? QStringLiteral("vd") : qs(mode_label);
    mode_value_->setText(mode);
    for (QAction* action : mode_group_->actions()) {
        if (action->text() == mode) {
            action->setChecked(true);
        }
    }
    if (volume_shape.has_value()) {
        shape_value_->setText(qs(volume_shape_text(*volume_shape)));
    }
    if (mock_nature.has_value()) {
        mock_value_->setText(qs(*mock_nature));
    }
}

void SeismicContextToolbar::set_status(const QString& text) {
    status_value_->setText(text.isEmpty() ? QStringLiteral("—") : text);
}

void SeismicContextToolbar::set_inferring(bool inferring) {
    run_btn_->setEnabled(!inferring);
    demo_btn_->setEnabled(!inferring);
    if (inferring) {
        status_value_->setText(QStringLiteral("推断中…"));
    }
}

void SeismicContextToolbar::set_source_entries(
    const std::vector<SourceComboEntry>& entries) {
    const QString previous = source_combo_->currentData().toString();
    const QSignalBlocker blocker(source_combo_);
    source_combo_->clear();
    for (const SourceComboEntry& entry : entries) {
        source_combo_->addItem(qs(entry.label), qs(entry.resource_id));
    }
    const int index = previous.isEmpty()
                          ? -1
                          : source_combo_->findData(previous);
    // Python setCurrentIndex(selected_index) parity: an unresolved previous
    // selection lands on -1 (nothing shown), never silently on row 0.
    source_combo_->setCurrentIndex(index);
}

std::string SeismicContextToolbar::selected_source_id() const {
    return source_combo_->currentData().toString().toStdString();
}

void SeismicContextToolbar::set_selected_attribute(const QString& label) {
    const QString text = label.trimmed();
    if (text.isEmpty()) {
        return;
    }
    attribute_value_->setText(text);
    suppress_signals_ = true;
    const int index = attribute_combo_->findText(text);
    if (index >= 0) {
        attribute_combo_->setCurrentIndex(index);
    }
    suppress_signals_ = false;
}

void SeismicContextToolbar::set_display_mode(const QString& mode) {
    mode_value_->setText(mode.isEmpty() ? QStringLiteral("vd") : mode);
    for (QAction* action : mode_group_->actions()) {
        if (action->text() == mode_value_->text()) {
            action->setChecked(true);
        }
    }
}

}  // namespace pwb::ui_wellseis::qt
