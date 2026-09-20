// UI-06 — hub_page.py :: HubPage Qt shell.
//
// Pill switcher + QStackedWidget hosting sub-module pages; forwards
// activate_page and emits page_activated / submodule_changed.
#pragma once

#include <QWidget>

#include <functional>
#include <map>
#include <string>
#include <vector>

class QHBoxLayout;
class QPushButton;
class QStackedWidget;

namespace pwb::ui_pages_data::qt {

class HubPage : public QWidget {
    Q_OBJECT
public:
    explicit HubPage(int hub_index, QWidget* parent = nullptr);

    int hub_index() const { return hub_index_; }

    void add_submodule(const std::string& key, const QString& title,
                       QWidget* page);
    // CLOSURE-PREVIEW (task 04): swap an already-added sub-module's widget
    // in place (the composite data page replaces the bare management
    // workspace; pill row and key order stay stable). The old widget is
    // returned un-parented — the caller adopts or deletes it; nullptr when
    // the key is unknown (no-op).
    QWidget* replace_submodule(const std::string& key, QWidget* page);
    void finish();

    // Activate the sub-module key (no-op when unknown). emit=true also
    // fires submodule_changed (UI-driven switch parity).
    void switch_to(const std::string& key, bool emit = false);

    std::string current_key() const;
    QWidget* current_page() const;
    QWidget* page(const std::string& key) const;
    // Forward the shell's page-activation to the current sub-module.
    void activate_page();

    // Python calls page.activate_page() when the page exposes it — the C++
    // seam injects the callback per key (shell wiring registers it).
    void set_activate_fn(const std::string& key, std::function<void()> fn);

Q_SIGNALS:
    void submodule_changed(int hub_index, const QString& key);
    void page_activated(int hub_index, const QString& key);

private:
    int hub_index_;
    std::vector<std::string> keys_;
    std::vector<QPushButton*> buttons_;
    std::map<std::string, QWidget*> pages_;
    std::map<std::string, std::function<void()>> activate_fns_;
    QWidget* switcher_host_;
    QHBoxLayout* switcher_layout_;
    QStackedWidget* stack_;
    std::string current_;
};

}  // namespace pwb::ui_pages_data::qt
