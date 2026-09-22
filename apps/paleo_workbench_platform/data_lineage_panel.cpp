#include "data_lineage_panel.hpp"

#include <QHeaderView>
#include <QLabel>
#include <QTabWidget>
#include <QTableWidget>
#include <QVBoxLayout>

#include "app_context.hpp"
#include "closure_data_workspace.hpp"

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/ui_pages_data/qt/asset_selection_bus.hpp>

namespace pwb::app {

namespace {

using pwb::ui_pages_data::AssetRow;

QStringList kColumns = {
    QStringLiteral("深度"), QStringLiteral("资产"),
    QStringLiteral("阶段"),  QStringLiteral("版本"),
    QStringLiteral("路径"),  QStringLiteral("运行")};

void setup_table(QTableWidget* table) {
    table->setColumnCount(kColumns.size());
    table->setHorizontalHeaderLabels(kColumns);
    table->verticalHeader()->setVisible(false);
    table->setEditTriggers(QTableWidget::NoEditTriggers);
    table->setSelectionBehavior(QTableWidget::SelectRows);
    table->setAlternatingRowColors(true);
}

#if defined(PWB_WITH_V14_DATA_LINEAGE)
// Resolve the selected asset's catalog version id from the LIVE store
// snapshot (real current_version_id — absent means the asset has no
// current version, an honest empty state, never fabricated).
std::optional<std::string> resolve_version_id(AppContext* context,
                                              const AssetRow& asset) {
    const auto store =
        context != nullptr ? context->projectStore() : nullptr;
    if (store == nullptr) return std::nullopt;
    const auto snapshot = store->snapshot();
    if (!snapshot.is_ok()) return std::nullopt;
    for (const auto& entry : snapshot.value().catalog_assets) {
        if (entry.id.str() == asset.view.id &&
            entry.current_version_id.has_value()) {
            return entry.current_version_id->str();
        }
    }
    return std::nullopt;
}
#endif

}  // namespace

DataLineagePanel::DataLineagePanel(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("DataLineagePanel"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(4, 4, 4, 4);
    layout->setSpacing(4);
    header_ = new QLabel(QStringLiteral("未选择资产"), this);
    header_->setObjectName(QStringLiteral("DataLineageHeader"));
    header_->setWordWrap(true);
    layout->addWidget(header_);

    tabs_ = new QTabWidget(this);
    tabs_->setObjectName(QStringLiteral("DataLineageTabs"));
    history_ = new QTableWidget(tabs_);
    history_->setObjectName(QStringLiteral("DataLineageHistory"));
    setup_table(history_);
    lineage_ = new QTableWidget(tabs_);
    lineage_->setObjectName(QStringLiteral("DataLineageRelations"));
    setup_table(lineage_);
    tabs_->addTab(history_, QStringLiteral("版本历史"));
    tabs_->addTab(lineage_, QStringLiteral("来源关系"));
    layout->addWidget(tabs_, 1);
}

void DataLineagePanel::set_context(AppContext* context) {
    context_ = context;
    refresh();
}

void DataLineagePanel::bind_selection_bus(
    pwb::ui_pages_data::qt::AssetSelectionBus* bus) {
    if (bus_ != nullptr) {
        disconnect(bus_, nullptr, this, nullptr);
    }
    bus_ = bus;
    if (bus_ != nullptr) {
        connect(bus_, &pwb::ui_pages_data::qt::AssetSelectionBus::
                          current_asset_changed,
                this, [this](const std::optional<AssetRow>&) { refresh(); });
    }
    refresh();
}

void DataLineagePanel::refresh() {
    const AssetRow* selected = nullptr;
    if (bus_ != nullptr && bus_->current_asset().has_value()) {
        selected = &*bus_->current_asset();
    }
    if (selected == nullptr) {
        header_->setText(QStringLiteral("未选择资产 — 在资产表中选择后显示版本历史与来源关系"));
        history_->setRowCount(0);
        lineage_->setRowCount(0);
        return;
    }
    const QString label = QStringLiteral("%1（%2）")
                              .arg(QString::fromStdString(selected->view.name),
                                   QString::fromStdString(selected->view.id));
    header_->setText(QStringLiteral("选中资产：%1").arg(label));
    fill_table(history_, QStringLiteral("ancestors"), label);
    fill_table(lineage_, QStringLiteral("descendants"), label);
}

void DataLineagePanel::fill_table(QTableWidget* table,
                                  const QString& direction,
                                  const QString& asset_label) {
    table->setRowCount(0);
#if defined(PWB_WITH_V14_DATA_LINEAGE)
    const auto store =
        context_ != nullptr ? context_->projectStore() : nullptr;
    if (store == nullptr) {
        emit status_message(QStringLiteral("血缘查询：请先打开工程"));
        return;
    }
    const auto asset =
        bus_ != nullptr ? bus_->current_asset() : std::nullopt;
    if (!asset.has_value()) return;
    const auto version_id = resolve_version_id(context_, *asset);
    if (!version_id.has_value()) {
        emit status_message(QStringLiteral("「%1」暂无目录版本记录")
                                .arg(asset_label));
        return;
    }
    const v14_lineage::LineageQueryResult result = v14_lineage::lineage_rows(
        store->project_file(), *version_id, direction.toStdString());
    if (!result.ok) {
        emit status_message(
            QStringLiteral("血缘查询失败：%1")
                .arg(QString::fromStdString(result.error)));
        return;
    }
    table->setRowCount(static_cast<int>(result.rows.size()));
    for (int i = 0; i < static_cast<int>(result.rows.size()); ++i) {
        const auto& row = result.rows[static_cast<size_t>(i)];
        const QString texts[] = {
            QString::number(row.depth),
            QString::fromStdString(row.asset_name.empty() ? row.asset_id
                                                          : row.asset_name),
            QString::fromStdString(row.stage),
            QStringLiteral("v%1").arg(row.version_number),
            QString::fromStdString(row.path),
            QString::fromStdString(row.run_id),
        };
        for (int col = 0; col < kColumns.size(); ++col) {
            table->setItem(i, col, new QTableWidgetItem(texts[col]));
        }
    }
    if (result.truncated) {
        emit status_message(QStringLiteral("血缘链过长，已截断显示"));
    }
#else
    (void)table; (void)direction; (void)asset_label;
    emit status_message(
        QStringLiteral("血缘查询切片未参与本次构建（V14-DATA-LINEAGE）"));
#endif
}

}  // namespace pwb::app
