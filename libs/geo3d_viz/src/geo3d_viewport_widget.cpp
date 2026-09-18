#include <pwb/geo3d_viz/geo3d_viewport_widget.hpp>

#include <QMouseEvent>
#include <QPainter>
#include <QVector4D>
#include <QWheelEvent>

#include <algorithm>
#include <cstdio>
#include <cmath>

namespace pwb::geo3d_viz {

namespace {
// renderer_3d.py _init_pyqtgraph: background "#1e1e2e", default camera
// 500/30/45, 500×500 grid with 50 spacing.
constexpr float kBackgroundRed = 0x1e / 255.0f;
constexpr float kBackgroundGreen = 0x1e / 255.0f;
constexpr float kBackgroundBlue = 0x2e / 255.0f;
constexpr double kGridExtent = 250.0;
constexpr double kGridStep = 50.0;
constexpr double kClickDragThresholdSq = 25.0;  // px² (Python contract)

const char* kMeshVertexShader = R"(
#version 330 core
in vec3 a_pos;
in vec4 a_color;
uniform mat4 u_mvp;
out vec4 v_color;
out vec3 v_world;
void main() {
    v_color = a_color;
    v_world = a_pos;
    gl_Position = u_mvp * vec4(a_pos, 1.0);
}
)";

const char* kMeshFragmentShader = R"(
#version 330 core
in vec4 v_color;
in vec3 v_world;
uniform vec4 u_clip[3];
uniform int u_clip_count;
uniform float u_opacity;
out vec4 frag_color;
void main() {
    for (int i = 0; i < u_clip_count; ++i) {
        // keep n.p <= d (pwb::geomodel as_clip_equation convention)
        if (dot(u_clip[i].xyz, v_world) > u_clip[i].w) discard;
    }
    frag_color = vec4(v_color.rgb, v_color.a * u_opacity);
}
)";

const char* kStrokeVertexShader = R"(
#version 330 core
in vec3 a_pos;
uniform mat4 u_mvp;
uniform float u_point_size;
out vec3 v_world;
void main() {
    v_world = a_pos;
    gl_Position = u_mvp * vec4(a_pos, 1.0);
    gl_PointSize = u_point_size;
}
)";

const char* kStrokeFragmentShader = R"(
#version 330 core
in vec3 v_world;
uniform vec4 u_color;
uniform vec4 u_clip[3];
uniform int u_clip_count;
uniform float u_opacity;
out vec4 frag_color;
void main() {
    for (int i = 0; i < u_clip_count; ++i) {
        if (dot(u_clip[i].xyz, v_world) > u_clip[i].w) discard;
    }
    frag_color = vec4(u_color.rgb, u_color.a * u_opacity);
}
)";

// u_clip wants floats; ClipEquation is double — widen then narrow here.
void pass_clip_planes(QOpenGLShaderProgram& program,
                      const std::optional<std::vector<ClipEquation>>& planes) {
    std::array<GLfloat, 12> flat{};
    for (int i = 0; i < 3; ++i) {
        flat[static_cast<std::size_t>(i) * 4 + 3] = 1e30f;  // disabled slot
    }
    int count = 0;
    if (planes.has_value()) {
        for (const ClipEquation& eq : *planes) {
            if (count >= 3) break;  // adapter emits at most 3 axis planes
            for (int k = 0; k < 4; ++k) {
                flat[static_cast<std::size_t>(count) * 4 +
                     static_cast<std::size_t>(k)] = static_cast<GLfloat>(eq[static_cast<std::size_t>(k)]);
            }
            ++count;
        }
    }
    program.setUniformValueArray("u_clip", flat.data(), 3, 4);
    program.setUniformValue("u_clip_count", static_cast<GLint>(count));
}

QMatrix4x4 to_qt(const Mat4& m) {
    // Mat4 is column-major (QMatrix4x4::constData layout): copy element-wise
    // rather than through the row-major constructor.
    QMatrix4x4 out;
    for (int i = 0; i < 16; ++i) {
        out.data()[i] = m[static_cast<std::size_t>(i)];
    }
    return out;
}

QMatrix4x4 full_mvp(const OrbitCamera& camera) {
    return to_qt(camera.projection_matrix()) * to_qt(camera.view_matrix());
}

}  // namespace

// ---------------------------------------------------------------------------
// construction / destruction
// ---------------------------------------------------------------------------

Geo3DViewportWidget::Geo3DViewportWidget(QWidget* parent)
    : QOpenGLWidget(parent) {
    setMouseTracking(true);
    setFocusPolicy(Qt::ClickFocus);
}

Geo3DViewportWidget::~Geo3DViewportWidget() {
    // RAII: release GPU buffers with the context current (safe even when
    // the platform never provided a working GL context).
    makeCurrent();
    release_gl_objects();
    doneCurrent();
}

// ---------------------------------------------------------------------------
// Geo3DViewportFacade
// ---------------------------------------------------------------------------

std::optional<CameraPose> Geo3DViewportWidget::camera_pose() const {
    return camera_.pose();
}

void Geo3DViewportWidget::apply_camera_pose(const CameraPose& pose) {
    camera_.set_pose(pose);
    update();
    emit camera_moved();
}

std::optional<Bounds> Geo3DViewportWidget::scene_bounds(bool visible_only) {
    return manager_.bounds({}, visible_only);
}

bool Geo3DViewportWidget::fit_objects(
    const std::optional<std::vector<std::string>>& names) {
    bool any = false;
    std::array<double, 3> lo{0, 0, 0};
    std::array<double, 3> hi{0, 0, 0};
    const std::vector<std::string> all = manager_.names();
    for (const std::string& name :
         names.has_value() ? *names : all) {
        const SceneObject* object = manager_.get(name);
        if (object == nullptr || !object->visible) continue;
        const auto b = object->bounds();
        if (!b.has_value()) continue;
        if (!any) {
            lo = b->first;
            hi = b->second;
            any = true;
            continue;
        }
        for (int k = 0; k < 3; ++k) {
            lo[k] = std::min(lo[k], b->first[k]);
            hi[k] = std::max(hi[k], b->second[k]);
        }
    }
    if (!any) return false;
    camera_.frame_bounds(lo, hi);
    update();
    emit camera_moved();
    return true;
}

std::optional<PickHit> Geo3DViewportWidget::pick_at(
    double px, double py, const std::vector<ObjectKind>& kinds) {
    const std::optional<Ray> ray = camera_.ray_at(px, py);
    if (!ray.has_value()) return std::nullopt;
    return manager_.pick(*ray, kinds);
}

QImage Geo3DViewportWidget::grab_scene_screenshot() {
    if (!gl_ready_) return QImage();
    return grabFramebuffer();
}

// ---------------------------------------------------------------------------
// GL lifecycle
// ---------------------------------------------------------------------------

void Geo3DViewportWidget::initializeGL() {
    // A missing 3.3-core context (offscreen without software GL, ancient
    // drivers) degrades to the placeholder path — the registry, picking and
    // state stay fully functional.
    gl_ready_ = initializeOpenGLFunctions();
    if (gl_ready_) {
        mesh_program_ = std::make_unique<QOpenGLShaderProgram>();
        stroke_program_ = std::make_unique<QOpenGLShaderProgram>();
        const bool mesh_ok =
            mesh_program_->addShaderFromSourceCode(QOpenGLShader::Vertex,
                                                   kMeshVertexShader) &&
            mesh_program_->addShaderFromSourceCode(QOpenGLShader::Fragment,
                                                   kMeshFragmentShader) &&
            mesh_program_->link();
        const bool stroke_ok =
            stroke_program_->addShaderFromSourceCode(QOpenGLShader::Vertex,
                                                     kStrokeVertexShader) &&
            stroke_program_->addShaderFromSourceCode(QOpenGLShader::Fragment,
                                                     kStrokeFragmentShader) &&
            stroke_program_->link();
        gl_ready_ = mesh_ok && stroke_ok;
    }
    if (!gl_ready_) {
        mesh_program_.reset();
        stroke_program_.reset();
    }
    if (gl_ready_ != gl_reported_) {
        gl_reported_ = gl_ready_;
        emit gl_available_changed(gl_ready_);
    }
    rendered_revision_ = static_cast<std::uint64_t>(-1);  // force rebuild
}

void Geo3DViewportWidget::resizeGL(int w, int h) {
    camera_.set_viewport(w, h);
}

void Geo3DViewportWidget::release_gl_objects() {
    for (auto& [name, mesh] : meshes_) {
        (void)name;
        if (mesh.vertices.isCreated()) mesh.vertices.destroy();
    }
    meshes_.clear();
    for (auto& [name, stroke] : strokes_) {
        (void)name;
        if (stroke.vertices.isCreated()) stroke.vertices.destroy();
    }
    strokes_.clear();
    if (grid_buffer_.isCreated()) grid_buffer_.destroy();
    grid_vertex_count_ = 0;
}

void Geo3DViewportWidget::rebuild_from_registry() {
    release_gl_objects();
    for (const std::string& name : manager_.names()) {
        const SceneObject* object = manager_.get(name);
        if (object == nullptr || !object->visible) continue;
        if (object->mode == ObjectMode::Mesh && !object->faces.empty()) {
            // Non-indexed triangle soup with per-vertex colors; face colors
            // duplicate per face → flat shading (Python smooth=False path).
            GlMesh mesh;
            std::vector<float> data;
            data.reserve(object->faces.size() * 3 * 7);
            for (std::size_t fi = 0; fi < object->faces.size(); ++fi) {
                const Rgba face_tint = object->face_colors.empty()
                                           ? object->color
                                           : object->face_colors[fi];
                for (int corner = 0; corner < 3; ++corner) {
                    const Vec3f& p = object->verts[static_cast<std::size_t>(
                        object->faces[fi][static_cast<std::size_t>(corner)])];
                    data.insert(data.end(), {p[0], p[1], p[2], face_tint[0],
                                             face_tint[1], face_tint[2],
                                             face_tint[3]});
                }
            }
            mesh.vertex_count = object->faces.size() * 3;
            if (!data.empty() && mesh.vertices.create()) {
                mesh.vertices.bind();
                mesh.vertices.allocate(data.data(),
                                       static_cast<int>(data.size() *
                                                        sizeof(float)));
                mesh.vertices.release();
                meshes_[name] = std::move(mesh);
            }
        } else if (object->mode == ObjectMode::Lines ||
                   object->mode == ObjectMode::Points) {
            GlStroke stroke;
            stroke.vertex_count = object->verts.size();
            stroke.color = object->color;
            stroke.width = object->width;
            stroke.size = object->size;
            stroke.opacity = object->opacity;
            stroke.is_points = object->mode == ObjectMode::Points;
            stroke.mode = stroke.is_points
                              ? GL_POINTS
                              : (object->line_strip ? GL_LINE_STRIP : GL_LINES);
            stroke.clip_planes = object->clip_planes;
            std::vector<float> data;
            data.reserve(object->verts.size() * 3);
            for (const Vec3f& p : object->verts) {
                data.push_back(p[0]);
                data.push_back(p[1]);
                data.push_back(p[2]);
            }
            if (!data.empty() && stroke.vertices.create()) {
                stroke.vertices.bind();
                stroke.vertices.allocate(data.data(),
                                         static_cast<int>(data.size() *
                                                          sizeof(float)));
                stroke.vertices.release();
                strokes_[name] = std::move(stroke);
            }
        }
    }
    // Ground grid (renderer_3d: 500×500, spacing 50, at z=0).
    std::vector<float> grid;
    const int lines = static_cast<int>(kGridExtent / kGridStep);
    for (int i = -lines; i <= lines; ++i) {
        const float x = static_cast<float>(i * kGridStep);
        grid.insert(grid.end(), {x, -static_cast<float>(kGridExtent), 0.0f, x,
                                 static_cast<float>(kGridExtent), 0.0f});
        const float y = static_cast<float>(i * kGridStep);
        grid.insert(grid.end(), {-static_cast<float>(kGridExtent), y, 0.0f,
                                 static_cast<float>(kGridExtent), y, 0.0f});
    }
    grid_vertex_count_ = grid.size() / 3;
    if (!grid.empty() && grid_buffer_.create()) {
        grid_buffer_.bind();
        grid_buffer_.allocate(grid.data(),
                              static_cast<int>(grid.size() * sizeof(float)));
        grid_buffer_.release();
    }
    rendered_revision_ = manager_.revision();
}

// ---------------------------------------------------------------------------
// rendering
// ---------------------------------------------------------------------------

void Geo3DViewportWidget::paintGL() {
    if (!gl_ready_) {
        // Honest GL-less placeholder (Python offscreen contract): no GL
        // calls on an uninitialized function table — paint the placeholder
        // background through QPainter instead.
        QPainter painter(this);
        painter.fillRect(QRect(0, 0, width(), height()),
                         QColor(int(kBackgroundRed * 255),
                                int(kBackgroundGreen * 255),
                                int(kBackgroundBlue * 255)));
        painter.end();
        return;
    }
    if (rendered_revision_ != manager_.revision()) rebuild_from_registry();

    glClearColor(kBackgroundRed, kBackgroundGreen, kBackgroundBlue, 1.0f);
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    const QMatrix4x4 mvp = full_mvp(camera_);

    // ground grid
    if (grid_vertex_count_ > 0 && grid_buffer_.isCreated()) {
        stroke_program_->bind();
        stroke_program_->setUniformValue("u_mvp", mvp);
        stroke_program_->setUniformValue(
            "u_color", QVector4D(0.35f, 0.35f, 0.42f, 1.0f));
        stroke_program_->setUniformValue("u_opacity", 1.0f);
        stroke_program_->setUniformValue("u_point_size", 1.0f);
        pass_clip_planes(*stroke_program_, std::nullopt);
        grid_buffer_.bind();
        const int pos_loc = stroke_program_->attributeLocation("a_pos");
        glEnableVertexAttribArray(static_cast<GLuint>(pos_loc));
        glVertexAttribPointer(static_cast<GLuint>(pos_loc), 3, GL_FLOAT,
                              GL_FALSE, 3 * sizeof(float), nullptr);
        glDrawArrays(GL_LINES, 0, static_cast<GLsizei>(grid_vertex_count_));
        glDisableVertexAttribArray(static_cast<GLuint>(pos_loc));
        grid_buffer_.release();
        stroke_program_->release();
    }

    // opaque pass first, then blended objects (stable two-pass ordering)
    for (int pass = 0; pass < 2; ++pass) {
        for (const std::string& name : manager_.names()) {
            const SceneObject* object = manager_.get(name);
            if (object == nullptr || !object->visible) continue;
            const bool blended = object->opacity < 1.0f;
            if ((pass == 0) == blended) continue;
            const auto mesh_it = meshes_.find(name);
            if (mesh_it != meshes_.end()) {
                draw_mesh(mesh_it->second, *object);
                continue;
            }
            const auto stroke_it = strokes_.find(name);
            if (stroke_it != strokes_.end()) {
                draw_stroke(stroke_it->second);
            }
        }
    }

    // Text overlay painted over the GL frame.
    QPainter painter(this);
    paint_text_overlay(painter);
    painter.end();
}

void Geo3DViewportWidget::draw_mesh(GlMesh& mesh,
                                    const SceneObject& object) {
    if (!mesh.vertices.isCreated() || mesh.vertex_count == 0) return;
    mesh_program_->bind();
    mesh_program_->setUniformValue("u_mvp", full_mvp(camera_));
    mesh_program_->setUniformValue("u_opacity", object.opacity);
    pass_clip_planes(*mesh_program_, object.clip_planes);
    mesh.vertices.bind();
    const int pos_loc = mesh_program_->attributeLocation("a_pos");
    const int color_loc = mesh_program_->attributeLocation("a_color");
    glEnableVertexAttribArray(static_cast<GLuint>(pos_loc));
    glVertexAttribPointer(static_cast<GLuint>(pos_loc), 3, GL_FLOAT, GL_FALSE,
                          7 * sizeof(float), nullptr);
    glEnableVertexAttribArray(static_cast<GLuint>(color_loc));
    glVertexAttribPointer(static_cast<GLuint>(color_loc), 4, GL_FLOAT,
                          GL_FALSE, 7 * sizeof(float),
                          reinterpret_cast<const void*>(3 * sizeof(float)));
    glDrawArrays(GL_TRIANGLES, 0, static_cast<GLsizei>(mesh.vertex_count));
    glDisableVertexAttribArray(static_cast<GLuint>(color_loc));
    glDisableVertexAttribArray(static_cast<GLuint>(pos_loc));
    mesh.vertices.release();
    mesh_program_->release();
}

void Geo3DViewportWidget::draw_stroke(GlStroke& stroke) {
    if (!stroke.vertices.isCreated() || stroke.vertex_count == 0) return;
    stroke_program_->bind();
    stroke_program_->setUniformValue("u_mvp", full_mvp(camera_));
    stroke_program_->setUniformValue(
        "u_color", QVector4D(stroke.color[0], stroke.color[1], stroke.color[2],
                             stroke.color[3]));
    stroke_program_->setUniformValue("u_opacity", stroke.opacity);
    stroke_program_->setUniformValue("u_point_size",
                                     stroke.is_points ? stroke.size : 1.0f);
    if (!stroke.is_points && stroke.width > 0.0f) {
        glLineWidth(stroke.width);
    }
    pass_clip_planes(*stroke_program_, stroke.clip_planes);
    stroke.vertices.bind();
    const int pos_loc = stroke_program_->attributeLocation("a_pos");
    glEnableVertexAttribArray(static_cast<GLuint>(pos_loc));
    glVertexAttribPointer(static_cast<GLuint>(pos_loc), 3, GL_FLOAT, GL_FALSE,
                          3 * sizeof(float), nullptr);
    glDrawArrays(stroke.mode, 0, static_cast<GLsizei>(stroke.vertex_count));
    glDisableVertexAttribArray(static_cast<GLuint>(pos_loc));
    stroke.vertices.release();
    stroke_program_->release();
}

void Geo3DViewportWidget::paint_text_overlay(QPainter& painter) {
    for (const std::string& name : manager_.names()) {
        const SceneObject* object = manager_.get(name);
        if (object == nullptr || !object->visible ||
            object->mode != ObjectMode::Text || object->verts.empty()) {
            continue;
        }
        const Vec3f& anchor = object->verts.front();
        const std::array<double, 3> world{anchor[0], anchor[1], anchor[2]};
        bool clipped = false;
        if (object->clip_planes.has_value()) {
            for (const ClipEquation& eq : *object->clip_planes) {
                if (clipped_out(eq, world)) {
                    clipped = true;
                    break;
                }
            }
        }
        if (clipped) continue;
        double px = 0.0;
        double py = 0.0;
        if (!camera_.project_to_screen(world, px, py)) continue;
        const Rgba& c = object->color;
        painter.setPen(QColor(static_cast<int>(c[0] * 255),
                              static_cast<int>(c[1] * 255),
                              static_cast<int>(c[2] * 255),
                              static_cast<int>(c[3] * 255)));
        painter.drawText(QPointF(px, py),
                         QString::fromStdString(object->text));
    }
}

// ---------------------------------------------------------------------------
// interaction
// ---------------------------------------------------------------------------

void Geo3DViewportWidget::mousePressEvent(QMouseEvent* event) {
    pressed_ = true;
    dragged_ = false;
    press_pos_ = event->position();
    last_pos_ = event->position();
    pressed_button_ = event->button();
}

void Geo3DViewportWidget::mouseMoveEvent(QMouseEvent* event) {
    update_hover_coordinates(event->position());
    if (!pressed_) return;
    const QPointF pos = event->position();
    const double dx = pos.x() - last_pos_.x();
    const double dy = pos.y() - last_pos_.y();
    last_pos_ = pos;
    const double ex = pos.x() - press_pos_.x();
    const double ey = pos.y() - press_pos_.y();
    if (!dragged_ && ex * ex + ey * ey < kClickDragThresholdSq) return;
    dragged_ = true;
    const bool pan_request = pressed_button_ == Qt::MiddleButton ||
                             pressed_button_ == Qt::RightButton ||
                             (event->modifiers() & Qt::ShiftModifier);
    if (pan_request) {
        camera_.pan(dx, dy);
    } else {
        camera_.orbit(dx, dy);
    }
    update();
    emit camera_moved();
}

void Geo3DViewportWidget::mouseReleaseEvent(QMouseEvent* event) {
    if (pressed_ && !dragged_) {
        // click (the orbit gesture never engaged)
        emit viewport_clicked(event->position().x(), event->position().y());
    }
    pressed_ = false;
    dragged_ = false;
    pressed_button_ = Qt::NoButton;
}

void Geo3DViewportWidget::wheelEvent(QWheelEvent* event) {
    const int steps = event->angleDelta().y() / 120;
    if (steps == 0) return;
    camera_.zoom(static_cast<double>(steps));
    update();
    emit camera_moved();
}

void Geo3DViewportWidget::keyPressEvent(QKeyEvent* event) {
    if (event->key() == Qt::Key_Escape) {
        emit escape_pressed();
    }
    QOpenGLWidget::keyPressEvent(event);
}

void Geo3DViewportWidget::update_hover_coordinates(const QPointF& pos) {
    QString text;
    const std::optional<Bounds> bounds = manager_.bounds({}, true);
    const std::optional<Ray> ray =
        bounds.has_value() ? camera_.ray_at(pos.x(), pos.y()) : std::nullopt;
    if (ray.has_value()) {
        // Ray → axis-aligned box entry point (slab method).
        const auto& [lo, hi] = *bounds;
        double t_min = -1e300;
        double t_max = 1e300;
        bool hit = true;
        for (int k = 0; k < 3; ++k) {
            if (std::abs(ray->direction[k]) < 1e-12) {
                if (ray->origin[k] < lo[static_cast<std::size_t>(k)] ||
                    ray->origin[k] > hi[static_cast<std::size_t>(k)]) {
                    hit = false;
                    break;
                }
                continue;
            }
            double t0 = (lo[static_cast<std::size_t>(k)] - ray->origin[k]) /
                        ray->direction[k];
            double t1 = (hi[static_cast<std::size_t>(k)] - ray->origin[k]) /
                        ray->direction[k];
            if (t0 > t1) std::swap(t0, t1);
            t_min = std::max(t_min, t0);
            t_max = std::min(t_max, t1);
            if (t_min > t_max) {
                hit = false;
                break;
            }
        }
        if (hit && t_max >= 0.0) {
            const double t = t_min >= 0.0 ? t_min : 0.0;
            text = QString("x=%1 y=%2 z=%3")
                       .arg(ray->origin[0] + t * ray->direction[0], 0, 'f', 1)
                       .arg(ray->origin[1] + t * ray->direction[1], 0, 'f', 1)
                       .arg(ray->origin[2] + t * ray->direction[2], 0, 'f', 1);
        }
    }
    emit coordinate_hovered(text);
}

}  // namespace pwb::geo3d_viz
