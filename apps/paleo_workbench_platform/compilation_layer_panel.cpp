#include "compilation_layer_panel.hpp"

#include <QCheckBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QSlider>
#include <QVBoxLayout>

namespace pwb::app {

namespace {

QLabel* section_header(const QString& text, QWidget* parent) {
    auto* label = new QLabel(text, parent);
    label->setStyleSheet(QStringLiteral(
        "font-weight: 600; padding: 3px 2px; border-bottom: 1px solid "
        "#d8dde3;"));
    return label;
}

}  // namespace

CompilationLayerPanel::CompilationLayerPanel(QWidget* parent)
    : QWidget(parent) {
    setObjectName(QStringLiteral("CompilationLayerPanel"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(4, 2, 4, 4);
    layout->setSpacing(2);

    layout->addWidget(
        section_header(QStringLiteral("主要图层"), this));

    tree_slot_ = new QWidget(this);
    tree_slot_->setObjectName(QStringLiteral("CompilationTreeSlot"));
    auto* tree_layout = new QVBoxLayout(tree_slot_);
    tree_layout->setContentsMargins(0, 0, 0, 0);
    tree_layout->setSpacing(0);
    layout->addWidget(tree_slot_, 1);

    reference_title_ =
        section_header(QStringLiteral("参考图层"), this);
    layout->addWidget(reference_title_);

    auto* ref_host = new QWidget(this);
    ref_host->setObjectName(QStringLiteral("CompilationRefHost"));
    reference_box_ = new QVBoxLayout(ref_host);
    reference_box_->setContentsMargins(0, 0, 0, 0);
    reference_box_->setSpacing(2);
    layout->addWidget(ref_host);
    rebuild_rows();

    chrome_row_ = new QWidget(this);
    chrome_row_->setObjectName(QStringLiteral("CompilationChromeRow"));
    auto* chrome_layout = new QHBoxLayout(chrome_row_);
    chrome_layout->setContentsMargins(0, 2, 0, 0);
    chrome_layout->setSpacing(10);
    legend_check_ = new QCheckBox(QStringLiteral("图例"), chrome_row_);
    north_scale_check_ =
        new QCheckBox(QStringLiteral("指北针与比例尺"), chrome_row_);
    connect(legend_check_, &QCheckBox::toggled, this,
            [this](bool on) {
                emit chrome_element_toggled(QStringLiteral("图例"), on);
            });
    // 稿底部「指北针与比例尺」是一个勾选管两个 chrome 元素。
    connect(north_scale_check_, &QCheckBox::toggled, this, [this](bool on) {
        emit chrome_element_toggled(QStringLiteral("指北针"), on);
        emit chrome_element_toggled(QStringLiteral("比例尺"), on);
    });
    chrome_layout->addWidget(legend_check_);
    chrome_layout->addWidget(north_scale_check_);
    chrome_layout->addStretch();
    layout->addWidget(chrome_row_);
    chrome_row_->setVisible(mode_ == Mode::Compilation);
}

void CompilationLayerPanel::set_tree_widget(QWidget* tree) {
    if (tree == nullptr) return;
    tree->setParent(tree_slot_);
    qobject_cast<QVBoxLayout*>(tree_slot_->layout())->addWidget(tree);
    tree->show();
}

void CompilationLayerPanel::set_mode(Mode mode) {
    if (mode_ == mode) return;
    mode_ = mode;
    reference_title_->setText(mode == Mode::Compilation
                                  ? QStringLiteral("参考图")
                                  : QStringLiteral("参考图层"));
    chrome_row_->setVisible(mode == Mode::Compilation);
    rebuild_rows();
}

void CompilationLayerPanel::set_reference_rows(
    const QVector<ReferenceRow>& rows) {
    rows_ = rows;
    reference_row_count_ = static_cast<int>(rows.size());
    rebuild_rows();
}

void CompilationLayerPanel::set_chrome_state(bool legend,
                                             bool north_arrow_scale) {
    legend_check_->setChecked(legend);
    north_scale_check_->setChecked(north_arrow_scale);
}

bool CompilationLayerPanel::chrome_row_visible() const {
    return chrome_row_ != nullptr && chrome_row_->isVisible();
}

void CompilationLayerPanel::rebuild_rows() {
    while (QLayoutItem* item = reference_box_->takeAt(0)) {
        delete item->widget();
        delete item;
    }
    if (rows_.isEmpty()) {
        auto* empty = new QLabel(
            QStringLiteral("暂无参考图层 — 叠加后经此处调透明度"),
            reference_box_->parentWidget());
        empty->setObjectName(QStringLiteral("CompilationRefEmpty"));
        empty->setWordWrap(true);
        reference_box_->addWidget(empty);
        return;
    }
    const bool sliders = mode_ == Mode::Compilation;
    for (const auto& row : rows_) {
        auto* line = new QWidget(reference_box_->parentWidget());
        auto* hbox = new QHBoxLayout(line);
        hbox->setContentsMargins(0, 0, 0, 0);
        hbox->setSpacing(4);
        auto* check = new QCheckBox(row.label, line);
        check->setChecked(row.visible);
        check->setToolTip(row.layer_id);
        hbox->addWidget(check);
        const QString id = row.layer_id;
        connect(check, &QCheckBox::toggled, this,
                [this, id](bool on) {
                    emit reference_visibility_changed(id, on);
                });
        if (sliders) {
            hbox->addStretch();
            auto* slider = new QSlider(Qt::Horizontal, line);
            slider->setRange(0, 100);
            slider->setValue(row.opacity_pct);
            slider->setFixedWidth(80);
            hbox->addWidget(slider);
            auto* pct = new QLabel(
                QStringLiteral("%1%").arg(row.opacity_pct), line);
            pct->setFixedWidth(34);
            hbox->addWidget(pct);
            connect(slider, &QSlider::valueChanged, this,
                    [this, id, pct](int v) {
                        pct->setText(QStringLiteral("%1%").arg(v));
                        emit reference_opacity_changed(id, v);
                    });
        }
        reference_box_->addWidget(line);
    }
}

}  // namespace pwb::app
