// UI-08 — paleo_workbench/ui/pages/tag_widgets.py port (the inspector-side
// slice): TagBadge / TagContainerWidget / TagInputDialog. The governance
// dialogs (TagManagerDialog, bulk add/remove) are catalog-mutation
// surfaces and stay deferred (see ui-08-findings.md).
#pragma once

#include <QDialog>
#include <QWidget>

#include <QString>
#include <QStringList>
#include <vector>

class QHBoxLayout;
class QLabel;
class QLineEdit;
class QPushButton;

namespace pwb::ui_pages_mapedit {

class TagBadge : public QWidget {
    Q_OBJECT
public:
    explicit TagBadge(const QString& tag_name, bool removable = true,
                      QWidget* parent = nullptr);

    QString tag_name() const { return tag_name_; }

    // Python public attributes.
    QLabel* label = nullptr;
    QPushButton* remove_btn = nullptr;  // only when removable

signals:
    void remove_requested(const QString& tag_name);

private:
    QString tag_name_;
};

class TagContainerWidget : public QWidget {
    Q_OBJECT
public:
    explicit TagContainerWidget(bool removable = true,
                                QWidget* parent = nullptr);

    void set_tags(const QStringList& tags);
    QStringList tags() const { return tags_; }

    // Python public attribute.
    QPushButton* add_btn = nullptr;

signals:
    void tag_added(const QString& tag_name);
    void tag_removed(const QString& tag_name);

private:
    void on_remove_tag(const QString& tag_name);
    void prompt_add_tag();

    QStringList tags_;
    bool removable_ = true;
    QHBoxLayout* layout_ = nullptr;
};

class TagInputDialog : public QDialog {
    Q_OBJECT
public:
    explicit TagInputDialog(const QStringList& existing_tags = {},
                            QWidget* parent = nullptr);

    // input text stripped + leading '#' removed (Python get_tag_name).
    QString get_tag_name() const;

    // Python public attributes.
    QLabel* label = nullptr;
    QLineEdit* input = nullptr;
    QLabel* error_label = nullptr;

private:
    void validate_and_accept();

    QStringList existing_lower_;
};

}  // namespace pwb::ui_pages_mapedit
