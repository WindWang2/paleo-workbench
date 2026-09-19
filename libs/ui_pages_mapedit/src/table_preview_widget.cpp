#include "pwb/ui_pages_mapedit/table_preview_widget.hpp"

#include "pwb/ui_shell/style_registry.hpp"

#include <QAbstractTableModel>
#include <QApplication>
#include <QClipboard>
#include <QFontMetrics>
#include <QHeaderView>
#include <QItemSelection>
#include <QItemSelectionModel>
#include <QKeyEvent>
#include <QKeySequence>
#include <QSizePolicy>

namespace pwb::ui_pages_mapedit {
namespace {

// Defensive payload bound only (Python MAX_PREVIEW_CELLS): the virtualized
// model removed the per-cell widget allocation, so the cap merely guards
// against pathological parser output.
constexpr int kMaxPreviewCells = 1'000'000;
// Column auto-fit only samples this many leading rows (Python
// _AUTO_FIT_SAMPLE_ROWS): resizeColumnsToContents walks every row.
constexpr int kAutoFitSampleRows = 400;

bool is_depth_header(const QString& header) {
    const QString up = header.toUpper();
    return up == QLatin1String("DEPT") || up == QLatin1String("DEPTH") ||
           header == QLatin1String("深度");
}

const QFont& mono_font() {
    static const QFont font(QStringLiteral("Cascadia Code"), 9);
    return font;
}

const QFont& mono_bold_font() {
    static QFont font = [] {
        QFont f(QStringLiteral("Cascadia Code"), 9);
        f.setBold(true);
        return f;
    }();
    return font;
}

// Python ``float(val)`` accepts underscores between digits plus
// inf/infinity/nan; QString::toDouble covers the same numeric grammar once
// underscores are validated and removed.
bool is_number(const QString& val) {
    if (val == QLatin1String("NaN")) {
        return true;
    }
    QString s = val;
    for (int i = 0; i < s.size(); ++i) {
        if (s[i] == u'_') {
            const bool between_digits =
                i > 0 && i + 1 < s.size() && s[i - 1].isDigit() &&
                s[i + 1].isDigit();
            if (!between_digits) {
                return false;
            }
        }
    }
    s.remove(u'_');
    bool ok = false;
    s.toDouble(&ok);
    return ok;
}

// Highlight brushes resolve from the ACTIVE theme palette (#1047 parity):
// fixed light-token brushes left dark themes with unreadable tints.
struct ThemedBrushes {
    QBrush depth_fg;
    QBrush depth_bg;
    QBrush tag_fg;
    QBrush tag_bg;
    QBrush unit_fg;
    QBrush nan_fg;
};

QString pal(const std::map<std::string, std::string>& p, const char* key,
            const char* fallback) {
    const auto it = p.find(key);
    const QString v = it != p.end() ? QString::fromStdString(it->second)
                                    : QString::fromLatin1(fallback);
    return v;
}

ThemedBrushes themed_brushes() {
    const auto& p = ui_shell::style_palette();
    return {QBrush(QColor(pal(p, "PRIMARY", "#0b5563"))),
            QBrush(QColor(pal(p, "BG_SELECTION", "#d8ebef"))),
            QBrush(QColor(pal(p, "TEAL", "#0f766e"))),
            QBrush(QColor(pal(p, "BG_SEARCH", "#edf1f4"))),
            QBrush(QColor(pal(p, "TEXT_SECONDARY", "#53616c"))),
            QBrush(QColor(pal(p, "PRIMARY_DISABLED", "#8c99a3")))};
}

constexpr int kAlignRight =
    static_cast<int>(Qt::AlignRight | Qt::AlignVCenter);
constexpr int kAlignCenter =
    static_cast<int>(Qt::AlignCenter | Qt::AlignVCenter);

}  // namespace

// TablePreviewModel — headers + string rows, display computed on demand
// (the Python virtualization contract: no per-cell allocation at load).
class TablePreviewModel : public QAbstractTableModel {
    Q_OBJECT
public:
    explicit TablePreviewModel(QObject* parent = nullptr)
        : QAbstractTableModel(parent) {}

    void set_table(const QStringList& headers,
                   const std::vector<QStringList>& rows) {
        beginResetModel();
        headers_ = headers;
        rows_ = rows;
        depth_column_ = -1;
        for (int i = 0; i < headers_.size(); ++i) {
            if (is_depth_header(headers_[i])) {
                depth_column_ = i;
                break;
            }
        }
        is_curve_def_ = headers_.size() >= 3 &&
                        (headers_[0] == QLatin1String("曲线") ||
                         headers_[0] == QLatin1String("Mnemonic"));
        endResetModel();
    }

    int rowCount(const QModelIndex& parent = QModelIndex()) const override {
        return parent.isValid() ? 0 : static_cast<int>(rows_.size());
    }
    int columnCount(const QModelIndex& parent = QModelIndex()) const override {
        return parent.isValid() ? 0 : headers_.size();
    }
    QVariant headerData(int section, Qt::Orientation orientation,
                        int role = Qt::DisplayRole) const override {
        if (role != Qt::DisplayRole) {
            return {};
        }
        if (orientation == Qt::Horizontal && section >= 0 &&
            section < headers_.size()) {
            return headers_[section];
        }
        if (orientation == Qt::Vertical && section >= 0 &&
            section < static_cast<int>(rows_.size())) {
            return QString::number(section + 1);
        }
        return {};
    }

    QVariant data(const QModelIndex& index,
                  int role = Qt::DisplayRole) const override {
        if (!index.isValid()) {
            return {};
        }
        const int row = index.row();
        const int column = index.column();
        if (!(row >= 0 && row < static_cast<int>(rows_.size()) &&
              column >= 0 && column < headers_.size())) {
            return {};
        }
        const auto& source = rows_[row];
        const QString val_str =
            column < source.size() ? source[column].trimmed() : QString();

        if (role == Qt::DisplayRole) {
            return val_str;
        }

        const ThemedBrushes brushes = themed_brushes();

        // 1. Depth column (DEPT / DEPTH / 深度)
        if (column == depth_column_) {
            if (role == Qt::FontRole) {
                return mono_bold_font();
            }
            if (role == Qt::ForegroundRole) {
                return brushes.depth_fg;
            }
            if (role == Qt::BackgroundRole) {
                return brushes.depth_bg;
            }
            if (role == Qt::TextAlignmentRole) {
                return kAlignRight;
            }
        }
        // 2. Curve mnemonic tag formatting in curve definition table
        else if (is_curve_def_ && column == 0) {
            if (role == Qt::FontRole) {
                return mono_bold_font();
            }
            if (role == Qt::ForegroundRole) {
                return brushes.tag_fg;
            }
            if (role == Qt::BackgroundRole) {
                return brushes.tag_bg;
            }
            if (role == Qt::TextAlignmentRole) {
                return kAlignCenter;
            }
        }
        // 3. Unit column formatting
        else if (is_curve_def_ && column == 1) {
            if (role == Qt::FontRole) {
                return mono_font();
            }
            if (role == Qt::ForegroundRole) {
                return brushes.unit_fg;
            }
            if (role == Qt::TextAlignmentRole) {
                return kAlignCenter;
            }
        }
        // 4. Numeric curve data formatting
        else if (is_number(val_str)) {
            if (role == Qt::FontRole) {
                return mono_font();
            }
            if (role == Qt::TextAlignmentRole) {
                return kAlignRight;
            }
            if (role == Qt::ForegroundRole &&
                val_str == QLatin1String("NaN")) {
                return brushes.nan_fg;
            }
        }
        return {};
    }

    // Formatted cell strings of one row (copy/export path).
    QStringList row_text(int row) const {
        if (row < 0 || row >= static_cast<int>(rows_.size())) {
            return {};
        }
        const auto& source = rows_[row];
        QStringList out;
        out.reserve(headers_.size());
        for (int c = 0; c < headers_.size(); ++c) {
            out.append(c < source.size() ? source[c].trimmed() : QString());
        }
        return out;
    }

    const QStringList& headers() const { return headers_; }

private:
    QStringList headers_;
    std::vector<QStringList> rows_;
    int depth_column_ = -1;
    bool is_curve_def_ = false;
};

TablePreviewWidget::TablePreviewWidget(QWidget* parent)
    : QTableView(parent), model_(new TablePreviewModel(this)) {
    setModel(model_);
    setEditTriggers(QTableView::NoEditTriggers);
    setAlternatingRowColors(true);
    setShowGrid(true);
    setSelectionBehavior(QTableView::SelectItems);
    setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    horizontalHeader()->setStretchLastSection(true);
    verticalHeader()->setDefaultSectionSize(28);
}

void TablePreviewWidget::apply_settings(int font_size, bool auto_fit) {
    QFont f = font();
    f.setPointSize(font_size);
    setFont(f);
    auto_fit_columns = auto_fit;
    horizontalHeader()->setSectionResizeMode(
        auto_fit_columns ? QHeaderView::ResizeToContents
                         : QHeaderView::Interactive);
}

void TablePreviewWidget::load_table(
    const QStringList& headers, const std::vector<QStringList>& rows) {
    truncated = false;
    truncation_message.clear();
    const int n_cols = headers.size();
    const std::vector<QStringList>* visible_rows = &rows;
    std::vector<QStringList> kept;
    if (n_cols > 0 &&
        static_cast<long long>(rows.size()) * n_cols > kMaxPreviewCells) {
        const int keep =
            std::max(1, kMaxPreviewCells / n_cols);
        kept.assign(rows.begin(), rows.begin() + std::min<int>(
                                     keep, static_cast<int>(rows.size())));
        visible_rows = &kept;
        truncated = true;
        truncation_message = QStringLiteral(
            "表格预览已截断：显示 %1/%2 行（上限 %3 单元格）")
            .arg(keep)
            .arg(rows.size())
            .arg(kMaxPreviewCells);
    }
    if (truncated) {
        setToolTip(truncation_message);
        setStatusTip(truncation_message);
    } else {
        setToolTip(QString());
        setStatusTip(QString());
    }
    model_->set_table(headers, *visible_rows);

    if (auto_fit_columns) {
        auto* hdr = horizontalHeader();
        const int cols = model_->columnCount();
        // Fit from a bounded SAMPLE of leading rows: resizeColumnsToContents
        // walks every row — the O(rows × columns) pass this widget removed.
        hdr->setSectionResizeMode(QHeaderView::Interactive);
        hdr->setStretchLastSection(false);
        const int sample =
            std::min(model_->rowCount(), kAutoFitSampleRows);
        std::vector<QStringList> sample_rows;
        sample_rows.reserve(sample);
        for (int r = 0; r < sample; ++r) {
            sample_rows.push_back(model_->row_text(r));
        }
        const QFontMetrics metrics = fontMetrics();
        for (int col = 0; col < cols; ++col) {
            int width =
                metrics.horizontalAdvance(model_->headers().at(col)) + 24;
            for (const auto& cells : sample_rows) {
                if (col < cells.size()) {
                    width = std::max(
                        width, metrics.horizontalAdvance(cells[col]) + 24);
                }
            }
            hdr->resizeSection(col, std::max(width + 16, 75));
        }
        hdr->setStretchLastSection(true);
    }
}

QString TablePreviewWidget::copy_all() const {
    const int n_cols = model_->columnCount();
    if (n_cols == 0) {
        return QString();
    }
    QStringList lines;
    lines.append(model_->headers().join(QLatin1Char('\t')));
    for (int r = 0; r < model_->rowCount(); ++r) {
        lines.append(model_->row_text(r).join(QLatin1Char('\t')));
    }
    if (model_->rowCount() == 0) {
        return model_->headers().join(QLatin1Char('\t'));
    }
    return lines.join(QLatin1Char('\n'));
}

void TablePreviewWidget::keyPressEvent(QKeyEvent* event) {
    bool is_copy = event->matches(QKeySequence::Copy);
    if (!is_copy && event->key() == Qt::Key_C &&
        (event->modifiers() & Qt::ControlModifier)) {
        is_copy = true;
    }
    if (is_copy) {
        const QModelIndexList indexes = selectedIndexes();
        if (indexes.isEmpty()) {
            event->accept();
            return;
        }
        std::map<int, std::map<int, QString>> by_row;
        for (const QModelIndex& index : indexes) {
            by_row[index.row()][index.column()] =
                index.data().toString();
        }
        QStringList lines;
        for (const auto& [row, cells] : by_row) {
            QStringList texts;
            for (const auto& [col, text] : cells) {
                texts.append(text);
            }
            lines.append(texts.join(QLatin1Char('\t')));
        }
        if (QClipboard* clipboard = QApplication::clipboard()) {
            clipboard->setText(lines.join(QLatin1Char('\n')));
        }
        event->accept();
        return;
    }
    QTableView::keyPressEvent(event);
}

int TablePreviewWidget::rowCount() const {
    return model_->rowCount();
}

int TablePreviewWidget::columnCount() const {
    return model_->columnCount();
}

QString TablePreviewWidget::item_text(int row, int column) const {
    const QModelIndex index = model_->index(row, column);
    return index.isValid() ? index.data(Qt::DisplayRole).toString()
                           : QString();
}

QStringList TablePreviewWidget::row_text(int row) const {
    return model_->row_text(row);
}

QString TablePreviewWidget::horizontal_header_text(int column) const {
    if (column < 0 || column >= model_->headers().size()) {
        return QString();
    }
    return model_->headers()[column];
}

void TablePreviewWidget::set_range_selected(int top_row, int left_column,
                                            int bottom_row, int right_column,
                                            bool select) {
    if (!select) {
        return;
    }
    const QModelIndex top_left = model_->index(top_row, left_column);
    const QModelIndex bottom_right =
        model_->index(bottom_row, right_column);
    QItemSelectionModel* selection_model = selectionModel();
    if (selection_model == nullptr) {
        return;
    }
    selection_model->select(
        QItemSelection(top_left, bottom_right),
        QItemSelectionModel::Select | QItemSelectionModel::Current);
}

}  // namespace pwb::ui_pages_mapedit

#include "table_preview_widget.moc"
