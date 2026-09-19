#include "pwb/ui_shell/float_controller.hpp"

#include <QGuiApplication>
#include <QScreen>
#include <QSplitter>
#include <QWidget>

#include <pwb/ui_shell/dock_manager.hpp>
#include <pwb/ui_shell/floating_panel.hpp>
#include <pwb/ui_shell/layout_persistence.hpp>

namespace pwb::ui_shell {

namespace {

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

// Resolve a floating window title from the shared panel registry
// (Python _registry_title parity): registered title, else the trailing
// ":name" segment, else the key itself.
QString registry_title(const std::string& key) {
    const std::string title = dock_manager().panel_title(key);
    if (!title.empty()) {
        return qstr(title);
    }
    const auto pos = key.rfind(':');
    const std::string tail =
        pos == std::string::npos ? key : key.substr(pos + 1);
    return qstr(tail.empty() ? key : tail);
}

}  // namespace

QRect clamp_geometry_to_screens(const QRect& geometry) {
    const QList<QScreen*> screens = QGuiApplication::screens();
    if (screens.isEmpty()) {
        return geometry;
    }
    QRect visible = screens.first()->availableGeometry();
    for (qsizetype i = 1; i < screens.size(); ++i) {
        visible = visible.united(screens.at(i)->availableGeometry());
    }
    if (!geometry.intersects(visible)) {
        const QRect primary =
            QGuiApplication::primaryScreen() != nullptr
                ? QGuiApplication::primaryScreen()->availableGeometry()
                : visible;
        const QSize size = geometry.size().boundedTo(primary.size());
        return QRect(primary.x() + 24, primary.y() + 24, size.width(),
                     size.height());
    }
    const int x = std::min(
        std::max(geometry.x(), visible.left()),
        std::max(visible.left(), visible.right() - 60));
    const int y = std::min(
        std::max(geometry.y(), visible.top()),
        std::max(visible.top(), visible.bottom() - 60));
    return QRect(x, y, geometry.width(), geometry.height());
}

FloatController::FloatController(
    std::function<QWidget*(const std::string&)> resolver,
    LayoutPersistence* persistence,
    std::function<QString(const std::string&)> title_for, QObject* parent)
    : QObject(parent),
      resolver_(std::move(resolver)),
      persistence_(persistence),
      title_for_(std::move(title_for)) {
    if (!title_for_) {
        title_for_ = &registry_title;
    }
}

bool FloatController::float_panel(const std::string& key, QWidget* widget,
                                  std::optional<QRect> geometry) {
    if (floats_.count(key) != 0) {
        return false;
    }
    if (widget == nullptr) {
        widget = resolve(key);
    }
    if (widget == nullptr) {
        return false;
    }

    QWidget* dock_parent = widget->parentWidget();
    QSplitter* splitter = enclosing_splitter(widget);
    FloatRecord record;
    record.widget = widget;
    record.dock_parent = dock_parent;
    record.dock_parent_was_set = dock_parent != nullptr;
    record.dock_geometry = widget->geometry();
    record.splitter = splitter;
    if (splitter != nullptr) {
        record.splitter_index = splitter->indexOf(widget);
        const QList<int> sizes = splitter->sizes();
        record.restore_sizes =
            std::vector<int>(sizes.begin(), sizes.end());
    }

    FloatingPanel* panel = ensure_panel(key);
    panel->set_content(widget);
    // Floating implies revealing: a widget restored as docked-hidden would
    // otherwise surface as an empty floating window.
    widget->setVisible(true);
    QRect target = geometry.has_value()
                       ? *geometry
                       : default_geometry(widget, dock_parent);
    // V5-U6: a restored float geometry may land on a disconnected monitor —
    // clamp to the visible desktop so the panel is never lost.
    panel->setGeometry(clamp_geometry_to_screens(target));
    panel->show();
    floats_[key] = record;

    if (persistence_ != nullptr) {
        persistence_->save_float(key, target);
        if (record.restore_sizes.has_value() &&
            !record.restore_sizes->empty()) {
            persistence_->save_docked_sizes(key, *record.restore_sizes);
        }
    }
    emit float_changed(qstr(key), true);
    return true;
}

bool FloatController::dock_panel(const std::string& key) {
    const auto it = floats_.find(key);
    if (it == floats_.end()) {
        return false;
    }
    const FloatRecord record = it->second;
    // Dock parent or widget destroyed (its C++ side is gone — the parity
    // of Python's RuntimeError catch in _reinsert): keep the record so the
    // panel stays afloat rather than orphaning the widget.
    if (record.widget.isNull() || !can_reinsert(record)) {
        return false;
    }
    reinsert(record);
    floats_.erase(it);

    const auto pit = panels_.find(key);
    FloatingPanel* panel =
        pit == panels_.end() ? nullptr : pit->second.data();
    panels_.erase(key);
    if (panel != nullptr) {
        panel->close();
        panel->deleteLater();
    }

    if (persistence_ != nullptr) {
        persistence_->save_dock(
            key, record.restore_sizes.value_or(std::vector<int>{}));
    }
    emit float_changed(qstr(key), false);
    return true;
}

bool FloatController::toggle(const std::string& key, QWidget* widget) {
    if (is_floating(key)) {
        return dock_panel(key);
    }
    return float_panel(key, widget);
}

bool FloatController::is_floating(const std::string& key) const {
    return floats_.count(key) != 0;
}

std::vector<std::string> FloatController::floating_keys() const {
    std::vector<std::string> out;
    out.reserve(floats_.size());
    for (const auto& [key, record] : floats_) {
        out.push_back(key);
    }
    return out;
}

FloatingPanel* FloatController::floating_panel(const std::string& key) const {
    const auto it = panels_.find(key);
    return it == panels_.end() ? nullptr : it->second.data();
}

bool FloatController::restore_saved(const std::string& key, QWidget* widget) {
    if (persistence_ == nullptr) {
        return false;
    }
    const PanelLayoutRecord saved = persistence_->load(key);
    if (saved.is_empty()) {
        return false;
    }
    if (saved.floating) {
        if (!float_panel(key, widget, saved.geometry)) {
            return false;
        }
        if (!saved.visible) {
            FloatingPanel* panel = floating_panel(key);
            if (panel != nullptr) {
                panel->hide();
            }
            // Belt and suspenders: hideEvent already reports the hide, but
            // keep the explicit write so the store can never disagree with
            // the UI (P1-1: a desync would revive a panel the user hid on
            // the next launch).
            persistence_->save_visibility(key, false);
        }
        return true;
    }

    if (widget == nullptr) {
        widget = resolve(key);
    }
    if (widget == nullptr) {
        return false;
    }
    if (saved.docked_sizes.has_value()) {
        QSplitter* splitter = enclosing_splitter(widget);
        if (splitter != nullptr) {
            QList<int> sizes;
            sizes.reserve(static_cast<qsizetype>(saved.docked_sizes->size()));
            for (const int size : *saved.docked_sizes) {
                sizes.push_back(size);
            }
            splitter->setSizes(sizes);
        }
    }
    if (!saved.visible) {
        widget->setVisible(false);
    }
    return true;
}

QWidget* FloatController::resolve(const std::string& key) const {
    if (!resolver_) {
        return nullptr;
    }
    return resolver_(key);
}

bool FloatController::can_reinsert(const FloatRecord& record) const {
    if (record.splitter_index.has_value()) {
        // Splitter path: the splitter was alive at record time.
        return !record.splitter.isNull();
    }
    // Non-splitter path: setParent(nullptr) is legal, so only a *dead*
    // dock parent blocks reinsertion (Python RuntimeError parity).
    return !record.dock_parent_was_set || !record.dock_parent.isNull();
}

FloatingPanel* FloatController::ensure_panel(const std::string& key) {
    FloatingPanel* panel = floating_panel(key);
    if (panel == nullptr) {
        QWidget* parent_widget = qobject_cast<QWidget*>(parent());
        panel = new FloatingPanel(key, title_for_(key), parent_widget);
        QObject::connect(
            panel, &FloatingPanel::dock_back_requested, this,
            [this](const QString& k) { dock_panel(k.toStdString()); });
        QObject::connect(
            panel, &FloatingPanel::visibility_changed, this,
            [this](const QString& k, bool visible) {
                on_panel_visibility_changed(k.toStdString(), visible);
            });
        panels_[key] = panel;
    }
    return panel;
}

void FloatController::on_panel_visibility_changed(const std::string& key,
                                                  bool visible) {
    if (persistence_ != nullptr && floats_.count(key) != 0) {
        persistence_->save_visibility(key, visible);
    }
}

QSplitter* FloatController::enclosing_splitter(QWidget* widget) {
    QWidget* parent = widget != nullptr ? widget->parentWidget() : nullptr;
    while (parent != nullptr) {
        if (auto* splitter = qobject_cast<QSplitter*>(parent)) {
            return splitter;
        }
        parent = parent->parentWidget();
    }
    return nullptr;
}

QRect FloatController::default_geometry(QWidget* widget,
                                        QWidget* dock_parent) {
    const QSize size = widget->size().expandedTo(kDefaultFloatSize);
    QPoint origin;
    if (dock_parent != nullptr) {
        origin = dock_parent->mapToGlobal(dock_parent->rect().topLeft());
    } else {
        origin = QPoint(kDefaultFloatOffset, kDefaultFloatOffset);
    }
    origin += QPoint(kDefaultFloatOffset, kDefaultFloatOffset);
    return QRect(origin, size);
}

void FloatController::reinsert(const FloatRecord& record) {
    QWidget* widget = record.widget.data();
    if (!record.splitter.isNull() && record.splitter_index.has_value()) {
        QSplitter* splitter = record.splitter.data();
        const int index = std::min(*record.splitter_index, splitter->count());
        splitter->insertWidget(index, widget);
        if (record.restore_sizes.has_value()) {
            QList<int> sizes;
            sizes.reserve(
                static_cast<qsizetype>(record.restore_sizes->size()));
            for (const int size : *record.restore_sizes) {
                sizes.push_back(size);
            }
            splitter->setSizes(sizes);
        }
    } else {
        widget->setParent(record.dock_parent.data());
        widget->setGeometry(record.dock_geometry);
    }
    widget->setVisible(true);
}

std::vector<FloatablePanelEntry> floatable_panel_entries(
    FloatController& controller,
    const std::map<std::string, QWidget*>& panels) {
    std::vector<FloatablePanelEntry> entries;
    entries.reserve(panels.size());
    for (const auto& [key, widget] : panels) {
        FloatablePanelEntry entry;
        entry.key = key;
        entry.title = qstr(dock_manager().panel_title(key));
        const bool floating = controller.is_floating(key);
        entry.floating = floating;
        if (floating) {
            FloatingPanel* window = controller.floating_panel(key);
            entry.visible = window != nullptr && window->isVisible();
            entry.set_visible = [window](bool on) {
                if (window != nullptr) {
                    window->setVisible(on);
                }
            };
        } else {
            entry.visible = widget != nullptr && !widget->isHidden();
            entry.set_visible = [widget](bool on) {
                if (widget != nullptr) {
                    widget->setVisible(on);
                }
            };
        }
        entry.toggle_float = [&controller, key, widget] {
            controller.toggle(key, widget);
        };
        entries.push_back(std::move(entry));
    }
    return entries;
}

}  // namespace pwb::ui_shell
