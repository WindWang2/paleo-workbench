#include "pwb/ui_widgets/facies_palette_widget.hpp"

#include "pwb/ui_widgets/core/facies_patterns.hpp"
#include "pwb/ui_widgets/ui_context.hpp"

#include <QCryptographicHash>
#include <QFrame>
#include <QGridLayout>
#include <QHBoxLayout>
#include <QPainter>
#include <QPixmap>
#include <QSizePolicy>

namespace pwb::ui_widgets {

// Compile-time source root (same idiom as platform_services); when the
// definition is absent the pattern dir simply does not exist -> honest
// no-pattern, matching the Python fallback.
#ifndef PWB_SOURCE_DIR
#define PWB_SOURCE_DIR ""
#endif

namespace {

// Pattern asset dir: repo-relative geo-viz-engine location (same idiom as
// the Python FACIES_PATTERN_DIR); missing dir -> honest no-pattern.
QString facies_pattern_dir() {
    return QStringLiteral(PWB_SOURCE_DIR) +
           QStringLiteral(
               "/geo-viz-engine/packages/geoviz_well_log/geoviz_well_log"
               "/assets/patterns/facies");
}

QString qt_md5_hex(const std::string& utf8) {
    return QString::fromLatin1(QCryptographicHash::hash(
                                   QByteArray::fromStdString(utf8),
                                   QCryptographicHash::Md5)
                                   .toHex());
}

// 纯色底 + 描边调色板缩略图（_swatch_icon parity; CANVAS_INK border）。
QIcon swatch_icon(const QString& color_hex) {
    QPixmap pixmap(18, 18);
    pixmap.fill(Qt::transparent);
    QPainter painter(&pixmap);
    painter.fillRect(1, 1, 16, 16, QColor(color_hex));
    painter.setPen(QColor(palette_token("CANVAS_INK")));
    painter.drawRect(0, 0, 17, 17);
    painter.end();
    return QIcon(pixmap);
}

QString trim_qs(const QString& s) { return s.trimmed(); }

}  // namespace

QString facies_color(const QString& name, const QString& feature_color) {
    return QString::fromStdString(core::facies_category_color(
        name.toStdString(), feature_color.toStdString(),
        [](const std::string& s) { return qt_md5_hex(s).toStdString(); }));
}

// ---------------------------------------------------------------------------
// FaciesBrushContext
// ---------------------------------------------------------------------------

FaciesBrushContext::FaciesBrushContext(QObject* parent) : QObject(parent) {}

QVariantMap FaciesBrushContext::selection() const {
    QVariantMap values = selection_;
    if (!values.contains("facies")) values.insert("facies", "");
    if (!values.contains("sub_facies")) values.insert("sub_facies", "");
    if (!values.contains("micro_facies")) values.insert("micro_facies", "");
    return values;
}

void FaciesBrushContext::equip(const QVariantMap& selection) {
    QVariantMap values = this->selection();
    auto field = [&selection](const char* key) {
        const QVariant v = selection.value(QString::fromLatin1(key));
        return v.isValid() && !v.isNull() ? v.toString() : QString();
    };
    values.insert("facies", field("facies"));
    values.insert("sub_facies", field("sub_facies"));
    values.insert("micro_facies", field("micro_facies"));
    values.remove("level");
    const std::map<std::string, std::string> sel = {
        {"facies", values.value("facies").toString().toStdString()},
        {"sub_facies", values.value("sub_facies").toString().toStdString()},
        {"micro_facies",
         values.value("micro_facies").toString().toStdString()},
    };
    values.insert("level", QString::fromStdString(
                               core::FaciesTaxonomy::selection_level(sel)));
    if (armed_ && values == selection_) return;
    selection_ = values;
    armed_ = true;
    emit equipped_changed(selection_);
}

void FaciesBrushContext::clear() {
    if (!armed_) return;
    selection_.clear();
    armed_ = false;
    emit equipped_changed(QVariantMap());
}

// ---------------------------------------------------------------------------
// FaciesPaletteWidget
// ---------------------------------------------------------------------------

FaciesPaletteWidget::FaciesPaletteWidget(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("FaciesPalette"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(6, 6, 6, 6);
    layout->setSpacing(6);

    auto* top_row = new QHBoxLayout();
    top_row->setSpacing(4);
    eyedropper_button = new QToolButton(this);
    eyedropper_button->setObjectName(QStringLiteral("FaciesEyedropperButton"));
    eyedropper_button->setText(QStringLiteral("吸色管"));
    eyedropper_button->setToolTip(QStringLiteral(
        "激活后在地图上点击已有相带，一键吸取其相带属性/颜色/花纹"));
    eyedropper_button->setCheckable(true);
    connect(eyedropper_button, &QToolButton::toggled, this,
            &FaciesPaletteWidget::eyedropper_toggled);
    summary_label_ = new QLabel(QStringLiteral("—"), this);
    summary_label_->setObjectName(QStringLiteral("FaciesPaletteSummary"));
    top_row->addWidget(eyedropper_button);
    top_row->addStretch(1);
    top_row->addWidget(summary_label_);
    layout->addLayout(top_row);

    scroll_ = new QScrollArea(this);
    scroll_->setWidgetResizable(true);
    scroll_->setFrameShape(QFrame::NoFrame);
    host_ = new QWidget(scroll_);
    host_layout_ = new QVBoxLayout(host_);
    host_layout_->setContentsMargins(0, 0, 0, 0);
    host_layout_->setSpacing(8);
    host_layout_->addStretch(1);
    scroll_->setWidget(host_);
    layout->addWidget(scroll_, 1);

    equip_label = new QLabel(QStringLiteral("未装备 — 点击格装备画刷"), this);
    equip_label->setObjectName(QStringLiteral("FaciesEquipLabel"));
    layout->addWidget(equip_label);
}

void FaciesPaletteWidget::set_taxonomy(
    const core::FaciesTaxonomy& taxonomy) {
    taxonomy_ = taxonomy;
    has_taxonomy_ = true;
    rebuild();
}

void FaciesPaletteWidget::set_brush(FaciesBrushContext* brush) {
    if (brush_ != nullptr) {
        disconnect(brush_, &FaciesBrushContext::equipped_changed, this,
                   nullptr);
    }
    brush_ = brush;
    if (brush_ != nullptr) {
        connect(brush_, &FaciesBrushContext::equipped_changed, this,
                &FaciesPaletteWidget::on_equipped);
    }
    on_equipped(brush_ != nullptr ? brush_->selection() : QVariantMap());
}

void FaciesPaletteWidget::rebuild() {
    while (host_layout_->count() > 1) {
        QLayoutItem* item = host_layout_->takeAt(0);
        if (item->widget() != nullptr) item->widget()->deleteLater();
        delete item;
    }
    swatches_.clear();
    favorites_.clear();
    if (!has_taxonomy_) return;

    for (const std::string& top_std : taxonomy_.names("facies")) {
        const QString top = QString::fromStdString(top_std);
        auto* section = new QFrame(host_);
        section->setObjectName(QStringLiteral("FaciesPaletteSection"));
        section->setProperty("faciesName", top);
        auto* section_layout = new QVBoxLayout(section);
        section_layout->setContentsMargins(4, 4, 4, 4);
        section_layout->setSpacing(4);
        auto* header = new QHBoxLayout();
        auto* header_label = new QLabel(top, section);
        header_label->setObjectName(
            QStringLiteral("FaciesPaletteSectionHeader"));
        const auto pattern = core::pattern_path_for_facies(
            top_std, facies_pattern_dir().toStdString());
        if (pattern) {
            auto* header_icon = new QLabel(section);
            header_icon->setPixmap(
                QIcon(QString::fromStdString(*pattern)).pixmap(QSize(20, 20)));
            header->addWidget(header_icon);
        }
        auto* color_chip = new QLabel(section);
        QPixmap chip(12, 12);
        chip.fill(QColor(facies_color(top)));
        color_chip->setPixmap(chip);
        header->addWidget(color_chip);
        header->addWidget(header_label);
        header->addStretch(1);
        section_layout->addLayout(header);

        auto* grid = new QGridLayout();
        grid->setSpacing(3);
        int column = 0;
        for (const std::string& sub_std :
             taxonomy_.names("sub_facies", {top_std})) {
            const QString sub = QString::fromStdString(sub_std);
            QVariantMap selection;
            selection.insert("facies", top);
            selection.insert("sub_facies", sub);
            selection.insert("micro_facies", "");
            auto* button = new QToolButton(section);
            button->setObjectName(QStringLiteral("FaciesSwatchButton"));
            button->setCheckable(true);
            button->setText(sub);
            button->setToolTip(top + " / " + sub);
            button->setIcon(swatch_icon(facies_color(top)));
            button->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
            button->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
            connect(button, &QToolButton::clicked, this,
                    [this, selection]() { equip_by_selection(selection); });
            const int index = int(swatches_.size());
            swatches_.push_back(Swatch{button, selection, top, sub});
            // 冻结语义：行号 = favorites 全局长度 // 3（跨分区共享；首 9 格
            // 之后恒为 3 —— 保留 Python 原状，见 ledger P-QUIRK）。
            if (int(favorites_.size()) < kFavoriteKeyCount) {
                favorites_.push_back(index);
            }
            grid->addWidget(button, int(favorites_.size()) / 3, column);
            column = (column + 1) % 3;
        }
        section_layout->addLayout(grid);
        host_layout_->insertWidget(host_layout_->count() - 1, section);
    }
    refresh_key_hints();
    const auto [n_f, n_s, n_m] = taxonomy_.counts();
    summary_label_->setText(QStringLiteral("相 %1 · 亚相 %2 · 微相 %3")
                                .arg(n_f)
                                .arg(n_s)
                                .arg(n_m));
}

void FaciesPaletteWidget::refresh_key_hints() {
    int index = 1;
    for (const int fav : favorites_) {
        swatches_[fav].button->setText(
            QStringLiteral("%1 %2").arg(index).arg(swatches_[fav].sub));
        ++index;
    }
}

QList<QVariantMap> FaciesPaletteWidget::favorites() const {
    QList<QVariantMap> out;
    for (const int fav : favorites_) {
        const Swatch& entry = swatches_[fav];
        QVariantMap copy = entry.selection;
        copy.insert("label", entry.top + " / " + entry.sub);
        out.append(copy);
    }
    return out;
}

void FaciesPaletteWidget::equip_by_selection(const QVariantMap& selection) {
    if (brush_ != nullptr) brush_->equip(selection);
}

void FaciesPaletteWidget::equip_by_index(int index) {
    if (index >= 0 && index < int(favorites_.size())) {
        equip_by_selection(swatches_[favorites_[index]].selection);
    }
}

QPair<QString, QString> FaciesPaletteWidget::swatch_key(const Swatch& entry) {
    return {entry.top, entry.sub};
}

QPair<QString, QString> FaciesPaletteWidget::current_swatch_key(
    const QVariantMap& selection) {
    return {selection.value("facies").toString(),
            selection.value("sub_facies").toString()};
}

void FaciesPaletteWidget::on_equipped(const QVariantMap& selection) {
    const bool armed = !selection.value("facies").toString().isEmpty();
    if (armed) {
        QStringList parts;
        for (const char* key : {"facies", "sub_facies", "micro_facies"}) {
            const QString v = selection.value(QString::fromLatin1(key)).toString();
            if (!v.isEmpty()) parts.append(v);
        }
        equip_label->setText(QStringLiteral("装备：") + parts.join(" / "));
    } else {
        equip_label->setText(QStringLiteral("未装备 — 点击格装备画刷"));
    }
    const auto current = current_swatch_key(selection);
    for (const Swatch& entry : swatches_) {
        const bool checked = armed && swatch_key(entry) == current;
        entry.button->setChecked(checked);
    }
}

int FaciesPaletteWidget::section_count() const {
    int count = 0;
    for (int i = 0; i < host_layout_->count(); ++i) {
        QWidget* w = host_layout_->itemAt(i)->widget();
        if (w != nullptr && w->objectName() == "FaciesPaletteSection") ++count;
    }
    return count;
}

void FaciesPaletteWidget::set_eyedropper_active(bool active) {
    eyedropper_button->blockSignals(true);
    eyedropper_button->setChecked(active);
    eyedropper_button->blockSignals(false);
}

}  // namespace pwb::ui_widgets
