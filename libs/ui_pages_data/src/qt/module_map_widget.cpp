// UI-06 — module relationship canvas shell (see qt/module_map_widget.hpp).
// Layout geometry, arrow painting and label text are direct ports of
// module_relationship.py; badge/icon rendering goes through the injected
// seams documented in the header.
#include <pwb/ui_pages_data/qt/module_map_widget.hpp>

#include <QBrush>
#include <QColor>
#include <QCursor>
#include <QFontMetrics>
#include <QGridLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QMouseEvent>
#include <QPainter>
#include <QPen>
#include <QVBoxLayout>

#include <cmath>
#include <numbers>

#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_pages_data::qt {
namespace {

QString pal(const char* token) {
    const auto p = ui_shell::style_palette();
    const auto it = p.find(token);
    return it != p.end() ? QString::fromStdString(it->second) : QString();
}

// _STATUS_TONES mirrored (module_map::step_tone owns the core copy).
QString status_tone(const QString& status) {
    static const std::map<QString, QString> tones = {
        {"complete", "success"}, {"running", "primary"},
        {"pending", "neutral"},  {"warning", "warning"},
        {"failed", "error"},
    };
    const auto it = tones.find(status);
    return it != tones.end() ? it->second : QStringLiteral("neutral");
}

QString card_sheet(bool accented) {
    const QString border = accented ? pal("PRIMARY") : pal("BORDER");
    const QString hover_border = accented ? pal("ACCENT") : pal("PRIMARY");
    const QString header_bg =
        accented ? pal("BG_SELECTION") : pal("BG_SEARCH");
    const QString title_color =
        accented ? pal("PRIMARY") : pal("TEXT_PRIMARY");
    return QStringLiteral(R"(
        QFrame#ModuleCard, QFrame#DatabaseModuleCard {
            background-color: %1;
            border: 1px solid %2;
            border-radius: 4px;
        }
        QFrame#ModuleCard:hover, QFrame#DatabaseModuleCard:hover {
            border-color: %3;
            background-color: %1;
        }
        QFrame#ModuleCardHeader {
            background-color: %4;
            border: none;
            border-bottom: 1px solid %5;
            border-top-left-radius: 3px;
            border-top-right-radius: 3px;
        }
        QLabel#ModuleCardTitle {
            color: %6;
            background-color: transparent;
            font-weight: 600;
            font-size: 12.5px;
        }
        QLabel#ModuleCardItem {
            color: %6;
            font-size: 11.5px;
            background: transparent;
        }
        QLabel#ModuleCardMeta {
            color: %7;
            font-size: 10.5px;
            background: transparent;
        }
        QLabel#ModuleCardOutput {
            color: %8;
            font-size: 10.5px;
            font-weight: 500;
            background: transparent;
        }
    )")
        .arg(pal("BG_SIDEBAR"), border, hover_border, header_bg,
             pal("BORDER_LIGHT"), title_color, pal("TEXT_SECONDARY"),
             pal("ACCENT"));
}

QString sub_card_sheet() {
    return QStringLiteral(R"(
        QFrame#SubCard {
            background-color: %1;
            border: 1px solid %2;
            border-radius: 4px;
        }
        QFrame#SubCard:hover {
            border-color: %3;
            background-color: %4;
        }
    )")
        .arg(pal("BG_SIDEBAR"), pal("BORDER"), pal("PRIMARY"),
             pal("BG_MENU_HOVER"));
}

QString legend_sheet() {
    return QStringLiteral(R"(
        QFrame#LegendWidget {
            background-color: %1;
            border: 1px solid %2;
            border-radius: 4px;
        }
        QLabel#ModuleCardMeta {
            color: %3;
            font-size: 11px;
            font-weight: 500;
            background: transparent;
        }
    )")
        .arg(pal("BG_RAIL_BOTTOM"), pal("BORDER"), pal("TEXT_SECONDARY"));
}

}  // namespace

// ---------------------------------------------------------------------------
// StatusBadge — PwbBadge seam (tone-styled QLabel).

StatusBadge::StatusBadge(QWidget* parent) : QLabel(parent) {
    setObjectName(QStringLiteral("StatusBadge"));
    set_tone(QStringLiteral("neutral"));
}

void StatusBadge::set_tone(const QString& tone) {
    tone_ = tone;
    // Badge tones resolve to palette keys (PwbBadge tone map parity):
    // success→SUCCESS primary→PRIMARY warning→WARNING error→ERROR_RED.
    static const std::map<QString, QString> tone_colors = {
        {"success", "SUCCESS"},   {"primary", "PRIMARY"},
        {"warning", "WARNING"},   {"error", "ERROR_RED"},
        {"neutral", "TEXT_SECONDARY"},
    };
    const auto it = tone_colors.find(tone);
    const QString color = pal(
        (it != tone_colors.end() ? it->second : "TEXT_SECONDARY")
            .toUtf8()
            .constData());
    setStyleSheet(QStringLiteral(
                      "color: %1; font-size: 10.5px; font-weight: 500;"
                      " padding: 1px 6px; border: 1px solid %1;"
                      " border-radius: 8px; background: transparent;")
                      .arg(color));
}

// ---------------------------------------------------------------------------
// ModuleCard

ModuleCard::ModuleCard(const QString& title,
                       const std::vector<QString>& items,
                       const std::vector<QString>& inputs,
                       const std::vector<QString>& outputs, bool is_accented,
                       int page_index, QWidget* parent)
    : QFrame(parent), page_index_(page_index), accented_(is_accented) {
    setObjectName(QStringLiteral("ModuleCard"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);

    auto* header = new QFrame(this);
    header->setObjectName(QStringLiteral("ModuleCardHeader"));
    auto* header_layout = new QHBoxLayout(header);
    header_layout->setContentsMargins(12, 8, 12, 8);  // SPACE_L, 8
    auto* title_label = new QLabel(title, header);
    title_label->setObjectName(QStringLiteral("ModuleCardTitle"));
    header_layout->addWidget(title_label);
    header_layout->addStretch(1);
    status_badge_ = new StatusBadge(header);
    header_layout->addWidget(status_badge_);
    status_badge_->hide();
    layout->addWidget(header);

    auto* body = new QFrame(this);
    body->setObjectName(QStringLiteral("ModuleCardBody"));
    auto* body_layout = new QVBoxLayout(body);
    body_layout->setContentsMargins(12, 8, 12, 12);  // SPACE_L,8,SPACE_L,SPACE_L
    body_layout->setSpacing(6);
    for (const QString& item : items) {
        auto* label = new QLabel(item, body);
        label->setObjectName(QStringLiteral("ModuleCardItem"));
        label->setWordWrap(true);
        body_layout->addWidget(label);
    }
    if (!inputs.empty() || !outputs.empty()) {
        auto* divider = new QFrame(body);
        divider->setFrameShape(QFrame::Shape::HLine);
        divider->setStyleSheet(
            QStringLiteral(
                "color: %1; background-color: %1; max-height: 1px;")
                .arg(pal("BORDER")));
        body_layout->addWidget(divider);
    }
    if (!inputs.empty()) {
        QString joined;
        for (std::size_t i = 0; i < inputs.size(); ++i) {
            if (i) joined += QStringLiteral(", ");
            joined += inputs[i];
        }
        auto* label = new QLabel(QStringLiteral("<b>输入:</b> ") + joined,
                                 body);
        label->setObjectName(QStringLiteral("ModuleCardMeta"));
        label->setWordWrap(true);
        body_layout->addWidget(label);
    }
    if (!outputs.empty()) {
        QString joined;
        for (std::size_t i = 0; i < outputs.size(); ++i) {
            if (i) joined += QStringLiteral(", ");
            joined += outputs[i];
        }
        auto* label = new QLabel(QStringLiteral("<b>输出:</b> ") + joined,
                                 body);
        label->setObjectName(QStringLiteral("ModuleCardOutput"));
        label->setWordWrap(true);
        body_layout->addWidget(label);
    }
    layout->addWidget(body);

    ui_shell::style_bind(this, [this] { return card_sheet(accented_); });
    setCursor(QCursor(Qt::CursorShape::PointingHandCursor));
}

void ModuleCard::mousePressEvent(QMouseEvent* event) {
    if (event->button() == Qt::MouseButton::LeftButton) {
        Q_EMIT clicked(page_index_);
    }
    QFrame::mousePressEvent(event);
}

void ModuleCard::set_status(const QString& status) {
    status_badge_->setText(
        QString::fromStdString(std::string(module_status_text(
            status.toStdString()))));
    status_badge_->set_tone(status_tone(status));
    status_badge_->show();
}

// ---------------------------------------------------------------------------
// SubCard

IconProviderFn SubCard::icon_provider_;

SubCard::SubCard(const QString& title, const std::string& icon_name,
                 int page_index, QWidget* parent)
    : QFrame(parent), page_index_(page_index), icon_name_(icon_name) {
    setObjectName(QStringLiteral("SubCard"));
    ui_shell::style_bind(this, sub_card_sheet);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(12, 8, 12, 8);      // SPACE_L, 8
    layout->setAlignment(Qt::AlignmentFlag::AlignCenter);
    layout->setSpacing(4);
    icon_label_ = new QLabel(this);
    icon_label_->setAlignment(Qt::AlignmentFlag::AlignCenter);
    layout->addWidget(icon_label_);
    auto* text_label = new QLabel(title, this);
    text_label->setObjectName(QStringLiteral("ModuleCardItem"));
    text_label->setAlignment(Qt::AlignmentFlag::AlignCenter);
    layout->addWidget(text_label);
    setCursor(QCursor(Qt::CursorShape::PointingHandCursor));
    refresh_icon();
}

void SubCard::set_icon_provider(IconProviderFn fn) {
    icon_provider_ = std::move(fn);
}

bool SubCard::event(QEvent* event) {
    // StyleChange → re-tint the icon (Python event() parity; the bound-
    // method teardown concern is a Python detail — C++ uses a plain member).
    if (event->type() == QEvent::Type::StyleChange) {
        refresh_icon();
    }
    return QFrame::event(event);
}

void SubCard::refresh_icon() {
    if (icon_provider_) {
        icon_label_->setPixmap(
            icon_provider_(icon_name_, pal("TEXT_SECONDARY"), 20));
    }
}

void SubCard::mousePressEvent(QMouseEvent* event) {
    if (event->button() == Qt::MouseButton::LeftButton) {
        Q_EMIT clicked(page_index_);
    }
    QFrame::mousePressEvent(event);
}

// ---------------------------------------------------------------------------
// DatabaseModuleCard

DatabaseModuleCard::DatabaseModuleCard(
    const QString& title,
    const std::vector<std::tuple<QString, std::string, int>>& sub_items,
    QWidget* parent)
    : QFrame(parent) {
    setObjectName(QStringLiteral("DatabaseModuleCard"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    auto* header = new QFrame(this);
    header->setObjectName(QStringLiteral("ModuleCardHeader"));
    auto* header_layout = new QHBoxLayout(header);
    header_layout->setContentsMargins(12, 8, 12, 8);
    auto* title_label = new QLabel(title, header);
    title_label->setObjectName(QStringLiteral("ModuleCardTitle"));
    header_layout->addWidget(title_label);
    header_layout->addStretch(1);
    status_badge_ = new StatusBadge(header);
    header_layout->addWidget(status_badge_);
    status_badge_->hide();
    layout->addWidget(header);

    auto* body = new QFrame(this);
    body->setObjectName(QStringLiteral("ModuleCardBody"));
    auto* body_layout = new QHBoxLayout(body);
    body_layout->setContentsMargins(16, 12, 16, 12);  // 16, SPACE_L
    body_layout->setSpacing(20);
    for (const auto& [label, icon, sub_page_index] : sub_items) {
        auto* sub_card = new SubCard(label, icon, sub_page_index, body);
        connect(sub_card, &SubCard::clicked, this,
                &DatabaseModuleCard::clicked);
        body_layout->addWidget(sub_card);
    }
    layout->addWidget(body);
    ui_shell::style_bind(this, [] { return card_sheet(false); });
}

void DatabaseModuleCard::set_status(const QString& status) {
    status_badge_->setText(
        QString::fromStdString(std::string(module_status_text(
            status.toStdString()))));
    status_badge_->set_tone(status_tone(status));
    status_badge_->show();
}

// ---------------------------------------------------------------------------
// _LegendLine + LegendWidget

namespace {

class LegendLine : public QWidget {
public:
    explicit LegendLine(const QString& kind, QWidget* parent = nullptr)
        : QWidget(parent), kind_(kind) {
        setFixedSize(22, 12);
    }

protected:
    void paintEvent(QPaintEvent*) override {
        QPainter painter(this);
        painter.setRenderHint(QPainter::RenderHint::Antialiasing);
        QPen pen(QColor(pal("PRIMARY")), 1.5);
        pen.setCapStyle(Qt::PenCapStyle::FlatCap);
        if (kind_ == QLatin1String("dashed")) {
            pen.setColor(QColor(pal("ACCENT")));
            pen.setStyle(Qt::PenStyle::DashLine);
            pen.setDashPattern({2.0, 2.0});
        }
        painter.setPen(pen);
        const int y = static_cast<int>(height() / 2);
        if (kind_ == QLatin1String("double")) {
            painter.drawLine(2, y - 2, width() - 4, y - 2);
            painter.drawLine(2, y + 2, width() - 4, y + 2);
        } else if (kind_ == QLatin1String("rect")) {
            painter.setPen(QPen(QColor(pal("BORDER_STRONG")), 1));
            painter.setBrush(QBrush(QColor(pal("BG_SIDEBAR"))));
            painter.drawRect(4, 2, width() - 10, height() - 5);
        } else {
            painter.drawLine(2, y, width() - 4, y);
        }
        painter.end();
    }

private:
    QString kind_;
};

}  // namespace

LegendWidget::LegendWidget(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("LegendWidget"));
    ui_shell::style_bind(this, legend_sheet);
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(16, 6, 16, 6);
    layout->setSpacing(24);
    layout->setAlignment(Qt::AlignmentFlag::AlignCenter);
    const std::pair<const char*, const char*> items[] = {
        {"主要数据流/成果流", "solid"},
        {"双向交互/反馈", "double"},
        {"数据供给/支撑", "dashed"},
        {"模块内部输入输出", "rect"},
    };
    for (const auto& [text, kind] : items) {
        auto* lbl_layout = new QHBoxLayout();
        lbl_layout->setSpacing(6);
        lbl_layout->addWidget(
            new LegendLine(QString::fromUtf8(kind), this));
        auto* label = new QLabel(QString::fromUtf8(text), this);
        label->setObjectName(QStringLiteral("ModuleCardMeta"));
        lbl_layout->addWidget(label);
        layout->addLayout(lbl_layout);
    }
}

// ---------------------------------------------------------------------------
// ModuleRelationshipCanvas

ModuleRelationshipCanvas::ModuleRelationshipCanvas(QWidget* parent)
    : QWidget(parent) {
    setObjectName(QStringLiteral("ModuleRelationshipCanvas"));
    setMinimumWidth(kMinCanvasWidth);
    setMinimumHeight(520);

    auto* grid = new QGridLayout(this);
    grid->setContentsMargins(15, 10, 15, 10);
    grid->setHorizontalSpacing(90);
    grid->setVerticalSpacing(65);

    // Card construction data comes from the core spec table so the Python
    // __init__ literals live in one oracle-checkable place.
    std::map<std::string, ModuleCard**> card_slots = {
        {"sequence", &card_sequence_}, {"well", &card_well_},
        {"seismic", &card_seismic_},   {"facies", &card_facies_},
        {"mapping", &card_mapping_},
    };
    for (const auto& spec : module_card_specs()) {
        if (spec.key == "data") continue;
        std::vector<QString> items, inputs, outputs;
        for (const auto& s : spec.items) items.push_back(QString::fromStdString(s));
        for (const auto& s : spec.inputs) inputs.push_back(QString::fromStdString(s));
        for (const auto& s : spec.outputs) outputs.push_back(QString::fromStdString(s));
        auto* card = new ModuleCard(QString::fromStdString(spec.title),
                                    items, inputs, outputs, spec.accented,
                                    spec.page_index, this);
        card->setMinimumWidth(spec.min_width);
        grid->addWidget(card, spec.grid_row, spec.grid_col,
                        spec.grid_row_span, spec.grid_col_span,
                        spec.align_center ? Qt::AlignmentFlag::AlignCenter
                                          : Qt::AlignmentFlag::AlignTop);
        *card_slots[spec.key] = card;
    }
    // DatabaseModuleCard (row 2, spans 3 columns).
    const ModuleCardSpec* data_spec = nullptr;
    for (const auto& spec : module_card_specs()) {
        if (spec.key == "data") data_spec = &spec;
    }
    std::vector<std::tuple<QString, std::string, int>> sub_items;
    for (const auto& [label, icon, idx] : data_spec->sub_items) {
        sub_items.emplace_back(QString::fromStdString(label), icon, idx);
    }
    card_data_ = new DatabaseModuleCard(
        QString::fromStdString(data_spec->title), sub_items, this);
    card_data_->setMinimumWidth(data_spec->min_width);
    grid->addWidget(card_data_, data_spec->grid_row, data_spec->grid_col,
                    data_spec->grid_row_span, data_spec->grid_col_span,
                    Qt::AlignmentFlag::AlignCenter);

    for (const auto& [key, slot] : card_slots) {
        connect(*slot, &ModuleCard::clicked, this,
                &ModuleRelationshipCanvas::navigation_requested);
    }
    connect(card_data_, &DatabaseModuleCard::clicked, this,
            &ModuleRelationshipCanvas::navigation_requested);
}

void ModuleRelationshipCanvas::update_states(
    const std::vector<StepLike>& steps) {
    const auto states = step_card_states(steps);
    auto apply = [&](const char* key, auto* card) {
        card->set_status(
            QString::fromStdString(states.at(key).status));
    };
    apply("data", card_data_);
    apply("sequence", card_sequence_);
    apply("well", card_well_);
    apply("seismic", card_seismic_);
    apply("facies", card_facies_);
    apply("mapping", card_mapping_);
}

void ModuleRelationshipCanvas::paintEvent(QPaintEvent* event) {
    QWidget::paintEvent(event);
    QPainter painter(this);
    painter.setRenderHint(QPainter::RenderHint::Antialiasing);
    draw_parallel_horizontal_arrows(painter);
    draw_vertical_framework_seismic_connection(painter);
    draw_vertical_framework_facies_connection(painter);
    draw_horizontal_facies_mapping_connection(painter);
    draw_database_support_arrows(painter);
    painter.end();
}

void ModuleRelationshipCanvas::draw_directed_arrow(
    QPainter& painter, const QPoint& start, const QPoint& end,
    const QString& text, const QString& text_pos, bool is_dashed,
    const QString& color_hex) {
    const QString hex = color_hex.isEmpty() ? pal("PRIMARY") : color_hex;
    const QColor color(hex);
    QPen pen(color, 1.5);
    if (is_dashed) pen.setStyle(Qt::PenStyle::DashLine);
    painter.setPen(pen);
    painter.setBrush(QBrush(color));
    painter.drawLine(start, end);

    const double dx = end.x() - start.x();
    const double dy = end.y() - start.y();
    const double angle = std::atan2(dy, dx);
    constexpr double kArrowSize = 7;
    constexpr double kPi = std::numbers::pi;
    const QPoint p1(
        static_cast<int>(end.x() - kArrowSize * std::cos(angle - kPi / 6)),
        static_cast<int>(end.y() - kArrowSize * std::sin(angle - kPi / 6)));
    const QPoint p2(
        static_cast<int>(end.x() - kArrowSize * std::cos(angle + kPi / 6)),
        static_cast<int>(end.y() - kArrowSize * std::sin(angle + kPi / 6)));
    painter.drawPolygon(QPolygon() << end << p1 << p2);

    if (!text.isEmpty()) {
        QFont font = this->font();
        font.setPointSize(9);
        painter.setFont(font);
        painter.setPen(QColor(pal("TEXT_SECONDARY")));
        const double mid_x = (start.x() + end.x()) / 2.0;
        const double mid_y = (start.y() + end.y()) / 2.0;
        const QStringList lines = text.split(QLatin1Char('\n'));
        const QFontMetrics metrics(font);
        const int line_height = metrics.height();
        for (int i = 0; i < lines.size(); ++i) {
            const QString& line = lines[i];
            const int text_width = metrics.horizontalAdvance(line);
            if (text_pos == QLatin1String("top")) {
                const int offset_y =
                    -(lines.size() - 1 - i) * line_height - 6;
                painter.drawText(static_cast<int>(mid_x - text_width / 2.0),
                                 static_cast<int>(mid_y + offset_y), line);
            } else if (text_pos == QLatin1String("bottom")) {
                const int offset_y = i * line_height + 15;
                painter.drawText(static_cast<int>(mid_x - text_width / 2.0),
                                 static_cast<int>(mid_y + offset_y), line);
            } else if (text_pos == QLatin1String("left")) {
                const int offset_y = static_cast<int>(
                    (i - lines.size() / 2.0 + 0.5) * line_height);
                painter.drawText(
                    static_cast<int>(mid_x - text_width - 8),
                    static_cast<int>(mid_y + offset_y + line_height / 3.0),
                    line);
            } else if (text_pos == QLatin1String("right")) {
                const int offset_y = static_cast<int>(
                    (i - lines.size() / 2.0 + 0.5) * line_height);
                painter.drawText(
                    static_cast<int>(mid_x + 8),
                    static_cast<int>(mid_y + offset_y + line_height / 3.0),
                    line);
            }
        }
    }
}

void ModuleRelationshipCanvas::draw_parallel_horizontal_arrows(
    QPainter& painter) {
    const QRect geom_well = card_well_->geometry();
    const QRect geom_seismic = card_seismic_->geometry();
    const int y_center = geom_well.top() + 85;
    const int y_top = y_center - 10;
    const int y_bottom = y_center + 10;
    draw_directed_arrow(painter,
                        QPoint(geom_well.right() + 4, y_top),
                        QPoint(geom_seismic.left() - 4, y_top),
                        QStringLiteral("提供井控信息\n约束与验证"),
                        QStringLiteral("top"));
    draw_directed_arrow(painter,
                        QPoint(geom_seismic.left() - 4, y_bottom),
                        QPoint(geom_well.right() + 4, y_bottom),
                        QStringLiteral("反馈地震相结果\n辅助单井解释"),
                        QStringLiteral("bottom"));
}

void ModuleRelationshipCanvas::draw_vertical_framework_seismic_connection(
    QPainter& painter) {
    const QRect geom_seq = card_sequence_->geometry();
    const QRect geom_seismic = card_seismic_->geometry();
    const int x_center = geom_seismic.center().x();
    draw_directed_arrow(painter, QPoint(x_center, geom_seq.bottom() + 4),
                        QPoint(x_center, geom_seismic.top() - 4),
                        QStringLiteral("提供层序格架\n约束条件"),
                        QStringLiteral("left"));
}

void ModuleRelationshipCanvas::draw_vertical_framework_facies_connection(
    QPainter& painter) {
    const QRect geom_seq = card_sequence_->geometry();
    const QRect geom_facies = card_facies_->geometry();
    const int x_center = geom_facies.center().x();
    const int x_left = x_center - 12;
    const int x_right = x_center + 12;
    draw_directed_arrow(painter, QPoint(x_left, geom_facies.top() - 4),
                        QPoint(x_left, geom_seq.bottom() + 4),
                        QStringLiteral("地层层序检查\n调整与更新"),
                        QStringLiteral("left"));
    draw_directed_arrow(painter, QPoint(x_right, geom_seq.bottom() + 4),
                        QPoint(x_right, geom_facies.top() - 4));
}

void ModuleRelationshipCanvas::draw_horizontal_facies_mapping_connection(
    QPainter& painter) {
    const QRect geom_facies = card_facies_->geometry();
    const QRect geom_mapping = card_mapping_->geometry();
    const int y_center = geom_facies.top() + 85;
    draw_directed_arrow(painter, QPoint(geom_facies.right() + 4, y_center),
                        QPoint(geom_mapping.left() - 4, y_center),
                        QStringLiteral("提供解释成果\n与图版方案"),
                        QStringLiteral("top"));
}

void ModuleRelationshipCanvas::draw_database_support_arrows(
    QPainter& painter) {
    const QRect geom_data = card_data_->geometry();
    const int y_top = geom_data.top() - 4;
    const QString accent = pal("ACCENT");
    for (QWidget* card :
         {static_cast<QWidget*>(card_well_), static_cast<QWidget*>(card_seismic_),
          static_cast<QWidget*>(card_facies_), static_cast<QWidget*>(card_sequence_)}) {
        const int x = card->geometry().center().x();
        draw_directed_arrow(painter, QPoint(x, y_top),
                            QPoint(x, card->geometry().bottom() + 4),
                            QString(), QStringLiteral("top"), true, accent);
    }
}

// ---------------------------------------------------------------------------
// ModuleRelationshipWidget

ModuleRelationshipWidget::ModuleRelationshipWidget(QWidget* parent)
    : QWidget(parent) {
    setObjectName(QStringLiteral("ModuleRelationshipWidget"));
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    canvas_ = new ModuleRelationshipCanvas(this);
    connect(canvas_, &ModuleRelationshipCanvas::navigation_requested, this,
            &ModuleRelationshipWidget::navigation_requested);
    layout->addWidget(canvas_, 0, Qt::AlignmentFlag::AlignCenter);
}

void ModuleRelationshipWidget::update_states(
    const std::vector<StepLike>& steps) {
    canvas_->update_states(steps);
}

}  // namespace pwb::ui_pages_data::qt
