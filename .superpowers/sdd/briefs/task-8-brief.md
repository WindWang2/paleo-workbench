### Task 8: UI Screen Inventory Artifact

**Files:**
- Create: `paleo_workbench/ui/__init__.py`
- Create: `paleo_workbench/ui/screen_inventory.py`
- Create: `docs/paleo_workbench_screen_inventory.md`
- Create: `tests/test_project_models.py` update for inventory import

**Interfaces:**
- Produces: `SCREEN_INVENTORY`
- Produces: human-readable inventory document used by UI implementation

- [ ] **Step 1: Write failing inventory import test**

Append to `tests/test_project_models.py`:

```python
from paleo_workbench.ui.screen_inventory import SCREEN_INVENTORY


def test_screen_inventory_includes_required_pages():
    page_ids = {page["id"] for page in SCREEN_INVENTORY["pages"]}

    assert {"dashboard", "data", "visualization", "preparation", "prediction", "paleomap", "qc_export"} <= page_ids
```

- [ ] **Step 2: Run inventory test to verify it fails**

Run:

```bash
python -m pytest tests/test_project_models.py::test_screen_inventory_includes_required_pages -v
```

Expected: FAIL with missing `paleo_workbench.ui`.

- [ ] **Step 3: Implement inventory module**

Create `paleo_workbench/ui/__init__.py`:

```python
from paleo_workbench.ui.screen_inventory import SCREEN_INVENTORY

__all__ = ["SCREEN_INVENTORY"]
```

Create `paleo_workbench/ui/screen_inventory.py`:

```python
SCREEN_INVENTORY = {
    "source": "古地理图编制系统 (standalone).html",
    "tokens": {
        "primary": "#1f6fe0",
        "accent": "#6f47cf",
        "success": "#1f9d57",
        "warning": "#c47e12",
        "surface": "#ffffff",
        "background": "#eef2f7",
    },
    "pages": [
        {"id": "dashboard", "title": "工程工作台", "purpose": "编图任务总览与运行入口"},
        {"id": "data", "title": "多源数据管理与转换", "purpose": "资源扫描、导入、分类、状态管理"},
        {"id": "visualization", "title": "数据可视化", "purpose": "测井、地震、连井、参考资料回溯"},
        {"id": "preparation", "title": "制图数据制备", "purpose": "单因素图任务管理与预览"},
        {"id": "prediction", "title": "沉积相预测", "purpose": "预测任务、证据贡献、待复核区"},
        {"id": "paleomap", "title": "古地理图编制", "purpose": "相带草图、人工编辑、图例样式"},
        {"id": "qc_export", "title": "质控与导出", "purpose": "规则检查、问题处理、成果导出"},
    ],
}
```

- [ ] **Step 4: Create inventory document**

Create `docs/paleo_workbench_screen_inventory.md`:

```markdown
# Paleogeography Workbench Screen Inventory

Source: `古地理图编制系统 (standalone).html`

## Pages

- 工程工作台: target horizon, sequence scheme, resource completeness, factor map status, prediction status, QC blockers, export artifacts.
- 多源数据管理与转换: resource categories, format/status table, conversion options, queue.
- 数据可视化: well log, seismic, cross-well, well-tie, reference document previews.
- 制图数据制备: factor map task cards, map preview, interpolation/method metadata.
- 沉积相预测: input selectors, mock/service adapter status, probability/evidence panels, review areas.
- 古地理图编制: facies polygons, well overlay, legend, north arrow, scale bar, coordinate/grid display.
- 质控与导出: QC rules, issue table, export formats, artifact summary.

## Design Tokens

- Primary: `#1f6fe0`
- Accent: `#6f47cf`
- Success: `#1f9d57`
- Warning: `#c47e12`
- Surface: `#ffffff`
- Background: `#eef2f7`
```

- [ ] **Step 5: Run inventory tests**

Run:

```bash
python -m pytest tests/test_project_models.py::test_screen_inventory_includes_required_pages -v
```

Expected: PASS.

- [ ] **Step 6: Checkpoint or commit**

If root git is repaired, run:

```bash
git add paleo_workbench/ui docs/paleo_workbench_screen_inventory.md tests/test_project_models.py
git commit -m "docs: add paleogeography workbench screen inventory"
```

If root git is still invalid, record checkpoint: `Task 8 complete; root commit pending repository repair`.

---

