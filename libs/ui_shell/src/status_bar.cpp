#include "pwb/ui_shell/status_bar.hpp"

#include <QHBoxLayout>

#include <pwb/platform_services/theme_tokens.hpp>
#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_shell {

namespace {

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

QString pal(const std::map<std::string, std::string>& palette,
            const char* key, const char* fallback) {
    const auto it = palette.find(key);
    return it == palette.end() ? QString::fromLatin1(fallback)
                               : qstr(it->second);
}

}  // namespace

std::pair<QString, QString> engine_status_info(
    const EngineProbe& probe,
    const std::map<std::string, std::string>& palette) {
    const bool has_cpp =
        probe.has_cpp_backend && probe.has_cpp_backend();
    const bool has_gl =
        probe.can_create_gl_context && probe.can_create_gl_context();

    // Badge colors use the BADGE_* tokens (deeper shades) so white text
    // clears WCAG 3:1 at bold 11px; WARNING/SUCCESS body tokens would not.
    const QString base = QStringLiteral(
        "color: #ffffff; padding: 2px 8px; border-radius: 4px;"
        " font-weight: 600; font-size: 11px;");
    if (has_gl && has_cpp) {
        return {QStringLiteral("GPU · OpenGL + C++"),
                QStringLiteral("background-color: %1; %2")
                    .arg(pal(palette, "BADGE_SUCCESS", "#2e7d32"), base)};
    }
    if (has_cpp) {
        return {QStringLiteral("CPU · Native C++"),
                QStringLiteral("background-color: %1; %2")
                    .arg(pal(palette, "BADGE_PRIMARY", "#1565c0"), base)};
    }
    return {QStringLiteral("CPU · Python"),
            QStringLiteral("background-color: %1; %2")
                .arg(pal(palette, "BADGE_WARNING", "#b26a00"), base)};
}

StatusBar::StatusBar(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("StatusBar"));
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(12, 0, 12, 0);  // SPACE_3
    layout->setSpacing(8);                      // SPACE_2
    status_label_ = new QLabel(
        QStringLiteral("就绪 · ") + project_name_, this);
    layout->addWidget(status_label_);

    // V6 §5 workbench segment: stage · edit target · backend · tasks
    // (UIContext-driven).
    workbench_label_ = new QLabel(QString(), this);
    workbench_label_->setObjectName(QStringLiteral("StatusWorkbenchLabel"));
    workbench_label_->hide();
    layout->addWidget(workbench_label_);
    layout->addStretch();

    coord_label_ = new QLabel(QString(), this);
    coord_label_->setObjectName(QStringLiteral("StatusCoordLabel"));
    coord_label_->hide();
    layout->addWidget(coord_label_);

    // GPU/CPU engine backend badge (style_bind: repaints on theme change).
    const auto [badge_text, sheet] =
        engine_status_info(probe_, style_palette());
    engine_label_ = new QLabel(badge_text, this);
    style_bind(engine_label_, [this] { return engine_badge_sheet(); });
    engine_label_->setToolTip(QStringLiteral("可视化与数据计算引擎状态"));
    layout->addWidget(engine_label_);
}

void StatusBar::set_engine_probe(EngineProbe probe) {
    probe_ = std::move(probe);
    update_engine_status();
    style_refresh(engine_label_);
}

QString StatusBar::engine_badge_sheet() const {
    return engine_status_info(probe_, style_palette()).second;
}

void StatusBar::update_engine_status(const QString& engine_name) {
    if (!engine_name.isEmpty()) {
        engine_label_->setText(engine_name);
        return;
    }
    engine_label_->setText(
        engine_status_info(probe_, style_palette()).first);
}

void StatusBar::set_project_name(const QString& name) {
    project_name_ = name;
    status_label_->setText(QStringLiteral("就绪 · ") + name);
}

void StatusBar::set_workbench_context(const QString& text,
                                      const QString& tooltip) {
    if (text.isEmpty()) {
        workbench_label_->hide();
        return;
    }
    workbench_label_->setText(text);
    workbench_label_->setToolTip(tooltip.isEmpty() ? text : tooltip);
    workbench_label_->show();
}

void StatusBar::update_context(const QString& coords, const QString& horizon,
                               const QString& crs, const QString& scale) {
    QStringList parts;
    if (!coords.isEmpty()) {
        parts.push_back(coords);
    }
    if (!horizon.isEmpty()) {
        parts.push_back(QStringLiteral("层位: ") + horizon);
    }
    if (!crs.isEmpty()) {
        parts.push_back(crs);
    }
    if (!scale.isEmpty()) {
        parts.push_back(QStringLiteral("1:") + scale);
    }
    if (parts.isEmpty()) {
        coord_label_->setText(QString());
        coord_label_->hide();
        return;
    }
    coord_label_->setText(parts.join(QStringLiteral("  ·  ")));
    coord_label_->show();
}

}  // namespace pwb::ui_shell
