#pragma once

// UI-02 — FaciesBrushContext + FaciesPaletteWidget + facies_color,
// ported from paleo_workbench/ui/components/facies_palette_widget.py and
// paleo_workbench/ui/workstation/facies_selector.py (FaciesBrushContext).
//
// Single sources of truth (D11): taxonomy = core::FaciesTaxonomy (project
// override wins), color = core::facies_category_color (same as the
// categorized renderer), pattern = core::facies_patterns. Equip state is
// written to the host-injected FaciesBrushContext — this widget keeps no
// private equip state.

#include <QHash>
#include <QLabel>
#include <QObject>
#include <QScrollArea>
#include <QToolButton>
#include <QVariantMap>
#include <QVBoxLayout>
#include <QWidget>

#include <vector>

#include "pwb/ui_widgets/core/facies_taxonomy.hpp"

namespace pwb::ui_widgets {

//: 常用相带快捷键位数（1-9 数字键装备；00-decisions D6/D11）。
inline constexpr int kFavoriteKeyCount = 9;

// 相名 → 分类渲染器同款颜色（单一取色真源，D11 三处一致）：
// feature color > geological_symbols known fill > md5-hash fallback.
QString facies_color(const QString& name,
                     const QString& feature_color = QString());

// 当前相带画刷（M2）：装备四元组 = 词表选择 {facies, sub_facies,
// micro_facies} + 派生 level；幂等装备不重复广播（杜绝回环放大）。
class FaciesBrushContext : public QObject {
    Q_OBJECT
public:
    explicit FaciesBrushContext(QObject* parent = nullptr);

    bool is_armed() const { return armed_; }

    // Selection map with all three level keys (missing -> "").
    QVariantMap selection() const;

    // Idempotent equip: same-value re-equips do not re-broadcast.
    void equip(const QVariantMap& selection);
    void clear();

signals:
    void equipped_changed(const QVariantMap& selection);

private:
    QVariantMap selection_;
    bool armed_ = false;
};

// Immersive facies palette: facies sections + sub-facies swatch grid +
// eyedropper toggle + equip bar.
class FaciesPaletteWidget : public QWidget {
    Q_OBJECT
public:
    explicit FaciesPaletteWidget(QWidget* parent = nullptr);

    void set_taxonomy(const core::FaciesTaxonomy& taxonomy);

    // Inject the equip context (FaciesBrushContext — read + equip writes).
    void set_brush(FaciesBrushContext* brush);

    // Favorites (first 9 swatches, 1-9 hotkeys; D6/D11).
    QList<QVariantMap> favorites() const;

    void equip_by_selection(const QVariantMap& selection);
    void equip_by_index(int index);

    // Counts for tests/visual regression.
    int section_count() const;
    int swatch_count() const { return int(swatches_.size()); }

    // External (eyedropper controller) re-sync of the button state
    // (suppresses re-broadcast).
    void set_eyedropper_active(bool active);

    QToolButton* eyedropper_button = nullptr;  // public per Python surface
    QLabel* equip_label = nullptr;

signals:
    void eyedropper_toggled(bool checked);

private:
    struct Swatch {
        QToolButton* button;
        QVariantMap selection;
        QString top;
        QString sub;
    };

    void rebuild();
    void refresh_key_hints();
    void on_equipped(const QVariantMap& selection);
    static QPair<QString, QString> swatch_key(const Swatch& entry);
    static QPair<QString, QString> current_swatch_key(
        const QVariantMap& selection);

    core::FaciesTaxonomy taxonomy_;
    bool has_taxonomy_ = false;
    FaciesBrushContext* brush_ = nullptr;  // not owned
    std::vector<Swatch> swatches_;
    std::vector<int> favorites_;
    QLabel* summary_label_ = nullptr;
    QScrollArea* scroll_ = nullptr;
    QWidget* host_ = nullptr;
    QVBoxLayout* host_layout_ = nullptr;
};

}  // namespace pwb::ui_widgets
