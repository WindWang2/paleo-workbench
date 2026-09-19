#include <pwb/ui_wellseis/qt/well_detail_panel.hpp>

#include <QFrame>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QPushButton>
#include <QTableView>
#include <QVBoxLayout>

#include <pwb/ui_wellseis/qt/object_table_model.hpp>
#include <pwb/ui_wellseis/well_detail.hpp>

namespace pwb::ui_wellseis::qt {

namespace {

QString qs(const std::string& text) {
    return QString::fromUtf8(text.data(), static_cast<int>(text.size()));
}

QFrame* section_card(const QString& title_text, QVBoxLayout** body_out,
                     QWidget* parent) {
    auto* card = new QFrame(parent);
    card->setObjectName(QStringLiteral("WellDetailCard"));
    card->setStyleSheet(QStringLiteral(
        "QFrame#WellDetailCard { background: #f6f7f9; border: 1px solid "
        "#d8dbe0; border-radius: 6px; }"));
    auto* card_layout = new QVBoxLayout(card);
    card_layout->setContentsMargins(12, 8, 12, 12);
    card_layout->setSpacing(4);
    auto* title = new QLabel(title_text, card);
    QFont title_font = title->font();
    title_font.setBold(true);
    title->setFont(title_font);
    card_layout->addWidget(title);
    auto* body = new QVBoxLayout();
    card_layout->addLayout(body);
    *body_out = body;
    return card;
}

}  // namespace

WellDetailPanel::WellDetailPanel(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("WellDetailPanel"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(12, 12, 12, 12);
    layout->setSpacing(8);

    title_ = new QLabel(QStringLiteral("井数据视图"), this);
    QFont title_font = title_->font();
    title_font.setPointSizeF(title_font.pointSizeF() + 3);
    title_font.setBold(true);
    title_->setFont(title_font);
    subtitle_ = new QLabel(this);
    subtitle_->setStyleSheet(QStringLiteral("color: #6b6f76;"));
    layout->addWidget(title_);
    layout->addWidget(subtitle_);

    roles_table_ = new QTableView(this);
    roles_model_ = new StringTableModel(this);
    roles_model_->set_columns({
        {QStringLiteral("role"), QStringLiteral("角色")},
        {QStringLiteral("members"), QStringLiteral("资产")},
        {QStringLiteral("primary"), QStringLiteral("主用")},
        {QStringLiteral("current"), QStringLiteral("当前版本")},
        {QStringLiteral("versions"), QStringLiteral("版本数")},
    });
    roles_table_->setModel(roles_model_);
    roles_table_->horizontalHeader()->setSectionResizeMode(
        1, QHeaderView::Stretch);
    roles_table_->setEditTriggers(QAbstractItemView::NoEditTriggers);
    roles_table_->setSelectionBehavior(QAbstractItemView::SelectRows);
    roles_table_->verticalHeader()->setVisible(false);
    layout->addWidget(roles_table_, 2);

    auto* status_row = new QHBoxLayout();
    status_row->addWidget(
        section_card(QStringLiteral("过期成果"), &stale_body_, this), 1);
    status_row->addWidget(
        section_card(QStringLiteral("未提交编辑"), &edits_body_, this), 1);
    status_row->addWidget(
        section_card(QStringLiteral("缺失/异常"), &missing_body_, this), 1);
    layout->addLayout(status_row, 1);

    auto* close_btn =
        new QPushButton(QStringLiteral("← 返回资产列表"), this);
    connect(close_btn, &QPushButton::clicked, this,
            &WellDetailPanel::close_requested);
    layout->addWidget(close_btn, 0, Qt::AlignLeft);
}

void WellDetailPanel::fill_card(QVBoxLayout* body,
                                const std::vector<std::string>& lines) {
    while (QLayoutItem* item = body->takeAt(0)) {
        delete item->widget();
        delete item;
    }
    for (const std::string& line : lines) {
        auto* label = new QLabel(qs(line));
        label->setWordWrap(true);
        body->addWidget(label);
    }
}

void WellDetailPanel::set_view(const WellDataViewSlice& view, bool has_view) {
    has_view_ = has_view;
    view_ = view;
    if (!has_view) {
        clear();
        return;
    }
    title_->setText(qs(well_detail_title(view)));
    subtitle_->setText(qs(well_detail_subtitle(view)));

    const std::vector<WellRoleRow> rows = well_role_rows(view);
    std::vector<std::string> keys;
    std::vector<std::vector<QString>> cells;
    keys.reserve(rows.size());
    cells.reserve(rows.size());
    for (const WellRoleRow& row : rows) {
        keys.push_back(row.role);
        cells.push_back({qs(row.role_display), qs(row.member_names),
                         qs(row.primary_mark), qs(row.current_version_text),
                         QString::number(row.version_count_sum)});
    }
    roles_model_->set_rows(keys, cells);

    fill_card(stale_body_, well_stale_lines(view, /*truncate_ids=*/false));
    fill_card(edits_body_, well_edit_lines(view));
    fill_card(missing_body_, well_missing_lines(view));
}

void WellDetailPanel::update_stale(
    const std::vector<StaleItemSlice>& items) {
    if (!has_view_) {
        return;
    }
    view_.stale_items = items;
    fill_card(stale_body_, well_stale_lines(view_, /*truncate_ids=*/true));
}

void WellDetailPanel::clear() {
    has_view_ = false;
    view_ = WellDataViewSlice{};
    title_->setText(QStringLiteral("井数据视图"));
    subtitle_->setText(QString());
    roles_model_->set_rows({}, {});
    for (QVBoxLayout* body : {stale_body_, edits_body_, missing_body_}) {
        while (QLayoutItem* item = body->takeAt(0)) {
            delete item->widget();
            delete item;
        }
    }
}

}  // namespace pwb::ui_wellseis::qt
