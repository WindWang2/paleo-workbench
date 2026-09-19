// UI-06 — ProjectOverviewPanel shell (see qt/project_overview_panel.hpp).
#include <pwb/ui_pages_data/qt/project_overview_panel.hpp>

#include <QHBoxLayout>
#include <QLabel>
#include <QSizePolicy>
#include <QVBoxLayout>

#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_pages_data::qt {
namespace {

QString pal(const char* token) {
    const auto p = ui_shell::style_palette();
    const auto it = p.find(token);
    return it != p.end() ? QString::fromStdString(it->second) : QString();
}

QLabel* caption(const QString& text, QWidget* parent) {
    auto* label = new QLabel(text, parent);
    label->setAlignment(Qt::AlignmentFlag::AlignCenter);
    ui_shell::style_bind(label, [] {
        return QStringLiteral("color: %1;").arg(pal("TEXT_SECONDARY"));
    });
    return label;
}

}  // namespace

ProjectOverviewPanel::ProjectOverviewPanel(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("ProjectOverviewPanel"));
    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(20, 20, 20, 20);    // SPACE_4
    root->setSpacing(20);                        // SPACE_4

    title_label_ = new QLabel(QStringLiteral("工区概览"), this);
    ui_shell::style_bind(title_label_, [] {
        return QStringLiteral("font-size: 14px; font-weight: 700;");
    });
    root->addWidget(title_label_);

    meta_label_ = new QLabel(QStringLiteral("未打开工程"), this);
    meta_label_->setWordWrap(true);
    root->addWidget(meta_label_);

    // Compact stat strip: one "value over caption" block per metric.
    auto* strip = new QHBoxLayout();
    strip->setSpacing(20);                       // SPACE_4
    const std::pair<const char*, const char*> specs[] = {
        {"wells", "井"},
        {"surveys", "地震工区"},
        {"raw", "原始输入 RAW"},
        {"derived", "派生 DERIVED"},
        {"output", "成果 OUTPUT"},
        {"issues", "缺失 / 外部异常"},
        {"unresolved", "待治理实体"},
        {"recent", "最近任务"},
    };
    for (const auto& [key, cap] : specs) {
        auto* block = new QWidget(this);
        block->setSizePolicy(QSizePolicy::Policy::Ignored,
                             QSizePolicy::Policy::Fixed);
        auto* block_layout = new QVBoxLayout(block);
        block_layout->setContentsMargins(0, 0, 0, 0);
        block_layout->setSpacing(4);             // SPACE_1
        auto* value = new QLabel(QStringLiteral("—"), block);
        value->setAlignment(Qt::AlignmentFlag::AlignCenter);
        ui_shell::style_bind(value, [] {
            return QStringLiteral("font-size: 13px; font-weight: 600;");
        });
        values_[key] = value;
        block_layout->addWidget(value);
        block_layout->addWidget(caption(QString::fromUtf8(cap), block));
        strip->addWidget(block, 1);
    }
    root->addLayout(strip);

    hint_label_ = new QLabel(QString(), this);
    hint_label_->setWordWrap(true);
    ui_shell::style_bind(hint_label_, [] {
        return QStringLiteral("color: %1;").arg(pal("TEXT_SECONDARY"));
    });
    hint_label_->setVisible(false);
    root->addWidget(hint_label_);
}

void ProjectOverviewPanel::set_map_widget(QWidget* widget) {
    layout()->addWidget(widget);
    widget->setVisible(true);
}

void ProjectOverviewPanel::refresh_from_project(
    const OverviewProject* project, const CatalogCounts* counts) {
    if (project == nullptr) {
        meta_label_->setText(QStringLiteral("未打开工程"));
        return;
    }
    const OverviewView view = compute_project_overview(project, counts);
    title_label_->setText(QString::fromStdString(view.title));
    meta_label_->setText(QString::fromStdString(view.meta));
    for (const auto& [key, display] : view.values) {
        if (auto* label = values_[key]) {
            label->setText(QString::fromStdString(display));
        }
    }
    std::string hints;
    for (std::size_t i = 0; i < view.hints.size(); ++i) {
        if (i) hints += '\n';
        hints += view.hints[i];
    }
    hint_label_->setText(QString::fromStdString(hints));
    hint_label_->setVisible(!view.hints.empty());
}

}  // namespace pwb::ui_pages_data::qt
