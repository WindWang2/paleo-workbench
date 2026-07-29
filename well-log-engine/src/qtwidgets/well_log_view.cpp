#include <welllog/qtwidgets/well_log_view.hpp>

#include "render_gl/capability_probe.hpp"
#include "render_gl/renderer.hpp"

#include <QKeyEvent>
#include <QMetaObject>
#include <QMouseEvent>
#include <QOpenGLContext>
#include <QOpenGLExtraFunctions>
#include <QOpenGLFunctions>
#include <QPainter>
#include <QSurfaceFormat>
#include <QWheelEvent>

#include <algorithm>
#include <cmath>
#include <utility>

namespace welllog {
namespace {

[[nodiscard]] QSurfaceFormat well_log_surface_format() {
  QSurfaceFormat format;
  format.setRenderableType(QSurfaceFormat::OpenGL);
  format.setVersion(3, 3);
  format.setProfile(QSurfaceFormat::CoreProfile);
  format.setDepthBufferSize(24);
  format.setStencilBufferSize(8);
  format.setSwapBehavior(QSurfaceFormat::DoubleBuffer);
  format.setSamples(0);
  return format;
}

[[nodiscard]] std::string gl_string(QOpenGLFunctions &functions,
                                    unsigned int name) {
  const auto *value = functions.glGetString(name);
  return value == nullptr ? std::string{}
                          : std::string{reinterpret_cast<const char *>(value)};
}

[[nodiscard]] CapabilityReport failed_capability_report(std::string reason) {
  CapabilityReport report;
  report.initialization_complete = true;
  report.unavailable_reason = std::move(reason);
  return report;
}

[[nodiscard]] detail::GlProcAddress resolve_gl_proc(void *context,
                                                    const char *name) noexcept {
  if (context == nullptr || name == nullptr) {
    return nullptr;
  }
  return static_cast<QOpenGLContext *>(context)->getProcAddress(name);
}

} // namespace

void configure_well_log_surface_format() {
  QSurfaceFormat::setDefaultFormat(well_log_surface_format());
}

struct WellLogView::Impl {
  std::shared_ptr<WellLogSession> session;
  std::optional<EntityId> document_id;
  CapabilityReport capability_report;
  detail::GlRenderer renderer;
  std::shared_ptr<const PreparedScene> uploaded_scene;
  QMetaObject::Connection context_cleanup_connection;
  std::optional<CurvePick> hover_pick;
  std::optional<CurvePick> click_pick;
  double drag_last_top{};
  bool dragging{};
  bool drag_moved{};
  bool framebuffer_stencil_verified{};
};

WellLogView::WellLogView(QWidget *parent)
    : WellLogView(std::make_shared<WellLogSession>(), parent) {}

WellLogView::WellLogView(std::shared_ptr<WellLogSession> session,
                         QWidget *parent)
    : QOpenGLWidget(parent), impl_(std::make_unique<Impl>()) {
  impl_->session = session == nullptr ? std::make_shared<WellLogSession>()
                                      : std::move(session);
  setFormat(well_log_surface_format());
  setMouseTracking(true);
  setFocusPolicy(Qt::StrongFocus);
  setUpdateBehavior(QOpenGLWidget::NoPartialUpdate);
}

WellLogView::~WellLogView() { cleanup_context(); }

WellLogSession &WellLogView::session() noexcept { return *impl_->session; }

const WellLogSession &WellLogView::session() const noexcept {
  return *impl_->session;
}

void WellLogView::set_document_id(EntityId document_id) noexcept {
  impl_->document_id =
      document_id.is_nil() ? std::nullopt : std::optional{document_id};
  const auto had_hover = impl_->hover_pick.has_value();
  impl_->hover_pick.reset();
  impl_->click_pick.reset();
  if (had_hover) {
    emit hoverChanged();
  }
  update();
}

std::optional<EntityId> WellLogView::document_id() const noexcept {
  return impl_->document_id;
}

const CapabilityReport &WellLogView::capability_report() const noexcept {
  return impl_->capability_report;
}

std::optional<CurvePick> WellLogView::hover_pick() const noexcept {
  return impl_->hover_pick;
}

std::optional<CurvePick> WellLogView::click_pick() const noexcept {
  return impl_->click_pick;
}

void WellLogView::initializeGL() {
  try {
    auto *current = QOpenGLContext::currentContext();
    if (current == nullptr || current != context()) {
      impl_->capability_report =
          failed_capability_report("no current OpenGL context is available");
      emit fatalViewError();
      return;
    }
    auto *functions = current->functions();
    if (functions == nullptr) {
      impl_->capability_report =
          failed_capability_report("OpenGL functions are unavailable");
      emit fatalViewError();
      return;
    }
    functions->initializeOpenGLFunctions();

    int maximum_texture_size{};
    functions->glGetIntegerv(GL_MAX_TEXTURE_SIZE, &maximum_texture_size);
    const auto format = current->format();
    impl_->capability_report =
        detail::evaluate_capabilities(detail::OpenGlContextCapabilities{
            .core_profile = format.profile() == QSurfaceFormat::CoreProfile,
            .open_gl_major = format.majorVersion(),
            .open_gl_minor = format.minorVersion(),
            .stencil_bits = format.stencilBufferSize(),
            .maximum_texture_size = maximum_texture_size,
            .vendor = gl_string(*functions, GL_VENDOR),
            .renderer = gl_string(*functions, GL_RENDERER),
            .open_gl_version = gl_string(*functions, GL_VERSION),
            .glsl_version = gl_string(*functions, GL_SHADING_LANGUAGE_VERSION),
        });
    if (impl_->capability_report.graphics_available &&
        !impl_->renderer.initialize(resolve_gl_proc, current)) {
      impl_->capability_report.graphics_available = false;
      impl_->capability_report.unavailable_reason =
          "OpenGL shader or buffer initialization failed";
    }
    impl_->context_cleanup_connection = connect(
        current, &QOpenGLContext::aboutToBeDestroyed, this,
        [this]() { cleanup_context(); }, Qt::DirectConnection);
    emit capabilityChanged();
    if (!impl_->capability_report.graphics_available) {
      emit fatalViewError();
    }
  } catch (...) {
    impl_->capability_report =
        failed_capability_report("OpenGL capability detection failed");
    emit fatalViewError();
  }
}

void WellLogView::resizeGL(int width, int height) {
  Q_UNUSED(width)
  Q_UNUSED(height)
}

void WellLogView::paintGL() {
  if (impl_->capability_report.graphics_available &&
      !impl_->framebuffer_stencil_verified) {
    auto *current = QOpenGLContext::currentContext();
    auto *functions = current == nullptr ? nullptr : current->extraFunctions();
    if (current != context() || functions == nullptr) {
      impl_->capability_report.graphics_available = false;
      impl_->capability_report.unavailable_reason =
          "the widget framebuffer could not be validated";
    } else {
      int stencil_bits{};
      functions->glGetFramebufferAttachmentParameteriv(
          GL_FRAMEBUFFER, GL_STENCIL_ATTACHMENT,
          GL_FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE, &stencil_bits);
      impl_->capability_report.stencil_bits = stencil_bits;
      if (stencil_bits < 8) {
        impl_->capability_report.graphics_available = false;
        impl_->capability_report.unavailable_reason =
            "an 8-bit stencil buffer is required";
      }
    }
    impl_->framebuffer_stencil_verified = true;
    emit capabilityChanged();
    if (!impl_->capability_report.graphics_available) {
      emit fatalViewError();
    }
  }
  if (!impl_->capability_report.graphics_available) {
    QPainter painter(this);
    painter.fillRect(rect(), QColor{35, 38, 41});
    painter.setPen(QColor{235, 235, 235});
    const auto reason =
        impl_->capability_report.unavailable_reason.empty()
            ? tr("OpenGL view unavailable")
            : tr("OpenGL view unavailable\n%1")
                  .arg(QString::fromStdString(
                      impl_->capability_report.unavailable_reason));
    painter.drawText(rect().adjusted(16, 16, -16, -16),
                     Qt::AlignCenter | Qt::TextWordWrap, reason);
    return;
  }
  try {
    auto *current = QOpenGLContext::currentContext();
    if (current == nullptr || current != context()) {
      emit fatalViewError();
      return;
    }
    std::shared_ptr<const PreparedScene> scene;
    std::optional<DepthViewport> viewport;
    std::optional<CrosshairState> crosshair;
    if (impl_->document_id.has_value()) {
      scene = impl_->session->prepared_scene(*impl_->document_id);
      viewport = impl_->session->viewport(*impl_->document_id);
      crosshair = impl_->session->crosshair(*impl_->document_id);
    }
    if (scene != nullptr && scene != impl_->uploaded_scene) {
      if (!impl_->renderer.upload(*scene)) {
        emit fatalViewError();
        return;
      }
      impl_->uploaded_scene = scene;
    }
    const auto fallback_viewport =
        scene == nullptr ? DepthViewport{.top = 0.0, .bottom = 1.0}
                         : DepthViewport{
                               .top = scene->reference_depth_range().top,
                               .bottom = scene->reference_depth_range().bottom,
                           };
    const auto pixel_ratio = devicePixelRatioF();
    const auto pixel_width =
        static_cast<int>(static_cast<double>(width()) * pixel_ratio);
    const auto pixel_height =
        static_cast<int>(static_cast<double>(height()) * pixel_ratio);
    if (!impl_->renderer.render(detail::GlRenderFrame{
            .framebuffer = defaultFramebufferObject(),
            .pixel_width = pixel_width,
            .pixel_height = pixel_height,
            .physical_pixels_per_millimetre =
                logicalDpiX() / 25.4 * pixel_ratio,
            .viewport =
                [&]() {
                  const auto current_viewport =
                      viewport.value_or(fallback_viewport);
                  return detail::GlDepthViewport{
                      .top = current_viewport.top,
                      .bottom = current_viewport.bottom,
                  };
                }(),
            .crosshair =
                crosshair.has_value()
                    ? std::optional<detail::GlCrosshair>{detail::GlCrosshair{
                          .horizontal_fraction = crosshair->track_fraction,
                          .display_depth = crosshair->display_depth,
                      }}
                    : std::nullopt,
            .draw_scene = scene != nullptr,
        })) {
      emit fatalViewError();
    }
  } catch (...) {
    emit fatalViewError();
  }
}

void WellLogView::mousePressEvent(QMouseEvent *event) {
  if (event->button() == Qt::LeftButton) {
    impl_->dragging = true;
    impl_->drag_moved = false;
    impl_->drag_last_top = event->position().y();
    update_pointer(event->position().x(), event->position().y());
    event->accept();
    return;
  }
  QOpenGLWidget::mousePressEvent(event);
}

void WellLogView::mouseMoveEvent(QMouseEvent *event) {
  if (impl_->dragging && impl_->document_id.has_value() && height() > 0) {
    const auto delta = event->position().y() - impl_->drag_last_top;
    const auto viewport = impl_->session->viewport(*impl_->document_id);
    if (viewport.has_value() && delta != 0.0) {
      const auto depth_delta = -delta / static_cast<double>(height()) *
                               (viewport->bottom - viewport->top);
      if (impl_->session
              ->execute(PanDepthCommand{
                  .document_id = *impl_->document_id,
                  .display_depth_delta = depth_delta,
              })
              .has_value()) {
        impl_->drag_moved = true;
        impl_->drag_last_top = event->position().y();
        emit viewportChanged();
        update();
      }
    }
  }
  update_pointer(event->position().x(), event->position().y());
  event->accept();
}

void WellLogView::mouseReleaseEvent(QMouseEvent *event) {
  if (event->button() == Qt::LeftButton && impl_->dragging) {
    update_pointer(event->position().x(), event->position().y());
    if (!impl_->drag_moved) {
      impl_->click_pick = impl_->hover_pick;
      if (impl_->click_pick.has_value()) {
        emit curveClicked();
      }
    }
    impl_->dragging = false;
    event->accept();
    return;
  }
  QOpenGLWidget::mouseReleaseEvent(event);
}

void WellLogView::wheelEvent(QWheelEvent *event) {
  if (!impl_->document_id.has_value() || height() <= 0) {
    QOpenGLWidget::wheelEvent(event);
    return;
  }
  const auto viewport = impl_->session->viewport(*impl_->document_id);
  if (!viewport.has_value() || event->angleDelta().y() == 0) {
    QOpenGLWidget::wheelEvent(event);
    return;
  }
  const auto top_fraction = std::clamp(
      event->position().y() / static_cast<double>(height()), 0.0, 1.0);
  const auto anchor =
      viewport->top + top_fraction * (viewport->bottom - viewport->top);
  const auto factor =
      std::exp(-static_cast<double>(event->angleDelta().y()) * 0.0015);
  if (impl_->session
          ->execute(ZoomDepthAtCommand{
              .document_id = *impl_->document_id,
              .anchor_display_depth = anchor,
              .span_factor = factor,
          })
          .has_value()) {
    emit viewportChanged();
    update_pointer(event->position().x(), event->position().y());
    update();
  }
  event->accept();
}

void WellLogView::leaveEvent(QEvent *event) {
  if (impl_->document_id.has_value() &&
      impl_->session
          ->execute(SetCrosshairCommand{
              .document_id = *impl_->document_id,
              .crosshair = std::nullopt,
          })
          .has_value()) {
    emit crosshairChanged();
  }
  if (impl_->hover_pick.has_value()) {
    impl_->hover_pick.reset();
    emit hoverChanged();
  }
  update();
  QOpenGLWidget::leaveEvent(event);
}

void WellLogView::keyPressEvent(QKeyEvent *event) {
  if (event->key() == Qt::Key_Home) {
    reset_viewport();
    event->accept();
    return;
  }
  QOpenGLWidget::keyPressEvent(event);
}

void WellLogView::reset_viewport() {
  if (!impl_->document_id.has_value()) {
    return;
  }
  if (impl_->session
          ->execute(ResetViewportCommand{.document_id = *impl_->document_id})
          .has_value()) {
    emit viewportChanged();
    update();
  }
}

void WellLogView::update_pointer(double left, double top) noexcept {
  try {
    if (!impl_->document_id.has_value() || width() <= 0 || height() <= 0) {
      return;
    }
    const auto scene = impl_->session->prepared_scene(*impl_->document_id);
    const auto viewport = impl_->session->viewport(*impl_->document_id);
    if (scene == nullptr || !viewport.has_value()) {
      return;
    }
    const auto horizontal_fraction =
        std::clamp(left / static_cast<double>(width()), 0.0, 1.0);
    const auto vertical_fraction =
        std::clamp(top / static_cast<double>(height()), 0.0, 1.0);
    const auto display_depth =
        viewport->top + vertical_fraction * (viewport->bottom - viewport->top);
    if (impl_->session
            ->execute(SetCrosshairCommand{
                .document_id = *impl_->document_id,
                .crosshair =
                    CrosshairState{
                        .track_fraction = horizontal_fraction,
                        .display_depth = display_depth,
                    },
            })
            .has_value()) {
      emit crosshairChanged();
    }

    const auto reference_range = scene->reference_depth_range();
    const auto reference_span = reference_range.bottom - reference_range.top;
    const auto viewport_span = viewport->bottom - viewport->top;
    const auto physical_width = scene->physical_width().value;
    const auto physical_height = scene->physical_height().value;
    if (reference_span <= 0.0 || viewport_span <= 0.0 ||
        physical_width <= 0.0 || physical_height <= 0.0) {
      return;
    }
    const auto reference_depth = display_depth;
    const auto next_hover = scene->pick_curve(CurvePickQuery{
        .scene_position =
            PhysicalPoint{
                .left = Millimetres{horizontal_fraction * physical_width},
                .top = Millimetres{(reference_depth - reference_range.top) /
                                   reference_span * physical_height},
            },
        .tolerance = DeviceIndependentPixels{6.0},
        .horizontal_device_independent_pixels_per_millimetre =
            static_cast<double>(width()) / physical_width,
        .vertical_device_independent_pixels_per_millimetre =
            static_cast<double>(height()) /
            (physical_height * viewport_span / reference_span),
    });
    impl_->hover_pick = next_hover;
    emit hoverChanged();
    update();
  } catch (...) {
    emit fatalViewError();
  }
}

void WellLogView::cleanup_context() noexcept {
  QObject::disconnect(impl_->context_cleanup_connection);
  impl_->context_cleanup_connection = {};
  auto *gl_context = context();
  if (gl_context != nullptr && gl_context->isValid()) {
    makeCurrent();
    if (QOpenGLContext::currentContext() == gl_context) {
      impl_->renderer.release();
      doneCurrent();
    } else {
      impl_->renderer.abandon();
    }
  } else {
    impl_->renderer.abandon();
  }
  impl_->uploaded_scene.reset();
  impl_->framebuffer_stencil_verified = false;
}

} // namespace welllog
