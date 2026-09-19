#include <pwb/geo3d_viz/orbit_camera.hpp>

#include <algorithm>
#include <cmath>
#include <limits>

namespace pwb::geo3d_viz {

namespace {
constexpr double kDegToRad = 3.14159265358979323846 / 180.0;
constexpr double kOrbitSensitivity = 0.5;      // deg per pixel
constexpr double kMinDistance = 1e-3;
constexpr double kMaxDistance = 1e9;
constexpr double kFovYDeg = 60.0;

using Vec3 = std::array<double, 3>;

Vec3 normalize(const Vec3& v) {
    const double n = std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    if (n < 1e-12) return {0.0, 0.0, 0.0};
    return {v[0] / n, v[1] / n, v[2] / n};
}

Vec3 cross(const Vec3& a, const Vec3& b) {
    return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]};
}

double dot(const Vec3& a, const Vec3& b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

Vec3 sub3(const Vec3& a, const Vec3& b) {
    return {a[0] - b[0], a[1] - b[1], a[2] - b[2]};
}

// Column-major lookAt (up = world +Z, degraded at the poles to +Y).
Mat4 look_at(const Vec3& eye, const Vec3& center, const Vec3& up) {
    const Vec3 f = normalize(sub3(center, eye));  // forward
    Vec3 up_candidate = up;
    if (std::abs(dot(f, up)) > 0.999) {
        up_candidate = {0.0, 1.0, 0.0};  // looking straight down/up
    }
    const Vec3 s = normalize(cross(f, up_candidate));
    const Vec3 u = cross(s, f);
    Mat4 m{};
    m[0] = static_cast<float>(s[0]);
    m[4] = static_cast<float>(s[1]);
    m[8] = static_cast<float>(s[2]);
    m[12] = static_cast<float>(-dot(s, eye));
    m[1] = static_cast<float>(u[0]);
    m[5] = static_cast<float>(u[1]);
    m[9] = static_cast<float>(u[2]);
    m[13] = static_cast<float>(-dot(u, eye));
    m[2] = static_cast<float>(-f[0]);
    m[6] = static_cast<float>(-f[1]);
    m[10] = static_cast<float>(-f[2]);
    m[14] = static_cast<float>(dot(f, eye));
    m[3] = 0.0f;
    m[7] = 0.0f;
    m[11] = 0.0f;
    m[15] = 1.0f;
    return m;
}

Mat4 perspective(double fov_y_deg, double aspect, double near_z, double far_z) {
    const double f = 1.0 / std::tan(fov_y_deg * kDegToRad / 2.0);
    Mat4 m{};
    m[0] = static_cast<float>(f / aspect);
    m[5] = static_cast<float>(f);
    m[10] = static_cast<float>((far_z + near_z) / (near_z - far_z));
    m[11] = -1.0f;
    m[14] = static_cast<float>((2.0 * far_z * near_z) / (near_z - far_z));
    return m;
}

}  // namespace

OrbitCamera::OrbitCamera() : pose_(default_pose()) {}

void OrbitCamera::set_pose(const CameraPose& pose) {
    pose_.distance = std::clamp(pose.distance, kMinDistance, kMaxDistance);
    pose_.elevation_deg = std::clamp(pose.elevation_deg, -90.0, 90.0);
    // azimuth is free-running (pyqtgraph does not wrap it)
    pose_.azimuth_deg = pose.azimuth_deg;
}

void OrbitCamera::set_pose(double distance, double elevation_deg,
                           double azimuth_deg) {
    set_pose(CameraPose{distance, elevation_deg, azimuth_deg});
}

Vec3 OrbitCamera::eye() const {
    const double elev = pose_.elevation_deg * kDegToRad;
    const double azim = pose_.azimuth_deg * kDegToRad;
    return {center_[0] + pose_.distance * std::cos(elev) * std::sin(azim),
            center_[1] + pose_.distance * std::cos(elev) * std::cos(azim),
            center_[2] + pose_.distance * std::sin(elev)};
}

void OrbitCamera::orbit(double dx_pixels, double dy_pixels) {
    pose_.azimuth_deg += dx_pixels * kOrbitSensitivity;
    pose_.elevation_deg =
        std::clamp(pose_.elevation_deg + dy_pixels * kOrbitSensitivity, -90.0,
                   90.0);
}

void OrbitCamera::pan(double dx_pixels, double dy_pixels) {
    if (height_ <= 0 || width_ <= 0) return;
    const Mat4 view = view_matrix();
    // camera right = row 0 of the rotation part; up = row 1
    const Vec3 right{view[0], view[4], view[8]};
    const Vec3 up{view[1], view[5], view[9]};
    const double world_per_pixel =
        2.0 * pose_.distance * std::tan(kFovYDeg * kDegToRad / 2.0) / height_;
    const Vec3 shift{(-dx_pixels * right[0] + dy_pixels * up[0]) *
                         world_per_pixel,
                     (-dx_pixels * right[1] + dy_pixels * up[1]) *
                         world_per_pixel,
                     (-dx_pixels * right[2] + dy_pixels * up[2]) *
                         world_per_pixel};
    center_ = {center_[0] + shift[0], center_[1] + shift[1],
               center_[2] + shift[2]};
}

void OrbitCamera::zoom(double wheel_steps) {
    // pyqtgraph wheel: each step scales distance by ~0.9^steps.
    const double factor = std::pow(0.9, wheel_steps);
    pose_.distance =
        std::clamp(pose_.distance * factor, kMinDistance, kMaxDistance);
}

void OrbitCamera::frame_bounds(const Vec3& lo, const Vec3& hi) {
    Vec3 diag = sub3(hi, lo);
    const double radius =
        0.5 * std::sqrt(dot(diag, diag) + 1e-12);
    center_ = {(lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0,
               (lo[2] + hi[2]) / 2.0};
    // Keep the current orientation, back off to frame the bounds.
    const double cos_elev = std::cos(pose_.elevation_deg * kDegToRad);
    pose_.distance = std::clamp(
        radius / std::max(cos_elev, 0.2) / std::tan(kFovYDeg * kDegToRad / 2.0) *
            1.2,
        kMinDistance, kMaxDistance);
}

void OrbitCamera::set_viewport(double width, double height) {
    width_ = width;
    height_ = height;
}

Mat4 OrbitCamera::view_matrix() const {
    return look_at(eye(), center_, {0.0, 0.0, 1.0});
}

Mat4 OrbitCamera::projection_matrix() const {
    const double aspect =
        height_ > 0 ? width_ / height_ : 1.0;
    const double near_z = std::max(pose_.distance * 1e-3, 1e-6);
    const double far_z = pose_.distance * 1e3 + 1e6;
    return perspective(kFovYDeg, aspect, near_z, far_z);
}

bool OrbitCamera::project_to_screen(const Vec3& world, double& px,
                                    double& py) const {
    if (width_ <= 0 || height_ <= 0) return false;
    const Mat4 view = view_matrix();
    const Mat4 proj = projection_matrix();
    // clip = proj * view * (p, 1)  (column-major chaining: view then proj)
    const auto apply4 = [](const Mat4& m,
                           const std::array<double, 4>& p) {
        std::array<double, 4> out{};
        for (int row = 0; row < 4; ++row) {
            out[row] = p[0] * m[row] + p[1] * m[4 + row] + p[2] * m[8 + row] +
                       p[3] * m[12 + row];
        }
        return out;
    };
    const std::array<double, 4> eye_p =
        apply4(view, {world[0], world[1], world[2], 1.0});
    if (eye_p[3] <= 0.0) return false;  // behind the eye
    const std::array<double, 4> clip = apply4(proj, eye_p);
    if (clip[3] <= 0.0) return false;  // behind the near plane: no mirror
    const double ndc_x = clip[0] / clip[3];
    const double ndc_y = clip[1] / clip[3];
    px = (ndc_x + 1.0) * 0.5 * width_;
    py = (1.0 - (ndc_y + 1.0) * 0.5) * height_;
    return true;
}

std::optional<Ray> OrbitCamera::ray_at(double px, double py) const {
    return screen_point_to_ray(px, py, width_, height_, view_matrix(),
                               projection_matrix());
}

}  // namespace pwb::geo3d_viz
