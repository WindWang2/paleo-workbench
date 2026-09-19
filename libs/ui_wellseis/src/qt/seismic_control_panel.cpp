#include <pwb/ui_wellseis/qt/seismic_control_panel.hpp>

#include <QComboBox>
#include <QLabel>
#include <QPushButton>
#include <QVBoxLayout>

#include <pwb/ui_wellseis/output_labels.hpp>
#include <pwb/ui_wellseis/page_state.hpp>
#include <pwb/ui_wellseis/seismic_attributes.hpp>

namespace pwb::ui_wellseis::qt {

namespace {

QString qs(const std::string& text) {
    return QString::fromUtf8(text.data(), static_cast<int>(text.size()));
}

QLabel* add_value(QVBoxLayout* layout, const QString& label_text,
                  const QString& value_text, QWidget* parent) {
    auto* label = new QLabel(label_text, parent);
    label->setObjectName(QStringLiteral("WorkFieldLabel"));
    layout->addWidget(label);
    auto* value = new QLabel(value_text, parent);
    value->setObjectName(QStringLiteral("WorkFieldValue"));
    layout->addWidget(value);
    return value;
}

}  // namespace

SeismicControlPanel::SeismicControlPanel(QWidget* parent)
    : QFrame(parent) {
    setObjectName(QStringLiteral("SeismicControlPanel"));
    setMinimumWidth(200);

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(12, 12, 12, 12);
    layout->setSpacing(4);

    auto* title = new QLabel(QStringLiteral("智能分析结果"), this);
    title->setObjectName(QStringLiteral("MapDockTitle"));
    layout->addWidget(title);

    status_value_ = add_value(layout, QStringLiteral("分析状态"),
                              QStringLiteral("待开始"), this);
    shape_value_ = add_value(layout, QStringLiteral("体数据维度"),
                           QStringLiteral("—"), this);
    horizon_value_ = add_value(layout, QStringLiteral("目标层位"),
                               QStringLiteral("—"), this);
    mock_value_ = add_value(layout, QStringLiteral("输出性质"),
                            QStringLiteral("—"), this);
    attribute_value_ = add_value(layout, QStringLiteral("当前属性"),
                                 QStringLiteral("振幅"), this);

    auto* mode_label = new QLabel(QStringLiteral("显示模式"), this);
    mode_label->setObjectName(QStringLiteral("WorkFieldLabel"));
    layout->addWidget(mode_label);
    mode_combo_ = new QComboBox(this);
    for (const std::string& mode : seismic_display_modes()) {
        mode_combo_->addItem(qs(mode));
    }
    connect(mode_combo_, &QComboBox::currentTextChanged, this,
            [this](const QString& text) {
                if (!suppress_) {
                    emit display_mode_changed(text);
                }
            });
    layout->addWidget(mode_combo_);

    well_tie_btn_ =
        new QPushButton(QStringLiteral("井震标定 (Auto-Tie)"), this);
    well_tie_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    well_tie_btn_->setCheckable(true);
    connect(well_tie_btn_, &QPushButton::toggled, this, [this](bool checked) {
        if (!suppress_) {
            emit well_tie_toggled(checked);
        }
    });
    layout->addWidget(well_tie_btn_);

    layout->addStretch();
    send_btn_ = new QPushButton(QStringLiteral("发送编图"), this);
    send_btn_->setObjectName(QStringLiteral("PrimaryButton"));
    connect(send_btn_, &QPushButton::clicked, this,
            &SeismicControlPanel::send_requested);
    layout->addWidget(send_btn_);

    set_controls_enabled(false);
}

void SeismicControlPanel::update_state(
    const PredictionTaskSlice* task,
    std::optional<std::array<std::int64_t, 3>> volume_shape) {
    shape_value_->setText(qs(volume_shape_text(volume_shape)));
    const std::string horizon =
        task != nullptr
            ? target_horizon_of(task->model_metadata, task->result_summary)
            : "";
    horizon_value_->setText(horizon.empty() ? QStringLiteral("—")
                                            : qs(horizon));
    status_value_->setText(
        task != nullptr && !task->status.empty() ? qs(task->status)
                                                 : QStringLiteral("待开始"));
    if (task == nullptr) {
        mock_value_->setText(QStringLiteral("—"));
        set_controls_enabled(seismic_controls_enabled(false));
        return;
    }
    mock_value_->setText(qs(seismic_output_nature(task->result_summary)));
    set_controls_enabled(seismic_controls_enabled(true));
}

void SeismicControlPanel::set_attribute_label(const QString& label) {
    attribute_value_->setText(
        qs(attribute_label_or_default(label.toStdString())));
}

void SeismicControlPanel::set_controls_enabled(bool enabled) {
    mode_combo_->setEnabled(enabled);
    well_tie_btn_->setEnabled(enabled);
    send_btn_->setEnabled(enabled);
}

void SeismicControlPanel::set_display_mode(const QString& mode) {
    suppress_ = true;
    mode_combo_->setCurrentText(mode);
    suppress_ = false;
}

void SeismicControlPanel::set_well_tie_checked(bool checked) {
    suppress_ = true;
    well_tie_btn_->setChecked(checked);
    suppress_ = false;
}

QString SeismicControlPanel::display_mode() const {
    return mode_combo_->currentText();
}

}  // namespace pwb::ui_wellseis::qt
