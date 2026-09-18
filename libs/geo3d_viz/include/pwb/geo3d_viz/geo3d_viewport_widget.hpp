#pragma once

// pwb::geo3d_viz — native Qt6 3D viewport (CONV-GEO3D).
//
// C++ replacement for the pyqtgraph GLViewWidget half of the Python stack
// (geo-viz-engine renderer_3d.py + joint_widget.py pass-through API):
//   * renders the named scene objects of a SceneObjectManager with modern
//     OpenGL (3.3 core): flat/smooth meshes, line strips, points, and a
//     QPainter text overlay for labels;
//   * three-way clipping in the shader (GL_CLIP_PLANE0..2 semantic: keep
//     n·p <= d, as produced by pwb::geomodel::Plane::as_clip_equation);
//   * orbit / pan / zoom mouse handling with the Python click-vs-drag
//     threshold (25 px²) and the default camera 500/30/45;
//   * CPU picking through the shared registry math (no GL readback);
//   * screenshot via grabFramebuffer, camera pose get/set, fit-to-objects;
//   * GL-less honesty: without a working context the widget degrades to the
//     placeholder behaviour of the Python offscreen path — the registry,
//     picking and state stay fully functional and nothing crashes.
//
// Lifecycle safety: the widget owns its registry; GL buffers are rebuilt
// from the registry revision inside paintGL (context current), so there are
// no cross-thread GL handles and repeated open/close cannot leak. Hosts
// reach the registry through scene_manager() and the Geo3DViewportFacade
// implemented below.

#include <QOpenGLBuffer>
#include <QOpenGLFunctions_3_3_Core>
#include <QOpenGLShaderProgram>
#include <QOpenGLWidget>

#include <map>
#include <memory>
#include <optional>
#include <string>

#include <pwb/geo3d_viz/orbit_camera.hpp>
#include <pwb/geo3d_viz/scene_object_manager.hpp>
#include <pwb/geo3d_viz/workspace_controller.hpp>

namespace pwb::geo3d_viz {

class Geo3DViewportWidget : public QOpenGLWidget,
                            protected QOpenGLFunctions_3_3_Core,
                            public Geo3DViewportFacade {
    Q_OBJECT

public:
    explicit Geo3DViewportWidget(QWidget* parent = nullptr);
    ~Geo3DViewportWidget() override;

    // The registry this widget renders (adapter provider target).
    SceneObjectManager& scene_manager() { return manager_; }
    const SceneObjectManager& scene_manager() const { return manager_; }
    OrbitCamera& camera() { return camera_; }
    const OrbitCamera& camera() const { return camera_; }

    // Scene identity marker consumed by the adapter's payload tokens: a
    // viewport rebind (project switch / rebuild) changes it so payloads
    // rebuild even when the domain objects are equal.
    void set_scene_identity(const std::string& identity) {
        scene_identity_ = identity;
    }
    const std::string& scene_identity() const { return scene_identity_; }

    // True when a 3.3-core context is actually rendering (honest GL probe;
    // offscreen/software-raster environments report what they provide).
    bool gl_ready() const { return gl_ready_; }

    // Screenshot of the last-rendered frame; a null image when no context
    // ever rendered (callers must treat that as "no screenshot available").
    QImage grab_scene_screenshot();

    // ------------------------------------------------------------------
    // Geo3DViewportFacade
    // ------------------------------------------------------------------

    std::optional<CameraPose> camera_pose() const override;
    void apply_camera_pose(const CameraPose& pose) override;
    std::optional<Bounds> scene_bounds(bool visible_only) override;
    bool fit_objects(
        const std::optional<std::vector<std::string>>& names) override;
    std::optional<PickHit> pick_at(
        double px, double py,
        const std::vector<ObjectKind>& kinds) override;

signals:
    // Raw click (click-vs-drag already resolved). Hosts wire this into
    // Geo3DWorkspaceController::handle_viewport_click for the measurement /
    // selection state machines.
    void viewport_clicked(double px, double py);
    void escape_pressed();
    // Cursor world coordinates over the current bounds ("x=… y=… z=…"), or
    // an empty string off-bounds.
    void coordinate_hovered(const QString& text);
    void camera_moved();
    void gl_available_changed(bool available);

protected:
    void initializeGL() override;
    void resizeGL(int w, int h) override;
    void paintGL() override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void wheelEvent(QWheelEvent* event) override;
    void keyPressEvent(QKeyEvent* event) override;

private:
    struct GlMesh {
        QOpenGLBuffer vertices{QOpenGLBuffer::VertexBuffer};
        std::size_t vertex_count = 0;  // triangles (non-indexed soup)
    };
    struct GlStroke {
        QOpenGLBuffer vertices{QOpenGLBuffer::VertexBuffer};
        std::size_t vertex_count = 0;
        GLenum mode = GL_LINE_STRIP;
        Rgba color{0.85f, 0.85f, 0.9f, 1.0f};
        float width = 1.0f;
        float size = 1.0f;
        float opacity = 1.0f;
        bool is_points = false;
        std::optional<std::vector<ClipEquation>> clip_planes;
    };

    void rebuild_from_registry();
    void release_gl_objects();
    // (the shader carries 3 clip-plane slots; the adapter emits at most the
    //  3 axis planes — the registry's 6-plane ceiling stays authoritative
    //  for validation while the viewport applies the first 3)
    void draw_mesh(GlMesh& mesh, const SceneObject& object);
    void draw_stroke(GlStroke& stroke, const SceneObject& object);
    void paint_text_overlay(QPainter& painter);
    void update_hover_coordinates(const QPointF& pos);

    SceneObjectManager manager_;
    OrbitCamera camera_;
    std::string scene_identity_;

    // GL context objects (valid only between initializeGL/destruct).
    std::unique_ptr<QOpenGLShaderProgram> mesh_program_;
    std::unique_ptr<QOpenGLShaderProgram> stroke_program_;
    std::map<std::string, GlMesh> meshes_;   // object name → buffers
    std::map<std::string, GlStroke> strokes_;
    QOpenGLBuffer grid_buffer_{QOpenGLBuffer::VertexBuffer};
    std::size_t grid_vertex_count_ = 0;
    std::uint64_t rendered_revision_ = static_cast<std::uint64_t>(-1);
    bool gl_ready_ = false;
    bool gl_reported_ = false;

    // Mouse interaction state (click-vs-drag threshold 25 px², Python
    // geological_modeling_3d_page press/release contract).
    QPointF press_pos_;
    QPointF last_pos_;
    bool pressed_ = false;
    bool dragged_ = false;
    Qt::MouseButton pressed_button_ = Qt::NoButton;
};

}  // namespace pwb::geo3d_viz
