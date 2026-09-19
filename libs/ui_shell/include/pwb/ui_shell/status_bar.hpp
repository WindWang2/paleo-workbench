#pragma once

// Port of paleo_workbench/ui/status_bar.py (UI-01).
// 主状态条：工程名 · 工作台上下文 · 坐标段 · 引擎后端 badge。
// Engine badge 的 (text, style_class) 由 get_engine_status_info 判定：
// C++ 后端 + GL 探测 → GPU badge；C++ only → CPU native；否则 CPU Python。

#include <QFrame>
#include <QLabel>

#include <functional>
#include <map>
#include <string>
#include <utility>

namespace pwb::ui_shell {

// (badge_text, qss) for the current engine acceleration state. The GL probe
// is injected so offscreen CI never creates a GL context (Python checks
// QT_QPA_PLATFORM=offscreen first, then tries QOffscreenSurface +
// QOpenGLContext).
struct EngineProbe {
    std::function<bool()> has_cpp_backend;      // seismic_3d / well_log
    std::function<bool()> can_create_gl_context;
};

// Returns (badge_text, stylesheet). `palette` supplies the theme tokens
// (BADGE_SUCCESS/BADGE_PRIMARY/BADGE_WARNING); callers pass the live
// registry palette so the badge re-renders on theme change.
std::pair<QString, QString> engine_status_info(
    const EngineProbe& probe,
    const std::map<std::string, std::string>& palette);

class StatusBar : public QFrame {
    Q_OBJECT
public:
    explicit StatusBar(QWidget* parent = nullptr);

    // Inject the engine probe (default: no C++ backend, no GL → CPU badge).
    void set_engine_probe(EngineProbe probe);

    void update_engine_status(const QString& engine_name = QString());
    void set_project_name(const QString& name);
    // V6 §5 workbench segment — empty text hides, never shows an empty run.
    void set_workbench_context(const QString& text,
                               const QString& tooltip = QString());
    // Contextual segments; empty values hide. `horizon` is prefixed
    // "层位: ", `scale` with "1:"; segments join with "  ·  ".
    void update_context(const QString& coords = QString(),
                        const QString& horizon = QString(),
                        const QString& crs = QString(),
                        const QString& scale = QString());

private:
    QString engine_badge_sheet() const;

    QString project_name_ = QStringLiteral("未命名工程");
    EngineProbe probe_;
    QLabel* status_label_ = nullptr;
    QLabel* workbench_label_ = nullptr;
    QLabel* coord_label_ = nullptr;
    QLabel* engine_label_ = nullptr;
};

}  // namespace pwb::ui_shell
