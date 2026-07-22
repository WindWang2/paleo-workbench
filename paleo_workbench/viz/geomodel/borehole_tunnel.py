import numpy as np

def get_seam_boundaries(well_data: dict) -> tuple[float, float, float, float]:
    """Extract seam 1 and seam 3 boundaries (top and bottom elevations) from well data.
    
    Tries flat fields first: seam_1_top, seam_1_bottom, seam_3_top, seam_3_bottom.
    Tries nested 'seams' dictionary next:
        {
            "seams": {
                "seam 1": {"top": ..., "bottom": ...},
                "seam 3": {"top": ..., "bottom": ...}
            }
        }
    Falls back to standard defaults if missing.
    """
    s1_top = well_data.get("seam_1_top")
    s1_bot = well_data.get("seam_1_bottom")
    s3_top = well_data.get("seam_3_top")
    s3_bot = well_data.get("seam_3_bottom")
    
    seams = well_data.get("seams", {})
    if s1_top is None:
        s1_top = seams.get("seam 1", {}).get("top")
    if s1_bot is None:
        s1_bot = seams.get("seam 1", {}).get("bottom")
    if s3_top is None:
        s3_top = seams.get("seam 3", {}).get("top")
    if s3_bot is None:
        s3_bot = seams.get("seam 3", {}).get("bottom")
        
    s1_top = s1_top if s1_top is not None else 0.0
    s1_bot = s1_bot if s1_bot is not None else -10.0
    s3_top = s3_top if s3_top is not None else -100.0
    s3_bot = s3_bot if s3_bot is not None else -110.0
    
    return float(s1_top), float(s1_bot), float(s3_top), float(s3_bot)


class BoreholeTraceGenerator:
    @staticmethod
    def generate_segments(wells_data: list[dict]) -> list[dict]:
        """Segments the borehole trajectories of wells based on seam 1 and seam 3 boundaries.
        
        Parameters
        ----------
        wells_data : list[dict]
            List of dictionaries containing well trajectory and seam boundary information.
            Each dict should have:
            - 'id' or 'name': str
            - 'trajectory': array-like of shape (N, 3) representing [x, y, z] points.
            - Optional seam boundaries (seam_1_top, seam_1_bottom, seam_3_top, seam_3_bottom)
            
        Returns
        -------
        list[dict]
            List of dictionaries (one per well) with keys:
            - 'well_id': str
            - 'segments': list[dict]
                Each segment has:
                - 'type': str, one of:
                    "above_seam_1"
                    "seam_1"
                    "between_seam_1_and_3"
                    "seam_3"
                    "below_seam_3"
                - 'points': np.ndarray of shape (M, 3) representing the segment points.
        """
        results = []
        for well in wells_data:
            well_id = well.get("id") or well.get("name") or "unknown"
            raw_trajectory = well.get("trajectory")
            if raw_trajectory is None or len(raw_trajectory) < 2:
                results.append({
                    "well_id": well_id,
                    "segments": []
                })
                continue
                
            trajectory = np.array(raw_trajectory, dtype=np.float64)
            
            # Clean consecutive duplicate points to avoid divide-by-zero or zero-length segments
            cleaned_traj = [trajectory[0]]
            for pt in trajectory[1:]:
                if not np.allclose(pt, cleaned_traj[-1]):
                    cleaned_traj.append(pt)
            trajectory = np.array(cleaned_traj, dtype=np.float64)
            
            if len(trajectory) < 2:
                results.append({
                    "well_id": well_id,
                    "segments": []
                })
                continue
                
            s1_top, s1_bot, s3_top, s3_bot = get_seam_boundaries(well)
            Z_boundaries = [s1_top, s1_bot, s3_top, s3_bot]
            
            # Insert intersections with boundary planes
            P_new = [trajectory[0]]
            for i in range(len(trajectory) - 1):
                p_start = trajectory[i]
                p_end = trajectory[i+1]
                z_start = p_start[2]
                z_end = p_end[2]
                
                crossed = []
                for Z in Z_boundaries:
                    if min(z_start, z_end) < Z < max(z_start, z_end):
                        crossed.append(Z)
                
                # Sort in the direction of traversal
                if z_end > z_start:
                    crossed.sort()  # Ascending
                else:
                    crossed.sort(reverse=True)  # Descending
                    
                for Z in crossed:
                    t = (Z - z_start) / (z_end - z_start)
                    p_interp = p_start + t * (p_end - p_start)
                    P_new.append(p_interp)
                
                P_new.append(p_end)
                
            # Classify and group segments
            segments = []
            current_type = None
            current_points = []
            
            for i in range(len(P_new) - 1):
                p0 = P_new[i]
                p1 = P_new[i+1]
                z_mid = (p0[2] + p1[2]) / 2.0
                
                # Classify zone based on midpoint
                if z_mid >= s1_top:
                    seg_type = "above_seam_1"
                elif s1_bot <= z_mid < s1_top:
                    seg_type = "seam_1"
                elif s3_top <= z_mid < s1_bot:
                    seg_type = "between_seam_1_and_3"
                elif s3_bot <= z_mid < s3_top:
                    seg_type = "seam_3"
                else:
                    seg_type = "below_seam_3"
                    
                if current_type is None:
                    current_type = seg_type
                    current_points = [p0, p1]
                elif seg_type == current_type:
                    current_points.append(p1)
                else:
                    segments.append({
                        "type": current_type,
                        "points": np.array(current_points, dtype=np.float64)
                    })
                    current_type = seg_type
                    current_points = [p0, p1]
                    
            if current_type is not None:
                segments.append({
                    "type": current_type,
                    "points": np.array(current_points, dtype=np.float64)
                })
                
            results.append({
                "well_id": well_id,
                "segments": segments
            })
            
        return results


class TunnelMeshGenerator:
    @staticmethod
    def generate_tube(trajectory: np.ndarray, radius: float, segments: int = 8) -> tuple[np.ndarray, np.ndarray]:
        """Generates a 3D tube/cylinder mesh around a 3D trajectory curve.
        
        Using a Rotation Minimizing Frame (RMF) to avoid sudden twists along the curve.
        
        Parameters
        ----------
        trajectory : np.ndarray of shape (N, 3)
            The 3D trajectory path points.
        radius : float
            The radius of the tube. Must be positive.
        segments : int, optional
            Number of radial segments around the tube circle (default 8). Must be >= 3.
            
        Returns
        -------
        vertices : np.ndarray of shape (N * segments, 3)
            The coordinates of the generated mesh vertices.
        faces : np.ndarray of shape ((N - 1) * segments * 2, 3)
            The face indices of the mesh triangles. Winding is oriented outwards.
        """
        trajectory = np.array(trajectory, dtype=np.float64)
        if len(trajectory.shape) != 2 or trajectory.shape[1] != 3:
            raise ValueError("Trajectory must be a 2D array of shape (N, 3).")
            
        N_pts = len(trajectory)
        if N_pts < 2:
            raise ValueError("Trajectory must have at least 2 points.")
            
        if radius <= 0:
            raise ValueError("Radius must be positive.")
            
        if segments < 3:
            raise ValueError("Segments must be at least 3 to form a valid 3D tube shape.")
            
        # 1. Compute tangent vectors along the curve
        tangents = np.zeros((N_pts, 3), dtype=np.float64)
        tangents[0] = trajectory[1] - trajectory[0]
        tangents[-1] = trajectory[-1] - trajectory[-2]
        for i in range(1, N_pts - 1):
            tangents[i] = trajectory[i+1] - trajectory[i-1]
            
        # Normalize tangents
        norms = np.linalg.norm(tangents, axis=1, keepdims=True)
        # Avoid division by zero for zero-length segments
        norms = np.where(norms < 1e-12, 1.0, norms)
        tangents = tangents / norms
        
        # 2. Compute starting frame (N_0, B_0) at trajectory[0]
        T_0 = tangents[0]
        # Choose a reference vector V not parallel to T_0
        if abs(T_0[0]) < 0.9 and abs(T_0[1]) < 0.9:
            V = np.array([1.0, 0.0, 0.0], dtype=np.float64)
        else:
            V = np.array([0.0, 0.0, 1.0], dtype=np.float64)
            
        N_0 = V - np.dot(V, T_0) * T_0
        N_0_norm = np.linalg.norm(N_0)
        if N_0_norm < 1e-12:
            # Absolute fallback
            V = np.array([0.123, 0.456, 0.789], dtype=np.float64)
            N_0 = V - np.dot(V, T_0) * T_0
            N_0_norm = np.linalg.norm(N_0)
            
        N_0 /= N_0_norm
        B_0 = np.cross(T_0, N_0)
        B_0 /= np.linalg.norm(B_0)
        
        # 3. Propagate the normal and binormal vectors using Double Reflection Method
        normals = np.zeros((N_pts, 3), dtype=np.float64)
        binormals = np.zeros((N_pts, 3), dtype=np.float64)
        
        normals[0] = N_0
        binormals[0] = B_0
        
        for i in range(1, N_pts):
            x_prev = trajectory[i-1]
            x_curr = trajectory[i]
            T_prev = tangents[i-1]
            T_curr = tangents[i]
            N_prev = normals[i-1]
            
            v1 = x_curr - x_prev
            c1 = np.dot(v1, v1)
            if c1 > 1e-12:
                # First reflection
                N_L = N_prev - (2.0 / c1) * np.dot(v1, N_prev) * v1
                T_L = T_prev - (2.0 / c1) * np.dot(v1, T_prev) * v1
                
                # Second reflection
                v2 = T_curr - T_L
                c2 = np.dot(v2, v2)
                if c2 > 1e-12:
                    N_curr = N_L - (2.0 / c2) * np.dot(v2, N_L) * v2
                else:
                    N_curr = N_L
            else:
                N_curr = N_prev
                
            N_curr_norm = np.linalg.norm(N_curr)
            if N_curr_norm < 1e-12:
                N_curr = N_prev
            else:
                N_curr /= N_curr_norm
                
            # Re-orthogonalize to T_curr to prevent accumulation of drift
            N_curr = N_curr - np.dot(N_curr, T_curr) * T_curr
            N_curr /= np.linalg.norm(N_curr)
            
            B_curr = np.cross(T_curr, N_curr)
            B_curr /= np.linalg.norm(B_curr)
            
            normals[i] = N_curr
            binormals[i] = B_curr
            
        # 4. Generate radial vertices
        theta = np.linspace(0, 2 * np.pi, segments, endpoint=False)
        cos_t = np.cos(theta)
        sin_t = np.sin(theta)
        
        vertices = np.zeros((N_pts * segments, 3), dtype=np.float64)
        for i in range(N_pts):
            P_i = trajectory[i]
            N_i = normals[i]
            B_i = binormals[i]
            
            for j in range(segments):
                vertices[i * segments + j] = P_i + radius * (cos_t[j] * N_i + sin_t[j] * B_i)
                
        # 5. Generate faces
        faces = np.zeros(((N_pts - 1) * segments * 2, 3), dtype=np.int32)
        face_idx = 0
        for i in range(N_pts - 1):
            for j in range(segments):
                idx0 = i * segments + j
                idx1 = (i + 1) * segments + j
                idx2 = (i + 1) * segments + (j + 1) % segments
                idx3 = i * segments + (j + 1) % segments
                
                # Triangle 1
                faces[face_idx] = [idx0, idx2, idx1]
                face_idx += 1
                # Triangle 2
                faces[face_idx] = [idx0, idx3, idx2]
                face_idx += 1
                
        return vertices, faces
