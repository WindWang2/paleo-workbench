# P5：Marching Tetrahedra 等值面 + 相干性 C3 接入 3D 视图 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用真正的 Marching Tetrahedra 重写 `marching_cubes_3d`（替换点汤实现），经注入模式把等值面接入引擎 3D 视图（工具栏控件），并把引擎 C3 相干性接入属性下拉。

**Architecture:** 算法在 workbench 的 C++ 扩展 `seismic_3d_core`；引擎出 `set_isosurface` 渲染 API + 模块级注入钩子（与 P4-A downsample 钩子同模式）+ SeismicView 工具栏控件；workbench 启动时经 `geoviz` facade 注入 C++ 提取器。C3 接入只是在 `attribute_pipeline.ATTRIBUTES` 追加一条目。

**Tech Stack:** C++17 / pybind11 / NumPy / PySide6 / pyqtgraph.opengl / pytest + pytest-qt。

## Global Constraints

- 不引入新第三方依赖；scikit-image 保持可选 import，绝不成为硬依赖。
- 引擎零反向依赖：geo-viz-engine 内不得 import workbench 或 native 模块；注入只走 `geoviz` facade。
- workbench 生产代码只准 `from geoviz import ...`（守卫测试 `tests/test_geoviz_package_independence.py` 的 `GEOVIZ_PUBLIC_FACADE` 白名单可扩展）。
- 接口签名（后续任务互相依赖，逐字遵守）：
  - `marching_cubes_3d(volume, isovalue=0.0) -> (verts float32 [N,3], faces int32 [M,3])`（voxel 索引坐标，签名不变）。
  - `geoviz_seismic/isosurface.py`：`set_isosurface_extractor(fn)` / `get_isosurface_extractor()`；`fn(volume: np.ndarray, isovalue: float) -> (verts, faces)`。
  - `Renderer3D.set_isosurface(verts, faces, color=(0.9, 0.5, 0.1, 0.8))`、`Renderer3D.clear_isosurface()`、`Renderer3D.volume_data() -> np.ndarray | None`。
- 提交目标：引擎仓库 main 与 workbench 仓库 main。**workbench 主工作区当前被并行会话切在 `feature/3d-geological-modeling`（有未提交改动）——workbench 侧一切编辑/提交在临时 worktree 执行**：`git worktree add .worktrees/p5-main main`，用完 `git worktree remove --force .worktrees/p5-main`；绝不在主工作区切分支。引擎仓库在 main 上，直接操作。
- pytest：workbench 用 `/home/kevin/projects/paleo_project/.venv/bin/python -m pytest`；引擎用 `cd /home/kevin/projects/paleo_project/geo-viz-engine && ../.venv/bin/python -m pytest tests -q`。
- C++ 重建（worktree 内对主工作区同源生效，因为 editable install 指向主工作区路径——在主工作区执行）：`/home/kevin/projects/paleo_project/.venv/bin/python -m pip install -e native/seismic_3d_core --no-build-isolation -q`。
- 回归基线：workbench 1175 全绿（已知顺序 flake：`test_project_lifecycle.py` 3 变体、`test_workflow_controller_api.py` 1 个，单独复跑通过即可）；引擎 112 通过 +1 既有失败 `test_curve_track_viewport_culling` +1 skip（pyvistaqt 缺失的既有 skip）。引擎 worker 测试文件退出时 exit 134 为既有问题，与本计划无关。
- 已知坐标事实：`Renderer3D.load_volume(data, origin, spacing)` 存 `_volume_data_cpu/_volume_origin/_volume_spacing`；bbox/层位均用物理坐标（index×spacing+origin）。等值面 mesh 必须在 `set_isosurface` 内部做 `verts * spacing + origin` 变换。

---

### Task 1: C++ Marching Tetrahedra 重写 + Python 保底清理（workbench）

**Files:**
- Modify: `native/seismic_3d_core/src/seismic_3d_core.cpp:209-256`（点汤实现）
- Modify: `paleo_workbench/viz/seismic_3d_api.py:104-128`（wrapper + 删除点汤降级）
- Modify: `docs/superpowers/specs/2026-07-22-p5-marching-cubes-isosurface-design.md`（算法决策更新）
- Test: `tests/test_seismic_3d_api.py`、`tests/test_seismic_3d_cpp.py`

**Interfaces:**
- Consumes: 无。
- Produces: `marching_cubes_3d(volume, isovalue=0.0) -> (verts float32 [N,3], faces int32 [M,3])`（voxel 索引坐标）；Task 4 把它注入引擎。

- [ ] **Step 1: 写失败测试**

在 `tests/test_seismic_3d_api.py` 末尾追加：

```python
def _sphere_volume() -> np.ndarray:
    x, y, z = np.ogrid[:20, :20, :20]
    return (25.0 - ((x - 10) ** 2 + (y - 10) ** 2 + (z - 10) ** 2)).astype(np.float32)


def test_marching_cubes_3d_sphere_surface_radius():
    vol = _sphere_volume()
    verts, faces = marching_cubes_3d(vol, isovalue=0.0)
    assert verts.shape[0] > 0 and faces.shape[0] > 0
    dist = np.linalg.norm(
        verts.astype(np.float64) - np.array([10.0, 10.0, 10.0]), axis=1
    )
    # 真实等值面顶点必须落在 r=5 球面附近；点汤实现含内部格点会失败
    assert np.all(dist >= 4.5)
    assert np.all(dist <= 5.5)


def test_marching_cubes_3d_faces_within_bounds():
    vol = _sphere_volume()
    verts, faces = marching_cubes_3d(vol, isovalue=0.0)
    assert faces.min() >= 0
    assert faces.max() < verts.shape[0]


def test_marching_cubes_3d_sphere_mesh_is_watertight():
    from collections import Counter

    vol = _sphere_volume()
    verts, faces = marching_cubes_3d(vol, isovalue=0.0)
    # 无顶点去重：先按坐标（1e-4 量化）归并再统计棱共享次数
    keys = np.round(verts.astype(np.float64), decimals=4)
    _uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    faces_u = inv[faces]
    edge_count: Counter = Counter()
    for a, b, c in faces_u:
        for e in ((a, b), (b, c), (c, a)):
            edge_count[tuple(sorted((int(e[0]), int(e[1]))))] += 1
    assert edge_count, "mesh is empty"
    assert all(v == 2 for v in edge_count.values())


def test_marching_cubes_3d_empty_when_threshold_out_of_range():
    vol = _sphere_volume()
    verts, faces = marching_cubes_3d(vol, isovalue=1.0e9)
    assert verts.shape == (0, 3)
    assert faces.shape == (0, 3)


def test_marching_cubes_3d_parity_with_skimage():
    skm = pytest.importorskip("skimage.measure")
    vol = _sphere_volume()
    verts_cpp, faces_cpp = marching_cubes_3d(vol, isovalue=0.0)
    verts_sk, faces_sk, _n, _v = skm.marching_cubes(vol, level=0.0)
    # 算法不同（tetra vs lewiner），只验顶点数同量级与 bbox 一致
    assert 0.5 < verts_cpp.shape[0] / max(1, verts_sk.shape[0]) < 4.0
    np.testing.assert_allclose(verts_cpp.min(axis=0), verts_sk.min(axis=0), atol=0.6)
    np.testing.assert_allclose(verts_cpp.max(axis=0), verts_sk.max(axis=0), atol=0.6)
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/kevin/projects/paleo_project/.venv/bin/python -m pytest tests/test_seismic_3d_api.py -q -k marching`
Expected: `test_marching_cubes_3d_sphere_surface_radius` FAIL（点汤顶点含 r<4.5 的内部格点）；`test_marching_cubes_3d_sphere_mesh_is_watertight` FAIL（点汤棱不闭合）；parity 用例 skip（skimage 未装）。

- [ ] **Step 3: 替换 C++ 实现**

将 `native/seismic_3d_core/src/seismic_3d_core.cpp` 中 `// 3D Marching Cubes Isosurface Mesh Extraction` 注释起的整个 `marching_cubes_3d` 函数（209-256 行）替换为：

```cpp
// 3D Isosurface Mesh Extraction via Marching Tetrahedra.
// Each cube is split into 6 tetrahedra around the body diagonal corner0->corner7.
// The face diagonals of this decomposition are consistent between axis-aligned
// neighbour cubes, so the resulting mesh is watertight by construction.
// Corner index layout: corner n -> offset (n&1, (n>>1)&1, (n>>2)&1).
py::tuple marching_cubes_3d(py::array_t<float, py::array::c_style | py::array::forcecast> input, float isovalue) {
    auto buf = input.request();
    if (buf.ndim != 3) {
        throw std::runtime_error("Input volume must be 3D");
    }

    size_t ni = buf.shape[0];
    size_t nx = buf.shape[1];
    size_t nt = buf.shape[2];
    const float* src = static_cast<const float*>(buf.ptr);

    static const int TETS[6][4] = {
        {0, 1, 3, 7}, {0, 1, 5, 7}, {0, 4, 5, 7},
        {0, 4, 6, 7}, {0, 2, 6, 7}, {0, 2, 3, 7},
    };
    static const int TET_EDGES[6][2] = {
        {0, 1}, {0, 2}, {0, 3}, {1, 2}, {1, 3}, {2, 3},
    };

    std::vector<float> verts;
    std::vector<int> faces;

    {
        py::gil_scoped_release release;
        for (size_t i = 0; i + 1 < ni; ++i) {
            for (size_t j = 0; j + 1 < nx; ++j) {
                for (size_t k = 0; k + 1 < nt; ++k) {
                    float cv[8];
                    float cp[8][3];
                    for (int c = 0; c < 8; ++c) {
                        size_t ci = i + (c & 1);
                        size_t cj = j + ((c >> 1) & 1);
                        size_t ck = k + ((c >> 2) & 1);
                        cv[c] = src[ci * (nx * nt) + cj * nt + ck];
                        cp[c][0] = static_cast<float>(ci);
                        cp[c][1] = static_cast<float>(cj);
                        cp[c][2] = static_cast<float>(ck);
                    }
                    int cube_mask = 0;
                    for (int c = 0; c < 8; ++c) {
                        if (cv[c] >= isovalue) cube_mask |= (1 << c);
                    }
                    if (cube_mask == 0 || cube_mask == 0xFF) continue;

                    for (const auto& tet : TETS) {
                        int tmask = 0;
                        for (int c = 0; c < 4; ++c) {
                            if (cube_mask & (1 << tet[c])) tmask |= (1 << c);
                        }
                        if (tmask == 0 || tmask == 0xF) continue;

                        // Interpolated intersection point per cut edge.
                        float pt[6][3];
                        bool cut[6] = {};
                        int n_cut = 0;
                        for (int e = 0; e < 6; ++e) {
                            int a = TET_EDGES[e][0];
                            int b = TET_EDGES[e][1];
                            bool ina = (tmask >> a) & 1;
                            bool inb = (tmask >> b) & 1;
                            if (ina == inb) continue;
                            int ca = tet[a], cb = tet[b];
                            float t = (isovalue - cv[ca]) / (cv[cb] - cv[ca]);
                            for (int d = 0; d < 3; ++d) {
                                pt[e][d] = cp[ca][d] + t * (cp[cb][d] - cp[ca][d]);
                            }
                            cut[e] = true;
                            ++n_cut;
                        }

                        // Centroid of inside corners (for outward orientation).
                        float ci[3] = {0.0f, 0.0f, 0.0f};
                        int n_inside = 0;
                        for (int c = 0; c < 4; ++c) {
                            if ((tmask >> c) & 1) {
                                ++n_inside;
                                for (int d = 0; d < 3; ++d) ci[d] += cp[tet[c]][d];
                            }
                        }
                        for (int d = 0; d < 3; ++d) ci[d] /= n_inside;

                        // Collect cut points in a deterministic order.
                        int tri_src[4];
                        int nq = 0;
                        if (n_inside == 2) {
                            // Quad: inside pair (a,b), outside pair (c,d) ->
                            // cycle p(a-c), p(a-d), p(b-d), p(b-c).
                            int ins[2], out[2], ni_ = 0, no_ = 0;
                            for (int c = 0; c < 4; ++c) {
                                if ((tmask >> c) & 1) ins[ni_++] = c; else out[no_++] = c;
                            }
                            auto edge_idx = [&](int x, int y) {
                                for (int e = 0; e < 6; ++e) {
                                    if ((TET_EDGES[e][0] == x && TET_EDGES[e][1] == y) ||
                                        (TET_EDGES[e][0] == y && TET_EDGES[e][1] == x)) return e;
                                }
                                return -1;
                            };
                            tri_src[0] = edge_idx(ins[0], out[0]);
                            tri_src[1] = edge_idx(ins[0], out[1]);
                            tri_src[2] = edge_idx(ins[1], out[1]);
                            tri_src[3] = edge_idx(ins[1], out[0]);
                            nq = 4;
                        } else {
                            // n_inside == 1 or 3: exactly 3 cut edges.
                            for (int e = 0; e < 6 && nq < 3; ++e) {
                                if (cut[e]) tri_src[nq++] = e;
                            }
                        }

                        int n_tris = (nq == 4) ? 2 : 1;
                        for (int t = 0; t < n_tris; ++t) {
                            int i0 = tri_src[(t == 0) ? 0 : 0];
                            int i1 = tri_src[(t == 0) ? 1 : 2];
                            int i2 = tri_src[(t == 0) ? 2 : 3];
                            float v0[3], v1[3], v2[3];
                            for (int d = 0; d < 3; ++d) {
                                v0[d] = pt[i0][d]; v1[d] = pt[i1][d]; v2[d] = pt[i2][d];
                            }
                            // Orient the normal away from the inside-centroid.
                            float e1[3] = {v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]};
                            float e2[3] = {v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]};
                            float nrm[3] = {
                                e1[1] * e2[2] - e1[2] * e2[1],
                                e1[2] * e2[0] - e1[0] * e2[2],
                                e1[0] * e2[1] - e1[1] * e2[0],
                            };
                            float ctr[3] = {(v0[0] + v1[0] + v2[0]) / 3.0f - ci[0],
                                            (v0[1] + v1[1] + v2[1]) / 3.0f - ci[1],
                                            (v0[2] + v1[2] + v2[2]) / 3.0f - ci[2]};
                            int base = static_cast<int>(verts.size() / 3);
                            if (nrm[0] * ctr[0] + nrm[1] * ctr[1] + nrm[2] * ctr[2] < 0.0f) {
                                faces.push_back(base);
                                faces.push_back(base + 2);
                                faces.push_back(base + 1);
                            } else {
                                faces.push_back(base);
                                faces.push_back(base + 1);
                                faces.push_back(base + 2);
                            }
                            for (int d = 0; d < 3; ++d) {
                                verts.push_back(v0[d]);
                            }
                            for (int d = 0; d < 3; ++d) {
                                verts.push_back(v1[d]);
                            }
                            for (int d = 0; d < 3; ++d) {
                                verts.push_back(v2[d]);
                            }
                        }
                    }
                }
            }
        }
    }

    size_t num_verts = verts.size() / 3;
    size_t num_faces = faces.size() / 3;

    auto r_verts = py::array_t<float>({num_verts, size_t(3)});
    auto r_faces = py::array_t<int>({num_faces, size_t(3)});

    std::copy(verts.begin(), verts.end(), static_cast<float*>(r_verts.request().ptr));
    std::copy(faces.begin(), faces.end(), static_cast<int*>(r_faces.request().ptr));

    return py::make_tuple(r_verts, r_faces);
}
```

（pybind 绑定行 `m.def("marching_cubes_3d", ...)` 不变。）

- [ ] **Step 4: 改 Python 保底**

将 `paleo_workbench/viz/seismic_3d_api.py` 的 `marching_cubes_3d` 整函数（104-128 行）替换为：

```python
def marching_cubes_3d(
    volume: np.ndarray,
    isovalue: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract 3D isosurface mesh (vertices, faces) at isovalue.

    C++ path uses marching tetrahedra (watertight). Falls back to
    scikit-image when available; raises ImportError otherwise.
    """
    if HAS_CPP_SEISMIC and hasattr(seismic_3d_core, "marching_cubes_3d"):
        return seismic_3d_core.marching_cubes_3d(volume, float(isovalue))

    try:
        from skimage.measure import marching_cubes
    except ImportError as exc:
        raise ImportError(
            "marching_cubes_3d requires the seismic_3d_core C++ extension "
            "or scikit-image"
        ) from exc

    verts, faces, _normals, _values = marching_cubes(volume, level=float(isovalue))
    return verts.astype(np.float32), faces.astype(np.int32)
```

- [ ] **Step 5: 更新 spec 算法决策**

`docs/superpowers/specs/2026-07-22-p5-marching-cubes-isosurface-design.md`：
- 「已确认决策」表第一行 `C++ 自研完整 MC（公共域查找表），不引新依赖` 改为 `C++ 自研 Marching Tetrahedra（水密、无外部查找表），不引新依赖`。
- 范围第 1 条中 `经典 Lorensen-Cline MC + 公共域查找表（edgeTable/triTable，含 MC33 歧义修正）；逐 cube 8 角点建 case index，棱上线性插值；计算段释放 GIL。` 改为 `Marching Tetrahedra：逐 cube 剖 6 四面体（主对角线分解，邻接面对角线一致，天然水密），棱上线性插值，法线统一朝外；计算段释放 GIL。`
- 同条中 `顶点坐标为 voxel 索引坐标——与引擎层位 mesh 同坐标系，叠加无需变换。` 改为 `输出 voxel 索引坐标；`Renderer3D.set_isosurface` 内部按 volume spacing/origin 变换到物理坐标后叠加。`

- [ ] **Step 6: 重建 + 运行测试**

Run: `/home/kevin/projects/paleo_project/.venv/bin/python -m pip install -e native/seismic_3d_core --no-build-isolation -q`
Expected: 无错误输出。

Run: `/home/kevin/projects/paleo_project/.venv/bin/python -m pytest tests/test_seismic_3d_api.py tests/test_seismic_3d_cpp.py -q`
Expected: 全部 PASS（parity 用例 skip 属预期）。

- [ ] **Step 7: Commit（worktree 流程）**

```bash
cd /home/kevin/projects/paleo_project
git worktree add .worktrees/p5-main main
cd .worktrees/p5-main
cp ../../native/seismic_3d_core/src/seismic_3d_core.cpp native/seismic_3d_core/src/
cp ../../paleo_workbench/viz/seismic_3d_api.py paleo_workbench/viz/
cp ../../tests/test_seismic_3d_api.py tests/
cp ../../docs/superpowers/specs/2026-07-22-p5-marching-cubes-isosurface-design.md docs/superpowers/specs/
git add native/seismic_3d_core/src/seismic_3d_core.cpp paleo_workbench/viz/seismic_3d_api.py tests/test_seismic_3d_api.py docs/superpowers/specs/2026-07-22-p5-marching-cubes-isosurface-design.md
git commit -m "feat(seismic): rewrite marching_cubes_3d as watertight marching tetrahedra"
cd /home/kevin/projects/paleo_project
git worktree remove --force .worktrees/p5-main
```

注意：实现编辑直接做主工作区（`native/`、`paleo_workbench/`、`tests/`、`docs/` 都不受 feature 分支脏区影响——先 `git status` 确认这些路径无并行会话改动，若有则停下来上报）；提交时按上面把文件复制进 worktree。

---

### Task 2: 引擎等值面渲染 API + 注入钩子（geo-viz-engine）

**Files:**
- Create: `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/isosurface.py`
- Modify: `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/renderer_3d.py`（`__init__` ~739-748、`_clear_visuals` 1184-1239、Public API 区 ~982 `remove_horizon` 之后）
- Modify: `geo-viz-engine/geoviz/__init__.py:65-68`（`_COMPATIBILITY_EXPORTS` 追加）
- Test: `geo-viz-engine/tests/test_isosurface.py`（新建）

**Interfaces:**
- Consumes: Task 1 的提取器签名 `fn(volume, isovalue) -> (verts, faces)`（本任务用假提取器测试，不依赖 Task 1 产物）。
- Produces: `set_isosurface_extractor(fn)` / `get_isosurface_extractor()`（模块级 + facade 导出）；`Renderer3D.set_isosurface(verts, faces, color=(0.9, 0.5, 0.1, 0.8))`、`clear_isosurface()`、`volume_data()`。Task 3、4 依赖。

- [ ] **Step 1: 写失败测试**

新建 `geo-viz-engine/tests/test_isosurface.py`：

```python
from __future__ import annotations

import numpy as np
import pytest

from geoviz_seismic import isosurface as iso_mod
from geoviz_seismic.renderer_3d import Renderer3D


@pytest.fixture(autouse=True)
def _reset_extractor():
    iso_mod.set_isosurface_extractor(None)
    yield
    iso_mod.set_isosurface_extractor(None)


def _renderer(qtbot):
    r = Renderer3D()
    qtbot.addWidget(r)
    vol = np.random.default_rng(0).standard_normal((8, 8, 8)).astype(np.float32)
    r.load_volume(vol)
    return r


def test_extractor_hook_set_get():
    fn = lambda vol, iso: (np.zeros((0, 3), np.float32), np.zeros((0, 3), np.int32))
    iso_mod.set_isosurface_extractor(fn)
    assert iso_mod.get_isosurface_extractor() is fn
    iso_mod.set_isosurface_extractor(None)
    assert iso_mod.get_isosurface_extractor() is None


def test_set_and_clear_isosurface(qtbot):
    r = _renderer(qtbot)
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    faces = np.array([[0, 1, 2]], dtype=np.int32)
    r.set_isosurface(verts, faces)
    assert r._isosurface_item is not None
    assert r._isosurface_item in r._view.items
    r.clear_isosurface()
    assert r._isosurface_item is None
    assert all(type(it).__name__ != "GLMeshItem" or it not in r._view.items for it in [])


def test_set_isosurface_replaces_previous(qtbot):
    r = _renderer(qtbot)
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    faces = np.array([[0, 1, 2]], dtype=np.int32)
    r.set_isosurface(verts, faces)
    first = r._isosurface_item
    r.set_isosurface(verts, faces)
    assert r._isosurface_item is not None
    assert r._isosurface_item is not first
    assert first not in r._view.items


def test_set_isosurface_empty_mesh_is_noop(qtbot):
    r = _renderer(qtbot)
    r.set_isosurface(np.zeros((0, 3), np.float32), np.zeros((0, 3), np.int32))
    assert r._isosurface_item is None


def test_isosurface_cleared_on_new_volume(qtbot):
    r = _renderer(qtbot)
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    faces = np.array([[0, 1, 2]], dtype=np.int32)
    r.set_isosurface(verts, faces)
    r.load_volume(np.zeros((4, 4, 4), dtype=np.float32))
    assert r._isosurface_item is None


def test_isosurface_scaled_by_spacing(qtbot):
    r = Renderer3D()
    qtbot.addWidget(r)
    vol = np.random.default_rng(0).standard_normal((8, 8, 8)).astype(np.float32)
    r.load_volume(vol, origin=(0, 0, 0), spacing=(2.0, 1.0, 3.0))
    verts = np.array([[1, 1, 1]], dtype=np.float32)
    faces = np.array([[0, 0, 0]], dtype=np.int32)
    r.set_isosurface(verts, faces)
    md = r._isosurface_item.meshData()
    np.testing.assert_allclose(md.vertexes()[0], [2.0, 1.0, 3.0], atol=1e-6)


def test_volume_data_accessor(qtbot):
    r = _renderer(qtbot)
    assert isinstance(r.volume_data(), np.ndarray)
    empty = Renderer3D()
    qtbot.addWidget(empty)
    assert empty.volume_data() is None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /home/kevin/projects/paleo_project/geo-viz-engine && ../.venv/bin/python -m pytest tests/test_isosurface.py -q`
Expected: 收集失败/ImportError（`geoviz_seismic.isosurface` 不存在）。

- [ ] **Step 3: 新建注入钩子模块**

新建 `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/isosurface.py`：

```python
"""Isosurface extractor hook installed by the host application.

The engine cannot depend on the host's native extensions; the workbench
injects its C++ marching-tetrahedra implementation at startup via
``set_isosurface_extractor`` (same pattern as the well-log downsample hook).
"""
from __future__ import annotations

from typing import Callable

import numpy as np

ExtractorFn = Callable[[np.ndarray, float], "tuple[np.ndarray, np.ndarray]"]

_extractor: ExtractorFn | None = None


def set_isosurface_extractor(fn: ExtractorFn | None) -> None:
    """Install (or clear, with None) the isosurface extraction provider."""
    global _extractor
    _extractor = fn


def get_isosurface_extractor() -> ExtractorFn | None:
    """Return the installed isosurface extraction provider, or None."""
    return _extractor
```

- [ ] **Step 4: Renderer3D API**

`renderer_3d.py`：
1. `__init__` 中 `self._sculpt_mode = "above"`（~747 行）之后加一行：`self._isosurface_item = None`
2. `_clear_visuals`（1184 行起）末尾（`self._annotation_items = []` 之后）加一行：`self.clear_isosurface()`
3. `remove_horizon` 方法（980-982 行）之后插入：

```python
    def volume_data(self) -> np.ndarray | None:
        """Return the CPU volume array currently loaded, or None."""
        return self._volume_data_cpu

    def set_isosurface(self, verts: np.ndarray, faces: np.ndarray,
                       color=(0.9, 0.5, 0.1, 0.8)):
        """Render an isosurface mesh (voxel-index coords), replacing any previous one."""
        self.clear_isosurface()
        if verts is None or faces is None or len(verts) == 0 or len(faces) == 0:
            return
        si, sx, st = self._volume_spacing
        oi, ox, ot = self._volume_origin
        v = np.asarray(verts, dtype=np.float32).copy()
        v[:, 0] = v[:, 0] * si + oi
        v[:, 1] = v[:, 1] * sx + ox
        v[:, 2] = v[:, 2] * st + ot
        mesh = gl.GLMeshItem(
            vertexes=v,
            faces=np.asarray(faces, dtype=np.int32),
            color=color,
            shader='shaded',
            smooth=True,
        )
        self._isosurface_item = mesh
        self._view.addItem(mesh)
        self._view.update()

    def clear_isosurface(self):
        """Remove the isosurface mesh if present."""
        if self._isosurface_item is not None:
            try:
                self._view.removeItem(self._isosurface_item)
            except Exception:
                pass
            self._isosurface_item = None
```

- [ ] **Step 5: facade 导出**

`geo-viz-engine/geoviz/__init__.py` 的 `_COMPATIBILITY_EXPORTS` 中，`"numpy_minmax_downsample"` 一行之后追加：

```python
    # Isosurface extractor hook installed by the workbench at startup.
    "set_isosurface_extractor": ("geoviz_seismic.isosurface", "set_isosurface_extractor"),
    "get_isosurface_extractor": ("geoviz_seismic.isosurface", "get_isosurface_extractor"),
```

- [ ] **Step 6: 运行测试**

Run: `cd /home/kevin/projects/paleo_project/geo-viz-engine && ../.venv/bin/python -m pytest tests/test_isosurface.py tests/test_renderer_3d.py -q`
Expected: 全部 PASS。

- [ ] **Step 7: Commit（引擎仓库，直接在 main）**

```bash
cd /home/kevin/projects/paleo_project/geo-viz-engine
git add packages/geoviz_seismic/geoviz_seismic/isosurface.py packages/geoviz_seismic/geoviz_seismic/renderer_3d.py geoviz/__init__.py tests/test_isosurface.py
git commit -m "feat(seismic): isosurface render API + extractor injection hook"
```

---

### Task 3: SeismicView 等值面工具栏控件（geo-viz-engine）

**Files:**
- Modify: `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/seismic_view.py`（工具栏构建 ~603-610 之后、row2 装配 ~765-766、新增处理器方法）
- Test: `geo-viz-engine/tests/test_isosurface.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 `set_isosurface` / `clear_isosurface` / `volume_data()` / `get_isosurface_extractor()`。
- Produces: `SeismicView._iso_checkbox`、`_iso_spin`、`_iso_timer`、`_refresh_isosurface_controls()`、`_on_isosurface_toggled(bool)`、`_on_isosurface_threshold_changed(float)`、`_rebuild_isosurface()`。

- [ ] **Step 1: 写失败测试**

`geo-viz-engine/tests/test_isosurface.py` 末尾追加：

```python
from geoviz_seismic.seismic_view import SeismicView


def _view(qtbot):
    v = SeismicView(auto_load=False)
    qtbot.addWidget(v)
    vol = np.random.default_rng(1).standard_normal((8, 8, 8)).astype(np.float32)
    v._renderer_3d.load_volume(vol)
    return v


def test_isosurface_controls_disabled_without_extractor(qtbot):
    v = _view(qtbot)
    v._refresh_isosurface_controls()
    assert not v._iso_checkbox.isEnabled()
    assert not v._iso_spin.isEnabled()


def test_isosurface_controls_enabled_with_extractor(qtbot):
    iso_mod.set_isosurface_extractor(
        lambda vol, iso: (np.zeros((0, 3), np.float32), np.zeros((0, 3), np.int32))
    )
    v = _view(qtbot)
    v._refresh_isosurface_controls()
    assert v._iso_checkbox.isEnabled()
    assert v._iso_spin.isEnabled()


def test_isosurface_toggle_extracts_and_clears(qtbot):
    calls = []

    def fake(vol, iso):
        calls.append(iso)
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        return verts, np.array([[0, 1, 2]], dtype=np.int32)

    iso_mod.set_isosurface_extractor(fake)
    v = _view(qtbot)
    v._refresh_isosurface_controls()
    v._iso_checkbox.setChecked(True)
    qtbot.wait(350)  # debounce 200ms
    assert len(calls) == 1
    assert v._renderer_3d._isosurface_item is not None
    v._iso_checkbox.setChecked(False)
    assert v._renderer_3d._isosurface_item is None


def test_isosurface_threshold_debounce(qtbot):
    calls = []

    def fake(vol, iso):
        calls.append(iso)
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        return verts, np.array([[0, 1, 2]], dtype=np.int32)

    iso_mod.set_isosurface_extractor(fake)
    v = _view(qtbot)
    v._refresh_isosurface_controls()
    v._iso_checkbox.setChecked(True)
    qtbot.wait(350)
    assert len(calls) == 1
    v._iso_spin.setValue(v._iso_spin.value() + 0.01)
    v._iso_spin.setValue(v._iso_spin.value() + 0.01)
    qtbot.wait(350)
    assert len(calls) == 2  # 两次快速改动合并为一次提取


def test_isosurface_extractor_error_unchecks(qtbot):
    def boom(vol, iso):
        raise RuntimeError("extraction failed")

    iso_mod.set_isosurface_extractor(boom)
    v = _view(qtbot)
    v._refresh_isosurface_controls()
    v._iso_checkbox.setChecked(True)
    qtbot.wait(350)
    assert not v._iso_checkbox.isChecked()
    assert v._renderer_3d._isosurface_item is None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /home/kevin/projects/paleo_project/geo-viz-engine && ../.venv/bin/python -m pytest tests/test_isosurface.py -q -k "controls or toggle or debounce or error"`
Expected: FAIL（`_refresh_isosurface_controls` 等不存在）。

- [ ] **Step 3: 实现控件与处理器**

`seismic_view.py`：
1. 顶部 import 区确认 `QTimer`、`QCheckBox` 已导入（`from PySide6.QtCore import ... QTimer`、`from PySide6.QtWidgets import ... QCheckBox`），缺则补进现有 import 列表。
2. `self._clip_spin...valueChanged.connect(self._on_clip_changed)`（603-610 行）之后插入：

```python
        self._iso_checkbox = QCheckBox(" 等值面")
        self._iso_checkbox.setEnabled(False)
        self._iso_checkbox.toggled.connect(self._on_isosurface_toggled)
        self._iso_spin = QDoubleSpinBox()
        self._iso_spin.setDecimals(3)
        self._iso_spin.setFixedWidth(90)
        self._iso_spin.setEnabled(False)
        self._iso_spin.valueChanged.connect(self._on_isosurface_threshold_changed)
        self._iso_timer = QTimer(self)
        self._iso_timer.setSingleShot(True)
        self._iso_timer.setInterval(200)
        self._iso_timer.timeout.connect(self._rebuild_isosurface)
```

3. row2 装配处 `bar2.addWidget(self._clip_spin)`（~766 行）之后追加：

```python
        bar2.addSeparator()
        bar2.addWidget(self._iso_checkbox)
        bar2.addWidget(self._iso_spin)
```

4. 找到数据加载后启用工具条滑杆的方法（grep `_tb_il_slider.setEnabled(True)`，同一方法内）追加一行调用：`self._refresh_isosurface_controls()`。
5. 新增方法（放在 `_on_opacity_changed` 之后）：

```python
    def _refresh_isosurface_controls(self):
        from .isosurface import get_isosurface_extractor

        vol = self._renderer_3d.volume_data()
        ok = vol is not None and get_isosurface_extractor() is not None
        self._iso_checkbox.setEnabled(ok)
        self._iso_spin.setEnabled(ok)
        if not ok:
            self._iso_checkbox.setToolTip("等值面不可用（未注入提取器或未加载数据）")
            if self._iso_checkbox.isChecked():
                self._iso_checkbox.setChecked(False)
            return
        self._iso_checkbox.setToolTip("")
        vmin = float(np.nanmin(vol))
        vmax = float(np.nanmax(vol))
        self._iso_spin.blockSignals(True)
        self._iso_spin.setRange(vmin, vmax)
        self._iso_spin.setSingleStep((vmax - vmin) / 100.0 if vmax > vmin else 1.0)
        self._iso_spin.setValue((vmin + vmax) / 2.0)
        self._iso_spin.blockSignals(False)

    def _on_isosurface_toggled(self, checked: bool):
        if checked:
            self._iso_timer.start()
        else:
            self._iso_timer.stop()
            self._renderer_3d.clear_isosurface()

    def _on_isosurface_threshold_changed(self, _value: float):
        if self._iso_checkbox.isChecked():
            self._iso_timer.start()

    def _rebuild_isosurface(self):
        from .isosurface import get_isosurface_extractor

        extractor = get_isosurface_extractor()
        vol = self._renderer_3d.volume_data()
        if extractor is None or vol is None or not self._iso_checkbox.isChecked():
            return
        try:
            verts, faces = extractor(vol, float(self._iso_spin.value()))
        except Exception:
            logger.warning("isosurface extraction failed", exc_info=True)
            self._renderer_3d.clear_isosurface()
            self._iso_checkbox.setChecked(False)
            return
        self._renderer_3d.set_isosurface(verts, faces)
```

（`logger`：文件顶部若已有 `logger = logging.getLogger(__name__)` 直接用；没有则补 `import logging` 与该定义。）

- [ ] **Step 4: 运行测试**

Run: `cd /home/kevin/projects/paleo_project/geo-viz-engine && ../.venv/bin/python -m pytest tests/test_isosurface.py tests/test_seismic_view.py -q`
Expected: 全部 PASS（test_seismic_view.py 既有失败/skip 保持原状不算回归，对比基线）。

- [ ] **Step 5: Commit**

```bash
cd /home/kevin/projects/paleo_project/geo-viz-engine
git add packages/geoviz_seismic/geoviz_seismic/seismic_view.py tests/test_isosurface.py
git commit -m "feat(seismic): isosurface toolbar controls with debounced extraction"
```

---

### Task 4: workbench 注入接线 + facade 白名单（workbench）

**Files:**
- Modify: `paleo_workbench/viz/render_accel.py`
- Modify: `tests/test_geoviz_package_independence.py:79-81`（白名单）
- Test: `tests/test_render_accel.py`（存在则扩展，不存在则新建）

**Interfaces:**
- Consumes: Task 1 的 `marching_cubes_3d`；Task 2 的 facade `set_isosurface_extractor`。
- Produces: 启动注入后 `geoviz.get_isosurface_extractor()` 返回 workbench 的 `marching_cubes_3d`。

- [ ] **Step 1: 写失败测试**

若 `tests/test_render_accel.py` 不存在则新建，否则追加：

```python
from __future__ import annotations

import geoviz
from paleo_workbench.viz import render_accel
from paleo_workbench.viz.seismic_3d_api import marching_cubes_3d


def test_install_injects_isosurface_extractor():
    render_accel._installed_provider = None  # reset idempotence guard
    render_accel.install_geoviz_acceleration()
    assert geoviz.get_isosurface_extractor() is marching_cubes_3d


def test_install_is_idempotent():
    render_accel._installed_provider = None
    render_accel.install_geoviz_acceleration()
    first = geoviz.get_isosurface_extractor()
    render_accel.install_geoviz_acceleration()
    assert geoviz.get_isosurface_extractor() is first
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/kevin/projects/paleo_project/.venv/bin/python -m pytest tests/test_render_accel.py -q`
Expected: FAIL（`geoviz` 无 `get_isosurface_extractor` 属性或注入未安装）。

- [ ] **Step 3: 实现注入**

`paleo_workbench/viz/render_accel.py` 的 `install_geoviz_acceleration` 改为：

```python
def install_geoviz_acceleration() -> None:
    """Inject the C++ providers into geoviz (idempotent)."""
    global _installed_provider
    if _installed_provider is not None:
        return
    from geoviz import set_downsample_provider, set_isosurface_extractor

    from paleo_workbench.viz.seismic_3d_api import marching_cubes_3d

    set_downsample_provider(_cpp_minmax_provider)
    set_isosurface_extractor(marching_cubes_3d)
    _installed_provider = _cpp_minmax_provider
```

`tests/test_geoviz_package_independence.py` 白名单中 `"numpy_minmax_downsample",` 一行之后追加：

```python
        "set_isosurface_extractor",
        "get_isosurface_extractor",
```

- [ ] **Step 4: 运行测试**

Run: `/home/kevin/projects/paleo_project/.venv/bin/python -m pytest tests/test_render_accel.py tests/test_geoviz_package_independence.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: Commit（worktree 流程，同 Task 1 Step 7）**

```bash
cd /home/kevin/projects/paleo_project
git worktree add .worktrees/p5-main main
cd .worktrees/p5-main
cp ../../paleo_workbench/viz/render_accel.py paleo_workbench/viz/
cp ../../tests/test_geoviz_package_independence.py tests/
cp ../../tests/test_render_accel.py tests/ 2>/dev/null || true
git add paleo_workbench/viz/render_accel.py tests/test_geoviz_package_independence.py tests/test_render_accel.py
git commit -m "feat(viz): inject C++ isosurface extractor into geoviz at startup"
cd /home/kevin/projects/paleo_project
git worktree remove --force .worktrees/p5-main
```

（若 Task 1 之后 main 已前移，worktree add 会自动基于最新 main；先 `git status` 确认这三个路径无并行会话改动。）

---

### Task 5: 相干性 C3 接入属性管线（geo-viz-engine）

**Files:**
- Modify: `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/attribute_pipeline.py:69-86`
- Test: `geo-viz-engine/tests/test_attribute_pipeline.py`（存在则扩展，不存在则新建）

**Interfaces:**
- Consumes: 现有 `attributes.compute_coherence_c3(data, win_il=5, win_xl=5, win_t=5, use_gpu=False)`（接受 2-D `(n_xl, n_samples)` 切片，返回同形状 [0,1]）。
- Produces: `ATTRIBUTES` 新增条目 `AttributeSpec("相干性(C3)", "curvature", _attr.compute_coherence_c3)`（`"curvature"` kind 的 dispatch 正是 `spec.compute(data)`，语义为"2-D 切片进、2-D 场出"，与 C3 匹配）。

- [ ] **Step 1: 写失败测试**

`geo-viz-engine/tests/test_attribute_pipeline.py`（新建或追加）：

```python
from __future__ import annotations

import numpy as np

from geoviz_seismic import attribute_pipeline as ap


def test_coherence_c3_in_labels():
    assert "相干性(C3)" in ap.labels()


def test_coherence_c3_apply_slice():
    idx = ap.labels().index("相干性(C3)")
    rng = np.random.default_rng(0)
    data = rng.standard_normal((16, 32)).astype(np.float32)
    out = ap.apply(idx, data)
    assert out.shape == data.shape
    assert float(np.nanmin(out)) >= 0.0
    assert float(np.nanmax(out)) <= 1.0


def test_coherence_c3_high_for_smooth_data():
    idx = ap.labels().index("相干性(C3)")
    x = np.linspace(0, 4 * np.pi, 32, dtype=np.float32)
    data = np.tile(np.sin(x), (16, 1))
    out = ap.apply(idx, data)
    assert float(np.nanmean(out)) > 0.5
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /home/kevin/projects/paleo_project/geo-viz-engine && ../.venv/bin/python -m pytest tests/test_attribute_pipeline.py -q`
Expected: FAIL（`相干性(C3)` 不在 labels 中）。

- [ ] **Step 3: 实现（一行）**

`attribute_pipeline.py` 的 `ATTRIBUTES` 中，`AttributeSpec("最大曲率", "curvature", _curvature_max),` 一行之后追加：

```python
    AttributeSpec("相干性(C3)", "curvature", _attr.compute_coherence_c3),
```

- [ ] **Step 4: 运行测试**

Run: `cd /home/kevin/projects/paleo_project/geo-viz-engine && ../.venv/bin/python -m pytest tests/test_attribute_pipeline.py tests/test_coherence.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
cd /home/kevin/projects/paleo_project/geo-viz-engine
git add packages/geoviz_seismic/geoviz_seismic/attribute_pipeline.py tests/test_attribute_pipeline.py
git commit -m "feat(seismic): expose C3 coherence in attribute pipeline"
```

---

### Task 6: 双仓库回归 + 文档 + gitlink（workbench）

**Files:**
- Modify: `progress.md`（追加 P5 记录）、`task_plan.md`（追加 Phase 16）
- Modify: workbench 的 `geo-viz-engine` gitlink（随引擎提交前移）

**Interfaces:**
- Consumes: Task 1-5 全部提交。
- Produces: 无代码接口。

- [ ] **Step 1: 引擎全量回归**

Run: `cd /home/kevin/projects/paleo_project/geo-viz-engine && ../.venv/bin/python -m pytest tests -q 2>&1 | tail -5`
Expected: 通过数 ≥ 基线 112 + 新增用例；既有失败仅 `test_curve_track_viewport_culling`；pyvistaqt skip 保持。

- [ ] **Step 2: workbench 全量回归（main worktree）**

```bash
cd /home/kevin/projects/paleo_project
git worktree add .worktrees/p5-main main
cd .worktrees/p5-main
git submodule update --init geo-viz-engine
PYTHONPATH=$PWD /home/kevin/projects/paleo_project/.venv/bin/python -m pytest tests -q 2>&1 | tail -5
```
Expected: 全绿（已知顺序 flake 单独复跑确认）。

- [ ] **Step 3: gitlink 前移 + 文档**

worktree 内：
```bash
cd /home/kevin/projects/paleo_project/.worktrees/p5-main
git add geo-viz-engine
```
`task_plan.md` 在最后一个 Phase 之后追加：

```markdown
### Phase 16: P5 等值面与相干性 3D 接入

- [x] `marching_cubes_3d` 重写为 Marching Tetrahedra（水密，替换点汤实现），Python 保底去点汤改 skimage/ImportError
- [x] 引擎 `Renderer3D.set_isosurface` + `geoviz_seismic.isosurface` 注入钩子 + facade 导出
- [x] SeismicView 等值面工具栏控件（checkbox + 阈值 + 200ms 防抖）
- [x] workbench 启动注入 C++ 提取器（`render_accel`）
- [x] 相干性 C3 接入属性下拉（`attribute_pipeline`）
- **Status:** complete
```

`progress.md` 在 `## Session Log` 最新条目处追加：

```markdown
- **P5 等值面 + 相干性 3D 接入（2026-07-22）**：`marching_cubes_3d` 重写为 Marching Tetrahedra（6 四面体主对角线分解、邻接面一致、法线朝外，水密无孔洞；球面半径/封闭性/空阈值语义测试）；引擎新增 `set_isosurface` 渲染 API（GLMeshItem，spacing/origin 变换）与 `isosurface` 注入钩子（仿 downsample 模式），SeismicView 工具栏等值面 checkbox + 阈值 spinbox（200ms 防抖、异常自动取消勾选）；workbench `render_accel` 启动注入 C++ 提取器；相干性 C3 经 `attribute_pipeline` 接入属性下拉。
```

```bash
git add geo-viz-engine task_plan.md progress.md
git commit -m "docs: record P5 isosurface/coherence completion and bump engine gitlink"
git log --oneline -3
cd /home/kevin/projects/paleo_project
git worktree remove --force .worktrees/p5-main
```

---

## Self-Review 结论

- **Spec 覆盖**：spec 范围 4 条 → Task 1（MC 重写+保底+spec 措辞同步）、Task 2+3（渲染 API+钩子+UI）、Task 4（注入+白名单）、Task 5（C3）；测试策略各条分散在对应 Task Step 1；文档/gitlink/回归 → Task 6。无遗漏。
- **Placeholder 扫描**：无 TBD；所有代码与命令完整。两处"先 grep 定位再插入"（Task 3 Step 3-4 的滑杆启用位置、logger 存在性）已给出精确搜索串与两种情形的处理。
- **类型一致性**：`marching_cubes_3d` / `set_isosurface_extractor` / `get_isosurface_extractor` / `set_isosurface` / `clear_isosurface` / `volume_data` 签名在 Global Constraints 与各 Task Interfaces 中逐字一致；facade 导出与白名单条目同名。
- **已知取舍**：顶点不去重（spec 非目标）；水密性测试用 1e-4 坐标量化归并顶点；skimage parity 用例在本环境 skip（可选依赖）。
