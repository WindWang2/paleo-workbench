#pragma once

#include <memory>
#include <optional>

#include <QOpenGLWidget>

#include <welllog/qtwidgets/export.hpp>
#include <welllog/render_gl/capability.hpp>
#include <welllog/session/session.hpp>

class QEvent;
class QKeyEvent;
class QMouseEvent;
class QResizeEvent;
class QShowEvent;
class QWheelEvent;

namespace welllog {

WELLLOG_QTWIDGETS_API void configure_well_log_surface_format();

class WELLLOG_QTWIDGETS_API WellLogView : public QOpenGLWidget {
  Q_OBJECT

public:
  explicit WellLogView(QWidget *parent = nullptr);
  explicit WellLogView(std::shared_ptr<WellLogSession> session,
                       QWidget *parent = nullptr);
  ~WellLogView() override;

  [[nodiscard]] WellLogSession &session() noexcept;
  [[nodiscard]] const WellLogSession &session() const noexcept;
  void set_document_id(EntityId document_id) noexcept;
  [[nodiscard]] std::optional<EntityId> document_id() const noexcept;
  [[nodiscard]] const CapabilityReport &capability_report() const noexcept;
  [[nodiscard]] std::optional<CurvePick> hover_pick() const noexcept;
  [[nodiscard]] std::optional<CurvePick> click_pick() const noexcept;

public slots:
  void reset_viewport();

signals:
  void capabilityChanged();
  void fatalViewError();
  void viewError(const QString &code, const QString &message);
  void documentChanged(const QString &document_id, quint64 revision);
  void diagnosticPublished(const QString &code, const QString &document_id,
                           quint64 revision);
  void viewportChanged();
  void crosshairChanged();
  void hoverChanged();
  void curveClicked();

protected:
  void initializeGL() override;
  void resizeGL(int width, int height) override;
  void paintGL() override;
  void showEvent(QShowEvent *event) override;
  void resizeEvent(QResizeEvent *event) override;
  void mousePressEvent(QMouseEvent *event) override;
  void mouseMoveEvent(QMouseEvent *event) override;
  void mouseReleaseEvent(QMouseEvent *event) override;
  void wheelEvent(QWheelEvent *event) override;
  void leaveEvent(QEvent *event) override;
  void keyPressEvent(QKeyEvent *event) override;

private:
  void publish_fatal_error();
  void cleanup_context() noexcept;
  void handle_session_event(ViewEvent event) noexcept;
  void schedule_coalesced_signals() noexcept;
  void update_pointer(double left, double top) noexcept;
  void update_capability_overlay() noexcept;
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

} // namespace welllog
