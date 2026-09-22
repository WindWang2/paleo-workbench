// 仅在编图切片（PWB_WITH_CLOSURE_MAPPING）构建中编译实体——模板库与
// 编图文档状态来自 mapping_document / closure_mapping 链接闭包；其它
// 构建中本面板不参与（对应命令保持诚实禁用原因）。include 也必须在
// 宏内，否则空 TU 的 AUTOMOC 仍会为 Q_OBJECT 类生成悬空 moc。

#if defined(PWB_WITH_CLOSURE_MAPPING)

#include "layout_compose_panel.hpp"

#include <algorithm>
#include <map>
#include <utility>

#include <QCheckBox>
#include <QComboBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QPainter>
#include <QPen>
#include <QPushButton>
#include <QVBoxLayout>

#include <pwb/mapping_document/composer_templates.hpp>
#include <pwb/ui_map/map_chrome_core.hpp>

namespace pwb::app {

namespace {

using pwb::domain::Json;
using pwb::mapping_document::composer_template_library;

// Real ISO 216 paper sizes (mm).
const std::map<QString, std::pair<double, double>> kPaperSizes = {
    {QStringLiteral("A4"), {210.0, 297.0}},
    {QStringLiteral("A3"), {297.0, 420.0}},
    {QStringLiteral("A2"), {420.0, 594.0}},
    {QStringLiteral("A1"), {594.0, 841.0}},
    {QStringLiteral("A0"), {841.0, 1189.0}},
};

QString chrome_title(const Json& chrome) {
    const auto it = chrome.find("title");
    return it != chrome.end() && it->is_string()
               ? QString::fromStdString(it->get<std::string>())
               : QString();
}

bool chrome_has(const Json& chrome, const QString& element) {
    const auto it = chrome.find("elements");
    if (it == chrome.end() || !it->is_array()) return false;
    for (const auto& entry : *it) {
        if (entry.is_string() &&
            entry.get<std::string>() == element.toStdString()) {
            return true;
        }
    }
    return false;
}

// The vector preview: paper + the selected template's REAL element
// geometry (mm) + the checked chrome decorations. Painted from the
// template data — never a screenshot.
class ComposePreview : public QWidget {
public:
    explicit ComposePreview(LayoutComposePanel* panel)
        : QWidget(panel), panel_(panel) {
        setObjectName(QStringLiteral("ComposePreview"));
        setMinimumHeight(160);
    }

protected:
    void paintEvent(QPaintEvent* event) override;

private:
    LayoutComposePanel* panel_;
};

}  // namespace

LayoutComposePanel::LayoutComposePanel(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("LayoutComposePanel"));
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(4, 2, 4, 2);
    outer->setSpacing(2);

    auto* controls = new QHBoxLayout;
    controls->setSpacing(6);
    controls->addWidget(new QLabel(QStringLiteral("模板"), this));
    template_ = new QComboBox(this);
    template_->setObjectName(QStringLiteral("ComposeTemplate"));
    controls->addWidget(template_);
    controls->addWidget(new QLabel(QStringLiteral("纸张"), this));
    paper_ = new QComboBox(this);
    paper_->setObjectName(QStringLiteral("ComposePaper"));
    for (const auto& [name, size] : kPaperSizes) {
        paper_->addItem(QStringLiteral("%1（%2×%3 mm）")
                            .arg(name)
                            .arg(size.first, 0, 'f', 0)
                            .arg(size.second, 0, 'f', 0),
                        name);
    }
    controls->addWidget(paper_);
    controls->addWidget(new QLabel(QStringLiteral("方向"), this));
    orientation_ = new QComboBox(this);
    orientation_->setObjectName(QStringLiteral("ComposeOrientation"));
    orientation_->addItem(QStringLiteral("横向"), QStringLiteral("landscape"));
    orientation_->addItem(QStringLiteral("纵向"), QStringLiteral("portrait"));
    controls->addWidget(orientation_);
    controls->addSpacing(8);
    // 图件整饰 —— 与 map_chrome 同一词汇、同一文档状态。
    for (const auto& element : ui_map::default_chrome_elements()) {
        const QString name = QString::fromStdString(element);
        auto* check = new QCheckBox(name, this);
        check->setObjectName(QStringLiteral("ComposeChrome_") + name);
        checks_.insert(name, check);
        connect(check, &QCheckBox::toggled, this, [this](bool) {
            if (!syncing_) emit_chrome();
        });
        controls->addWidget(check);
    }
    controls->addStretch(1);
    auto* export_button = new QPushButton(QStringLiteral("导出图件…"), this);
    export_button->setObjectName(QStringLiteral("ComposeExport"));
    connect(export_button, &QPushButton::clicked, this, [this] {
        if (export_action_ != nullptr) {
            export_action_->trigger();
        } else {
            emit status_message(
                QStringLiteral("导出入口未装配（ governed map_export 未绑定）"));
        }
    });
    controls->addWidget(export_button);
    outer->addLayout(controls);

    preview_ = new ComposePreview(this);
    outer->addWidget(preview_, 1);

    hint_ = new QLabel(this);
    hint_->setObjectName(QStringLiteral("ComposeHint"));
    hint_->setWordWrap(true);
    outer->addWidget(hint_);

    rebuild_template_selector();
    for (auto* combo : {template_, paper_, orientation_}) {
        connect(combo, &QComboBox::currentIndexChanged, this,
                [this](int) { update_preview(); });
    }
    update_preview();
    sync_chrome_checks();
}

void LayoutComposePanel::set_chrome_reader(std::function<Json()> reader) {
    chrome_reader_ = std::move(reader);
    sync_chrome_checks();
}

void LayoutComposePanel::set_chrome_writer(
    std::function<void(const Json&)> writer) {
    chrome_writer_ = std::move(writer);
}

void LayoutComposePanel::set_export_action(QAction* action) {
    export_action_ = action;
    if (auto* button = findChild<QPushButton*>(
            QStringLiteral("ComposeExport"))) {
        button->setEnabled(action != nullptr && action->isEnabled());
        if (action != nullptr) {
            button->setToolTip(action->toolTip().isEmpty()
                                   ? action->text()
                                   : action->toolTip());
        }
    }
}

void LayoutComposePanel::refresh_chrome() { sync_chrome_checks(); }

QString LayoutComposePanel::selected_template_id() const {
    return template_->currentData().toString();
}

bool LayoutComposePanel::chrome_checked(const QString& element) const {
    const QCheckBox* check = checks_.value(element);
    return check != nullptr && check->isChecked();
}

Json LayoutComposePanel::draft() const {
    Json chrome = Json::object();
    Json elements = Json::array();
    for (auto it = checks_.begin(); it != checks_.end(); ++it) {
        if (it.value()->isChecked()) {
            elements.push_back(it.key().toStdString());
        }
    }
    chrome["title"] = chrome_title(chrome_reader_ != nullptr
                                       ? chrome_reader_()
                                       : Json::object())
                          .toStdString();
    chrome["elements"] = std::move(elements);
    return Json{{"template_id", selected_template_id().toStdString()},
                {"paper_size", paper_->currentData().toString().toStdString()},
                {"orientation",
                 orientation_->currentData().toString().toStdString()},
                {"map_chrome", std::move(chrome)}};
}

void LayoutComposePanel::rebuild_template_selector() {
    const QString current = template_->currentData().toString();
    template_->clear();
    const auto& library = composer_template_library();
    if (library.empty()) {
        // Honest empty state — the built-in library ships 9 templates,
        // so an empty list is a build anomaly, never silently hidden.
        template_->addItem(QStringLiteral("（无内置模板）"), QString());
        template_->setEnabled(false);
    } else {
        for (const auto& entry : library) {
            template_->addItem(QString::fromStdString(entry.label),
                               QString::fromStdString(entry.template_id));
        }
        template_->setEnabled(true);
        const int index = template_->findData(current);
        if (!current.isEmpty() && index >= 0) {
            template_->setCurrentIndex(index);
        }
    }
    hint_->setText(library.empty()
                       ? QStringLiteral("模板库为空（mapping_document 切片未接入）")
                       : QStringLiteral(
                             "版式模式：调整模板/纸张/整饰后导出；导出走既有"
                             " governed 动作并报告真实写入结果"));
}

void LayoutComposePanel::sync_chrome_checks() {
    const Json chrome =
        chrome_reader_ != nullptr ? chrome_reader_() : Json::object();
    syncing_ = true;
    for (auto it = checks_.begin(); it != checks_.end(); ++it) {
        it.value()->setChecked(chrome_has(chrome, it.key()));
    }
    syncing_ = false;
    update_preview();
}

void LayoutComposePanel::emit_chrome() {
    // The SAME payload shape MapChromePanel emits — the document stays
    // the single authority (F:69, no second chrome state).
    Json payload = Json::object();
    Json elements = Json::array();
    for (auto it = checks_.begin(); it != checks_.end(); ++it) {
        if (it.value()->isChecked()) {
            elements.push_back(it.key().toStdString());
        }
    }
    const Json current =
        chrome_reader_ != nullptr ? chrome_reader_() : Json::object();
    payload["title"] = chrome_title(current).toStdString();
    payload["elements"] = std::move(elements);
    if (chrome_writer_ != nullptr) {
        chrome_writer_(payload);
    }
    update_preview();
}

void LayoutComposePanel::update_preview() {
    preview_->update();
}

// ---------------------------------------------------------------------------
// preview painting (real template geometry, vector)
// ---------------------------------------------------------------------------

void ComposePreview::paintEvent(QPaintEvent* event) {
    QWidget::paintEvent(event);
    QPainter painter(this);
    painter.fillRect(rect(), QColor(0xf0, 0xf0, 0xf0));

    const QString paper_name = panel_->paper_selector()->currentData().toString();
    const auto paper_it = kPaperSizes.find(paper_name);
    if (paper_it == kPaperSizes.end()) {
        painter.setPen(QColor(0x53, 0x61, 0x6c));
        painter.drawText(rect(), Qt::AlignCenter,
                         QStringLiteral("选择纸张规格"));
        return;
    }
    double paper_w = paper_it->second.first;
    double paper_h = paper_it->second.second;
    if (panel_->orientation_selector()->currentData().toString() ==
        QStringLiteral("landscape")) {
        std::swap(paper_w, paper_h);
    }

    // Fit the paper into the widget with a margin.
    const double margin = 12.0;
    const double scale =
        std::min((width() - 2 * margin) / paper_w,
                 (height() - 2 * margin) / paper_h);
    const double w_px = paper_w * scale;
    const double h_px = paper_h * scale;
    const double x0 = (width() - w_px) / 2.0;
    const double y0 = (height() - h_px) / 2.0;

    painter.fillRect(QRectF(x0, y0, w_px, h_px), Qt::white);
    painter.setPen(QColor(0xcc, 0xd1, 0xd6));
    painter.drawRect(QRectF(x0, y0, w_px, h_px));
    painter.setPen(QColor(0x53, 0x61, 0x6c));
    painter.drawText(QRectF(x0, y0 - 14, w_px, 12), Qt::AlignLeft,
                     QStringLiteral("%1 %2 · %3×%4 mm")
                         .arg(paper_name,
                              panel_->orientation_selector()
                                  ->currentData()
                                  .toString())
                         .arg(paper_w, 0, 'f', 0)
                         .arg(paper_h, 0, 'f', 0));

    // The selected template's REAL element geometry (mm → px).
    const QString template_id = panel_->selected_template_id();
    const auto* entry =
        pwb::mapping_document::find_composer_template(template_id.toStdString());
    if (entry != nullptr) {
        const double template_w =
            entry->orientation == "landscape"
                ? std::max(paper_w, paper_h)
                : std::min(paper_w, paper_h);
        const double template_h =
            entry->orientation == "landscape"
                ? std::min(paper_w, paper_h)
                : std::max(paper_w, paper_h);
        const double offset_x = x0 + (w_px - template_w * scale) / 2.0;
        const double offset_y = y0 + (h_px - template_h * scale) / 2.0;
        painter.setPen(QPen(QColor(0x00, 0x78, 0xd4), 1, Qt::DashLine));
        for (const auto& def : entry->element_definitions) {
            const QRectF rect(offset_x + def.x_mm * scale,
                              offset_y + def.y_mm * scale,
                              def.width_mm * scale, def.height_mm * scale);
            painter.drawRect(rect);
            if (rect.height() >= 14) {
                painter.drawText(rect.adjusted(2, 1, -2, -1),
                                 Qt::AlignTop | Qt::AlignHCenter,
                                 QString::fromStdString(def.element_type));
            }
        }
        painter.setPen(QColor(0x53, 0x61, 0x6c));
        painter.drawText(QRectF(x0, y0 + h_px + 2, w_px, 12), Qt::AlignLeft,
                         QStringLiteral("模板：%1")
                             .arg(QString::fromStdString(entry->label)));
    }

    // Chrome decorations on the paper margin (real checked state).
    auto checked = [this](const QString& name) {
        return panel_->chrome_checked(name);
    };
    const bool legend = checked(QStringLiteral("图例"));
    const bool scale_bar = checked(QStringLiteral("比例尺"));
    const bool north = checked(QStringLiteral("指北针"));
    const bool title_bar = checked(QStringLiteral("标题栏"));
    painter.setPen(QColor(0x25, 0x31, 0x3d));
    if (title_bar) {
        painter.fillRect(QRectF(x0 + 8, y0 + 4, w_px - 16, 14),
                         QColor(0xd8, 0xeb, 0xef));
        painter.drawText(QRectF(x0 + 8, y0 + 4, w_px - 16, 14),
                         Qt::AlignCenter, QStringLiteral("标题栏"));
    }
    if (legend) {
        painter.fillRect(QRectF(x0 + w_px - 56, y0 + 24, 48, 40),
                         QColor(0xed, 0xf2, 0xf4));
        painter.drawRect(QRectF(x0 + w_px - 56, y0 + 24, 48, 40));
        painter.drawText(QRectF(x0 + w_px - 56, y0 + 24, 48, 12),
                         Qt::AlignCenter, QStringLiteral("图例"));
    }
    if (scale_bar) {
        painter.fillRect(QRectF(x0 + 12, y0 + h_px - 18, 72, 6),
                         QColor(0x25, 0x31, 0x3d));
        painter.drawText(QRectF(x0 + 12, y0 + h_px - 30, 72, 10),
                         Qt::AlignCenter, QStringLiteral("比例尺"));
    }
    if (north) {
        painter.drawText(QRectF(x0 + 10, y0 + 22, 20, 20), Qt::AlignCenter,
                         QStringLiteral("N"));
        painter.drawLine(QPointF(x0 + 20, y0 + 40), QPointF(x0 + 20, y0 + 26));
    }
}

}  // namespace pwb::app

#endif  // PWB_WITH_CLOSURE_MAPPING
