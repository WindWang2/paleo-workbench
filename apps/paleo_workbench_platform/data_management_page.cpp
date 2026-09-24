// data_management_page — see the header for the contract.

#include "data_management_page.hpp"

#include <QHeaderView>
#include <QLabel>
#include <QPushButton>
#include <QSplitter>
#include <QStandardItemModel>
#include <QTextBrowser>
#include <QToolButton>
#include <QTreeView>
#include <QVBoxLayout>

namespace pwb::app {

DataManagementPage::DataManagementPage(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("DataManagementPage"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);

    auto* splitter = new QSplitter(this);
    splitter->setObjectName(QStringLiteral("DataPageSplitter"));

    // ---- 左栏：数据列表 ----------------------------------------------------
    auto* left = new QWidget(splitter);
    auto* left_layout = new QVBoxLayout(left);
    left_layout->setContentsMargins(6, 6, 6, 6);
    left_layout->setSpacing(4);
    auto* header = new QHBoxLayout();
    auto* title = new QLabel(tr("数据列表"), left);
    title->setObjectName(QStringLiteral("DataListTitle"));
    header->addWidget(title, 1);
    auto* refresh = new QToolButton(left);
    refresh->setText(tr("刷新"));
    refresh->setAutoRaise(true);
    connect(refresh, &QToolButton::clicked, this,
            &DataManagementPage::refresh_requested);
    header->addWidget(refresh);
    left_layout->addLayout(header);

    model_ = new QStandardItemModel(this);
    model_->setHorizontalHeaderLabels(
        {tr("名称"), tr("类型"), tr("位置")});
    list_ = new QTreeView(left);
    list_->setObjectName(QStringLiteral("DataList"));
    list_->setModel(model_);
    list_->setRootIsDecorated(false);
    list_->setUniformRowHeights(true);
    list_->setEditTriggers(QAbstractItemView::NoEditTriggers);
    list_->setSelectionBehavior(QAbstractItemView::SelectRows);
    list_->setSelectionMode(QAbstractItemView::SingleSelection);
    list_->header()->setStretchLastSection(true);
    left_layout->addWidget(list_, 1);
    splitter->addWidget(left);

    // ---- 右栏：信息展示 ----------------------------------------------------
    auto* right = new QWidget(splitter);
    auto* right_layout = new QVBoxLayout(right);
    right_layout->setContentsMargins(6, 6, 6, 6);
    right_layout->setSpacing(4);
    auto* info_title = new QLabel(tr("信息"), right);
    info_title->setObjectName(QStringLiteral("DataInfoTitle"));
    right_layout->addWidget(info_title);
    info_ = new QTextBrowser(right);
    info_->setObjectName(QStringLiteral("DataInfo"));
    right_layout->addWidget(info_, 1);
    splitter->addWidget(right);

    splitter->setStretchFactor(0, 3);
    splitter->setStretchFactor(1, 2);
    layout->addWidget(splitter, 1);

    // 选中 → 信息面板（detail 列存于 UserRole）。
    connect(list_->selectionModel(), &QItemSelectionModel::currentChanged,
            this, [this](const QModelIndex& current, const QModelIndex&) {
                const QString detail = current.isValid()
                    ? model_->data(current, Qt::UserRole).toString()
                    : QString();
                info_->setHtml(detail.isEmpty()
                                   ? tr("<i>选中条目以查看信息。</i>")
                                   : detail);
            });
    info_->setHtml(tr("<i>未打开工程。打开或新建工程后，"
                      "此处列出工程数据资产。</i>"));
}

void DataManagementPage::set_entries(const QVector<DataEntry>& entries) {
    model_->removeRows(0, model_->rowCount());
    for (const DataEntry& entry : entries) {
        auto* name = new QStandardItem(entry.name);
        name->setData(entry.detail, Qt::UserRole);
        auto* kind = new QStandardItem(entry.kind);
        auto* location = new QStandardItem(entry.location);
        location->setToolTip(entry.location);
        model_->appendRow({name, kind, location});
    }
    if (entries.isEmpty()) {
        info_->setHtml(tr("<i>工程无数据资产，或未打开工程。</i>"));
    } else {
        info_->setHtml(tr("<i>选中条目以查看信息。</i>"));
    }
}

}  // namespace pwb::app
