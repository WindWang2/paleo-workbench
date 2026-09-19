#include "pwb/ui_pages_mapedit/map_topology_issue_panel.hpp"

#include "pwb/ui_widgets/object_table.hpp"
#include "pwb/ui_widgets/states.hpp"

#include <QLabel>
#include <QResizeEvent>
#include <QVBoxLayout>

namespace pwb::ui_pages_mapedit {

// --- TopologyCellProxy --------------------------------------------------------

QString TopologyCellProxy::text() const {
    const QVariant value =
        model_->data(model_->index(row_, column_));
    return value.isNull() ? QString() : value.toString();
}

// --- TopologyTableView --------------------------------------------------------

TopologyTableView::TopologyTableView(QWidget* parent) : QTableView(parent) {}

int TopologyTableView::rowCount() const {
    QAbstractItemModel* m = model();
    return m == nullptr ? 0 : m->rowCount();
}

TopologyCellProxy* TopologyTableView::item(int row, int column) {
    QAbstractItemModel* m = model();
    if (m == nullptr || row < 0 || column < 0 || row >= m->rowCount() ||
        column >= m->columnCount()) {
        return nullptr;
    }
    last_item_.emplace(m, row, column);
    return &*last_item_;
}

void TopologyTableView::setCurrentCell(int row, int column) {
    QAbstractItemModel* m = model();
    if (m == nullptr) {
        return;
    }
    setCurrentIndex(m->index(row, column));
}

void TopologyTableView::emit_item_double_clicked(const QModelIndex& index) {
    emit itemDoubleClicked(item(index.row(), index.column()));
}

// --- MapTopologyIssuePanel -----------------------------------------------------

MapTopologyIssuePanel::MapTopologyIssuePanel(QWidget* parent)
    : QWidget(parent) {
    auto* layout = new QVBoxLayout(this);
    summary = new QLabel(QStringLiteral("当前没有拓扑问题"), this);
    // Rows are packed as (key, issue-map) pairs — Python ``pair[1].get()``.
    const auto issue_of = [](const QVariant& row) {
        const auto pair = row.toList();
        return pair.size() >= 2 ? pair[1].toMap() : QVariantMap();
    };
    // Python ``str(issue.get(key, "") or "")``: falsy scalars (None, 0,
    // False, "") all collapse to "".
    const auto truthy_cell = [](const QVariant& v) -> QString {
        if (v.isNull()) {
            return {};
        }
        switch (v.typeId()) {
            case QMetaType::Bool:
                return v.toBool() ? QStringLiteral("True") : QString();
            case QMetaType::Int:
            case QMetaType::LongLong:
            case QMetaType::UInt:
            case QMetaType::ULongLong:
            case QMetaType::Double:
                return v.toDouble() == 0.0 ? QString() : v.toString();
            default:
                return v.toString();
        }
    };
    model_ = new ui_widgets::ObjectTableModel(
        {ui_widgets::ColumnSpec{
             QStringLiteral("feature_id"), QStringLiteral("要素"),
             [issue_of, truthy_cell](const QVariant& row) {
                 return truthy_cell(
                     issue_of(row).value(QStringLiteral("feature_id")));
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("message"), QStringLiteral("问题"),
             [issue_of, truthy_cell](const QVariant& row) {
                 return truthy_cell(
                     issue_of(row).value(QStringLiteral("message")));
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("severity"), QStringLiteral("级别"),
             [issue_of, truthy_cell](const QVariant& row) {
                 return truthy_cell(
                     issue_of(row).value(QStringLiteral("severity")));
             }}},
        [](const QVariant& row) {
            const auto pair = row.toList();
            return pair.isEmpty() ? QString() : pair.first().toString();
        },
        this);
    table = new TopologyTableView(this);
    table->setModel(model_);
    ui_widgets::bind_table_defaults(table);
    layout->addWidget(summary);
    layout->addWidget(table);

    empty_state_ = new ui_widgets::PwbEmptyState(
        QStringLiteral("未发现拓扑问题"),
        QStringLiteral("图幅拓扑检查通过。"), QStringLiteral("inbox.svg"),
        nullptr, this);
    empty_state_->setAttribute(Qt::WA_TransparentForMouseEvents);
    empty_state_->setParent(table);
    empty_state_->hide();
    connect(model_, &QAbstractItemModel::modelReset, this,
            [this]() { update_empty_state(); });
    connect(model_, &QAbstractItemModel::rowsInserted, this,
            [this](const QModelIndex&, int, int) { update_empty_state(); });
    connect(model_, &QAbstractItemModel::rowsRemoved, this,
            [this](const QModelIndex&, int, int) { update_empty_state(); });

    connect(table, &QTableView::activated, this,
            [this](const QModelIndex& index) { on_row_activated(index); });
    connect(table, &QTableView::doubleClicked, table,
            [this](const QModelIndex& index) {
                table->emit_item_double_clicked(index);
            });
    connect(table, &TopologyTableView::itemDoubleClicked, this,
            [this](TopologyCellProxy* item) {
                on_item_double_clicked(item);
            });
    update_empty_state();
}

void MapTopologyIssuePanel::on_item_double_clicked(
    TopologyCellProxy* item) {
    if (item != nullptr) {
        on_row_activated(model_->index(item->row(), item->column()));
    }
}

void MapTopologyIssuePanel::set_issues(
    const std::vector<QVariantMap>& issues) {
    issues_ = issues;
    summary->setText(QStringLiteral("拓扑问题：%1").arg(issues.size()));
    // 行对象包一层 (稳定键, issue)：issue dict 无业务 id，键由确定性
    // 序号+要素 id 构成，重复 set_issues 走 set_rows 差分路径。
    std::vector<QVariant> rows;
    rows.reserve(issues_.size());
    int i = 0;
    for (const auto& issue : issues_) {
        const QString key =
            QStringLiteral("%1:%2")
                .arg(i++)
                .arg(issue.value(QStringLiteral("feature_id")).toString());
        rows.push_back(QVariantList{key, issue});
    }
    model_->set_rows(rows);
}

void MapTopologyIssuePanel::on_row_activated(const QModelIndex& index) {
    // Double-click / Enter on a row asks to locate its feature. The row
    // OBJECT is read through the model — a sorted view reorders display
    // rows, so issues_[row] would locate the wrong feature.
    const QVariant row = model_->row_at(index.row());
    const auto pair = row.toList();
    if (pair.size() < 2) {
        return;
    }
    const QString feature_id =
        pair[1].toMap().value(QStringLiteral("feature_id")).toString();
    if (!feature_id.isEmpty()) {
        emit locate_requested(feature_id);
    }
}

void MapTopologyIssuePanel::resizeEvent(QResizeEvent* event) {
    QWidget::resizeEvent(event);
    if (empty_state_->isVisible()) {
        empty_state_->setGeometry(table->viewport()->rect());
    }
}

void MapTopologyIssuePanel::update_empty_state() {
    if (model_->rowCount() == 0) {
        empty_state_->setGeometry(table->viewport()->rect());
        empty_state_->show();
        empty_state_->raise();
    } else {
        empty_state_->hide();
    }
}

}  // namespace pwb::ui_pages_mapedit
