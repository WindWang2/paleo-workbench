#pragma once

// pwb::geo3d_viz — orbit camera for the native 3D viewport (CONV-GEO3D).
//
// Parameterization parity with the Python stack: a pose is
// (distance, elevation_deg, azimuth_deg) around a center point — the same
// keys GLViewWidget exposes and WellSeismicJointWidget.camera_pose() reads
// back. Frozen presets: default viewport 500/30/45 (renderer_3d.py
// _init_pyqtgraph), perspective align 250/30/-45 and top-down 250/90/0
// (geological_modeling_3d_page._CAMERA_PERSPECTIVE/_CAMERA_TOP_DOWN).
//
// The camera is GL-less: view()/projection() emit column-major float16
// matrices (QMatrix4x4::constData layout) so both the Qt widget and the
// headless pick tests share one math implementation.
//
// Qt-free, Python-free.

#include <array>
#include <optional>
#include <utility>

#include <pwb/geo3d_viz/scene_object_manager.hpp>  // Mat4, Ray

namespace pwb::geo3d_viz {

struct CameraPose {
    double distance = 500.0;
    double elevation_deg = 30.0;
    double azimuth_deg = 45.0;
};

class OrbitCamera {
public:
    OrbitCamera();

    const CameraPose& pose() const { return pose_; }
    void set_pose(const CameraPose& pose);  // clamped like set_camera_pose
    void set_pose(double distance, double elevation_deg, double azimuth_deg);

    const std::array<double, 3>& center() const { return center_; }
    void set_center(const std::array<double, 3>& center) { center_ = center; }

    // Interaction (pyqtgraph-like sensitivities).
    void orbit(double dx_pixels, double dy_pixels);      // left-drag
    void pan(double dx_pixels, double dy_pixels);        // shift/middle-drag
    void zoom(double wheel_steps);                        // wheel; >0 zooms in
    void frame_bounds(const std::array<double, 3>& lo,
                      const std::array<double, 3>& hi);  // fit-to-objects

    std::array<double, 3> eye() const;

    // Viewport for projection + screen mapping (widget resizeGL keeps this
    // fresh; tests set it explicitly).
    void set_viewport(double width, double height);
    std::pair<double, double> viewport() const { return {width_, height_}; }

    Mat4 view_matrix() const;
    // Perspective with the GLViewWidget-like 60° y-fov; near/far derived
    // from the current distance so pick math and rendering agree.
    Mat4 projection_matrix() const;

    // World point → widget pixel (for text overlays / tests); y in widget
    // space (top-left origin). Returns false when the point is behind the
    // near plane (w <= 0).
    bool project_to_screen(const std::array<double, 3>& world, double& px,
                           double& py) const;

    // screen_point_to_ray bound to the current camera/viewport.
    std::optional<Ray> ray_at(double px, double py) const;

    static CameraPose default_pose() { return {500.0, 30.0, 45.0}; }
    static CameraPose perspective_preset() { return {250.0, 30.0, -45.0}; }
    static CameraPose top_down_preset() { return {250.0, 90.0, 0.0}; }

private:
    CameraPose pose_;
    std::array<double, 3> center_{0.0, 0.0, 0.0};
    double width_ = 800.0;
    double height_ = 600.0;
};

}  // namespace pwb::geo3d_viz
