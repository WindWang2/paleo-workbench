#pragma once

// Port of paleo_workbench/ui/command_registry.py (UI-01).
// 命令注册表（V5-U6 / V6）：Command Palette 的唯一真源。
//
// Qt-free: recents persistence goes through an injected SettingsSink; the qt
// target binds it to QSettings (PaleoWorkbench/Workstation, key
// "ui/recent_commands"). Context is duck-typed in Python — here it is a
// concrete CommandContext base that domain snapshots may subclass.

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_shell {

inline constexpr int kRecentMax = 8;

// Duck-typed context replacement. Domain snapshots (UIContextSnapshot port)
// may subclass and carry more fields; applicability predicates receive the
// base reference and may downcast.
struct CommandContext {
    bool write_granted = false;
    std::optional<std::string> mapping_stage;
    virtual ~CommandContext() = default;
};

struct CommandSpec {
    std::string id;
    std::string label;
    std::string hint;
    std::string keywords;
    std::string shortcut_hint;
    std::function<void()> callback;
    // Group name (palette display order: recents -> by label).
    std::string group;
    // V6 applicability metadata (all optional; empty = any context).
    std::vector<std::string> context_tags;
    // Stage whitelist (stage values; empty = all stages).
    std::vector<std::string> stages;
    bool requires_write = false;
    // Unavailable commands hide from the palette (default: keep + show the
    // disabled reason — discoverability first).
    bool hidden_when_unavailable = false;
    // Domain predicate evaluated AFTER stage/permission gates: returns a
    // human-readable disable reason, or nullopt/empty when available.
    std::function<std::optional<std::string>(const CommandContext&)>
        applicability;
};

struct CommandAvailability {
    bool enabled = false;
    // Mandatory when enabled == false (Python contract).
    std::string reason;
};

// Recents persistence seam — the qt side binds QSettings. load() returns the
// stored id list; save() persists it.
struct RecentSettingsSink {
    std::function<std::vector<std::string>()> load;
    std::function<void(const std::vector<std::string>&)> save;
};

class CommandRegistry {
public:
    CommandRegistry() = default;

    // Registration is idempotent: same-id re-register replaces (debug log).
    void register_command(const CommandSpec& spec);
    void unregister(const std::string& command_id);
    // keep_core preserves "core:"-prefixed commands (test isolation aid).
    void clear(bool keep_core = true);

    // Sorted by (group, label) — Python tuple-key parity.
    std::vector<const CommandSpec*> specs() const;
    const CommandSpec* get(const std::string& command_id) const;

    // Evaluate availability under `context`. nullptr context -> always
    // available (V5 compatibility path). Order: existence -> WRITE grant ->
    // stage whitelist (fail-closed on unknown stage) -> domain predicate
    // (exception -> unavailable). Disabled always carries a reason.
    CommandAvailability evaluate(const std::string& command_id,
                                 const CommandContext* context) const;

    // Subsequence fuzzy match (label primary; keywords/tags/hint weak +10;
    // prefix hit -5). With context: hidden_when_unavailable commands are
    // filtered out; the rest stay so the palette can render reasons.
    std::vector<const CommandSpec*> find(const std::string& query,
                                         int limit = 50,
                                         const CommandContext* context =
                                             nullptr) const;

    // Recents (SettingsSink-backed; no-op when no sink bound).
    void record_recent(const std::string& command_id);
    std::vector<const CommandSpec*> recent_specs() const;
    void load_recent();
    void bind_settings(RecentSettingsSink sink);

private:
    std::map<std::string, CommandSpec> specs_;
    std::vector<std::string> recent_;
    RecentSettingsSink sink_;
};

// Subsequence hit -> start index (lower is better); -1 on miss.
// Whitespace in needle is skipped (Python parity).
int subsequence_score(const std::string& needle, const std::string& haystack);

// ASCII-case-insensitive lowercase (command matching is CJK/pinyin — byte
// lowercase is sufficient and locale-independent).
std::string ascii_lower(const std::string& text);

// Process-level registry (Python module-global `command_registry` parity).
CommandRegistry& command_registry();

}  // namespace pwb::ui_shell
