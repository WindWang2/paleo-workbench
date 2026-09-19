#pragma once

// Port of paleo_workbench/ui/pages/lazy_visualization_tabs.py (UI-07):
// "数据列表" stack (table/text/well_log_summary) + "可视化预览" stack
// (prompt/loading/message/host). The geoviz host itself is NOT ported
// (viz/hosts domain, integration slice) — it is injected through a
// factory and managed as a QWidget*; the lazy-creation, no-steal and
// requested-latch contract is preserved exactly.

#include <QTabWidget>
#include <functional>
#include <string>
#include <utility>
#include <vector>

class QPushButton;
class QStackedWidget;
class QWidget;

#include <pwb/ui_pages_preview/lazy_tabs_state.hpp>

namespace pwb::ui_pages_preview {

class MessagePreviewWidget;
struct PreviewSettings;
class SummaryTablePreviewWidget;
class TablePreviewWidget;
class TextPreviewWidget;

// PreviewResult-shaped payload consumed by load_summary (preview_provider
// is UI-03 domain — the fields this widget reads are frozen here).
struct LazySummaryResult {
    std::string mode;  // "text" | "well_log" | other (→ summary table)
    std::string text;
    std::vector<std::pair<std::string, std::string>> summary_rows;
    std::vector<std::string> table_headers;
    std::vector<std::vector<std::string>> table_rows;
    std::string message;
    std::vector<std::string> data_headers;
    std::vector<std::vector<std::string>> data_rows;
};

class LazyVisualizationTabs : public QTabWidget {
    Q_OBJECT
public:
    explicit LazyVisualizationTabs(QWidget* parent = nullptr);

    // Host injection (GeoVizPreviewHost replacement): the factory is called
    // once, on first host() access, with this widget as parent. Throws
    // std::runtime_error if the host already exists — mirrors Python's
    // "cannot replace engine after visualization host creation".
    void set_host_factory(std::function<QWidget*(QWidget* parent)> factory);

    // Lazily creates the host through the factory and adds it to the visual
    // stack. Returns nullptr when no factory was set.
    QWidget* host();

    bool host_created() const { return host_ != nullptr; }
    bool requested() const { return state_.requested; }

    // load_summary(result): mode dispatch + reset to tab 0 + prompt page.
    void load_summary(const LazySummaryResult& result);

    // show_loading(): requested latch + loading page. No tab steal (#630).
    void show_loading();

    // show_preview(activate): the caller renders the host first (through
    // the concrete host type); this swaps the stack to it and applies the
    // tab contract — activate || already-on-visual-tab → tab 1.
    void show_preview(bool activate = true);

    void show_error(const QString& message, bool retryable = true,
                    bool activate = false);

    void reset();

    // Host lifecycle forwards — invoked via QMetaObject::invokeMethod so a
    // host without these slots degrades gracefully (QWidget base has none).
    void clear_host();
    void release_all();

    void apply_settings(const PreviewSettings& settings);

    TablePreviewWidget* summary() const { return summary_; }
    TextPreviewWidget* text() const { return text_; }
    SummaryTablePreviewWidget* well_log_summary() const {
        return well_log_summary_;
    }
    QStackedWidget* summary_stack() const { return summary_stack_; }
    QStackedWidget* visual_stack() const { return visual_stack_; }
    MessagePreviewWidget* prompt_label() const { return prompt_label_; }
    MessagePreviewWidget* loading_label() const { return loading_label_; }
    MessagePreviewWidget* message_label() const { return message_label_; }
    QPushButton* reload_button() const { return reload_button_; }

    // Test seam: the observable state-machine mirror.
    const LazyTabsState& state() const { return state_; }

signals:
    void visualization_requested();

private:
    void on_current_changed(int index);
    void request_retry();

    LazyTabsState state_;
    std::function<QWidget*(QWidget*)> host_factory_;
    QWidget* host_ = nullptr;

    TablePreviewWidget* summary_ = nullptr;
    TextPreviewWidget* text_ = nullptr;
    SummaryTablePreviewWidget* well_log_summary_ = nullptr;
    QStackedWidget* summary_stack_ = nullptr;
    QStackedWidget* visual_stack_ = nullptr;
    MessagePreviewWidget* prompt_label_ = nullptr;
    MessagePreviewWidget* loading_label_ = nullptr;
    QWidget* message_panel_ = nullptr;
    MessagePreviewWidget* message_label_ = nullptr;
    QPushButton* reload_button_ = nullptr;
};

}  // namespace pwb::ui_pages_preview
