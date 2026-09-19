#pragma once

// Port of paleo_workbench/ui/shortcuts.py (UI-01).
// 中央快捷键注册表（V5-U6）：所有应用级 QShortcut 经 register_shortcut
// 创建（记录 id/键/标签/回调归属），冲突检测报告同一 QKeySequence 的
// 重复注册（只告警不阻断）。Command Palette 从这里取 shortcut 展示文案。

#include <QKeySequence>
#include <QPointer>
#include <QShortcut>
#include <functional>
#include <map>
#include <string>
#include <vector>

namespace pwb::ui_shell {

struct ShortcutSpec {
    std::string id;
    std::string key;    // QKeySequence-parseable ("Ctrl+K")
    std::string label;  // display name (palette / docs)
};

class ShortcutRegistry {
public:
    // Create a QShortcut on `parent` and register it. Same-id re-register
    // replaces the old binding (deleteLater — the C++ side may already be
    // gone after a host-window teardown, so the pointer is only touched
    // through the tracked map).
    QShortcut* register_shortcut(
        QWidget* parent, const ShortcutSpec& spec,
        std::function<void()> callback,
        bool enabled_in_text_input = true,
        Qt::ShortcutContext context = Qt::ApplicationShortcut);

    // Register metadata only (the shortcut was created by legacy code;
    // palette display stays aligned).
    void register_meta(const ShortcutSpec& spec);
    void unregister(const std::string& spec_id);

    std::vector<ShortcutSpec> all_specs() const;  // sorted by key
    const ShortcutSpec* get(const std::string& spec_id) const;
    // Same-key duplicate registrations (id-deduped, >1 = conflict candidate;
    // the LAST registered wins at runtime — detection warns, never blocks).
    std::map<std::string, std::vector<ShortcutSpec>> conflicts() const;

private:
    void warn_conflicts(const ShortcutSpec& spec) const;

    std::map<std::string, ShortcutSpec> registry_;
    // QPointer auto-nulls when the parent widget tree destroys the
    // shortcut (shell teardown) — re-registration must never touch a
    // dangling pointer.
    std::map<std::string, QPointer<QShortcut>> shortcuts_;
};

// Current focus inside a text-input widget (guard's unified type list):
// QLineEdit/QTextEdit/QPlainTextEdit/QTextBrowser, QSpinBox/QDoubleSpinBox,
// editable QComboBox, and inline editors inside item views.
bool focus_in_text_input();

// Process-level registry (Python module-global parity).
ShortcutRegistry& shortcut_registry();

}  // namespace pwb::ui_shell
