from __future__ import annotations

import numpy as np

def check_boreholes(boreholes_data: list[dict]) -> dict:
    """Analyze borehole data for overlaps, invalid coordinates, or depth mismatch.
    
    Format: list of dicts, each having:
      - name: str
      - x: float
      - y: float
      - total_depth: float
      - layers: list of dicts with:
        - top: float
        - bottom: float
        - lithology: str
    """
    issues = []
    checked_count = 0
    for bh in boreholes_data:
        checked_count += 1
        name = bh.get("name", "Unknown")
        x, y = bh.get("x", 0.0), bh.get("y", 0.0)
        td = bh.get("total_depth", 0.0)
        
        # Check invalid coordinates
        if not np.isfinite(x) or not np.isfinite(y):
            issues.append({
                "type": "error",
                "borehole": name,
                "message": f"Invalid coordinates: X={x}, Y={y}"
            })
            
        # Check negative total depth
        if td <= 0:
            issues.append({
                "type": "error",
                "borehole": name,
                "message": f"Non-positive total depth: {td}"
            })
            
        # Check layers
        layers = bh.get("layers", [])
        last_bottom = 0.0
        for idx, layer in enumerate(layers):
            top = layer.get("top", 0.0)
            bottom = layer.get("bottom", 0.0)
            lithology = layer.get("lithology", "Unknown")
            
            # Check overlap or inversion within layer
            if top > bottom:
                issues.append({
                    "type": "error",
                    "borehole": name,
                    "message": f"Layer {idx} ({lithology}) has inverted depths: top={top} > bottom={bottom}"
                })
            
            # Check overlap between consecutive layers
            if top < last_bottom - 1e-5:
                issues.append({
                    "type": "warning",
                    "borehole": name,
                    "message": f"Layer {idx} ({lithology}) top={top} overlaps with previous bottom={last_bottom}"
                })
            last_bottom = max(last_bottom, bottom)
            
        # Check total depth matching
        if last_bottom > td + 1e-5:
            issues.append({
                "type": "warning",
                "borehole": name,
                "message": f"Layers extend to bottom={last_bottom}, exceeding total depth={td}"
            })
            
    return {
        "checked_boreholes": checked_count,
        "issues": issues,
        "status": "PASS" if not any(x["type"] == "error" for x in issues) else "FAIL"
    }


def check_coplanar_faults(faults_data: list[dict]) -> dict:
    """Analyze faults to check if any are coplanar (have very similar orientation and offset).
    
    Format: list of dicts, each having:
      - name: str
      - normal: tuple[float, float, float]  # normal vector (A, B, C) where Ax + By + Cz + D = 0
      - d: float  # offset parameter D
    """
    issues = []
    checked_count = len(faults_data)
    
    for i in range(checked_count):
        for j in range(i + 1, checked_count):
            f1 = faults_data[i]
            f2 = faults_data[j]
            
            n1 = np.array(f1.get("normal", (1.0, 0.0, 0.0)))
            n2 = np.array(f2.get("normal", (1.0, 0.0, 0.0)))
            
            # Normalize vectors
            n1 = n1 / np.linalg.norm(n1)
            n2 = n2 / np.linalg.norm(n2)
            
            d1 = f1.get("d", 0.0)
            d2 = f2.get("d", 0.0)
            
            # Check parallel direction (dot product close to 1 or -1)
            dot = np.dot(n1, n2)
            is_parallel = abs(abs(dot) - 1.0) < 0.05
            
            if is_parallel:
                # If pointing in opposite direction, flip normal and d
                if dot < 0:
                    d2_adj = -d2
                else:
                    d2_adj = d2
                
                # Check if planes are close in distance
                dist_diff = abs(d1 - d2_adj)
                if dist_diff < 15.0:  # Threshold for being close
                    issues.append({
                        "type": "warning",
                        "faults": [f1.get("name"), f2.get("name")],
                        "message": f"Faults {f1.get('name')} and {f2.get('name')} are coplanar. Angle diff: {np.degrees(np.arccos(abs(dot))):.2f}°, Distance diff: {dist_diff:.2f}"
                    })
                    
    return {
        "checked_faults": checked_count,
        "issues": issues,
        "status": "PASS" if not issues else "WARNING"
    }
