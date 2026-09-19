#include "pwb/ui_pages_mapedit/factor_preview_grid.hpp"

#include "pwb/ui_data_core/json_util.hpp"
#include "pwb/ui_shell/style_registry.hpp"

#include <QGridLayout>
#include <QLabel>
#include <QScrollArea>
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

QString pal(const char* key) {
    const auto& p = ui_shell::style_palette();
    const auto it = p.find(key);
    return it != p.end() ? QString::fromStdString(it->second) : QString();
}

QString json_qstr(const domain::Json& obj, const char* key,
                  const QString& fallback = QString()) {
    if (!obj.is_object()) {
        return fallback;
    }
    const auto it = obj.find(key);
    if (it == obj.end() || it->is_null()) {
        return fallback;
    }
    return QString::fromStdString(ui_data_core::python_str(*it));
}

// task.quality_metrics or {} — object only.
const domain::Json* metrics_of(const domain::Json& task) {
    static const domain::Json empty = domain::Json::object();
    if (!task.is_object()) {
        return &empty;
    }
    const auto it = task.find("quality_metrics");
    return it != task.end() && it->is_object() ? &*it : &empty;
}

}  // namespace

// --- FactorPreviewCard ---------------------------------------------------------

FactorPreviewCard::FactorPreviewCard(const domain::Json& task,
                                     QWidget* parent)
    : QFrame(parent), task(task) {
    setObjectName(QStringLiteral("FactorPreviewCard"));
    setMinimumSize(160, 100);

    auto* layout = new QVBoxLayout(this);
    const int pad = tok_int("PANEL_PADDING", 12);
    layout->setContentsMargins(pad, pad, pad, pad);
    layout->setSpacing(tok_int("SPACE_2", 8));

    const auto* metrics = metrics_of(task);

    // title = task.factor_type or task.name — `or` truthiness: falsy
    // factor_type (null/0/"") falls through to name.
    QString title;
    if (const auto it = task.find("factor_type");
        it != task.end() && ui_data_core::json_truthy(*it)) {
        title = QString::fromStdString(ui_data_core::python_str(*it));
    } else {
        title = json_qstr(task, "name");
    }
    name_label = new QLabel(title, this);
    ui_shell::style_bind(name_label, [] {
        return QStringLiteral(
                   "color: %1; font-size: %2; font-weight: 600;"
                   " border: none; background: transparent;")
            .arg(pal("TEXT_PRIMARY"),
                 pal("FONT_SIZE_TITLE"));
    });
    layout->addWidget(name_label);

    // str(metrics.get("range", "—")) — present-but-null renders "None"
    // (Python str parity); only an ABSENT key gets the placeholder.
    const auto range_it = metrics->find("range");
    range_label = new QLabel(
        range_it != metrics->end()
            ? QString::fromStdString(ui_data_core::python_str(*range_it))
            : QStringLiteral("—"),
        this);
    ui_shell::style_bind(range_label, [] {
        return QStringLiteral(
                   "color: %1; font-size: %2;"
                   " border: none; background: transparent;")
            .arg(pal("TEXT_PRIMARY"), pal("FONT_SIZE_BASE"));
    });
    layout->addWidget(range_label);

    const auto rsq_it = metrics->find("r_squared");
    rsquared_label = new QLabel(QString(), this);
    ui_shell::style_bind(rsquared_label, [] {
        return QStringLiteral(
                   "color: %1; font-size: %2;"
                   " border: none; background: transparent;")
            .arg(pal("TEXT_SECONDARY"), pal("FONT_SIZE_STATUS"));
    });
    if (rsq_it != metrics->end() && !rsq_it->is_null()) {
        rsquared_label->setText(QStringLiteral("R² %1").arg(
            QString::fromStdString(ui_data_core::python_str(*rsq_it))));
        rsquared_label->show();
    } else if (!metrics->empty()) {
        // #939-5: the plan/batch path legitimately omits LOO R² while the
        // single-run path reports it — show the reason instead of hiding.
        rsquared_label->setText(QStringLiteral("R² 本轮未计算"));
        rsquared_label->show();
    } else {
        rsquared_label->hide();
    }
    layout->addWidget(rsquared_label);

    const auto dup_it = metrics->find("duplicate_wells_dropped");
    const long long dup_count =
        dup_it != metrics->end() && dup_it->is_number()
            ? dup_it->get<long long>()
            : 0;
    dup_label = new QLabel(QString(), this);
    ui_shell::style_bind(dup_label, [] {
        return QStringLiteral(
                   "color: %1; font-size: %2;"
                   " border: none; background: transparent;")
            .arg(pal("ERROR_RED"), pal("FONT_SIZE_STATUS"));
    });
    if (dup_count > 0) {
        dup_label->setText(QStringLiteral(
            "%1 口同坐标井已去重（保留先录入值）")
            .arg(dup_count));
        dup_label->show();
    } else {
        dup_label->hide();
    }
    layout->addWidget(dup_label);
    layout->addStretch();
}

void FactorPreviewCard::mouseReleaseEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton) {
        emit clicked(task);
        event->accept();
        return;
    }
    QFrame::mouseReleaseEvent(event);
}

// --- FactorPreviewGrid ----------------------------------------------------------

FactorPreviewGrid::FactorPreviewGrid(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("FactorPreviewGrid"));
    ui_shell::style_bind(this, [] {
        return QStringLiteral(
            "QWidget#FactorPreviewGrid { background: transparent; }");
    });

    auto* outer = new QVBoxLayout(this);
    const int pad = tok_int("PANEL_PADDING", 12);
    outer->setContentsMargins(pad, pad, pad, pad);
    outer->setSpacing(tok_int("SPACE_2", 8));

    header_label_ = new QLabel(QStringLiteral("单因素图集"), this);
    header_label_->setObjectName(QStringLiteral("MapDockTitle"));
    outer->addWidget(header_label_);

    scroll_ = new QScrollArea(this);
    scroll_->setWidgetResizable(true);
    scroll_->setFrameShape(QScrollArea::NoFrame);
    ui_shell::style_bind(scroll_, [] {
        return QStringLiteral(
            "QScrollArea { border: none; background: transparent; }");
    });
    grid_container_ = new QWidget(scroll_);
    ui_shell::style_bind(grid_container_, [] {
        return QStringLiteral("background: transparent;");
    });
    grid_layout_ = new QGridLayout(grid_container_);
    grid_layout_->setContentsMargins(0, 0, 0, 0);
    grid_layout_->setSpacing(tok_int("SPACE_3", 12));
    grid_layout_->setColumnStretch(0, 1);
    grid_layout_->setColumnStretch(1, 1);
    scroll_->setWidget(grid_container_);
    outer->addWidget(scroll_, 1);
}

void FactorPreviewGrid::clear_grid() {
    while (grid_layout_->count()) {
        QLayoutItem* item = grid_layout_->takeAt(0);
        if (QWidget* widget = item->widget()) {
            widget->hide();
            widget->setParent(nullptr);
            widget->deleteLater();
        }
        delete item;
    }
    empty_label_ = nullptr;
}

void FactorPreviewGrid::update_state(
    const std::vector<domain::Json>& tasks) {
    std::vector<const domain::Json*> completed;
    for (const auto& task : tasks) {
        if (json_qstr(task, "status") == QLatin1String("complete")) {
            completed.push_back(&task);
        }
    }

    clear_grid();
    if (completed.empty()) {
        header_label_->setText(QStringLiteral("单因素图集"));
        empty_label_ =
            new QLabel(QStringLiteral("暂无已生成的单因素图"), this);
        empty_label_->setObjectName(QStringLiteral("EmptyStateLabel"));
        grid_layout_->addWidget(empty_label_, 0, 0, 1, 2);
        return;
    }

    const domain::Json& first = *completed.front();
    // Python ``first.target_horizon`` — the attribute always exists on the
    // task model and renders via f-string str(): present-null → "None".
    QString horizon;
    if (const auto it = first.find("target_horizon");
        it != first.end()) {
        horizon = QString::fromStdString(ui_data_core::python_str(*it));
    } else {
        horizon = QStringLiteral("None");
    }
    // ``first.method or "—"`` — or-truthiness: null/0/"" all collapse.
    QString method;
    if (const auto it = first.find("method");
        it != first.end() && ui_data_core::json_truthy(*it)) {
        method = QString::fromStdString(ui_data_core::python_str(*it));
    } else {
        method = QStringLiteral("—");
    }
    const auto* metrics = metrics_of(first);
    // ``metrics.get("grid", "50×50")`` — the default only applies when the
    // key is ABSENT; present-null renders str(None) → "None".
    const auto grid_it = metrics->find("grid");
    const QString grid_value =
        grid_it != metrics->end()
            ? QString::fromStdString(ui_data_core::python_str(*grid_it))
            : QStringLiteral("50×50");
    header_label_->setText(
        QStringLiteral("%1 单因素图集（%2插值 · 网格 %3 m）")
            .arg(horizon, method, grid_value));

    constexpr int cols = 2;
    int index = 0;
    for (const domain::Json* task : completed) {
        auto* card = new FactorPreviewCard(*task, this);
        connect(card, &FactorPreviewCard::clicked, this,
                [this](const domain::Json& t) { emit card_clicked(t); });
        grid_layout_->addWidget(card, index / cols, index % cols);
        ++index;
    }
}

}  // namespace pwb::ui_pages_mapedit
