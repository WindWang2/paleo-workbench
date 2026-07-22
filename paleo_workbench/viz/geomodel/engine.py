from __future__ import annotations

import numpy as np
import pyqtgraph.opengl as gl
from PySide6.QtGui import QOpenGLContext
from OpenGL import GL

class ClippedGLMeshItem(gl.GLMeshItem):
    """GLMeshItem supporting interactive three-way clipping planes."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clip_x_enabled = False
        self.clip_x_val = 0.0
        self.clip_x_dir = 1.0  # 1.0: clip x > val; -1.0: clip x < val
        
        self.clip_y_enabled = False
        self.clip_y_val = 0.0
        self.clip_y_dir = 1.0
        
        self.clip_z_enabled = False
        self.clip_z_val = 0.0
        self.clip_z_dir = 1.0

    def set_clipping(self, axis: str, enabled: bool, val: float, direction: float = 1.0):
        if axis == 'x':
            self.clip_x_enabled = enabled
            self.clip_x_val = val
            self.clip_x_dir = direction
        elif axis == 'y':
            self.clip_y_enabled = enabled
            self.clip_y_val = val
            self.clip_y_dir = direction
        elif axis == 'z':
            self.clip_z_enabled = enabled
            self.clip_z_val = val
            self.clip_z_dir = direction
        self.update()

    def paint(self):
        ctx = QOpenGLContext.currentContext()
        if ctx is None:
            super().paint()
            return
            
        planes_to_disable = []
        if self.clip_x_enabled:
            GL.glEnable(GL.GL_CLIP_PLANE0)
            GL.glClipPlane(GL.GL_CLIP_PLANE0, (-self.clip_x_dir, 0.0, 0.0, self.clip_x_val * self.clip_x_dir))
            planes_to_disable.append(GL.GL_CLIP_PLANE0)
            
        if self.clip_y_enabled:
            GL.glEnable(GL.GL_CLIP_PLANE1)
            GL.glClipPlane(GL.GL_CLIP_PLANE1, (0.0, -self.clip_y_dir, 0.0, self.clip_y_val * self.clip_y_dir))
            planes_to_disable.append(GL.GL_CLIP_PLANE1)
            
        if self.clip_z_enabled:
            GL.glEnable(GL.GL_CLIP_PLANE2)
            GL.glClipPlane(GL.GL_CLIP_PLANE2, (0.0, 0.0, -self.clip_z_dir, self.clip_z_val * self.clip_z_dir))
            planes_to_disable.append(GL.GL_CLIP_PLANE2)
            
        try:
            super().paint()
        finally:
            for plane in planes_to_disable:
                GL.glDisable(plane)


class ClippedGLVolumeItem(gl.GLVolumeItem):
    """GLVolumeItem supporting interactive three-way clipping planes."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clip_x_enabled = False
        self.clip_x_val = 0.0
        self.clip_x_dir = 1.0
        
        self.clip_y_enabled = False
        self.clip_y_val = 0.0
        self.clip_y_dir = 1.0
        
        self.clip_z_enabled = False
        self.clip_z_val = 0.0
        self.clip_z_dir = 1.0

    def set_clipping(self, axis: str, enabled: bool, val: float, direction: float = 1.0):
        if axis == 'x':
            self.clip_x_enabled = enabled
            self.clip_x_val = val
            self.clip_x_dir = direction
        elif axis == 'y':
            self.clip_y_enabled = enabled
            self.clip_y_val = val
            self.clip_y_dir = direction
        elif axis == 'z':
            self.clip_z_enabled = enabled
            self.clip_z_val = val
            self.clip_z_dir = direction
        self.update()

    def paint(self):
        ctx = QOpenGLContext.currentContext()
        if ctx is None:
            super().paint()
            return
            
        planes_to_disable = []
        if self.clip_x_enabled:
            GL.glEnable(GL.GL_CLIP_PLANE0)
            GL.glClipPlane(GL.GL_CLIP_PLANE0, (-self.clip_x_dir, 0.0, 0.0, self.clip_x_val * self.clip_x_dir))
            planes_to_disable.append(GL.GL_CLIP_PLANE0)
            
        if self.clip_y_enabled:
            GL.glEnable(GL.GL_CLIP_PLANE1)
            GL.glClipPlane(GL.GL_CLIP_PLANE1, (0.0, -self.clip_y_dir, 0.0, self.clip_y_val * self.clip_y_dir))
            planes_to_disable.append(GL.GL_CLIP_PLANE1)
            
        if self.clip_z_enabled:
            GL.glEnable(GL.GL_CLIP_PLANE2)
            GL.glClipPlane(GL.GL_CLIP_PLANE2, (0.0, 0.0, -self.clip_z_dir, self.clip_z_val * self.clip_z_dir))
            planes_to_disable.append(GL.GL_CLIP_PLANE2)
            
        try:
            super().paint()
        finally:
            for plane in planes_to_disable:
                GL.glDisable(plane)


def generate_cylinder_geometry(p1, p2, radius=2.0, color=(1.0, 0.0, 0.0, 1.0), resolution=12) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calculate cylinder mesh vertices, faces, and colors (thread-safe, no Qt/GL dependencies)."""
    p1 = np.array(p1, dtype=np.float32)
    p2 = np.array(p2, dtype=np.float32)
    v = p2 - p1
    length = np.linalg.norm(v)
    if length == 0:
        return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.int32), np.zeros((0, 4), dtype=np.float32)
        
    v_norm = v / length
    if abs(v_norm[0]) < 0.9:
        ortho1 = np.cross(v_norm, [1.0, 0.0, 0.0])
    else:
        ortho1 = np.cross(v_norm, [0.0, 1.0, 0.0])
    ortho1 = ortho1 / np.linalg.norm(ortho1)
    ortho2 = np.cross(v_norm, ortho1)
    
    vertices = []
    faces = []
    
    # Generate vertices around cylinder tube
    for i in range(resolution):
        theta = 2 * np.pi * i / resolution
        c = np.cos(theta) * radius
        s = np.sin(theta) * radius
        offset = c * ortho1 + s * ortho2
        vertices.append(p1 + offset)
        vertices.append(p2 + offset)
        
    # Cap centers
    vertices.append(p1)
    vertices.append(p2)
    idx_p1 = len(vertices) - 2
    idx_p2 = len(vertices) - 1
    
    # Generate faces
    for i in range(resolution):
        next_i = (i + 1) % resolution
        faces.append([2*i, 2*next_i, 2*i+1])
        faces.append([2*next_i, 2*next_i+1, 2*i+1])
        # Caps
        faces.append([idx_p1, 2*next_i, 2*i])
        faces.append([idx_p2, 2*i+1, 2*next_i+1])
        
    verts = np.array(vertices, dtype=np.float32)
    faces = np.array(faces, dtype=np.int32)
    colors = np.tile(color, (len(faces), 1)).astype(np.float32)
    
    return verts, faces, colors


def generate_tube_geometry(path, radius=3.0, color=(0.8, 0.8, 0.8, 1.0), resolution=12) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calculate sweeping tube mesh vertices, faces, and colors (thread-safe, no Qt/GL dependencies)."""
    path = [np.array(p, dtype=np.float32) for p in path]
    if len(path) < 2:
        return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.int32), np.zeros((0, 4), dtype=np.float32)
        
    vertices = []
    faces = []
    
    for j, p in enumerate(path):
        if j == 0:
            tangent = path[1] - path[0]
        elif j == len(path) - 1:
            tangent = path[-1] - path[-2]
        else:
            tangent = path[j+1] - path[j-1]
        
        tang_len = np.linalg.norm(tangent)
        if tang_len == 0:
            tangent = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        else:
            tangent = tangent / tang_len
            
        if abs(tangent[0]) < 0.9:
            ortho1 = np.cross(tangent, [1.0, 0.0, 0.0])
        else:
            ortho1 = np.cross(tangent, [0.0, 1.0, 0.0])
        ortho1 = ortho1 / np.linalg.norm(ortho1)
        ortho2 = np.cross(tangent, ortho1)
        
        for i in range(resolution):
            theta = 2 * np.pi * i / resolution
            c = np.cos(theta) * radius
            s = np.sin(theta) * radius
            vertices.append(p + c * ortho1 + s * ortho2)
            
    num_slices = len(path)
    for j in range(num_slices - 1):
        slice_start = j * resolution
        next_slice_start = (j + 1) * resolution
        for i in range(resolution):
            next_i = (i + 1) % resolution
            p0 = slice_start + i
            p1 = slice_start + next_i
            p2 = next_slice_start + i
            p3 = next_slice_start + next_i
            faces.append([p0, p1, p2])
            faces.append([p1, p3, p2])
            
    verts = np.array(vertices, dtype=np.float32)
    faces = np.array(faces, dtype=np.int32)
    colors = np.tile(color, (len(faces), 1)).astype(np.float32)
    
    return verts, faces, colors


def generate_fault_geometry(xlim=(-100, 100), ylim=(-100, 100), nx=40, ny=40, color=(0.1, 0.6, 0.8, 0.8)) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calculate faulted surface mesh vertices, faces, and colors (thread-safe, no Qt/GL dependencies)."""
    xs = np.linspace(xlim[0], xlim[1], nx)
    ys = np.linspace(ylim[0], ylim[1], ny)
    X, Y = np.meshgrid(xs, ys)
    
    # Gently sloping dome Z shape
    Z = 15.0 * np.sin(X / 50.0) * np.cos(Y / 50.0)
    
    # Add fault throw offset: Fault line Y = 0.5 * X + 10.0
    fault_mask = Y > (0.5 * X + 10.0)
    Z[fault_mask] += 25.0
    
    vertices = []
    for r in range(ny):
        for c in range(nx):
            vertices.append([X[r, c], Y[r, c], Z[r, c]])
            
    faces = []
    for r in range(ny - 1):
        for c in range(nx - 1):
            v0 = r * nx + c
            v1 = r * nx + c + 1
            v2 = (r + 1) * nx + c
            v3 = (r + 1) * nx + c + 1
            faces.append([v0, v1, v2])
            faces.append([v1, v3, v2])
            
    verts = np.array(vertices, dtype=np.float32)
    faces = np.array(faces, dtype=np.int32)
    colors = np.tile(color, (len(faces), 1)).astype(np.float32)
    
    return verts, faces, colors


def create_cylinder_mesh(p1, p2, radius=2.0, color=(1.0, 0.0, 0.0, 1.0), resolution=12) -> ClippedGLMeshItem:
    """Convenience helper to create a ClippedGLMeshItem cylinder directly (must run on Qt GUI thread)."""
    v, f, c = generate_cylinder_geometry(p1, p2, radius, color, resolution)
    return ClippedGLMeshItem(vertexes=v, faces=f, faceColors=c, smooth=True)


def create_tube_mesh(path, radius=3.0, color=(0.8, 0.8, 0.8, 1.0), resolution=12) -> ClippedGLMeshItem:
    """Convenience helper to create a ClippedGLMeshItem sweeping tube directly (must run on Qt GUI thread)."""
    v, f, c = generate_tube_geometry(path, radius, color, resolution)
    return ClippedGLMeshItem(vertexes=v, faces=f, faceColors=c, smooth=True)


def create_faulted_surface(xlim=(-100, 100), ylim=(-100, 100), nx=40, ny=40, color=(0.1, 0.6, 0.8, 0.8)) -> ClippedGLMeshItem:
    """Convenience helper to create a ClippedGLMeshItem faulted surface directly (must run on Qt GUI thread)."""
    v, f, c = generate_fault_geometry(xlim, ylim, nx, ny, color)
    return ClippedGLMeshItem(vertexes=v, faces=f, faceColors=c, smooth=True)
