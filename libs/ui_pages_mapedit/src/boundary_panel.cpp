#include "pwb/ui_pages_mapedit/boundary_panel.hpp"

#include "pwb/ui_shell/style_registry.hpp"

#include <QComboBox>
#include <QDoubleSpinBox>
#include <QLabel>
#include <QPushButton>
#include <QVBoxLayout>

namespace pwb::ui_pages_mapedit {
namespace {

QString pal(const char* key) {
    const auto& p = ui_shell::style_palette();
    const auto it = p.find(key);
    return it != p.end() ? QString::fromStdString(it->second) : QString();
}

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

// _field_label_sheet(): field-label text style.
QString field_label_sheet() {
    return QStringLiteral(
               "color: %1; font-size: %2;"
               " border: none; background: transparent;")
        .arg(pal("TEXT_SECONDARY"), pal("FONT_SIZE_STATUS"));
}

// _field_control_sheet(selector): boxed control style.
QString field_control_sheet(const QString& selector) {
    return QStringLiteral(
               "%1 { background: %2; border: 1px solid %3;"
               " border-radius: %4px; padding: 2px 6px; }")
        .arg(selector, pal("BG_SIDEBAR"), pal("BORDER"),
             pal("RADIUS_BUTTON"));
}

}  // namespace

BoundaryPanel::BoundaryPanel(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("BoundaryPanel"));
    // 侧栏宽度：保底 220，窄屏下可收缩、宽屏最多 1.6 倍有界弹性
    setMinimumWidth(220);
    setMaximumWidth(static_cast<int>(220 * 1.6));

    auto* layout = new QVBoxLayout(this);
    const int pad = tok_int("PANEL_PADDING", 12);
    layout->setContentsMargins(pad, pad, pad, pad);
    layout->setSpacing(tok_int("SPACE_2", 8));

    title_label = new QLabel(QStringLiteral("初始岩相边界制备"), this);
    title_label->setObjectName(QStringLiteral("MapDockTitle"));
    layout->addWidget(title_label);

    // Threshold spin (0.0–1.0, step 0.05, default 0.55, 2 decimals)
    threshold_label = new QLabel(QStringLiteral("概率阈值"), this);
    ui_shell::style_bind(threshold_label, &field_label_sheet);
    layout->addWidget(threshold_label);
    threshold_spin = new QDoubleSpinBox(this);
    threshold_spin->setRange(0.0, 1.0);
    threshold_spin->setSingleStep(0.05);
    threshold_spin->setDecimals(2);
    threshold_spin->setValue(0.55);
    ui_shell::style_bind(threshold_spin, [] {
        return field_control_sheet(QStringLiteral("QDoubleSpinBox"));
    });
    layout->addWidget(threshold_spin);

    // Smoothing combo (SMOOTHING_LEVELS, default 中)
    smoothing_label = new QLabel(QStringLiteral("边界平滑强度"), this);
    ui_shell::style_bind(smoothing_label, &field_label_sheet);
    layout->addWidget(smoothing_label);
    smoothing_combo = new QComboBox(this);
    smoothing_combo->addItems(smoothing_levels());
    smoothing_combo->setCurrentText(QStringLiteral("中"));
    ui_shell::style_bind(smoothing_combo, [] {
        return field_control_sheet(QStringLiteral("QComboBox"));
    });
    layout->addWidget(smoothing_combo);

    // Minimum area spin (0.0–10.0, step 0.1, default 0.5, 1 decimal, " km²")
    area_label = new QLabel(QStringLiteral("最小图斑面积 (km²)"), this);
    ui_shell::style_bind(area_label, &field_label_sheet);
    layout->addWidget(area_label);
    area_spin = new QDoubleSpinBox(this);
    area_spin->setRange(0.0, 10.0);
    area_spin->setSingleStep(0.1);
    area_spin->setDecimals(1);
    area_spin->setValue(0.5);
    area_spin->setSuffix(QStringLiteral(" km²"));
    ui_shell::style_bind(area_spin, [] {
        return field_control_sheet(QStringLiteral("QDoubleSpinBox"));
    });
    layout->addWidget(area_spin);

    // Facies placeholder label
    facies_label =
        new QLabel(QStringLiteral("三角洲前缘砂体 · 分流间湾泥"), this);
    ui_shell::style_bind(facies_label, &field_label_sheet);
    layout->addWidget(facies_label);

    layout->addStretch();

    generate_btn =
        new QPushButton(QStringLiteral("生成初始边界并送入编图"), this);
    generate_btn->setObjectName(QStringLiteral("PrimaryButton"));
    generate_btn->setToolTip(QStringLiteral("生成初始相带边界"));
    layout->addWidget(generate_btn);
}

}  // namespace pwb::ui_pages_mapedit
