#include "pwb/ui_pages_mapedit/map_factor_shelf.hpp"

#include "pwb/ui_data_core/json_util.hpp"
#include "pwb/ui_pages_mapedit/factor_preview_grid.hpp"
#include "pwb/ui_pages_mapedit/map_icons.hpp"
#include "pwb/ui_shell/style_registry.hpp"

#include <QHBoxLayout>
#include <QPushButton>
#include <QVBoxLayout>

namespace pwb::ui_pages_mapedit {
namespace {

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

}  // namespace

MapFactorShelf::MapFactorShelf(QWidget* parent) : QWidget(parent) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(tok_int("SPACE_2", 8));

    auto* actions = new QHBoxLayout();
    actions->setContentsMargins(tok_int("SPACE_2", 8), tok_int("SPACE_1", 4),
                                tok_int("SPACE_2", 8), 0);

    create_factor_map_btn =
        new QPushButton(QStringLiteral("新建单因素地质编图"), this);
    create_factor_map_btn->setObjectName(QStringLiteral("PrimaryButton"));
    ui_shell::style_track_control_height(create_factor_map_btn);
    create_factor_map_btn->setToolTip(QStringLiteral(
        "从井点属性执行空间克里金插值，生成包含栅格、等值线及井位标注的 GIS 图件"));
    connect(create_factor_map_btn, &QPushButton::clicked, this,
            [this]() { emit create_factor_map_requested(); });
    actions->addWidget(create_factor_map_btn);

    contour_draft_btn = new QPushButton(
        panel_icon(QStringLiteral("btn-contour-draft")),
        QStringLiteral("从单因素生成等值线初稿"), this);
    contour_draft_btn->setObjectName(QStringLiteral("SecondaryButton"));
    ui_shell::style_track_control_height(contour_draft_btn);
    contour_draft_btn->setToolTip(QStringLiteral(
        "对已完成网格的单因素任务提取 ContourDraft 并写入当前工程图件"));
    connect(contour_draft_btn, &QPushButton::clicked, this,
            [this]() { emit contour_draft_requested(); });
    actions->addWidget(contour_draft_btn);

    fault_interpretation_btn =
        new QPushButton(QStringLiteral("断层约束→解释版本"), this);
    fault_interpretation_btn->setObjectName(QStringLiteral("SecondaryButton"));
    ui_shell::style_track_control_height(fault_interpretation_btn);
    fault_interpretation_btn->setToolTip(QStringLiteral(
        "把当前图件中断线/断层多段线提升为正式断层解释，保存为不可变解释版本（目录血缘）"));
    connect(fault_interpretation_btn, &QPushButton::clicked, this,
            [this]() { emit fault_interpretation_requested(); });
    actions->addWidget(fault_interpretation_btn);

    map_product_btn = new QPushButton(
        QStringLiteral("装配古地理成果 (MapProduct)"), this);
    map_product_btn->setObjectName(QStringLiteral("PrimaryButton"));
    ui_shell::style_track_control_height(map_product_btn);
    map_product_btn->setToolTip(QStringLiteral(
        "多因素 + 解释 + 组图 → 一个带完整血缘的 OUTPUT 成果版本（拒绝合成数据）"));
    connect(map_product_btn, &QPushButton::clicked, this,
            [this]() { emit map_product_requested(); });
    actions->addWidget(map_product_btn);
    actions->addStretch(1);
    layout->addLayout(actions);

    grid = new FactorPreviewGrid(this);
    connect(grid, &FactorPreviewGrid::card_clicked, this,
            [this](const domain::Json& task) { on_card_clicked(task); });
    layout->addWidget(grid, 1);
}

void MapFactorShelf::update_state(
    const std::vector<domain::Json>& tasks) {
    grid->update_state(tasks);
}

void MapFactorShelf::on_card_clicked(const domain::Json& task) {
    // Request the clicked factor card's output as a map overlay.
    // Python: str(outputs[0]) if outputs else str(task.id or "") — the
    // fallback engages only on an EMPTY list, never on a falsy element.
    QString overlay_id;
    const auto it = task.find("output_resource_ids");
    if (it != task.end() && it->is_array() && !it->empty()) {
        overlay_id = QString::fromStdString(
            ui_data_core::python_str(it->front()));
    } else {
        const auto iit = task.find("id");
        if (iit != task.end() && ui_data_core::json_truthy(*iit)) {
            overlay_id =
                QString::fromStdString(ui_data_core::python_str(*iit));
        }
    }
    if (!overlay_id.isEmpty()) {
        emit factor_overlay_requested(overlay_id);
    }
}

}  // namespace pwb::ui_pages_mapedit
