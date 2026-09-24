// UI-06 — DataDetailPanel shell (see qt/data_detail_panel.hpp).
#include <pwb/ui_pages_data/qt/data_detail_panel.hpp>

#include <QGridLayout>
#include <QLabel>
#include <QVBoxLayout>

#include <pwb/ui_pages_data/vocab.hpp>
#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_pages_data::qt {

namespace {

QString pal(const char* key) {
    const auto p = ui_shell::style_palette();
    const auto it = p.find(key);
    return it != p.end() ? QString::fromStdString(it->second) : QString();
}

}  // namespace

DataDetailPanel::DataDetailPanel(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("DataDetailPanel"));
    setMinimumWidth(240);
    ui_shell::style_bind(this, [] {
        return QStringLiteral(
                   "QFrame#DataDetailPanel { background: %1;"
                   " border: 1px solid %2; border-radius: 6px; }")
            .arg(pal("BG_SIDEBAR"), pal("BORDER"));
    });

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(12, 12, 12, 12);
    layout->setSpacing(12);

    // 稿 ws0 右列：面板标题恒为「数据属性」（文件名称是首行 kv），
    // 值对为两列网格（键灰、值主色）。
    title_ = new QLabel(QStringLiteral("数据属性"), this);
    ui_shell::style_bind(title_, [] {
        return QStringLiteral("color: %1; font-weight: 600;")
            .arg(pal("TEXT_PRIMARY"));
    });
    layout->addWidget(title_);

    grid_ = new QGridLayout();
    grid_->setHorizontalSpacing(8);
    grid_->setVerticalSpacing(4);
    grid_->setColumnStretch(1, 1);
    layout->addLayout(grid_);
    layout->addStretch();

    update_asset(std::nullopt);
}

void DataDetailPanel::update_asset(
    const std::optional<AssetRow>& asset) {
    clear_grid();

    if (!asset.has_value()) {
        auto* hint = new QLabel(
            QStringLiteral("从列表中选择一个数据、成果或文件"), this);
        hint->setWordWrap(true);
        ui_shell::style_bind(hint, [] {
            return QStringLiteral("color: %1;").arg(pal("TEXT_SECONDARY"));
        });
        grid_->addWidget(hint, 0, 0, 1, 2);
        return;
    }

    const AssetRow& row = *asset;
    const AssetView& v = row.view;
    const auto show = [](const std::string& s) {
        return s.empty() ? QStringLiteral("—")
                         : QString::fromStdString(s);
    };
    // 稿式键序：文件名称/数据类型/所属对象/层位/版本/深度范围/
    // 数据单位/数据来源/修改时间/文件大小/状态/描述。
    add_kv(QStringLiteral("文件名称"), show(v.name));
    add_kv(QStringLiteral("数据类型"),
           row.kind == AssetKind::Artifact
               ? QStringLiteral("成果")
               : QString::fromStdString(std::string(
                     resource_type_label(v.type))));
    add_kv(QStringLiteral("所属对象"), show(v.linked_label));
    add_kv(QStringLiteral("层位"), show(v.horizon_label));
    add_kv(QStringLiteral("版本"), show(v.version_label));
    // 深度范围/数据单位：目录未暴露逐资产字段 —— 诚实 "—"。
    add_kv(QStringLiteral("深度范围"), QStringLiteral("—"));
    add_kv(QStringLiteral("数据单位"), QStringLiteral("—"));
    add_kv(QStringLiteral("数据来源"), show(v.source_label));
    add_kv(QStringLiteral("修改时间"), show(v.modified_label));
    add_kv(QStringLiteral("文件大小"), show(v.size_label));
    add_kv(QStringLiteral("状态"), show(v.status));
    add_kv(QStringLiteral("描述"), show(v.description));
}

void DataDetailPanel::show_downstream_impact(
    const std::vector<std::tuple<std::string, std::string, std::string>>&
        rows) {
    if (rows.empty()) return;
    const int row_base = grid_->rowCount();
    auto* title = new QLabel(QStringLiteral("下游影响"), this);
    ui_shell::style_bind(title, [] {
        return QStringLiteral("color: %1; font-weight: 600;")
            .arg(pal("TEXT_PRIMARY"));
    });
    grid_->addWidget(title, row_base, 0, 1, 2);
    for (std::size_t i = 0; i < rows.size() && i < 20; ++i) {
        const auto& [label, state, state_label] = rows[i];
        auto* line = new QLabel(
            QStringLiteral("· %1 — %2")
                .arg(QString::fromStdString(label.empty() ? "?" : label),
                     QString::fromStdString(state_label)),
            this);
        line->setWordWrap(true);
        const bool stale = state == "STALE";
        ui_shell::style_bind(line, [stale] {
            return QStringLiteral("color: %1;")
                .arg(pal(stale ? "WARNING" : "TEXT_SECONDARY"));
        });
        grid_->addWidget(line, row_base + 1 + static_cast<int>(i), 0, 1, 2);
    }
}

void DataDetailPanel::add_kv(const QString& key, const QString& value) {
    const int row = grid_->rowCount();
    auto* k = new QLabel(key, this);
    ui_shell::style_bind(k, [] {
        return QStringLiteral("color: %1;").arg(pal("TEXT_SECONDARY"));
    });
    auto* val = new QLabel(value, this);
    val->setWordWrap(true);
    val->setTextInteractionFlags(
        Qt::TextInteractionFlag::TextSelectableByMouse);
    ui_shell::style_bind(val, [] {
        return QStringLiteral("color: %1;").arg(pal("TEXT_PRIMARY"));
    });
    grid_->addWidget(k, row, 0, Qt::AlignmentFlag::AlignTop);
    grid_->addWidget(val, row, 1, Qt::AlignmentFlag::AlignTop);
}

void DataDetailPanel::clear_grid() {
    while (grid_->count()) {
        QLayoutItem* child = grid_->takeAt(0);
        if (QWidget* widget = child->widget()) {
            widget->hide();
            widget->setParent(nullptr);
            widget->deleteLater();
        }
        delete child;
    }
}

}  // namespace pwb::ui_pages_data::qt
