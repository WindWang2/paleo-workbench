#pragma once

// MainWindow — direct C++ hosting of QgsMapCanvas + QgsLayerTreeView via
// ProjectSession (no Shiboken address bridge, no mirror copies). This first
// round deliberately carries a minimal shell: canvas + tree + toolbar driven
// by Pwb::ToolPolicy + an editable fixture layer for the smoke path.

#include <memory>

#include <QMainWindow>

#include <pwb/application/project_session.hpp>
#include <pwb/ui/tool_actions.hpp>

class QgsMapCanvas;
class QgsLayerTreeView;
class QLabel;

namespace pwb::app {

class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    explicit MainWindow(QWidget* parent = nullptr);
    ~MainWindow() override;

    // Loads a vector fixture + raster fixture, sets an active layer and
    // returns "" (or the diagnostic). Used by the app smoke entry and tests.
    QString loadFixtures(const QString& vector_uri, const QString& raster_uri);

    pwb::application::ProjectSession* session() const { return session_.get(); }

protected:
    void closeEvent(QCloseEvent* event) override;

private:
    void buildUi();
    void buildToolbar();
    void refreshActionStates();

    std::unique_ptr<pwb::application::ProjectSession> session_;
    pwb::ui::ToolActionSet actions_;
    QgsMapCanvas* canvas_ = nullptr;
    QgsLayerTreeView* tree_ = nullptr;
    QLabel* status_label_ = nullptr;
};

}  // namespace pwb::app
