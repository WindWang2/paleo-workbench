# ISSUE-015: Missing Character Encoding Fallback in `FormationTopsModel.load_csv`

- **Severity**: Medium
- **Subproject**: `geo-viz-engine` (`geo-viz-engine/packages/geoviz_cross_well`)
- **Target File**:
  - `file:///home/kevin/projects/paleo_project/main/geo-viz-engine/packages/geoviz_cross_well/geoviz_cross_well/tops_model.py#L62`
  - `file:///home/kevin/projects/paleo_project/main/geo-viz-engine/packages/geoviz_cross_well/geoviz_cross_well/seismic_tie.py#L50`

---

## Defect Description & Root Cause Analysis

In `geoviz_cross_well/tops_model.py:62` and `seismic_tie.py:50`, CSV import routines open files with explicit UTF-8 encoding:
```python
with open(path, newline="", encoding="utf-8") as f:
    reader = csv.reader(f)
    # ...
```

In Chinese exploration geological databases, formation tops, checkshots, and well marker CSV tables exported from legacy software (Landmark, GeoFrame, or Excel on Windows) are standardly encoded in GBK / GB18030 / CP936.

Attempting to load any GBK-encoded CSV formation tops table immediately crashes with `UnicodeDecodeError: 'utf-8' codec can't decode byte 0x... in position ...: invalid start byte`.

---

## Impact Analysis

- **Import Crash**: Prevents importing geological formation tops and time-depth tables exported from domestic exploration workflows.
- **Workflow Interruption**: Forces users to manually re-encode CSV files in external text editors before loading into the cross-well canvas.

---

## Reproduction Scenario & Execution Proof

### Code Trace
1. Create a GBK-encoded CSV file:
   ```python
   Path("tops_gbk.csv").write_bytes("井号,层位,顶深\nWell-1,龙马溪组,1200.5\n".encode("gb18030"))
   ```
2. Call `FormationTopsModel.load_csv("tops_gbk.csv")`.
3. Execution fails immediately: `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xbe in position 0: invalid start byte`.

---

## Concrete Suggested Fix

Read file bytes and attempt decoding with an encoding fallback chain (`utf-8-sig`, `utf-8`, `gb18030`, `latin1`):

### Patch (`geo-viz-engine/packages/geoviz_cross_well/geoviz_cross_well/tops_model.py`)
```python
# In FormationTopsModel.load_csv():
raw_bytes = Path(path).read_bytes()
for enc in ("utf-8-sig", "utf-8", "gb18030", "latin1"):
    try:
        text = raw_bytes.decode(enc)
        break
    except UnicodeDecodeError:
        continue
reader = csv.reader(text.splitlines())
```
