#include <pwb/ui_map/map_chrome_panel.hpp>

#include <QCheckBox>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>
#include <QVBoxLayout>

#include <set>

#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_map {

namespace {

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

QString pal(const char* key, const char* fallback) {
    const auto palette = pwb::ui_shell::style_palette();
    const auto it = palette.find(key);
    return it == palette.end() ? QString::fromLatin1(fallback)
                               : qstr(it->second);
}

// E1: theme-bound label styles re-read the palette on every render.
QString label_qss() {
    return QStringLiteral(
               "color: %1; font-size: 11px;"
               " border: none; background: transparent;")
        .arg(pal("TEXT_SECONDARY", "#616161"));
}

QString value_qss() {
    return QStringLiteral(
               "color: %1; font-size: 14px; font-weight: 500;"
               " border: none; background: transparent;")
        .arg(pal("TEXT_PRIMARY", "#212121"));
}

QLabel* add_value(QVBoxLayout* layout, const QString& label_text,
                  const QString& value_text, QWidget* parent) {
    auto* label = new QLabel(label_text, parent);
    pwb::ui_shell::style_bind(label, label_qss);
    layout->addWidget(label);
    auto* value = new QLabel(value_text, parent);
    value->setWordWrap(true);
    pwb::ui_shell::style_bind(value, value_qss);
    layout->addWidget(value);
    return value;
}

}  // namespace

MapChromePanel::MapChromePanel(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("MapChromePanel"));
    setMinimumWidth(200);

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(16, 16, 16, 16);  // PAGE_MARGIN
    layout->setSpacing(12);                      // SPACE_3

    auto* title = new QLabel(QStringLiteral("图面要素"), this);
    title->setObjectName(QStringLiteral("MapDockTitle"));
    layout->addWidget(title);

    title_value_ = add_value(layout, QStringLiteral("图名"),
                             QStringLiteral("未设置"), this);
    elements_value_ = add_value(
        layout, QStringLiteral("已启用"),
        QStringLiteral("图例 / 指北针 / 比例尺 / 标题栏"), this);

    title_edit_ = new QLineEdit(this);
    title_edit_->setPlaceholderText(QStringLiteral("地图标题"));
    layout->addWidget(title_edit_);
    for (const auto& element : default_chrome_elements()) {
        auto* check = new QCheckBox(qstr(element), this);
        check->setChecked(true);
        element_checks_[element] = check;
        layout->addWidget(check);
        connect(check, &QCheckBox::toggled, this,
                [this](bool) { emit_changed(); });
    }
    connect(title_edit_, &QLineEdit::editingFinished, this,
            [this]() { emit_changed(); });

    layout->addStretch();
    save_btn_ = new QPushButton(QStringLiteral("保存编图草稿"), this);
    save_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    layout->addWidget(save_btn_);
    review_btn_ = new QPushButton(QStringLiteral("发送成图审核"), this);
    review_btn_->setObjectName(QStringLiteral("PrimaryButton"));
    layout->addWidget(review_btn_);
}

void MapChromePanel::update_state(const Json& document) {
    const Json chrome = document.is_object()
                            ? field_value(document, "map_chrome",
                                          Json::object())
                            : Json::object();
    std::string fallback = document.is_object()
                               ? field_value_str(document, "name", "")
                               : std::string();
    if (fallback.empty()) {
        fallback = "未设置";
    }
    std::string title = field_value_str(chrome, "title", "");
    if (title.empty()) {
        title = fallback;
    }
    Json elements = field_value(chrome, "elements", Json::array());
    if (!elements.is_array() || elements.empty()) {
        elements = Json::array();
        for (const auto& element : default_chrome_elements()) {
            elements.push_back(element);
        }
    }
    title_value_->setText(qstr(title));
    QStringList parts;
    std::set<std::string> enabled;
    for (const auto& element : elements) {
        if (element.is_string()) {
            enabled.insert(element.get<std::string>());
            parts << qstr(element.get<std::string>());
        }
    }
    elements_value_->setText(parts.join(QStringLiteral(" / ")));
    title_edit_->blockSignals(true);
    title_edit_->setText(qstr(title));
    title_edit_->blockSignals(false);
    for (auto& [element, check] : element_checks_) {
        check->blockSignals(true);
        check->setChecked(enabled.count(element) > 0);
        check->blockSignals(false);
    }
}

void MapChromePanel::emit_changed() {
    // DEFAULT_CHROME_ELEMENTS order (the std::map storage is byte-sorted
    // and would scramble the emitted tuple — Python iterates its dict in
    // declaration order).
    Json elements = Json::array();
    for (const auto& element : default_chrome_elements()) {
        const auto it = element_checks_.find(element);
        if (it != element_checks_.end() && it->second->isChecked()) {
            elements.push_back(element);
        }
    }
    emit chrome_changed(Json{{"title",
                              title_edit_->text().trimmed().toStdString()},
                             {"elements", std::move(elements)}});
}

std::string MapChromePanel::title_text() const {
    return title_value_->text().toStdString();
}

std::string MapChromePanel::elements_text() const {
    return elements_value_->text().toStdString();
}

Json MapChromePanel::current_chrome() const {
    Json elements = Json::array();
    for (const auto& element : default_chrome_elements()) {
        const auto it = element_checks_.find(element);
        if (it != element_checks_.end() && it->second->isChecked()) {
            elements.push_back(element);
        }
    }
    return Json{{"title", title_edit_->text().trimmed().toStdString()},
                {"elements", std::move(elements)}};
}

}  // namespace pwb::ui_map
