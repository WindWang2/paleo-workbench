#include <pwb/ui_seqviz/qt/viz_panels.hpp>

#include <QListWidget>
#include <QListWidgetItem>
#include <QPushButton>
#include <QVariant>
#include <QVBoxLayout>

#include <pwb/ui_seqviz/page_tokens.hpp>
#include <pwb/ui_widgets/reconcile.hpp>

namespace pwb::ui_seqviz::qt {

namespace {

QLabel* add_value_row(QVBoxLayout* layout, const QString& label_text,
                      const QString& value_text, QLabel** value_out,
                      QWidget* parent) {
    auto* label = new QLabel(label_text, parent);
    label->setObjectName("WorkFieldLabel");
    layout->addWidget(label);
    auto* value = new QLabel(value_text, parent);
    value->setObjectName("WorkFieldValue");
    value->setWordWrap(true);
    layout->addWidget(value);
    *value_out = value;
    return value;
}

}  // namespace

// ---------------------------------------------------------------------------
// VisualizationSummaryPanel
// ---------------------------------------------------------------------------

VisualizationSummaryPanel::VisualizationSummaryPanel(QWidget* parent)
    : QFrame(parent) {
    setObjectName("VisualizationSummaryPanel");
    setMinimumWidth(200);

    auto* layout = new QVBoxLayout(this);
    const int pad = tokens::PANEL_PADDING;
    layout->setContentsMargins(pad, pad, pad, pad);
    layout->setSpacing(tokens::SPACE_2);
    auto* title = new QLabel("可视化总览", this);
    title->setObjectName("MapDockTitle");
    layout->addWidget(title);

    add_value_row(layout, "预测任务", "0 个", &prediction_count_value_,
                  this);
    add_value_row(layout, "古地理图", "0 幅", &map_count_value_, this);
    add_value_row(layout, "资源项", "0 项", &resource_count_value_, this);

    auto* list_label = new QLabel("可打开资产", this);
    list_label->setObjectName("WorkFieldLabel");
    layout->addWidget(list_label);
    asset_list_ = new QListWidget(this);
    asset_list_->setObjectName("WorkListWidget");
    connect(asset_list_, &QListWidget::itemActivated, this,
            &VisualizationSummaryPanel::on_item_activated);
    connect(asset_list_, &QListWidget::itemClicked, this,
            &VisualizationSummaryPanel::on_item_activated);
    layout->addWidget(asset_list_, 1);
}

void VisualizationSummaryPanel::update_state(
    const std::vector<ui_data_core::ResourceItem>& resources,
    const std::vector<PredictionTaskSlice>& prediction_tasks,
    const std::vector<MapDocSlice>& map_documents) {
    const VizSummaryCounts counts = summary_counts(
        resources.size(), prediction_tasks.size(), map_documents.size());
    prediction_count_value_->setText(
        QString::fromStdString(counts.prediction_text));
    map_count_value_->setText(QString::fromStdString(counts.map_text));
    resource_count_value_->setText(
        QString::fromStdString(counts.resource_text));

    entries_ = summary_asset_entries(resources, map_documents,
                                     prediction_tasks);

    std::vector<QString> keys;
    keys.reserve(entries_.size());
    for (const auto& entry : entries_) {
        keys.push_back(QString::fromStdString(entry.key));
    }
    const auto* entries_ptr = &entries_;
    ui_widgets::reconcile_widget_items(
        asset_list_, keys,
        [entries_ptr](const QString& key) {
            auto* item = new QListWidgetItem();
            item->setData(Qt::UserRole, key);
            return item;
        },
        [entries_ptr](QListWidgetItem* item, const QString& key) {
            for (const auto& entry : *entries_ptr) {
                if (QString::fromStdString(entry.key) == key) {
                    item->setText(QString::fromStdString(entry.text));
                    item->setData(Qt::UserRole, key);
                    return;
                }
            }
        });
}

void VisualizationSummaryPanel::on_item_activated(QListWidgetItem* item) {
    if (item == nullptr) {
        return;
    }
    const QString key = item->data(Qt::UserRole).toString();
    for (const auto& entry : entries_) {
        if (QString::fromStdString(entry.key) == key) {
            emit asset_selected(entry.ref);
            return;
        }
    }
}

// ---------------------------------------------------------------------------
// VisualizationTracePanel
// ---------------------------------------------------------------------------

VisualizationTracePanel::VisualizationTracePanel(QWidget* parent)
    : QFrame(parent) {
    setObjectName("VisualizationTracePanel");
    setMinimumWidth(220);
    setMaximumWidth(static_cast<int>(220 * 1.6));

    auto* layout = new QVBoxLayout(this);
    const int pad = tokens::PANEL_PADDING;
    layout->setContentsMargins(pad, pad, pad, pad);
    layout->setSpacing(tokens::SPACE_2);
    auto* title = new QLabel("视图追踪", this);
    title->setObjectName("MapDockTitle");
    layout->addWidget(title);

    add_value_row(layout, "预测任务", "未选择预测任务", &task_value_, this);
    add_value_row(layout, "古地理图", "未选择古地理图", &map_value_, this);
    add_value_row(layout, "来源", "—", &source_value_, this);
    add_value_row(layout, "标签", "—", &label_value_, this);
    add_value_row(layout, "类型", "—", &kind_value_, this);
    add_value_row(layout, "路径/消息", "—", &path_value_, this);

    layout->addStretch();
    refresh_btn_ = new QPushButton("刷新视图", this);
    refresh_btn_->setObjectName("SecondaryButton");
    connect(refresh_btn_, &QPushButton::clicked, this,
            &VisualizationTracePanel::refresh_requested);
    layout->addWidget(refresh_btn_);
    export_btn_ = new QPushButton("导出当前视图 PNG", this);
    export_btn_->setObjectName("PrimaryButton");
    connect(export_btn_, &QPushButton::clicked, this,
            [this] { emit export_requested("PNG"); });
    layout->addWidget(export_btn_);
    export_svg_btn_ = new QPushButton("导出 SVG", this);
    export_svg_btn_->setObjectName("SecondaryButton");
    connect(export_svg_btn_, &QPushButton::clicked, this,
            [this] { emit export_requested("SVG"); });
    layout->addWidget(export_svg_btn_);
    export_pdf_btn_ = new QPushButton("导出 PDF", this);
    export_pdf_btn_->setObjectName("SecondaryButton");
    connect(export_pdf_btn_, &QPushButton::clicked, this,
            [this] { emit export_requested("PDF"); });
    layout->addWidget(export_pdf_btn_);
    set_export_capabilities({"PNG"});
}

void VisualizationTracePanel::update_state(
    const std::vector<PredictionTaskSlice>& prediction_tasks,
    const std::vector<MapDocSlice>& map_documents) {
    const VizTraceView view =
        trace_state_view(prediction_tasks, map_documents);
    task_value_->setText(QString::fromStdString(view.task_text));
    map_value_->setText(QString::fromStdString(view.map_text));
}

void VisualizationTracePanel::update_ref(const VizRefSlice* ref,
                                       const UiVizPayload* payload) {
    VizTraceView view;
    view.task_text = task_value_->text().toStdString();
    view.map_text = map_value_->text().toStdString();
    trace_apply_ref(view, ref, payload);
    task_value_->setText(QString::fromStdString(view.task_text));
    map_value_->setText(QString::fromStdString(view.map_text));
    source_value_->setText(QString::fromStdString(view.source_text));
    label_value_->setText(QString::fromStdString(view.label_text));
    kind_value_->setText(QString::fromStdString(view.kind_text));
    path_value_->setText(QString::fromStdString(view.path_text));
}

void VisualizationTracePanel::set_export_capabilities(
    const std::set<std::string>& formats) {
    const ExportCaps caps = export_capability_state(formats);
    export_btn_->setEnabled(caps.png);
    export_svg_btn_->setEnabled(caps.svg);
    export_pdf_btn_->setEnabled(caps.pdf);
    export_btn_->setToolTip(QString::fromStdString(caps.png_tip));
    export_svg_btn_->setToolTip(QString::fromStdString(caps.svg_tip));
    export_pdf_btn_->setToolTip(QString::fromStdString(caps.pdf_tip));
}

}  // namespace pwb::ui_seqviz::qt
