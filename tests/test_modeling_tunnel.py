import numpy as np
import pytest
from geoviz import TunnelMeshGenerator

def test_tunnel_straight_line():
    trajectory = np.array([
        [0.0, 0.0, 0.0],
        [10.0, 0.0, 0.0]
    ])
    radius = 2.0
    segments = 8
    
    vertices, faces = TunnelMeshGenerator.generate_tube(trajectory, radius, segments)
    
    # 2 points, each has 8 radial points -> 16 vertices total
    assert vertices.shape == (16, 3)
    # (2-1) * 8 * 2 = 16 triangles total
    assert faces.shape == (16, 3)
    
    # First 8 vertices should be on a circle at x=0 in the YZ plane
    for j in range(8):
        v = vertices[j]
        assert np.isclose(v[0], 0.0)
        dist = np.sqrt(v[1]**2 + v[2]**2)
        assert np.isclose(dist, radius)
        
    # Second 8 vertices should be on a circle at x=10 in the YZ plane
    for j in range(8):
        v = vertices[8 + j]
        assert np.isclose(v[0], 10.0)
        dist = np.sqrt(v[1]**2 + v[2]**2)
        assert np.isclose(dist, radius)

def test_tunnel_invalid_parameters():
    # Trajectory with 1 point
    with pytest.raises(ValueError, match="at least 2 points"):
        TunnelMeshGenerator.generate_tube(np.array([[0, 0, 0]]), radius=1.0)
        
    # Negative/zero radius
    with pytest.raises(ValueError, match="Radius must be positive"):
        TunnelMeshGenerator.generate_tube(np.array([[0, 0, 0], [10, 0, 0]]), radius=0.0)
    with pytest.raises(ValueError, match="Radius must be positive"):
        TunnelMeshGenerator.generate_tube(np.array([[0, 0, 0], [10, 0, 0]]), radius=-1.5)
        
    # Segments too small
    with pytest.raises(ValueError, match="at least 3"):
        TunnelMeshGenerator.generate_tube(np.array([[0, 0, 0], [10, 0, 0]]), radius=1.0, segments=2)

def test_tunnel_curved_path():
    # A spiral path
    t = np.linspace(0, 2 * np.pi, 20)
    x = t
    y = np.sin(t)
    z = np.cos(t)
    trajectory = np.column_stack((x, y, z))
    
    radius = 0.5
    segments = 6
    vertices, faces = TunnelMeshGenerator.generate_tube(trajectory, radius, segments)
    
    assert vertices.shape == (20 * 6, 3)
    assert faces.shape == (19 * 6 * 2, 3)
    
    # Check that all vertices are distance radius from the corresponding trajectory point
    for i in range(20):
        P_i = trajectory[i]
        for j in range(6):
            v = vertices[i * 6 + j]
            dist = np.linalg.norm(v - P_i)
            assert np.isclose(dist, radius)

def test_tunnel_winding_order():
    # Check that the winding order of the faces points outwards.
    # We can check this by verifying that for any face, the dot product
    # of the face normal and the vector from the trajectory midpoint to face center is positive.
    trajectory = np.array([
        [0.0, 0.0, 0.0],
        [5.0, 0.0, 0.0]
    ])
    radius = 1.0
    segments = 4
    vertices, faces = TunnelMeshGenerator.generate_tube(trajectory, radius, segments)
    
    for face in faces:
        p0 = vertices[face[0]]
        p1 = vertices[face[1]]
        p2 = vertices[face[2]]
        
        # Face normal (winding order: p0 -> p1 -> p2)
        normal = np.cross(p1 - p0, p2 - p0)
        normal /= np.linalg.norm(normal)
        
        # Center of face
        center = (p0 + p1 + p2) / 3.0
        # Projected midpoint on the trajectory (X axis)
        proj_x = center[0]
        traj_pt = np.array([proj_x, 0.0, 0.0])
        
        # Outward pointing vector
        out_vec = center - traj_pt
        out_vec /= np.linalg.norm(out_vec)
        
        # Winding order is correct if normal points in the same direction as out_vec
        dot = np.dot(normal, out_vec)
        assert dot > 0.5  # Should be close to 1.0 (outwards)
