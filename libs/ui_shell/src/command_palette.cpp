#include "pwb/ui_shell/command_palette.hpp"

#include <QEvent>
#include <QKeyEvent>
#include <QLineEdit>
#include <QListWidget>
#include <QVBoxLayout>

#include <pwb/ui_shell/command_registry.hpp>

namespace pwb::ui_shell {

namespace {
constexpr int kPaletteWidth = 360;
constexpr int kPaletteHeight = 320;
constexpr int kSpace2 = 8;
constexpr int kMenuBarHeight = 40;  // tokens.MENU_BAR_HEIGHT
constexpr int kFindLimit = 300;

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}
}  // namespace

CommandPalette::CommandPalette(
    QWidget* parent, CommandRegistry& registry,
    std::function<const CommandContext*()> context_provider)
    : QFrame(parent),
      registry_(registry),
      context_provider_(std::move(context_provider)) {
    setObjectName(QStringLiteral("PanelCard"));  // themed card chrome
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(kSpace2, kSpace2, kSpace2, kSpace2);
    layout->setSpacing(kSpace2);

    filter_input_ = new QLineEdit(this);
    filter_input_->setPlaceholderText(
        QStringLiteral("跳转到页面 / 子模块…"));
    filter_input_->installEventFilter(this);
    layout->addWidget(filter_input_);

    result_list_ = new QListWidget(this);
    result_list_->installEventFilter(this);
    layout->addWidget(result_list_, 1);

    QObject::connect(result_list_, &QListWidget::itemActivated, this,
                     &CommandPalette::activate_item);
    QObject::connect(result_list_, &QListWidget::itemClicked, this,
                     &CommandPalette::activate_item);
    QObject::connect(filter_input_, &QLineEdit::textChanged, this,
                     &CommandPalette::apply_filter);
    hide();
}

void CommandPalette::set_tool_details_provider(
    ToolDetailsProvider provider) {
    tool_details_provider_ = std::move(provider);
}

// BEGIN CPP-CLOSE-12 — function-level integration lease (see header).
void CommandPalette::set_context_provider(
    std::function<const CommandContext*()> provider) {
    context_provider_ = std::move(provider);
}
// END CPP-CLOSE-12

void CommandPalette::popup() {
    rebuild_commands();
    apply_filter(filter_input_->text());
    resize(kPaletteWidth, kPaletteHeight);
    QWidget* shell = parentWidget();
    if (shell != nullptr) {
        move(std::max(kSpace2, (shell->width() - width()) / 2),
             kMenuBarHeight + 92 + kSpace2);
    }
    show();
    raise();
    filter_input_->setFocus();
}

void CommandPalette::dismiss() {
    hide();
    filter_input_->clear();
}

void CommandPalette::set_filter_text(const QString& text) {
    // setText → textChanged → apply_filter (the input's own wiring).
    filter_input_->setText(text);
}

void CommandPalette::rebuild_commands() {
    // Commands come from ui.command_registry (pages/theme/density/preset/
    // panels); the registry is the single source — nothing to cache here.
}

void CommandPalette::apply_filter(const QString& text) {
    const QString query = text.trimmed();
    result_list_->clear();
    const CommandContext* context =
        context_provider_ ? context_provider_() : nullptr;
    // V6 §4: context filters/annotates applicability (disabled commands
    // stay discoverable). V11: limit raised — command count exceeds 50
    // (navigation+stage+mapping tools); truncation broke the
    // filtered-count < total invariant (test_app_shell caught it).
    std::vector<const CommandSpec*> specs =
        registry_.find(query.toStdString(), kFindLimit, context);
    if (query.isEmpty()) {
        // Empty query: most-recently-used first.
        const auto recents = registry_.recent_specs();
        std::vector<const CommandSpec*> ordered(recents.begin(),
                                                recents.end());
        for (const CommandSpec* spec : specs) {
            if (std::find(ordered.begin(), ordered.end(), spec) ==
                ordered.end()) {
                ordered.push_back(spec);
            }
        }
        specs = std::move(ordered);
    }
    for (const CommandSpec* spec : specs) {
        QString label = spec->hint.empty()
                            ? qstr(spec->label)
                            : qstr(spec->label) + QStringLiteral("  —  ") +
                                  qstr(spec->hint);
        if (!spec->shortcut_hint.empty()) {
            label += QStringLiteral("   [") + qstr(spec->shortcut_hint) +
                     QStringLiteral("]");
        }
        auto* item = new QListWidgetItem(label);
        item->setData(Qt::ItemDataRole::UserRole,
                      qstr(spec->id));
        if (context != nullptr) {
            const CommandAvailability availability =
                registry_.evaluate(spec->id, context);
            if (!availability.enabled) {
                // Disabled but discoverable: greyed + reason suffix, and
                // not activatable.
                item->setText(label + QStringLiteral("（") +
                              qstr(availability.reason) +
                              QStringLiteral("）"));
                item->setFlags(item->flags() &
                               ~Qt::ItemFlag::ItemIsEnabled);
            }
            // V11 (01-ui-audit A5): map-tool commands carry the full
            // explanation (requirements/impact/missing prerequisites) —
            // previously action_help.format_details had no UI consumer.
            if (spec->id.rfind("map:", 0) == 0 &&
                tool_details_provider_) {
                const QString details =
                    tool_details_provider_(spec->id.substr(4), *context);
                if (!details.isEmpty()) {
                    item->setToolTip(details);
                }
            }
        }
        result_list_->addItem(item);
    }
    if (result_list_->count() > 0) {
        result_list_->setCurrentRow(0);
    }
}

void CommandPalette::activate_item(QListWidgetItem* item) {
    if (item == nullptr) {
        return;
    }
    const std::string spec_id =
        item->data(Qt::ItemDataRole::UserRole).toString().toStdString();
    const CommandSpec* spec = registry_.get(spec_id);
    if (spec == nullptr) {
        return;
    }
    // V6 §4: disabled commands never execute (the palette stays open, the
    // reason remains visible).
    if (context_provider_) {
        const CommandContext* context = context_provider_();
        if (context != nullptr &&
            !registry_.evaluate(spec->id, context).enabled) {
            return;
        }
    }
    dismiss();
    if (spec->callback) {
        registry_.record_recent(spec->id);
        spec->callback();
    }
}

bool CommandPalette::eventFilter(QObject* source, QEvent* event) {
    if (event->type() == QEvent::Type::KeyPress) {
        auto* key_event = static_cast<QKeyEvent*>(event);
        // Esc dismisses from both the filter box and the result list; all
        // other keys are only intercepted in the filter box (the list
        // keeps native Up/Down/Enter navigation).
        if (key_event->key() == Qt::Key::Key_Escape) {
            dismiss();
            return true;
        }
        if (source == filter_input_) {
            const int key = key_event->key();
            if (key == Qt::Key::Key_Return || key == Qt::Key::Key_Enter) {
                activate_item(result_list_->currentItem());
                return true;
            }
            if (key == Qt::Key::Key_Down) {
                result_list_->setCurrentRow(
                    std::min(result_list_->currentRow() + 1,
                             result_list_->count() - 1));
                return true;
            }
            if (key == Qt::Key::Key_Up) {
                result_list_->setCurrentRow(
                    std::max(result_list_->currentRow() - 1, 0));
                return true;
            }
        }
    }
    return QFrame::eventFilter(source, event);
}

}  // namespace pwb::ui_shell
