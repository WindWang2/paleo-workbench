// UI-06 — ResourceTable shell (see qt/resource_table.hpp).
#include <pwb/ui_pages_data/qt/resource_table.hpp>

#include <QHeaderView>
#include <QLabel>
#include <QVBoxLayout>

#include <pwb/ui_pages_data/table_model.hpp>
#include <pwb/ui_pages_data/vocab.hpp>
#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_pages_data::qt {
namespace {

// COLUMN_HEADERS / COLUMN_WIDTHS (0 = stretch).
constexpr const char* kHeaders[] = {"文件名", "类型", "格式", "状态", "路径"};
constexpr int kWidths[] = {200, 100, 80, 100, 0};

QString pal_color(const char* token) {
    const auto p = ui_shell::style_palette();
    const auto it = p.find(token);
    return it != p.end() ? QString::fromStdString(it->second) : QString();
}

}  // namespace

ResourceTableModel::ResourceTableModel(QObject* parent)
    : QAbstractTableModel(parent) {}

void ResourceTableModel::set_rows(std::vector<AssetView> rows) {
    beginResetModel();
    rows_ = std::move(rows);
    endResetModel();
}

const AssetView* ResourceTableModel::row_at(int row) const {
    if (row < 0 || row >= static_cast<int>(rows_.size())) return nullptr;
    return &rows_[static_cast<std::size_t>(row)];
}

std::string ResourceTableModel::key_for_row(int row) const {
    const AssetView* view = row_at(row);
    if (view == nullptr) return {};
    if (!view->id.empty()) return view->id;
    if (!view->path.empty()) return view->path;
    return view->name;
}

int ResourceTableModel::index_for_key(const std::string& key) const {
    for (std::size_t i = 0; i < rows_.size(); ++i) {
        if (key_for_row(static_cast<int>(i)) == key)
            return static_cast<int>(i);
    }
    return -1;
}

int ResourceTableModel::rowCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0 : static_cast<int>(rows_.size());
}

int ResourceTableModel::columnCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0 : 5;
}

QVariant ResourceTableModel::data(const QModelIndex& index, int role) const {
    const AssetView* view = row_at(index.row());
    if (view == nullptr || index.column() < 0 || index.column() >= 5) {
        return {};
    }
    if (role == Qt::ItemDataRole::DisplayRole) {
        switch (index.column()) {
        case 0: return QString::fromStdString(view->name);
        case 1:
            return QString::fromStdString(
                std::string(resource_label(view->type)));
        case 2: return QString::fromStdString(view->format);
        case 3: return QString::fromStdString(view->status);
        case 4: return QString::fromStdString(view->path);
        default: return {};
        }
    }
    if (role == Qt::ItemDataRole::ForegroundRole && index.column() == 3) {
        const std::string token =
            std::string(status_color_token(view->status));
        const QString color = pal_color(token.c_str());
        if (!color.isEmpty()) return QColor(color);
    }
    if (role == Qt::ItemDataRole::UserRole && index.column() == 0) {
        return QString::fromStdString(key_for_row(index.row()));
    }
    return {};
}

QVariant ResourceTableModel::headerData(int section,
                                        Qt::Orientation orientation,
                                        int role) const {
    if (orientation == Qt::Orientation::Horizontal &&
        role == Qt::ItemDataRole::DisplayRole && section >= 0 && section < 5) {
        return QString::fromUtf8(kHeaders[section]);
    }
    return {};
}

// ---------------------------------------------------------------------------

ResourceTable::ResourceTable(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("ResourceTable"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    model_ = new ResourceTableModel(this);
    table_ = new QTableView(this);
    table_->setModel(model_);
    // bind_table_defaults verbatim.
    table_->setAlternatingRowColors(true);
    table_->setShowGrid(false);
    table_->setSelectionBehavior(QTableView::SelectionBehavior::SelectRows);
    table_->setEditTriggers(QTableView::EditTrigger::NoEditTriggers);
    table_->verticalHeader()->setVisible(false);
    table_->horizontalHeader()->setStretchLastSection(false);
    table_->horizontalHeader()->setHighlightSections(false);
    QHeaderView* header = table_->horizontalHeader();
    for (int i = 0; i < 5; ++i) {
        if (kWidths[i] > 0) {
            header->resizeSection(i, kWidths[i]);
        } else {
            header->setSectionResizeMode(
                i, QHeaderView::ResizeMode::Stretch);
        }
    }
    layout->addWidget(table_);

    // PwbEmptyState seam (ui.components.states) — same title/hint pair.
    empty_state_ = new QLabel(
        QStringLiteral("暂无资源\n导入数据后将在此列出工程资源。"), table_);
    empty_state_->setAlignment(Qt::AlignmentFlag::AlignCenter);
    empty_state_->setAttribute(Qt::WidgetAttribute::WA_TransparentForMouseEvents);
    empty_state_->hide();
    connect(model_, &QAbstractItemModel::modelReset, this,
            &ResourceTable::update_empty_state);
    connect(model_, &QAbstractItemModel::rowsInserted, this,
            &ResourceTable::update_empty_state);
    connect(model_, &QAbstractItemModel::rowsRemoved, this,
            &ResourceTable::update_empty_state);
}

void ResourceTable::update_resources(std::vector<AssetView> resources) {
    model_->set_rows(std::move(resources));
    update_empty_state();
}

void ResourceTable::resizeEvent(QResizeEvent* event) {
    QWidget::resizeEvent(event);
    if (empty_state_->isVisible()) {
        empty_state_->setGeometry(table_->viewport()->rect());
    }
}

void ResourceTable::update_empty_state() {
    if (model_->rowCount() == 0) {
        empty_state_->setGeometry(table_->viewport()->rect());
        empty_state_->show();
        empty_state_->raise();
    } else {
        empty_state_->hide();
    }
}

}  // namespace pwb::ui_pages_data::qt
