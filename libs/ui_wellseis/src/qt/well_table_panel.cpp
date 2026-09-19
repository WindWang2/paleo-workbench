#include <pwb/ui_wellseis/qt/well_table_panel.hpp>

#include <QHeaderView>
#include <QLabel>
#include <QTableView>
#include <QVBoxLayout>

#include <pwb/ui_wellseis/qt/object_table_model.hpp>
#include <pwb/ui_wellseis/well_table_format.hpp>

namespace pwb::ui_wellseis::qt {

namespace {

QString qs(const std::string& text) {
    return QString::fromUtf8(text.data(), static_cast<int>(text.size()));
}

// QC token -> palette color (success green / warning amber / error red /
// secondary grey).
QColor qc_color(const std::string& token) {
    if (token == "SUCCESS") {
        return QColor(0x2e, 0x7d, 0x32);
    }
    if (token == "WARNING") {
        return QColor(0xb4, 0x6a, 0x00);
    }
    if (token == "ERROR_RED") {
        return QColor(0xc6, 0x28, 0x28);
    }
    return QColor(0x6b, 0x6f, 0x76);  // TEXT_SECONDARY
}

}  // namespace

WellTablePanel::WellTablePanel(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("WellTablePanel"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(8, 8, 8, 8);
    layout->setSpacing(4);

    title_label_ = new QLabel(this);
    title_label_->setObjectName(QStringLiteral("MapDockTitle"));
    layout->addWidget(title_label_);

    summary_label_ = new QLabel(this);
    summary_label_->setObjectName(QStringLiteral("WorkFieldValue"));
    layout->addWidget(summary_label_);

    table_ = new QTableView(this);
    model_ = new StringTableModel(this);
    std::vector<StringTableModel::Column> columns;
    columns.reserve(kWellTableColumns.size());
    for (const WellTableColumn& column : kWellTableColumns) {
        columns.push_back({qs(column.key), qs(column.title)});
    }
    model_->set_columns(columns);
    table_->setModel(model_);
    table_->setEditTriggers(QAbstractItemView::NoEditTriggers);
    table_->setSelectionBehavior(QAbstractItemView::SelectRows);
    table_->setSelectionMode(QAbstractItemView::SingleSelection);
    table_->verticalHeader()->setVisible(false);
    table_->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);
    connect(table_, &QTableView::activated, this,
            [this](const QModelIndex& index) {
                if (auto key = model_->key_for_index(index)) {
                    emit well_activated(qs(*key));
                }
            });
    layout->addWidget(table_, 1);
}

void WellTablePanel::update_from_well_table(const WellTableSlice& table) {
    well_table_ = table;
    // Stable selection across the refresh (StableSelection parity).
    auto* selection = table_->selectionModel();
    const auto keys = capture_selected_keys(selection, model_);
    const auto current = current_key(selection, model_);

    std::vector<std::string> row_keys;
    std::vector<std::vector<QString>> rows;
    row_keys.reserve(table.rows.size());
    rows.reserve(table.rows.size());
    for (const WellTableRowSlice& row : table.rows) {
        row_keys.push_back(row.well_id);
        std::vector<QString> cells;
        cells.reserve(kWellTableColumns.size());
        for (const WellTableColumn& column : kWellTableColumns) {
            cells.push_back(qs(well_table_cell(row, column.key)));
        }
        rows.push_back(std::move(cells));
    }
    model_->set_rows(row_keys, rows);
    for (int i = 0; i < static_cast<int>(table.rows.size()); ++i) {
        const auto token = qc_foreground_token(table.rows[i].qc_flag);
        if (token.has_value()) {
            model_->set_row_foreground(i, QBrush(qc_color(*token)));
        }
    }
    restore_selected_keys(selection, model_, keys, current);

    title_label_->setText(qs(well_table_title(table)));
    summary_label_->setText(qs(well_table_summary(table)));
}

void WellTablePanel::clear() {
    update_from_well_table(WellTableSlice{});
}

std::optional<std::string> WellTablePanel::selected_well_id() const {
    return current_key(table_->selectionModel(),
                       const_cast<StringTableModel*>(model_));
}

void WellTablePanel::select_well(const std::string& well_id) {
    const int row = model_->row_for_key(well_id);
    if (row >= 0) {
        table_->setCurrentIndex(model_->index(row, 0));
    }
}

QString WellTablePanel::title_text() const {
    return title_label_->text();
}

QString WellTablePanel::summary_text() const {
    return summary_label_->text();
}

StringTableModel* WellTablePanel::model() const {
    return model_;
}

}  // namespace pwb::ui_wellseis::qt
