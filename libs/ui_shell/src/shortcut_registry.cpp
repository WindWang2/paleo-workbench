#include "pwb/ui_shell/shortcut_registry.hpp"

#include <QAbstractItemView>
#include <QApplication>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QLineEdit>
#include <QLoggingCategory>
#include <QPlainTextEdit>
#include <QSpinBox>
#include <QTextBrowser>
#include <QTextEdit>
#include <QWidget>

#include <algorithm>

namespace pwb::ui_shell {

namespace {

Q_LOGGING_CATEGORY(lcShortcuts, "pwb.ui_shell.shortcuts")

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

}  // namespace

QShortcut* ShortcutRegistry::register_shortcut(
    QWidget* parent, const ShortcutSpec& spec,
    std::function<void()> callback,
    bool enabled_in_text_input,
    Qt::ShortcutContext context) {
    // Same-id re-register replaces the old binding; deleteLater because the
    // old object may already be a destroyed shell child.
    const auto old = shortcuts_.find(spec.id);
    if (old != shortcuts_.end() && old->second != nullptr) {
        old->second->deleteLater();
    }
    auto* shortcut = new QShortcut(QKeySequence(qstr(spec.key)), parent);
    shortcut->setContext(context);
    QObject::connect(shortcut, &QShortcut::activated, parent,
                     [callback, enabled_in_text_input] {
                         if (!enabled_in_text_input &&
                             focus_in_text_input()) {
                             return;
                         }
                         if (callback) {
                             callback();
                         }
                     });
    shortcuts_[spec.id] = shortcut;
    registry_[spec.id] = spec;
    warn_conflicts(spec);
    return shortcut;
}

void ShortcutRegistry::register_meta(const ShortcutSpec& spec) {
    registry_[spec.id] = spec;
}

void ShortcutRegistry::unregister(const std::string& spec_id) {
    registry_.erase(spec_id);
    shortcuts_.erase(spec_id);  // metadata only — the QShortcut lives/dies
                                // with its parent widget
}

std::vector<ShortcutSpec> ShortcutRegistry::all_specs() const {
    std::vector<ShortcutSpec> out;
    out.reserve(registry_.size());
    for (const auto& [id, spec] : registry_) {
        out.push_back(spec);
    }
    std::sort(out.begin(), out.end(),
              [](const ShortcutSpec& a, const ShortcutSpec& b) {
                  return a.key < b.key;
              });
    return out;
}

const ShortcutSpec* ShortcutRegistry::get(const std::string& spec_id) const {
    const auto it = registry_.find(spec_id);
    return it == registry_.end() ? nullptr : &it->second;
}

std::map<std::string, std::vector<ShortcutSpec>>
ShortcutRegistry::conflicts() const {
    std::map<std::string, std::map<std::string, ShortcutSpec>> by_key;
    for (const auto& [id, spec] : registry_) {
        by_key[spec.key][spec.id] = spec;  // id-dedup like the Python dict
    }
    std::map<std::string, std::vector<ShortcutSpec>> out;
    for (const auto& [key, specs] : by_key) {
        if (specs.size() > 1) {
            for (const auto& [id, spec] : specs) {
                out[key].push_back(spec);
            }
        }
    }
    return out;
}

void ShortcutRegistry::warn_conflicts(const ShortcutSpec& spec) const {
    std::vector<std::string> others;
    for (const auto& [id, existing] : registry_) {
        if (existing.key == spec.key && existing.id != spec.id) {
            others.push_back(existing.id);
        }
    }
    if (!others.empty()) {
        std::string joined;
        for (const auto& id : others) {
            joined += (joined.empty() ? "" : ", ") + id;
        }
        qCWarning(lcShortcuts,
                  "shortcut conflict on %s: %s vs %s",
                  qUtf8Printable(qstr(spec.key)),
                  qUtf8Printable(qstr(spec.id)),
                  qUtf8Printable(qstr(joined)));
    }
}

bool focus_in_text_input() {
    QWidget* w = QApplication::focusWidget();
    while (w != nullptr) {
        if (qobject_cast<QLineEdit*>(w) || qobject_cast<QTextEdit*>(w) ||
            qobject_cast<QPlainTextEdit*>(w) ||
            qobject_cast<QTextBrowser*>(w) || qobject_cast<QSpinBox*>(w) ||
            qobject_cast<QDoubleSpinBox*>(w)) {
            return true;
        }
        if (auto* combo = qobject_cast<QComboBox*>(w)) {
            if (combo->isEditable()) {
                return true;
            }
        }
        // Inline editors are children of the item view's viewport — walking
        // the parent chain reaches the view itself (QTreeView/QTableView).
        if (qobject_cast<QAbstractItemView*>(w)) {
            return true;
        }
        w = w->parentWidget();
    }
    return false;
}

ShortcutRegistry& shortcut_registry() {
    static ShortcutRegistry registry;
    return registry;
}

}  // namespace pwb::ui_shell
