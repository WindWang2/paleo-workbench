#pragma once

// Well-log track settings panel for the platform's 测井 dock (PWB_WITH_WELL_LOG).
//
// Thin Qt glue over pwb::viz::WellLogTrackLayout + WellLogHostWidget: the
// layout model and its semantics live in the Qt-free visualization layer
// (parity-tested against the Python oracle); this panel only edits and
// applies them, and offers template JSON persistence plus engine-backed
// exports. Replaces the Python WellLogCanvasPanel/TrackSettingsDialog glue
// for the C++ product chain (Python side stays legacy/oracle).

#include <QWidget>

class QListWidget;
class QListWidgetItem;
class QComboBox;
class QLabel;

namespace pwb::viz {
class WellLogHostWidget;
}

class WellLogTrackPanel final : public QWidget {
    Q_OBJECT

public:
    explicit WellLogTrackPanel(QWidget* parent = nullptr);
    ~WellLogTrackPanel() override;

    // Binds the host whose layout this panel edits. Safe to call once the
    // host has or has not loaded a document (the panel disables itself
    // without one).
    void bind(pwb::viz::WellLogHostWidget* host);

    // Re-reads the layout from the host and rebuilds the curve list.
    void refresh();

private:
    void on_item_changed(QListWidgetItem* item);
    void on_move_group(int offset);
    void on_merge_selected();
    void on_unmerge_selected();
    void on_scale_mode_changed(int index);
    void on_save_template();
    void on_load_template();
    void on_export(const QString& suffix, const QString& filter);

    [[nodiscard]] pwb::viz::WellLogHostWidget* host() const;

    QListWidget* curves_;
    QComboBox* scale_mode_;
    QLabel* hint_;
    pwb::viz::WellLogHostWidget* host_{nullptr};
    bool rebuilding_{false};
};
