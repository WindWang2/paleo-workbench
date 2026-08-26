# ISSUE-010: Chinese Character Encoding Corruption in LAS & Well Data Parsers

- **Severity**: High
- **Subproject**: `paleo_workbench` (`paleo_workbench/resources/preview_parsers`)
- **Target File**:
  - `file:///home/kevin/projects/paleo_project/main/paleo_workbench/resources/preview_parsers/well_log_parsers.py#L99-L100`
  - `file:///home/kevin/projects/paleo_project/main/paleo_workbench/resources/well_tops_parser.py#L24`
  - `file:///home/kevin/projects/paleo_project/main/paleo_workbench/viz/joint_well_parsers.py#L35-L37`
  - `file:///home/kevin/projects/paleo_project/main/paleo_workbench/resources/import_service.py#L135`

---

## Defect Description & Root Cause Analysis

In `paleo_workbench/resources/preview_parsers/well_log_parsers.py:99`:
```python
content = path.read_text(encoding="utf-8", errors="replace")
_headers, arr = fast_las_parse_data(content, header.null_value)
```

In Chinese petroleum geological datasets (PetroChina, Sinopec, CNOOC), legacy LAS 2.0 well logs and formation top tables are overwhelmingly encoded in GBK / GB2312 / GB18030.

Opening such files unconditionally with `encoding="utf-8", errors="replace"` corrupts all multi-byte Chinese character sequences (well names such as "达深101", formation names such as "泉头组", horizon comments, and operator names) into Unicode replacement characters (`\ufffd`), permanently destroying data metadata.

While `table_parsers.py` correctly implemented `decode_text_with_fallback()` to handle `utf-8-sig` -> `utf-8` -> `gb18030` -> fallback, `well_log_parsers.py`, `well_tops_parser.py`, and `joint_well_parsers.py` bypassed this utility and used raw `read_text(encoding="utf-8", errors="replace")`.

---

## Impact Analysis

- **Metadata Destruction**: Well names, formation tops, and header descriptions in Chinese well datasets are replaced by garbled strings (`\ufffd\ufffd\ufffd\ufffd101`).
- **Stratigraphic Correlation Failure**: Formation top matching fails because Chinese horizon names cannot be resolved against the project's sequence stratigraphy database.

---

## Reproduction Scenario & Execution Proof

### Verifiable Python Code Execution
```python
from paleo_workbench.resources.preview_parsers.table_parsers import decode_text_with_fallback

chinese_text = "WELL. 达深101 : 井名\nSTRT.M 1000.0 : 起始深度\n"
gbk_bytes = chinese_text.encode("gb18030")

# Buggy behavior:
corrupted = gbk_bytes.decode("utf-8", errors="replace")
print("Corrupted:", repr(corrupted))
assert "\ufffd" in corrupted

# Fixed behavior:
fixed = decode_text_with_fallback(gbk_bytes)
print("Decoded:", repr(fixed))
assert "达深101" in fixed
```

---

## Concrete Suggested Fix

Use `decode_text_with_fallback` on the raw byte content instead of `read_text(encoding="utf-8", errors="replace")`.

### Patch (`paleo_workbench/resources/preview_parsers/well_log_parsers.py`)
```python
from paleo_workbench.resources.preview_parsers.table_parsers import decode_text_with_fallback

# In well_log_parsers.py:
# BEFORE:
# content = path.read_text(encoding="utf-8", errors="replace")

# AFTER:
content = decode_text_with_fallback(path.read_bytes())
```
