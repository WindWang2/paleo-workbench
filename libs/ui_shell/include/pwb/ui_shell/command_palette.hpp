#pragma once

// Port of paleo_workbench/ui/app_shell.py CommandPalette (UI-01).
// Ctrl+K quick-jump palette: searchable list of commands from the
// CommandRegistry (pages/theme/density/presets/panels). A plain child
// widget of the shell (no window flags, no modality) — safe under the
// offscreen CI platform. Filter matches labels/keywords; Enter or click
// activates, Esc dismisses.

#include <QFrame>

#include <functional>

class QLineEdit;
class QListWidget;
class QListWidgetItem;

namespace pwb::ui_shell {

class CommandRegistry;
struct CommandContext;

class CommandPalette : public QFrame {
    Q_OBJECT
public:
    // navigate: activate(command_id) → run the spec callback (default:
    // invoke spec.callback directly after record_recent).
    // context_provider: () -> const CommandContext* (V6 §4 applicability;
    //   may return nullptr = unconstrained). The pointer must stay valid
    //   for the duration of the call only.
    explicit CommandPalette(
        QWidget* parent,
        CommandRegistry& registry,
        std::function<const CommandContext*()> context_provider = nullptr);

    // "map:"-prefixed commands get a full explanation tooltip (V11 01-ui-
    // audit A5: requirements/impact/missing prerequisites). Injected so
    // UI-01 carries no dependency on the workstation action_help layer
    // (UI-12 domain). Signature: (tool_id, context) -> details text.
    using ToolDetailsProvider =
        std::function<QString(const std::string& tool_id,
                              const CommandContext& context)>;
    void set_tool_details_provider(ToolDetailsProvider provider);

    void popup();
    void dismiss();

    // Pre-fills the query text (Python parity: host-driven palette
    // injection — the workstation command line routes non-agent
    // commands here before popping the palette).
    void set_filter_text(const QString& text);

protected:
    bool eventFilter(QObject* source, QEvent* event) override;

private:
    void rebuild_commands();
    void apply_filter(const QString& text);
    void activate_item(QListWidgetItem* item);

    CommandRegistry& registry_;
    std::function<const CommandContext*()> context_provider_;
    ToolDetailsProvider tool_details_provider_;
    QLineEdit* filter_input_ = nullptr;
    QListWidget* result_list_ = nullptr;
};

}  // namespace pwb::ui_shell
